"""Autorización de los endpoints de administración.

El servicio corre con `service_role`, que bypassea RLS. Eso está bien para
el worker, pero significa que cualquiera que alcance la URL de Railway
podría cambiar precios si no se valida quién llama.

Por eso los endpoints que escriben catálogo o precios exigen el JWT del
usuario (el mismo que emite Supabase Auth en el frontend) y comprueban su
rol en `sadimex_profiles`. La verificación se hace contra Supabase, no
decodificando el token acá: así una sesión revocada deja de funcionar de
inmediato.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request

from . import db

log = logging.getLogger(__name__)

ROLES_ADMIN = {"admin"}
ROLES_LECTURA_GERENCIAL = {"admin", "gerente"}


def _token_del_header(request: Request) -> str:
    autorizacion = request.headers.get("Authorization") or ""
    if not autorizacion.lower().startswith("bearer "):
        raise HTTPException(401, "Falta el encabezado Authorization: Bearer <token>.")
    token = autorizacion.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, "Token vacío.")
    return token


def usuario_actual(request: Request) -> dict:
    """Perfil del usuario que hace la llamada, validado contra Supabase."""
    token = _token_del_header(request)
    try:
        respuesta = db.cliente().auth.get_user(token)
    except Exception as exc:
        log.warning("Token rechazado por Supabase: %s", exc)
        raise HTTPException(401, "Token inválido o expirado.") from exc

    usuario = getattr(respuesta, "user", None)
    if usuario is None:
        raise HTTPException(401, "Token inválido o expirado.")

    perfil = db.traer_perfil(usuario.id)
    if perfil is None:
        raise HTTPException(403, "El usuario no tiene perfil en SADIMEX.")
    if perfil.get("activo") is False:
        raise HTTPException(403, "Cuenta desactivada.")
    return perfil


def _exige(roles: set[str], etiqueta: str):
    def dependencia(perfil: dict = Depends(usuario_actual)) -> dict:
        if perfil.get("rol") not in roles:
            raise HTTPException(403, f"Se requiere rol {etiqueta}.")
        return perfil

    return dependencia


requiere_admin = _exige(ROLES_ADMIN, "administrador")
requiere_gerencia = _exige(ROLES_LECTURA_GERENCIAL, "gerente o administrador")


def ciudad_del_perfil(perfil: dict) -> Optional[str]:
    """Ciudad a la que se limita este usuario, o None si ve todo el país."""
    ciudad = perfil.get("ciudad")
    if perfil.get("rol") in ROLES_LECTURA_GERENCIAL or ciudad == "ALL":
        return None
    return ciudad
