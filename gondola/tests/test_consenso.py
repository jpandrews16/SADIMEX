"""Tests de la fusión de dos lecturas.

El criterio que estos tests protegen: **conservador donde el error es
caro.** Es preferible decir "no sé" que afirmar algo falso sobre una sala
o sobre el trabajo de una persona.
"""

from __future__ import annotations

import pytest

from gondola.app.consenso import (
    BONUS_ACUERDO,
    PENALIZACION_SIN_ACUERDO,
    fusionar,
)
from gondola.app.schemas import BBox, Deteccion, Etiqueta, Hueco, Observacion


def det(codigo, nivel=3, frentes=4, confianza=0.9, x0=100, x1=200, frenteado=True):
    return Deteccion(
        sku_codigo=codigo, confianza=confianza, nivel=nivel, frentes=frentes,
        bbox=BBox(x0=x0, y0=0, x1=x1, y1=100), frenteado=frenteado,
    )


def eti(codigo, precio=12.5, legible=True, confianza=0.9, nivel=3):
    return Etiqueta(
        texto_producto=codigo, precio_leido=precio, legible=legible,
        nivel=nivel, sku_asociado=codigo, confianza=confianza,
    )


def obs(detecciones=None, etiquetas=None, huecos=None, confianza=0.6, **kw):
    base = dict(
        niveles_visibles=5, nivel_ojos=4, mueble_completo_visible=True,
        calidad_foto="buena", frentes_totales_lineal=40,
        detecciones=detecciones or [], etiquetas=etiquetas or [],
        huecos=huecos or [], confianza_global=confianza,
    )
    base.update(kw)
    return Observacion(**base)


# =====================================================================
# Detecciones
# =====================================================================


def test_lo_que_ven_las_dos_lecturas_gana_confianza():
    a = obs([det("NOEL-A", confianza=0.8)])
    b = obs([det("NOEL-A", confianza=0.8)])

    fusion, acuerdo = fusionar(a, b)

    assert len(fusion.detecciones) == 1
    assert fusion.detecciones[0].confianza == pytest.approx(0.8 + BONUS_ACUERDO)
    assert acuerdo.skus_en_ambas == ["NOEL-A"]


def test_lo_que_ve_solo_una_lectura_queda_castigado():
    """Un SKU que solo vio una pasada no debería contar como presente."""
    a = obs([det("NOEL-A", confianza=0.9), det("NOEL-B", confianza=0.9)])
    b = obs([det("NOEL-A", confianza=0.9)])

    fusion, acuerdo = fusionar(a, b)

    solitaria = next(d for d in fusion.detecciones if d.sku_codigo == "NOEL-B")
    assert solitaria.confianza == pytest.approx(0.9 * PENALIZACION_SIN_ACUERDO)
    # Con el umbral de detección por defecto (0.60) deja de contar.
    assert solitaria.confianza < 0.60
    assert acuerdo.skus_en_una == ["NOEL-B"]


def test_los_frentes_se_promedian():
    """Contar unidades iguales en fila es lo que un LLM hace peor."""
    fusion, _ = fusionar(obs([det("A", frentes=4)]), obs([det("A", frentes=6)]))
    assert fusion.detecciones[0].frentes == 5


def test_si_discrepan_de_nivel_manda_la_lectura_mas_segura():
    a = obs([det("A", nivel=4, confianza=0.95)])
    b = obs([det("A", nivel=3, confianza=0.60)])

    fusion, _ = fusionar(a, b)

    assert fusion.detecciones[0].nivel == 4


def test_el_mismo_sku_en_dos_bandejas_no_se_cruza():
    """Una marca puede ocupar dos niveles: son detecciones distintas."""
    a = obs([det("A", nivel=2), det("A", nivel=4)])
    b = obs([det("A", nivel=2), det("A", nivel=4)])

    fusion, acuerdo = fusionar(a, b)

    assert len(fusion.detecciones) == 2
    assert sorted(d.nivel for d in fusion.detecciones) == [2, 4]
    assert acuerdo.skus_en_una == []


def test_basta_que_una_lectura_lo_vea_desordenado():
    fusion, _ = fusionar(obs([det("A", frenteado=True)]), obs([det("A", frenteado=False)]))
    assert fusion.detecciones[0].frenteado is False


# =====================================================================
# Precios — el caso más caro del sistema
# =====================================================================


def test_precios_iguales_se_conservan():
    fusion, acuerdo = fusionar(obs(etiquetas=[eti("A", 12.50)]), obs(etiquetas=[eti("A", 12.50)]))

    assert fusion.etiquetas[0].precio_leido == 12.50
    assert fusion.etiquetas[0].legible is True
    assert acuerdo.precios_descartados == []


def test_precios_distintos_se_descartan_y_la_etiqueta_queda_ilegible():
    """Acusar a una sala de tener el precio mal por un dígito mal leído es
    el error más caro que este software puede cometer."""
    fusion, acuerdo = fusionar(obs(etiquetas=[eti("A", 12.50)]), obs(etiquetas=[eti("A", 15.90)]))

    assert fusion.etiquetas[0].precio_leido is None
    assert fusion.etiquetas[0].legible is False
    assert len(acuerdo.precios_descartados) == 1
    assert "12.5" in acuerdo.precios_descartados[0]
    assert "15.9" in acuerdo.precios_descartados[0]


def test_una_diferencia_de_redondeo_no_descarta_el_precio():
    fusion, acuerdo = fusionar(obs(etiquetas=[eti("A", 12.50)]), obs(etiquetas=[eti("A", 12.505)]))

    assert fusion.etiquetas[0].precio_leido == 12.50
    assert acuerdo.precios_descartados == []


def test_si_solo_una_lectura_leyo_el_precio_se_conserva():
    """La otra pudo no verlo por reflejo: eso no es ausencia de precio."""
    fusion, _ = fusionar(obs(etiquetas=[eti("A", 12.50)]), obs(etiquetas=[eti("A", None)]))
    assert fusion.etiquetas[0].precio_leido == 12.50


def test_etiqueta_vista_por_una_sola_lectura_baja_su_confianza():
    fusion, _ = fusionar(obs(etiquetas=[eti("A", 12.50, confianza=1.0)]), obs())

    assert len(fusion.etiquetas) == 1
    assert fusion.etiquetas[0].confianza == pytest.approx(0.8)


def test_una_lectura_ilegible_marca_la_etiqueta_como_ilegible():
    fusion, _ = fusionar(
        obs(etiquetas=[eti("A", 12.50, legible=True)]),
        obs(etiquetas=[eti("A", 12.50, legible=False)]),
    )
    assert fusion.etiquetas[0].legible is False


# =====================================================================
# Huecos — un falso quiebre manda gente a una sala sin problema
# =====================================================================


def test_solo_los_huecos_vistos_por_ambas_cuentan():
    a = obs(huecos=[Hueco(nivel=3, ancho_frentes_aprox=4)])
    b = obs(huecos=[])

    fusion, acuerdo = fusionar(a, b)

    assert fusion.huecos == []
    assert acuerdo.huecos_descartados == 1


def test_un_hueco_confirmado_se_conserva_con_el_ancho_menor():
    a = obs(huecos=[Hueco(nivel=3, ancho_frentes_aprox=5)])
    b = obs(huecos=[Hueco(nivel=3, ancho_frentes_aprox=2)])

    fusion, _ = fusionar(a, b)

    assert len(fusion.huecos) == 1
    assert fusion.huecos[0].ancho_frentes_aprox == 2


# =====================================================================
# Estructura de la góndola
# =====================================================================


def test_si_una_lectura_dice_que_el_mueble_sale_cortado_no_se_evalua_la_altura():
    a = obs(mueble_completo_visible=True)
    b = obs(mueble_completo_visible=False)

    fusion, _ = fusionar(a, b)

    assert fusion.mueble_completo_visible is False


def test_se_conserva_la_peor_calidad_de_foto():
    fusion, _ = fusionar(obs(calidad_foto="buena"), obs(calidad_foto="mala"))
    assert fusion.calidad_foto == "mala"


def test_los_frentes_del_lineal_se_promedian():
    fusion, _ = fusionar(obs(frentes_totales_lineal=40), obs(frentes_totales_lineal=50))
    assert fusion.frentes_totales_lineal == 45


def test_la_discrepancia_de_niveles_queda_registrada():
    _, acuerdo = fusionar(obs(niveles_visibles=5), obs(niveles_visibles=4))
    assert acuerdo.niveles_discrepan is True


# =====================================================================
# Confianza global
# =====================================================================


def test_dos_lecturas_que_coinciden_conservan_su_confianza():
    a = obs([det("A")], confianza=0.8)
    b = obs([det("A")], confianza=0.8)

    fusion, acuerdo = fusionar(a, b)

    assert acuerdo.indice == 1.0
    assert fusion.confianza_global == pytest.approx(0.8)


def test_dos_lecturas_seguras_que_se_contradicen_dan_confianza_baja():
    """Es el punto de todo esto: la seguridad del modelo no vale nada si
    dos lecturas independientes ven cosas distintas."""
    a = obs([det("A"), det("B")], confianza=0.9)
    b = obs([det("C"), det("D")], confianza=0.9)

    fusion, acuerdo = fusionar(a, b)

    assert acuerdo.indice == 0.0
    assert fusion.confianza_global == pytest.approx(0.45)
    assert fusion.confianza_global < min(a.confianza_global, b.confianza_global)


def test_el_acuerdo_de_dos_lecturas_vacias_es_total():
    """Ninguna vio nada: coinciden, y eso no debe leerse como desacuerdo."""
    _, acuerdo = fusionar(obs(), obs())
    assert acuerdo.indice == 1.0


def test_el_resumen_describe_lo_que_paso():
    a = obs([det("A"), det("B")], etiquetas=[eti("A", 12.5)], confianza=0.7)
    b = obs([det("A")], etiquetas=[eti("A", 99.9)], confianza=0.7)

    _, acuerdo = fusionar(a, b)
    resumen = acuerdo.resumen()

    assert "acuerdo" in resumen
    assert "sin confirmar" in resumen
    assert "precios descartados" in resumen


# =====================================================================
# Integración con el motor de reglas
# =====================================================================


def test_el_consenso_evita_un_falso_quiebre_en_el_score():
    """Un hueco que solo vio una lectura no debe generar un hallazgo."""
    from gondola.app.rules import evaluar
    from gondola.app.schemas import Regla, Sku

    skus = [Sku(id="s1", codigo="A", nombre="Producto A", marca="Noel", categoria="cafe")]
    reglas = {"A": Regla(nivel_objetivo="cualquiera", frentes_minimos=1)}

    a = obs([det("A")], huecos=[Hueco(nivel=3, ancho_frentes_aprox=6)], etiquetas=[eti("A", 12.5)])
    b = obs([det("A")], huecos=[], etiquetas=[eti("A", 12.5)])

    fusion, _ = fusionar(a, b)
    evaluacion = evaluar(fusion, skus, reglas, precios={})

    assert evaluacion.quiebres_detectados == 0
    assert not any(h.regla == "sin_quiebre" for h in evaluacion.hallazgos)


def test_el_consenso_evita_acusar_de_precio_incorrecto_con_una_mala_lectura():
    from gondola.app.rules import evaluar
    from gondola.app.schemas import Precio, Regla, Sku

    skus = [Sku(id="s1", codigo="A", nombre="Producto A", marca="Noel", categoria="cafe")]
    reglas = {"A": Regla(nivel_objetivo="cualquiera", frentes_minimos=1)}
    precios = {"A": Precio(sku_id="s1", pvp=12.50, tolerancia_pct=3.0)}

    # Una lectura leyó bien; la otra leyó 15.90. Sin consenso, el sistema
    # habría reportado "precio incorrecto, 27% de desvío" como crítico.
    a = obs([det("A")], etiquetas=[eti("A", 12.50)])
    b = obs([det("A")], etiquetas=[eti("A", 15.90)])

    fusion, _ = fusionar(a, b)
    evaluacion = evaluar(fusion, skus, reglas, precios)

    criticos = [h for h in evaluacion.hallazgos if h.severidad == "critico"]
    assert not any("desvío" in h.mensaje for h in criticos)
    assert any("ilegible" in h.mensaje for h in evaluacion.hallazgos)


# =====================================================================
# Conteo del lineal
# =====================================================================


def test_una_lectura_que_no_conto_el_lineal_no_arrastra_a_la_otra():
    """Un 0 es "esta lectura no contó", no "la góndola está vacía".
    Promediarlo partiría el denominador del share of shelf a la mitad, y
    la sala aparecería con el doble de espacio del que tiene."""
    fusion, _ = fusionar(obs(frentes_totales_lineal=80), obs(frentes_totales_lineal=0))

    assert fusion.frentes_totales_lineal == 80


def test_si_ninguna_lectura_conto_el_lineal_queda_sin_medir():
    fusion, _ = fusionar(obs(frentes_totales_lineal=0), obs(frentes_totales_lineal=0))

    assert fusion.frentes_totales_lineal == 0


def test_dos_conteos_validos_se_promedian():
    fusion, _ = fusionar(obs(frentes_totales_lineal=80), obs(frentes_totales_lineal=90))

    assert fusion.frentes_totales_lineal == 85
