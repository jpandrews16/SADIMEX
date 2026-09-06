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
