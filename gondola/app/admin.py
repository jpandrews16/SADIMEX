"""Endpoints de administración: catálogo y precios por cadena.

Todo lo que escribe exige rol `admin`. Todo lo que lee (cobertura, costos,
qué falta cargar) lo puede ver gerencia.

La carga es por CSV porque es lo que el administrador ya tiene: una
planilla de precios por cadena. No hay que enseñarle una interfaz nueva
para subir 300 precios.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import db
from .auth import requiere_admin, requiere_gerencia
from .reference_sheet import limpiar_cache

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gondola/admin", tags=["administración"])

# Tamaño máximo de un CSV. Una planilla de precios de todo el país no
# llega ni cerca; por encima de esto es un archivo equivocado.
MAX_CSV_BYTES = 5 * 1024 * 1024


# =====================================================================
# Utilidades de CSV
# =====================================================================


def _leer_csv(contenido: bytes) -> list[dict]:
    """Parsea un CSV a filas con claves normalizadas.

    Acepta UTF-8 con o sin BOM, que es lo que exporta Excel en Windows.
    """
    if len(contenido) > MAX_CSV_BYTES:
        raise HTTPException(413, f"El archivo supera {MAX_CSV_BYTES // 1024 // 1024} MB.")
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            texto = contenido.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "No se pudo leer el archivo: codificación desconocida.") from exc

    # Excel exporta con ';' en configuraciones en español.
    muestra = texto[:4096]
    delimitador = ";" if muestra.count(";") > muestra.count(",") else ","

    lector = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
    if not lector.fieldnames:
        raise HTTPException(400, "El CSV no tiene encabezados.")

    filas = []
    for fila in lector:
        limpia = {
            (k or "").strip().lower().replace(" ", "_"): (v.strip() if isinstance(v, str) else v)
            for k, v in fila.items()
        }
        if any(limpia.values()):
            filas.append(limpia)
    return filas


def _numero(valor, defecto: Optional[float] = None) -> Optional[float]:
    """Convierte a float tolerando coma decimal y símbolos de moneda."""
    if valor is None or valor == "":
        return defecto
    if isinstance(valor, (int, float)):
        return float(valor)
    limpio = str(valor).replace("Bs", "").replace("$", "").replace(" ", "").strip()
    # "1.234,56" (formato local) -> "1234.56"
    if "," in limpio and "." in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    else:
        limpio = limpio.replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return defecto


def _booleano(valor) -> bool:
    return str(valor).strip().lower() in {"1", "true", "si", "sí", "x", "y", "yes", "verdadero"}


# =====================================================================
# Precios
# =====================================================================


class PrecioEntrada(BaseModel):
    sku_codigo: str
    # Vacío o ausente = precio nacional, aplica donde la cadena no tiene uno propio.
    cadena: Optional[str] = None
    pvp: float = Field(gt=0)
    moneda: str = "BOB"
    tolerancia_pct: float = 3.0


class ResumenCarga(BaseModel):
    total: int
    creados: int = 0
    actualizados: int = 0
    sin_cambio: int = 0
    errores: list[str] = Field(default_factory=list)


def _cargar_precios(entradas: list[PrecioEntrada]) -> ResumenCarga:
    resumen = ResumenCarga(total=len(entradas))
    for entrada in entradas:
        resultado = db.cargar_precio(
            sku_codigo=entrada.sku_codigo,
            cadena_nombre=entrada.cadena,
            pvp=entrada.pvp,
            moneda=entrada.moneda,
            tolerancia_pct=entrada.tolerancia_pct,
        )
        accion = resultado.get("accion")
        if accion == "creado":
            resumen.creados += 1
        elif accion == "actualizado":
            resumen.actualizados += 1
        elif accion == "sin_cambio":
            resumen.sin_cambio += 1
        else:
            resumen.errores.append(resultado.get("detalle") or "error desconocido")
    return resumen


@router.post("/precios", response_model=ResumenCarga)
def cargar_precios(entradas: list[PrecioEntrada], _admin=Depends(requiere_admin)) -> ResumenCarga:
    """Carga precios desde JSON. El precio anterior se cierra, no se borra."""
    if not entradas:
        raise HTTPException(400, "No se recibió ningún precio.")
    return _cargar_precios(entradas)


@router.post("/precios/csv", response_model=ResumenCarga)
def cargar_precios_csv(
    archivo: UploadFile = File(...), _admin=Depends(requiere_admin)
) -> ResumenCarga:
    """Carga masiva desde la planilla del administrador.

    Columnas: `sku_codigo, cadena, pvp` y opcionalmente `moneda`,
    `tolerancia_pct`. Dejar `cadena` vacía carga el precio nacional.

        sku_codigo,cadena,pvp
        NOEL-FESTIVAL-200,Fidalga,12.50
        NOEL-FESTIVAL-200,Hipermaxi,13.90
        NOEL-FESTIVAL-200,Tía,12.90
        NOEL-SALTIN-250,,15.00
    """
    filas = _leer_csv(archivo.file.read())
    if not filas:
        raise HTTPException(400, "El CSV está vacío.")

    entradas: list[PrecioEntrada] = []
    errores: list[str] = []

    for i, fila in enumerate(filas, start=2):  # fila 1 = encabezados
        codigo = fila.get("sku_codigo") or fila.get("codigo") or fila.get("sku")
        pvp = _numero(fila.get("pvp") or fila.get("precio"))
        if not codigo:
            errores.append(f"fila {i}: falta sku_codigo")
            continue
        if pvp is None or pvp <= 0:
            errores.append(f"fila {i}: PVP inválido para {codigo}")
            continue
        entradas.append(
            PrecioEntrada(
                sku_codigo=codigo,
                cadena=fila.get("cadena") or None,
                pvp=pvp,
                moneda=(fila.get("moneda") or "BOB").upper(),
                tolerancia_pct=_numero(fila.get("tolerancia_pct"), 3.0) or 3.0,
            )
        )

    resumen = _cargar_precios(entradas)
    # Las filas que ni siquiera se pudieron interpretar también cuentan en
    # el total: si no, el resumen miente sobre cuántas líneas traía el CSV.
    resumen.total = len(filas)
    resumen.errores = errores + resumen.errores
    return resumen


@router.get("/precios")
def listar_precios(cadena: Optional[str] = None, _g=Depends(requiere_gerencia)) -> dict:
    """Precios en vigor hoy, por SKU y cadena."""
    filtros = {"cadena": cadena} if cadena else None
    filas = db.traer_vista("gondola_precios_vigentes", filtros)
    return {"total": len(filas), "precios": filas}


@router.get("/precios/faltantes")
def precios_faltantes(_g=Depends(requiere_gerencia)) -> dict:
    """SKU sin PVP cargado.

    Para estos el sistema audita si la etiqueta está y es legible, pero no
    puede decir si el precio exhibido es correcto.
    """
    filas = db.traer_vista("gondola_skus_sin_precio")
    return {
        "total": len(filas),
        "prioritarios": sum(1 for f in filas if f.get("es_prioritario")),
        "skus": filas,
    }


# =====================================================================
# Catálogo
# =====================================================================


class SkuEntrada(BaseModel):
    codigo: str
    nombre: str
    marca: str
    categoria: str
    gramaje: Optional[str] = None
    ean: Optional[str] = None
    es_prioritario: bool = False
    packshot_url: Optional[str] = None
    descripcion_visual: Optional[str] = None
    activo: bool = True


@router.post("/catalogo")
def cargar_catalogo(entradas: list[SkuEntrada], _admin=Depends(requiere_admin)) -> dict:
    """Alta o actualización masiva de SKU, identificados por `codigo`."""
    if not entradas:
        raise HTTPException(400, "No se recibió ningún SKU.")
    filas = db.upsert_skus([e.model_dump() for e in entradas])
    # El mosaico de packshots se arma una vez y se cachea; si cambió el
    # catálogo hay que rearmarlo o las fotos siguientes usarían el viejo.
    limpiar_cache()
    return {"cargados": len(filas), "codigos": [f["codigo"] for f in filas]}


@router.post("/catalogo/csv")
def cargar_catalogo_csv(
    archivo: UploadFile = File(...), _admin=Depends(requiere_admin)
) -> dict:
    """Carga masiva de SKU desde CSV.

    Columnas: `codigo, nombre, marca, categoria` y opcionalmente
    `gramaje, ean, es_prioritario, packshot_url, descripcion_visual`.
    Es el formato que emite `tools/importar_catalogo_canva.py`.
    """
    filas = _leer_csv(archivo.file.read())
    if not filas:
        raise HTTPException(400, "El CSV está vacío.")

    entradas: list[SkuEntrada] = []
    errores: list[str] = []

    for i, fila in enumerate(filas, start=2):
        faltantes = [c for c in ("codigo", "nombre", "marca", "categoria") if not fila.get(c)]
        if faltantes:
            errores.append(f"fila {i}: faltan columnas {', '.join(faltantes)}")
            continue
        entradas.append(
            SkuEntrada(
                codigo=fila["codigo"],
                nombre=fila["nombre"],
                marca=fila["marca"],
                categoria=fila["categoria"],
                gramaje=fila.get("gramaje") or None,
                ean=fila.get("ean") or None,
                es_prioritario=_booleano(fila.get("es_prioritario")),
                packshot_url=fila.get("packshot_url") or None,
                descripcion_visual=fila.get("descripcion_visual") or None,
                activo=_booleano(fila.get("activo")) if fila.get("activo") else True,
            )
        )

    cargados = db.upsert_skus([e.model_dump() for e in entradas]) if entradas else []
    limpiar_cache()
    return {"total_filas": len(filas), "cargados": len(cargados), "errores": errores}


@router.get("/catalogo/cobertura")
def cobertura_catalogo(_g=Depends(requiere_gerencia)) -> dict:
    """Qué tan listo está el catálogo para auditar de verdad.

    `pct_con_packshot` bajo significa que el modelo no tiene con qué
    distinguir variantes parecidas en esa categoría.
    """
    return {"categorias": db.traer_vista("gondola_cobertura_catalogo")}


@router.get("/cadenas")
def listar_cadenas(_g=Depends(requiere_gerencia)) -> dict:
    return {"cadenas": db.traer_cadenas()}


# =====================================================================
# Costos
# =====================================================================


@router.get("/costos")
def costos(_g=Depends(requiere_gerencia)) -> dict:
    """Gasto de IA por día, ciudad y modelo.

    Con volumen alto la factura es un KPI operativo. Acá se ve el efecto
    de mover `UMBRAL_ESCALADO`.
    """
    filas = db.traer_vista("gondola_costos_diarios")
    filas.sort(key=lambda f: (f.get("dia") or ""), reverse=True)
    return {
        "dias": filas,
        "costo_total_usd": round(sum(float(f.get("costo_usd") or 0) for f in filas), 4),
        "fotos_totales": sum(int(f.get("fotos") or 0) for f in filas),
    }
