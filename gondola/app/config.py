"""Configuración del lector de góndola.

Todo se controla por variables de entorno para poder cambiar de modelo,
umbrales o pesos en Railway sin volver a desplegar código.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Supabase (la misma base que el módulo de audio) ──────────────
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_bucket: str = "gondola-fotos"

    # ── OpenRouter ───────────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Modelo primario: barato, se usa en el 100% de las fotos.
    # Qwen3-VL 32B es el más barato con visión de detalle decente en
    # OpenRouter. Valídalo contra tus propias fotos con
    # `tools/comparar_modelos.py` antes de dejarlo fijo.
    modelo_primario: str = "qwen/qwen3-vl-32b-instruct"
    # Modelo de escalado: solo cuando el primario reporta baja confianza.
    modelo_escalado: str = "qwen/qwen3-vl-235b-a22b-instruct"
    # Por debajo de esta confianza global se reintenta con el modelo de escalado.
    # Con volumen alto este número es la perilla del gasto: subirlo escala
    # más fotos y cuesta más; bajarlo abarata y deja pasar más error.
    umbral_escalado: float = 0.75
    # Detecciones por debajo de esta confianza no cuentan como producto presente.
    umbral_deteccion: float = 0.60
    # Tope de fotos que pueden escalar al modelo grande, como fracción del
    # total del día. Protege la factura cuando entra un lote de fotos malas.
    # 0 desactiva el escalado; 1.0 lo deja sin tope.
    escalado_max_fraccion_diaria: float = 0.20

    # Identificación de la app ante OpenRouter (aparece en su dashboard).
    app_url: str = "https://sadimex.com"
    app_title: str = "SADIMEX Lector de Gondola"

    # ── Umbrales de semáforo (mismos que el módulo de audio) ─────────
    umbral_verde: int = 80
    umbral_amarillo: int = 60

    # ── Worker ───────────────────────────────────────────────────────
    worker_intervalo_segundos: float = 5.0
    worker_max_intentos: int = 3
    # Fotos procesadas a la vez. Subir con cuidado: pega en el rate limit.
    worker_concurrencia: int = 2

    # ── Imagen ───────────────────────────────────────────────────────
    # La góndola se manda en alta resolución; más de esto no aporta y sí cuesta.
    imagen_max_lado: int = 1600
    imagen_calidad_jpeg: int = 88
    # La hoja de referencia de packshots va más chica: solo debe dejar
    # reconocer el envase, no leer la letra pequeña.
    packshot_lado: int = 220
    packshot_columnas: int = 5
    # Tope de packshots en la hoja de referencia. Con catálogos grandes el
    # mosaico se vuelve el costo dominante de cada foto: son tokens de
    # imagen que se pagan en TODAS las llamadas. Se priorizan los SKU
    # marcados como prioritarios y se corta el resto.
    packshot_max_en_hoja: int = 24

    # ── Operación ────────────────────────────────────────────────────
    log_level: str = "INFO"
    # Metros de margen sobre el radio de la sala antes de marcar la foto.
    gps_margen_metros: int = 100
    http_timeout_segundos: float = 120.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
