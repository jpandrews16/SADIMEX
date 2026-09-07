#!/usr/bin/env python3
"""Mide el acierto de SKU contra fotos de nuestras salas, anotadas a mano.

Por qué esta herramienta y no `evaluar_sku110k.py`
--------------------------------------------------
SKU-110K etiqueta todos los productos como una sola clase "objeto", así que
sirve para medir el CONTEO del lineal y nada más. Lo que decide si este
sistema sirve —si acierta QUÉ SKU es cada cosa— solo se puede medir con
fotos de nuestras salas y alguien que conozca el catálogo diciendo qué hay
en cada una.

Qué mide
--------
Presencia por SKU, que es de lo que cuelgan las reglas de presencia,
bloque y etiqueta:

  * **Recall**: de los SKU que SÍ estaban, cuántos encontró. Lo que se
    pierde acá son quiebres falsos: el sistema dice que falta un producto
    que estaba, y alguien va a la sala en vano.
  * **Precisión**: de los SKU que reportó, cuántos estaban de verdad. Lo
    que se pierde acá es peor: un producto ausente que figura presente
    tapa un quiebre real.

Se informan por separado a propósito. Un promedio de los dos escondería
justo la diferencia que importa para decidir en qué confiar.

Formato de las anotaciones (CSV)
--------------------------------
    foto,skus
    f01.jpg,DUCALES;SALTIN-NOEL
    f02.jpg,DUCALES
    f03.jpg,

Una fila por foto. `skus` son códigos del catálogo separados por punto y
coma. Vacío = en esa foto no hay ningún producto nuestro, que es un caso
que hay que incluir: es donde se ven los falsos positivos.

Uso
---
    export OPENROUTER_API_KEY=...
    python -m gondola.tools.evaluar_salas \\
        --fotos ./fotos_sala --catalogo ./catalogo.json \\
        --anotaciones ./anotaciones.csv --salida resultado.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from gondola.app.config import get_settings  # noqa: E402
from gondola.app.reference_sheet import (  # noqa: E402
    construir_hoja_referencia,
    preparar_foto_gondola,
)
from gondola.app.schemas import Sku  # noqa: E402
from gondola.app.vision import VisionError, analizar_foto  # noqa: E402

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}


def cargar_catalogo(ruta: Path) -> list[Sku]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return [Sku(**s) for s in datos["skus"] if s.get("activo", True)]


def cargar_anotaciones(ruta: Path) -> dict[str, set[str]]:
    """Devuelve {nombre_de_foto: {codigos}}. Una foto sin SKU es válida."""
    anotaciones: dict[str, set[str]] = {}
    with ruta.open(encoding="utf-8-sig") as fh:
        for fila in csv.DictReader(fh):
            foto = (fila.get("foto") or "").strip()
            if not foto:
                continue
            crudo = (fila.get("skus") or "").strip()
            anotaciones[foto] = {c.strip() for c in crudo.split(";") if c.strip()}
    return anotaciones


def main() -> int:
    parser = argparse.ArgumentParser(description="Mide el acierto de SKU en fotos de sala.")
    parser.add_argument("--fotos", required=True, help="Carpeta con las fotos")
    parser.add_argument("--catalogo", required=True, help="Catálogo JSON")
    parser.add_argument("--anotaciones", required=True, help="CSV foto,skus")
    parser.add_argument(
        "--mapa",
        help=(
            "JSON {codigo_sku: grupo}. El modelo trabaja con el catálogo fino "
            "—que es lo real y lo difícil— pero se puntúa contra el grupo. "
            "Sirve cuando quien anotó las fotos apuntó la marca y no la "
            "variante exacta: mide identificación real sin inventar una "
            "verdad de referencia que nadie verificó."
        ),
    )
    parser.add_argument("--categoria", default="galletas")
    parser.add_argument("--cadena", default="")
    parser.add_argument("--salida", help="Guarda el detalle en este JSON")
    args = parser.parse_args()

    cfg = get_settings()
    if not cfg.openrouter_api_key:
        print("Falta OPENROUTER_API_KEY.", file=sys.stderr)
        return 1

    skus = cargar_catalogo(Path(args.catalogo))
    mapa: dict[str, str] = (
        json.loads(Path(args.mapa).read_text(encoding="utf-8")) if args.mapa else {}
    )
    esperado = cargar_anotaciones(Path(args.anotaciones))
    carpeta = Path(args.fotos)
    fotos = sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES)
    if not fotos:
        print(f"No hay fotos en {carpeta}", file=sys.stderr)
        return 1

    # La hoja se arma una vez y viaja en todas las llamadas.
    hoja = construir_hoja_referencia(skus)
    if hoja is None:
        print("Sin packshots: el modelo solo tiene la descripción de texto.\n")

    print(f"Modelo: {cfg.modelo_primario}   {len(fotos)} fotos, {len(skus)} SKU\n")
    print(f"{'foto':<12} {'esperado':<28} {'detectado':<28} {'':<6}")
    print("-" * 78)

    # aciertos[codigo] = [verdaderos_positivos, falsos_positivos, falsos_negativos]
    conteo: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    filas = []

    with httpx.Client() as client:
        for foto in fotos:
            real = esperado.get(foto.name)
            if real is None:
                print(f"{foto.name:<12} (sin anotación, se salta)")
                continue

            try:
                obs, uso = analizar_foto(
                    skus,
                    preparar_foto_gondola(foto.read_bytes()),
                    hoja_referencia=hoja,
                    categoria=args.categoria,
                    cadena=args.cadena,
                    client=client,
                )
            except (VisionError, httpx.HTTPError) as exc:
                print(f"{foto.name:<12} FALLO  {str(exc)[:50]}")
                filas.append({"foto": foto.name, "error": str(exc)[:300]})
                continue

            detectado = {
                mapa.get(d.sku_codigo, d.sku_codigo)
                for d in obs.detecciones
                if d.confianza >= cfg.umbral_deteccion
            }
            for codigo in real | detectado:
                if codigo in real and codigo in detectado:
                    conteo[codigo][0] += 1
                elif codigo in detectado:
                    conteo[codigo][1] += 1
                else:
                    conteo[codigo][2] += 1

            marca = "OK" if real == detectado else "≠"
            print(
                f"{foto.name:<12} {';'.join(sorted(real)) or '—':<28} "
                f"{';'.join(sorted(detectado)) or '—':<28} {marca}"
            )
            filas.append({
                "foto": foto.name,
                "esperado": sorted(real),
                "detectado": sorted(detectado),
                # La confianza de cada detección, para poder barrer el
                # umbral después sin volver a pagar las llamadas. El 0.60
                # que hay hoy se puso a ojo y nunca se midió.
                "confianzas": sorted(
                    ({"sku": d.sku_codigo, "grupo": mapa.get(d.sku_codigo, d.sku_codigo),
                      "confianza": round(d.confianza, 3),
                      "frentes": d.frentes, "nivel": d.nivel} for d in obs.detecciones),
                    key=lambda x: -x["confianza"],
                ),
                "frentes_lineal": obs.frentes_totales_lineal,
                "niveles": obs.niveles_visibles,
                "calidad": obs.calidad_foto,
                "confianza": obs.confianza_global,
                "etiquetas": len(obs.etiquetas),
                "huecos": len(obs.huecos),
                "costo_usd": uso.costo_usd,
                "ms": uso.duracion_ms,
            })

    validas = [f for f in filas if "error" not in f]
    if not validas:
        print("\nNinguna foto se pudo analizar.")
        return 1

    print("-" * 78)
    print(f"\n{'SKU':<16} {'estaba':>7} {'encontró':>9} {'recall':>8} {'precisión':>10}")
    for codigo in sorted(conteo):
        vp, fp, fn = conteo[codigo]
        recall = vp / (vp + fn) if vp + fn else 0.0
        precision = vp / (vp + fp) if vp + fp else 0.0
        print(
            f"{codigo:<16} {vp + fn:>7} {vp + fp:>9} "
            f"{recall:>7.0%} {precision:>10.0%}"
        )

    vp = sum(c[0] for c in conteo.values())
    fp = sum(c[1] for c in conteo.values())
    fn = sum(c[2] for c in conteo.values())
    print(f"\n{'TOTAL':<16} {vp + fn:>7} {vp + fp:>9} "
          f"{vp / (vp + fn) if vp + fn else 0:>7.0%} "
          f"{vp / (vp + fp) if vp + fp else 0:>10.0%}")

    exactas = sum(1 for f in validas if f["esperado"] == f["detectado"])
    print(f"\n{'fotos clavadas (mismo conjunto de SKU)':<44} {exactas}/{len(validas)}")
    print(f"{'quiebres falsos (dijo que faltaba y estaba)':<44} {fn}")
    print(f"{'ausencias tapadas (dijo que estaba y no)':<44} {fp}")
    print(f"{'costo total':<44} {sum(f['costo_usd'] for f in validas):.4f} USD")
    print(f"{'latencia mediana':<44} "
          f"{sorted(f['ms'] for f in validas)[len(validas) // 2] / 1000:.1f} s")

    if args.salida:
        Path(args.salida).write_text(
            json.dumps({"modelo": cfg.modelo_primario, "filas": filas}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nDetalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
