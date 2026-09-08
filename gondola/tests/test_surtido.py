"""Acotar el catálogo al surtido de la cadena.

Es el cambio que más mejoró la lectura de fotos reales, y no toca al
modelo: medido sobre 17 fotos de sala anotadas a mano, pasar del catálogo
entero de la categoría (10 SKU) al surtido real de la cadena (6 SKU) llevó
el recall de 58% a 70% y la precisión de 41% a 65%.
"""

from __future__ import annotations

import pytest

from gondola.app import pipeline
from gondola.app.schemas import Sku


def sku(codigo: str) -> Sku:
    return Sku(id=codigo, codigo=codigo, nombre=codigo, marca="M", categoria="galletas")


@pytest.fixture
def catalogo() -> list[Sku]:
    return [sku("DUCALES"), sku("SALTIN"), sku("FESTIVAL-FRESA"), sku("FESTIVAL-LIMON")]


def test_deja_solo_lo_que_la_cadena_lleva(catalogo, monkeypatch):
    monkeypatch.setattr(pipeline.db, "traer_surtido", lambda c, k: ["DUCALES", "SALTIN"])

    acotados = pipeline._acotar_al_surtido(catalogo, "cadena-1", "galletas")

    assert [s.codigo for s in acotados] == ["DUCALES", "SALTIN"]


def test_sin_surtido_cargado_se_usa_la_categoria_completa(catalogo, monkeypatch):
    """Cargar el surtido tiene que poder hacerse cadena por cadena, sin
    dejar de analizar fotos mientras tanto."""
    monkeypatch.setattr(pipeline.db, "traer_surtido", lambda c, k: [])

    assert pipeline._acotar_al_surtido(catalogo, "cadena-1", "galletas") == catalogo


def test_sin_cadena_no_se_acota(catalogo):
    """Una foto sin sala asignada no tiene cadena de la que sacar surtido."""
    assert pipeline._acotar_al_surtido(catalogo, None, "galletas") == catalogo


def test_un_surtido_que_no_cruza_con_nada_no_vacia_el_catalogo(catalogo, monkeypatch):
    """Un surtido mal cargado —códigos viejos, otra categoría— dejaría al
    modelo sin nada que buscar y toda la góndola saldría como quiebre
    total. Ante esa contradicción se prefiere la categoría completa."""
    monkeypatch.setattr(pipeline.db, "traer_surtido", lambda c, k: ["CODIGO-QUE-NO-EXISTE"])

    assert pipeline._acotar_al_surtido(catalogo, "cadena-1", "galletas") == catalogo


def test_si_falla_la_consulta_la_foto_no_se_pierde(catalogo, monkeypatch):
    def explota(_c, _k):
        raise RuntimeError("supabase caído")

    monkeypatch.setattr(pipeline.db, "traer_surtido", explota)

    assert pipeline._acotar_al_surtido(catalogo, "cadena-1", "galletas") == catalogo
