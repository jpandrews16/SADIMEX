"""Orquestación: de una foto en la cola a un análisis persistido."""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from typing import Optional

from . import db
from .catalog import resolver_precios, resolver_reglas, skus_desde_filas
from .config import get_settings
from .reference_sheet import construir_hoja_referencia, preparar_foto_gondola
from .rules import (
    PESOS_POR_DEFECTO,
    detecciones_por_sku,
    evaluar,
    evaluar_etiquetas,
)
from .schemas import Analisis, Evaluacion, Observacion, Precio, Regla, Sku
from .vision import analizar_foto

log = logging.getLogger(__name__)

RADIO_TIERRA_M = 6_371_000


@dataclass
class Contexto:
    """Catálogo y reglas ya resueltos para una foto concreta."""

    skus: list[Sku]
    reglas: dict[str, Regla]
    precios: dict[str, Precio]
    pesos: dict[str, float]
    cadena_id: Optional[str] = None
    cadena_nombre: str = ""


# =====================================================================
# Integridad de la evidencia
# =====================================================================


def distancia_metros(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine. Suficiente para distinguir 'está en la sala' de 'no está'."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(math.sqrt(a))


def validar_captura(foto: dict, sala: Optional[dict], contenido: bytes) -> Optional[str]:
    """Chequeos de integridad de la foto como evidencia.

    Sin esto, evaluar reponedores por foto es un sistema de honor: basta
    con resubir la foto buena de la semana pasada. Devuelve el texto de la
    alerta, o None si la captura es limpia.
    """
    cfg = get_settings()
    alertas: list[str] = []

    sha = hashlib.sha256(contenido).hexdigest()
    if foto.get("imagen_sha256") and foto["imagen_sha256"] != sha:
        alertas.append("el hash declarado no coincide con el archivo almacenado")
    if db.hash_ya_existe(sha, excluir_photo_id=foto["id"]):
        alertas.append("foto idéntica ya subida antes (posible reciclaje)")

    if sala and sala.get("gps_lat") is not None and foto.get("gps_lat") is not None:
        dist = distancia_metros(
            float(foto["gps_lat"]), float(foto["gps_lng"]),
            float(sala["gps_lat"]), float(sala["gps_lng"]),
        )
        limite = float(sala.get("radio_metros") or 150) + cfg.gps_margen_metros
        if dist > limite:
            alertas.append(f"tomada a {int(dist)} m de la sala declarada")
    elif foto.get("gps_lat") is None:
        alertas.append("sin geolocalización")

    return "; ".join(alertas) if alertas else None


# =====================================================================
# Contexto
# =====================================================================


def _acotar_al_surtido(
    skus: list[Sku], cadena_id: Optional[str], categoria: str
) -> list[Sku]:
    """Deja solo los SKU que esa cadena efectivamente lleva.

    Es el cambio que más mejoró la lectura, y no toca al modelo. Medido
    sobre 17 fotos de sala anotadas a mano, con la misma foto, el mismo
    prompt y el mismo modelo:

        catálogo entero de la categoría (10 SKU)   recall 58%  precisión 41%
        surtido real de la cadena       ( 6 SKU)   recall 70%  precisión 65%

    Preguntar por un SKU que la cadena no vende no es neutro: el modelo
    reparte adivinanzas entre todos los envases de la hoja de referencia.
    Las cuatro variantes de Festival, que no estaban en NINGUNA de las 17
    fotos, se reportaron en 6 fotos cada una —25 de los 44 falsos
    positivos—. Y un falso positivo tapa un quiebre real, que es el error
    caro de este sistema.

    Sin surtido cargado se usa la categoría completa: así cargarlo es
    opcional y se puede ir haciendo cadena por cadena, aunque hasta que
    esté cargado esa cadena arrastra los falsos positivos.
    """
    if not cadena_id:
        return skus
    try:
        codigos = set(db.traer_surtido(cadena_id, categoria))
    except Exception as exc:
        # Sin surtido no se pierde la foto: se analiza contra la categoría.
        log.warning("No se pudo leer el surtido de la cadena: %s", exc)
        return skus

    if not codigos:
        log.info(
            "La cadena no tiene surtido cargado para '%s'; se usa la categoría "
            "completa (%d SKU) y la precisión baja",
            categoria, len(skus),
        )
        return skus

    acotados = [s for s in skus if s.codigo in codigos]
    if not acotados:
        log.warning(
            "El surtido de '%s' no coincide con ningún SKU activo de la categoría; "
            "se usa la categoría completa", categoria,
        )
        return skus

    log.info("Surtido de la cadena: %d de %d SKU de '%s'", len(acotados), len(skus), categoria)
    return acotados


def cargar_contexto(categoria: str, sala: Optional[dict] = None) -> Contexto:
    cadena = (sala or {}).get("cadenas") or {}
    cadena_id = cadena.get("id")

    skus = skus_desde_filas(db.traer_skus(categoria))
    skus = _acotar_al_surtido(skus, cadena_id, categoria)
    return Contexto(
        skus=skus,
        reglas=resolver_reglas(skus, db.traer_reglas(), cadena_id),
        precios=resolver_precios(skus, db.traer_precios(), cadena_id),
        pesos=db.traer_pesos() or PESOS_POR_DEFECTO,
        cadena_id=cadena_id,
        cadena_nombre=cadena.get("nombre", ""),
    )


# =====================================================================
# Análisis
# =====================================================================


def evaluar_observacion(obs: Observacion, ctx: Contexto) -> tuple[Evaluacion, list[dict]]:
    """Aplica las reglas y devuelve también el detalle por etiqueta."""
    cfg = get_settings()
    evaluacion = evaluar(
        obs=obs,
        skus=ctx.skus,
        reglas=ctx.reglas,
        precios=ctx.precios,
        pesos=ctx.pesos,
        umbral_deteccion=cfg.umbral_deteccion,
        umbral_verde=cfg.umbral_verde,
        umbral_amarillo=cfg.umbral_amarillo,
    )
    detectados = detecciones_por_sku(obs, cfg.umbral_deteccion)
    _, detalle = evaluar_etiquetas(obs, ctx.skus, ctx.reglas, detectados, ctx.precios)
    return evaluacion, detalle


def analizar(foto: dict) -> tuple[Analisis, list[dict]]:
    """Procesa una foto ya reclamada de la cola. No persiste nada."""
    sala = db.traer_sala(foto["sala_id"])
    contenido = db.descargar_imagen(foto["storage_path"])

    if alerta := validar_captura(foto, sala, contenido):
        log.warning("Foto %s con alerta de captura: %s", foto["id"], alerta)
        db.marcar_alerta_captura(foto["id"], alerta)

    ctx = cargar_contexto(foto["categoria"], sala)
    if not ctx.skus:
        raise RuntimeError(
            f"No hay SKU activos en la categoría '{foto['categoria']}'. "
            "Carga el catálogo antes de procesar fotos."
        )

    observacion, uso = analizar_foto(
        skus=ctx.skus,
        foto_data_url=preparar_foto_gondola(contenido),
        hoja_referencia=construir_hoja_referencia(ctx.skus),
        categoria=foto["categoria"],
        cadena=ctx.cadena_nombre,
        # Sin los precios no se puede detectar un precio fuera de rango,
        # que es uno de los tres motivos para verificar la lectura.
        precios=ctx.precios,
    )

    evaluacion, detalle = evaluar_observacion(observacion, ctx)

    analisis = Analisis(
        photo_id=foto["id"],
        reponedor_id=foto["reponedor_id"],
        sala_id=foto["sala_id"],
        ciudad=foto["ciudad"],
        observacion=observacion,
        evaluacion=evaluacion,
        uso=uso,
    )
    return analisis, detalle


def procesar(foto: dict) -> Analisis:
    """Analiza y persiste. Deja la foto en 'completado' o en 'error'."""
    try:
        analisis, detalle = analizar(foto)
        db.guardar_analisis(analisis, detalle)
        db.marcar_estado(foto["id"], "completado")
        log.info(
            "Foto %s | score %d (%s) | %s | %.4f USD | %d ms",
            foto["id"], analisis.evaluacion.score, analisis.evaluacion.semaforo,
            analisis.uso.modelo, analisis.uso.costo_usd, analisis.uso.duracion_ms,
        )
        return analisis
    except Exception as exc:
        log.exception("Error procesando la foto %s", foto["id"])
        db.marcar_estado(foto["id"], "error", str(exc))
        raise
