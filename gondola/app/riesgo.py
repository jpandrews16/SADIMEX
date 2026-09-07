"""Cuándo vale la pena leer una foto dos veces.

El criterio obvio sería "cuando el modelo dice que no está seguro". No
sirve: en la primera prueba real, Qwen se declaró 95% seguro **y** reportó
dos huecos que no existían. La autoevaluación de un modelo no es una
medida de su acierto.

El criterio que sí sirve: **verificar cuando equivocarse sale caro.**

Hay tres hallazgos que, si son falsos, hacen daño de verdad:

  1. Un hueco → manda a un supervisor a una sala donde no había problema.
  2. Un precio fuera de rango → acusa a la sala de algo que no hizo.
  3. Un SKU prioritario ausente → dispara una reposición de urgencia
     innecesaria, o peor, esconde que sí estaba.

Los tres tienen algo en común: **cuestan trabajo humano y credibilidad**,
que valen mucho más que la décima de centavo de una segunda lectura. Una
foto limpia, sin ninguno de estos, se queda con una sola lectura.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .schemas import Observacion, Precio, Sku


def _skus_detectados(obs: Observacion, umbral: float) -> set[str]:
    return {d.sku_codigo for d in obs.detecciones if d.confianza >= umbral}


def motivos_para_verificar(
    obs: Observacion,
    skus: Sequence[Sku],
    precios: Mapping[str, Precio] | None = None,
    umbral_confianza: float = 0.75,
    umbral_deteccion: float = 0.60,
) -> list[str]:
    """Razones por las que conviene una segunda lectura. Vacío = no hace falta.

    Devuelve texto legible porque termina en el registro del análisis: si
    alguien pregunta meses después por qué esa foto costó el doble, la
    respuesta está escrita.
    """
    precios = precios or {}
    motivos: list[str] = []

    # ── Hallazgos caros si resultan falsos ───────────────────────────
    if obs.huecos:
        frentes = sum(h.ancho_frentes_aprox for h in obs.huecos)
        motivos.append(f"reporta {len(obs.huecos)} hueco(s) (~{frentes} frentes vacíos)")

    detectados = _skus_detectados(obs, umbral_deteccion)
    prioritarios_ausentes = sorted(
        s.codigo for s in skus if s.es_prioritario and s.codigo not in detectados
    )
    if prioritarios_ausentes:
        muestra = ", ".join(prioritarios_ausentes[:3])
        resto = f" y {len(prioritarios_ausentes) - 3} más" if len(prioritarios_ausentes) > 3 else ""
        motivos.append(f"SKU prioritario sin detectar: {muestra}{resto}")

    fuera_de_rango = []
    for etiqueta in obs.etiquetas:
        codigo = etiqueta.sku_asociado
        if not codigo or etiqueta.precio_leido is None:
            continue
        precio = precios.get(codigo)
        if precio is None or precio.pvp <= 0:
            continue
        desvio = abs(etiqueta.precio_leido - precio.pvp) / precio.pvp * 100
        if desvio > precio.tolerancia_pct:
            fuera_de_rango.append(f"{codigo} ({etiqueta.precio_leido} vs {precio.pvp})")
    if fuera_de_rango:
        motivos.append("precio fuera de rango en " + ", ".join(fuera_de_rango[:3]))

    # ── Señales de que la lectura misma es floja ─────────────────────
    if obs.calidad_foto == "mala":
        motivos.append(f"foto de mala calidad ({obs.motivo_calidad or 'sin motivo'})")
    if obs.confianza_global < umbral_confianza:
        motivos.append(f"confianza {obs.confianza_global:.0%} bajo el umbral")

    return motivos
