"""La corrección de una lectura, que es de donde el sistema aprende.

Cada foto corregida o confirmada por una persona sirve para tres cosas a
la vez: deducir el surtido de la cadena, medir la exactitud del lector y
acumular verdad de referencia sin que nadie anote fotos a propósito.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gondola.app import db, main
from gondola.app.auth import usuario_actual


ANALISIS = {
    "photo_id": "foto-1",
    "modelo_usado": "qwen/qwen3-vl-32b-instruct",
    "observacion": {
        "detecciones": [
            {"sku_codigo": "DUCALES", "confianza": 0.9, "nivel": 2, "frentes": 3},
            {"sku_codigo": "FESTIVAL", "confianza": 0.8, "nivel": 3, "frentes": 2},
        ]
    },
}


@pytest.fixture
def cliente(monkeypatch):
    guardadas = []

    monkeypatch.setattr(db, "traer_analisis", lambda pid: dict(ANALISIS) if pid == "foto-1" else None)
    monkeypatch.setattr(
        db, "guardar_correccion",
        lambda **kw: guardadas.append(kw) or {
            "tipo": "confirmada" if sorted(set(kw["skus_reales"])) == sorted(set(kw["skus_leidos"]))
                    else "corregida",
            "skus_reales": sorted(set(kw["skus_reales"])),
        },
    )
    main.app.dependency_overrides[usuario_actual] = lambda: {
        "id": "sup-1", "rol": "supervisor", "nombre": "Supervisora", "ciudad": "LPZ",
    }
    yield TestClient(main.app), guardadas
    main.app.dependency_overrides.clear()


def test_una_correccion_guarda_lo_leido_y_lo_real(cliente):
    """Se congela lo que el sistema había leído: si solo se guardaran las
    diferencias, cambiar de modelo dejaría sin sentido el historial."""
    app, guardadas = cliente

    r = app.post("/api/gondola/analisis/foto-1/correccion",
                 json={"skus_reales": ["DUCALES", "SALTIN"]})

    assert r.status_code == 200
    assert r.json()["skus_leidos"] == ["DUCALES", "FESTIVAL"]
    assert r.json()["skus_reales"] == ["DUCALES", "SALTIN"]
    assert guardadas[0]["modelo"] == "qwen/qwen3-vl-32b-instruct"


def test_confirmar_una_lectura_correcta_tambien_cuenta(cliente):
    """Es evidencia mucho más barata de conseguir que una corrección, y
    sostiene la misma medición."""
    app, _ = cliente

    r = app.post("/api/gondola/analisis/foto-1/correccion",
                 json={"skus_reales": ["FESTIVAL", "DUCALES"]})

    assert r.json()["tipo"] == "confirmada"


def test_una_foto_sin_analisis_no_se_puede_corregir(cliente):
    app, _ = cliente
    r = app.post("/api/gondola/analisis/foto-x/correccion", json={"skus_reales": []})
    assert r.status_code == 404


def test_el_reponedor_no_corrige_su_propia_foto(monkeypatch):
    """Sería calificarse a sí mismo: la corrección es justo lo que después
    mide al reponedor."""
    main.app.dependency_overrides[usuario_actual] = lambda: {
        "id": "rep-1", "rol": "reponedor", "ciudad": "LPZ",
    }
    try:
        r = TestClient(main.app).post(
            "/api/gondola/analisis/foto-1/correccion", json={"skus_reales": []}
        )
        assert r.status_code == 403
    finally:
        main.app.dependency_overrides.clear()
