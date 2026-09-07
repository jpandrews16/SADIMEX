#!/usr/bin/env python3
"""Mide el conteo de productos contra SKU-110K, con anotaciones reales.

Qué mide y qué NO
-----------------
SKU-110K son 11.762 fotos de góndolas de supermercados de todo el mundo con
1,73 millones de productos marcados a mano. Pero **etiqueta todo como una
sola clase "object"**: no dice qué SKU es cada cosa.

Así que este evaluador NO puede decir si acertamos el SKU —para eso hacen
falta fotos de tus salas anotadas por alguien que conozca el catálogo—.
Lo que sí mide, con verdad de referencia real, es el **conteo de productos
en el lineal**: nuestro `frentes_totales_lineal`.

Ese número no es un detalle: es el **denominador del share of shelf**. Si
el conteo total está inflado, el share of shelf sale bajo y parece que
perdimos espacio que no perdimos. Si está corto, pasa lo contrario. Y
contar objetos repetidos es justo lo que un modelo de visión hace peor.

Uso
---
    export OPENROUTER_API_KEY=...
    python -m gondola.tools.evaluar_sku110k --imagenes 8

    # Sobre las fotos menos densas, que se parecen más a un tramo de góndola
    python -m gondola.tools.evaluar_sku110k --imagenes 6 --max-productos 120

    # Guardar el detalle para comparar después de un cambio de prompt
    python -m gondola.tools.evaluar_sku110k --imagenes 8 --salida antes.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gondola.app.config import get_settings  # noqa: E402
from gondola.app.reference_sheet import preparar_foto_gondola  # noqa: E402
from gondola.app.schemas import Sku  # noqa: E402
from gondola.app.vision import VisionError, _llamar_con_reintento, _normalizar  # noqa: E402
from gondola.app.prompt import construir_mensajes  # noqa: E402

SHARD = (
    "https://huggingface.co/datasets/PrashantDixit0/SKU-110K/"
    "resolve/main/data/train-00000-of-00235.parquet"
)

# El catálogo tiene que ser el de producción: SKU reales y acotados.
#
# El primer intento usó un SKU genérico ("cualquier producto envasado") y
# eso rompió la medición: el modelo trató de enumerar los 42-260 productos
# de la foto uno por uno, la salida se pasó del tope de tokens y el JSON
# llegó cortado en 7 de 8 fotos. En producción nunca pasa eso —el catálogo
# son estos SKU y solo estos se enumeran en `detecciones`; todo lo demás
# (la competencia, que en una góndola es casi todo) va como un número en
# `frentes_totales_lineal`.
#
# Estas son marcas bolivianas/colombianas que no aparecen en SKU-110K
# (fotos de supermercados de EEUU e Israel), así que `detecciones` sale
# vacía —lo correcto— y el conteo total queda como único campo a medir.
CATALOGO_EVAL = [
    Sku(
        id="eval-1", codigo="COLCAFE-MOCCA-108G", nombre="Cappuccino Mocca",
        marca="Colcafé", categoria="cafe", gramaje="108 g",
        descripcion_visual="Caja roja de cappuccino instantáneo.",
    ),
    Sku(
        id="eval-2", codigo="COLCAFE-VAINILLA-108G", nombre="Cappuccino Vainilla",
        marca="Colcafé", categoria="cafe", gramaje="108 g",
        descripcion_visual="Caja azul de cappuccino instantáneo.",
    ),
    Sku(
        id="eval-3", codigo="NOEL-FESTIVAL-200G", nombre="Festival",
        marca="Noel", categoria="galletas", gramaje="200 g",
        descripcion_visual="Paquete rojo de galletas rellenas.",
    ),
]
CODIGOS_EVAL = {s.codigo for s in CATALOGO_EVAL}


def cargar_muestra(limite: int, max_productos: int, ruta_local: str | None):
    """Devuelve [(image_id, bytes, n_productos)] ordenado de menos a más denso."""
    import pyarrow.parquet as pq

    if ruta_local:
        f = pq.ParquetFile(ruta_local)
    else:
        import fsspec

        print("Leyendo SKU-110K desde HuggingFace...")
        f = pq.ParquetFile(fsspec.filesystem("http").open(SHARD))

    tabla = f.read(columns=["image_id", "objects"]).to_pylist()
    candidatas = sorted(
        ((r["image_id"], len(r["objects"])) for r in tabla),
        key=lambda x: x[1],
    )
    if max_productos:
        candidatas = [c for c in candidatas if c[1] <= max_productos]
    elegidas = {c[0] for c in candidatas[:limite]}
    if not elegidas:
        raise SystemExit("Ninguna imagen cumple el filtro de densidad.")

    print(f"Descargando {len(elegidas)} imágenes...")
    completa = f.read(columns=["image_id", "image", "objects"]).to_pylist()
    muestra = [
        (r["image_id"], r["image"]["bytes"], len(r["objects"]))
        for r in completa
        if r["image_id"] in elegidas
    ]
    return sorted(muestra, key=lambda x: x[2])


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalúa el conteo contra SKU-110K.")
    parser.add_argument("--imagenes", type=int, default=6)
    parser.add_argument(
        "--max-productos", type=int, default=0,
        help="Descarta fotos con más productos que esto. 0 = sin filtro.",
    )
    parser.add_argument("--parquet", help="Shard local, si ya lo bajaste")
    parser.add_argument("--salida", help="Guarda el detalle en este JSON")
    args = parser.parse_args()

    cfg = get_settings()
    if not cfg.openrouter_api_key:
        print("Falta OPENROUTER_API_KEY.", file=sys.stderr)
        return 1

    muestra = cargar_muestra(args.imagenes, args.max_productos, args.parquet)

    import httpx

    print(f"\nModelo: {cfg.modelo_primario}")
    print(f"{'imagen':<16} {'real':>6} {'contado':>8} {'error':>8} {'error %':>8} {'ms':>7} {'det':>4}")
    print("-" * 66)

    filas = []
    with httpx.Client() as client:
        for image_id, datos, real in muestra:
            mensajes = construir_mensajes(CATALOGO_EVAL, preparar_foto_gondola(datos))
            try:
                bruto, uso, ms = _llamar_con_reintento(client, cfg.modelo_primario, mensajes)
                obs = _normalizar(bruto, CODIGOS_EVAL)
            except (VisionError, httpx.HTTPError) as exc:
                print(f"{image_id:<16} {real:>6} {'FALLO':>8}  {str(exc)[:30]}")
                filas.append({"image_id": image_id, "real": real, "contado": None})
                continue

            contado = obs.frentes_totales_lineal
            error = contado - real
            error_pct = 100 * error / real if real else 0
            print(
                f"{image_id:<16} {real:>6} {contado:>8} {error:>+8} "
                f"{error_pct:>+7.0f}% {ms:>7} {len(obs.detecciones):>4}"
            )
            filas.append({
                "image_id": image_id, "real": real, "contado": contado,
                "error": error, "error_pct": round(error_pct, 1),
                "confianza": obs.confianza_global, "ms": ms,
                # Debería ser 0: el catálogo son marcas que no existen en
                # estas fotos. Si sale >0, el modelo está inventando SKU.
                "detecciones": len(obs.detecciones),
                "tokens_salida": (uso.get("completion_tokens") or 0),
                "costo_usd": float(uso.get("cost") or 0.0),
            })

    validas = [f for f in filas if f.get("contado") is not None]
    if not validas:
        print("\nNinguna imagen se pudo analizar.")
        return 1

    errores = [f["error"] for f in validas]
    errores_pct = [abs(f["error_pct"]) for f in validas]

    print("-" * 66)
    print(f"\n{'RESULTADO':<28} {len(validas)}/{len(filas)} imágenes analizadas")
    print(f"{'error absoluto medio':<28} {statistics.mean(abs(e) for e in errores):.1f} productos")
    print(f"{'error relativo medio':<28} {statistics.mean(errores_pct):.0f}%")
    print(f"{'sesgo (+ sobrecuenta)':<28} {statistics.mean(errores):+.1f} productos")
    print(f"{'costo total':<28} {sum(f['costo_usd'] for f in validas):.4f} USD")
    inventadas = sum(f["detecciones"] for f in validas)
    print(f"{'SKU propios inventados':<28} {inventadas} (debería ser 0)")

    # Lo que de verdad importa para el negocio: cuánto se desvía el share
    # of shelf si el denominador está mal contado.
    print(f"\n{'Qué significa para el share of shelf':<40}")
    for pct in (10, 25, 50):
        cercanas = sum(1 for e in errores_pct if e <= pct)
        print(f"  fotos con el conteo dentro de ±{pct:>2}%: {cercanas}/{len(validas)}")

    if args.salida:
        Path(args.salida).write_text(
            json.dumps({"modelo": cfg.modelo_primario, "filas": filas}, indent=2),
            encoding="utf-8",
        )
        print(f"\nDetalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
