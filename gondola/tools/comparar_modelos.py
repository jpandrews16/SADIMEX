#!/usr/bin/env python3
"""Compara modelos de visión sobre TUS fotos reales.

Elegir el modelo por lo que dice un benchmark público es adivinar. Una
góndola de Ketal con reflejo de tubo fluorescente no se parece a nada de
un benchmark. Esta herramienta corre varios modelos sobre las mismas
fotos y te dice, con números, cuál acierta más y cuánto cuesta cada uno.

Uso
---
1) Anota a mano la verdad de unas 20-30 fotos:

   fotos/
     ketal_calacoto_01.jpg
     ketal_calacoto_01.json      <- verdad anotada por una persona

   El JSON de verdad solo necesita lo que importa medir:

     {
       "skus_presentes": ["NOEL-FESTIVAL-200", "WILD-FRESA"],
       "frentes": {"NOEL-FESTIVAL-200": 4, "WILD-FRESA": 2},
       "niveles": {"NOEL-FESTIVAL-200": 4},
       "precios": {"NOEL-FESTIVAL-200": 12.5}
     }

2) Corre la comparación:

   python -m gondola.tools.comparar_modelos \\
       --fotos ./fotos \\
       --catalogo gondola/catalogo.ejemplo.json \\
       --modelos google/gemini-2.5-flash-lite,qwen/qwen3-vl-32b-instruct,google/gemini-2.5-flash

Métricas
--------
  precision  de los SKU que el modelo dijo ver, cuántos estaban de verdad.
             Bajo = el modelo alucina productos nuestros donde no hay.
  recall     de los SKU que estaban, cuántos vio.
             Bajo = el modelo no ve nuestro producto y lo reportamos como quiebre falso.
  frentes    error absoluto medio en el conteo de caras.
  precios    aciertos de lectura de precio sobre las etiquetas anotadas.
  costo      USD reales por foto, según lo que reporta OpenRouter.

Para auditoría de góndola el recall pesa más: un falso quiebre manda a un
supervisor a una sala donde no había problema, y eso quema la confianza en
el sistema más rápido que cualquier otra cosa.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Optional

import httpx

# Permite correr el script desde la raíz del repo sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gondola.app.catalog import cargar_catalogo_local  # noqa: E402
from gondola.app.config import get_settings  # noqa: E402
from gondola.app.reference_sheet import construir_hoja_referencia, preparar_foto_gondola  # noqa: E402
from gondola.app.schemas import Observacion, Sku  # noqa: E402
from gondola.app.vision import VisionError, _llamar_modelo, _normalizar  # noqa: E402
from gondola.app.prompt import construir_mensajes  # noqa: E402

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}


def _analizar_con(modelo: str, skus: list[Sku], foto: Path, hoja: Optional[str],
                  client: httpx.Client) -> tuple[Observacion, dict, int]:
    mensajes = construir_mensajes(skus, preparar_foto_gondola(foto.read_bytes()), hoja)
    bruto, uso, ms = _llamar_modelo(client, modelo, mensajes)
    return _normalizar(bruto, {s.codigo for s in skus}), uso, ms


def _metricas(obs: Observacion, verdad: dict, umbral: float) -> dict:
    dichos = {d.sku_codigo for d in obs.detecciones if d.confianza >= umbral}
    reales = set(verdad.get("skus_presentes", []))

    aciertos = dichos & reales
    precision = len(aciertos) / len(dichos) if dichos else (1.0 if not reales else 0.0)
    recall = len(aciertos) / len(reales) if reales else 1.0

    errores_frentes = []
    frentes_obs: dict[str, int] = {}
    for d in obs.detecciones:
        if d.confianza >= umbral:
            frentes_obs[d.sku_codigo] = frentes_obs.get(d.sku_codigo, 0) + d.frentes
    for codigo, esperado in (verdad.get("frentes") or {}).items():
        errores_frentes.append(abs(frentes_obs.get(codigo, 0) - esperado))

    niveles_ok, niveles_total = 0, 0
    nivel_obs = {d.sku_codigo: d.nivel for d in obs.detecciones}
    for codigo, esperado in (verdad.get("niveles") or {}).items():
        niveles_total += 1
        if nivel_obs.get(codigo) == esperado:
            niveles_ok += 1

    precios_ok, precios_total = 0, 0
    precio_obs = {e.sku_asociado: e.precio_leido for e in obs.etiquetas if e.sku_asociado}
    for codigo, esperado in (verdad.get("precios") or {}).items():
        precios_total += 1
        leido = precio_obs.get(codigo)
        if leido is not None and abs(leido - esperado) < 0.01:
            precios_ok += 1

    return {
        "precision": precision,
        "recall": recall,
        "falsos_positivos": sorted(dichos - reales),
        "no_vistos": sorted(reales - dichos),
        "error_frentes": statistics.mean(errores_frentes) if errores_frentes else None,
        "niveles_ok": niveles_ok,
        "niveles_total": niveles_total,
        "precios_ok": precios_ok,
        "precios_total": precios_total,
        "confianza_reportada": obs.confianza_global,
    }


def _promedio(valores: list) -> Optional[float]:
    limpios = [v for v in valores if v is not None]
    return statistics.mean(limpios) if limpios else None


def _fmt(valor: Optional[float], sufijo: str = "", decimales: int = 3) -> str:
    return "—" if valor is None else f"{valor:.{decimales}f}{sufijo}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara modelos de visión sobre fotos de góndola.")
    parser.add_argument("--fotos", required=True, help="Carpeta con las fotos y sus .json de verdad")
    parser.add_argument("--catalogo", required=True, help="JSON de catálogo (ver catalogo.ejemplo.json)")
    parser.add_argument("--modelos", required=True, help="IDs de OpenRouter separados por coma")
    parser.add_argument("--salida", default="comparacion_modelos.json")
    parser.add_argument("--umbral", type=float, default=None, help="Umbral de detección (default: el de config)")
    args = parser.parse_args()

    cfg = get_settings()
    if not cfg.openrouter_api_key:
        print("Falta OPENROUTER_API_KEY en el entorno.", file=sys.stderr)
        return 1

    umbral = args.umbral if args.umbral is not None else cfg.umbral_deteccion
    skus, _, _ = cargar_catalogo_local(args.catalogo)
    hoja = construir_hoja_referencia(skus)

    carpeta = Path(args.fotos)
    fotos = sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES)
    if not fotos:
        print(f"No se encontraron fotos en {carpeta}", file=sys.stderr)
        return 1

    con_verdad = [f for f in fotos if f.with_suffix(".json").exists()]
    print(f"{len(fotos)} fotos, {len(con_verdad)} con verdad anotada.")
    if not con_verdad:
        print("Sin archivos de verdad no se puede medir precisión. Anota al menos 20 fotos.",
              file=sys.stderr)
        return 1

    modelos = [m.strip() for m in args.modelos.split(",") if m.strip()]
    resultados: dict[str, dict] = {}

    with httpx.Client() as client:
        for modelo in modelos:
            print(f"\n=== {modelo} ===")
            por_foto, costos, tiempos, fallos = [], [], [], 0

            for foto in con_verdad:
                verdad = json.loads(foto.with_suffix(".json").read_text(encoding="utf-8"))
                try:
                    obs, uso, ms = _analizar_con(modelo, skus, foto, hoja, client)
                except (VisionError, httpx.HTTPError) as exc:
                    print(f"  {foto.name}: FALLO — {exc}")
                    fallos += 1
                    continue

                m = _metricas(obs, verdad, umbral)
                m["foto"] = foto.name
                m["costo_usd"] = float(uso.get("cost") or 0.0)
                por_foto.append(m)
                costos.append(m["costo_usd"])
                tiempos.append(ms)

                print(
                    f"  {foto.name}: precision {m['precision']:.2f} | recall {m['recall']:.2f}"
                    f" | precios {m['precios_ok']}/{m['precios_total']}"
                    f" | {m['costo_usd']:.5f} USD"
                )

            if not por_foto:
                resultados[modelo] = {"error": "ninguna foto se pudo analizar", "fallos": fallos}
                continue

            resultados[modelo] = {
                "fotos": len(por_foto),
                "fallos": fallos,
                "precision": _promedio([m["precision"] for m in por_foto]),
                "recall": _promedio([m["recall"] for m in por_foto]),
                "error_frentes": _promedio([m["error_frentes"] for m in por_foto]),
                "niveles_acierto": (
                    sum(m["niveles_ok"] for m in por_foto)
                    / max(1, sum(m["niveles_total"] for m in por_foto))
                ),
                "precios_acierto": (
                    sum(m["precios_ok"] for m in por_foto)
                    / max(1, sum(m["precios_total"] for m in por_foto))
                ),
                "costo_promedio_usd": _promedio(costos),
                "costo_1000_fotos_usd": (_promedio(costos) or 0) * 1000,
                "ms_promedio": _promedio([float(t) for t in tiempos]),
                "detalle": por_foto,
            }

    print("\n" + "=" * 100)
    print(f"{'MODELO':<42} {'PREC':>6} {'RECALL':>7} {'NIVEL':>7} {'PRECIO':>7} "
          f"{'USD/1k':>9} {'ms':>7}")
    print("-" * 100)
    for modelo, r in resultados.items():
        if "error" in r:
            print(f"{modelo:<42} {r['error']}")
            continue
        print(
            f"{modelo:<42} {_fmt(r['precision'], decimales=3):>6} {_fmt(r['recall'], decimales=3):>7} "
            f"{_fmt(r['niveles_acierto'], decimales=3):>7} {_fmt(r['precios_acierto'], decimales=3):>7} "
            f"{_fmt(r['costo_1000_fotos_usd'], decimales=2):>9} {_fmt(r['ms_promedio'], decimales=0):>7}"
        )
    print("=" * 100)
    print("Para auditoría de góndola prioriza RECALL: un falso quiebre manda a un")
    print("supervisor a una sala donde no había problema.")

    Path(args.salida).write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalle completo en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
