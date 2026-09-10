-- ============================================================
-- Correcciones: la operación se vuelve verdad de referencia
-- ============================================================
--
-- El problema que resuelve
-- ------------------------
-- Este módulo depende de datos que hoy nadie tiene cargados: qué SKU
-- lleva cada cadena, en qué nivel debería estar cada uno, a qué precio.
-- Pedirlos por planilla es frágil —un código mal escrito deja un SKU
-- invisible para siempre— y además nunca se termina de actualizar: el
-- surtido cambia cada temporada.
--
-- La alternativa es que el sistema los aprenda de su propia operación.
-- Cada foto que sube un reponedor ya pasó por el modelo; lo único que
-- falta es que alguien diga si la lectura estuvo bien. Un toque por foto.
--
-- Con eso salen tres cosas que hoy no existen:
--
--   1. Surtido, sin que nadie lo cargue. Si en Fidalga se confirma
--      Ducales en quince fotos y Festival en ninguna, el surtido de
--      galletas de Fidalga ya está escrito.
--   2. Verdad de referencia que crece sola. Hoy hay 17 fotos anotadas a
--      mano; una semana de operación agrega cientos.
--   3. Exactitud vigilada por cadena y categoría, en vez de una medición
--      suelta. Si un cambio de modelo o de prompt empeora las cosas, se
--      ve en la vista en vez de descubrirse meses después.
--
-- Qué NO es
-- ---------
-- No es un ciclo de revisión humana de cada foto: eso ya se descartó al
-- diseñar el módulo, por costo. Es una corrección OPCIONAL, que un
-- supervisor hace sobre las fotos que le llaman la atención. Aunque solo
-- se corrija el 5% de las fotos, en un mes son cientos de anotaciones
-- reales, que es más de lo que cualquiera va a anotar a propósito.

BEGIN;

-- ── Corrección de una lectura ────────────────────────────────────
CREATE TABLE IF NOT EXISTS gondola_correcciones (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    photo_id     uuid NOT NULL REFERENCES gondola_photos(id) ON DELETE CASCADE,
    corregido_por uuid NOT NULL REFERENCES sadimex_profiles(id),

    -- Los SKU que de verdad estaban en la foto, en códigos. Es la verdad
    -- de referencia: se guarda la lista completa y no las diferencias,
    -- porque las diferencias dependen de qué modelo corrió ese día y
    -- dejarían de tener sentido al cambiarlo.
    skus_reales  text[] NOT NULL DEFAULT '{}',

    -- Lo que había reportado el sistema cuando se corrigió, congelado.
    -- Permite medir después sin depender de que el análisis siga igual.
    skus_leidos  text[] NOT NULL DEFAULT '{}',
    modelo       text,

    -- "confirmada" = el supervisor miró y estaba bien; "corregida" = tocó
    -- algo. Se distinguen porque una confirmación es evidencia más
    -- barata y más frecuente, y no hay que confundirlas al contar.
    tipo         text NOT NULL DEFAULT 'corregida'
                 CHECK (tipo IN ('confirmada', 'corregida')),
    nota         text,
    creado_en    timestamptz NOT NULL DEFAULT now(),

    -- Una corrección por foto: la última manda. Corregir dos veces la
    -- misma foto es arreglar un error de tipeo, no dos observaciones.
    UNIQUE (photo_id)
);

CREATE INDEX IF NOT EXISTS gondola_correcciones_fecha_idx
    ON gondola_correcciones (creado_en DESC);

ALTER TABLE gondola_correcciones ENABLE ROW LEVEL SECURITY;

-- Misma regla de ciudad que el resto del módulo: cada quien ve las salas
-- de su ciudad, gerencia y administración ven todo.
DROP POLICY IF EXISTS gondola_correcciones_lectura ON gondola_correcciones;
CREATE POLICY gondola_correcciones_lectura ON gondola_correcciones
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM gondola_photos f
            JOIN salas s ON s.id = f.sala_id
            JOIN sadimex_profiles p ON p.id = auth.uid()
            WHERE f.id = gondola_correcciones.photo_id
              AND (p.rol IN ('admin', 'gerente') OR p.ciudad = s.ciudad)
        )
    );

-- Corrige quien supervisa, no quien repone: si el reponedor pudiera
-- corregir su propia foto, estaría calificándose a sí mismo.
DROP POLICY IF EXISTS gondola_correcciones_escritura ON gondola_correcciones;
CREATE POLICY gondola_correcciones_escritura ON gondola_correcciones
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM sadimex_profiles p
            WHERE p.id = auth.uid() AND p.rol IN ('admin', 'gerente', 'supervisor')
        )
    );

-- ── Surtido aprendido de las correcciones ────────────────────────
--
-- Lo que de verdad se vio en cada cadena y categoría, contado sobre
-- fotos confirmadas o corregidas por una persona. Es la fuente para
-- llenar `gondola_surtido` sin que nadie cargue una planilla.
CREATE OR REPLACE VIEW gondola_surtido_observado AS
WITH visto AS (
    SELECT
        s.cadena_id,
        f.categoria,
        unnest(c.skus_reales) AS codigo,
        c.photo_id
    FROM gondola_correcciones c
    JOIN gondola_photos f ON f.id = c.photo_id
    JOIN salas s          ON s.id = f.sala_id
),
fotos_por_cadena AS (
    SELECT s.cadena_id, f.categoria, count(*) AS fotos_revisadas
    FROM gondola_correcciones c
    JOIN gondola_photos f ON f.id = c.photo_id
    JOIN salas s          ON s.id = f.sala_id
    GROUP BY s.cadena_id, f.categoria
)
SELECT
    v.cadena_id,
    ca.nombre AS cadena,
    v.categoria,
    v.codigo,
    k.nombre  AS sku,
    k.marca,
    count(DISTINCT v.photo_id) AS fotos_con_el_sku,
    t.fotos_revisadas,
    round(100.0 * count(DISTINCT v.photo_id) / t.fotos_revisadas, 1) AS pct_de_fotos,
    -- Ya en el surtido cargado, o todavía no.
    EXISTS (
        SELECT 1 FROM gondola_surtido_vigente sv
        WHERE sv.cadena_id = v.cadena_id AND sv.codigo = v.codigo
    ) AS ya_en_surtido
FROM visto v
JOIN cadenas ca      ON ca.id = v.cadena_id
JOIN fotos_por_cadena t ON t.cadena_id = v.cadena_id AND t.categoria = v.categoria
LEFT JOIN gondola_skus k ON k.codigo = v.codigo
GROUP BY v.cadena_id, ca.nombre, v.categoria, v.codigo, k.nombre, k.marca, t.fotos_revisadas
ORDER BY ca.nombre, v.categoria, count(DISTINCT v.photo_id) DESC;

-- ── Exactitud del lector, por cadena y categoría ─────────────────
--
-- Recall y precisión calculados sobre las fotos que una persona revisó.
-- Se informan separados a propósito: un falso positivo tapa un quiebre
-- real y es el error caro; un falso negativo manda a alguien a una sala
-- en vano. Promediarlos escondería justo esa diferencia.
CREATE OR REPLACE VIEW gondola_exactitud AS
WITH por_foto AS (
    SELECT
        s.cadena_id,
        ca.nombre AS cadena,
        f.categoria,
        date_trunc('month', c.creado_en) AS mes,
        c.modelo,
        cardinality(ARRAY(SELECT unnest(c.skus_reales) INTERSECT SELECT unnest(c.skus_leidos))) AS aciertos,
        cardinality(ARRAY(SELECT unnest(c.skus_leidos) EXCEPT SELECT unnest(c.skus_reales))) AS inventados,
        cardinality(ARRAY(SELECT unnest(c.skus_reales) EXCEPT SELECT unnest(c.skus_leidos))) AS perdidos,
        (c.skus_reales <@ c.skus_leidos AND c.skus_leidos <@ c.skus_reales) AS clavada
    FROM gondola_correcciones c
    JOIN gondola_photos f ON f.id = c.photo_id
    JOIN salas s          ON s.id = f.sala_id
    JOIN cadenas ca       ON ca.id = s.cadena_id
)
SELECT
    cadena, categoria, mes, modelo,
    count(*)                    AS fotos_revisadas,
    sum(aciertos)               AS aciertos,
    sum(perdidos)               AS quiebres_falsos,
    sum(inventados)             AS ausencias_tapadas,
    CASE WHEN sum(aciertos) + sum(perdidos) > 0
         THEN round(100.0 * sum(aciertos) / (sum(aciertos) + sum(perdidos)), 1) END AS recall_pct,
    CASE WHEN sum(aciertos) + sum(inventados) > 0
         THEN round(100.0 * sum(aciertos) / (sum(aciertos) + sum(inventados)), 1) END AS precision_pct,
    round(100.0 * count(*) FILTER (WHERE clavada) / count(*), 1) AS fotos_clavadas_pct
FROM por_foto
GROUP BY cadena, categoria, mes, modelo
ORDER BY mes DESC, cadena, categoria;

-- ── Pasar el surtido observado al surtido vigente ────────────────
--
-- Un SKU entra al surtido cuando apareció en al menos `p_min_fotos`
-- fotos revisadas de esa cadena. El mínimo existe porque una corrección
-- suelta puede ser un error de quien corrige, y meter un SKU equivocado
-- al surtido es justo el problema que el surtido viene a evitar.
--
-- No da de baja nada: que un SKU no aparezca puede ser que la cadena
-- dejó de llevarlo, o que todavía no se fotografió esa parte de la
-- góndola. Las bajas se hacen a mano.
CREATE OR REPLACE FUNCTION gondola_promover_surtido(
    p_min_fotos int DEFAULT 3
) RETURNS TABLE (accion text, detalle text)
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_altas int;
BEGIN
    WITH nuevas AS (
        INSERT INTO gondola_surtido (cadena_id, sku_id)
        SELECT DISTINCT o.cadena_id, k.id
        FROM gondola_surtido_observado o
        JOIN gondola_skus k ON k.codigo = o.codigo AND k.activo
        WHERE o.fotos_con_el_sku >= p_min_fotos
          AND NOT o.ya_en_surtido
        ON CONFLICT (cadena_id, sku_id) DO UPDATE SET vigente_hasta = NULL
        RETURNING 1
    )
    SELECT count(*) INTO v_altas FROM nuevas;

    RETURN QUERY SELECT
        'ok',
        format('%s SKU agregados al surtido con %s o más fotos revisadas',
               v_altas, p_min_fotos);
END;
$$;

COMMIT;
