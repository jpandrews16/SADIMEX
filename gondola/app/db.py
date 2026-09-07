"""Acceso a Supabase con service_role.

El worker corre del lado servidor y bypassea RLS a propósito: necesita ver
todas las fotos pendientes de las tres ciudades. El aislamiento por ciudad
lo aplican las políticas RLS cuando el frontend lee con el token del
usuario, igual que en el módulo de audio.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import Client, create_client

from .config import get_settings
from .schemas import Analisis

log = logging.getLogger(__name__)

_cliente: Optional[Client] = None


def cliente() -> Client:
    global _cliente
    if _cliente is None:
        cfg = get_settings()
        if not cfg.supabase_url or not cfg.supabase_service_role_key:
            raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY.")
        _cliente = create_client(cfg.supabase_url, cfg.supabase_service_role_key)
    return _cliente


# =====================================================================
# Catálogo y configuración
# =====================================================================


def traer_skus(categoria: Optional[str] = None) -> list[dict]:
    q = cliente().table("gondola_skus").select("*").eq("activo", True)
    if categoria:
        q = q.eq("categoria", categoria)
    return q.execute().data or []


def traer_reglas() -> list[dict]:
    return cliente().table("gondola_reglas").select("*").eq("activo", True).execute().data or []


def traer_precios() -> list[dict]:
    return cliente().table("gondola_precios").select("*").is_("vigente_hasta", None).execute().data or []


def traer_pesos() -> dict[str, float]:
    filas = cliente().table("gondola_pesos").select("regla,peso").execute().data or []
    return {f["regla"]: float(f["peso"]) for f in filas}


def traer_perfil(user_id: str) -> Optional[dict]:
    filas = (
        cliente().table("sadimex_profiles").select("*").eq("id", user_id).limit(1).execute().data
    )
    return filas[0] if filas else None


def traer_cadenas() -> list[dict]:
    return cliente().table("cadenas").select("*").eq("activo", True).order("nombre").execute().data or []


def traer_sala(sala_id: str) -> Optional[dict]:
    filas = (
        cliente()
        .table("salas")
        .select("*, cadenas(id,nombre,formato)")
        .eq("id", sala_id)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


# =====================================================================
# Cola de fotos
# =====================================================================


def reclamar_foto() -> Optional[dict]:
    """Toma la siguiente foto pendiente de forma atómica.

    Usa SKIP LOCKED del lado de Postgres, así que se pueden levantar
    varios workers sin que dos procesen la misma foto.
    """
    cfg = get_settings()
    filas = cliente().rpc(
        "gondola_reclamar_foto", {"max_intentos": cfg.worker_max_intentos}
    ).execute().data
    if not filas:
        return None
    return filas[0] if isinstance(filas, list) else filas


def descargar_imagen(storage_path: str) -> bytes:
    cfg = get_settings()
    return cliente().storage.from_(cfg.supabase_bucket).download(storage_path)


def hash_ya_existe(sha256: str, excluir_photo_id: Optional[str] = None) -> bool:
    """Detecta una foto reciclada: mismo archivo subido dos veces."""
    q = cliente().table("gondola_photos").select("id").eq("imagen_sha256", sha256)
    if excluir_photo_id:
        q = q.neq("id", excluir_photo_id)
    return bool(q.limit(1).execute().data)


def registrar_foto(datos: dict[str, Any]) -> dict:
    return cliente().table("gondola_photos").insert(datos).execute().data[0]


def marcar_estado(photo_id: str, estado: str, error: Optional[str] = None) -> None:
    payload: dict[str, Any] = {"estado": estado}
    if error is not None:
        # Postgres corta igual, pero mejor no mandar un traceback entero.
        payload["error_mensaje"] = error[:1000]
    cliente().table("gondola_photos").update(payload).eq("id", photo_id).execute()


def marcar_alerta_captura(photo_id: str, alerta: str) -> None:
    cliente().table("gondola_photos").update({"alerta_captura": alerta}).eq("id", photo_id).execute()


# =====================================================================
# Resultados
# =====================================================================


def guardar_analisis(analisis: Analisis, etiquetas_detalle: list[dict]) -> dict:
    ev, obs, uso = analisis.evaluacion, analisis.observacion, analisis.uso
    fila = {
        "photo_id": analisis.photo_id,
        "reponedor_id": analisis.reponedor_id,
        "sala_id": analisis.sala_id,
        "ciudad": analisis.ciudad,
        "score": ev.score,
        "semaforo": ev.semaforo,
        "reglas": {k: v.model_dump() for k, v in ev.reglas.items()},
        "observacion": obs.model_dump(mode="json"),
        "etiquetas": etiquetas_detalle,
        "hallazgos": [h.model_dump() for h in ev.hallazgos],
        "share_of_shelf_pct": ev.share_of_shelf_pct,
        "quiebres_detectados": ev.quiebres_detectados,
        "confianza_global": obs.confianza_global,
        "calidad_foto": obs.calidad_foto,
        "modelo_usado": uso.modelo,
        "escalado": uso.escalado,
        "tokens_entrada": uso.tokens_entrada,
        "tokens_salida": uso.tokens_salida,
        "costo_usd": uso.costo_usd,
        "duracion_ms": uso.duracion_ms,
        "lecturas": uso.lecturas,
        "nota_consenso": uso.nota_consenso,
    }
    # upsert por photo_id: reprocesar una foto reemplaza su análisis en
    # vez de duplicarlo.
    return cliente().table("gondola_analyses").upsert(fila, on_conflict="photo_id").execute().data[0]


def traer_analisis(photo_id: str) -> Optional[dict]:
    filas = cliente().table("gondola_analyses").select("*").eq("photo_id", photo_id).limit(1).execute().data
    return filas[0] if filas else None


# =====================================================================
# Administración de catálogo y precios
# =====================================================================


def cargar_precio(
    sku_codigo: str,
    cadena_nombre: Optional[str],
    pvp: float,
    moneda: str = "BOB",
    tolerancia_pct: float = 3.0,
) -> dict:
    """Carga un precio cerrando el anterior. Devuelve {accion, detalle}.

    La lógica vive en el RPC `gondola_cargar_precio` para que el cierre del
    precio viejo y la inserción del nuevo ocurran en una sola transacción.
    """
    filas = cliente().rpc(
        "gondola_cargar_precio",
        {
            "p_sku_codigo": sku_codigo,
            "p_cadena_nombre": cadena_nombre,
            "p_pvp": pvp,
            "p_moneda": moneda,
            "p_tolerancia": tolerancia_pct,
        },
    ).execute().data
    if not filas:
        return {"accion": "error", "detalle": "el RPC no devolvió resultado"}
    return filas[0] if isinstance(filas, list) else filas


def upsert_skus(filas: list[dict]) -> list[dict]:
    """Alta o actualización masiva de SKU, por código."""
    if not filas:
        return []
    return cliente().table("gondola_skus").upsert(filas, on_conflict="codigo").execute().data or []


def traer_vista(nombre: str, filtros: Optional[dict] = None, limite: int = 1000) -> list[dict]:
    q = cliente().table(nombre).select("*")
    for columna, valor in (filtros or {}).items():
        q = q.eq(columna, valor)
    return q.limit(limite).execute().data or []
