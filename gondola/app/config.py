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
    modelo_primario: str = "google/gemini-2.5-flash-lite"
    # Modelo de escalado: solo cuando el primario reporta baja confianza.
    modelo_escalado: str = "google/gemini-2.5-flash"
    # Por debajo de esta confianza global se reintenta con el modelo de escalado.
    umbral_escalado: float = 0.75
    # Detecciones por debajo de esta confianza no cuentan como producto presente.
    umbral_deteccion: float = 0.60

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

    # ── Operación ────────────────────────────────────────────────────
    log_level: str = "INFO"
    # Metros de margen sobre el radio de la sala antes de marcar la foto.
    gps_margen_metros: int = 100
    http_timeout_segundos: float = 120.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
