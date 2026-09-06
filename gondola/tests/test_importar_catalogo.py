"""Tests del importador de packshots de Canva.

Lo que importa acá: que 348 páginas produzcan 348 códigos únicos y
legibles, y que el recorte del fondo blanco no se coma el producto.
"""

from __future__ import annotations

import io

from PIL import Image

from gondola.tools.importar_catalogo_canva import (
    _slug,
    parece_vacia,
    recortar_fondo,
    sugerir_codigo,
)


# =====================================================================
# Códigos
# =====================================================================


def test_slug_quita_tildes_y_simbolos():
    assert _slug("Café Ligero") == "CAFELIGERO"
    assert _slug("200 g") == "200G"


def test_codigo_se_arma_de_marca_variante_y_gramaje():
    codigo = sugerir_codigo(
        {"marca": "Colcafé", "variante": "Ligero Descafeinado", "gramaje": "200 g"},
        set(),
        11,
    )
    assert codigo == "COLCAFE-LIGERODESCAF-200G"


def test_codigos_repetidos_se_desambiguan():
    """Dos presentaciones idénticas no pueden pisarse en el catálogo."""
    usados: set[str] = set()
    datos = {"marca": "Noel", "variante": "Festival", "gramaje": "200g"}

    primero = sugerir_codigo(datos, usados, 1)
    segundo = sugerir_codigo(datos, usados, 2)

    assert primero != segundo
    assert segundo.endswith("-2")


def test_sin_datos_cae_al_numero_de_pagina():
    """Una página que la IA no pudo leer igual entra al CSV, marcada."""
    assert sugerir_codigo({}, set(), 42) == "SKU-042"


def test_todos_los_codigos_de_un_catalogo_grande_son_unicos():
    usados: set[str] = set()
    datos = {"marca": "Noel", "variante": "Festival", "gramaje": "200g"}

    codigos = [sugerir_codigo(dict(datos), usados, i) for i in range(1, 349)]

    assert len(set(codigos)) == 348


# =====================================================================
# Recorte
# =====================================================================


def _con_recuadro(fondo, color, caja) -> Image.Image:
    img = Image.new("RGB", (400, 400), fondo)
    img.paste(Image.new("RGB", (caja[2] - caja[0], caja[3] - caja[1]), color), caja[:2])
    return img


def test_recorta_el_margen_blanco_de_canva():
    img = _con_recuadro((255, 255, 255), (200, 30, 30), (150, 150, 250, 250))

    recortada = recortar_fondo(img)

    # El producto medía 100x100; con el margen de seguridad queda cerca.
    assert 100 <= recortada.width <= 130
    assert 100 <= recortada.height <= 130


def test_no_recorta_el_producto_mismo():
    img = _con_recuadro((255, 255, 255), (10, 120, 60), (100, 100, 300, 300))

    recortada = recortar_fondo(img)

    assert recortada.width >= 200
    assert recortada.height >= 200


def test_imagen_de_un_solo_color_se_devuelve_intacta():
    """Una página en blanco no debe convertirse en una imagen de 0 píxeles."""
    img = Image.new("RGB", (400, 400), (255, 255, 255))
    assert recortar_fondo(img).size == (400, 400)


def test_funciona_con_fondo_no_blanco():
    img = _con_recuadro((20, 20, 40), (240, 240, 240), (150, 150, 250, 250))

    recortada = recortar_fondo(img)

    assert recortada.width < 400


# =====================================================================
# Páginas en blanco
# =====================================================================


def test_pagina_en_blanco_se_detecta():
    """Un diseño de Canva trae separadores y huecos: no son productos."""
    assert parece_vacia(Image.new("RGB", (800, 800), (255, 255, 255))) is True


def test_pagina_de_un_color_cualquiera_tambien_esta_vacia():
    assert parece_vacia(Image.new("RGB", (800, 800), (12, 40, 90))) is True


def test_pagina_con_producto_no_esta_vacia():
    img = _con_recuadro((255, 255, 255), (200, 30, 30), (150, 150, 250, 250))
    assert parece_vacia(img) is False


def test_una_marca_muy_tenue_no_cuenta_como_producto():
    """Un degradado casi imperceptible de Canva no debe pasar por envase."""
    img = _con_recuadro((255, 255, 255), (253, 253, 253), (150, 150, 250, 250))
    assert parece_vacia(img) is True


def test_conserva_el_formato_al_guardar():
    img = recortar_fondo(_con_recuadro((255, 255, 255), (200, 30, 30), (150, 150, 250, 250)))
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="PNG")
    assert Image.open(io.BytesIO(buffer.getvalue())).mode == "RGB"
