"""Fusión de dos lecturas independientes de la misma foto.

Por qué existe este módulo
--------------------------
La autoevaluación de un modelo ("mi confianza es 0.8") es poco fiable: un
modelo puede estar seguro y equivocado. En cambio, si se le pide la misma
foto dos veces con enfoques distintos y **las dos lecturas coinciden**, eso
sí es evidencia. Y donde no coinciden, es exactamente donde no hay que
confiar.

Además sale más barato que escalar: dos llamadas al modelo chico cuestan
menos que una al grande, sobre todo en tokens de salida.

Criterio general: **conservador donde el error es caro.**

  * Un producto que solo vio una de las dos lecturas queda con la
    confianza castigada, así que probablemente no llegue a contar como
    presente. Preferimos no afirmar que un SKU está.
  * Un hueco que solo vio una lectura se descarta. Un falso quiebre manda
    a un supervisor a una sala donde no había problema, y eso quema la
    confianza en el sistema más rápido que cualquier otra cosa.
  * Un precio leído distinto en cada pasada se descarta y la etiqueta pasa
    a "ilegible". Acusar a una sala de tener el precio mal por un dígito
    mal leído es el error más caro que este software puede cometer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .schemas import Deteccion, Etiqueta, Hueco, Observacion

log = logging.getLogger(__name__)

# Cuánto se castiga una detección que solo apareció en una de las dos
# lecturas. Con el umbral de detección por defecto (0.60), una detección
# de confianza 0.9 vista una sola vez cae a 0.54 y deja de contar.
PENALIZACION_SIN_ACUERDO = 0.60

# Bonus por coincidir, con techo en 1.0. Dos lecturas que ven lo mismo
# merecen más crédito que el promedio de sus confianzas.
BONUS_ACUERDO = 0.10

# Diferencia máxima en bolivianos para dar dos lecturas de precio por
# iguales. Cubre el redondeo, no un dígito distinto.
TOLERANCIA_PRECIO = 0.01

# Niveles de diferencia que se toleran al emparejar la misma detección
# entre las dos lecturas.
MAX_DISTANCIA_NIVEL = 1


@dataclass
class Acuerdo:
    """Cuánto coincidieron las dos lecturas. Sirve para diagnóstico."""

    skus_en_ambas: list[str] = field(default_factory=list)
    skus_en_una: list[str] = field(default_factory=list)
    # Las dos lecturas vieron el producto pero no coinciden en la variante.
    # No es desacuerdo sobre la presencia: cuenta como acuerdo en el índice.
    variantes_en_disputa: list[str] = field(default_factory=list)
    precios_descartados: list[str] = field(default_factory=list)
    huecos_descartados: int = 0
    niveles_discrepan: bool = False

    @property
    def indice(self) -> float:
        """0.0-1.0. Jaccard de los SKU vistos por cada lectura.

        Una variante en disputa cuenta del lado del acuerdo: las dos
        lecturas coincidieron en que ahí hay un producto nuestro, que es
        lo que este índice mide.
        """
        de_acuerdo = len(self.skus_en_ambas) + len(self.variantes_en_disputa)
        total = de_acuerdo + len(self.skus_en_una)
        if total == 0:
            return 1.0  # ninguna vio nada: coinciden en el vacío
        return de_acuerdo / total

    def resumen(self) -> str:
        partes = [f"acuerdo {self.indice:.0%}"]
        if self.skus_en_una:
            partes.append(f"{len(self.skus_en_una)} SKU sin confirmar")
        if self.precios_descartados:
            partes.append(f"{len(self.precios_descartados)} precios descartados")
        if self.huecos_descartados:
            partes.append(f"{self.huecos_descartados} huecos descartados")
        if self.niveles_discrepan:
            partes.append("discrepan los niveles")
        return "; ".join(partes)


# =====================================================================
# Emparejamiento
# =====================================================================


def _se_solapan(a: Deteccion, b: Deteccion) -> bool:
    """¿Las dos cajas ocupan el mismo tramo horizontal de la bandeja?"""
    solape = min(a.bbox.x1, b.bbox.x1) - max(a.bbox.x0, b.bbox.x0)
    menor = min(a.bbox.ancho, b.bbox.ancho)
    return menor > 0 and solape > menor / 2


def _disputas_de_variante(
    huerfanas_a: list[Deteccion],
    huerfanas_b: list[Deteccion],
    marcas: dict[str, str],
) -> tuple[list[tuple[Deteccion, Deteccion]], list[Deteccion]]:
    """Detecta el caso "las dos lecturas vieron el producto, discuten cuál es".

    Con un catálogo fino esto es lo normal: una lectura dice
    FESTIVAL-SABORFRESA y la otra FESTIVAL-SABORLIMON, en la misma bandeja
    y en el mismo tramo. Emparejando por código exacto no casan, las dos
    quedan huérfanas, las dos se castigan y el producto desaparece —aunque
    las dos lecturas coincidieron en que ahí hay algo nuestro—.

    Eso invierte el criterio del módulo. El castigo existe para no AFIRMAR
    una presencia que solo vio una lectura; acá la presencia la vieron las
    dos y lo único en duda es la variante. Se conserva la lectura más
    segura sin el castigo fuerte: la duda de variante ya queda registrada
    en el acuerdo.

    Solo cuenta como disputa de variante si los dos SKU son de la MISMA
    MARCA. Que una lectura vea Ducales y la otra Saltín Noel en el mismo
    lugar no es una duda de sabor: es un desacuerdo de verdad, y ese sí
    lleva castigo. Sin `marcas` no se puede distinguir un caso del otro,
    así que no se empareja nada.
    """
    disputas: list[tuple[Deteccion, Deteccion]] = []
    libres_b = list(huerfanas_b)
    sin_pareja: list[Deteccion] = []

    def misma_marca(x: Deteccion, y: Deteccion) -> bool:
        marca_x, marca_y = marcas.get(x.sku_codigo), marcas.get(y.sku_codigo)
        return bool(marca_x) and marca_x == marca_y

    for det_a in huerfanas_a:
        rival = next(
            (
                d for d in libres_b
                if abs(d.nivel - det_a.nivel) <= MAX_DISTANCIA_NIVEL
                and _se_solapan(det_a, d)
                and misma_marca(det_a, d)
            ),
            None,
        )
        if rival is None:
            sin_pareja.append(det_a)
        else:
            libres_b.remove(rival)
            disputas.append((det_a, rival))

    return disputas, sin_pareja + libres_b


def _emparejar_detecciones(
    a: list[Deteccion], b: list[Deteccion], marcas: dict[str, str]
) -> tuple[list[tuple[Deteccion, Deteccion]], list[Deteccion], list[Deteccion]]:
    """Empareja detecciones del mismo SKU entre las dos lecturas.

    Dentro de un SKU se emparejan por nivel más cercano: la misma caja de
    galletas puede estar en dos bandejas, y no queremos cruzar una con la
    otra. Lo que no encuentra pareja se devuelve aparte.
    """
    por_sku_a: dict[str, list[Deteccion]] = {}
    por_sku_b: dict[str, list[Deteccion]] = {}
    for d in a:
        por_sku_a.setdefault(d.sku_codigo, []).append(d)
    for d in b:
        por_sku_b.setdefault(d.sku_codigo, []).append(d)

    parejas: list[tuple[Deteccion, Deteccion]] = []
    # Se separan por lectura de origen: dos huérfanas de la MISMA lectura
    # no pueden ser la misma caja discutida, así que solo se cruzan las de
    # lecturas distintas.
    huerfanas_a: list[Deteccion] = []
    huerfanas_b: list[Deteccion] = []

    for codigo in sorted(set(por_sku_a) | set(por_sku_b)):
        lista_a = sorted(por_sku_a.get(codigo, []), key=lambda d: d.nivel)
        lista_b = sorted(por_sku_b.get(codigo, []), key=lambda d: d.nivel)
        libres_b = list(lista_b)

        for det_a in lista_a:
            candidata = None
            for det_b in libres_b:
                if abs(det_b.nivel - det_a.nivel) <= MAX_DISTANCIA_NIVEL:
                    if candidata is None or abs(det_b.nivel - det_a.nivel) < abs(candidata.nivel - det_a.nivel):
                        candidata = det_b
            if candidata is not None:
                libres_b.remove(candidata)
                parejas.append((det_a, candidata))
            else:
                huerfanas_a.append(det_a)

        huerfanas_b.extend(libres_b)

    disputas, sueltas = _disputas_de_variante(huerfanas_a, huerfanas_b, marcas)
    return parejas, disputas, sueltas


def _fusionar_pareja(a: Deteccion, b: Deteccion) -> Deteccion:
    """Una detección confirmada por las dos lecturas."""
    confianza = min(1.0, (a.confianza + b.confianza) / 2 + BONUS_ACUERDO)
    mejor = a if a.confianza >= b.confianza else b

    return Deteccion(
        sku_codigo=a.sku_codigo,
        confianza=round(confianza, 3),
        # Si difieren de nivel, manda la lectura más segura.
        nivel=mejor.nivel,
        # Los frentes se promedian: contar unidades iguales en fila es
        # justo lo que un modelo de visión hace peor, y el promedio de dos
        # intentos se acerca más que cualquiera de los dos por separado.
        frentes=max(1, round((a.frentes + b.frentes) / 2)),
        bbox=mejor.bbox,
        # Frenteado: basta que una lo vea desordenado para revisarlo.
        frenteado=a.frenteado and b.frenteado,
    )


# =====================================================================
# Etiquetas
# =====================================================================


def _fusionar_etiquetas(
    a: list[Etiqueta], b: list[Etiqueta], acuerdo: Acuerdo
) -> list[Etiqueta]:
    """Fusiona las etiquetas de precio, descartando los precios en disputa."""
    por_sku_a = {e.sku_asociado: e for e in a if e.sku_asociado}
    por_sku_b = {e.sku_asociado: e for e in b if e.sku_asociado}
    sueltas = [e for e in a + b if not e.sku_asociado]

    resultado: list[Etiqueta] = []

    for codigo in sorted(set(por_sku_a) | set(por_sku_b)):
        et_a, et_b = por_sku_a.get(codigo), por_sku_b.get(codigo)

        if et_a is None or et_b is None:
            # Solo una lectura vio la etiqueta. Se conserva: si la otra no
            # la vio puede ser recorte o reflejo, no ausencia. Pero baja
            # la confianza para que quede trazado.
            unica = et_a or et_b
            resultado.append(unica.model_copy(update={"confianza": round(unica.confianza * 0.8, 3)}))
            continue

        precio_a, precio_b = et_a.precio_leido, et_b.precio_leido
        legible = et_a.legible and et_b.legible
        precio: Optional[float] = None

        if precio_a is not None and precio_b is not None:
            if abs(precio_a - precio_b) <= TOLERANCIA_PRECIO:
                precio = precio_a
            else:
                # Las dos lecturas leyeron números distintos en la misma
                # etiqueta. No hay forma de saber cuál es: se descarta y la
                # etiqueta pasa a ilegible. Es preferible reportar
                # "etiqueta ilegible" antes que acusar a la sala de tener
                # un precio mal por un dígito mal leído.
                legible = False
                acuerdo.precios_descartados.append(
                    f"{codigo} ({precio_a} vs {precio_b})"
                )
        else:
            # Solo una leyó el precio: se conserva, con menos confianza.
            precio = precio_a if precio_a is not None else precio_b

        base = et_a if et_a.confianza >= et_b.confianza else et_b
        resultado.append(base.model_copy(update={
            "precio_leido": precio,
            "legible": legible,
            "confianza": round(min(1.0, (et_a.confianza + et_b.confianza) / 2 + BONUS_ACUERDO), 3),
            "es_promocion": et_a.es_promocion or et_b.es_promocion,
        }))

    # Las etiquetas sin SKU asociado no afectan la auditoría de precios de
    # nuestros productos, pero se conservan como evidencia del riel.
    vistas: set[tuple] = set()
    for e in sueltas:
        firma = (e.nivel, e.precio_leido, (e.texto_producto or "").lower())
        if firma not in vistas:
            vistas.add(firma)
            resultado.append(e)

    return resultado


# =====================================================================
# Huecos
# =====================================================================


def _fusionar_huecos(a: list[Hueco], b: list[Hueco], acuerdo: Acuerdo) -> list[Hueco]:
    """Solo se conservan los huecos que ambas lecturas vieron.

    Un hueco dispara un hallazgo de quiebre, que manda a alguien a la sala.
    Con una sola lectura no alcanza.
    """
    confirmados: list[Hueco] = []
    libres_b = list(b)

    for hueco_a in a:
        pareja = None
        for hueco_b in libres_b:
            if abs(hueco_b.nivel - hueco_a.nivel) <= MAX_DISTANCIA_NIVEL:
                pareja = hueco_b
                break
        if pareja is None:
            continue
        libres_b.remove(pareja)
        confirmados.append(Hueco(
            nivel=hueco_a.nivel,
            bbox=hueco_a.bbox,
            # Conservador: el menor de los dos anchos.
            ancho_frentes_aprox=min(hueco_a.ancho_frentes_aprox, pareja.ancho_frentes_aprox),
            sku_codigo_sugerido=hueco_a.sku_codigo_sugerido or pareja.sku_codigo_sugerido,
        ))

    acuerdo.huecos_descartados = (len(a) - len(confirmados)) + len(libres_b)
    return confirmados


# =====================================================================
# Fusión completa
# =====================================================================


def _promedio_del_lineal(a: Observacion, b: Observacion) -> int:
    """Promedia el conteo del lineal ignorando la lectura que no contó.

    Un 0 no es "la góndola está vacía": es que esa lectura no llegó a
    contar. Meterlo al promedio parte el denominador del share of shelf a
    la mitad, y el share sale al doble de lo real.
    """
    valores = [v for v in (a.frentes_totales_lineal, b.frentes_totales_lineal) if v > 0]
    if not valores:
        return 0
    return round(sum(valores) / len(valores))


def fusionar(
    a: Observacion, b: Observacion, marcas: Optional[dict[str, str]] = None
) -> tuple[Observacion, Acuerdo]:
    """Combina dos lecturas de la misma foto en una sola observación.

    La confianza global resultante no es el promedio de las dos: es el
    promedio corregido por cuánto coincidieron. Dos lecturas seguras que se
    contradicen dan una confianza baja, que es lo correcto.
    """
    acuerdo = Acuerdo()

    parejas, disputas, huerfanas = _emparejar_detecciones(
        a.detecciones, b.detecciones, marcas or {}
    )

    detecciones = [_fusionar_pareja(x, y) for x, y in parejas]
    acuerdo.skus_en_ambas = sorted({d.sku_codigo for d in detecciones})

    # Presencia confirmada por las dos lecturas, variante en disputa: gana
    # la más segura, sin el castigo que se reserva para lo que vio una sola.
    for x, y in disputas:
        gana, pierde = (x, y) if x.confianza >= y.confianza else (y, x)
        detecciones.append(gana.model_copy(update={
            "confianza": round((x.confianza + y.confianza) / 2, 3),
        }))
        acuerdo.variantes_en_disputa.append(f"{gana.sku_codigo} vs {pierde.sku_codigo}")

    for suelta in huerfanas:
        detecciones.append(suelta.model_copy(update={
            "confianza": round(suelta.confianza * PENALIZACION_SIN_ACUERDO, 3),
        }))
    acuerdo.skus_en_una = sorted(
        {d.sku_codigo for d in huerfanas} - set(acuerdo.skus_en_ambas)
    )

    etiquetas = _fusionar_etiquetas(a.etiquetas, b.etiquetas, acuerdo)
    huecos = _fusionar_huecos(a.huecos, b.huecos, acuerdo)

    acuerdo.niveles_discrepan = a.niveles_visibles != b.niveles_visibles

    # Manda la lectura que se declaró más segura para lo estructural.
    dominante = a if a.confianza_global >= b.confianza_global else b
    calidades = ("mala", "regular", "buena")
    peor_calidad = min(a.calidad_foto, b.calidad_foto, key=calidades.index)

    confianza = round(
        ((a.confianza_global + b.confianza_global) / 2) * (0.5 + 0.5 * acuerdo.indice), 3
    )

    fusionada = Observacion(
        niveles_visibles=dominante.niveles_visibles,
        nivel_ojos=dominante.nivel_ojos,
        # Si una lectura dice que el mueble sale cortado, no se evalúa la
        # altura. Es la opción que no castiga al reponedor.
        mueble_completo_visible=a.mueble_completo_visible and b.mueble_completo_visible,
        calidad_foto=peor_calidad,
        motivo_calidad=a.motivo_calidad or b.motivo_calidad,
        # 0 significa "esta lectura no contó el lineal", no "el lineal está
        # vacío". Promediarlo con una lectura buena partiría el denominador
        # del share of shelf a la mitad e inflaría el share al doble.
        frentes_totales_lineal=_promedio_del_lineal(a, b),
        frentes_por_nivel=(
            a.frentes_por_nivel if a.frentes_totales_lineal else b.frentes_por_nivel
        ),
        detecciones=detecciones,
        huecos=huecos,
        etiquetas=etiquetas,
        confianza_global=min(1.0, max(0.0, confianza)),
    )

    log.info("Consenso de dos lecturas: %s", acuerdo.resumen())
    return fusionada, acuerdo
