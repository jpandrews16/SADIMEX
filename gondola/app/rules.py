"""Motor determinístico de las 6 reglas de ejecución en góndola.

Este módulo no habla con ningún modelo de IA. Recibe una `Observacion`
(lo que la visión vio) y devuelve una `Evaluacion` (el veredicto).

Por qué importa que sea así:

  * El score es reproducible. La misma foto da siempre el mismo número.
  * Se puede recalcular sobre el histórico cuando cambian las reglas o
    los pesos, sin pagar de nuevo la llamada de visión.
  * Es defendible frente a un reponedor que reclama su nota: cada punto
    sale de una regla escrita, no de la opinión de un modelo.

Las 6 reglas:
  R1 presencia   — el SKU obligatorio está en la góndola
  R2 nivel       — está a la altura objetivo (ojos / manos)
  R3 frentes     — cumple frentes mínimos y share of shelf
  R4 bloque      — los SKUs de la marca van contiguos, no dispersos
  R5 etiqueta    — etiqueta presente, legible y con el precio correcto
  R6 sin_quiebre — sin huecos en nuestro espacio y producto frenteado

Una regla que no se puede evaluar con la foto disponible se marca como
NO APLICABLE y se saca del denominador del score. Nunca se castiga a un
reponedor por algo que la foto no permite ver.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from .config import get_settings
from .schemas import (
    Deteccion,
    Etiqueta,
    Evaluacion,
    Hallazgo,
    Observacion,
    Precio,
    Regla,
    ResultadoRegla,
    Semaforo,
    Sku,
)

PESOS_POR_DEFECTO: dict[str, float] = {
    "presencia": 0.30,
    "nivel": 0.20,
    "frentes": 0.20,
    "bloque": 0.10,
    "etiqueta": 0.15,
    "sin_quiebre": 0.05,
}

# Un hueco horizontal mayor a este múltiplo del ancho promedio de un
# frente se considera que rompe el bloque de marca.
FACTOR_RUPTURA_BLOQUE = 1.6


# =====================================================================
# Alturas de góndola
# =====================================================================


def nivel_de_ojos(niveles_visibles: int, reportado: Optional[int] = None) -> int:
    """Nivel que queda a la altura de los ojos de un adulto.

    Se prefiere lo que reporta el modelo, que ve el mueble. El cálculo es
    el respaldo: en una góndola de 4-5 bandejas la altura de ojos es la
    penúltima contando desde el piso.
    """
    if reportado and 1 <= reportado <= niveles_visibles:
        return reportado
    if niveles_visibles >= 3:
        return niveles_visibles - 1
    return niveles_visibles


def nivel_de_manos(niveles_visibles: int, nivel_ojos: int) -> int:
    return max(1, nivel_ojos - 1)


def _zona_cumple(nivel: int, objetivo: str, n_ojos: int, n_manos: int) -> bool:
    if objetivo == "cualquiera":
        return True
    if objetivo == "ojos":
        return nivel == n_ojos
    if objetivo == "manos":
        return nivel == n_manos
    if objetivo == "ojos_o_manos":
        return nivel in (n_ojos, n_manos)
    if objetivo == "superior":
        return nivel > n_ojos
    if objetivo == "inferior":
        return nivel < n_manos
    return True


def _nombre_zona(nivel: int, n_ojos: int, n_manos: int) -> str:
    if nivel > n_ojos:
        return "superior"
    if nivel == n_ojos:
        return "ojos"
    if nivel == n_manos:
        return "manos"
    return "inferior"


# =====================================================================
# Reglas
# =====================================================================


def _detecciones_validas(obs: Observacion, umbral: float) -> list[Deteccion]:
    """Detecciones cuya confianza alcanza para afirmar que el producto está."""
    return [d for d in obs.detecciones if d.confianza >= umbral]


def _por_sku(detecciones: Iterable[Deteccion]) -> dict[str, list[Deteccion]]:
    agrupado: dict[str, list[Deteccion]] = defaultdict(list)
    for d in detecciones:
        agrupado[d.sku_codigo].append(d)
    return dict(agrupado)


def detecciones_por_sku(obs: Observacion, umbral: float) -> dict[str, list[Deteccion]]:
    """Detecciones creíbles agrupadas por código de SKU."""
    return _por_sku(_detecciones_validas(obs, umbral))


def evaluar_presencia(
    skus: list[Sku], reglas: dict[str, Regla], detectados: dict[str, list[Deteccion]]
) -> tuple[Optional[ResultadoRegla], list[str], list[str]]:
    obligatorios = [s for s in skus if reglas[s.codigo].exige_presencia]
    if not obligatorios:
        return None, [], []

    presentes = [s.codigo for s in obligatorios if s.codigo in detectados]
    ausentes = [s.codigo for s in obligatorios if s.codigo not in detectados]
    cumplimiento = len(presentes) / len(obligatorios)

    return (
        ResultadoRegla(
            regla="presencia",
            cumple=not ausentes,
            cumplimiento=cumplimiento,
            esperado=f"{len(obligatorios)} SKU obligatorios en góndola",
            obtenido=f"{len(presentes)} presentes, {len(ausentes)} ausentes",
            detalle=("Faltan: " + ", ".join(ausentes)) if ausentes else "Portafolio completo.",
        ),
        presentes,
        ausentes,
    )


def evaluar_nivel(
    obs: Observacion, reglas: dict[str, Regla], detectados: dict[str, list[Deteccion]]
) -> Optional[ResultadoRegla]:
    # Sin el mueble completo en la foto no se puede afirmar a qué altura
    # está nada. Preferimos no evaluar antes que inventar.
    if not obs.mueble_completo_visible:
        return None

    evaluables = {
        codigo: dets
        for codigo, dets in detectados.items()
        if codigo in reglas and reglas[codigo].nivel_objetivo != "cualquiera"
    }
    if not evaluables:
        return None

    n_ojos = nivel_de_ojos(obs.niveles_visibles, obs.nivel_ojos)
    n_manos = nivel_de_manos(obs.niveles_visibles, n_ojos)

    cumplen, fuera = [], []
    for codigo, dets in evaluables.items():
        objetivo = reglas[codigo].nivel_objetivo
        # Basta con que el SKU tenga presencia en la zona objetivo.
        if any(_zona_cumple(d.nivel, objetivo, n_ojos, n_manos) for d in dets):
            cumplen.append(codigo)
        else:
            zona_real = _nombre_zona(dets[0].nivel, n_ojos, n_manos)
            fuera.append(f"{codigo} (está en {zona_real}, debía estar en {objetivo})")

    cumplimiento = len(cumplen) / len(evaluables)
    return ResultadoRegla(
        regla="nivel",
        cumple=not fuera,
        cumplimiento=cumplimiento,
        esperado=f"{len(evaluables)} SKU en su altura objetivo",
        obtenido=f"{len(cumplen)} en zona correcta",
        detalle=("; ".join(fuera)) if fuera else f"Altura de ojos = nivel {n_ojos}.",
    )


def evaluar_frentes(
    obs: Observacion,
    reglas: dict[str, Regla],
    detectados: dict[str, list[Deteccion]],
) -> tuple[Optional[ResultadoRegla], Optional[float]]:
    frentes_nuestros = sum(d.frentes for dets in detectados.values() for d in dets)
    share = None
    if obs.frentes_totales_lineal > 0:
        share = round(100 * frentes_nuestros / obs.frentes_totales_lineal, 2)

    evaluables = {c: d for c, d in detectados.items() if c in reglas and reglas[c].frentes_minimos > 0}
    if not evaluables and share is None:
        return None, share

    faltantes: list[str] = []
    puntajes: list[float] = []
    for codigo, dets in evaluables.items():
        minimo = reglas[codigo].frentes_minimos
        obtenidos = sum(d.frentes for d in dets)
        puntajes.append(min(1.0, obtenidos / minimo))
        if obtenidos < minimo:
            faltantes.append(f"{codigo} ({obtenidos}/{minimo} frentes)")

    # El share exigido es el más alto entre las reglas que lo declaran.
    share_exigido = max(
        (r.share_minimo_pct for r in reglas.values() if r.share_minimo_pct is not None),
        default=None,
    )

    # El share of shelf se informa, pero NO puntúa mientras el conteo del
    # lineal no sea confiable.
    #
    # Medido contra SKU-110K —11.762 fotos de góndola con 1,73 millones de
    # productos marcados a mano—, el conteo del lineal por bandejas queda
    # en 10,5% de error mediano y sin sesgo. Eso alcanza para una
    # tendencia, no para una foto suelta: el error de una foto puntual se
    # va al 20%, y de una foto puntual cuelga el bono de un reponedor.
    #
    # El numerador (nuestros frentes) es fácil: son pocas unidades de
    # productos que el modelo tiene en la hoja de referencia. El
    # denominador es contar cien envases ajenos, que es lo que peor hace.
    #
    # Así que el share entra al informe como dato y se queda fuera de la
    # nota hasta medirlo sobre fotos de nuestras salas. Se activa con
    # SHARE_OF_SHELF_PUNTUA=true.
    share_puntua = get_settings().share_of_shelf_puntua
    if share_puntua and share_exigido is not None and share is not None:
        puntajes.append(min(1.0, share / share_exigido) if share_exigido > 0 else 1.0)

    if not puntajes:
        return None, share

    cumplimiento = sum(puntajes) / len(puntajes)
    if share is None:
        detalle_share = ""
    elif share_puntua:
        detalle_share = f" Share of shelf: {share}%."
    else:
        detalle_share = f" Share of shelf: {share}% (referencial, no puntúa)."
    if share_exigido is not None and share_puntua:
        detalle_share += f" Mínimo exigido: {share_exigido}%."

    incumple_share = (
        share_puntua and share_exigido is not None and share is not None and share < share_exigido
    )
    exigido = "Frentes mínimos por SKU"
    if share_exigido is not None and share_puntua:
        exigido += f" y {share_exigido}% de share"

    return (
        ResultadoRegla(
            regla="frentes",
            cumple=not faltantes and not incumple_share,
            cumplimiento=cumplimiento,
            esperado=exigido,
            obtenido=f"{frentes_nuestros} frentes propios de {obs.frentes_totales_lineal or '?'} del lineal",
            detalle=(("Bajo el mínimo: " + ", ".join(faltantes)) if faltantes else "Frentes en regla.")
            + detalle_share,
        ),
        share,
    )


def evaluar_bloque(
    skus: list[Sku], reglas: dict[str, Regla], detectados: dict[str, list[Deteccion]]
) -> Optional[ResultadoRegla]:
    """Mide si cada marca está en un bloque compacto o dispersa por el lineal.

    Se cuenta cuántos grupos horizontales separados forma la marca dentro
    de cada nivel. Un bloque perfecto = 1 grupo. Dos grupos = la marca
    está partida y pierde impacto visual.
    """
    marca_por_codigo = {s.codigo: s.marca for s in skus}
    marcas_exigidas = {
        marca_por_codigo[c] for c in detectados if c in reglas and reglas[c].exige_bloque and c in marca_por_codigo
    }
    if not marcas_exigidas:
        return None

    todas = [d for dets in detectados.values() for d in dets]
    anchos = [d.bbox.ancho / max(1, d.frentes) for d in todas if d.bbox.ancho > 0]
    ancho_frente = (sum(anchos) / len(anchos)) if anchos else 0.0

    puntajes: list[float] = []
    dispersas: list[str] = []

    for marca in sorted(marcas_exigidas):
        dets = [
            d
            for codigo, lista in detectados.items()
            if marca_por_codigo.get(codigo) == marca
            for d in lista
        ]
        grupos_marca = 0
        for _nivel, del_nivel in _agrupar_por_nivel(dets).items():
            grupos_marca += _contar_grupos(del_nivel, ancho_frente)
        # Estar en varios niveles es normal y deseable; lo que penaliza es
        # estar partido dentro de un mismo nivel.
        niveles_ocupados = len(_agrupar_por_nivel(dets))
        grupos_extra = max(0, grupos_marca - niveles_ocupados)
        puntaje = 1.0 / (1 + grupos_extra)
        puntajes.append(puntaje)
        if grupos_extra:
            dispersas.append(f"{marca} partida en {grupos_marca} bloques")

    cumplimiento = sum(puntajes) / len(puntajes)
    return ResultadoRegla(
        regla="bloque",
        cumple=not dispersas,
        cumplimiento=cumplimiento,
        esperado="Cada marca en un bloque contiguo por nivel",
        obtenido=f"{len(marcas_exigidas) - len(dispersas)}/{len(marcas_exigidas)} marcas bloqueadas",
        detalle=("; ".join(dispersas)) if dispersas else "Bloques de marca compactos.",
    )


def _agrupar_por_nivel(dets: Iterable[Deteccion]) -> dict[int, list[Deteccion]]:
    por_nivel: dict[int, list[Deteccion]] = defaultdict(list)
    for d in dets:
        por_nivel[d.nivel].append(d)
    return dict(por_nivel)


def _contar_grupos(dets: list[Deteccion], ancho_frente: float) -> int:
    """Grupos horizontales separados dentro de un mismo nivel."""
    if not dets:
        return 0
    if ancho_frente <= 0:
        return 1
    ordenados = sorted(dets, key=lambda d: d.bbox.x0)
    grupos = 1
    borde_derecho = ordenados[0].bbox.x1
    for d in ordenados[1:]:
        if d.bbox.x0 - borde_derecho > ancho_frente * FACTOR_RUPTURA_BLOQUE:
            grupos += 1
        borde_derecho = max(borde_derecho, d.bbox.x1)
    return grupos


def evaluar_etiquetas(
    obs: Observacion,
    skus: list[Sku],
    reglas: dict[str, Regla],
    detectados: dict[str, list[Deteccion]],
    precios: dict[str, Precio],
) -> tuple[Optional[ResultadoRegla], list[dict]]:
    """Audita la etiqueta de precio de cada SKU presente.

    Devuelve también el detalle por etiqueta, que es lo que el supervisor
    necesita ver para mandar a corregir el riel.
    """
    evaluables = [c for c in detectados if c in reglas and reglas[c].exige_etiqueta]
    if not evaluables:
        return None, []

    sku_por_codigo = {s.codigo: s for s in skus}
    por_sku: dict[str, Etiqueta] = {}
    for e in obs.etiquetas:
        if e.sku_asociado and e.sku_asociado not in por_sku:
            por_sku[e.sku_asociado] = e

    puntajes: list[float] = []
    detalle_etiquetas: list[dict] = []
    problemas: list[str] = []

    for codigo in sorted(evaluables):
        nombre = sku_por_codigo[codigo].nombre if codigo in sku_por_codigo else codigo
        etiqueta = por_sku.get(codigo)
        precio = precios.get(codigo)

        if etiqueta is None:
            puntajes.append(0.0)
            problemas.append(f"{codigo}: sin etiqueta de precio")
            detalle_etiquetas.append(
                {"sku_codigo": codigo, "sku_nombre": nombre, "estado": "ausente",
                 "precio_leido": None, "pvp": precio.pvp if precio else None}
            )
            continue

        if not etiqueta.legible:
            puntajes.append(0.4)
            problemas.append(f"{codigo}: etiqueta ilegible")
            detalle_etiquetas.append(
                {"sku_codigo": codigo, "sku_nombre": nombre, "estado": "ilegible",
                 "precio_leido": None, "pvp": precio.pvp if precio else None}
            )
            continue

        if etiqueta.precio_leido is None:
            puntajes.append(0.5)
            problemas.append(f"{codigo}: etiqueta sin precio visible")
            detalle_etiquetas.append(
                {"sku_codigo": codigo, "sku_nombre": nombre, "estado": "sin_precio",
                 "precio_leido": None, "pvp": precio.pvp if precio else None}
            )
            continue

        if precio is None:
            # Sin PVP cargado no podemos juzgar el monto. Se registra el
            # precio observado y se da por buena la etiqueta: el vacío es
            # nuestro, no del reponedor.
            puntajes.append(0.9)
            detalle_etiquetas.append(
                {"sku_codigo": codigo, "sku_nombre": nombre, "estado": "sin_pvp_referencia",
                 "precio_leido": etiqueta.precio_leido, "pvp": None}
            )
            continue

        desvio_pct = abs(etiqueta.precio_leido - precio.pvp) / precio.pvp * 100
        if desvio_pct <= precio.tolerancia_pct:
            puntajes.append(1.0)
            detalle_etiquetas.append(
                {"sku_codigo": codigo, "sku_nombre": nombre, "estado": "correcta",
                 "precio_leido": etiqueta.precio_leido, "pvp": precio.pvp,
                 "desvio_pct": round(desvio_pct, 2)}
            )
        else:
            puntajes.append(0.3)
            direccion = "sobre" if etiqueta.precio_leido > precio.pvp else "bajo"
            problemas.append(
                f"{codigo}: {etiqueta.precio_leido} {precio.moneda} vs PVP {precio.pvp} "
                f"({desvio_pct:.1f}% {direccion})"
            )
            detalle_etiquetas.append(
                {"sku_codigo": codigo, "sku_nombre": nombre, "estado": "precio_incorrecto",
                 "precio_leido": etiqueta.precio_leido, "pvp": precio.pvp,
                 "desvio_pct": round(desvio_pct, 2)}
            )

    cumplimiento = sum(puntajes) / len(puntajes)
    return (
        ResultadoRegla(
            regla="etiqueta",
            cumple=not problemas,
            cumplimiento=cumplimiento,
            esperado=f"{len(evaluables)} etiquetas presentes, legibles y al PVP",
            obtenido=f"{sum(1 for p in puntajes if p >= 1.0)}/{len(evaluables)} correctas",
            detalle=("; ".join(problemas)) if problemas else "Etiquetas en regla.",
        ),
        detalle_etiquetas,
    )


def evaluar_sin_quiebre(
    obs: Observacion, reglas: dict[str, Regla], detectados: dict[str, list[Deteccion]]
) -> tuple[Optional[ResultadoRegla], int]:
    if not any(r.exige_sin_quiebre for r in reglas.values()):
        return None, len(obs.huecos)

    frentes_nuestros = sum(d.frentes for dets in detectados.values() for d in dets)
    frentes_vacios = sum(h.ancho_frentes_aprox for h in obs.huecos)
    base = frentes_nuestros + frentes_vacios

    puntaje_huecos = 1.0 if base == 0 else 1.0 - (frentes_vacios / base)

    todas = [d for dets in detectados.values() for d in dets]
    puntaje_frenteo = (sum(1 for d in todas if d.frenteado) / len(todas)) if todas else 1.0

    cumplimiento = 0.7 * puntaje_huecos + 0.3 * puntaje_frenteo
    desordenados = [d.sku_codigo for d in todas if not d.frenteado]

    problemas = []
    if obs.huecos:
        problemas.append(f"{len(obs.huecos)} hueco(s), ~{frentes_vacios} frentes vacíos")
    if desordenados:
        problemas.append("sin frentear: " + ", ".join(sorted(set(desordenados))))

    return (
        ResultadoRegla(
            regla="sin_quiebre",
            cumple=not problemas,
            cumplimiento=cumplimiento,
            esperado="Góndola llena y producto frenteado",
            obtenido=f"{len(obs.huecos)} huecos, {len(desordenados)} SKU sin frentear",
            detalle=("; ".join(problemas)) if problemas else "Góndola sana.",
        ),
        len(obs.huecos),
    )


# =====================================================================
# Orquestación
# =====================================================================


def semaforo_de(score: int, umbral_verde: int, umbral_amarillo: int) -> Semaforo:
    if score >= umbral_verde:
        return "verde"
    if score >= umbral_amarillo:
        return "amarillo"
    return "rojo"


def evaluar(
    obs: Observacion,
    skus: list[Sku],
    reglas: dict[str, Regla],
    precios: Optional[dict[str, Precio]] = None,
    pesos: Optional[dict[str, float]] = None,
    umbral_deteccion: float = 0.60,
    umbral_verde: int = 80,
    umbral_amarillo: int = 60,
) -> Evaluacion:
    """Convierte lo observado en un veredicto con score y hallazgos.

    `reglas` viene indexado por código de SKU y ya resuelto (la jerarquía
    cadena > marca > categoría se aplica en `catalog.py`).
    """
    precios = precios or {}
    pesos = pesos or PESOS_POR_DEFECTO

    detectados = _por_sku(_detecciones_validas(obs, umbral_deteccion))
    # Un SKU sin regla propia no debería llegar acá, pero si llega no puede
    # tumbar la evaluación entera.
    reglas = {**{s.codigo: Regla() for s in skus}, **reglas}

    resultados: dict[str, ResultadoRegla] = {}

    r_presencia, presentes, ausentes = evaluar_presencia(skus, reglas, detectados)
    if r_presencia:
        resultados["presencia"] = r_presencia

    if (r := evaluar_nivel(obs, reglas, detectados)) is not None:
        resultados["nivel"] = r

    r_frentes, share = evaluar_frentes(obs, reglas, detectados)
    if r_frentes:
        resultados["frentes"] = r_frentes

    if (r := evaluar_bloque(skus, reglas, detectados)) is not None:
        resultados["bloque"] = r

    r_etiqueta, detalle_etiquetas = evaluar_etiquetas(obs, skus, reglas, detectados, precios)
    if r_etiqueta:
        resultados["etiqueta"] = r_etiqueta

    r_quiebre, quiebres = evaluar_sin_quiebre(obs, reglas, detectados)
    if r_quiebre:
        resultados["sin_quiebre"] = r_quiebre

    # Score: promedio ponderado solo sobre las reglas que sí se pudieron
    # evaluar. Las no aplicables salen del denominador.
    peso_total = sum(pesos.get(nombre, 0.0) for nombre in resultados)
    if peso_total > 0:
        score = round(
            100 * sum(pesos.get(n, 0.0) * r.cumplimiento for n, r in resultados.items()) / peso_total
        )
    else:
        score = 0

    evaluacion = Evaluacion(
        score=int(score),
        semaforo=semaforo_de(int(score), umbral_verde, umbral_amarillo),
        reglas=resultados,
        share_of_shelf_pct=share,
        quiebres_detectados=quiebres,
        skus_presentes=sorted(presentes),
        skus_ausentes=sorted(ausentes),
    )
    evaluacion.hallazgos = construir_hallazgos(obs, skus, evaluacion, detalle_etiquetas, resultados)
    return evaluacion


def construir_hallazgos(
    obs: Observacion,
    skus: list[Sku],
    evaluacion: Evaluacion,
    detalle_etiquetas: list[dict],
    resultados: dict[str, ResultadoRegla],
) -> list[Hallazgo]:
    """Traduce el veredicto a tareas concretas para el supervisor."""
    nombre_de = {s.codigo: s.nombre for s in skus}
    prioritario = {s.codigo: s.es_prioritario for s in skus}
    hallazgos: list[Hallazgo] = []

    for codigo in evaluacion.skus_ausentes:
        hallazgos.append(
            Hallazgo(
                severidad="critico" if prioritario.get(codigo) else "alto",
                regla="presencia",
                sku_codigo=codigo,
                mensaje=f"{nombre_de.get(codigo, codigo)} no está en góndola.",
                accion="Reponer desde bodega de sala o levantar pedido de urgencia.",
            )
        )

    if (r := resultados.get("nivel")) and not r.cumple:
        hallazgos.append(
            Hallazgo(
                severidad="alto",
                regla="nivel",
                mensaje=f"Producto fuera de su altura objetivo. {r.detalle}",
                accion="Reubicar a la altura acordada con la sala.",
            )
        )

    if (r := resultados.get("frentes")) and not r.cumple:
        hallazgos.append(
            Hallazgo(
                severidad="medio",
                regla="frentes",
                mensaje=f"Espacio por debajo de lo negociado. {r.detalle}",
                accion="Ampliar frentes hasta el mínimo y avisar al jefe de sala.",
            )
        )

    if (r := resultados.get("bloque")) and not r.cumple:
        hallazgos.append(
            Hallazgo(
                severidad="medio",
                regla="bloque",
                mensaje=f"Marca dispersa en el lineal. {r.detalle}",
                accion="Juntar los SKU de la marca en un bloque continuo.",
            )
        )

    for e in detalle_etiquetas:
        estado = e["estado"]
        if estado == "correcta" or estado == "sin_pvp_referencia":
            continue
        severidad, mensaje, accion = {
            "ausente": (
                "alto",
                f"Falta etiqueta de precio de {e['sku_nombre']}.",
                "Solicitar impresión de la etiqueta al jefe de sala.",
            ),
            "ilegible": (
                "medio",
                f"Etiqueta de {e['sku_nombre']} ilegible o dañada.",
                "Reemplazar la etiqueta.",
            ),
            "sin_precio": (
                "medio",
                f"La etiqueta de {e['sku_nombre']} no muestra precio.",
                "Reimprimir la etiqueta con el precio vigente.",
            ),
            "precio_incorrecto": (
                "critico",
                f"{e['sku_nombre']} exhibido a {e['precio_leido']} contra PVP {e['pvp']} "
                f"({e.get('desvio_pct')}% de desvío).",
                "Corregir el precio en caja y en el riel el mismo día.",
            ),
        }[estado]
        hallazgos.append(
            Hallazgo(severidad=severidad, regla="etiqueta", sku_codigo=e["sku_codigo"],
                     mensaje=mensaje, accion=accion)
        )

    if (r := resultados.get("sin_quiebre")) and not r.cumple:
        hallazgos.append(
            Hallazgo(
                severidad="alto" if obs.huecos else "bajo",
                regla="sin_quiebre",
                mensaje=r.detalle,
                accion="Rellenar los espacios vacíos y frentear el producto.",
            )
        )

    # La calidad de la foto no es culpa de la góndola, pero sí condiciona
    # cuánto de esto se puede creer. Se avisa siempre.
    if obs.calidad_foto == "mala":
        hallazgos.append(
            Hallazgo(
                severidad="alto",
                regla="presencia",
                mensaje=f"Foto de mala calidad: {obs.motivo_calidad or 'no especificado'}. "
                        "El análisis puede ser incompleto.",
                accion="Pedir al reponedor que repita la foto de frente y con el mueble completo.",
            )
        )
    elif not obs.mueble_completo_visible:
        hallazgos.append(
            Hallazgo(
                severidad="medio",
                regla="nivel",
                mensaje="El mueble no se ve completo, no se pudo evaluar la altura.",
                accion="Repetir la foto incluyendo desde el piso hasta la bandeja superior.",
            )
        )

    orden = {"critico": 0, "alto": 1, "medio": 2, "bajo": 3}
    hallazgos.sort(key=lambda h: orden[h.severidad])
    return hallazgos
