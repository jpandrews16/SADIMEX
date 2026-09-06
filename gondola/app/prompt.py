"""Construcción del prompt de visión.

Regla de diseño: al modelo se le pide **observar**, nunca juzgar. No se le
menciona el score, ni los pesos, ni si algo "está bien". Si supiera que lo
están calificando tendería a acomodar la respuesta; además el veredicto
debe salir de `rules.py`, que es auditable.
"""

from __future__ import annotations

import json
from typing import Sequence

from .schemas import Sku

SYSTEM = """Eres un auditor de ejecución en punto de venta (retail execution) especializado en supermercados de Bolivia.

Tu única función es DESCRIBIR con precisión lo que aparece en una foto de góndola. No evalúas, no calificas y no opinas sobre si la ejecución es buena o mala. Otro sistema se encarga de eso.

Reglas que no puedes romper:
1. Solo reportas SKU que estén en el CATÁLOGO que se te entrega. Si ves un producto de otra marca, NO lo reportes como detección: solo cuéntalo dentro de `frentes_totales_lineal`.
2. Si no estás seguro de cuál variante exacta es, reporta el SKU más probable con una confianza BAJA (por ejemplo 0.45). Nunca inventes un código que no esté en el catálogo.
3. Los niveles se cuentan desde ABAJO: nivel 1 = la bandeja más cercana al piso.
4. "Frentes" (facings) es cuántas unidades del producto se ven de frente en una fila horizontal. No cuentes las de atrás en profundidad.
5. Las coordenadas `bbox` van normalizadas de 0 a 1000 sobre la imagen: [x0, y0, x1, y1], con origen arriba a la izquierda.
6. Para cada etiqueta de precio del riel, asocia `sku_asociado` al producto que está JUSTO ENCIMA de ella. Si no hay producto encima o no lo reconoces, deja `sku_asociado` en null.
7. Lee los precios tal como aparecen impresos. Si el número está borroso o cortado, marca `legible: false` y deja `precio_leido` en null. Nunca adivines un precio.
8. Responde SIEMPRE en el formato JSON pedido, sin texto adicional ni markdown."""


def _catalogo_texto(skus: Sequence[Sku]) -> str:
    lineas = []
    for s in sorted(skus, key=lambda x: (x.marca, x.codigo)):
        partes = [f'- {s.codigo} | {s.nombre} | marca: {s.marca}']
        if s.gramaje:
            partes.append(f"gramaje: {s.gramaje}")
        if s.descripcion_visual:
            partes.append(f"se ve así: {s.descripcion_visual}")
        lineas.append(" | ".join(partes))
    return "\n".join(lineas)


def construir_mensajes(
    skus: Sequence[Sku],
    foto_data_url: str,
    hoja_referencia: str | None = None,
    categoria: str = "",
    cadena: str = "",
) -> list[dict]:
    """Arma el payload de mensajes para OpenRouter.

    Orden deliberado: primero el catálogo en texto, después la hoja de
    packshots, y al final la foto de góndola. El modelo llega a la foto
    ya sabiendo qué está buscando.
    """
    contexto = []
    if cadena:
        contexto.append(f"Cadena: {cadena}")
    if categoria:
        contexto.append(f"Categoría auditada: {categoria}")
    contexto_txt = ("\n" + " | ".join(contexto)) if contexto else ""

    contenido: list[dict] = [
        {
            "type": "text",
            "text": (
                f"=== CATÁLOGO SADIMEX (únicos SKU reportables) ==={contexto_txt}\n"
                f"{_catalogo_texto(skus)}\n"
            ),
        }
    ]

    if hoja_referencia:
        contenido.append(
            {
                "type": "text",
                "text": (
                    "\n=== HOJA DE REFERENCIA VISUAL ===\n"
                    "La siguiente imagen es un mosaico con el envase real de cada SKU, "
                    "rotulado abajo con su código. Úsala para distinguir variantes "
                    "de la misma línea (sabores, gramajes) antes de decidir un código."
                ),
            }
        )
        contenido.append({"type": "image_url", "image_url": {"url": hoja_referencia}})

    contenido.append(
        {
            "type": "text",
            "text": (
                "\n=== FOTO DE GÓNDOLA A ANALIZAR ===\n"
                "Reporta todo lo que observes siguiendo el esquema JSON:\n"
                "- niveles_visibles: cuántas bandejas se ven, contando desde el piso.\n"
                "- nivel_ojos: qué bandeja queda a la altura de los ojos de un adulto "
                "de pie frente al mueble (típicamente la penúltima de arriba hacia abajo).\n"
                "- mueble_completo_visible: false si la foto corta el mueble por arriba o por abajo.\n"
                "- frentes_totales_lineal: frentes de TODAS las marcas en la sección visible, "
                "incluida la competencia. Es el denominador del share of shelf.\n"
                "- detecciones: un item por cada SKU del catálogo que veas.\n"
                "- huecos: espacios vacíos en las bandejas.\n"
                "- etiquetas: cada etiqueta de precio del riel.\n"
                "- confianza_global: qué tan confiable es tu lectura completa de esta foto (0 a 1). "
                "Baja este número si hay reflejos, desenfoque, poca luz o ángulo malo."
            ),
        }
    )
    contenido.append({"type": "image_url", "image_url": {"url": foto_data_url}})

    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": contenido},
    ]


# Esquema estricto. Forzarlo por `response_format` evita el parseo frágil
# de JSON dentro de bloques markdown.
BBOX_SCHEMA = {
    "type": "object",
    "properties": {
        "x0": {"type": "integer"},
        "y0": {"type": "integer"},
        "x1": {"type": "integer"},
        "y1": {"type": "integer"},
    },
    "required": ["x0", "y0", "x1", "y1"],
    "additionalProperties": False,
}

OBSERVACION_SCHEMA = {
    "type": "object",
    "properties": {
        "niveles_visibles": {"type": "integer", "description": "Bandejas visibles, contando desde el piso"},
        "nivel_ojos": {"type": ["integer", "null"]},
        "mueble_completo_visible": {"type": "boolean"},
        "calidad_foto": {"type": "string", "enum": ["buena", "regular", "mala"]},
        "motivo_calidad": {"type": ["string", "null"]},
        "frentes_totales_lineal": {"type": "integer"},
        "detecciones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sku_codigo": {"type": "string"},
                    "confianza": {"type": "number"},
                    "nivel": {"type": "integer"},
                    "frentes": {"type": "integer"},
                    "bbox": BBOX_SCHEMA,
                    "frenteado": {"type": "boolean"},
                },
                "required": ["sku_codigo", "confianza", "nivel", "frentes", "bbox", "frenteado"],
                "additionalProperties": False,
            },
        },
        "huecos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nivel": {"type": "integer"},
                    "bbox": BBOX_SCHEMA,
                    "ancho_frentes_aprox": {"type": "integer"},
                    "sku_codigo_sugerido": {"type": ["string", "null"]},
                },
                "required": ["nivel", "bbox", "ancho_frentes_aprox", "sku_codigo_sugerido"],
                "additionalProperties": False,
            },
        },
        "etiquetas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "texto_producto": {"type": ["string", "null"]},
                    "precio_leido": {"type": ["number", "null"]},
                    "moneda": {"type": "string"},
                    "legible": {"type": "boolean"},
                    "nivel": {"type": "integer"},
                    "bbox": BBOX_SCHEMA,
                    "sku_asociado": {"type": ["string", "null"]},
                    "confianza": {"type": "number"},
                    "es_promocion": {"type": "boolean"},
                },
                "required": [
                    "texto_producto", "precio_leido", "moneda", "legible",
                    "nivel", "bbox", "sku_asociado", "confianza", "es_promocion",
                ],
                "additionalProperties": False,
            },
        },
        "confianza_global": {"type": "number"},
    },
    "required": [
        "niveles_visibles", "nivel_ojos", "mueble_completo_visible", "calidad_foto",
        "motivo_calidad", "frentes_totales_lineal", "detecciones", "huecos",
        "etiquetas", "confianza_global",
    ],
    "additionalProperties": False,
}

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "observacion_gondola",
        "strict": True,
        "schema": OBSERVACION_SCHEMA,
    },
}


def esquema_json_texto() -> str:
    """El esquema en texto, para modelos que no soportan structured output."""
    return json.dumps(OBSERVACION_SCHEMA, ensure_ascii=False, indent=2)
