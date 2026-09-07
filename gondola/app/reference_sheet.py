"""Hoja de referencia visual de SKUs.

En vez de mandarle al modelo un packshot por producto (N imágenes, N veces
el costo), se arma **una sola imagen** tipo mosaico con todos los envases
rotulados con su código. El modelo la usa como leyenda para no confundir
variantes: es la diferencia entre acertar "Wild Protein" y acertar
"Wild Protein Fresa".

El mosaico se cachea en memoria y solo se rearma cuando cambia el
catálogo, así que su costo de construcción se paga una vez por proceso.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from typing import Optional, Sequence

import httpx
from PIL import Image, ImageDraw, ImageFont

from .config import get_settings
from .schemas import Sku

log = logging.getLogger(__name__)

_cache: dict[str, str] = {}

FONDO = (255, 255, 255)
BORDE = (203, 213, 225)
TEXTO = (15, 23, 42)
ALTO_ROTULO = 34


def _clave_catalogo(skus: Sequence[Sku]) -> str:
    crudo = "|".join(f"{s.codigo}:{s.packshot_url or ''}" for s in sorted(skus, key=lambda x: x.codigo))
    return hashlib.sha256(crudo.encode()).hexdigest()


def _fuente(tam: int = 15) -> ImageFont.ImageFont:
    for ruta in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(ruta, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def _ancho(texto: str, fuente: ImageFont.ImageFont) -> int:
    caja = fuente.getbbox(texto)
    return caja[2] - caja[0]


def _fuente_que_entra(texto: str, ancho_max: int) -> ImageFont.ImageFont:
    """La fuente más grande con la que el código entra en su celda.

    Los códigos reales son largos (`FESTIVAL-SABORLIMON-2016G`) y con
    tamaño fijo se salían de la celda y se superponían con el rótulo
    vecino. El modelo tiene que poder leer el código completo: si lee uno
    partido, responde con un SKU que no existe y la detección se descarta.
    """
    for tam in range(15, 7, -1):
        fuente = _fuente(tam)
        if _ancho(texto, fuente) <= ancho_max:
            return fuente
    return _fuente(8)


def _descargar(client: httpx.Client, url: str, lado: int) -> Optional[Image.Image]:
    try:
        # Un packshot también puede ser un archivo local. Sirve para probar
        # el catálogo recién extraído del PDF, antes de tener dónde subirlo:
        # sin esto habría que montar Storage solo para ver si el mosaico
        # mejora el acierto.
        if not url.startswith(("http://", "https://")):
            img = Image.open(url).convert("RGB")
            img.thumbnail((lado, lado), Image.LANCZOS)
            return img

        resp = client.get(url, timeout=20.0)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        img = img.convert("RGB")
        img.thumbnail((lado, lado), Image.LANCZOS)
        return img
    except Exception as exc:  # una URL rota no puede tumbar el análisis
        log.warning("No se pudo descargar el packshot %s: %s", url, exc)
        return None


def seleccionar_para_hoja(skus: Sequence[Sku], tope: int) -> list[Sku]:
    """Elige qué packshots entran al mosaico cuando el catálogo es grande.

    El mosaico viaja en CADA llamada, así que sus tokens de imagen se pagan
    en todas las fotos. Con catálogos de cientos de SKU hay que cortar:
    primero los prioritarios, después el resto, y siempre en orden estable
    para que la caché del mosaico no se invalide entre fotos.
    """
    con_foto = [s for s in skus if s.packshot_url]
    if len(con_foto) <= tope:
        return sorted(con_foto, key=lambda s: s.codigo)

    prioritarios = sorted((s for s in con_foto if s.es_prioritario), key=lambda s: s.codigo)
    resto = sorted((s for s in con_foto if not s.es_prioritario), key=lambda s: s.codigo)
    seleccion = (prioritarios + resto)[:tope]

    log.warning(
        "Catálogo con %d packshots supera el tope de %d para la hoja de referencia; "
        "%d SKU quedan sin imagen de apoyo. Considera dividir la categoría.",
        len(con_foto), tope, len(con_foto) - tope,
    )
    return sorted(seleccion, key=lambda s: s.codigo)


def construir_hoja_referencia(skus: Sequence[Sku]) -> Optional[str]:
    """Devuelve el mosaico como data URL JPEG, o None si no hay packshots.

    Sin packshots el sistema sigue funcionando: el modelo se apoya solo en
    los nombres y las descripciones visuales del catálogo, con menos
    precisión en variantes parecidas.
    """
    cfg = get_settings()
    con_foto = seleccionar_para_hoja(skus, cfg.packshot_max_en_hoja)
    if not con_foto:
        return None

    clave = _clave_catalogo(con_foto)
    if clave in _cache:
        return _cache[clave]

    lado = cfg.packshot_lado
    columnas = min(cfg.packshot_columnas, len(con_foto))
    filas = (len(con_foto) + columnas - 1) // columnas
    celda_w, celda_h = lado, lado + ALTO_ROTULO

    hoja = Image.new("RGB", (columnas * celda_w, filas * celda_h), FONDO)
    dibujo = ImageDraw.Draw(hoja)

    with httpx.Client(follow_redirects=True) as client:
        for i, sku in enumerate(con_foto):
            col, fila = i % columnas, i // columnas
            x0, y0 = col * celda_w, fila * celda_h
            dibujo.rectangle([x0, y0, x0 + celda_w - 1, y0 + celda_h - 1], outline=BORDE)

            img = _descargar(client, sku.packshot_url or "", lado - 12)
            if img is not None:
                hoja.paste(img, (x0 + (celda_w - img.width) // 2, y0 + (lado - img.height) // 2))

            # El rótulo es lo que hace útil el mosaico: el modelo responde
            # con este código exacto, no con un nombre libre. Por eso tiene
            # que entrar ENTERO y dentro de su celda: con códigos largos se
            # salía y se pisaba con el rótulo de al lado, y ahí el modelo
            # lee un código que no existe.
            dibujo.text(
                (x0 + 6, y0 + lado + 8),
                sku.codigo,
                fill=TEXTO,
                font=_fuente_que_entra(sku.codigo, celda_w - 12),
            )

    buffer = io.BytesIO()
    hoja.save(buffer, format="JPEG", quality=85, optimize=True)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    _cache[clave] = data_url
    log.info("Hoja de referencia construida: %d SKU, %d KB", len(con_foto), len(data_url) // 1024)
    return data_url


def preparar_foto_gondola(contenido: bytes) -> str:
    """Normaliza la foto de sala y la devuelve como data URL.

    Se reescala al lado máximo configurado: por encima de eso el modelo no
    gana precisión y sí se paga más por tokens de imagen.
    """
    cfg = get_settings()
    img = Image.open(io.BytesIO(contenido))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > cfg.imagen_max_lado:
        img.thumbnail((cfg.imagen_max_lado, cfg.imagen_max_lado), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=cfg.imagen_calidad_jpeg, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def limpiar_cache() -> None:
    _cache.clear()
