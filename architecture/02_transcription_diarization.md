# SOP 02 — Transcripción y Diarización
## SADIMEX Sales Intelligence | Layer 1: Architecture

**Última actualización:** 2026-02-21
**Tool correspondiente:** `tools/transcribe_diarize.py`

---

## Objetivo
Convertir el audio crudo de una visita en una transcripción diarizada que diferencie claramente los turnos del VENDEDOR y del CLIENTE, usando Gemini 1.5 Pro.

## Inputs
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `audio_id` | UUID | ID del `AudioRecord` con `estado = 'pendiente'` |

## Outputs
- `.tmp/<audio_id>_diarization.json` con array de segmentos etiquetados
- `AudioRecord.estado` actualizado a `'diarizado'`

## Pasos

1. **Cargar AudioRecord** → Desde Supabase (o `.tmp/<audio_id>_record.json` en offline)
2. **Actualizar estado** → `procesando`
3. **Subir audio a Gemini Files API** → `genai.upload_file(path)`
4. **Llamar Gemini 1.5 Pro** con prompt de diarización estricta
5. **Parsear JSON** → Limpiar markdown si Gemini lo incluye en respuesta
6. **Limpiar archivo de Gemini** → `genai.delete_file()` (evitar acumulación)
7. **Guardar en `.tmp/`** → `<audio_id>_diarization.json`
8. **Actualizar estado** → `diarizado`

## Prompt de Diarización
El prompt está hardcodeado en el tool como `DIARIZATION_PROMPT`. Contiene:
- Instrucción de etiquetado estricto (`VENDEDOR` / `CLIENTE`)
- Definición de rol por comportamiento en la conversación
- Reconocimiento de jerga boliviana (caserita, bono, combo, quiebre, etc.)
- Uso de `[ininteligible]` para audio de baja calidad
- Output format: JSON puro

## Reglas de Negocio
- **Diarización antes de análisis:** Es literalmente imposible correr `extract_kpis.py` si no hay segmentos con speaker `VENDEDOR`.
- El modelo es Gemini **1.5 Pro** (no Flash) para máxima precisión en diarización.
- Si `confianza_diarizacion = 'baja'`, el análisis se marca para revisión manual.

## Edge Cases
| Caso | Comportamiento |
|------|---------------|
| Audio < 10 segundos | Gemini puede devolver array vacío — registrar como error |
| Solo se escucha el CLIENTE | Gemini etiqueta todo como CLIENTE — `extract_kpis` rechazará el análisis |
| Respuesta no es JSON válido | Intentar limpiar markdown y re-parsear; si falla → estado `error` |
| Timeout de Gemini (>60s) | Estado `error`, no reintentar automáticamente |

## Errores Conocidos
*(Vacío — poblar con Self-Annealing cuando ocurran)*
