"""Conteo del lineal dividiendo la foto en trozos y sumando en código.

Por qué existe
--------------
Medido contra SKU-110K, pedirle a un modelo de visión el total de envases
de una góndola entera da un error cercano al 50%, y en fotos densas
devuelve 0. No es cómo está escrito el prompt: la literatura de conteo con
VLM mide que la precisión cae en picada pasando los ~30 objetos, y las
fotos de góndola tienen entre 40 y 250.

La salida es dividir y vencer: cortar la imagen, contar cada trozo por
separado —cada uno bajo el umbral donde el modelo sí cuenta— y sumar en
Python. Tres cosas que se midieron acá y que definen el diseño:

1. **Los rieles no se los podemos preguntar al modelo.** Se le pidió la
   altura de cada bandeja y devolvió progresiones aritméticas perfectas
   (135, 265, 395, 525…, siempre 130 de separación) en fotos distintas:
   las inventa parejas en vez de mirarlas. Acá se detectan con visión
   clásica —un riel es una línea horizontal larga y de alto contraste—,
   que es determinista, gratis y auditable.

2. **El corte tiene que ir sobre el riel.** Un corte horizontal a la
   altura del riel no parte ningún producto, porque los productos se
   apoyan ahí y crecen hacia arriba. Un corte a media bandeja partiría
   cada envase en dos y se contaría doble.

3. **El modelo se satura alrededor de 14 por trozo.** Con bandejas de 14
   o menos el conteo dio -6%; en bandejas con 26 y 29 productos reales
   devolvió 14 en las dos. Por eso una banda que llega al techo se parte
   en dos por su columna más vacía —la que menos probablemente cruce un
   envase— y se cuentan las mitades.

Costo
-----
Los trozos suman aproximadamente la superficie de la foto, así que los
tokens de imagen se reparten en vez de duplicarse. Cada trozo devuelve un
número —unos pocos tokens de salida— y todos se piden en paralelo, así que
la latencia es la de una sola llamada.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from PIL import Image, ImageFilter, ImageOps

from .config import get_settings

log = logging.getLogger(__name__)

# Prompt corto a propósito. Está medido que agregar descriptores visuales a
# una tarea de conteo BAJA la precisión —el modelo se distrae describiendo
# en vez de contar—, así que acá se pide una sola cosa.
PROMPT_TROZO = (
    "Esta imagen es una bandeja de una góndola de supermercado.\n"
    "Cuenta cuántos envases se ven de frente, de izquierda a derecha.\n"
    "Cuenta todas las marcas por igual. No cuentes los de atrás en profundidad.\n"
    "Responde SOLO con el número, sin ninguna palabra más."
)

# A partir de acá se asume que el modelo tocó su techo y está subcontando,
# así que el trozo se parte en dos. Medido: bandejas con 26 y 29 productos
# reales devolvieron 14 las dos.
TECHO_POR_TROZO = 14

# Nadie pone más de 200 frentes en una bandeja: por encima de eso el
# modelo devolvió otra cosa (un precio, un año, una medida).
MAX_PLAUSIBLE = 200

# Alto mínimo de una banda en píxeles. Más fina que esto no tiene producto.
ALTO_MINIMO = 28


# =====================================================================
# Detección de rieles — visión clásica, sin modelo
# =====================================================================


def _perfil_filas(img: Image.Image) -> list[float]:
    """Energía de borde horizontal de cada fila de píxeles.

    El truco de reducir a un píxel de ancho promedia cada fila sin
    necesidad de numpy: la imagen ya trae la operación.
    """
    gris = ImageOps.grayscale(img)
    # Sobel horizontal: resalta los bordes que cruzan la imagen a lo ancho,
    # que es lo que es un riel.
    bordes = gris.filter(ImageFilter.Kernel((3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1))
    columna = bordes.resize((1, img.height), Image.BOX)
    return list(columna.getdata())


def _perfil_columnas(img: Image.Image) -> list[float]:
    """Energía de borde vertical de cada columna. Sirve para elegir por
    dónde partir una banda sin cruzar un envase: la columna más floja es
    la que más probablemente sea el hueco entre dos productos."""
    gris = ImageOps.grayscale(img)
    bordes = gris.filter(ImageFilter.Kernel((3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1))
    fila = bordes.resize((img.width, 1), Image.BOX)
    return list(fila.getdata())


def detectar_rieles(img: Image.Image, max_rieles: int) -> list[int]:
    """Devuelve la altura de cada riel en píxeles, de arriba hacia abajo.

    Un riel es un máximo local de energía de borde horizontal. Se exige
    separación mínima entre rieles para no devolver tres líneas de la misma
    bandeja, y se pide que el pico destaque sobre el promedio para no
    inventar rieles en una pared lisa.
    """
    perfil = _perfil_filas(img)
    if not perfil:
        return []

    promedio = sum(perfil) / len(perfil)
    umbral = promedio * 1.6
    separacion = max(ALTO_MINIMO, img.height // (max_rieles + 1))

    # El borde de la imagen es el mayor salto de contraste que hay y no es
    # un riel: si se dejara, cada foto empezaría con dos bandas vacías.
    margen = max(2, round(img.height * 0.03))
    candidatos = sorted(
        (
            i for i, v in enumerate(perfil)
            if v >= umbral and margen <= i <= img.height - margen
        ),
        key=lambda i: perfil[i],
        reverse=True,
    )

    elegidos: list[int] = []
    for i in candidatos:
        if all(abs(i - y) >= separacion for y in elegidos):
            elegidos.append(i)
        if len(elegidos) >= max_rieles:
            break

    return sorted(elegidos)


def bandas_desde_rieles(rieles: list[int], alto: int) -> list[tuple[int, int]]:
    """Convierte los rieles en recortes (y0, y1). Cada banda va del riel de
    arriba al riel donde se apoyan sus productos."""
    bandas: list[tuple[int, int]] = []
    techo = 0
    for y in rieles:
        if y - techo >= ALTO_MINIMO:
            bandas.append((techo, min(alto, y + 4)))
        techo = y
    # Lo que queda por debajo del último riel también es bandeja.
    if alto - techo >= ALTO_MINIMO:
        bandas.append((techo, alto))
    return bandas


def corte_mas_vacio(img: Image.Image) -> int:
    """Columna por donde partir la banda con menos riesgo de cruzar un envase.

    Se busca en el tercio central: partir muy al borde deja un trozo que no
    aporta y otro igual de cargado que el original.
    """
    perfil = _perfil_columnas(img)
    if not perfil:
        return img.width // 2
    desde, hasta = img.width // 3, (2 * img.width) // 3
    ventana = perfil[desde:hasta] or perfil
    return desde + min(range(len(ventana)), key=lambda i: ventana[i])


# =====================================================================
# Conteo
# =====================================================================


def _a_data_url(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=get_settings().imagen_calidad_jpeg, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _numero(texto: str) -> Optional[int]:
    """Saca el número de la respuesta, aunque venga con palabras alrededor."""
    encontrados = re.findall(r"\d+", texto or "")
    if not encontrados:
        return None
    valor = int(encontrados[0])
    return valor if 0 <= valor <= MAX_PLAUSIBLE else None


def _contar_trozo(client: httpx.Client, img: Image.Image) -> Optional[int]:
    cfg = get_settings()
    payload = {
        "model": cfg.modelo_primario,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_TROZO},
                {"type": "image_url", "image_url": {"url": _a_data_url(img)}},
            ],
        }],
        "temperature": 0.0,
        # La respuesta es un número. Un tope corto evita que un modelo que
        # se pone a explicar se lleve la latencia de toda la foto.
        "max_tokens": 24,
        "usage": {"include": True},
    }
    try:
        resp = client.post(
            f"{cfg.openrouter_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": cfg.app_url,
                "X-Title": cfg.app_title,
            },
            json=payload,
            timeout=cfg.http_timeout_segundos,
        )
        if resp.status_code >= 400:
            log.warning("Conteo de trozo: OpenRouter %s", resp.status_code)
            return None
        return _numero(resp.json()["choices"][0]["message"].get("content") or "")
    except Exception as exc:  # un trozo perdido no puede tumbar la foto
        log.warning("Conteo de trozo falló: %s", exc)
        return None


def _contar_banda(client: httpx.Client, img: Image.Image) -> Optional[int]:
    """Cuenta una banda, partiéndola si el modelo llega a su techo.

    Que devuelva el techo no prueba que esté subcontando, pero el costo de
    los dos casos es muy distinto: partir de más cuesta una llamada corta,
    y no partir cuando hacía falta mete un -50% en el denominador del share
    of shelf. Por eso se parte ante la duda.
    """
    total = _contar_trozo(client, img)
    if total is None or total < TECHO_POR_TROZO or img.width < 2 * ALTO_MINIMO:
        return total

    x = corte_mas_vacio(img)
    izq = _contar_trozo(client, img.crop((0, 0, x, img.height)))
    der = _contar_trozo(client, img.crop((x, 0, img.width, img.height)))
    if izq is None or der is None:
        return total
    if izq + der <= total:
        return total  # partir no aportó; nos quedamos con la lectura entera

    log.info("Banda saturada: %d de una pasada, %d+%d partida", total, izq, der)
    return izq + der


def _bytes_de(foto: bytes | str) -> bytes:
    """Acepta la foto como bytes o como el data URL que ya viaja al modelo."""
    if isinstance(foto, bytes):
        return foto
    _, _, b64 = foto.partition(",")
    return base64.b64decode(b64)


def contar_por_bandas(
    foto: bytes | str,
    client: Optional[httpx.Client] = None,
) -> tuple[Optional[int], list[Optional[int]]]:
    """Cuenta el lineal bandeja por bandeja y devuelve (total, por_banda).

    El total es None cuando no se pudo contar alguna banda, que es la señal
    de "no medido": `rules.py` saca el share of shelf del promedio en vez
    de inventar un denominador.

    Las bandas que fallan sueltas NO se rellenan con una estimación. Un
    total incompleto es un denominador chico, y un denominador chico infla
    el share of shelf, que es justo el error que hace quedar bien a una
    sala que está mal.
    """
    cfg = get_settings()
    img = Image.open(io.BytesIO(_bytes_de(foto)))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > cfg.imagen_max_lado:
        img.thumbnail((cfg.imagen_max_lado, cfg.imagen_max_lado * 10), Image.LANCZOS)

    rieles = detectar_rieles(img, cfg.conteo_bandas_max)
    bandas = bandas_desde_rieles(rieles, img.height)
    if not bandas:
        return None, []

    recortes = [img.crop((0, y0, img.width, y1)) for y0, y1 in bandas]
    propio = client is None
    cliente = client or httpx.Client()
    try:
        # En paralelo: el trabajo es esperar a OpenRouter, así que las N
        # bandas cuestan el tiempo de una sola llamada.
        with ThreadPoolExecutor(max_workers=len(recortes)) as pool:
            por_banda = list(pool.map(lambda r: _contar_banda(cliente, r), recortes))
    finally:
        if propio:
            cliente.close()

    if any(n is None for n in por_banda):
        log.warning("Conteo por bandas incompleto (%s); el total se descarta", por_banda)
        return None, por_banda

    return sum(n for n in por_banda if n is not None), por_banda
