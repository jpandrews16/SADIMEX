"""API del lector de góndola.

Endpoints mínimos. El frontend sube la foto directo al Storage de Supabase
(igual que hace hoy con los audios) y después registra la foto acá; el
worker la levanta de la cola. Se puede forzar el análisis inmediato de una
foto puntual, que es lo que usa la pantalla de "analizar ahora".
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .admin import router as admin_router
from .config import get_settings
from .schemas import SubirFotoRequest, SubirFotoResponse

cfg = get_settings()
logging.basicConfig(
    level=cfg.log_level,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title="SADIMEX — Lector de Góndola",
    description="Auditoría automática de ejecución en sala y etiquetas de precio.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(admin_router)


@app.get("/health")
def health() -> dict:
    """Chequeo que Railway usa para saber si el servicio está vivo."""
    from .vision import cuota_escalado

    return {
        "ok": True,
        "modelo_primario": cfg.modelo_primario,
        "modelo_escalado": cfg.modelo_escalado,
        "cuota_escalado": cuota_escalado.estado(),
        "supabase_configurado": bool(cfg.supabase_url and cfg.supabase_service_role_key),
        "openrouter_configurado": bool(cfg.openrouter_api_key),
    }


@app.post("/api/gondola/fotos", response_model=SubirFotoResponse)
def registrar_foto(req: SubirFotoRequest) -> SubirFotoResponse:
    """Encola una foto ya subida al Storage."""
    sala = db.traer_sala(req.sala_id)
    if sala is None:
        raise HTTPException(404, f"Sala {req.sala_id} no encontrada.")

    alerta = None
    if req.imagen_sha256 and db.hash_ya_existe(req.imagen_sha256):
        alerta = "foto idéntica ya subida antes (posible reciclaje)"

    fila = db.registrar_foto(
        {
            "reponedor_id": req.reponedor_id,
            "sala_id": req.sala_id,
            "ciudad": sala["ciudad"],
            "categoria": req.categoria,
            "storage_path": req.storage_path,
            "tomada_at": req.tomada_at.isoformat() if req.tomada_at else None,
            "gps_lat": req.gps_lat,
            "gps_lng": req.gps_lng,
            "imagen_sha256": req.imagen_sha256,
            "alerta_captura": alerta,
        }
    )
    return SubirFotoResponse(photo_id=fila["id"], estado=fila["estado"], alerta_captura=alerta)


@app.post("/api/gondola/fotos/{photo_id}/analizar")
def analizar_ahora(photo_id: str, tareas: BackgroundTasks) -> dict:
    """Fuerza el análisis de una foto sin esperar al worker."""
    from .pipeline import procesar

    filas = db.cliente().table("gondola_photos").select("*").eq("id", photo_id).limit(1).execute().data
    if not filas:
        raise HTTPException(404, f"Foto {photo_id} no encontrada.")

    db.marcar_estado(photo_id, "procesando")
    tareas.add_task(procesar, filas[0])
    return {"photo_id": photo_id, "estado": "procesando"}


@app.get("/api/gondola/analisis/{photo_id}")
def obtener_analisis(photo_id: str) -> dict:
    analisis = db.traer_analisis(photo_id)
    if analisis is None:
        filas = (
            db.cliente().table("gondola_photos").select("estado,error_mensaje")
            .eq("id", photo_id).limit(1).execute().data
        )
        if not filas:
            raise HTTPException(404, f"Foto {photo_id} no encontrada.")
        return {"photo_id": photo_id, "estado": filas[0]["estado"], "error": filas[0].get("error_mensaje")}
    return analisis


@app.get("/api/gondola/catalogo")
def catalogo(categoria: Optional[str] = None) -> dict:
    """Catálogo activo. Lo usa la app para armar el selector de categoría."""
    skus = db.traer_skus(categoria)
    return {
        "total": len(skus),
        "con_packshot": sum(1 for s in skus if s.get("packshot_url")),
        "categorias": sorted({s["categoria"] for s in skus}),
        "skus": skus,
    }
