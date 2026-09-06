"""Tests de la validación de la foto como evidencia.

Sin estos chequeos, medir reponedores por foto es un sistema de honor.
"""

from __future__ import annotations

import pytest

from gondola.app import pipeline
from gondola.app.pipeline import distancia_metros, validar_captura

# Ketal Calacoto, La Paz (aproximado).
SALA = {"gps_lat": -16.5350, "gps_lng": -68.0850, "radio_metros": 150}
CONTENIDO = b"foto-de-gondola"


@pytest.fixture(autouse=True)
def sin_base(monkeypatch):
    """El chequeo de hash duplicado consulta Supabase; acá se apaga."""
    monkeypatch.setattr(pipeline.db, "hash_ya_existe", lambda *a, **kw: False)


def foto(**kw) -> dict:
    base = {"id": "p1", "gps_lat": SALA["gps_lat"], "gps_lng": SALA["gps_lng"]}
    base.update(kw)
    return base


# =====================================================================
# Distancia
# =====================================================================


def test_distancia_entre_el_mismo_punto_es_cero():
    assert distancia_metros(-16.535, -68.085, -16.535, -68.085) == pytest.approx(0.0, abs=0.1)


def test_distancia_conocida_es_razonable():
    # ~0.01 grados de latitud ≈ 1.1 km
    d = distancia_metros(-16.535, -68.085, -16.545, -68.085)
    assert 1050 < d < 1150


# =====================================================================
# Validación
# =====================================================================


def test_foto_tomada_en_la_sala_no_genera_alerta():
    assert validar_captura(foto(), SALA, CONTENIDO) is None


def test_foto_lejos_de_la_sala_se_marca():
    lejos = foto(gps_lat=-16.500, gps_lng=-68.130)

    alerta = validar_captura(lejos, SALA, CONTENIDO)

    assert alerta is not None
    assert "de la sala declarada" in alerta


def test_foto_dentro_del_margen_de_tolerancia_pasa():
    """El GPS de un celular dentro de un supermercado no es exacto."""
    cerca = foto(gps_lat=-16.5360, gps_lng=-68.0850)  # ~110 m
    assert validar_captura(cerca, SALA, CONTENIDO) is None


def test_foto_sin_gps_se_marca():
    alerta = validar_captura(foto(gps_lat=None, gps_lng=None), SALA, CONTENIDO)
    assert alerta == "sin geolocalización"


def test_hash_declarado_que_no_coincide_se_marca():
    alerta = validar_captura(foto(imagen_sha256="0" * 64), SALA, CONTENIDO)
    assert "hash declarado no coincide" in alerta


def test_foto_reciclada_se_marca(monkeypatch):
    monkeypatch.setattr(pipeline.db, "hash_ya_existe", lambda *a, **kw: True)

    alerta = validar_captura(foto(), SALA, CONTENIDO)

    assert "posible reciclaje" in alerta


def test_sala_sin_coordenadas_no_puede_validar_ubicacion():
    sala_sin_gps = {"gps_lat": None, "gps_lng": None, "radio_metros": 150}
    assert validar_captura(foto(), sala_sin_gps, CONTENIDO) is None
