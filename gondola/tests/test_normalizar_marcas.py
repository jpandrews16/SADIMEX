"""Tests de la unificación de marcas.

Casos tomados de la corrida real sobre el catálogo de 347 productos, donde
el modelo devolvió 59 "marcas" que en realidad eran bastantes menos.
"""

from __future__ import annotations

from gondola.tools.normalizar_marcas import (
    agrupar,
    asegurar_unicos,
    clave,
    rehacer_codigo,
)


# =====================================================================
# Clave de comparación
# =====================================================================


def test_clave_ignora_tildes_mayusculas_y_espacios():
    assert clave("Colcafé") == clave("COLCAFE") == clave("colcafe") == "COLCAFE"
    assert clave("CHOCO LISTO") == clave("Chocolisto") == "CHOCOLISTO"


# =====================================================================
# Agrupación
# =====================================================================


def test_unifica_las_variantes_reales_de_colcafe():
    marcas = ["Colcafé"] * 10 + ["COLCAFÉ"] * 3 + ["Colcafe"] * 2 + ["Colcaf"]

    mapa = agrupar(marcas)

    assert len(set(mapa.values())) == 1
    assert mapa["Colcaf"] == "Colcafé"
    assert mapa["COLCAFÉ"] == "Colcafé"


def test_unifica_marca_con_y_sin_espacio():
    mapa = agrupar(["CHOCO LISTO", "CHOCOLISTO", "CHOCOLISTO"])
    assert len(set(mapa.values())) == 1


def test_no_mezcla_marcas_realmente_distintas():
    """Fusionar dos marcas distintas es peor que dejar una variante suelta."""
    mapa = agrupar(["Colcafé", "Noel", "Wild Protein", "Chocolisto"])
    assert len(set(mapa.values())) == 4


def test_no_une_marcas_cortas_que_empiezan_igual():
    mapa = agrupar(["AL", "ALPINA", "ALPINA"])
    assert mapa["ALPINA"] != mapa["AL"]


def test_prefiere_la_forma_mas_frecuente():
    mapa = agrupar(["Noel"] * 5 + ["NOEL"])
    assert set(mapa.values()) == {"Noel"}


def test_a_igual_frecuencia_prefiere_la_forma_con_tildes():
    mapa = agrupar(["COLCAFE", "Colcafé"])
    assert set(mapa.values()) == {"Colcafé"}


def test_una_marca_fijada_a_mano_manda():
    mapa = agrupar(["COLCAFE"] * 20 + ["Colcafé"], fijadas={clave("Colcafé"): "Colcafé"})
    assert set(mapa.values()) == {"Colcafé"}


def test_ignora_marcas_vacias():
    mapa = agrupar(["Noel", "", "  ", None])
    assert set(mapa.values()) == {"Noel"}


# =====================================================================
# Códigos
# =====================================================================


def test_el_codigo_se_actualiza_con_la_marca_nueva():
    assert rehacer_codigo("COLCAFE-MOCCA-108G", "Colcafe", "Colcafé") == "COLCAFE-MOCCA-108G"
    assert rehacer_codigo("CHOCOLISTO-VAINILLA", "CHOCO LISTO", "Chocolisto") == "CHOCOLISTO-VAINILLA"


def test_el_codigo_que_no_empieza_con_la_marca_se_deja_igual():
    assert rehacer_codigo("SKU-042", "Colcafe", "Colcafé") == "SKU-042"


def test_los_codigos_repetidos_tras_renombrar_se_desambiguan():
    """Unificar marcas puede volver idénticos dos códigos que no lo eran."""
    filas = [
        {"codigo": "COLCAFE-MOCCA-108G"},
        {"codigo": "COLCAFE-MOCCA-108G"},
        {"codigo": "COLCAFE-MOCCA-108G"},
    ]

    arreglados = asegurar_unicos(filas)

    assert arreglados == 2
    assert len({f["codigo"] for f in filas}) == 3
