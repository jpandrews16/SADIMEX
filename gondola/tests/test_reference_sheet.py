"""Tests del preprocesado de imágenes y la hoja de referencia."""

from __future__ import annotations

import base64
import io

from PIL import Image

from gondola.app.config import get_settings
from gondola.app.reference_sheet import (
    construir_hoja_referencia,
    limpiar_cache,
    preparar_foto_gondola,
)
from gondola.app.schemas import Sku


def _imagen(ancho: int, alto: int, formato: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), (200, 40, 40)).save(buffer, format=formato)
    return buffer.getvalue()


def _decodificar(data_url: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))


def test_la_foto_grande_se_reescala_al_maximo_configurado():
    """Más resolución no mejora la lectura y sí encarece cada foto."""
    cfg = get_settings()
    data_url = preparar_foto_gondola(_imagen(4000, 3000))

    assert data_url.startswith("data:image/jpeg;base64,")
    assert max(_decodificar(data_url).size) == cfg.imagen_max_lado


def test_la_foto_chica_no_se_agranda():
    data_url = preparar_foto_gondola(_imagen(800, 600))
    assert _decodificar(data_url).size == (800, 600)


def test_convierte_png_con_transparencia_a_jpeg():
    buffer = io.BytesIO()
    Image.new("RGBA", (300, 300), (10, 20, 30, 128)).save(buffer, format="PNG")

    data_url = preparar_foto_gondola(buffer.getvalue())

    assert _decodificar(data_url).mode == "RGB"


def test_sin_packshots_no_hay_hoja_de_referencia():
    """El sistema debe seguir funcionando aunque falte el catálogo visual."""
    limpiar_cache()
    skus = [
        Sku(id="s1", codigo="A-1", nombre="Producto A", marca="Noel",
            categoria="galletas", packshot_url=None),
    ]
    assert construir_hoja_referencia(skus) is None
