"""Cliente de visión sobre OpenRouter.

Estrategia por defecto (`consenso`), pensada para volumen alto:

  1. Toda foto pasa una vez por el modelo primario (barato).
  2. Si esa lectura no es confiable, se pide una **segunda lectura al
     mismo modelo barato**, con un método de conteo distinto, y se
     fusionan (ver `consenso.py`).
  3. Solo si las dos lecturas se contradicen de verdad se paga el modelo
     grande, sujeto a la cuota diaria.

Por qué así y no escalando directo al modelo grande:

  * Sale más barato. Dos llamadas al modelo chico cuestan menos que una
    al grande, sobre todo en tokens de salida (0.416 vs 1.90 por millón
    en Qwen3-VL 32B contra 235B).
  * El acuerdo entre dos lecturas independientes es mejor evidencia que
    la autoevaluación del modelo: un modelo puede estar seguro y
    equivocado, pero es raro que se equivoque igual dos veces con
    métodos distintos.
  * Donde no coinciden, sabemos exactamente qué no hay que creer. Eso es
    lo que ninguna lectura única puede darte.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

import httpx
from pydantic import ValidationError

from .config import get_settings
from .consenso import fusionar
from .prompt import RESPONSE_FORMAT, construir_mensajes, construir_mensajes_verificacion
from .riesgo import motivos_para_verificar
from .schemas import Observacion, Precio, Sku, UsoModelo

log = logging.getLogger(__name__)


class VisionError(RuntimeError):
    """El modelo no devolvió una observación utilizable."""


class LimiteDeSalida(VisionError):
    """La respuesta se cortó por el tope de tokens, no por un fallo.

    Se separa porque no tiene sentido reintentarla: el mismo prompt con el
    mismo tope se vuelve a cortar en el mismo lugar. Lo que hay que hacer
    es subir el tope o pedirle menos al modelo.
    """


class CuotaDiaria:
    """Tope de llamadas extra por día, como fracción de las fotos del día.

    Con volumen alto, un lote de fotos malas (una sala con contraluz, un
    reponedor nuevo con mal pulso) puede disparar verificaciones o
    escalados en cascada y multiplicar la factura sin que nadie se entere.
    Este contador corta cuando se pasa de la fracción configurada.

    Vive en memoria del proceso: con varias réplicas del worker cada una
    lleva su propia cuota, lo que reparte el tope de forma proporcional.
    No necesita ser exacto, necesita evitar la sorpresa a fin de mes.
    """

    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self._dia: Optional[str] = None
        self._total = 0
        self._usados = 0

    def _rotar(self) -> None:
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if hoy != self._dia:
            self._dia, self._total, self._usados = hoy, 0, 0

    def registrar_foto(self) -> None:
        self._rotar()
        self._total += 1

    def permite(self, fraccion_max: float) -> bool:
        self._rotar()
        if fraccion_max >= 1.0:
            return True
        if fraccion_max <= 0:
            return False
        # La primera del día siempre pasa: sin esto, con el total en 1
        # ninguna llegaría nunca al umbral.
        if self._usados == 0:
            return True
        return self._usados < self._total * fraccion_max

    def registrar_uso(self) -> None:
        self._rotar()
        self._usados += 1

    def estado(self) -> dict:
        self._rotar()
        return {"dia": self._dia, "fotos": self._total, self.nombre: self._usados}


# Las fotos se cuentan una sola vez, en la cuota de verificación; la de
# escalado comparte ese total a través de `registrar_foto` en ambas.
cuota_verificacion = CuotaDiaria("verificaciones")
cuota_escalado = CuotaDiaria("escalados")


def _headers() -> dict[str, str]:
    cfg = get_settings()
    return {
        "Authorization": f"Bearer {cfg.openrouter_api_key}",
        "Content-Type": "application/json",
        # OpenRouter usa estos dos para atribuir el tráfico en su dashboard.
        "HTTP-Referer": cfg.app_url,
        "X-Title": cfg.app_title,
    }


def _extraer_json(texto: str) -> dict:
    """Parsea la respuesta aunque el modelo la envuelva en markdown.

    Todo fallo sale como `VisionError`, nunca como `JSONDecodeError`: es lo
    que permite que `_llamar_con_reintento` lo capture y vuelva a pedir.
    Dejar escapar la excepción de json haría reventar al worker con una
    respuesta truncada, que es justo el caso que hay que reintentar.
    """
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("```", 2)[1]
        if texto.startswith("json"):
            texto = texto[4:]
        texto = texto.strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    # Segundo intento: recortar a las llaves exteriores, por si el modelo
    # adornó la respuesta. Si el JSON viene partido a la mitad esto también
    # falla, y ahí sí no hay nada que rescatar.
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise VisionError(f"Respuesta sin JSON reconocible: {texto[:300]}")
    try:
        return json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError as exc:
        raise VisionError(f"JSON incompleto o mal formado: {exc}") from exc


def _normalizar(bruto: dict, codigos_validos: set[str]) -> Observacion:
    """Sanea la salida del modelo antes de dársela al motor de reglas.

    Aunque el esquema sea estricto, un modelo puede devolver un código que
    no existe o un nivel en cero. Se descarta la basura en vez de dejar
    que contamine el score.
    """
    detecciones = []
    for d in bruto.get("detecciones") or []:
        codigo = (d.get("sku_codigo") or "").strip()
        if codigo not in codigos_validos:
            log.info("Detección descartada: SKU '%s' no está en el catálogo", codigo)
            continue
        d["sku_codigo"] = codigo
        d["nivel"] = max(1, int(d.get("nivel") or 1))
        d["frentes"] = max(1, int(d.get("frentes") or 1))
        d["confianza"] = min(1.0, max(0.0, float(d.get("confianza") or 0.0)))
        # El modelo devuelve la caja como dos enteros planos porque el
        # objeto anidado lo hace generar JSON roto (ver prompt.py); acá se
        # vuelve a armar el bbox que usa el motor de reglas.
        if "bbox" not in d:
            d["bbox"] = {"x0": int(d.pop("x0", 0) or 0), "x1": int(d.pop("x1", 1000) or 0)}
        detecciones.append(d)
    bruto["detecciones"] = detecciones

    # Solo sobreviven las etiquetas de un SKU nuestro. Una etiqueta de la
    # competencia no la usa ninguna regla —ni la auditoría de precios ni
    # las señales de riesgo la miran—, así que arrastrarla solo infla el
    # registro. El costo real de pedirlas se paga antes, en tokens de
    # salida: medido contra SKU-110K, una foto con 60 etiquetas ajenas
    # gastó 6.882 tokens y 122 segundos para que el código las tirara.
    etiquetas = []
    for e in bruto.get("etiquetas") or []:
        if e.get("sku_asociado") not in codigos_validos:
            continue
        e["nivel"] = max(1, int(e.get("nivel") or 1))
        etiquetas.append(e)
    bruto["etiquetas"] = etiquetas

    for h in bruto.get("huecos") or []:
        h["nivel"] = max(1, int(h.get("nivel") or 1))
        h["ancho_frentes_aprox"] = max(1, int(h.get("ancho_frentes_aprox") or 1))
        if h.get("sku_codigo_sugerido") not in codigos_validos:
            h["sku_codigo_sugerido"] = None

    bruto["niveles_visibles"] = max(1, int(bruto.get("niveles_visibles") or 1))

    # El total del lineal lo suma el código, no el modelo. Se le pide el
    # desglose bandeja por bandeja porque preguntarle el total de una vez
    # no funciona: medido contra SKU-110K, respondía 0 en 8 de 12 fotos
    # que tenían más de cien productos, o soltaba un número redondo
    # repetido. Obligarlo a recorrer bandeja por bandeja es lo que lo hace
    # contar de verdad, y la suma es aritmética: no hay por qué delegarla.
    por_nivel = [max(0, int(n or 0)) for n in (bruto.get("frentes_por_nivel") or [])]
    bruto["frentes_por_nivel"] = por_nivel
    total = sum(por_nivel) or max(0, int(bruto.get("frentes_totales_lineal") or 0))

    # El total no puede quedar por debajo de lo nuestro: sería un share of
    # shelf mayor a 100%. Un 0 se deja en 0 a propósito: es la señal de "no
    # se pudo contar el lineal" y `rules.py` saca el share del promedio en
    # vez de inventar un denominador.
    propios = sum(d["frentes"] for d in detecciones)
    if 0 < total < propios:
        log.info(
            "Lineal mal contado: %d totales < %d frentes propios; se usa el mayor",
            total, propios,
        )
        total = propios
    bruto["frentes_totales_lineal"] = total

    try:
        return Observacion.model_validate(bruto)
    except ValidationError as exc:
        raise VisionError(f"Observación inválida: {exc}") from exc


def _llamar_modelo(
    client: httpx.Client, modelo: str, mensajes: list[dict], temperatura: float = 0.0
) -> tuple[dict, dict, int]:
    cfg = get_settings()
    payload = {
        "model": modelo,
        "messages": mensajes,
        "response_format": RESPONSE_FORMAT,
        # La primera lectura va con 0: la misma foto debe dar el mismo
        # resultado. La de verificación sube la temperatura a propósito.
        "temperature": temperatura,
        # La latencia de esta llamada es casi toda generación de salida:
        # medido, ~16 ms por token. El tope evita que una respuesta que se
        # descarrila convierta una foto de 30 s en uno de tres minutos.
        "max_tokens": cfg.max_tokens_salida,
        # Pide a OpenRouter el costo real de la llamada.
        "usage": {"include": True},
    }
    if cfg.preferencia_proveedor:
        # OpenRouter sirve el mismo modelo desde varios proveedores, con
        # velocidades muy distintas. Sin esto toma el que le toque.
        payload["provider"] = {"sort": cfg.preferencia_proveedor}

    inicio = time.monotonic()
    resp = client.post(
        f"{cfg.openrouter_base_url}/chat/completions",
        headers=_headers(),
        json=payload,
        timeout=cfg.http_timeout_segundos,
    )
    duracion_ms = int((time.monotonic() - inicio) * 1000)

    if resp.status_code >= 400:
        raise VisionError(f"OpenRouter {resp.status_code} con {modelo}: {resp.text[:500]}")

    data = resp.json()
    if "choices" not in data or not data["choices"]:
        raise VisionError(f"Respuesta sin choices: {json.dumps(data)[:500]}")

    eleccion = data["choices"][0]
    contenido = eleccion["message"].get("content") or ""

    # Un corte por límite de tokens no es un fallo transitorio: reintentar
    # da exactamente lo mismo. Se distingue para que el mensaje diga qué
    # hacer (subir MAX_TOKENS_SALIDA) en vez de "JSON mal formado".
    if eleccion.get("finish_reason") == "length":
        usados = (data.get("usage") or {}).get("completion_tokens", "?")
        raise LimiteDeSalida(
            f"{modelo} agotó el tope de {cfg.max_tokens_salida} tokens de salida "
            f"(usó {usados}) y la respuesta quedó cortada. Sube MAX_TOKENS_SALIDA "
            f"o reduce el catálogo de la categoría."
        )

    return _extraer_json(contenido), data.get("usage") or {}, duracion_ms


def _llamar_con_reintento(
    client: httpx.Client, modelo: str, mensajes: list[dict], temperatura: float = 0.0
) -> tuple[dict, dict, int]:
    """Llama al modelo reintentando, con más temperatura en cada intento.

    El modelo entra a veces en un bucle degenerado —se queda escribiendo
    tabuladores en vez de cerrar el JSON— y el proveedor devuelve eso como
    respuesta terminada. Medido contra Qwen3-VL 32B sobre la misma foto,
    pasa aproximadamente 1 de cada 3 veces.

    La clave está en **subir la temperatura en cada reintento**. Con 0, la
    decodificación es voraz y determinista: repetir la petición idéntica
    reproduce exactamente el mismo bucle, así que reintentar no serviría de
    nada. Un poco de aleatoriedad es justo lo que rompe el ciclo.

    No tiene que ver con la foto: la misma imagen funciona al segundo
    intento. Darla por perdida sería mandar a un reponedor a repetir un
    trabajo que hizo bien.

    Lo que NO se reintenta: un 4xx de OpenRouter, que significa que la
    petición está mal armada y volver a mandarla daría lo mismo.
    """
    cfg = get_settings()
    ultimo: Optional[VisionError] = None
    gastado_ms = 0
    intentos = max(1, cfg.reintentos_respuesta_invalida)

    for intento in range(1, intentos + 1):
        # 0.0 → 0.35 → 0.70 …: suficiente para salir del bucle sin perder
        # el apego a lo que la foto muestra.
        temp = temperatura + (intento - 1) * 0.35
        inicio = time.monotonic()
        try:
            bruto, uso, ms = _llamar_modelo(client, modelo, mensajes, temp)
            if intento > 1:
                log.info(
                    "Respuesta válida al intento %d con %s (temperatura %.2f)",
                    intento, modelo, temp,
                )
            return bruto, uso, gastado_ms + ms
        except LimiteDeSalida:
            raise  # reintentar con el mismo tope se corta en el mismo lugar
        except VisionError as exc:
            texto = str(exc)
            if "OpenRouter 4" in texto:
                raise  # petición mal armada: reintentar no cambia nada
            ultimo = exc
            # El intento fallido igual consumió tiempo de pared; si no se
            # sumara, el reporte de latencia mentiría.
            gastado_ms += int((time.monotonic() - inicio) * 1000)
            log.warning(
                "Respuesta inutilizable de %s (intento %d, temperatura %.2f): %s",
                modelo, intento, temp, texto[:160],
            )

    raise ultimo or VisionError(f"{modelo} no devolvió una respuesta utilizable.")


class _Gasto:
    """Acumula tokens, costo y tiempo de todas las llamadas de una foto.

    Cada lectura se suma: verificar no es gratis y tiene que verse en el
    reporte de gasto, aunque sea barato.
    """

    def __init__(self) -> None:
        self.tokens_in = 0
        self.tokens_out = 0
        self.costo = 0.0
        self.duracion = 0
        self.lecturas = 0

    def sumar(self, uso: dict, duracion_ms: int) -> None:
        self.tokens_in += uso.get("prompt_tokens", 0)
        self.tokens_out += uso.get("completion_tokens", 0)
        self.costo += float(uso.get("cost") or 0.0)
        self.duracion += duracion_ms
        self.lecturas += 1


def _filtrar_motivos(motivos: list[str], cfg) -> list[str]:
    """Aplica los interruptores de configuración a los motivos detectados."""
    apagados = []
    if not cfg.verificar_si_hay_huecos:
        apagados.append("hueco")
    if not cfg.verificar_si_precio_fuera_rango:
        apagados.append("precio fuera de rango")
    if not cfg.verificar_si_falta_prioritario:
        apagados.append("SKU prioritario")
    return [m for m in motivos if not any(a in m for a in apagados)]


def analizar_foto(
    skus: Sequence[Sku],
    foto_data_url: str,
    hoja_referencia: Optional[str] = None,
    categoria: str = "",
    cadena: str = "",
    client: Optional[httpx.Client] = None,
    precios: Optional[Mapping[str, Precio]] = None,
) -> tuple[Observacion, UsoModelo]:
    """Lee una foto de góndola y devuelve la observación cruda.

    Una sola llamada al modelo barato en el caso normal. Se pide una
    **segunda lectura al mismo modelo barato**, con un método de conteo
    distinto, cuando la primera reporta algo que sería caro si fuera falso:
    un hueco, un precio fuera de rango o un SKU prioritario ausente
    (ver `riesgo.py`). Las dos lecturas se fusionan en `consenso.py`.

    `precios` es opcional pero conviene pasarlo: sin él no se puede saber
    si un precio leído está fuera de rango, y se pierde uno de los tres
    motivos de verificación.
    """
    cfg = get_settings()
    if not cfg.openrouter_api_key:
        raise VisionError("Falta OPENROUTER_API_KEY.")

    codigos = {s.codigo for s in skus}
    args_prompt = (skus, foto_data_url, hoja_referencia, categoria, cadena)
    mensajes = construir_mensajes(*args_prompt)

    propio = client is None
    client = client or httpx.Client()
    gasto = _Gasto()

    try:
        cuota_verificacion.registrar_foto()
        cuota_escalado.registrar_foto()

        bruto, uso, ms = _llamar_con_reintento(client, cfg.modelo_primario, mensajes)
        gasto.sumar(uso, ms)
        obs = _normalizar(bruto, codigos)
        modelo_usado, escalado, nota = cfg.modelo_primario, False, None

        motivos = _filtrar_motivos(
            motivos_para_verificar(
                obs, skus, precios,
                umbral_confianza=cfg.umbral_escalado,
                umbral_deteccion=cfg.umbral_deteccion,
            ),
            cfg,
        )
        if not motivos:
            return obs, _uso(modelo_usado, escalado, gasto, nota)

        if not cuota_verificacion.permite(cfg.verificacion_max_fraccion_diaria):
            log.warning(
                "Habría que verificar (%s) pero la cuota diaria está agotada (%s).",
                "; ".join(motivos), cuota_verificacion.estado(),
            )
            return obs, _uso(modelo_usado, escalado, gasto, "verificación omitida por cuota")

        estrategia = cfg.estrategia_baja_confianza
        log.info("Verificando porque %s → estrategia '%s'", "; ".join(motivos), estrategia)

        # ── Consenso: segunda lectura del mismo modelo barato ────────
        if estrategia == "consenso":
            cuota_verificacion.registrar_uso()
            try:
                bruto2, uso2, ms2 = _llamar_con_reintento(
                    client,
                    cfg.modelo_primario,
                    construir_mensajes_verificacion(*args_prompt),
                    temperatura=cfg.temperatura_verificacion,
                )
                gasto.sumar(uso2, ms2)
                obs2 = _normalizar(bruto2, codigos)
                obs, acuerdo = fusionar(obs, obs2)
                nota = f"verificada ({motivos[0]}); {acuerdo.resumen()}"

                # Tercer intento solo si las dos lecturas se contradicen de
                # verdad: ahí el modelo barato ya demostró que no puede con
                # esta foto y vale pagar el grande.
                if (
                    cfg.umbral_acuerdo_para_escalar > 0
                    and acuerdo.indice < cfg.umbral_acuerdo_para_escalar
                    and cfg.modelo_escalado != cfg.modelo_primario
                    and cuota_escalado.permite(cfg.escalado_max_fraccion_diaria)
                ):
                    log.info("Acuerdo de solo %.0f%%: se escala a %s", acuerdo.indice * 100, cfg.modelo_escalado)
                    cuota_escalado.registrar_uso()
                    bruto3, uso3, ms3 = _llamar_con_reintento(client, cfg.modelo_escalado, mensajes)
                    gasto.sumar(uso3, ms3)
                    obs3 = _normalizar(bruto3, codigos)
                    obs, modelo_usado, escalado = obs3, cfg.modelo_escalado, True
                    nota = f"{nota}; resuelto por {cfg.modelo_escalado}"
            except VisionError as exc:
                # La verificación es una mejora, no un requisito: si falla
                # nos quedamos con la primera lectura.
                log.warning("Falló la lectura de verificación, se conserva la primera: %s", exc)
                nota = "verificación fallida"

        # ── Escalado directo al modelo grande ────────────────────────
        elif estrategia == "escalado" and cfg.modelo_escalado != cfg.modelo_primario:
            if not cuota_escalado.permite(cfg.escalado_max_fraccion_diaria):
                log.warning(
                    "Cuota diaria de escalado agotada (%s); se conserva la lectura barata.",
                    cuota_escalado.estado(),
                )
            else:
                cuota_escalado.registrar_uso()
                try:
                    bruto2, uso2, ms2 = _llamar_con_reintento(client, cfg.modelo_escalado, mensajes)
                    gasto.sumar(uso2, ms2)
                    obs2 = _normalizar(bruto2, codigos)
                    if obs2.confianza_global >= obs.confianza_global:
                        obs, modelo_usado, escalado = obs2, cfg.modelo_escalado, True
                except VisionError as exc:
                    log.warning("Falló el escalado, se conserva la lectura primaria: %s", exc)

        return obs, _uso(modelo_usado, escalado, gasto, nota)
    finally:
        if propio:
            client.close()


def _uso(modelo: str, escalado: bool, gasto: _Gasto, nota: Optional[str]) -> UsoModelo:
    return UsoModelo(
        modelo=modelo,
        escalado=escalado,
        tokens_entrada=gasto.tokens_in,
        tokens_salida=gasto.tokens_out,
        costo_usd=round(gasto.costo, 6),
        duracion_ms=gasto.duracion,
        lecturas=gasto.lecturas,
        nota_consenso=nota,
    )
