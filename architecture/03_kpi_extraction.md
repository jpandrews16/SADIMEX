# SOP 03 — Extracción de KPIs
## SADIMEX Sales Intelligence | Layer 1: Architecture

**Última actualización:** 2026-02-21
**Tool correspondiente:** `tools/extract_kpis.py`

---

## Objetivo
Usar la diarización y el catálogo Sadimex para extraer KPIs cuantitativos y generar coaching insights cualitativos de tono constructivo. Persiste un `VisitAnalysis` completo.

## Inputs
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `audio_id` | UUID | ID del audio con `estado = 'diarizado'` |

## Outputs
- `VisitAnalysis` persistido en Supabase o `.tmp/<audio_id>_analysis.json`
- Score 0-100 y semáforo verde/amarillo/rojo

## Gate de Diarización Estricta (REGLA DE ORO)
Antes de llamar a Gemini, el tool valida que exista al menos un segmento con `speaker = 'VENDEDOR'`.
**Si no hay segmentos VENDEDOR → el tool aborta con código de salida 1.**
Esto previene análisis basados solo en el habla del cliente.

## Pasos

1. **Cargar diarización** → `.tmp/<audio_id>_diarization.json`
2. **Gate check** → Verificar existencia de segmentos `VENDEDOR`
3. **Cargar KnowledgeBase** → `knowledge.json`
4. **Construir prompt** → Incluye diálogo formateado + catálogo + criterios de Venta Perfecta + umbrales
5. **Llamar Gemini 1.5 Flash** → Temperatura 0.2 para determinismo
6. **Parsear JSON** → Limpiar markdown
7. **Calcular `score_visita`** → Basado en `venta_perfecta_score` + penalizaciones
8. **Asignar semáforo** → Según umbrales en `knowledge.json`
9. **Persistir VisitAnalysis** → Supabase o `.tmp/`

## Lógica del Score
```
score_visita ≈ venta_perfecta_score (calculado por Gemini según pesos en knowledge.json)
semáforo:
  verde   → score >= 80
  amarillo → score 60-79
  rojo    → score < 60
```

## Tono de Coaching (REGLA CONDUCTUAL)
Los `coaching_insights` deben seguir siempre este patrón:
- `observacion`: Qué ocurrió en la conversación (neutro, factual)
- `sugerencia_tactica`: Qué hacer diferente (constructivo, específico, en español)

❌ **Prohibido:** "El vendedor no hizo X" (punitivo)
✅ **Correcto:** "Para la próxima visita, considera mencionar Wild Protein cuando el cliente pida bebidas energéticas."

## Edge Cases
| Caso | Comportamiento |
|------|---------------|
| `marcas_mencionadas` vacío | Brecha de portafolio total — coaching prioritario |
| Gemini devuelve score > 100 | Normalizar a 100 |
| `precio_correcto = false` | Siempre genera coaching_insight de categoría `precio` |
