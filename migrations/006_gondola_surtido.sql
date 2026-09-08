-- ============================================================
-- Surtido por cadena: qué SKU lleva cada cadena de cada categoría
-- ============================================================
--
-- Por qué existe esta tabla
-- -------------------------
-- Hasta ahora, para analizar una foto se le pasaban al modelo TODOS los
-- SKU de la categoría. Medido contra 17 fotos de sala anotadas a mano,
-- eso es el error más grande que tenía el módulo:
--
--   catálogo completo (10 SKU)   recall 58%   precisión 41%
--   surtido real      ( 6 SKU)   recall 70%   precisión 65%
--
-- Mismo modelo, mismo prompt, mismas fotos. La diferencia entera está en
-- lo que se le pregunta. Con SKU que la cadena no vende, el modelo
-- reparte adivinanzas entre todos los envases de la hoja de referencia:
-- las cuatro variantes de Festival, que no estaban en NINGUNA de las 17
-- fotos, se reportaron en 6 fotos cada una. Eran 25 de los 44 falsos
-- positivos.
--
-- Un falso positivo tapa un quiebre real, así que es el error caro. La
-- forma de no cometerlo es no preguntar por lo que no puede estar.
--
-- Cómo se usa
-- -----------
-- Si una cadena tiene surtido cargado para una categoría, el análisis usa
-- solo esos SKU. Si no tiene, se cae a la categoría completa —el
-- comportamiento anterior— para que cargar el surtido sea opcional y
-- gradual, cadena por cadena.

BEGIN;

CREATE TABLE IF NOT EXISTS gondola_surtido (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cadena_id   uuid NOT NULL REFERENCES cadenas(id) ON DELETE CASCADE,
    sku_id      uuid NOT NULL REFERENCES gondola_skus(id) ON DELETE CASCADE,
    -- Fecha en que el SKU deja de venderse en esa cadena. NULL = vigente.
    -- No se borra la fila: un análisis viejo tiene que seguir siendo
    -- auditable con el surtido que regía cuando se hizo.
    vigente_hasta timestamptz,
    creado_en   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (cadena_id, sku_id)
);

CREATE INDEX IF NOT EXISTS gondola_surtido_cadena_idx
    ON gondola_surtido (cadena_id) WHERE vigente_hasta IS NULL;

ALTER TABLE gondola_surtido ENABLE ROW LEVEL SECURITY;

-- El surtido es información comercial de la empresa, no de una ciudad:
-- lo lee cualquier usuario autenticado y lo escribe solo administración.
DROP POLICY IF EXISTS gondola_surtido_lectura ON gondola_surtido;
CREATE POLICY gondola_surtido_lectura ON gondola_surtido
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS gondola_surtido_escritura ON gondola_surtido;
CREATE POLICY gondola_surtido_escritura ON gondola_surtido
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM sadimex_profiles p
            WHERE p.id = auth.uid() AND p.rol IN ('admin', 'gerencia')
        )
    );

-- Vista de consulta: el surtido vigente, con lo que el análisis necesita.
CREATE OR REPLACE VIEW gondola_surtido_vigente AS
SELECT
    s.cadena_id,
    c.nombre AS cadena,
    k.id     AS sku_id,
    k.codigo,
    k.nombre AS sku,
    k.marca,
    k.categoria,
    k.es_prioritario
FROM gondola_surtido s
JOIN cadenas c       ON c.id = s.cadena_id
JOIN gondola_skus k  ON k.id = s.sku_id
WHERE s.vigente_hasta IS NULL
  AND k.activo;

-- Qué cadenas todavía no tienen surtido cargado por categoría. Mientras
-- una categoría aparezca acá, sus fotos se analizan contra el catálogo
-- entero y arrastran los falsos positivos que la tabla viene a evitar.
CREATE OR REPLACE VIEW gondola_surtido_faltante AS
SELECT
    c.id   AS cadena_id,
    c.nombre AS cadena,
    k.categoria,
    count(*) AS skus_en_catalogo
FROM cadenas c
CROSS JOIN (SELECT DISTINCT categoria FROM gondola_skus WHERE activo) cat
JOIN gondola_skus k ON k.categoria = cat.categoria AND k.activo
WHERE c.activo
  AND NOT EXISTS (
      SELECT 1 FROM gondola_surtido_vigente v
      WHERE v.cadena_id = c.id AND v.categoria = cat.categoria
  )
GROUP BY c.id, c.nombre, k.categoria
ORDER BY c.nombre, k.categoria;

-- Carga masiva del surtido de una cadena y categoría, por códigos de SKU.
-- Reemplaza lo que hubiera: cierra lo que ya no está en la lista y agrega
-- lo nuevo, en una sola transacción.
CREATE OR REPLACE FUNCTION gondola_cargar_surtido(
    p_cadena_nombre text,
    p_categoria     text,
    p_codigos       text[]
) RETURNS TABLE (accion text, detalle text)
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_cadena_id uuid;
    v_altas     int;
    v_bajas     int;
    v_faltantes text[];
BEGIN
    SELECT id INTO v_cadena_id FROM cadenas
    WHERE lower(nombre) = lower(trim(p_cadena_nombre)) AND activo;

    IF v_cadena_id IS NULL THEN
        RETURN QUERY SELECT 'error', format('no existe la cadena "%s"', p_cadena_nombre);
        RETURN;
    END IF;

    -- Códigos que no están en el catálogo: se avisan en vez de ignorarse
    -- en silencio, porque un código mal escrito deja el SKU fuera del
    -- surtido y el análisis nunca lo va a buscar.
    SELECT array_agg(cod) INTO v_faltantes
    FROM unnest(p_codigos) AS cod
    WHERE NOT EXISTS (SELECT 1 FROM gondola_skus k WHERE k.codigo = cod AND k.activo);

    -- Baja de lo que dejó de estar en la lista.
    WITH cerradas AS (
        UPDATE gondola_surtido s SET vigente_hasta = now()
        WHERE s.cadena_id = v_cadena_id
          AND s.vigente_hasta IS NULL
          AND s.sku_id IN (
              SELECT k.id FROM gondola_skus k
              WHERE k.categoria = p_categoria AND k.activo
                AND NOT (k.codigo = ANY (p_codigos))
          )
        RETURNING 1
    )
    SELECT count(*) INTO v_bajas FROM cerradas;

    -- Alta de lo nuevo. Si la fila existía cerrada, se reabre.
    WITH nuevas AS (
        INSERT INTO gondola_surtido (cadena_id, sku_id)
        SELECT v_cadena_id, k.id
        FROM gondola_skus k
        WHERE k.codigo = ANY (p_codigos) AND k.activo
        ON CONFLICT (cadena_id, sku_id)
        DO UPDATE SET vigente_hasta = NULL
        RETURNING 1
    )
    SELECT count(*) INTO v_altas FROM nuevas;

    RETURN QUERY SELECT
        'ok',
        format(
            '%s SKU en el surtido de %s / %s; %s dados de baja%s',
            v_altas, p_cadena_nombre, p_categoria, v_bajas,
            CASE WHEN v_faltantes IS NULL THEN ''
                 ELSE format('; códigos que no existen en el catálogo: %s',
                             array_to_string(v_faltantes, ', '))
            END
        );
END;
$$;

COMMIT;
