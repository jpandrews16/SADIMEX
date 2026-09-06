"""Tests de los controles de costo.

Con volumen alto y muchas categorías, dos cosas deciden la factura: cuánto
pesa la hoja de referencia (viaja en CADA foto) y cuántas fotos escalan al
modelo grande.
"""

from __future__ import annotations

from gondola.app.reference_sheet import seleccionar_para_hoja
from gondola.app.schemas import Sku
from gondola.app.vision import CuotaEscalado


def sku(codigo: str, prioritario: bool = False, con_foto: bool = True) -> Sku:
    return Sku(
        id=codigo, codigo=codigo, nombre=codigo, marca="Noel", categoria="cafe",
        es_prioritario=prioritario,
        packshot_url=f"https://cdn/{codigo}.png" if con_foto else None,
    )


# =====================================================================
# Hoja de referencia
# =====================================================================


def test_catalogo_chico_entra_completo():
    skus = [sku(f"A-{i}") for i in range(5)]
    assert len(seleccionar_para_hoja(skus, tope=24)) == 5


def test_catalogo_grande_se_corta_en_el_tope():
    """348 packshots en cada llamada arruinarían el costo por foto."""
    skus = [sku(f"A-{i:03d}") for i in range(100)]
    assert len(seleccionar_para_hoja(skus, tope=24)) == 24


def test_los_prioritarios_entran_primero():
    skus = [sku(f"Z-{i:03d}") for i in range(50)] + [sku("P-1", prioritario=True)]

    seleccion = seleccionar_para_hoja(skus, tope=5)

    assert "P-1" in {s.codigo for s in seleccion}


def test_la_seleccion_es_estable_entre_llamadas():
    """Si cambiara en cada foto, la caché del mosaico nunca serviría."""
    skus = [sku(f"A-{i:03d}") for i in range(50)]

    primera = [s.codigo for s in seleccionar_para_hoja(skus, tope=10)]
    segunda = [s.codigo for s in seleccionar_para_hoja(list(reversed(skus)), tope=10)]

    assert primera == segunda


def test_los_sku_sin_packshot_no_ocupan_lugar():
    skus = [sku("A-1"), sku("A-2", con_foto=False), sku("A-3")]
    assert [s.codigo for s in seleccionar_para_hoja(skus, tope=24)] == ["A-1", "A-3"]


# =====================================================================
# Cuota de escalado
# =====================================================================


def test_la_primera_foto_del_dia_siempre_puede_escalar():
    cuota = CuotaEscalado()
    cuota.registrar_foto()
    assert cuota.permite_escalar(0.20) is True


def test_la_cuota_corta_cuando_se_pasa_de_la_fraccion():
    """Un lote de fotos malas no puede multiplicar la factura del día."""
    cuota = CuotaEscalado()
    for _ in range(10):
        cuota.registrar_foto()

    # Tope 20% de 10 fotos = 2 escalados.
    assert cuota.permite_escalar(0.20)
    cuota.registrar_escalado()
    assert cuota.permite_escalar(0.20)
    cuota.registrar_escalado()
    assert not cuota.permite_escalar(0.20)


def test_fraccion_cero_desactiva_el_escalado():
    cuota = CuotaEscalado()
    cuota.registrar_foto()
    assert cuota.permite_escalar(0.0) is False


def test_fraccion_uno_deja_escalar_siempre():
    cuota = CuotaEscalado()
    for _ in range(3):
        cuota.registrar_foto()
        cuota.registrar_escalado()
    assert cuota.permite_escalar(1.0) is True


def test_la_cuota_se_reinicia_al_cambiar_el_dia():
    cuota = CuotaEscalado()
    for _ in range(10):
        cuota.registrar_foto()
    cuota.registrar_escalado()
    cuota.registrar_escalado()
    assert not cuota.permite_escalar(0.20)

    cuota._dia = "1999-01-01"  # fuerza la rotación

    assert cuota.estado()["fotos"] == 0
    assert cuota.permite_escalar(0.20) is True


def test_el_estado_reporta_el_consumo():
    cuota = CuotaEscalado()
    cuota.registrar_foto()
    cuota.registrar_escalado()

    estado = cuota.estado()

    assert estado["fotos"] == 1
    assert estado["escalados"] == 1
    assert estado["dia"]
