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

Tienes DOS TAREAS SEPARADAS. La segunda no anula la primera.

═══ TAREA A — CENSO DEL MUEBLE (el catálogo NO interviene) ═══
Cuenta cuántos envases se ven de frente en cada bandeja, EMPEZANDO POR LA DE ABAJO, y escribe un entero por bandeja en `frentes_por_nivel`.

Cuentas TODO lo que haya en la bandeja: marcas del catálogo, marcas de la competencia, marcas que no reconoces, marcas que no sabes leer. Acá no distingues marcas. Si la bandeja tiene doce botellas de gaseosa de cualquier marca, el número es 12.

Esta tarea se hace SIEMPRE y PRIMERO, incluso si en toda la foto no hay un solo producto del catálogo. Que no reconozcas ninguna marca NO es motivo para poner 0: 0 significa que esa bandeja está VACÍA, sin nada encima. Es el error más grave que puedes cometer acá.

Recorre cada bandeja de izquierda a derecha antes de escribir su número. No estimes, no redondees a números redondos como 10, 20 o 100.

═══ TAREA B — IDENTIFICAR NUESTROS PRODUCTOS (acá sí manda el catálogo) ═══
Recién ahora buscas los SKU del CATÁLOGO. Reglas que no puedes romper:
1. Solo reportas en `detecciones` SKU que estén en el CATÁLOGO. Un producto de otra marca NO va en `detecciones`: ya quedó contado en la TAREA A.
2. Si no estás seguro de cuál variante exacta es, reporta el SKU más probable con una confianza BAJA (por ejemplo 0.45). Nunca inventes un código que no esté en el catálogo.
3. Los niveles se cuentan desde ABAJO: nivel 1 = la bandeja más cercana al piso.
4. AGRUPA. Un item de `detecciones` representa un GRUPO de unidades del mismo SKU juntas en la misma bandeja, no una unidad suelta. Si ves 5 paquetes iguales en fila, eso es UNA detección con `frentes: 5`, nunca cinco detecciones de un frente. Solo abres una segunda detección del mismo SKU si está en otra bandeja o separado por otro producto.
5. "Frentes" (facings) es cuántas unidades se ven de frente en esa fila horizontal. No cuentes las de atrás en profundidad.
6. `x0` y `x1` son el borde izquierdo y derecho del grupo, normalizados de 0 a 1000 sobre el ancho de la imagen.
7. Reporta en `etiquetas` SOLO las que correspondan a un SKU del CATÁLOGO, y pon su código en `sku_asociado`. Son dos casos: la etiqueta está justo debajo de un producto del catálogo, o el texto impreso en la etiqueta nombra un producto del catálogo aunque encima haya un hueco (eso delata un quiebre). Las etiquetas de la competencia NO se reportan: un riel tiene decenas y ninguna sirve acá. Nunca devuelvas una etiqueta con `sku_asociado` en null.
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
                "- frentes_por_nivel: la TAREA A. Un número por bandeja, de abajo hacia "
                "arriba, con todos los envases que se ven de frente en ella, sea de "
                "quien sea la marca. Un 0 significa bandeja vacía, nunca 'no reconocí "
                "las marcas'.\n"
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
# 3. **El conteo del lineal va desglosado por bandeja, y el total lo suma
#    Python.** Preguntarle el total directo no funciona: medido contra
#    SKU-110K, devolvía 0 en 8 de 12 fotos con más de cien productos, o
#    repetía un número redondo. Pedir un entero por bandeja lo obliga a
#    recorrer el mueble para poder contestar, cuesta media docena de
#    tokens más, y deja la suma donde es auditable.
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
        "frentes_por_nivel": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Un entero por bandeja, de abajo hacia arriba",
        },
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
        "motivo_calidad", "frentes_por_nivel", "detecciones", "huecos",
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
