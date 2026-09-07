"""Contratos de datos del lector de góndola.

Separación deliberada en dos capas:

  Observacion  — lo que el modelo de visión *ve* en la foto. Sin juicio.
  Evaluacion   — el veredicto contra las reglas, calculado por `rules.py`
                 en Python puro.

El modelo nunca decide si una góndola está bien ejecutada: solo reporta
qué hay, dónde y cuántos frentes. Así el score es reproducible, auditable
y se puede recalcular sobre fotos viejas cuando cambian las reglas, sin
volver a pagar una llamada de visión.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Semaforo = Literal["verde", "amarillo", "rojo"]
CalidadFoto = Literal["buena", "regular", "mala"]
NivelObjetivo = Literal["ojos", "manos", "ojos_o_manos", "superior", "inferior", "cualquiera"]
NombreRegla = Literal["presencia", "nivel", "frentes", "bloque", "etiqueta", "sin_quiebre"]
Severidad = Literal["critico", "alto", "medio", "bajo"]


# =====================================================================
# Catálogo y reglas (vienen de la base)
# =====================================================================


class Sku(BaseModel):
    id: str
    codigo: str
    nombre: str
    marca: str
    categoria: str
    gramaje: Optional[str] = None
    es_prioritario: bool = False
    packshot_url: Optional[str] = None
    descripcion_visual: Optional[str] = None


class Precio(BaseModel):
    sku_id: str
    cadena_id: Optional[str] = None
    pvp: float
    moneda: str = "BOB"
    tolerancia_pct: float = 3.0


class Regla(BaseModel):
    """Regla de ejecución ya resuelta para un SKU concreto."""

    nombre: str = "regla"
    exige_presencia: bool = True
    nivel_objetivo: NivelObjetivo = "cualquiera"
    frentes_minimos: int = 1
    share_minimo_pct: Optional[float] = None
    exige_bloque: bool = True
    exige_etiqueta: bool = True
    exige_sin_quiebre: bool = True


# =====================================================================
# Capa 1 — Observación (salida cruda del modelo de visión)
# =====================================================================


class BBox(BaseModel):
    """Caja normalizada 0-1000 sobre la imagen enviada: [x0, y0, x1, y1]."""

    x0: int = 0
    y0: int = 0
    x1: int = 1000
    y1: int = 1000

    @property
    def centro_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def ancho(self) -> int:
        return max(0, self.x1 - self.x0)


class Deteccion(BaseModel):
    """Un producto nuestro localizado en la góndola."""

    sku_codigo: str
    confianza: float = Field(ge=0.0, le=1.0)
    nivel: int = Field(ge=1, description="1 = nivel más bajo (piso)")
    frentes: int = Field(ge=1, description="Caras del producto visibles de frente")
    bbox: BBox = Field(default_factory=BBox)
    frenteado: bool = True


class Hueco(BaseModel):
    """Espacio vacío detectado en el lineal."""

    nivel: int = Field(ge=1)
    bbox: BBox = Field(default_factory=BBox)
    ancho_frentes_aprox: int = 1
    # Si el modelo puede inferir de quién era el espacio por las etiquetas.
    sku_codigo_sugerido: Optional[str] = None


class Etiqueta(BaseModel):
    """Etiqueta de precio leída del riel de la góndola."""

    texto_producto: Optional[str] = None
    precio_leido: Optional[float] = None
    moneda: str = "BOB"
    legible: bool = True
    nivel: int = Field(default=1, ge=1)
    bbox: BBox = Field(default_factory=BBox)
    # SKU del producto que está justo encima de esta etiqueta.
    sku_asociado: Optional[str] = None
    confianza: float = Field(default=0.0, ge=0.0, le=1.0)
    es_promocion: bool = False


class Observacion(BaseModel):
    """Todo lo que el modelo reporta de una foto. Sin veredictos."""

    model_config = ConfigDict(extra="ignore")

    niveles_visibles: int = Field(default=1, ge=1)
    nivel_ojos: Optional[int] = Field(
        default=None, description="Nivel que queda a la altura de los ojos de un adulto"
    )
    mueble_completo_visible: bool = True
    calidad_foto: CalidadFoto = "buena"
    motivo_calidad: Optional[str] = None
    # Un entero por bandeja, de abajo hacia arriba. Se le pide al modelo
    # desglosado en vez de como un total: al obligarlo a recorrer bandeja
    # por bandeja cuenta de verdad, y si le pides directo el total tiende a
    # contestar 0 o un número redondo sin haber mirado.
    frentes_por_nivel: list[int] = Field(default_factory=list)
    frentes_totales_lineal: int = Field(
        default=0, ge=0, description="Frentes de TODAS las marcas en la sección fotografiada"
    )
    detecciones: list[Deteccion] = Field(default_factory=list)
    huecos: list[Hueco] = Field(default_factory=list)
    etiquetas: list[Etiqueta] = Field(default_factory=list)
    confianza_global: float = Field(default=0.0, ge=0.0, le=1.0)


# =====================================================================
# Capa 2 — Evaluación (calculada en Python, no por el modelo)
# =====================================================================


class ResultadoRegla(BaseModel):
    regla: NombreRegla
    cumple: bool
    # 0.0-1.0. Permite crédito parcial: 3 de 4 SKUs presentes = 0.75.
    cumplimiento: float = Field(ge=0.0, le=1.0)
    esperado: str
    obtenido: str
    detalle: str = ""


class Hallazgo(BaseModel):
    """Un problema concreto que alguien tiene que ir a arreglar a la sala."""

    severidad: Severidad
    regla: NombreRegla
    sku_codigo: Optional[str] = None
    mensaje: str
    accion: str


class Evaluacion(BaseModel):
    score: int = Field(ge=0, le=100)
    semaforo: Semaforo
    reglas: dict[str, ResultadoRegla] = Field(default_factory=dict)
    hallazgos: list[Hallazgo] = Field(default_factory=list)
    share_of_shelf_pct: Optional[float] = None
    quiebres_detectados: int = 0
    skus_presentes: list[str] = Field(default_factory=list)
    skus_ausentes: list[str] = Field(default_factory=list)


# =====================================================================
# Metadatos de la llamada al modelo
# =====================================================================


class UsoModelo(BaseModel):
    modelo: str
    escalado: bool = False
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    duracion_ms: int = 0
    # Cuántas veces se leyó la foto. 1 = lectura confiable de una pasada;
    # 2 = hubo que verificar; 3 = las dos lecturas se contradijeron.
    lecturas: int = 1
    # Qué pasó al fusionar dos lecturas: cuánto coincidieron, qué precios
    # se descartaron. Es lo que permite auditar un score dudoso después.
    nota_consenso: Optional[str] = None


class Analisis(BaseModel):
    """Resultado completo, listo para persistir."""

    photo_id: str
    reponedor_id: str
    sala_id: str
    ciudad: str
    observacion: Observacion
    evaluacion: Evaluacion
    uso: UsoModelo
    creado_en: datetime = Field(default_factory=datetime.utcnow)


# =====================================================================
# API
# =====================================================================


class SubirFotoRequest(BaseModel):
    reponedor_id: str
    sala_id: str
    categoria: str
    storage_path: str
    tomada_at: Optional[datetime] = None
    gps_lat: Optional[float] = None
    gps_lng: Optional[float] = None
    imagen_sha256: Optional[str] = None


class SubirFotoResponse(BaseModel):
    photo_id: str
    estado: str
    alerta_captura: Optional[str] = None
