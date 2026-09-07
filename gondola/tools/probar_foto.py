#!/usr/bin/env python3
"""Analiza una foto de góndola sin base de datos.

Todo el valor del sistema —leer la góndola, aplicar las 6 reglas, sacar el
score y los hallazgos— no necesita Supabase para nada. Esto corre el
pipeline completo contra una foto suelta y un catálogo en JSON, y muestra
el resultado en la terminal.

Sirve para tres cosas:
  * Ver el producto funcionando antes de tener nada desplegado.
  * Probar un cambio de prompt o de reglas contra una foto real.
  * Depurar por qué una foto dio el score que dio.

Uso
---
    export OPENROUTER_API_KEY=...
    python -m gondola.tools.probar_foto \\
        --foto ./gondola_ketal.jpg \\
        --catalogo gondola/catalogo.ejemplo.json

    # Con el catálogo real exportado del importador de Canva
    python -m gondola.tools.probar_foto \\
        --foto ./gondola.jpg --catalogo-csv ./packshots/catalogo.csv \\
        --categoria cafe

    # Guardar la observación cruda para revisarla
    python -m gondola.tools.probar_foto --foto f.jpg --catalogo cat.json --json salida.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gondola.app.catalog import (  # noqa: E402
    cargar_catalogo_local, resolver_precios, resolver_reglas, skus_desde_filas,
)
from gondola.app.config import get_settings  # noqa: E402
from gondola.app.reference_sheet import construir_hoja_referencia, preparar_foto_gondola  # noqa: E402
from gondola.app.rules import evaluar  # noqa: E402
from gondola.app.vision import analizar_foto  # noqa: E402

log = logging.getLogger("probar_foto")

SEMAFORO_COLOR = {"verde": "\033[92m", "amarillo": "\033[93m", "rojo": "\033[91m"}
SEVERIDAD_EMOJI = {"critico": "🔴", "alto": "🟠", "medio": "🟡", "bajo": "⚪"}
RESET = "\033[0m"
NEGRITA = "\033[1m"


def skus_desde_csv(ruta: Path, categoria: str = "") -> list:
    """Lee el CSV que produce el importador de Canva."""
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))

    registros = []
    for i, fila in enumerate(filas, start=1):
        if categoria and (fila.get("categoria") or "").strip().lower() != categoria.lower():
            continue
        if not fila.get("codigo") or not fila.get("nombre"):
            continue
        registros.append({
            "id": f"csv-{i}",
            "codigo": fila["codigo"].strip(),
            "nombre": fila["nombre"].strip(),
            "marca": (fila.get("marca") or "SIN MARCA").strip(),
            "categoria": (fila.get("categoria") or categoria or "general").strip(),
            "gramaje": (fila.get("gramaje") or "").strip() or None,
            "es_prioritario": str(fila.get("es_prioritario", "")).strip().lower() in {"1", "true", "si", "sí", "x"},
            "packshot_url": (fila.get("packshot_url") or "").strip() or None,
            "descripcion_visual": (fila.get("descripcion_visual") or "").strip() or None,
            "activo": True,
        })
    return skus_desde_filas(registros)


def barra(pct: float, ancho: int = 24) -> str:
    lleno = int(round(pct * ancho))
    return "█" * lleno + "░" * (ancho - lleno)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analiza una foto de góndola sin base de datos.")
    parser.add_argument("--foto", required=True)
    parser.add_argument("--catalogo", help="JSON de catálogo (ver catalogo.ejemplo.json)")
    parser.add_argument("--catalogo-csv", help="CSV del importador de Canva")
    parser.add_argument("--categoria", default="", help="Filtra el catálogo a una categoría")
    parser.add_argument("--cadena", default="", help="Nombre de cadena, para el contexto del prompt")
    parser.add_argument("--json", help="Guarda el resultado completo en este archivo")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level="INFO" if args.verbose else "WARNING",
        format="%(levelname)s :: %(message)s",
    )

    cfg = get_settings()
    if not cfg.openrouter_api_key:
        print("Falta OPENROUTER_API_KEY en el entorno.", file=sys.stderr)
        return 1

    if not args.catalogo and not args.catalogo_csv:
        print("Indica --catalogo (JSON) o --catalogo-csv.", file=sys.stderr)
        return 1

    # ── Catálogo ─────────────────────────────────────────────────────
    if args.catalogo_csv:
        skus = skus_desde_csv(Path(args.catalogo_csv), args.categoria)
        filas_reglas, filas_precios = [], []
    else:
        skus, filas_reglas, filas_precios = cargar_catalogo_local(args.catalogo)
        if args.categoria:
            skus = [s for s in skus if s.categoria.lower() == args.categoria.lower()]

    if not skus:
        print("El catálogo quedó vacío con esos filtros.", file=sys.stderr)
        return 1

    reglas = resolver_reglas(skus, filas_reglas, None)
    precios = resolver_precios(skus, filas_precios, None)

    ruta_foto = Path(args.foto)
    print(f"\n{NEGRITA}Analizando{RESET} {ruta_foto.name}")
    print(f"  catálogo : {len(skus)} SKU, {len({s.marca for s in skus})} marcas")
    print(f"  packshots: {sum(1 for s in skus if s.packshot_url)}/{len(skus)}")
    print(f"  precios  : {len(precios)} SKU con PVP cargado")
    print(f"  modelo   : {cfg.modelo_primario}")
    print(f"  estrategia si la lectura es dudosa: {cfg.estrategia_baja_confianza}\n")

    # ── Análisis ─────────────────────────────────────────────────────
    observacion, uso = analizar_foto(
        skus=skus,
        foto_data_url=preparar_foto_gondola(ruta_foto.read_bytes()),
        hoja_referencia=construir_hoja_referencia(skus),
        categoria=args.categoria,
        cadena=args.cadena,
    )

    evaluacion = evaluar(
        obs=observacion,
        skus=skus,
        reglas=reglas,
        precios=precios,
        umbral_deteccion=cfg.umbral_deteccion,
        umbral_verde=cfg.umbral_verde,
        umbral_amarillo=cfg.umbral_amarillo,
    )

    # ── Resultado ────────────────────────────────────────────────────
    color = SEMAFORO_COLOR.get(evaluacion.semaforo, "")
    print("=" * 68)
    print(f"{color}{NEGRITA}  SCORE: {evaluacion.score}/100   ({evaluacion.semaforo.upper()}){RESET}")
    print("=" * 68)

    print(f"\n{NEGRITA}LO QUE VIO EL MODELO{RESET}")
    print(f"  niveles visibles    : {observacion.niveles_visibles}"
          f" (altura de ojos: nivel {observacion.nivel_ojos or '?'})")
    print(f"  mueble completo     : {'sí' if observacion.mueble_completo_visible else 'NO — no se evalúa la altura'}")
    print(f"  calidad de la foto  : {observacion.calidad_foto}"
          f"{' — ' + observacion.motivo_calidad if observacion.motivo_calidad else ''}")
    print(f"  confianza           : {observacion.confianza_global:.0%}")
    print(f"  frentes del lineal  : {observacion.frentes_totales_lineal} (todas las marcas)")
    if evaluacion.share_of_shelf_pct is not None:
        print(f"  share of shelf      : {evaluacion.share_of_shelf_pct}%")

    if observacion.detecciones:
        print(f"\n{NEGRITA}PRODUCTOS DETECTADOS{RESET}")
        for d in sorted(observacion.detecciones, key=lambda x: (-x.nivel, x.bbox.x0)):
            marca = "  " if d.confianza >= cfg.umbral_deteccion else "✗ "
            nombre = next((s.nombre for s in skus if s.codigo == d.sku_codigo), d.sku_codigo)
            print(f"  {marca}nivel {d.nivel} · {d.frentes} frentes · {d.confianza:.0%} · {nombre}")
        if any(d.confianza < cfg.umbral_deteccion for d in observacion.detecciones):
            print(f"     (✗ = bajo el umbral de {cfg.umbral_deteccion:.0%}, no cuenta como presente)")

    if evaluacion.skus_ausentes:
        print(f"\n{NEGRITA}NO ENCONTRADOS{RESET} ({len(evaluacion.skus_ausentes)})")
        for codigo in evaluacion.skus_ausentes[:10]:
            print(f"  · {codigo}")
        if len(evaluacion.skus_ausentes) > 10:
            print(f"  ... y {len(evaluacion.skus_ausentes) - 10} más")

    print(f"\n{NEGRITA}LAS 6 REGLAS{RESET}")
    for nombre in ("presencia", "nivel", "frentes", "bloque", "etiqueta", "sin_quiebre"):
        r = evaluacion.reglas.get(nombre)
        if r is None:
            print(f"  {'—':>2} {nombre:<12} no evaluable con esta foto")
            continue
        marca = "✓" if r.cumple else "✗"
        print(f"  {marca:>2} {nombre:<12} {barra(r.cumplimiento)} {r.cumplimiento:>4.0%}  {r.detalle[:60]}")

    if evaluacion.hallazgos:
        print(f"\n{NEGRITA}QUÉ HAY QUE CORREGIR{RESET} ({len(evaluacion.hallazgos)})")
        for h in evaluacion.hallazgos:
            print(f"  {SEVERIDAD_EMOJI.get(h.severidad, '·')} {h.mensaje}")
            print(f"     → {h.accion}")
    else:
        print(f"\n{NEGRITA}Sin observaciones.{RESET} La góndola cumple todas las reglas.")

    print(f"\n{NEGRITA}COSTO{RESET}")
    print(f"  {uso.lecturas} lectura(s) · {uso.modelo}")
    if uso.nota_consenso:
        print(f"  consenso: {uso.nota_consenso}")
    print(f"  {uso.costo_usd:.5f} USD  ({uso.costo_usd * 1000:.2f} USD por cada 1.000 fotos)")
    print(f"  {uso.duracion_ms} ms\n")

    if args.json:
        Path(args.json).write_text(
            json.dumps({
                "observacion": observacion.model_dump(mode="json"),
                "evaluacion": evaluacion.model_dump(mode="json"),
                "uso": uso.model_dump(mode="json"),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Resultado completo en {args.json}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
