#!/usr/bin/env python3
"""Convierte el PDF de packshots de Canva en el catálogo del sistema.

El diseño de producto vive en Canva: una página por SKU. Este script hace
el puente en un solo paso:

  PDF de Canva ──▶ un PNG por página ──▶ la IA lee cada envase ──▶ CSV de catálogo
                        │
                        └──▶ (opcional) sube los packshots a Supabase Storage
                             y deja la URL pública en el CSV

Lo que la IA extrae de cada packshot es lo mismo que el lector de góndola
necesita después para reconocerlo en la foto de sala: marca, nombre,
gramaje y —lo más importante— la `descripcion_visual`, los rasgos que
distinguen una variante de otra ("pote negro con banda rosada" y no
"sabor fresa"; el modelo ve colores, no sabores).

El CSV que sale es un BORRADOR. Revísalo antes de cargarlo: los códigos
son sugeridos y la categoría es una inferencia. Corregir 348 filas en una
planilla toma minutos; escribirlas desde cero, días.

Corre en TU máquina, no en un servidor. El PDF puede pesar cientos de MB
y nunca se sube a ningún lado: se procesa localmente y solo viajan los
packshots ya reducidos, a tu propio Storage de Supabase.

Uso
---
    # 1. Descargar de Canva: Archivo → Descargar → PDF estándar → todas las páginas

    # 2. Preparar el entorno (una sola vez)
    git clone https://github.com/jpandrews16/SADIMEX.git && cd SADIMEX
    git checkout claude/gondola-product-reader-m3oslg
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r gondola/requirements-tools.txt

    # 3. Probar con 5 páginas antes de gastar en las 348
    export OPENROUTER_API_KEY=...
    export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
    python -m gondola.tools.importar_catalogo_canva \\
        --pdf ~/Descargas/PRODUCTOS_SDX.pdf --salida ./packshots --limite 5

    # 4. Si el resultado se ve bien, correr todo
    python -m gondola.tools.importar_catalogo_canva \\
        --pdf ~/Descargas/PRODUCTOS_SDX.pdf \\
        --salida ./packshots \\
        --categoria cafe \\
        --subir

    # 5. Revisar ./packshots/catalogo.csv y corregir códigos/categorías

    # 6. Cargarlo
    curl -X POST https://<tu-servicio>.railway.app/api/gondola/admin/catalogo/csv \\
         -H "Authorization: Bearer <jwt de un admin>" \\
         -F archivo=@./packshots/catalogo.csv

Es reanudable
-------------
Nada se paga dos veces. Los PNG ya extraídos y las descripciones ya
pagadas se guardan en la carpeta de salida y se reutilizan. Si se corta la
conexión, cierras la terminal o cancelas con Ctrl-C, vuelve a correr el
mismo comando y sigue donde quedó.

Para trabajar por tandas: `--desde 1 --hasta 100`, luego `--desde 101`.
El CSV final se arma siempre con todos los packshots de la carpeta, no
solo con el último lote.

Otras banderas útiles:
  --solo-extraer  corta el PDF en PNG y para, sin gastar en IA
  --imagenes      usa una carpeta de PNG en vez del PDF
  --rehacer       ignora el trabajo previo y empieza de cero
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gondola.app.config import get_settings  # noqa: E402
from gondola.app.vision import VisionError, _extraer_json  # noqa: E402

log = logging.getLogger("importar_catalogo")

EXTENSIONES = {".png", ".jpg", ".jpeg", ".webp"}
BUCKET_PACKSHOTS = "gondola-packshots"

# Los packshots se guardan más grandes que el mosaico: el mosaico se
# regenera desde estos, y sirven además para el catálogo en la app.
LADO_PACKSHOT = 800

SYSTEM = """Eres un catalogador de productos de consumo masivo en Bolivia.

Recibes la foto de UN producto sobre fondo liso (un packshot de catálogo) y describes lo que ves.

Reglas:
1. Lee el texto del envase tal como está impreso. No traduzcas ni corrijas la marca.
2. `descripcion_visual` es lo más importante: describe COLORES, FORMA y TEXTO GRANDE del envase, porque es lo que permitirá reconocerlo en una foto de góndola llena. Escribe "frasco de vidrio con tapa verde y etiqueta roja, letras blancas COLCAFÉ" y NO "café instantáneo descafeinado".
3. Si el producto pertenece a una línea con variantes (sabores, intensidades, tamaños), di explícitamente qué rasgo visual lo distingue de sus hermanos.
4. Si un dato no está visible, devuélvelo como null. No lo inventes.
5. Responde solo el JSON pedido, sin markdown."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "marca": {"type": ["string", "null"]},
        "nombre": {"type": ["string", "null"], "description": "Nombre comercial completo, con la variante"},
        "variante": {"type": ["string", "null"], "description": "Sabor, tipo o intensidad, si aplica"},
        "gramaje": {"type": ["string", "null"], "description": "Contenido neto tal como está impreso, ej '200 g'"},
        "categoria_sugerida": {"type": ["string", "null"]},
        "descripcion_visual": {"type": ["string", "null"]},
        "legible": {"type": "boolean"},
    },
    "required": ["marca", "nombre", "variante", "gramaje", "categoria_sugerida",
                 "descripcion_visual", "legible"],
    "additionalProperties": False,
}

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "packshot", "strict": True, "schema": ESQUEMA},
}

COLUMNAS = [
    "codigo", "nombre", "marca", "categoria", "gramaje", "es_prioritario",
    "packshot_url", "descripcion_visual", "archivo", "pagina", "revisar",
]


# =====================================================================
# Extracción de imágenes
# =====================================================================


def _caja_de_contenido(img: Image.Image, tolerancia: int = 12) -> Optional[tuple]:
    """Región que se diferencia del color de la esquina superior izquierda.

    None significa que toda la página es de un solo color: no hay producto.
    """
    rgb = img.convert("RGB")
    fondo = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    diferencia = ImageChops.difference(rgb, fondo)
    return ImageChops.add(diferencia, diferencia, 2.0, -tolerancia).getbbox()


def parece_vacia(img: Image.Image, tolerancia: int = 12) -> bool:
    """True si la página no tiene nada dibujado.

    Un diseño de Canva casi siempre trae páginas en blanco: separadores,
    la última del archivo, huecos de maquetación. Sin este chequeo cada
    una se convertiría en una fila basura del catálogo y en una llamada
    pagada al modelo.
    """
    return _caja_de_contenido(img, tolerancia) is None


def recortar_fondo(img: Image.Image, tolerancia: int = 12) -> Image.Image:
    """Quita el margen liso alrededor del producto.

    Las páginas de Canva traen mucho blanco alrededor. Recortarlo hace que
    el envase ocupe toda la imagen, que es justo lo que el modelo necesita
    ver, y baja el peso del mosaico.
    """
    caja = _caja_de_contenido(img, tolerancia)
    if caja is None:
        return img
    # Un margen chico evita cortar el borde del envase.
    margen = 8
    x0, y0, x1, y1 = caja
    return img.crop((
        max(0, x0 - margen), max(0, y0 - margen),
        min(img.width, x1 + margen), min(img.height, y1 + margen),
    ))


def paginas_desde_pdf(
    ruta_pdf: Path,
    destino: Path,
    dpi: int = 150,
    desde: int = 1,
    hasta: int = 0,
    rehacer: bool = False,
) -> list[Path]:
    """Rasteriza el PDF de Canva a un PNG por página.

    Trabaja página por página y libera cada pixmap enseguida: un PDF de
    cientos de MB nunca se carga entero en memoria.

    Si el PNG de una página ya existe no se vuelve a generar, así que
    volver a correr el script después de un corte retoma donde quedó.
    """
    try:
        # `pymupdf` es el nombre nuevo; `fitz` sigue funcionando en
        # versiones anteriores pero emite un aviso de deprecación.
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
    except ImportError:
        print(
            "Falta PyMuPDF para leer el PDF. Instálalo con:\n"
            "    pip install -r gondola/requirements-tools.txt\n"
            "O exporta PNG desde Canva y usa --imagenes en vez de --pdf.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    documento = fitz.open(ruta_pdf)
    total = documento.page_count
    primera = max(1, desde)
    ultima = min(total, hasta) if hasta else total

    escala = dpi / 72
    salidas: list[Path] = []
    reutilizadas = 0
    vacias = 0

    tamano_mb = ruta_pdf.stat().st_size / 1024 / 1024
    print(
        f"Extrayendo páginas {primera}-{ultima} de {total} "
        f"({ruta_pdf.name}, {tamano_mb:.0f} MB) a {dpi} DPI..."
    )

    for numero in range(primera, ultima + 1):
        salida = destino / f"pagina_{numero:03d}.png"

        if salida.exists() and not rehacer:
            salidas.append(salida)
            reutilizadas += 1
            continue

        pagina = documento.load_page(numero - 1)
        pixmap = pagina.get_pixmap(matrix=fitz.Matrix(escala, escala))
        datos = pixmap.tobytes("png")
        # Sin esto, PyMuPDF acumula los mapas de bits de todas las páginas.
        pixmap = None

        with Image.open(io.BytesIO(datos)) as bruta:
            # Una página en blanco del diseño no es un producto: no debe
            # generar una fila del catálogo ni una llamada pagada al modelo.
            if parece_vacia(bruta):
                log.info("Página %d está en blanco, se omite.", numero)
                vacias += 1
                continue
            img = recortar_fondo(bruta)

        # Un recorte diminuto es ruido de maquetación, no un envase.
        if img.width < 60 or img.height < 60:
            log.info("Página %d sin contenido útil, se omite.", numero)
            vacias += 1
            continue

        img.thumbnail((LADO_PACKSHOT, LADO_PACKSHOT), Image.LANCZOS)
        img.convert("RGB").save(salida, format="PNG", optimize=True)
        salidas.append(salida)

        if numero % 25 == 0 or numero == ultima:
            print(f"  {numero}/{ultima}")

    documento.close()

    if reutilizadas:
        print(f"  {reutilizadas} páginas ya estaban extraídas y se reutilizaron.")
    if vacias:
        print(f"  {vacias} páginas vacías omitidas.")
    return salidas


def imagenes_desde_carpeta(carpeta: Path, destino: Path) -> list[Path]:
    """Normaliza PNG exportados de Canva (o de un ZIP ya descomprimido)."""
    fuentes = sorted(p for p in carpeta.rglob("*") if p.suffix.lower() in EXTENSIONES)
    salidas: list[Path] = []

    print(f"Normalizando {len(fuentes)} imágenes de {carpeta}...")
    for i, fuente in enumerate(fuentes, start=1):
        if fuente.parent == destino:
            continue
        img = recortar_fondo(Image.open(fuente))
        img.thumbnail((LADO_PACKSHOT, LADO_PACKSHOT), Image.LANCZOS)
        salida = destino / f"pagina_{i:03d}.png"
        img.convert("RGB").save(salida, format="PNG", optimize=True)
        salidas.append(salida)

    return salidas


# =====================================================================
# Descripción con IA
# =====================================================================


def _data_url(ruta: Path) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(ruta.read_bytes()).decode()


def describir(ruta: Path, modelo: str, client: httpx.Client) -> dict:
    mensajes = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe este producto siguiendo el esquema."},
                {"type": "image_url", "image_url": {"url": _data_url(ruta)}},
            ],
        },
    ]
    cfg = get_settings()
    payload = {
        "model": modelo,
        "messages": mensajes,
        "response_format": RESPONSE_FORMAT,
        "temperature": 0.0,
        "usage": {"include": True},
    }
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
        raise VisionError(f"OpenRouter {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    contenido = data["choices"][0]["message"].get("content") or ""
    return {
        "datos": _extraer_json(contenido),
        "costo": float((data.get("usage") or {}).get("cost") or 0.0),
    }


# =====================================================================
# Código de SKU
# =====================================================================


def _slug(texto: str, largo: int = 12) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^A-Za-z0-9]+", "", sin_tildes).upper()
    return limpio[:largo]


def sugerir_codigo(datos: dict, usados: set[str], pagina: int) -> str:
    """Arma un código estable a partir de marca, variante y gramaje.

    Es una sugerencia: el administrador lo cambiará por el código real de
    su ERP. Lo importante es que sea único y legible para poder revisarlo.
    """
    marca = _slug(datos.get("marca") or "", 10)
    variante = _slug(datos.get("variante") or datos.get("nombre") or "", 12)
    gramaje = _slug((datos.get("gramaje") or "").replace(" ", ""), 6)

    partes = [p for p in (marca, variante, gramaje) if p]
    base = "-".join(partes) if partes else f"SKU-{pagina:03d}"

    codigo = base
    sufijo = 2
    while codigo in usados:
        codigo = f"{base}-{sufijo}"
        sufijo += 1
    usados.add(codigo)
    return codigo


# =====================================================================
# Storage
# =====================================================================


def subir_packshots(rutas: list[Path]) -> dict[str, str]:
    """Sube los PNG al Storage y devuelve {nombre_archivo: url_pública}."""
    from gondola.app import db

    cliente = db.cliente()
    storage = cliente.storage

    try:
        storage.create_bucket(BUCKET_PACKSHOTS, options={"public": True})
        print(f"Bucket '{BUCKET_PACKSHOTS}' creado.")
    except Exception:
        # Ya existía; es el caso normal a partir de la segunda corrida.
        pass

    bucket = storage.from_(BUCKET_PACKSHOTS)
    urls: dict[str, str] = {}

    for ruta in rutas:
        try:
            bucket.upload(
                path=ruta.name,
                file=ruta.read_bytes(),
                file_options={"content-type": "image/png", "upsert": "true"},
            )
            urls[ruta.name] = bucket.get_public_url(ruta.name)
        except Exception as exc:
            log.warning("No se pudo subir %s: %s", ruta.name, exc)

    print(f"Subidos {len(urls)}/{len(rutas)} packshots a '{BUCKET_PACKSHOTS}'.")
    return urls


# =====================================================================
# Main
# =====================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convierte packshots de Canva en el catálogo del lector de góndola.",
    )
    fuente = parser.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--pdf", help="PDF exportado de Canva (una página por producto)")
    fuente.add_argument("--imagenes", help="Carpeta con PNG/JPG, uno por producto")

    parser.add_argument("--salida", default="./packshots", help="Carpeta destino")
    parser.add_argument("--categoria", default="", help="Categoría por defecto para todas las filas")
    parser.add_argument("--modelo", default=None, help="Modelo de OpenRouter (default: el primario)")
    parser.add_argument("--concurrencia", type=int, default=6)
    parser.add_argument("--subir", action="store_true", help="Subir los packshots al Storage de Supabase")
    parser.add_argument("--dpi", type=int, default=150, help="Resolución al rasterizar el PDF")
    parser.add_argument("--limite", type=int, default=0, help="Procesar solo las primeras N páginas (prueba)")
    parser.add_argument("--desde", type=int, default=1, help="Primera página del PDF a procesar")
    parser.add_argument("--hasta", type=int, default=0, help="Última página a procesar (0 = hasta el final)")
    parser.add_argument(
        "--solo-extraer", action="store_true",
        help="Cortar el PDF en PNG y parar, sin llamar a la IA. Útil para revisar antes de gastar.",
    )
    parser.add_argument(
        "--rehacer", action="store_true",
        help="Ignorar el trabajo previo y volver a extraer y describir todo.",
    )
    args = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(levelname)s :: %(message)s")

    cfg = get_settings()
    # --solo-extraer no llama a la IA, así que no tiene por qué exigir la clave.
    if not cfg.openrouter_api_key and not args.solo_extraer:
        print("Falta OPENROUTER_API_KEY en el entorno.", file=sys.stderr)
        print("Si solo quieres cortar el PDF en imágenes, usa --solo-extraer.", file=sys.stderr)
        return 1

    modelo = args.modelo or cfg.modelo_primario
    destino = Path(args.salida)
    destino.mkdir(parents=True, exist_ok=True)

    # ── 1. Imágenes ──────────────────────────────────────────────────
    if args.pdf:
        rutas = paginas_desde_pdf(
            Path(args.pdf), destino, args.dpi, args.desde, args.hasta, args.rehacer
        )
    else:
        rutas = imagenes_desde_carpeta(Path(args.imagenes), destino)

    if not rutas:
        print("No se extrajo ninguna imagen.", file=sys.stderr)
        return 1
    if args.limite:
        rutas = rutas[: args.limite]
    print(f"{len(rutas)} packshots listos en {destino}/")

    if args.solo_extraer:
        print("\n--solo-extraer: no se llamó a la IA. Revisa los PNG y vuelve a correr sin la bandera.")
        return 0

    # ── 2. Storage ───────────────────────────────────────────────────
    # Las URLs también se acumulan entre corridas, para que el CSV final
    # las tenga todas aunque el PDF se haya procesado por tandas.
    ruta_urls = destino / "packshot_urls.json"
    urls: dict[str, str] = {}
    if ruta_urls.exists() and not args.rehacer:
        try:
            urls = json.loads(ruta_urls.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("packshot_urls.json ilegible, se descarta.")

    if args.subir:
        pendientes_subida = [r for r in rutas if r.name not in urls]
        if pendientes_subida:
            urls.update(subir_packshots(pendientes_subida))
            ruta_urls.write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            print("Todos los packshots de este lote ya estaban subidos.")

    # ── 3. Descripción con IA ────────────────────────────────────────
    # Lo ya descrito en una corrida anterior no se vuelve a pagar. Con
    # cientos de páginas, un corte a mitad de camino no puede significar
    # empezar de cero.
    ruta_json = destino / "catalogo.json"
    resultados: dict[str, dict] = {}
    if ruta_json.exists() and not args.rehacer:
        try:
            resultados = json.loads(ruta_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("catalogo.json ilegible, se descarta y se describe todo de nuevo.")

    pendientes = [r for r in rutas if not resultados.get(r.name)]
    ya_hechas = len(rutas) - len(pendientes)
    costo_total = 0.0

    if ya_hechas:
        print(f"\n{ya_hechas} productos ya descritos en una corrida anterior; se reutilizan.")

    if not pendientes:
        print("Nada nuevo que describir.")
    else:
        print(f"\nDescribiendo {len(pendientes)} productos con {modelo}...")

        with httpx.Client() as client:
            def tarea(ruta: Path) -> tuple[Path, Optional[dict], float]:
                try:
                    r = describir(ruta, modelo, client)
                    return ruta, r["datos"], r["costo"]
                except Exception as exc:
                    log.warning("%s: %s", ruta.name, exc)
                    return ruta, None, 0.0

            try:
                with ThreadPoolExecutor(max_workers=args.concurrencia) as pool:
                    for i, (ruta, datos, costo) in enumerate(pool.map(tarea, pendientes), start=1):
                        if datos:
                            resultados[ruta.name] = datos
                        costo_total += costo
                        if i % 25 == 0 or i == len(pendientes):
                            print(f"  {i}/{len(pendientes)} ({costo_total:.4f} USD)")
                            # Guardar seguido: si se corta la conexión o
                            # cierras la terminal, lo pagado queda a salvo.
                            ruta_json.write_text(
                                json.dumps(resultados, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
            except KeyboardInterrupt:
                print("\nInterrumpido. Lo descrito hasta ahora quedó guardado;")
                print("vuelve a correr el mismo comando para continuar desde ahí.")
                ruta_json.write_text(
                    json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return 130

    # ── 4. CSV ───────────────────────────────────────────────────────
    # Se arma sobre TODOS los packshots de la carpeta, no solo sobre el
    # lote de esta corrida: quien procese el PDF por tandas debe terminar
    # con un solo CSV completo, no con el último pedazo.
    todas = sorted(destino.glob("pagina_*.png"))
    usados: set[str] = set()
    filas: list[dict] = []
    sin_leer = 0

    for ruta in todas:
        datos = resultados.get(ruta.name) or {}
        pagina = int(re.search(r"(\d+)", ruta.stem).group(1))

        motivos = []
        if not datos:
            motivos.append("la IA no pudo leer el envase")
            sin_leer += 1
        if not datos.get("marca"):
            motivos.append("falta marca")
        if not datos.get("gramaje"):
            motivos.append("falta gramaje")
        if datos.get("legible") is False:
            motivos.append("envase poco legible")

        filas.append({
            "codigo": sugerir_codigo(datos, usados, pagina),
            "nombre": datos.get("nombre") or "",
            "marca": datos.get("marca") or "",
            "categoria": args.categoria or datos.get("categoria_sugerida") or "",
            "gramaje": datos.get("gramaje") or "",
            "es_prioritario": "",
            "packshot_url": urls.get(ruta.name, ""),
            "descripcion_visual": datos.get("descripcion_visual") or "",
            "archivo": ruta.name,
            "pagina": pagina,
            "revisar": "; ".join(motivos),
        })

    ruta_csv = destino / "catalogo.csv"
    with ruta_csv.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)

    ruta_json.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 5. Resumen ───────────────────────────────────────────────────
    marcas = sorted({f["marca"] for f in filas if f["marca"]})
    a_revisar = sum(1 for f in filas if f["revisar"])
    con_url = sum(1 for f in filas if f["packshot_url"])

    print("\n" + "=" * 70)
    print(f"Catálogo borrador: {ruta_csv}")
    print(f"  productos        : {len(filas)}")
    print(f"  marcas           : {len(marcas)} ({', '.join(marcas[:8])}{'...' if len(marcas) > 8 else ''})")
    print(f"  a revisar        : {a_revisar}" + (f" ({sin_leer} sin lectura)" if sin_leer else ""))
    print(f"  con packshot_url : {con_url}/{len(filas)}")
    print(f"  costo de esta corrida: {costo_total:.4f} USD")
    print("=" * 70)
    print("\nSiguiente paso: abre catalogo.csv y revisa la columna 'codigo'")
    print("(cámbiala por el código real de tu ERP) y 'categoria'. La columna")
    print("'revisar' marca las filas donde la IA no estuvo segura.")
    if con_url < len(filas):
        print("\nOjo: las filas sin packshot_url no aportan hoja de referencia visual.")
        print("Vuelve a correr con --subir antes de auditar en sala.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
