#!/usr/bin/env python3
"""
tools/transcribe_diarize.py — Phase 3: Transcripción y Diarización
===================================================================
Llama a Gemini 2.5 Pro con el audio y un prompt de diarización estricta.
Diferencia claramente entre VENDEDOR y CLIENTE.
Guarda el resultado en .tmp/<audio_id>_diarization.json.

Uso:
    python tools/transcribe_diarize.py --audio_id <uuid>

Precondición: El AudioRecord debe existir en .tmp/<audio_id>_record.json
              o en Supabase con estado 'pendiente'.

Self-Annealing Note (2026-02-21):
  Migrado de google-generativeai (DEPRECATED) a google-genai.
  Modelos: gemini-2.5-pro (transcripción), gemini-2.5-flash (análisis).
  API: google.genai.Client(api_key=...) + client.files.upload() para audio.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv(Path(__file__).parent.parent / ".env")
console = Console()
TMP_DIR = Path(os.getenv("TMP_DIR", ".tmp"))

DIARIZATION_PROMPT = """Eres un experto en transcripción y diarización de llamadas comerciales de campo en Bolivia.

Tu tarea es analizar este audio de una visita de ventas y producir una transcripción diarizada en formato JSON.

REGLAS ESTRICTAS:
1. SIEMPRE etiqueta cada segmento como "VENDEDOR" o "CLIENTE". Nunca uses "SPEAKER_UNKNOWN" si puedes inferir el rol por el contexto.
2. El VENDEDOR es quien ofrece productos, menciona precios, presenta combos o cierra pedidos.
3. El CLIENTE es el dueño/encargado del punto de venta (tienda, bodega, minimarket).
4. Reconoce jerga boliviana del canal tradicional: "caserita", "bono", "combo", "quiebre de stock", "cuánto me das", "fiado", "a crédito", etc.
5. Si hay mucho ruido o la voz es ininteligible, usa "[ininteligible]" para ese fragmento específico.
6. El idioma puede ser español con mezcla de términos en aymara o quechua — transcribe fonéticamente si es necesario.

FORMATO DE RESPUESTA (JSON puro, sin markdown):
{
  "idioma_detectado": "es-BO",
  "duracion_estimada_segundos": <numero>,
  "confianza_diarizacion": "alta | media | baja",
  "segmentos": [
    {
      "speaker": "VENDEDOR | CLIENTE",
      "inicio_ms": <numero>,
      "fin_ms": <numero>,
      "texto": "<transcripcion exacta>"
    }
  ],
  "notas_calidad": "<observaciones sobre calidad de audio>"
}

Responde ÚNICAMENTE con el JSON. Sin explicaciones adicionales."""


def load_audio_record(audio_id: str) -> dict:
    """Carga el AudioRecord desde .tmp/ o Supabase."""
    record_path = TMP_DIR / f"{audio_id}_record.json"
    if record_path.exists():
        return json.loads(record_path.read_text())

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if supabase_url and supabase_key:
        try:
            from supabase import create_client
            sb = create_client(supabase_url, supabase_key)
            result = sb.table("audio_records").select("*").eq("id", audio_id).single().execute()
            return result.data
        except Exception as e:
            raise FileNotFoundError(f"AudioRecord no encontrado en Supabase: {e}")

    raise FileNotFoundError(f"No se encontró el AudioRecord para audio_id: {audio_id}")


def transcribe_and_diarize(audio_record: dict) -> dict:
    """Envía el audio a Gemini 2.5 Pro y obtiene la diarización."""
    import google.genai as genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL_TRANSCRIPTION", "gemini-2.5-pro")

    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError("GEMINI_API_KEY no configurada en .env")

    client = genai.Client(api_key=api_key)
    audio_path = Path(audio_record["archivo_local_path"])

    if not audio_path.exists():
        raise FileNotFoundError(f"Archivo de audio no encontrado: {audio_path}")

    console.print(f"   [dim]Subiendo audio ({audio_path.stat().st_size / 1024:.1f} KB)...[/dim]")

    # Determinar MIME type
    ext = audio_path.suffix.lower()
    mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}
    mime_type = mime_map.get(ext, "audio/mpeg")

    # Subir el audio usando Files API
    with open(audio_path, "rb") as f:
        uploaded_file = client.files.upload(
            file=f,
            config=types.UploadFileConfig(mime_type=mime_type)
        )

    console.print(f"   [dim]Audio subido. Procesando con {model_name}...[/dim]")

    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=mime_type),
            DIARIZATION_PROMPT
        ]
    )

    # Parsear respuesta JSON
    raw_text = response.text.strip()
    # Limpiar posibles bloques markdown
    if raw_text.startswith("```"):
        parts = raw_text.split("```")
        raw_text = parts[1] if len(parts) > 1 else raw_text
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    diarization = json.loads(raw_text.strip())

    # Limpiar el archivo subido (evitar acumulación)
    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass

    return diarization


def update_record_status(audio_id: str, estado: str):
    """Actualiza el estado del AudioRecord en Supabase o .tmp/"""
    record_path = TMP_DIR / f"{audio_id}_record.json"
    if record_path.exists():
        record = json.loads(record_path.read_text())
        record["estado"] = estado
        record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if supabase_url and "supabase.co" in supabase_url and supabase_key:
        try:
            from supabase import create_client
            sb = create_client(supabase_url, supabase_key)
            sb.table("audio_records").update({"estado": estado}).eq("id", audio_id).execute()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Transcripción y diarización de audio SADIMEX")
    parser.add_argument("--audio_id", required=True, help="UUID del AudioRecord a procesar")
    args = parser.parse_args()

    console.print(f"\n[cyan]🎙️  Transcribiendo audio:[/cyan] {args.audio_id}")

    try:
        # 1. Cargar registro
        record = load_audio_record(args.audio_id)
        console.print(f"   Ciudad: [yellow]{record['ciudad']}[/yellow] | Cliente: {record['cliente_nombre']}")

        # 2. Actualizar estado → procesando
        update_record_status(args.audio_id, "procesando")

        # 3. Transcribir y diarizar
        diarization_result = transcribe_and_diarize(record)

        # 4. Enriquecer con metadata
        output = {
            "audio_id": args.audio_id,
            "vendedor_id": record["vendedor_id"],
            "ciudad": record["ciudad"],
            **diarization_result
        }

        # 5. Guardar en .tmp/
        output_path = TMP_DIR / f"{args.audio_id}_diarization.json"
        output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

        # 6. Actualizar estado → diarizado
        update_record_status(args.audio_id, "diarizado")

        speakers = {s["speaker"] for s in diarization_result.get("segmentos", [])}
        n_segments = len(diarization_result.get("segmentos", []))
        console.print(
            f"[green]✅ Diarización completa:[/green] {n_segments} segmentos | "
            f"Speakers: {speakers} | Confianza: {diarization_result.get('confianza_diarizacion', '?')}"
        )
        print("\n", json.dumps({"status": "ok", "output_path": str(output_path), "preview": output}, indent=2, ensure_ascii=False))
        sys.exit(0)

    except Exception as e:
        update_record_status(args.audio_id, "error")
        console.print(f"[red]❌ Error en diarización:[/red] {e}")
        print("\n", json.dumps({"status": "error", "audio_id": args.audio_id, "error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
