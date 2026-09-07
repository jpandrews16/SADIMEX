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
4. AGRUPA. Un item de `detecciones` representa un GRUPO de unidades del mismo SKU juntas en la misma bandeja, no una unidad suelta. Si ves 5 paquetes iguales en fila, eso es UNA detección con `frentes: 5`, nunca cinco detecciones de un frente. Solo abres una segunda detección del mismo SKU si está en otra bandeja o separado por otro producto.
5. "Frentes" (facings) es cuántas unidades se ven de frente en esa fila horizontal. No cuentes las de atrás en profundidad.
6. `x0` y `x1` son el borde izquierdo y derecho del grupo, normalizados de 0 a 1000 sobre el ancho de la imagen.
7. Para cada etiqueta de precio del riel, asocia `sku_asociado` al producto que está JUSTO ENCIMA de ella. Si no hay producto encima o no lo reconoces, deja `sku_asociado` en null.
8. Lee los precios tal como aparecen impresos. Si el número está borroso o cortado, marca `legible: false` y deja `precio_leido` en null. Nunca adivines un precio.
9. Responde SIEMPRE en el formato JSON pedido, sin texto adicional ni markdown."""


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
                "- detecciones: un item por cada GRUPO de unidades del mismo SKU en una bandeja.\n"
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


# Segunda pasada de verificación. El enfoque tiene que ser DISTINTO al de
# la primera: si solo se repitiera la misma pregunta, la respuesta sería un
# eco y el acuerdo entre ambas no probaría nada.
#
# Acá se fuerza un recorrido sistemático bandeja por bandeja, que es la
# forma en que un auditor humano cuenta de verdad y la que menos se salta
# unidades en una fila larga.
SYSTEM_VERIFICACION = SYSTEM + """

MÉTODO OBLIGATORIO PARA ESTA LECTURA:
Recorre la góndola BANDEJA POR BANDEJA, empezando por la más baja (nivel 1) y subiendo.
Para cada bandeja, avanza de IZQUIERDA A DERECHA y ve nombrando lo que encuentras antes de contar.
Cuenta las unidades de frente de UNA EN UNA; no estimes "varias" ni redondees a un número redondo.
Reporta cada fila de unidades iguales como UNA detección con su total en `frentes`, no como una detección por unidad.
Si en una fila hay muchas unidades iguales, cuéntalas dos veces antes de responder.
Trata cada bandeja como un problema separado: no asumas que se repite lo de la bandeja anterior."""


def construir_mensajes_verificacion(
    skus: Sequence[Sku],
    foto_data_url: str,
    hoja_referencia: str | None = None,
    categoria: str = "",
    cadena: str = "",
) -> list[dict]:
    """Mensajes de la segunda lectura, con el método de conteo explícito."""
    mensajes = construir_mensajes(skus, foto_data_url, hoja_referencia, categoria, cadena)
    mensajes[0] = {"role": "system", "content": SYSTEM_VERIFICACION}
    return mensajes


# Esquema estricto. Forzarlo por `response_format` evita el parseo frágil
# de JSON dentro de bloques markdown.
#
# Dos decisiones acá salieron de medir, no de suponer:
#
# 1. **Solo se pide lo que alguna regla usa.** Cada campo se paga dos
#    veces: en dinero y —sobre todo— en latencia, porque el modelo genera
#    la salida token por token, a ~16 ms cada uno. Quitar los campos
#    muertos (y0/y1 de la detección, la caja de etiquetas y huecos, el SKU
#    sugerido) bajó la salida de 3.659 a ~1.200 tokens.
#
# 2. **Nada de objetos anidados.** La caja del producto va como dos
#    enteros planos, x0 y x1, y no como un objeto `bbox`. Medido sobre la
#    misma foto: con el objeto anidado el modelo se atasca en un bucle de
#    tabuladores y devuelve JSON roto 2 de cada 3 veces; con los campos
#    planos, 1 de cada 3. El decodificador restringido del proveedor
#    tropieza con la estructura anidada.
#
# Si mañana una regla nueva necesita otro campo, se agrega aquí —pero
# midiendo antes y después, porque el costo no es solo de tokens.

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
                    "x0": {"type": "integer", "description": "Borde izquierdo del grupo, 0-1000"},
                    "x1": {"type": "integer", "description": "Borde derecho del grupo, 0-1000"},
                    "frenteado": {"type": "boolean"},
                },
                "required": ["sku_codigo", "confianza", "nivel", "frentes", "x0", "x1", "frenteado"],
                "additionalProperties": False,
            },
        },
        "huecos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nivel": {"type": "integer"},
                    "ancho_frentes_aprox": {"type": "integer"},
                },
                "required": ["nivel", "ancho_frentes_aprox"],
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
                    "sku_asociado": {"type": ["string", "null"]},
                    "confianza": {"type": "number"},
                    "es_promocion": {"type": "boolean"},
                },
                "required": [
                    "texto_producto", "precio_leido", "moneda", "legible",
                    "nivel", "sku_asociado", "confianza", "es_promocion",
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
