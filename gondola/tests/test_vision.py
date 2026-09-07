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


# =====================================================================
# Estrategia ante una lectura dudosa
# =====================================================================


@pytest.fixture
def registrar_llamadas(monkeypatch):
    """Reemplaza la llamada real y anota (modelo, temperatura) de cada una."""
    from gondola.app import vision

    llamadas: list[tuple[str, float]] = []
    respuestas: list[dict] = []

    def falsa(_client, modelo, mensajes, temperatura=0.0):
        llamadas.append((modelo, temperatura))
        i = min(len(llamadas) - 1, len(respuestas) - 1)
        return respuestas[i], {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0001}, 500

    monkeypatch.setattr(vision, "_llamar_modelo", falsa)
    monkeypatch.setattr(vision.cuota_escalado, "_dia", None)
    return llamadas, respuestas


@pytest.fixture
def skus_min():
    return [Sku(id="s1", codigo="NOEL-A", nombre="A", marca="Noel", categoria="cafe")]


def _respuesta(confianza, skus=("NOEL-A",)):
    return bruto(
        confianza_global=confianza,
        detecciones=[deteccion(s) for s in skus],
    )


def test_una_lectura_confiable_no_gasta_una_segunda_llamada(registrar_llamadas, skus_min, monkeypatch):
    from gondola.app import vision

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)
    llamadas, respuestas = registrar_llamadas
    respuestas.append(_respuesta(0.95))

    _obs, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert len(llamadas) == 1
    assert uso.lecturas == 1
    assert uso.nota_consenso is None


def test_una_lectura_dudosa_dispara_una_segunda_al_mismo_modelo_barato(
    registrar_llamadas, skus_min, monkeypatch
):
    """El punto de la estrategia: verificar sale más barato que escalar."""
    from gondola.app import vision

    cfg = vision.get_settings()
    monkeypatch.setattr(cfg, "openrouter_api_key", "test", raising=False)
    llamadas, respuestas = registrar_llamadas
    respuestas.extend([_respuesta(0.5), _respuesta(0.5)])

    _obs, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert len(llamadas) == 2
    # Las dos con el modelo barato, no con el grande.
    assert llamadas[0][0] == llamadas[1][0] == cfg.modelo_primario
    assert uso.escalado is False
    assert uso.lecturas == 2
    assert "acuerdo" in (uso.nota_consenso or "")


def test_la_segunda_lectura_usa_temperatura_para_no_ser_un_eco(
    registrar_llamadas, skus_min, monkeypatch
):
    from gondola.app import vision

    cfg = vision.get_settings()
    monkeypatch.setattr(cfg, "openrouter_api_key", "test", raising=False)
    llamadas, respuestas = registrar_llamadas
    respuestas.extend([_respuesta(0.5), _respuesta(0.5)])

    vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert llamadas[0][1] == 0.0
    assert llamadas[1][1] == cfg.temperatura_verificacion


def test_dos_lecturas_que_se_contradicen_escalan_al_modelo_grande(
    registrar_llamadas, monkeypatch
):
    from gondola.app import vision

    cfg = vision.get_settings()
    monkeypatch.setattr(cfg, "openrouter_api_key", "test", raising=False)
    skus = [
        Sku(id="s1", codigo="NOEL-A", nombre="A", marca="Noel", categoria="cafe"),
        Sku(id="s2", codigo="WILD-FRESA", nombre="B", marca="Wild", categoria="cafe"),
    ]
    llamadas, respuestas = registrar_llamadas
    respuestas.extend([
        _respuesta(0.5, ("NOEL-A",)),
        _respuesta(0.5, ("WILD-FRESA",)),   # no coinciden en nada
        _respuesta(0.9, ("NOEL-A",)),
    ])

    _obs, uso = vision.analizar_foto(skus, "data:image/jpeg;base64,AAA")

    assert len(llamadas) == 3
    assert llamadas[2][0] == cfg.modelo_escalado
    assert uso.escalado is True
    assert uso.lecturas == 3


def test_el_costo_de_todas_las_lecturas_se_suma(registrar_llamadas, skus_min, monkeypatch):
    """Verificar no es gratis y tiene que verse en el reporte de gasto."""
    from gondola.app import vision

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)
    _llamadas, respuestas = registrar_llamadas
    respuestas.extend([_respuesta(0.5), _respuesta(0.5)])

    _obs, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert uso.costo_usd == pytest.approx(0.0002)
    assert uso.tokens_entrada == 200
    assert uso.duracion_ms == 1000


def test_si_la_verificacion_falla_se_conserva_la_primera_lectura(skus_min, monkeypatch):
    from gondola.app import vision

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)
    intentos = {"n": 0}

    def falsa(_client, modelo, mensajes, temperatura=0.0):
        intentos["n"] += 1
        if intentos["n"] == 1:
            return _respuesta(0.5), {"cost": 0.0001}, 100
        raise vision.VisionError("timeout de OpenRouter")

    monkeypatch.setattr(vision, "_llamar_modelo", falsa)

    obs_final, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert obs_final.confianza_global == 0.5
    assert uso.nota_consenso == "verificación fallida"


def test_la_estrategia_ninguna_se_queda_con_la_primera_lectura(
    registrar_llamadas, skus_min, monkeypatch
):
    from gondola.app import vision

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)
    monkeypatch.setattr(vision.get_settings(), "estrategia_baja_confianza", "ninguna", raising=False)
    llamadas, respuestas = registrar_llamadas
    respuestas.append(_respuesta(0.3))

    vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert len(llamadas) == 1
