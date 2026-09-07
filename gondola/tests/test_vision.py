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


def _etiqueta(sku_asociado, **kw) -> dict:
    base = {
        "texto_producto": "PEPSI 2L", "precio_leido": 10.0, "moneda": "BOB",
        "legible": True, "nivel": 2, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10},
        "sku_asociado": sku_asociado, "confianza": 0.8, "es_promocion": False,
    }
    base.update(kw)
    return base


def test_descarta_la_etiqueta_de_un_sku_que_no_es_nuestro():
    """Ninguna regla mira una etiqueta de la competencia, así que guardarla
    solo ensucia el registro que ve el supervisor."""
    obs = _normalizar(bruto(etiquetas=[_etiqueta("PEPSI-2L")]), CODIGOS)
    assert obs.etiquetas == []


def test_descarta_la_etiqueta_sin_sku_asociado():
    obs = _normalizar(bruto(etiquetas=[_etiqueta(None)]), CODIGOS)
    assert obs.etiquetas == []


def test_conserva_la_etiqueta_de_un_sku_nuestro():
    obs = _normalizar(bruto(etiquetas=[_etiqueta("WILD-FRESA")]), CODIGOS)
    assert [e.sku_asociado for e in obs.etiquetas] == ["WILD-FRESA"]


def test_niveles_visibles_nunca_es_cero():
    obs = _normalizar(bruto(niveles_visibles=0), CODIGOS)
    assert obs.niveles_visibles == 1


def test_el_total_del_lineal_lo_suma_el_codigo():
    """Al modelo se le pide el desglose por bandeja, no el total: pedirle
    el total directo le sale 0 o un número redondo. La suma es aritmética
    y se hace acá, donde es auditable."""
    obs = _normalizar(bruto(frentes_por_nivel=[12, 9, 14, 8]), CODIGOS)
    assert obs.frentes_totales_lineal == 43


def test_un_desglose_vacio_cae_al_total_que_haya_mandado_el_modelo():
    """Compatibilidad: si el modelo responde con el esquema viejo, la foto
    no se pierde."""
    obs = _normalizar(
        bruto(frentes_por_nivel=[], frentes_totales_lineal=55), CODIGOS
    )
    assert obs.frentes_totales_lineal == 55


def test_el_lineal_nunca_es_menor_que_los_frentes_propios():
    """Si el total del lineal fuera menor que lo nuestro, el share of shelf
    saldría arriba de 100% y la sala aparecería mejor de lo que está."""
    obs = _normalizar(
        bruto(
            frentes_totales_lineal=3,
            detecciones=[deteccion("WILD-FRESA", frentes=8)],
        ),
        CODIGOS,
    )
    assert obs.frentes_totales_lineal == 8


def test_un_lineal_en_cero_se_respeta_como_no_medido():
    """0 significa "no pude contar el lineal", no "la góndola está llena de
    lo nuestro": rules.py saca el share del promedio en vez de inventar un
    denominador. Pisarlo con los frentes propios daría 100% de share."""
    obs = _normalizar(
        bruto(
            frentes_totales_lineal=0,
            detecciones=[deteccion("WILD-FRESA", frentes=8)],
        ),
        CODIGOS,
    )
    assert obs.frentes_totales_lineal == 0


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


@pytest.fixture(autouse=True)
def cuotas_limpias():
    """Las cuotas son globales del proceso: sin esto un test contamina al
    siguiente y los fallos dependen del orden de ejecución."""
    from gondola.app import vision

    for cuota in (vision.cuota_verificacion, vision.cuota_escalado):
        cuota._dia, cuota._total, cuota._usados = None, 0, 0
    yield


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
    assert "verificada" in (uso.nota_consenso or "")
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


def test_un_hueco_dispara_la_verificacion_aunque_la_confianza_sea_alta(
    registrar_llamadas, skus_min, monkeypatch
):
    """El caso real: Qwen reportó 95% de confianza y 12 huecos inventados.
    Antes de este cambio, esa foto se procesaba con una sola lectura."""
    from gondola.app import vision

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)
    llamadas, respuestas = registrar_llamadas

    con_hueco = _respuesta(0.95)
    con_hueco["huecos"] = [{
        "nivel": 3, "bbox": {"x0": 0, "y0": 0, "x1": 100, "y1": 100},
        "ancho_frentes_aprox": 3, "sku_codigo_sugerido": None,
    }]
    respuestas.extend([con_hueco, _respuesta(0.95)])

    obs_final, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert len(llamadas) == 2
    assert uso.lecturas == 2
    assert "hueco" in (uso.nota_consenso or "")
    # La segunda lectura no lo vio: el hueco no sobrevive al consenso.
    assert obs_final.huecos == []


def test_un_precio_fuera_de_rango_dispara_la_verificacion(
    registrar_llamadas, skus_min, monkeypatch
):
    from gondola.app import vision
    from gondola.app.schemas import Precio

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)
    llamadas, respuestas = registrar_llamadas

    con_precio_malo = _respuesta(0.95)
    con_precio_malo["etiquetas"] = [{
        "texto_producto": "A", "precio_leido": 99.0, "moneda": "BOB", "legible": True,
        "nivel": 3, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10},
        "sku_asociado": "NOEL-A", "confianza": 0.9, "es_promocion": False,
    }]
    respuestas.extend([con_precio_malo, _respuesta(0.95)])

    _obs, uso = vision.analizar_foto(
        skus_min, "data:image/jpeg;base64,AAA",
        precios={"NOEL-A": Precio(sku_id="s1", pvp=12.50, tolerancia_pct=3.0)},
    )

    assert len(llamadas) == 2
    assert "precio fuera de rango" in (uso.nota_consenso or "")


def test_la_cuota_diaria_corta_las_verificaciones(registrar_llamadas, skus_min, monkeypatch):
    """Si el modelo empieza a reportar huecos en todas partes, el gasto
    no puede dispararse en cascada."""
    from gondola.app import vision

    cfg = vision.get_settings()
    monkeypatch.setattr(cfg, "openrouter_api_key", "test", raising=False)
    monkeypatch.setattr(cfg, "verificacion_max_fraccion_diaria", 0.0, raising=False)
    llamadas, respuestas = registrar_llamadas
    respuestas.append(_respuesta(0.3))

    _obs, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert len(llamadas) == 1
    assert uso.nota_consenso == "verificación omitida por cuota"


def test_los_interruptores_de_configuracion_apagan_un_motivo(
    registrar_llamadas, skus_min, monkeypatch
):
    from gondola.app import vision

    cfg = vision.get_settings()
    monkeypatch.setattr(cfg, "openrouter_api_key", "test", raising=False)
    monkeypatch.setattr(cfg, "verificar_si_hay_huecos", False, raising=False)
    llamadas, respuestas = registrar_llamadas

    con_hueco = _respuesta(0.95)
    con_hueco["huecos"] = [{
        "nivel": 3, "bbox": {"x0": 0, "y0": 0, "x1": 100, "y1": 100},
        "ancho_frentes_aprox": 3, "sku_codigo_sugerido": None,
    }]
    respuestas.append(con_hueco)

    _obs, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert len(llamadas) == 1
    assert uso.lecturas == 1


@pytest.mark.parametrize(
    "truncado",
    [
        # Cortado antes de cerrar nada.
        '{"calidad_foto": "buena", "detecciones": [{"sku_codigo": "A", "conf',
        # Cortado pero con una llave de cierre suelta: el recorte a las
        # llaves exteriores tampoco salva este.
        '{"calidad_foto": "buena", "detecciones": [{"sku_codigo": "A"}, {"sku',
        # El bucle de tabuladores que devuelve el proveedor en la práctica.
        '{\n  "calidad_foto":  \t\t\t\t\n  "mala",\n  "detecciones": [\n    {\n      "x0": \t\t\t\n      \t\t\t\n',
    ],
)
def test_un_json_truncado_sale_como_VisionError_no_como_JSONDecodeError(truncado):
    """Si escapara el JSONDecodeError, el reintento no lo capturaría y el
    worker reventaría con una respuesta partida, que es justo el caso que
    hay que reintentar."""
    with pytest.raises(VisionError):
        _extraer_json(truncado)


def test_una_respuesta_truncada_se_reintenta_en_vez_de_matar_la_foto(skus_min, monkeypatch):
    from gondola.app import vision

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)
    intentos = {"n": 0}

    def falsa(_client, modelo, mensajes, temperatura=0.0):
        intentos["n"] += 1
        if intentos["n"] == 1:
            # Lo que devuelve el proveedor cuando corta la generación.
            return vision._extraer_json('{"calidad_foto": "buena", "detec'), {}, 100
        return _respuesta(0.95), {"cost": 0.0001}, 100

    monkeypatch.setattr(vision, "_llamar_modelo", falsa)

    obs, uso = vision.analizar_foto(skus_min, "data:image/jpeg;base64,AAA")

    assert intentos["n"] == 2
    assert obs.confianza_global == 0.95


def test_corte_por_tope_de_tokens_no_se_reintenta(monkeypatch):
    """Un corte por MAX_TOKENS_SALIDA se corta en el mismo lugar cada vez:
    reintentar solo gastaría tres llamadas para el mismo resultado. Medido
    contra SKU-110K, un tope de 4.000 tokens perdía 7 de 8 fotos y el
    mensaje decía "JSON mal formado", que manda a arreglar lo que no era."""
    from gondola.app import vision

    llamadas = {"n": 0}

    def falsa(_client, modelo, mensajes, temperatura=0.0):
        llamadas["n"] += 1
        raise vision.LimiteDeSalida("agotó el tope de tokens")

    monkeypatch.setattr(vision, "_llamar_modelo", falsa)

    with pytest.raises(vision.LimiteDeSalida):
        vision._llamar_con_reintento(None, "modelo-x", [])

    assert llamadas["n"] == 1


def test_finish_reason_length_se_reporta_como_tope_no_como_json_roto(monkeypatch):
    """El proveedor devuelve 200 con el JSON cortado a la mitad. Si eso
    saliera como VisionError genérico, el reintento lo trataría como bucle
    transitorio y la causa real quedaría escondida."""
    from gondola.app import vision

    monkeypatch.setattr(vision.get_settings(), "openrouter_api_key", "test", raising=False)

    class RespuestaCortada:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "choices": [{
                    "message": {"content": '{"calidad_foto": "buena", "detec'},
                    "finish_reason": "length",
                }],
                "usage": {"completion_tokens": 12000},
            }

    class ClienteFalso:
        @staticmethod
        def post(*_args, **_kwargs):
            return RespuestaCortada()

    with pytest.raises(vision.LimiteDeSalida) as exc:
        vision._llamar_modelo(ClienteFalso(), "modelo-x", [])

    assert "12000" in str(exc.value)
