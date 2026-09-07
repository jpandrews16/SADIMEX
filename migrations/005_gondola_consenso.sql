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
