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
    # Qué hacer cuando la primera lectura no es confiable:
    #   consenso — segunda lectura con el MISMO modelo barato y enfoque
    #              distinto, y se fusionan. Dos llamadas al chico cuestan
    #              menos que una al grande, y el acuerdo entre lecturas
    #              independientes es mejor señal que la autoevaluación del
    #              modelo. Es el default.
    #   escalado — reintenta con el modelo grande (más caro).
    #   ninguna  — se queda con la primera lectura.
    estrategia_baja_confianza: str = "consenso"

    # Por debajo de esta confianza global se aplica la estrategia anterior.
    # OJO: la autoevaluación del modelo es poco fiable —en pruebas reales
    # se declara 95% seguro incluso cuando inventa huecos—, así que este
    # umbral casi nunca se dispara solo. Lo que de verdad decide la
    # verificación son las señales de riesgo de abajo.
    umbral_escalado: float = 0.75

    # Verificar con una segunda lectura cuando la PRIMERA reporta algo que,
    # de ser falso, cuesta trabajo humano y credibilidad. Cada uno se puede
    # apagar por separado si en tu operación no aplica.
    verificar_si_hay_huecos: bool = True          # falso quiebre → visita en vano
    verificar_si_precio_fuera_rango: bool = True  # falsa acusación a la sala
    verificar_si_falta_prioritario: bool = True   # falsa reposición de urgencia

    # Tope de verificaciones por día, como fracción de las fotos. Protege
    # la factura si el modelo empieza a reportar huecos en todas partes.
    verificacion_max_fraccion_diaria: float = 0.50

    # La segunda lectura necesita algo de temperatura: con 0 devolvería la
    # misma respuesta y el acuerdo no probaría nada.
    temperatura_verificacion: float = 0.4

    # Si tras el consenso las dos lecturas siguen en desacuerdo por debajo
    # de este índice, se escala al modelo grande como último recurso
    # (sujeto a la cuota diaria). 0 desactiva ese tercer intento.
    umbral_acuerdo_para_escalar: float = 0.50
    # Detecciones por debajo de esta confianza no cuentan como producto presente.
    umbral_deteccion: float = 0.60
    # Tope de fotos que pueden escalar al modelo grande, como fracción del
    # total del día. Protege la factura cuando entra un lote de fotos malas.
    # 0 desactiva el escalado; 1.0 lo deja sin tope.
    escalado_max_fraccion_diaria: float = 0.20

    # Preferencia de proveedor en OpenRouter ("throughput" el más rápido,
    # "price" el más barato). Vacío por defecto: se midió contra Qwen3-VL
    # 32B y no aportó nada —sirvió el mismo proveedor y tardó más— así que
    # no vale la pena restringir el enrutado. Vuelve a medirlo si cambias
    # de modelo.
    preferencia_proveedor: str = ""

    # Tope duro de tokens de salida. Una foto normal usa ~1.200; esto corta
    # al modelo si se pone a divagar, que es cuando una foto tarda tres
    # minutos en vez de veinte segundos.
    max_tokens_salida: int = 4000

    # El proveedor corta la respuesta a media generación cada tanto, y la
    # devuelve con finish_reason "stop" como si estuviera completa: el JSON
    # llega partido. Medido en la práctica, pasa en torno a 1 de cada 3
    # llamadas. Es transitorio, así que se reintenta en vez de dar la foto
    # por perdida.
    reintentos_respuesta_invalida: int = 3

    # Identificación de la app ante OpenRouter (aparece en su dashboard).
    app_url: str = "https://sadimex.com"
    app_title: str = "SADIMEX Lector de Gondola"

    # ── Umbrales de semáforo (mismos que el módulo de audio) ─────────
    umbral_verde: int = 80
    umbral_amarillo: int = 60

    # ── Worker ───────────────────────────────────────────────────────
    worker_intervalo_segundos: float = 5.0
    worker_max_intentos: int = 3
    # Fotos procesadas a la vez por réplica. El trabajo es esperar a
    # OpenRouter, no calcular, así que subirlo escala casi lineal el
    # rendimiento sin más CPU: con 30 s por foto, 6 en paralelo son ~12
    # fotos por minuto por réplica. El techo real es el rate limit de tu
    # cuenta de OpenRouter, no el worker.
    worker_concurrencia: int = 6

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
