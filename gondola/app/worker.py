"""Worker de la cola de fotos.

Corre como proceso aparte del API en Railway. Toma fotos pendientes,
las procesa y vuelve a dormir. Es seguro levantar varias réplicas: el
reclamo de foto usa SKIP LOCKED en Postgres.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import db
from .config import get_settings

log = logging.getLogger(__name__)

_corriendo = True


def _detener(signum, _frame):  # pragma: no cover - depende de señales del SO
    global _corriendo
    log.info("Señal %s recibida, terminando el lote en curso...", signum)
    _corriendo = False


def _procesar_seguro(foto: dict) -> None:
    from .pipeline import procesar  # import diferido: evita cargar PIL en el API

    try:
        procesar(foto)
    except Exception:
        # `procesar` ya registró el error y marcó la foto. El worker no
        # puede morir por una foto mala.
        pass


def ciclo() -> int:
    """Procesa todas las fotos pendientes disponibles. Devuelve cuántas."""
    cfg = get_settings()
    procesadas = 0

    with ThreadPoolExecutor(max_workers=cfg.worker_concurrencia) as pool:
        while _corriendo:
            lote = []
            for _ in range(cfg.worker_concurrencia):
                foto = db.reclamar_foto()
                if foto is None:
                    break
                lote.append(foto)

            if not lote:
                break

            list(pool.map(_procesar_seguro, lote))
            procesadas += len(lote)

    return procesadas


def main() -> None:
    cfg = get_settings()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    signal.signal(signal.SIGTERM, _detener)
    signal.signal(signal.SIGINT, _detener)

    log.info(
        "Worker de góndola arriba | primario=%s escalado=%s",
        cfg.modelo_primario, cfg.modelo_escalado,
    )

    while _corriendo:
        try:
            if ciclo() == 0:
                time.sleep(cfg.worker_intervalo_segundos)
        except Exception:
            # Caída de red o de Supabase: se espera y se reintenta. Salir
            # dejaría la cola parada hasta el próximo deploy.
            log.exception("Fallo en el ciclo del worker; reintentando")
            time.sleep(cfg.worker_intervalo_segundos * 3)

    log.info("Worker detenido.")
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
