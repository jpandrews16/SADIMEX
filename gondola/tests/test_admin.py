"""Tests de la carga masiva del administrador.

La planilla de precios la exporta una persona desde Excel. Tiene que
aguantar coma decimal, punto y coma como separador, BOM de Windows y
columnas con nombres distintos.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from gondola.app.admin import MAX_CSV_BYTES, _booleano, _leer_csv, _numero


# =====================================================================
# Números
# =====================================================================


def test_lee_decimal_con_punto():
    assert _numero("12.50") == 12.50


def test_lee_decimal_con_coma():
    """Excel en español exporta 12,50 y no puede romper la carga."""
    assert _numero("12,50") == 12.50


def test_lee_miles_con_punto_y_decimal_con_coma():
    assert _numero("1.234,56") == 1234.56


def test_ignora_el_simbolo_de_moneda():
    assert _numero("Bs 12.50") == 12.50
    assert _numero("$ 210") == 210.0


def test_valor_vacio_devuelve_el_defecto():
    assert _numero("", 3.0) == 3.0
    assert _numero(None) is None


def test_texto_no_numerico_devuelve_el_defecto():
    assert _numero("consultar", 3.0) == 3.0


# =====================================================================
# Booleanos
# =====================================================================


@pytest.mark.parametrize("valor", ["1", "true", "si", "sí", "X", "y", "VERDADERO"])
def test_reconoce_los_si(valor):
    assert _booleano(valor) is True


@pytest.mark.parametrize("valor", ["0", "no", "", "false", None])
def test_reconoce_los_no(valor):
    assert _booleano(valor) is False


# =====================================================================
# CSV
# =====================================================================


def test_lee_csv_con_coma():
    csv = b"sku_codigo,cadena,pvp\nNOEL-FESTIVAL-200,Fidalga,12.50\n"
    filas = _leer_csv(csv)
    assert filas == [{"sku_codigo": "NOEL-FESTIVAL-200", "cadena": "Fidalga", "pvp": "12.50"}]


def test_lee_csv_con_punto_y_coma():
    """Excel en configuración regional española usa ';'."""
    csv = b"sku_codigo;cadena;pvp\nNOEL-FESTIVAL-200;Hipermaxi;13,90\n"
    filas = _leer_csv(csv)
    assert filas[0]["cadena"] == "Hipermaxi"
    assert _numero(filas[0]["pvp"]) == 13.90


def test_lee_csv_con_bom_de_windows():
    csv = "﻿sku_codigo,pvp\nNOEL-SALTIN-250,15.00\n".encode("utf-8")
    filas = _leer_csv(csv)
    assert filas[0]["sku_codigo"] == "NOEL-SALTIN-250"


def test_lee_csv_en_latin1():
    csv = "sku_codigo,cadena,pvp\nCAFE-01,Tía,12.50\n".encode("latin-1")
    filas = _leer_csv(csv)
    assert filas[0]["cadena"] == "Tía"


def test_normaliza_encabezados_con_espacios_y_mayusculas():
    csv = b"SKU Codigo,Cadena,PVP\nA-1,Fidalga,10\n"
    filas = _leer_csv(csv)
    assert set(filas[0]) == {"sku_codigo", "cadena", "pvp"}


def test_descarta_filas_completamente_vacias():
    csv = b"sku_codigo,pvp\nA-1,10\n,\n\nB-2,20\n"
    assert len(_leer_csv(csv)) == 2


def test_csv_sin_encabezados_es_error():
    with pytest.raises(HTTPException) as exc:
        _leer_csv(b"")
    assert exc.value.status_code == 400


def test_archivo_demasiado_grande_es_rechazado():
    with pytest.raises(HTTPException) as exc:
        _leer_csv(b"x" * (MAX_CSV_BYTES + 1))
    assert exc.value.status_code == 413


def test_cadena_vacia_significa_precio_nacional():
    """Una fila sin cadena carga el PVP nacional, no un error."""
    csv = b"sku_codigo,cadena,pvp\nNOEL-SALTIN-250,,15.00\n"
    filas = _leer_csv(csv)
    assert filas[0]["cadena"] == ""


def test_las_cuatro_cadenas_reales_se_leen_igual():
    csv = (
        "sku_codigo,cadena,pvp\n"
        "CAFE-01,Fidalga,12.50\n"
        "CAFE-01,Hipermaxi,13.90\n"
        "CAFE-01,Tía,12.90\n"
        "CAFE-01,IC Norte,13.50\n"
    ).encode("utf-8")

    filas = _leer_csv(csv)

    assert [f["cadena"] for f in filas] == ["Fidalga", "Hipermaxi", "Tía", "IC Norte"]
    assert all(_numero(f["pvp"]) > 0 for f in filas)
