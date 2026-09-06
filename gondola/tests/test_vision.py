"""Tests del saneamiento de la respuesta del modelo.

Un modelo de visión puede devolver un código que no existe, un nivel en
cero o un JSON envuelto en markdown. Nada de eso puede llegar al motor de
reglas ni tumbar el análisis.
"""

from __future__ import annotations

import pytest

from gondola.app.prompt import OBSERVACION_SCHEMA, construir_mensajes
from gondola.app.schemas import Sku
from gondola.app.vision import VisionError, _extraer_json, _normalizar

CODIGOS = {"NOEL-FESTIVAL-200", "WILD-FRESA"}


def bruto(**overrides) -> dict:
    base = {
        "niveles_visibles": 5,
        "nivel_ojos": 4,
        "mueble_completo_visible": True,
        "calidad_foto": "buena",
        "motivo_calidad": None,
        "frentes_totales_lineal": 40,
        "detecciones": [],
        "huecos": [],
        "etiquetas": [],
        "confianza_global": 0.9,
    }
    base.update(overrides)
    return base


def deteccion(codigo: str, **kw) -> dict:
    base = {
        "sku_codigo": codigo, "confianza": 0.9, "nivel": 3, "frentes": 2,
        "bbox": {"x0": 0, "y0": 0, "x1": 100, "y1": 100}, "frenteado": True,
    }
    base.update(kw)
    return base


# =====================================================================
# Parseo
# =====================================================================


def test_extrae_json_envuelto_en_markdown():
    assert _extraer_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extrae_json_con_texto_alrededor():
    assert _extraer_json('Claro, aquí está:\n{"a": 1}\nEspero que sirva.') == {"a": 1}


def test_respuesta_sin_json_es_error():
    with pytest.raises(VisionError):
        _extraer_json("No pude analizar la imagen.")


# =====================================================================
# Saneamiento
# =====================================================================


def test_descarta_sku_que_no_esta_en_el_catalogo():
    """El modelo no puede inventar productos que no vendemos."""
    obs = _normalizar(
        bruto(detecciones=[deteccion("NOEL-FESTIVAL-200"), deteccion("COCA-COLA-2L")]),
        CODIGOS,
    )
    assert [d.sku_codigo for d in obs.detecciones] == ["NOEL-FESTIVAL-200"]


def test_corrige_nivel_y_frentes_en_cero():
    obs = _normalizar(
        bruto(detecciones=[deteccion("WILD-FRESA", nivel=0, frentes=0)]), CODIGOS
    )
    assert obs.detecciones[0].nivel == 1
    assert obs.detecciones[0].frentes == 1


def test_acota_la_confianza_al_rango_valido():
    obs = _normalizar(bruto(detecciones=[deteccion("WILD-FRESA", confianza=1.7)]), CODIGOS)
    assert obs.detecciones[0].confianza == 1.0


def test_desasocia_etiqueta_de_un_sku_inexistente():
    obs = _normalizar(
        bruto(
            etiquetas=[{
                "texto_producto": "PEPSI 2L", "precio_leido": 10.0, "moneda": "BOB",
                "legible": True, "nivel": 2, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10},
                "sku_asociado": "PEPSI-2L", "confianza": 0.8, "es_promocion": False,
            }]
        ),
        CODIGOS,
    )
    # La etiqueta se conserva (existe en el riel) pero deja de apuntar a
    # un SKU nuestro, así que no contamina la auditoría de precios.
    assert obs.etiquetas[0].sku_asociado is None


def test_niveles_visibles_nunca_es_cero():
    obs = _normalizar(bruto(niveles_visibles=0), CODIGOS)
    assert obs.niveles_visibles == 1


# =====================================================================
# Prompt
# =====================================================================


@pytest.fixture
def skus() -> list[Sku]:
    return [
        Sku(id="s1", codigo="WILD-FRESA", nombre="Wild Protein Fresa", marca="Wild Protein",
            categoria="suplementos", gramaje="500g",
            descripcion_visual="Pote negro con banda rosada."),
    ]


def test_el_prompt_incluye_el_catalogo_y_la_descripcion_visual(skus):
    mensajes = construir_mensajes(skus, "data:image/jpeg;base64,AAA", categoria="suplementos")
    texto = "".join(p.get("text", "") for p in mensajes[1]["content"])

    assert "WILD-FRESA" in texto
    assert "banda rosada" in texto
    assert "suplementos" in texto


def test_la_foto_va_al_final_del_prompt(skus):
    """El modelo debe llegar a la foto sabiendo ya qué buscar."""
    mensajes = construir_mensajes(skus, "data:image/jpeg;base64,FOTO")
    assert mensajes[1]["content"][-1]["image_url"]["url"] == "data:image/jpeg;base64,FOTO"


def test_la_hoja_de_referencia_va_antes_que_la_foto(skus):
    mensajes = construir_mensajes(skus, "data:image/jpeg;base64,FOTO", "data:image/jpeg;base64,HOJA")
    imagenes = [p["image_url"]["url"] for p in mensajes[1]["content"] if p["type"] == "image_url"]
    assert imagenes == ["data:image/jpeg;base64,HOJA", "data:image/jpeg;base64,FOTO"]


def test_sin_packshots_no_se_manda_hoja_de_referencia(skus):
    mensajes = construir_mensajes(skus, "data:image/jpeg;base64,FOTO", None)
    imagenes = [p for p in mensajes[1]["content"] if p["type"] == "image_url"]
    assert len(imagenes) == 1


def test_el_esquema_exige_todos_los_campos_de_observacion():
    # `strict: true` en OpenRouter falla si un required no está en properties.
    assert set(OBSERVACION_SCHEMA["required"]) == set(OBSERVACION_SCHEMA["properties"])
