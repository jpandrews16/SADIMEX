# SOP 01 — Ingesta de Audio
## SADIMEX Sales Intelligence | Layer 1: Architecture

**Última actualización:** 2026-02-21
**Tool correspondiente:** `tools/ingest_audio.py`

---

## Objetivo
Registrar un archivo de audio de visita de campo en el sistema, validando su integridad y preparándolo para la pipeline de análisis.

## Inputs
| Campo | Tipo | Obligatorio | Descripción |
|-------|------|-------------|-------------|
| `archivo` | Path | ✅ | Ruta al archivo `.mp3`, `.wav` o `.m4a` |
| `vendedor_id` | UUID | ✅ | ID del vendedor que realizó la visita |
| `cliente_nombre` | String | ✅ | Nombre del punto de venta visitado |
| `ciudad` | Enum | ✅ | `LPZ`, `CBBA` o `SCZ` |

## Outputs
- Registro `AudioRecord` en Supabase con `estado = 'pendiente'`
- Copia del archivo en `.tmp/<uuid>.<ext>`
- JSON de confirmación con `audio_id`

## Pasos

1. **Validar extensión** → Rechazar si no es `.mp3`, `.wav`, `.m4a`
2. **Validar tamaño** → Rechazar si < 1 KB (archivo vacío o corrupto)
3. **Validar ciudad** → Rechazar si no es `LPZ`, `CBBA` o `SCZ`
4. **Generar UUID** → `audio_id = uuid4()`
5. **Copiar a `.tmp/`** → `shutil.copy2(origen, .tmp/<audio_id>.<ext>)`
6. **Crear AudioRecord** → Insert en `audio_records` con `estado = 'pendiente'`
7. **Fallback offline** → Si Supabase no disponible, guardar `<audio_id>_record.json` en `.tmp/`
8. **Retornar JSON** → `{status, audio_id, estado, persistence}`

## Reglas de Negocio
- Un audio con el mismo path puede ingresarse múltiples veces (crea nuevos AudioRecord — no se deduplica automáticamente).
- El `venddedor_id` no se valida contra la BD en este step (validación delegada al step de autenticación upstream).
- El archivo original **no se elimina** del path de origen. El sistema trabaja sobre la copia en `.tmp/`.

## Edge Cases
| Caso | Comportamiento |
|------|---------------|
| Archivo `.ogg` o `.mp4` | Rechazar con error descriptivo |
| Disco `.tmp/` lleno | Error `OSError` — registrar en `error_registry` de `progress.md` |
| Supabase timeout | Guardar en `.tmp/` automáticamente (modo offline) |
| audio_id colisión | Probabilidad despreciable (UUID4), no se maneja explícitamente |

## Errores Conocidos
*(Vacío — poblar con Self-Annealing cuando ocurran)*
