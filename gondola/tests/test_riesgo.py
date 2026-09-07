"""Tests de cuándo se verifica una foto con una segunda lectura.

El caso que motivó todo esto: en la primera prueba real contra Qwen, el
modelo se declaró 95% seguro y reportó dos huecos que no existían. Si la
decisión de verificar dependiera de su confianza, esos dos falsos quiebres
habrían llegado al supervisor sin que nada los cuestionara.
"""

from __future__ import annotations

from gondola.app.riesgo import motivos_para_verificar
from gondola.app.schemas import (
    BBox, Deteccion, Etiqueta, Hueco, Observacion, Precio, Sku,
)


def sku(codigo, prioritario=False):
    return Sku(id=codigo, codigo=codigo, nombre=codigo, marca="Noel",
               categoria="cafe", es_prioritario=prioritario)


def det(codigo, confianza=0.9):
    return Deteccion(sku_codigo=codigo, confianza=confianza, nivel=3, frentes=2,
                     bbox=BBox(), frenteado=True)


def eti(codigo, precio):
    return Etiqueta(texto_producto=codigo, precio_leido=precio, legible=True,
                    nivel=3, sku_asociado=codigo, confianza=0.9)


def obs(confianza=0.95, **kw):
    base = dict(
        niveles_visibles=5, nivel_ojos=4, mueble_completo_visible=True,
        calidad_foto="buena", frentes_totales_lineal=40,
        detecciones=[], huecos=[], etiquetas=[], confianza_global=confianza,
    )
    base.update(kw)
    return Observacion(**base)


SKUS = [sku("NOEL-A", prioritario=True), sku("NOEL-B")]
PRECIOS = {"NOEL-A": Precio(sku_id="NOEL-A", pvp=12.50, tolerancia_pct=3.0)}


# =====================================================================
# El caso que originó el cambio
# =====================================================================


def test_un_hueco_dispara_verificacion_aunque_el_modelo_este_seguro():
    """Qwen dijo 95% de confianza y se inventó dos huecos. La confianza
    del modelo no puede ser lo que decide."""
    o = obs(confianza=0.95, detecciones=[det("NOEL-A"), det("NOEL-B")],
            huecos=[Hueco(nivel=3, ancho_frentes_aprox=3)])

    motivos = motivos_para_verificar(o, SKUS, PRECIOS)

    assert any("hueco" in m for m in motivos)


def test_una_foto_limpia_no_gasta_una_segunda_lectura():
    """Sin hallazgos caros, una sola lectura. Es el caso normal y el que
    mantiene barato el costo por foto."""
    o = obs(confianza=0.95, detecciones=[det("NOEL-A"), det("NOEL-B")],
            etiquetas=[eti("NOEL-A", 12.50)])

    assert motivos_para_verificar(o, SKUS, PRECIOS) == []


# =====================================================================
# Los tres hallazgos caros
# =====================================================================


def test_un_precio_fuera_de_tolerancia_dispara_verificacion():
    """Acusar a una sala de tener el precio mal merece una segunda mirada."""
    o = obs(detecciones=[det("NOEL-A"), det("NOEL-B")], etiquetas=[eti("NOEL-A", 15.90)])

    motivos = motivos_para_verificar(o, SKUS, PRECIOS)

    assert any("precio fuera de rango" in m for m in motivos)
    assert "15.9" in " ".join(motivos)


def test_un_precio_dentro_de_tolerancia_no_dispara_nada():
    o = obs(detecciones=[det("NOEL-A"), det("NOEL-B")], etiquetas=[eti("NOEL-A", 12.80)])
    assert motivos_para_verificar(o, SKUS, PRECIOS) == []


def test_un_sku_prioritario_ausente_dispara_verificacion():
    """Una falsa ausencia dispara una reposición de urgencia en vano."""
    o = obs(detecciones=[det("NOEL-B")])  # falta NOEL-A, que es prioritario

    motivos = motivos_para_verificar(o, SKUS, PRECIOS)

    assert any("prioritario" in m for m in motivos)
    assert "NOEL-A" in " ".join(motivos)


def test_un_sku_no_prioritario_ausente_no_dispara_nada():
    o = obs(detecciones=[det("NOEL-A")])  # falta NOEL-B, que no es prioritario
    assert motivos_para_verificar(o, SKUS, PRECIOS) == []


def test_una_deteccion_bajo_el_umbral_cuenta_como_ausente():
    o = obs(detecciones=[det("NOEL-A", confianza=0.3)])

    motivos = motivos_para_verificar(o, SKUS, PRECIOS, umbral_deteccion=0.60)

    assert any("prioritario" in m for m in motivos)


# =====================================================================
# Señales de lectura floja
# =====================================================================


def test_la_foto_de_mala_calidad_dispara_verificacion():
    o = obs(detecciones=[det("NOEL-A"), det("NOEL-B")],
            calidad_foto="mala", motivo_calidad="reflejo del tubo fluorescente")

    motivos = motivos_para_verificar(o, SKUS, PRECIOS)

    assert any("mala calidad" in m for m in motivos)
    assert "reflejo" in " ".join(motivos)


def test_la_confianza_baja_sigue_disparando_verificacion():
    o = obs(confianza=0.4, detecciones=[det("NOEL-A"), det("NOEL-B")])

    motivos = motivos_para_verificar(o, SKUS, PRECIOS, umbral_confianza=0.75)

    assert any("confianza" in m for m in motivos)


# =====================================================================
# Sin datos suficientes
# =====================================================================


def test_sin_precios_cargados_no_se_puede_juzgar_el_monto():
    """No es motivo de verificación: el vacío de datos es nuestro."""
    o = obs(detecciones=[det("NOEL-A"), det("NOEL-B")], etiquetas=[eti("NOEL-A", 999.0)])

    assert motivos_para_verificar(o, SKUS, precios=None) == []


def test_una_etiqueta_sin_precio_leido_no_dispara_nada():
    o = obs(detecciones=[det("NOEL-A"), det("NOEL-B")],
            etiquetas=[Etiqueta(sku_asociado="NOEL-A", precio_leido=None, legible=False, nivel=3)])

    assert motivos_para_verificar(o, SKUS, PRECIOS) == []


def test_los_motivos_son_legibles_para_una_persona():
    """Terminan en el registro del análisis: si alguien pregunta por qué
    esta foto costó el doble, la respuesta tiene que estar escrita."""
    o = obs(detecciones=[det("NOEL-B")], huecos=[Hueco(nivel=2, ancho_frentes_aprox=4)])

    motivos = motivos_para_verificar(o, SKUS, PRECIOS)

    assert len(motivos) == 2
    assert all(isinstance(m, str) and len(m) > 10 for m in motivos)
    assert "1 hueco(s)" in motivos[0]


def test_varios_sku_prioritarios_ausentes_se_resumen():
    skus = [sku(f"P-{i}", prioritario=True) for i in range(6)]

    motivos = motivos_para_verificar(obs(), skus, {})

    assert any("y 3 más" in m for m in motivos)
