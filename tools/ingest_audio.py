#!/usr/bin/env python3
"""
tools/ingest_audio.py — Phase 3: Ingesta de Audio
==================================================
Valida y registra un archivo de audio en el sistema.
Crea el registro AudioRecord en Supabase con estado 'pendiente'.

Uso:
    python tools/ingest_audio.py \
        --file /ruta/al/audio.mp3 \
        --vendedor_id <uuid> \
        --cliente_nombre "Tienda Don Pedro" \
        --ciudad LPZ

Salida: JSON con el AudioRecord creado o error.
"""

import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv(Path(__file__).parent.parent / ".env")

console = Console()
TMP_DIR = Path(os.getenv("TMP_DIR", ".tmp"))
VALID_EXTENSIONS = {".mp3", ".wav", ".m4a"}
CIUDADES_VALIDAS = {"LPZ", "CBBA", "SCZ"}


def validate_audio_file(file_path: Path) -> dict:
    """Valida existencia, extensión y tamaño mínimo del archivo."""
    if not file_path.exists():
        return {"ok": False, "error": f"Archivo no encontrado: {file_path}"}
    if file_path.suffix.lower() not in VALID_EXTENSIONS:
        return {"ok": False, "error": f"Extensión inválida '{file_path.suffix}'. Formatos aceptados: {VALID_EXTENSIONS}"}
    if file_path.stat().st_size < 1024:  # menos de 1KB = sospechoso
        return {"ok": False, "error": "El archivo parece estar vacío o corrupto (< 1KB)"}
    return {"ok": True}


def copy_to_tmp(file_path: Path, audio_id: str) -> Path:
    """Copia el audio a .tmp/ con nombre basado en el ID para evitar colisiones."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    dest = TMP_DIR / f"{audio_id}{file_path.suffix.lower()}"
    shutil.copy2(file_path, dest)
    return dest


def create_audio_record(
    audio_id: str,
    vendedor_id: str,
    ciudad: str,
    cliente_nombre: str,
    archivo_tmp: Path,
    original_size: int,
) -> dict:
    """Construye el diccionario AudioRecord listo para insertar en BD."""
    return {
        "id": audio_id,
        "vendedor_id": vendedor_id,
        "ciudad": ciudad.upper(),
        "fecha_visita": datetime.utcnow().isoformat() + "Z",
        "cliente_nombre": cliente_nombre,
        "archivo_local_path": str(archivo_tmp.resolve()),
        "duracion_segundos": None,  # Se calculará en transcripción
        "estado": "pendiente",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "file_size_bytes": original_size,
    }


def persist_record(record: dict) -> dict:
    """
    Persiste el AudioRecord en Supabase.
    Si Supabase no está configurado, guarda localmente en .tmp/<id>_record.json
    como fallback para modo offline.
    """
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if supabase_url and "supabase.co" in supabase_url and supabase_key:
        try:
            from supabase import create_client
            sb = create_client(supabase_url, supabase_key)
            result = sb.table("audio_records").insert(record).execute()
            return {"persisted": "supabase", "data": result.data}
        except Exception as e:
            console.print(f"[yellow]⚠️  Supabase no disponible ({e}). Modo offline: guardando en .tmp/[/yellow]")

    # Fallback offline: guardar JSON en .tmp/
    record_path = TMP_DIR / f"{record['id']}_record.json"
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return {"persisted": "local_tmp", "path": str(record_path)}


def main():
    parser = argparse.ArgumentParser(description="Ingesta de audio para SADIMEX Sales Intelligence")
    parser.add_argument("--file", required=True, help="Ruta al archivo de audio (.mp3, .wav, .m4a)")
    parser.add_argument("--vendedor_id", required=True, help="UUID del vendedor")
    parser.add_argument("--cliente_nombre", default="Desconocido", help="Nombre del cliente visitado")
    parser.add_argument("--ciudad", required=True, choices=["LPZ", "CBBA", "SCZ"], help="Ciudad de la visita")
    args = parser.parse_args()

    file_path = Path(args.file)
    console.print(f"\n[cyan]📥 Ingresando audio:[/cyan] {file_path.name}")

    # 1. Validar
    validation = validate_audio_file(file_path)
    if not validation["ok"]:
        console.print(f"[red]❌ Error de validación:[/red] {validation['error']}")
        sys.exit(1)

    # 2. Generar ID y copiar a .tmp/
    audio_id = str(uuid.uuid4())
    tmp_path = copy_to_tmp(file_path, audio_id)
    console.print(f"   [dim]Copiado a .tmp/: {tmp_path.name}[/dim]")

    # 3. Crear registro
    record = create_audio_record(
        audio_id=audio_id,
        vendedor_id=args.vendedor_id,
        ciudad=args.ciudad,
        cliente_nombre=args.cliente_nombre,
        archivo_tmp=tmp_path,
        original_size=file_path.stat().st_size,
    )

    # 4. Persistir
    persistence = persist_record(record)

    result = {
        "status": "ok",
        "audio_id": audio_id,
        "estado": "pendiente",
        "ciudad": args.ciudad,
        "persistence": persistence,
    }

    console.print(f"[green]✅ AudioRecord creado:[/green] {audio_id}")
    print("\n", json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
