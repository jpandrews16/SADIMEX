# 🔍 findings.md — Research, Discoveries & Constraints

> **Protocol:** B.L.A.S.T. | **Phase:** 0 — Initialization
> **Last Updated:** 2026-02-21

---

## Discoveries

| # | Fecha | Finding | Impacto |
|---|-------|---------|---------|
| 1 | 2026-02-21 | Directorio limpio — no existe código previo | Neutral |
| 2 | 2026-02-21 | `google-generativeai` DEPRECATED. Usar `google-genai` (`google.genai.Client()`) | Alto — afecta todos los tools |
| 3 | 2026-02-21 | `gemini-1.5-*` no disponible para esta API key. Modelos activos: `gemini-2.5-flash`, `gemini-2.5-pro` | Alto — afecta configuración de modelos en `.env` |
| 4 | 2026-02-21 | gTTS genera MP3 de voz española correctamente para fixtures de prueba | Positivo — fixture de 534KB usado en demo exitoso |
| 5 | 2026-02-21 | Gemini 2.5 Pro diariza español boliviano con **confianza: alta** y 18 segmentos correctos en fixture de prueba | Positivo — valida la arquitectura core |

---

## API / Integration Research

> ⚠️ No integrations defined yet. Will populate after Discovery Q2 is answered.

---

## Constraints & Gotchas

> ⚠️ None documented yet.

---

## GitHub / External Resources

> ⚠️ Research not started. Will conduct once Blueprint is approved.

---

## Notes

- This file is updated after any meaningful discovery during research or execution.
- Do NOT overwrite — always append new rows to tables.
