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
