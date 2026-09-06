"""Cliente de visión sobre OpenRouter.

Estrategia de dos niveles, pensada para volumen alto:

  1. Toda foto pasa por el modelo primario (barato).
  2. Solo si el propio modelo reporta baja confianza —o la foto salió
     mala— se reintenta con el modelo de escalado.

Así el costo promedio queda cerca del modelo barato y la precisión cerca
del caro, sin meter a una persona en el circuito.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Sequence

import httpx
from pydantic import ValidationError

from .config import get_settings
from .prompt import RESPONSE_FORMAT, construir_mensajes
from .schemas import Observacion, Sku, UsoModelo

log = logging.getLogger(__name__)


class VisionError(RuntimeError):
    """El modelo no devolvió una observación utilizable."""


class CuotaEscalado:
    """Tope diario de escalados al modelo grande.

    Con volumen alto, un lote de fotos malas (una sala con contraluz, un
    reponedor nuevo con mal pulso) puede mandar todo al modelo caro y
    multiplicar la factura del día sin que nadie se entere. Este contador
    corta el escalado cuando pasa de la fracción configurada.

    Vive en memoria del proceso: con varias réplicas del worker cada una
    lleva su propia cuota, lo que reparte el tope de forma proporcional.
    No necesita ser exacto, necesita evitar la sorpresa a fin de mes.
    """

    def __init__(self) -> None:
        self._dia: Optional[str] = None
        self._total = 0
        self._escalados = 0

    def _rotar(self) -> None:
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if hoy != self._dia:
            self._dia, self._total, self._escalados = hoy, 0, 0

    def registrar_foto(self) -> None:
        self._rotar()
        self._total += 1

    def permite_escalar(self, fraccion_max: float) -> bool:
        self._rotar()
        if fraccion_max >= 1.0:
            return True
        if fraccion_max <= 0:
            return False
        # Las primeras fotos del día siempre pueden escalar: sin esto,
        # con el total en 1 ninguna pasaría nunca el umbral.
        if self._escalados == 0:
            return True
        return self._escalados < self._total * fraccion_max

    def registrar_escalado(self) -> None:
        self._rotar()
        self._escalados += 1

    def estado(self) -> dict:
        self._rotar()
        return {"dia": self._dia, "fotos": self._total, "escalados": self._escalados}


cuota_escalado = CuotaEscalado()


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
    """Parsea la respuesta aunque el modelo la envuelva en markdown."""
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("```", 2)[1]
        if texto.startswith("json"):
            texto = texto[4:]
        texto = texto.strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio, fin = texto.find("{"), texto.rfind("}")
        if inicio == -1 or fin <= inicio:
            raise VisionError(f"Respuesta sin JSON reconocible: {texto[:300]}")
        return json.loads(texto[inicio : fin + 1])


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
        detecciones.append(d)
    bruto["detecciones"] = detecciones

    for e in bruto.get("etiquetas") or []:
        if e.get("sku_asociado") and e["sku_asociado"] not in codigos_validos:
            e["sku_asociado"] = None
        e["nivel"] = max(1, int(e.get("nivel") or 1))

    for h in bruto.get("huecos") or []:
        h["nivel"] = max(1, int(h.get("nivel") or 1))
        h["ancho_frentes_aprox"] = max(1, int(h.get("ancho_frentes_aprox") or 1))
        if h.get("sku_codigo_sugerido") not in codigos_validos:
            h["sku_codigo_sugerido"] = None

    bruto["niveles_visibles"] = max(1, int(bruto.get("niveles_visibles") or 1))
    bruto["frentes_totales_lineal"] = max(0, int(bruto.get("frentes_totales_lineal") or 0))

    try:
        return Observacion.model_validate(bruto)
    except ValidationError as exc:
        raise VisionError(f"Observación inválida: {exc}") from exc


def _llamar_modelo(
    client: httpx.Client, modelo: str, mensajes: list[dict]
) -> tuple[dict, dict, int]:
    cfg = get_settings()
    payload = {
        "model": modelo,
        "messages": mensajes,
        "response_format": RESPONSE_FORMAT,
        # Determinismo: la misma foto debe dar la misma lectura.
        "temperature": 0.0,
        # Pide a OpenRouter el costo real de la llamada.
        "usage": {"include": True},
    }

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

    contenido = data["choices"][0]["message"].get("content") or ""
    return _extraer_json(contenido), data.get("usage") or {}, duracion_ms


def analizar_foto(
    skus: Sequence[Sku],
    foto_data_url: str,
    hoja_referencia: Optional[str] = None,
    categoria: str = "",
    cadena: str = "",
    client: Optional[httpx.Client] = None,
) -> tuple[Observacion, UsoModelo]:
    """Lee una foto de góndola y devuelve la observación cruda."""
    cfg = get_settings()
    if not cfg.openrouter_api_key:
        raise VisionError("Falta OPENROUTER_API_KEY.")

    codigos = {s.codigo for s in skus}
    mensajes = construir_mensajes(skus, foto_data_url, hoja_referencia, categoria, cadena)

    propio = client is None
    client = client or httpx.Client()
    try:
        cuota_escalado.registrar_foto()
        bruto, uso, duracion = _llamar_modelo(client, cfg.modelo_primario, mensajes)
        obs = _normalizar(bruto, codigos)
        modelo_usado, escalado = cfg.modelo_primario, False
        tokens_in = uso.get("prompt_tokens", 0)
        tokens_out = uso.get("completion_tokens", 0)
        costo = float(uso.get("cost") or 0.0)

        necesita_escalar = (
            obs.confianza_global < cfg.umbral_escalado or obs.calidad_foto == "mala"
        )
        if necesita_escalar and not cuota_escalado.permite_escalar(cfg.escalado_max_fraccion_diaria):
            log.warning(
                "Foto con confianza %.2f pero la cuota diaria de escalado está agotada (%s); "
                "se conserva la lectura del modelo barato.",
                obs.confianza_global, cuota_escalado.estado(),
            )
            necesita_escalar = False

        if necesita_escalar and cfg.modelo_escalado != cfg.modelo_primario:
            cuota_escalado.registrar_escalado()
            log.info(
                "Escalando a %s (confianza %.2f, calidad %s)",
                cfg.modelo_escalado, obs.confianza_global, obs.calidad_foto,
            )
            try:
                bruto2, uso2, duracion2 = _llamar_modelo(client, cfg.modelo_escalado, mensajes)
                obs2 = _normalizar(bruto2, codigos)
                # Se acumula el costo de ambas llamadas: el escalado no es gratis
                # y tiene que verse en el reporte de gasto.
                tokens_in += uso2.get("prompt_tokens", 0)
                tokens_out += uso2.get("completion_tokens", 0)
                costo += float(uso2.get("cost") or 0.0)
                duracion += duracion2
                if obs2.confianza_global >= obs.confianza_global:
                    obs, modelo_usado, escalado = obs2, cfg.modelo_escalado, True
            except VisionError as exc:
                # Si el escalado falla nos quedamos con la lectura barata.
                log.warning("Falló el escalado, se conserva la lectura primaria: %s", exc)

        return obs, UsoModelo(
            modelo=modelo_usado,
            escalado=escalado,
            tokens_entrada=tokens_in,
            tokens_salida=tokens_out,
            costo_usd=round(costo, 6),
            duracion_ms=duracion,
        )
    finally:
        if propio:
            client.close()
