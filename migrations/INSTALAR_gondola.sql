-- ═══════════════════════════════════════════════════════════════════
--  SADIMEX — LECTOR DE GÓNDOLA
--  Instalación completa de la base de datos
-- ═══════════════════════════════════════════════════════════════════
--
--  CÓMO USARLO
--  1. Abre Supabase → SQL Editor → New query
--  2. Pega TODO este archivo
--  3. Run
--
--  Es seguro correrlo más de una vez: todo usa IF NOT EXISTS o
--  CREATE OR REPLACE, así que no duplica ni borra nada existente.
--
--  Va dentro de una transacción: si algo falla, no queda nada a medias.
--
--  QUÉ CREA
--    · 8 tablas nuevas (cadenas, salas, catálogo, precios, reglas,
--      pesos, cola de fotos, resultados)
--    · El rol `reponedor` en sadimex_profiles
--    · Políticas RLS con el mismo aislamiento por ciudad que el resto
--      del sistema: un supervisor de CBBA no ve datos de LPZ
--    · 7 vistas de reporte (ranking de reponedores, salud de salas,
--      precios vigentes, SKU sin precio, cobertura del catálogo,
--      costos diarios, efecto del consenso)
--    · 2 funciones: reclamar foto de la cola y cargar precios
--    · Las 4 cadenas: Fidalga, Hipermaxi, Tía, IC Norte
--
--  NO TOCA nada del módulo de audio que ya está en producción.
--
--  DESPUÉS DE ESTO
--    · Crear el bucket `gondola-fotos` en Storage (Supabase → Storage)
--    · Cargar el catálogo y las salas
-- ═══════════════════════════════════════════════════════════════════

BEGIN;



-- -------------------------------------------------------------------
--  PARTE 1 — Estructura, permisos y cola de trabajo
--  (origen: migrations/003_gondola_schema.sql)
-- -------------------------------------------------------------------

-- =====================================================
-- SADIMEX — Lector de Góndola (Retail Execution)
-- Migration: 003_gondola_schema.sql
-- =====================================================
-- Módulo independiente del pipeline de audio. Comparte la
-- misma base y el mismo modelo de acceso por ciudad.
--
-- Convención de acceso (idéntica al resto del sistema):
--   reponedor  -> ve solo lo suyo
--   supervisor -> ve solo su ciudad
--   gerente    -> ve todo (solo lectura)
--   admin      -> administra catálogo, salas y reglas
-- Los INSERT los hace el worker con service_role (bypassea RLS).
-- =====================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- ROL NUEVO: reponedor
-- =====================================================
-- sadimex_profiles.rol es la fuente de verdad en producción.
DO $$
BEGIN
    ALTER TABLE public.sadimex_profiles DROP CONSTRAINT IF EXISTS sadimex_profiles_rol_check;
    ALTER TABLE public.sadimex_profiles ADD CONSTRAINT sadimex_profiles_rol_check
        CHECK (rol IN ('gerente', 'supervisor', 'vendedor', 'reponedor', 'admin'));
EXCEPTION WHEN undefined_table THEN
    RAISE NOTICE 'sadimex_profiles no existe todavía; omitiendo ampliación de roles.';
END $$;

-- =====================================================
-- TABLA: cadenas (Ketal, Hipermaxi, Fidalga, IC Norte...)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.cadenas (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre      TEXT NOT NULL UNIQUE,
    formato     TEXT CHECK (formato IN ('hipermercado', 'supermercado', 'express', 'mayorista')),
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.cadenas IS 'Cadenas de supermercado donde SADIMEX tiene presencia.';

-- =====================================================
-- TABLA: salas (sucursales / puntos de venta)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.salas (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cadena_id   UUID NOT NULL REFERENCES public.cadenas(id) ON DELETE RESTRICT,
    nombre      TEXT NOT NULL,
    ciudad      TEXT NOT NULL CHECK (ciudad IN ('LPZ', 'CBBA', 'SCZ')),
    direccion   TEXT,
    -- Coordenadas para validar que la foto se tomó en la sala declarada.
    gps_lat     NUMERIC(9, 6),
    gps_lng     NUMERIC(9, 6),
    radio_metros INTEGER NOT NULL DEFAULT 150,
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cadena_id, nombre)
);

COMMENT ON TABLE public.salas IS 'Sucursal concreta. gps_lat/lng + radio_metros permiten validar la geolocalización de la foto.';

CREATE INDEX IF NOT EXISTS idx_salas_ciudad ON public.salas(ciudad);

-- =====================================================
-- TABLA: gondola_skus (catálogo visual — fuente de verdad)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.gondola_skus (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo            TEXT NOT NULL UNIQUE,
    nombre            TEXT NOT NULL,
    marca             TEXT NOT NULL,
    categoria         TEXT NOT NULL,
    gramaje           TEXT,
    ean               TEXT,
    es_prioritario    BOOLEAN NOT NULL DEFAULT FALSE,
    -- URL pública del packshot. Se arma la hoja de referencia visual que
    -- se le manda al modelo junto con la foto de góndola.
    packshot_url      TEXT,
    -- Texto corto que describe cómo se ve el envase. Es lo que evita que
    -- el modelo confunda dos sabores de la misma línea.
    descripcion_visual TEXT,
    activo            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.gondola_skus IS 'Catálogo de SKUs propios que el lector debe reconocer en góndola.';
COMMENT ON COLUMN public.gondola_skus.descripcion_visual IS 'Rasgos distintivos del envase: color dominante, forma, texto grande. Crítico para distinguir variantes.';

CREATE INDEX IF NOT EXISTS idx_gondola_skus_marca ON public.gondola_skus(marca);
CREATE INDEX IF NOT EXISTS idx_gondola_skus_categoria ON public.gondola_skus(categoria);

-- =====================================================
-- TABLA: gondola_precios (PVP vigente por SKU y cadena)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.gondola_precios (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id          UUID NOT NULL REFERENCES public.gondola_skus(id) ON DELETE CASCADE,
    -- NULL = precio nacional, aplica a toda cadena sin precio propio.
    cadena_id       UUID REFERENCES public.cadenas(id) ON DELETE CASCADE,
    pvp             NUMERIC(10, 2) NOT NULL CHECK (pvp > 0),
    moneda          TEXT NOT NULL DEFAULT 'BOB',
    -- Margen aceptado antes de marcar el precio como incorrecto.
    tolerancia_pct  NUMERIC(5, 2) NOT NULL DEFAULT 3.00,
    vigente_desde   DATE NOT NULL DEFAULT CURRENT_DATE,
    vigente_hasta   DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.gondola_precios IS 'Lista de precios sugeridos. Sin un registro vigente el sistema audita presencia y legibilidad de la etiqueta, pero no puede juzgar si el precio es correcto.';

CREATE INDEX IF NOT EXISTS idx_gondola_precios_sku ON public.gondola_precios(sku_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gondola_precios_vigente
    ON public.gondola_precios(sku_id, COALESCE(cadena_id, '00000000-0000-0000-0000-000000000000'::uuid))
    WHERE vigente_hasta IS NULL;

-- =====================================================
-- TABLA: gondola_reglas (Picture of Success configurable)
-- =====================================================
-- Una regla se resuelve de lo más específico a lo más general:
-- (cadena + sku) > (cadena + marca) > (sku) > (marca) > (categoría).
CREATE TABLE IF NOT EXISTS public.gondola_reglas (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre            TEXT NOT NULL,
    -- Ámbito. Todos NULL = regla global de la categoría.
    cadena_id         UUID REFERENCES public.cadenas(id) ON DELETE CASCADE,
    sku_id            UUID REFERENCES public.gondola_skus(id) ON DELETE CASCADE,
    marca             TEXT,
    categoria         TEXT,

    -- R1 Presencia: el SKU debe estar sí o sí en la góndola.
    exige_presencia   BOOLEAN NOT NULL DEFAULT TRUE,
    -- R2 Nivel: dónde debe estar a la altura.
    nivel_objetivo    TEXT NOT NULL DEFAULT 'cualquiera'
                      CHECK (nivel_objetivo IN ('ojos', 'manos', 'ojos_o_manos', 'superior', 'inferior', 'cualquiera')),
    -- R3 Frentes y espacio.
    frentes_minimos   SMALLINT NOT NULL DEFAULT 1 CHECK (frentes_minimos >= 0),
    share_minimo_pct  NUMERIC(5, 2) CHECK (share_minimo_pct BETWEEN 0 AND 100),
    -- R4 Bloque de marca: los SKUs de la marca deben ir contiguos.
    exige_bloque      BOOLEAN NOT NULL DEFAULT TRUE,
    -- R5 Etiqueta de precio.
    exige_etiqueta    BOOLEAN NOT NULL DEFAULT TRUE,
    -- R6 Góndola sana: sin huecos, producto frenteado.
    exige_sin_quiebre BOOLEAN NOT NULL DEFAULT TRUE,

    activo            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.gondola_reglas IS 'Reglas de ejecución en sala. Se resuelven de lo más específico a lo más general por SKU.';

CREATE INDEX IF NOT EXISTS idx_gondola_reglas_cadena ON public.gondola_reglas(cadena_id);
CREATE INDEX IF NOT EXISTS idx_gondola_reglas_sku ON public.gondola_reglas(sku_id);

-- =====================================================
-- TABLA: gondola_pesos (ponderación del score)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.gondola_pesos (
    regla       TEXT PRIMARY KEY CHECK (regla IN (
                    'presencia', 'nivel', 'frentes', 'bloque', 'etiqueta', 'sin_quiebre')),
    peso        NUMERIC(4, 3) NOT NULL CHECK (peso >= 0 AND peso <= 1),
    descripcion TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.gondola_pesos (regla, peso, descripcion) VALUES
    ('presencia',   0.30, 'El SKU obligatorio está en la góndola'),
    ('nivel',       0.20, 'El SKU está a la altura objetivo (ojos / manos)'),
    ('frentes',     0.20, 'Cumple los frentes mínimos y el share of shelf'),
    ('bloque',      0.10, 'Los SKUs de la marca están contiguos, sin dispersión'),
    ('etiqueta',    0.15, 'Etiqueta de precio presente, legible y correcta'),
    ('sin_quiebre', 0.05, 'Sin huecos en nuestro espacio y producto frenteado')
ON CONFLICT (regla) DO NOTHING;

COMMENT ON TABLE public.gondola_pesos IS 'Ponderación de cada regla en el score 0-100. La suma de pesos debería dar 1.0.';

-- =====================================================
-- TABLA: gondola_photos (cola de trabajo)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.gondola_photos (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reponedor_id    UUID NOT NULL,
    sala_id         UUID NOT NULL REFERENCES public.salas(id) ON DELETE RESTRICT,
    ciudad          TEXT NOT NULL CHECK (ciudad IN ('LPZ', 'CBBA', 'SCZ')),
    categoria       TEXT NOT NULL,
    storage_path    TEXT NOT NULL,

    -- Evidencia de captura. Sin esto no se puede evaluar a un reponedor:
    -- cualquiera podría resubir la foto buena de la semana pasada.
    tomada_at       TIMESTAMPTZ,
    gps_lat         NUMERIC(9, 6),
    gps_lng         NUMERIC(9, 6),
    imagen_sha256   TEXT,
    -- Se marca cuando el hash ya existía o el GPS cae fuera del radio de la sala.
    alerta_captura  TEXT,

    estado          TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'procesando', 'completado', 'error', 'rechazada')),
    intentos        SMALLINT NOT NULL DEFAULT 0,
    error_mensaje   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.gondola_photos IS 'Cada foto de góndola subida. El worker toma de aquí las que están en estado pendiente.';
COMMENT ON COLUMN public.gondola_photos.imagen_sha256 IS 'Hash del archivo original. Un hash repetido es una foto reciclada.';

CREATE INDEX IF NOT EXISTS idx_gondola_photos_estado ON public.gondola_photos(estado, created_at);
CREATE INDEX IF NOT EXISTS idx_gondola_photos_reponedor ON public.gondola_photos(reponedor_id);
CREATE INDEX IF NOT EXISTS idx_gondola_photos_sala ON public.gondola_photos(sala_id);
CREATE INDEX IF NOT EXISTS idx_gondola_photos_ciudad ON public.gondola_photos(ciudad);
CREATE INDEX IF NOT EXISTS idx_gondola_photos_sha ON public.gondola_photos(imagen_sha256);

-- =====================================================
-- TABLA: gondola_analyses (resultado auditable)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.gondola_analyses (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    photo_id            UUID NOT NULL UNIQUE REFERENCES public.gondola_photos(id) ON DELETE CASCADE,
    reponedor_id        UUID NOT NULL,
    sala_id             UUID NOT NULL REFERENCES public.salas(id) ON DELETE RESTRICT,
    ciudad              TEXT NOT NULL CHECK (ciudad IN ('LPZ', 'CBBA', 'SCZ')),

    score               SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 100),
    semaforo            TEXT NOT NULL CHECK (semaforo IN ('verde', 'amarillo', 'rojo')),

    -- Resultado por regla: {presencia: {cumple, obtenido, esperado, detalle}, ...}
    reglas              JSONB NOT NULL DEFAULT '{}',
    -- Lo que el modelo vio, sin juicio: SKUs, frentes, niveles, bboxes.
    observacion         JSONB NOT NULL DEFAULT '{}',
    -- Auditoría de etiquetas de precio.
    etiquetas           JSONB NOT NULL DEFAULT '[]',
    -- Lista accionable para el supervisor.
    hallazgos           JSONB NOT NULL DEFAULT '[]',

    share_of_shelf_pct  NUMERIC(5, 2),
    quiebres_detectados SMALLINT NOT NULL DEFAULT 0,
    confianza_global    NUMERIC(4, 3) CHECK (confianza_global BETWEEN 0 AND 1),
    calidad_foto        TEXT CHECK (calidad_foto IN ('buena', 'regular', 'mala')),

    -- Trazabilidad de costo y modelo, para poder comparar modelos con datos.
    modelo_usado        TEXT,
    escalado            BOOLEAN NOT NULL DEFAULT FALSE,
    tokens_entrada      INTEGER,
    tokens_salida       INTEGER,
    costo_usd           NUMERIC(10, 6),
    duracion_ms         INTEGER,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.gondola_analyses IS 'Resultado del análisis. observacion = lo que el modelo vio; reglas = veredicto calculado por el motor determinístico.';
COMMENT ON COLUMN public.gondola_analyses.escalado IS 'TRUE si hubo que reintentar con el modelo grande por baja confianza.';

CREATE INDEX IF NOT EXISTS idx_gondola_analyses_reponedor ON public.gondola_analyses(reponedor_id);
CREATE INDEX IF NOT EXISTS idx_gondola_analyses_ciudad ON public.gondola_analyses(ciudad);
CREATE INDEX IF NOT EXISTS idx_gondola_analyses_sala ON public.gondola_analyses(sala_id);
CREATE INDEX IF NOT EXISTS idx_gondola_analyses_fecha ON public.gondola_analyses(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gondola_analyses_semaforo ON public.gondola_analyses(semaforo);

-- =====================================================
-- VISTA: ranking de reponedores (últimos 30 días)
-- =====================================================
CREATE OR REPLACE VIEW public.gondola_ranking_reponedores AS
SELECT
    a.reponedor_id,
    a.ciudad,
    COUNT(*)                                          AS fotos_analizadas,
    ROUND(AVG(a.score), 1)                            AS score_promedio,
    COUNT(*) FILTER (WHERE a.semaforo = 'verde')      AS fotos_verdes,
    COUNT(*) FILTER (WHERE a.semaforo = 'rojo')       AS fotos_rojas,
    ROUND(AVG(a.share_of_shelf_pct), 1)               AS share_promedio,
    SUM(a.quiebres_detectados)                        AS quiebres_totales,
    COUNT(DISTINCT a.sala_id)                         AS salas_cubiertas,
    MAX(a.created_at)                                 AS ultima_foto
FROM public.gondola_analyses a
WHERE a.created_at >= NOW() - INTERVAL '30 days'
GROUP BY a.reponedor_id, a.ciudad;

COMMENT ON VIEW public.gondola_ranking_reponedores IS 'Desempeño por reponedor en los últimos 30 días.';

-- =====================================================
-- VISTA: salud de la ejecución por sala
-- =====================================================
CREATE OR REPLACE VIEW public.gondola_salud_salas AS
SELECT
    s.id            AS sala_id,
    s.nombre        AS sala,
    c.nombre        AS cadena,
    s.ciudad,
    COUNT(a.id)                                       AS fotos_30d,
    ROUND(AVG(a.score), 1)                            AS score_promedio,
    ROUND(AVG(a.share_of_shelf_pct), 1)               AS share_promedio,
    SUM(a.quiebres_detectados)                        AS quiebres_30d,
    MAX(a.created_at)                                 AS ultima_auditoria
FROM public.salas s
JOIN public.cadenas c ON c.id = s.cadena_id
LEFT JOIN public.gondola_analyses a
       ON a.sala_id = s.id AND a.created_at >= NOW() - INTERVAL '30 days'
WHERE s.activo
GROUP BY s.id, s.nombre, c.nombre, s.ciudad;

COMMENT ON VIEW public.gondola_salud_salas IS 'Estado de ejecución por sucursal. ultima_auditoria NULL = sala sin visitar.';

-- =====================================================
-- ROW LEVEL SECURITY
-- =====================================================
ALTER TABLE public.gondola_photos   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gondola_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gondola_skus     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gondola_reglas   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gondola_precios  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.salas            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cadenas          ENABLE ROW LEVEL SECURITY;

-- Reponedor: solo lo suyo.
DROP POLICY IF EXISTS "reponedor_own_photos" ON public.gondola_photos;
CREATE POLICY "reponedor_own_photos" ON public.gondola_photos
    FOR SELECT USING (reponedor_id = auth.uid());

DROP POLICY IF EXISTS "reponedor_own_analyses" ON public.gondola_analyses;
CREATE POLICY "reponedor_own_analyses" ON public.gondola_analyses
    FOR SELECT USING (reponedor_id = auth.uid());

-- El reponedor sube sus propias fotos desde el cliente.
DROP POLICY IF EXISTS "reponedor_insert_photos" ON public.gondola_photos;
CREATE POLICY "reponedor_insert_photos" ON public.gondola_photos
    FOR INSERT WITH CHECK (reponedor_id = auth.uid());

-- Supervisor: solo su ciudad.
DROP POLICY IF EXISTS "supervisor_ciudad_photos" ON public.gondola_photos;
CREATE POLICY "supervisor_ciudad_photos" ON public.gondola_photos
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.sadimex_profiles p
                WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = gondola_photos.ciudad)
    );

DROP POLICY IF EXISTS "supervisor_ciudad_analyses" ON public.gondola_analyses;
CREATE POLICY "supervisor_ciudad_analyses" ON public.gondola_analyses
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.sadimex_profiles p
                WHERE p.id = auth.uid() AND p.rol = 'supervisor' AND p.ciudad = gondola_analyses.ciudad)
    );

-- Gerente y admin: lectura nacional.
DROP POLICY IF EXISTS "gerencia_all_photos" ON public.gondola_photos;
CREATE POLICY "gerencia_all_photos" ON public.gondola_photos
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.sadimex_profiles p
                WHERE p.id = auth.uid() AND p.rol IN ('gerente', 'admin'))
    );

DROP POLICY IF EXISTS "gerencia_all_analyses" ON public.gondola_analyses;
CREATE POLICY "gerencia_all_analyses" ON public.gondola_analyses
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.sadimex_profiles p
                WHERE p.id = auth.uid() AND p.rol IN ('gerente', 'admin'))
    );

-- Catálogo, reglas, precios, salas y cadenas: lectura para todo usuario
-- autenticado (la app los necesita para armar la UI); escritura solo admin.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['gondola_skus', 'gondola_reglas', 'gondola_precios', 'salas', 'cadenas']
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS "lectura_autenticada" ON public.%I', t);
        EXECUTE format(
            'CREATE POLICY "lectura_autenticada" ON public.%I FOR SELECT USING (auth.uid() IS NOT NULL)', t);
        EXECUTE format('DROP POLICY IF EXISTS "admin_escribe" ON public.%I', t);
        EXECUTE format(
            'CREATE POLICY "admin_escribe" ON public.%I FOR ALL USING (EXISTS ('
            || 'SELECT 1 FROM public.sadimex_profiles p WHERE p.id = auth.uid() AND p.rol = ''admin''))', t);
    END LOOP;
END $$;

-- =====================================================
-- TRIGGERS updated_at
-- =====================================================
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_gondola_photos_updated_at ON public.gondola_photos;
CREATE TRIGGER trg_gondola_photos_updated_at
    BEFORE UPDATE ON public.gondola_photos
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_gondola_skus_updated_at ON public.gondola_skus;
CREATE TRIGGER trg_gondola_skus_updated_at
    BEFORE UPDATE ON public.gondola_skus
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_gondola_reglas_updated_at ON public.gondola_reglas;
CREATE TRIGGER trg_gondola_reglas_updated_at
    BEFORE UPDATE ON public.gondola_reglas
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- =====================================================
-- RPC: reclamar la siguiente foto pendiente sin condición de carrera
-- =====================================================
CREATE OR REPLACE FUNCTION public.gondola_reclamar_foto(max_intentos SMALLINT DEFAULT 3)
RETURNS SETOF public.gondola_photos AS $$
    UPDATE public.gondola_photos p
       SET estado = 'procesando',
           intentos = p.intentos + 1,
           updated_at = NOW()
     WHERE p.id = (
         SELECT id FROM public.gondola_photos
          WHERE estado = 'pendiente' AND intentos < max_intentos
          ORDER BY created_at
          FOR UPDATE SKIP LOCKED
          LIMIT 1
     )
    RETURNING p.*;
$$ LANGUAGE sql;

COMMENT ON FUNCTION public.gondola_reclamar_foto IS 'SKIP LOCKED permite correr varios workers en paralelo sin que dos tomen la misma foto.';


-- -------------------------------------------------------------------
--  PARTE 2 — Cadenas, precios por cadena y reportes
--  (origen: migrations/004_gondola_cadenas_precios.sql)
-- -------------------------------------------------------------------

-- =====================================================
-- SADIMEX — Lector de Góndola: cadenas, carga de precios y costos
-- Migration: 004_gondola_cadenas_precios.sql
-- =====================================================
-- Depende de 003_gondola_schema.sql.
--
-- Agrega:
--   * las cadenas donde SADIMEX opera hoy
--   * carga de precios por cadena con historial (el precio viejo no se
--     borra, se cierra: así un análisis de la semana pasada sigue siendo
--     auditable contra el PVP que regía ese día)
--   * vista de costo de IA por día, para vigilar la factura con volumen alto
-- =====================================================

-- =====================================================
-- SEED: cadenas
-- =====================================================
INSERT INTO public.cadenas (nombre, formato) VALUES
    ('Fidalga',   'supermercado'),
    ('Hipermaxi', 'hipermercado'),
    ('Tía',       'supermercado'),
    ('IC Norte',  'hipermercado')
ON CONFLICT (nombre) DO NOTHING;

-- =====================================================
-- HISTORIAL DE PRECIOS
-- =====================================================
-- 003 dejaba un índice único sobre (sku, cadena) WHERE vigente_hasta IS NULL,
-- que es exactamente lo que se necesita: un solo precio vigente a la vez.
-- Falta el índice para consultar el histórico cerrado.
CREATE INDEX IF NOT EXISTS idx_gondola_precios_historial
    ON public.gondola_precios(sku_id, cadena_id, vigente_desde DESC);

-- =====================================================
-- RPC: cargar un precio (upsert con cierre del anterior)
-- =====================================================
-- Es lo que usa la carga masiva del administrador. Recibe códigos y
-- nombres, no UUIDs: el CSV que sube el admin no conoce los ids internos.
--
-- Devuelve la acción tomada para que la UI pueda mostrar un resumen
-- honesto: cuántos precios cambiaron, cuántos ya estaban igual y cuántos
-- fallaron por SKU o cadena inexistente.
CREATE OR REPLACE FUNCTION public.gondola_cargar_precio(
    p_sku_codigo    TEXT,
    p_cadena_nombre TEXT,
    p_pvp           NUMERIC,
    p_moneda        TEXT DEFAULT 'BOB',
    p_tolerancia    NUMERIC DEFAULT 3.00
)
RETURNS TABLE (accion TEXT, detalle TEXT) AS $$
DECLARE
    v_sku_id      UUID;
    v_cadena_id   UUID;
    v_precio_prev public.gondola_precios%ROWTYPE;
BEGIN
    IF p_pvp IS NULL OR p_pvp <= 0 THEN
        RETURN QUERY SELECT 'error'::TEXT, format('PVP inválido: %s', p_pvp);
        RETURN;
    END IF;

    SELECT id INTO v_sku_id
      FROM public.gondola_skus
     WHERE codigo = p_sku_codigo AND activo;

    IF v_sku_id IS NULL THEN
        RETURN QUERY SELECT 'error'::TEXT, format('SKU no encontrado: %s', p_sku_codigo);
        RETURN;
    END IF;

    -- Cadena vacía o nula = precio nacional, aplica donde no haya uno propio.
    IF p_cadena_nombre IS NOT NULL AND btrim(p_cadena_nombre) <> '' THEN
        SELECT id INTO v_cadena_id
          FROM public.cadenas
         WHERE lower(nombre) = lower(btrim(p_cadena_nombre));

        IF v_cadena_id IS NULL THEN
            RETURN QUERY SELECT 'error'::TEXT, format('Cadena no encontrada: %s', p_cadena_nombre);
            RETURN;
        END IF;
    END IF;

    SELECT * INTO v_precio_prev
      FROM public.gondola_precios
     WHERE sku_id = v_sku_id
       AND cadena_id IS NOT DISTINCT FROM v_cadena_id
       AND vigente_hasta IS NULL;

    IF FOUND AND v_precio_prev.pvp = p_pvp
             AND v_precio_prev.moneda = p_moneda
             AND v_precio_prev.tolerancia_pct = p_tolerancia THEN
        RETURN QUERY SELECT 'sin_cambio'::TEXT, format('%s ya estaba en %s', p_sku_codigo, p_pvp);
        RETURN;
    END IF;

    IF FOUND THEN
        -- El precio anterior se cierra, no se borra: los análisis viejos
        -- deben seguir siendo auditables contra el PVP que regía entonces.
        UPDATE public.gondola_precios
           SET vigente_hasta = CURRENT_DATE
         WHERE id = v_precio_prev.id;
    END IF;

    INSERT INTO public.gondola_precios
        (sku_id, cadena_id, pvp, moneda, tolerancia_pct, vigente_desde)
    VALUES
        (v_sku_id, v_cadena_id, p_pvp, p_moneda, p_tolerancia, CURRENT_DATE);

    RETURN QUERY SELECT
        CASE WHEN v_precio_prev.id IS NULL THEN 'creado' ELSE 'actualizado' END::TEXT,
        format('%s @ %s = %s %s',
               p_sku_codigo, COALESCE(p_cadena_nombre, 'nacional'), p_pvp, p_moneda);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.gondola_cargar_precio IS
    'Carga un precio por código de SKU y nombre de cadena, cerrando el anterior. Usada por la carga masiva del administrador.';

-- =====================================================
-- VISTA: precios vigentes en lenguaje humano
-- =====================================================
-- Lo que el administrador revisa después de subir el CSV.
CREATE OR REPLACE VIEW public.gondola_precios_vigentes AS
SELECT
    s.codigo                          AS sku_codigo,
    s.nombre                          AS sku_nombre,
    s.marca,
    s.categoria,
    COALESCE(c.nombre, 'NACIONAL')    AS cadena,
    p.pvp,
    p.moneda,
    p.tolerancia_pct,
    p.vigente_desde
FROM public.gondola_precios p
JOIN public.gondola_skus s ON s.id = p.sku_id
LEFT JOIN public.cadenas c ON c.id = p.cadena_id
WHERE p.vigente_hasta IS NULL AND s.activo;

COMMENT ON VIEW public.gondola_precios_vigentes IS
    'Precios en vigor hoy, por SKU y cadena. NACIONAL aplica donde la cadena no tiene precio propio.';

-- =====================================================
-- VISTA: SKU sin precio cargado
-- =====================================================
-- Un SKU sin PVP no se puede auditar en monto, solo en presencia de la
-- etiqueta. Esta vista dice exactamente qué falta cargar.
CREATE OR REPLACE VIEW public.gondola_skus_sin_precio AS
SELECT
    s.codigo,
    s.nombre,
    s.marca,
    s.categoria,
    s.es_prioritario
FROM public.gondola_skus s
WHERE s.activo
  AND NOT EXISTS (
      SELECT 1 FROM public.gondola_precios p
       WHERE p.sku_id = s.id AND p.vigente_hasta IS NULL
  );

COMMENT ON VIEW public.gondola_skus_sin_precio IS
    'SKU activos sin PVP vigente. Para estos el sistema audita si la etiqueta existe y es legible, pero no si el monto es correcto.';

-- =====================================================
-- VISTA: costo de IA por día
-- =====================================================
-- Con volumen alto la factura es un KPI operativo, no un detalle. Esta
-- vista responde "cuánto llevamos gastado y cuánto sale cada foto".
CREATE OR REPLACE VIEW public.gondola_costos_diarios AS
SELECT
    (a.created_at AT TIME ZONE 'UTC')::DATE            AS dia,
    a.ciudad,
    a.modelo_usado,
    COUNT(*)                                           AS fotos,
    COUNT(*) FILTER (WHERE a.escalado)                 AS escaladas,
    ROUND(SUM(a.costo_usd)::NUMERIC, 4)                AS costo_usd,
    ROUND(AVG(a.costo_usd)::NUMERIC, 6)                AS costo_promedio_foto,
    ROUND(AVG(a.duracion_ms)::NUMERIC, 0)              AS ms_promedio,
    ROUND(AVG(a.confianza_global)::NUMERIC, 3)         AS confianza_promedio
FROM public.gondola_analyses a
GROUP BY 1, 2, 3;

COMMENT ON VIEW public.gondola_costos_diarios IS
    'Gasto de IA por día, ciudad y modelo. Vigila aquí el efecto de subir o bajar UMBRAL_ESCALADO.';

-- =====================================================
-- VISTA: cobertura del catálogo visual
-- =====================================================
-- Sin packshot el modelo no puede distinguir variantes parecidas. Esta
-- vista dice cuánto del catálogo está listo para auditarse en serio.
CREATE OR REPLACE VIEW public.gondola_cobertura_catalogo AS
SELECT
    s.categoria,
    COUNT(*)                                                          AS skus,
    COUNT(*) FILTER (WHERE s.packshot_url IS NOT NULL)                AS con_packshot,
    COUNT(*) FILTER (WHERE s.descripcion_visual IS NOT NULL)          AS con_descripcion,
    COUNT(*) FILTER (WHERE s.es_prioritario)                          AS prioritarios,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE s.packshot_url IS NOT NULL) / NULLIF(COUNT(*), 0),
        1
    )                                                                 AS pct_con_packshot
FROM public.gondola_skus s
WHERE s.activo
GROUP BY s.categoria;

COMMENT ON VIEW public.gondola_cobertura_catalogo IS
    'Qué tan listo está el catálogo por categoría. pct_con_packshot bajo = precisión baja entre variantes.';


-- -------------------------------------------------------------------
--  PARTE 3 — Trazabilidad del consenso de lecturas
--  (origen: migrations/005_gondola_consenso.sql)
-- -------------------------------------------------------------------

-- =====================================================
-- SADIMEX — Lector de Góndola: trazabilidad del consenso
-- Migration: 005_gondola_consenso.sql
-- =====================================================
-- Depende de 003_gondola_schema.sql.
--
-- Cuando una lectura no es confiable, el sistema pide una segunda al
-- mismo modelo barato y fusiona ambas. Estas columnas dejan registro de
-- eso, que es lo que permite defender un score meses después:
-- "¿por qué esta foto dio 62?" → "hubo que leerla dos veces, coincidieron
-- en un 55% y se descartaron dos precios en disputa".
-- =====================================================

ALTER TABLE public.gondola_analyses
    ADD COLUMN IF NOT EXISTS lecturas SMALLINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS nota_consenso TEXT;

COMMENT ON COLUMN public.gondola_analyses.lecturas IS
    'Veces que se leyó la foto: 1 = confiable de una pasada, 2 = hubo que verificar, 3 = las dos lecturas se contradijeron y se escaló.';
COMMENT ON COLUMN public.gondola_analyses.nota_consenso IS
    'Resumen de la fusión: índice de acuerdo, SKU sin confirmar, precios descartados por discrepancia.';

-- Las fotos que necesitaron más de una lectura son las candidatas a
-- revisar cuando alguien discute un resultado.
CREATE INDEX IF NOT EXISTS idx_gondola_analyses_lecturas
    ON public.gondola_analyses(lecturas)
    WHERE lecturas > 1;

-- =====================================================
-- VISTA: efecto real del consenso
-- =====================================================
-- Responde la pregunta que decide si esta estrategia vale la pena:
-- ¿cuántas fotos necesitan verificarse, cuánto sube el costo por eso, y
-- cuánta confianza se gana?
CREATE OR REPLACE VIEW public.gondola_efecto_consenso AS
SELECT
    (a.created_at AT TIME ZONE 'UTC')::DATE            AS dia,
    a.lecturas,
    COUNT(*)                                           AS fotos,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (
        PARTITION BY (a.created_at AT TIME ZONE 'UTC')::DATE), 1)  AS pct_del_dia,
    ROUND(AVG(a.costo_usd)::NUMERIC, 6)                AS costo_promedio,
    ROUND(AVG(a.confianza_global)::NUMERIC, 3)         AS confianza_promedio,
    ROUND(AVG(a.score)::NUMERIC, 1)                    AS score_promedio,
    COUNT(*) FILTER (WHERE a.nota_consenso LIKE '%precios descartados%') AS con_precios_en_disputa
FROM public.gondola_analyses a
GROUP BY 1, 2;

COMMENT ON VIEW public.gondola_efecto_consenso IS
    'Cuántas fotos se leen una, dos o tres veces, y qué cuesta cada caso. Si el porcentaje de fotos con 2+ lecturas es alto, el problema está en la calidad de las fotos, no en el modelo.';


COMMIT;

-- ═══════════════════════════════════════════════════════════════════
--  Listo. Para confirmar que quedó todo, corre esto en una consulta
--  nueva:
--
--    SELECT table_name FROM information_schema.tables
--     WHERE table_schema = 'public'
--       AND (table_name LIKE 'gondola%' OR table_name IN ('salas','cadenas'))
--     ORDER BY table_name;
--
--  Deberías ver 8 tablas y 7 vistas (15 filas). Y las 4 cadenas:
--
--    SELECT nombre, formato FROM public.cadenas ORDER BY nombre;
-- ═══════════════════════════════════════════════════════════════════
