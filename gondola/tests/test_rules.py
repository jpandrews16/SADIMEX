"""Tests del motor de reglas.

Cubren lo que tiene que ser cierto para que un score sea defendible frente
a un reponedor que reclama su nota.
"""

from __future__ import annotations

import pytest

from gondola.app.catalog import resolver_precios, resolver_reglas
from gondola.app.rules import (
    PESOS_POR_DEFECTO,
    evaluar,
    nivel_de_manos,
    nivel_de_ojos,
    semaforo_de,
)
from gondola.app.schemas import (
    BBox,
    Deteccion,
    Etiqueta,
    Hueco,
    Observacion,
    Precio,
    Regla,
    Sku,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def skus() -> list[Sku]:
    return [
        Sku(id="s1", codigo="NOEL-FESTIVAL-200", nombre="Festival 200g",
            marca="Noel", categoria="galletas", es_prioritario=True),
        Sku(id="s2", codigo="NOEL-SALTIN-250", nombre="Saltín 250g",
            marca="Noel", categoria="galletas", es_prioritario=True),
        Sku(id="s3", codigo="WILD-FRESA", nombre="Wild Protein Fresa",
            marca="Wild Protein", categoria="galletas", es_prioritario=False),
    ]


@pytest.fixture
def reglas() -> dict[str, Regla]:
    exigente = Regla(
        exige_presencia=True, nivel_objetivo="ojos_o_manos", frentes_minimos=3,
        exige_bloque=True, exige_etiqueta=True, exige_sin_quiebre=True,
    )
    return {
        "NOEL-FESTIVAL-200": exigente,
        "NOEL-SALTIN-250": exigente,
        "WILD-FRESA": Regla(exige_presencia=False, nivel_objetivo="cualquiera", frentes_minimos=1),
    }


@pytest.fixture
def precios() -> dict[str, Precio]:
    return {
        "NOEL-FESTIVAL-200": Precio(sku_id="s1", pvp=12.50, tolerancia_pct=3.0),
        "NOEL-SALTIN-250": Precio(sku_id="s2", pvp=15.00, tolerancia_pct=3.0),
    }


def det(codigo: str, nivel: int = 4, frentes: int = 3, x0: int = 100, x1: int = 200,
        confianza: float = 0.95, frenteado: bool = True) -> Deteccion:
    return Deteccion(
        sku_codigo=codigo, confianza=confianza, nivel=nivel, frentes=frentes,
        bbox=BBox(x0=x0, y0=0, x1=x1, y1=100), frenteado=frenteado,
    )


def etiqueta(codigo: str, precio: float | None = None, legible: bool = True) -> Etiqueta:
    return Etiqueta(
        texto_producto=codigo, precio_leido=precio, legible=legible,
        nivel=4, sku_asociado=codigo, confianza=0.9,
    )


def observacion_perfecta() -> Observacion:
    """Góndola ideal: 5 niveles, todo a la altura de ojos, etiquetas al PVP."""
    return Observacion(
        niveles_visibles=5,
        nivel_ojos=4,
        mueble_completo_visible=True,
        calidad_foto="buena",
        frentes_totales_lineal=40,
        detecciones=[
            det("NOEL-FESTIVAL-200", nivel=4, frentes=4, x0=100, x1=200),
            det("NOEL-SALTIN-250", nivel=4, frentes=4, x0=200, x1=300),
        ],
        huecos=[],
        etiquetas=[etiqueta("NOEL-FESTIVAL-200", 12.50), etiqueta("NOEL-SALTIN-250", 15.00)],
        confianza_global=0.93,
    )


# =====================================================================
# Alturas
# =====================================================================


def test_nivel_de_ojos_usa_lo_que_reporta_el_modelo():
    assert nivel_de_ojos(5, reportado=3) == 3


def test_nivel_de_ojos_ignora_un_reporte_imposible():
    # El modelo no puede decir "nivel 9" en un mueble de 4 bandejas.
    assert nivel_de_ojos(4, reportado=9) == 3


def test_nivel_de_ojos_calcula_cuando_no_hay_reporte():
    assert nivel_de_ojos(5) == 4
    assert nivel_de_ojos(4) == 3
    assert nivel_de_ojos(2) == 2


def test_nivel_de_manos_nunca_baja_del_piso():
    assert nivel_de_manos(1, nivel_ojos=1) == 1


# =====================================================================
# Caso completo
# =====================================================================


def test_gondola_perfecta_puntua_100(skus, reglas, precios):
    ev = evaluar(observacion_perfecta(), skus, reglas, precios)
    assert ev.score == 100
    assert ev.semaforo == "verde"
    assert ev.hallazgos == []
    assert ev.skus_ausentes == []


def test_sku_ausente_baja_presencia_y_genera_hallazgo_critico(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.detecciones = [d for d in obs.detecciones if d.sku_codigo != "NOEL-SALTIN-250"]
    obs.etiquetas = [e for e in obs.etiquetas if e.sku_asociado != "NOEL-SALTIN-250"]

    ev = evaluar(obs, skus, reglas, precios)

    assert "NOEL-SALTIN-250" in ev.skus_ausentes
    assert ev.reglas["presencia"].cumplimiento == 0.5
    assert not ev.reglas["presencia"].cumple
    criticos = [h for h in ev.hallazgos if h.severidad == "critico"]
    assert any(h.sku_codigo == "NOEL-SALTIN-250" for h in criticos)


def test_deteccion_bajo_el_umbral_no_cuenta_como_presente(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.detecciones[1].confianza = 0.35  # el modelo dudó

    ev = evaluar(obs, skus, reglas, precios, umbral_deteccion=0.60)

    assert "NOEL-SALTIN-250" in ev.skus_ausentes


# =====================================================================
# R2 nivel
# =====================================================================


def test_producto_en_el_piso_incumple_altura_de_ojos(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.detecciones[0].nivel = 1  # se fue al piso

    ev = evaluar(obs, skus, reglas, precios)

    assert not ev.reglas["nivel"].cumple
    assert ev.reglas["nivel"].cumplimiento == 0.5
    assert "inferior" in ev.reglas["nivel"].detalle


def test_sin_mueble_completo_la_altura_no_se_evalua(skus, reglas, precios):
    """No se castiga por algo que la foto no permite ver."""
    obs = observacion_perfecta()
    obs.mueble_completo_visible = False
    obs.detecciones[0].nivel = 1

    ev = evaluar(obs, skus, reglas, precios)

    assert "nivel" not in ev.reglas
    # Y el score no se hunde por una regla que no se pudo medir.
    assert ev.score == 100
    assert any("mueble no se ve completo" in h.mensaje for h in ev.hallazgos)


# =====================================================================
# R3 frentes y share
# =====================================================================


def test_frentes_por_debajo_del_minimo_dan_credito_parcial(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.detecciones[0].frentes = 1  # exige 3

    ev = evaluar(obs, skus, reglas, precios)

    assert ev.reglas["frentes"].cumplimiento == pytest.approx((1 / 3 + 1) / 2)
    assert not ev.reglas["frentes"].cumple


def test_share_of_shelf_se_calcula_sobre_el_lineal_completo(skus, reglas, precios):
    obs = observacion_perfecta()  # 8 frentes propios de 40 del lineal
    ev = evaluar(obs, skus, reglas, precios)
    assert ev.share_of_shelf_pct == 20.0


def test_share_bajo_el_minimo_penaliza(skus, precios):
    reglas = {
        "NOEL-FESTIVAL-200": Regla(frentes_minimos=1, share_minimo_pct=40.0),
        "NOEL-SALTIN-250": Regla(frentes_minimos=1, share_minimo_pct=40.0),
        "WILD-FRESA": Regla(exige_presencia=False),
    }
    ev = evaluar(observacion_perfecta(), skus, reglas, precios)
    # 20% real contra 40% exigido = medio punto en la parte de share.
    assert not ev.reglas["frentes"].cumple
    assert ev.reglas["frentes"].cumplimiento < 1.0


# =====================================================================
# R4 bloque de marca
# =====================================================================


def test_marca_partida_en_el_lineal_rompe_el_bloque(skus, reglas, precios):
    obs = observacion_perfecta()
    # Los dos Noel quedan en el mismo nivel pero separados por medio lineal.
    obs.detecciones = [
        det("NOEL-FESTIVAL-200", nivel=4, frentes=4, x0=100, x1=200),
        det("NOEL-SALTIN-250", nivel=4, frentes=4, x0=700, x1=800),
    ]

    ev = evaluar(obs, skus, reglas, precios)

    assert not ev.reglas["bloque"].cumple
    assert ev.reglas["bloque"].cumplimiento < 1.0
    assert "Noel" in ev.reglas["bloque"].detalle


def test_marca_en_varios_niveles_contiguos_no_penaliza(skus, reglas, precios):
    """Ocupar dos bandejas es buena ejecución, no dispersión."""
    obs = observacion_perfecta()
    obs.detecciones = [
        det("NOEL-FESTIVAL-200", nivel=4, frentes=4, x0=100, x1=200),
        det("NOEL-SALTIN-250", nivel=3, frentes=4, x0=100, x1=200),
    ]

    ev = evaluar(obs, skus, reglas, precios)

    assert ev.reglas["bloque"].cumple


# =====================================================================
# R5 etiquetas de precio
# =====================================================================


def test_etiqueta_ausente_genera_hallazgo(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.etiquetas = [e for e in obs.etiquetas if e.sku_asociado != "NOEL-FESTIVAL-200"]

    ev = evaluar(obs, skus, reglas, precios)

    assert not ev.reglas["etiqueta"].cumple
    assert any(h.regla == "etiqueta" and "Falta etiqueta" in h.mensaje for h in ev.hallazgos)


def test_precio_fuera_de_tolerancia_es_critico(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.etiquetas[0] = etiqueta("NOEL-FESTIVAL-200", 15.90)  # PVP 12.50

    ev = evaluar(obs, skus, reglas, precios)

    criticos = [h for h in ev.hallazgos if h.severidad == "critico" and h.regla == "etiqueta"]
    assert len(criticos) == 1
    assert "15.9" in criticos[0].mensaje


def test_precio_dentro_de_tolerancia_pasa(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.etiquetas[0] = etiqueta("NOEL-FESTIVAL-200", 12.80)  # 2.4% de desvío, tolerancia 3%

    ev = evaluar(obs, skus, reglas, precios)

    assert ev.reglas["etiqueta"].cumple


def test_sin_pvp_cargado_no_se_castiga_al_reponedor(skus, reglas):
    """El vacío de datos es nuestro, no de quien repone."""
    obs = observacion_perfecta()
    obs.etiquetas[0] = etiqueta("NOEL-FESTIVAL-200", 99.99)

    ev = evaluar(obs, skus, reglas, precios={})

    assert ev.reglas["etiqueta"].cumple
    assert not any(h.regla == "etiqueta" for h in ev.hallazgos)


def test_etiqueta_ilegible_puntua_parcial(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.etiquetas[0] = etiqueta("NOEL-FESTIVAL-200", None, legible=False)

    ev = evaluar(obs, skus, reglas, precios)

    assert 0 < ev.reglas["etiqueta"].cumplimiento < 1.0
    assert any("ilegible" in h.mensaje for h in ev.hallazgos)


# =====================================================================
# R6 quiebres
# =====================================================================


def test_hueco_en_gondola_cuenta_como_quiebre(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.huecos = [Hueco(nivel=4, ancho_frentes_aprox=4, bbox=BBox(x0=300, y0=0, x1=400, y1=100))]

    ev = evaluar(obs, skus, reglas, precios)

    assert ev.quiebres_detectados == 1
    assert not ev.reglas["sin_quiebre"].cumple
    assert any(h.regla == "sin_quiebre" for h in ev.hallazgos)


def test_producto_sin_frentear_penaliza_parcialmente(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.detecciones[0].frenteado = False

    ev = evaluar(obs, skus, reglas, precios)

    assert not ev.reglas["sin_quiebre"].cumple
    assert ev.reglas["sin_quiebre"].cumplimiento == pytest.approx(0.7 + 0.3 * 0.5)


# =====================================================================
# Score y semáforo
# =====================================================================


def test_semaforo_respeta_los_umbrales():
    assert semaforo_de(80, 80, 60) == "verde"
    assert semaforo_de(79, 80, 60) == "amarillo"
    assert semaforo_de(60, 80, 60) == "amarillo"
    assert semaforo_de(59, 80, 60) == "rojo"


def test_score_solo_pondera_reglas_evaluables(skus, precios):
    """Si solo aplica presencia, el score es el de presencia, no 30/100."""
    reglas = {
        s.codigo: Regla(
            exige_presencia=True, nivel_objetivo="cualquiera", frentes_minimos=0,
            exige_bloque=False, exige_etiqueta=False, exige_sin_quiebre=False,
        )
        for s in skus
    }
    obs = observacion_perfecta()
    obs.frentes_totales_lineal = 0

    ev = evaluar(obs, skus, reglas, precios)

    assert set(ev.reglas) == {"presencia"}
    # 2 de 3 SKU obligatorios presentes.
    assert ev.score == 67


def test_foto_mala_avisa_que_el_analisis_es_dudoso(skus, reglas, precios):
    obs = observacion_perfecta()
    obs.calidad_foto = "mala"
    obs.motivo_calidad = "reflejo del flash sobre el riel"

    ev = evaluar(obs, skus, reglas, precios)

    assert any("mala calidad" in h.mensaje for h in ev.hallazgos)


def test_pesos_por_defecto_suman_uno():
    assert sum(PESOS_POR_DEFECTO.values()) == pytest.approx(1.0)


# =====================================================================
# Resolución de reglas (jerarquía)
# =====================================================================


def test_la_regla_de_cadena_manda_sobre_la_nacional(skus):
    filas = [
        {"nombre": "nacional", "marca": "Noel", "frentes_minimos": 2, "nivel_objetivo": "cualquiera"},
        {"nombre": "hipermaxi", "cadena_id": "c1", "marca": "Noel",
         "frentes_minimos": 6, "nivel_objetivo": "ojos"},
    ]

    resueltas = resolver_reglas(skus, filas, cadena_id="c1")

    assert resueltas["NOEL-FESTIVAL-200"].nombre == "hipermaxi"
    assert resueltas["NOEL-FESTIVAL-200"].frentes_minimos == 6


def test_la_regla_de_otra_cadena_no_se_aplica(skus):
    filas = [
        {"nombre": "nacional", "marca": "Noel", "frentes_minimos": 2},
        {"nombre": "ketal", "cadena_id": "c2", "marca": "Noel", "frentes_minimos": 6},
    ]

    resueltas = resolver_reglas(skus, filas, cadena_id="c1")

    assert resueltas["NOEL-FESTIVAL-200"].nombre == "nacional"


def test_sku_sin_regla_recibe_la_de_por_defecto(skus):
    resueltas = resolver_reglas(skus, [{"nombre": "otra_marca", "marca": "Inexistente"}], None)
    assert resueltas["WILD-FRESA"].nombre == "default"


def test_precio_de_cadena_gana_al_nacional(skus):
    filas = [
        {"sku_id": "s1", "cadena_id": None, "pvp": 12.50, "vigente_hasta": None},
        {"sku_id": "s1", "cadena_id": "c1", "pvp": 13.90, "vigente_hasta": None},
    ]

    resueltos = resolver_precios(skus, filas, cadena_id="c1")

    assert resueltos["NOEL-FESTIVAL-200"].pvp == 13.90


def test_precio_vencido_se_ignora(skus):
    filas = [{"sku_id": "s1", "cadena_id": None, "pvp": 9.90, "vigente_hasta": "2025-01-01"}]
    assert resolver_precios(skus, filas, None) == {}
