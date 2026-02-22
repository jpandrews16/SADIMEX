# SOP 04 — Generación del Scorecard Semanal
## SADIMEX Sales Intelligence | Layer 1: Architecture

**Última actualización:** 2026-02-21
**Tool correspondiente:** `tools/generate_scorecard.py`

---

## Objetivo
Agregar todos los `VisitAnalysis` de la semana para un vendedor y producir el `WeeklyScorecard`, el payload final del sistema.

## Inputs
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `vendedor_id` | UUID | ID del vendedor |
| `semana_inicio` | `YYYY-MM-DD` | Lunes de la semana a procesar |

## Outputs
- `WeeklyScorecard` persistido en Supabase o `.tmp/scorecard_<vendedor_id>_<semana_inicio>.json`
- Restricción UNIQUE: un scorecard por vendedor por semana (re-ejecutar sobreescribe)

## Pasos

1. **Calcular `semana_fin`** → `semana_inicio + 6 días`
2. **Cargar VisitAnalysis** → Filtrar por `vendedor_id` + rango de fechas
3. **Guard: 0 análisis** → Retornar `status: no_data` sin error
4. **Calcular métricas:**
   - `score_promedio` = media aritmética de `score_visita`
   - `tasa_cierre` = `count(cierre_exitoso=true) / total_visitas`
   - `marcas_con_brecha` = marcas faltantes en > 40% de visitas de la semana
   - `venta_perfecta_rate` = `count(score >= 80) / total_visitas`
   - `quiebres_detectados` = suma de visitas con `quiebre_de_stock = true`
5. **Calcular semáforo** → Basado en `score_promedio` y umbrales de `knowledge.json`
6. **Extraer top 3 coaching** → Deduplicar `sugerencia_tactica` de todos los VisitAnalysis
7. **Persistir** → Supabase con UPSERT por `(vendedor_id, semana_inicio)`

## Ejecución Semanal
El scorecard se genera **cada lunes** para la semana que terminó el domingo anterior.
El trigger (Fase 5) ejecuta: `generate_scorecard.py` para cada uno de los 13 vendedores.

## Reglas de Negocio
- `marcas_con_brecha`: umbral del 40% deliberado — si una marca falta en menos del 40% de visitas se considera variación normal, no brecha estructural.
- La `tendencia` (mejorando/estable/deteriorando) compara el scorecard actual con el de la semana anterior. Se implementa en versión 2.

## Edge Cases
| Caso | Comportamiento |
|------|---------------|
| Semana sin visitas analizadas | Retorna `{status: "no_data"}`, no genera scorecard |
| Solo 1 visita en la semana | Scorecard válido con `total_visitas = 1` |
| Scorecard ya existente | UPSERT sobrescribe (protege contra ejecuciones dobles del cron) |
