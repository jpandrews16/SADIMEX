#!/usr/bin/env python3
"""Unifica las marcas escritas de varias formas en el catálogo borrador.

El modelo lee cada envase por separado, así que la misma marca sale
escrita distinto según la página: `COLCAFÉ`, `Colcafe`, `Colcaf`;
`CHOCO LISTO` y `CHOCOLISTO`. Para una persona es obvio que son la misma;
para el sistema no: las reglas de góndola se resuelven por nombre de
marca, y `Colcafe` no coincide con `COLCAFÉ`.

Este script agrupa las variantes y deja una sola forma por marca. No usa
IA: compara los nombres ignorando tildes, mayúsculas y separadores, y
después fusiona los que se parecen mucho. Todo lo que fusiona lo reporta,
para que puedas revisarlo y deshacerlo si se equivocó.

Uso
---
    # Ver qué haría, sin tocar el archivo
    python -m gondola.tools.normalizar_marcas --csv packshots/catalogo.csv

    # Aplicar los cambios (guarda una copia .bak del original)
    python -m gondola.tools.normalizar_marcas --csv packshots/catalogo.csv --aplicar

    # Forzar una forma concreta para una marca
    python -m gondola.tools.normalizar_marcas --csv packshots/catalogo.csv \\
        --aplicar --fijar "Colcafé" --fijar "Choco Listo"
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Dos nombres se consideran la misma marca por encima de esta similitud.
# Alto a propósito: preferimos dejar dos variantes sin unir antes que
# fusionar dos marcas que de verdad son distintas.
UMBRAL_SIMILITUD = 0.86


def clave(nombre: str) -> str:
    """Forma comparable: sin tildes, sin separadores, en mayúsculas."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "", sin_tildes).upper()


def _parecidos(a: str, b: str) -> bool:
    """True si dos claves son casi seguro la misma marca."""
    if not a or not b:
        return False
    # Un nombre truncado por el modelo ('Colcaf' por 'Colcafe') es un
    # prefijo del completo. Se exige largo mínimo para no unir 'AL' con
    # cualquier marca que empiece igual.
    corto, largo = sorted((a, b), key=len)
    if len(corto) >= 4 and largo.startswith(corto):
        return True
    return SequenceMatcher(None, a, b).ratio() >= UMBRAL_SIMILITUD


def elegir_canonica(variantes: Counter, fijadas: dict[str, str]) -> str:
    """Qué forma se queda para el grupo.

    Prioridad: una forma que el usuario fijó a mano; si no, la más
    frecuente; a igual frecuencia, la que tenga tildes y no esté toda en
    mayúsculas, que es como se escribe una marca de verdad.
    """
    for variante in variantes:
        if clave(variante) in fijadas:
            return fijadas[clave(variante)]

    def puntaje(item: tuple[str, int]) -> tuple:
        nombre, veces = item
        tiene_tildes = any(unicodedata.combining(c) for c in unicodedata.normalize("NFD", nombre))
        todo_mayusculas = nombre.isupper()
        return (veces, tiene_tildes, not todo_mayusculas, len(nombre))

    return max(variantes.items(), key=puntaje)[0]


def agrupar(marcas: Iterable[str], fijadas: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Devuelve {marca_original: marca_canónica} para todas las variantes."""
    fijadas = fijadas or {}
    conteo = Counter(m.strip() for m in marcas if m and m.strip())

    grupos: list[Counter] = []
    for nombre, veces in conteo.most_common():  # los más frecuentes fundan grupo
        k = clave(nombre)
        for grupo in grupos:
            if any(_parecidos(k, clave(existente)) for existente in grupo):
                grupo[nombre] += veces
                break
        else:
            grupos.append(Counter({nombre: veces}))

    mapa: dict[str, str] = {}
    for grupo in grupos:
        canonica = elegir_canonica(grupo, fijadas)
        for variante in grupo:
            mapa[variante] = canonica
    return mapa


def rehacer_codigo(codigo: str, marca_vieja: str, marca_nueva: str) -> str:
    """Reemplaza el prefijo de marca dentro del código sugerido."""
    prefijo_viejo = clave(marca_vieja)[:10]
    prefijo_nuevo = clave(marca_nueva)[:10]
    if prefijo_viejo and codigo.startswith(prefijo_viejo + "-"):
        return prefijo_nuevo + codigo[len(prefijo_viejo):]
    return codigo


def asegurar_unicos(filas: list[dict]) -> int:
    """Vuelve a desambiguar códigos que quedaron repetidos tras renombrar."""
    vistos: set[str] = set()
    arreglados = 0
    for fila in filas:
        codigo = fila["codigo"]
        if codigo not in vistos:
            vistos.add(codigo)
            continue
        sufijo = 2
        while f"{codigo}-{sufijo}" in vistos:
            sufijo += 1
        fila["codigo"] = f"{codigo}-{sufijo}"
        vistos.add(fila["codigo"])
        arreglados += 1
    return arreglados


def main() -> int:
    parser = argparse.ArgumentParser(description="Unifica marcas repetidas en el catálogo borrador.")
    parser.add_argument("--csv", required=True, help="Ruta a catalogo.csv")
    parser.add_argument("--aplicar", action="store_true", help="Escribir los cambios (por defecto solo muestra)")
    parser.add_argument(
        "--fijar", action="append", default=[],
        help="Forma exacta que debe quedar para una marca. Repetible.",
    )
    args = parser.parse_args()

    ruta = Path(args.csv)
    if not ruta.exists():
        print(f"No existe {ruta}", file=sys.stderr)
        return 1

    with ruta.open(encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        columnas = lector.fieldnames or []
        filas = list(lector)

    if "marca" not in columnas:
        print("El CSV no tiene columna 'marca'.", file=sys.stderr)
        return 1

    fijadas = {clave(v): v for v in args.fijar}
    mapa = agrupar((f.get("marca", "") for f in filas), fijadas)

    grupos: dict[str, list[str]] = {}
    for original, canonica in mapa.items():
        if original != canonica:
            grupos.setdefault(canonica, []).append(original)

    antes = len({f.get("marca", "").strip() for f in filas if f.get("marca", "").strip()})
    despues = len(set(mapa.values()))

    print(f"Marcas distintas: {antes} → {despues}\n")
    if not grupos:
        print("No hay variantes que unificar.")
        return 0

    for canonica in sorted(grupos):
        print(f"  {canonica}")
        for variante in sorted(grupos[canonica]):
            print(f"      ← {variante}")

    if not args.aplicar:
        print("\nEsto es una vista previa. Agrega --aplicar para escribir los cambios.")
        print("Si alguna fusión está mal, usa --fijar \"Nombre Correcto\" o corrige el CSV a mano.")
        return 0

    cambios = 0
    for fila in filas:
        vieja = (fila.get("marca") or "").strip()
        nueva = mapa.get(vieja, vieja)
        if vieja and nueva != vieja:
            fila["marca"] = nueva
            fila["codigo"] = rehacer_codigo(fila.get("codigo", ""), vieja, nueva)
            cambios += 1

    repetidos = asegurar_unicos(filas)

    respaldo = ruta.with_suffix(".csv.bak")
    shutil.copy2(ruta, respaldo)
    with ruta.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)

    print(f"\n{cambios} filas actualizadas.")
    if repetidos:
        print(f"{repetidos} códigos repetidos se desambiguaron con un sufijo.")
    print(f"Original guardado en {respaldo.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
