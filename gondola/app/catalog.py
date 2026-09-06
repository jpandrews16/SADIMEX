"""Catálogo, precios y resolución de reglas.

Una regla puede estar escrita a distintos niveles de detalle: para toda la
categoría, para una marca, para un SKU, y cualquiera de esas acotada a una
cadena. Acá se decide cuál manda para cada SKU concreto.

Criterio: gana la más específica. Se puntúa cada dimensión declarada
(cadena, SKU, marca, categoría) y la de mayor puntaje aplica. Empate
imposible por construcción, porque los puntajes son potencias distintas.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from .schemas import Precio, Regla, Sku

log = logging.getLogger(__name__)

# Pesos de especificidad. Cadena pesa más que SKU: una regla negociada con
# Hipermaxi para la marca manda sobre la regla nacional del SKU.
PESO_CADENA = 8
PESO_SKU = 4
PESO_MARCA = 2
PESO_CATEGORIA = 1


def _especificidad(fila: dict, sku: Sku, cadena_id: Optional[str]) -> Optional[int]:
    """Puntaje de la regla para este SKU, o None si no le aplica."""
    puntaje = 0

    if fila.get("cadena_id"):
        if fila["cadena_id"] != cadena_id:
            return None
        puntaje += PESO_CADENA

    if fila.get("sku_id"):
        if fila["sku_id"] != sku.id:
            return None
        puntaje += PESO_SKU

    if fila.get("marca"):
        if fila["marca"].strip().lower() != sku.marca.strip().lower():
            return None
        puntaje += PESO_MARCA

    if fila.get("categoria"):
        if fila["categoria"].strip().lower() != sku.categoria.strip().lower():
            return None
        puntaje += PESO_CATEGORIA

    return puntaje


def resolver_reglas(
    skus: Sequence[Sku], filas_reglas: Sequence[dict], cadena_id: Optional[str] = None
) -> dict[str, Regla]:
    """Devuelve la regla efectiva para cada SKU, indexada por código.

    Un SKU sin ninguna regla aplicable recibe la regla por defecto, que
    solo exige presencia y etiqueta. Nunca se queda sin evaluar.
    """
    activas = [f for f in filas_reglas if f.get("activo", True)]
    resueltas: dict[str, Regla] = {}

    for sku in skus:
        mejor: Optional[dict] = None
        mejor_puntaje = -1
        for fila in activas:
            puntaje = _especificidad(fila, sku, cadena_id)
            if puntaje is not None and puntaje > mejor_puntaje:
                mejor, mejor_puntaje = fila, puntaje

        if mejor is None:
            resueltas[sku.codigo] = Regla(nombre="default")
            continue

        resueltas[sku.codigo] = Regla(
            nombre=mejor.get("nombre", "regla"),
            exige_presencia=bool(mejor.get("exige_presencia", True)),
            nivel_objetivo=mejor.get("nivel_objetivo") or "cualquiera",
            frentes_minimos=int(mejor.get("frentes_minimos") or 1),
            share_minimo_pct=(
                float(mejor["share_minimo_pct"]) if mejor.get("share_minimo_pct") is not None else None
            ),
            exige_bloque=bool(mejor.get("exige_bloque", True)),
            exige_etiqueta=bool(mejor.get("exige_etiqueta", True)),
            exige_sin_quiebre=bool(mejor.get("exige_sin_quiebre", True)),
        )

    return resueltas


def resolver_precios(
    skus: Sequence[Sku], filas_precios: Sequence[dict], cadena_id: Optional[str] = None
) -> dict[str, Precio]:
    """Precio vigente por código de SKU.

    El precio de la cadena manda sobre el nacional. Un SKU sin precio
    cargado simplemente no aparece: el motor de reglas lo trata como
    "no podemos juzgar el monto" y no castiga al reponedor por eso.
    """
    por_sku_id = {s.id: s for s in skus}
    resueltos: dict[str, Precio] = {}
    especificidad: dict[str, int] = {}

    for fila in filas_precios:
        sku = por_sku_id.get(fila.get("sku_id"))
        if sku is None:
            continue
        if fila.get("vigente_hasta"):
            continue
        fila_cadena = fila.get("cadena_id")
        if fila_cadena and fila_cadena != cadena_id:
            continue

        puntaje = 1 if fila_cadena else 0
        if especificidad.get(sku.codigo, -1) >= puntaje:
            continue

        resueltos[sku.codigo] = Precio(
            sku_id=sku.id,
            cadena_id=fila_cadena,
            pvp=float(fila["pvp"]),
            moneda=fila.get("moneda") or "BOB",
            tolerancia_pct=float(fila.get("tolerancia_pct") or 3.0),
        )
        especificidad[sku.codigo] = puntaje

    return resueltos


def skus_desde_filas(filas: Sequence[dict]) -> list[Sku]:
    return [
        Sku(
            id=str(f["id"]),
            codigo=f["codigo"],
            nombre=f["nombre"],
            marca=f["marca"],
            categoria=f["categoria"],
            gramaje=f.get("gramaje"),
            es_prioritario=bool(f.get("es_prioritario", False)),
            packshot_url=f.get("packshot_url"),
            descripcion_visual=f.get("descripcion_visual"),
        )
        for f in filas
        if f.get("activo", True)
    ]


def cargar_catalogo_local(ruta: str | Path) -> tuple[list[Sku], list[dict], list[dict]]:
    """Catálogo desde un JSON en disco.

    Sirve para desarrollo, para los tests y para correr el evaluador de
    modelos sin depender de la base.
    """
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return (
        skus_desde_filas(datos.get("skus", [])),
        datos.get("reglas", []),
        datos.get("precios", []),
    )
