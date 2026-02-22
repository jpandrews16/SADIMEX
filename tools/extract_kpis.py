#!/usr/bin/env python3
"""
tools/extract_kpis.py — Phase 3: Extracción de KPIs
====================================================
Lee el DiarizationSegment de .tmp/ y la KnowledgeBase (knowledge.json).
Usa Gemini 2.5 Flash para extraer KPIs y generar coaching insights.
Persiste el VisitAnalysis en Supabase o .tmp/.

Uso:
    python tools/extract_kpis.py --audio_id <uuid>

Precondición: .tmp/<audio_id>_diarization.json debe existir.

Self-Annealing Note (2026-02-21):
  Migrado de google-generativeai (DEPRECATED) a google-genai.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv(Path(__file__).parent.parent / ".env")
console = Console()
TMP_DIR = Path(os.getenv("TMP_DIR", ".tmp"))
PROJECT_ROOT = Path(__file__).parent.parent


def load_knowledge_base() -> dict:
    kb_path = PROJECT_ROOT / "knowledge.json"
    if not kb_path.exists():
        raise FileNotFoundError("knowledge.json no encontrado.")
    return json.loads(kb_path.read_text())


def load_diarization(audio_id: str) -> dict:
    path = TMP_DIR / f"{audio_id}_diarization.json"
    if not path.exists():
        raise FileNotFoundError(f"Diarización no encontrada: {path}. Ejecuta transcribe_diarize.py primero.")
    return json.loads(path.read_text())


def build_kpi_prompt(diarization: dict, knowledge_base: dict) -> str:
    marcas = [m["nombre"] for m in knowledge_base["marcas"]]
    marcas_prioritarias = [m["nombre"] for m in knowledge_base["marcas"] if m["es_marca_prioritaria"]]
    criterios_vp = knowledge_base["definicion_venta_perfecta"]["criterios"]
    umbrales = knowledge_base["umbrales_semaforo"]

    dialogo = "\n".join([
        f"[{s['speaker']}]: {s['texto']}"
        for s in diarization.get("segmentos", [])
    ])

    criterios_texto = "\n".join([
        f"  - {c['nombre']} (peso: {c['peso_ponderacion']*100:.0f}%): {c['descripcion']}"
        for c in criterios_vp
    ])

    return f"""Eres un Consultor Senior de Ventas del canal tradicional boliviano, especializado en la metodología de Sadimex.

Analiza la siguiente transcripción diarizada de una visita comercial y genera un análisis completo en JSON.

=== TRANSCRIPCIÓN ===
{dialogo}

=== CATÁLOGO SADIMEX ===
Marcas disponibles: {', '.join(marcas)}
Marcas PRIORITARIAS: {', '.join(marcas_prioritarias)}

=== CRITERIOS DE VENTA PERFECTA ===
{criterios_texto}

=== INSTRUCCIONES ===
1. Solo analiza los turnos del VENDEDOR para evaluar técnicas de venta.
2. Tu tono es el de un consultor senior: constructivo, específico y accionable. NUNCA punitivo.
3. Los coaching_insights deben ser sugerencias tácticas concretas.
4. Detecta jerga boliviana como evidencia de rapport con el cliente.

=== UMBRALES DE SEMÁFORO ===
Verde: score >= {umbrales['verde']} | Amarillo: score {umbrales['amarillo']}-{umbrales['verde']-1} | Rojo: score < {umbrales['amarillo']}

RESPONDE ÚNICAMENTE con este JSON (sin markdown):
{{
  "kpis": {{
    "saludo_adecuado": true,
    "marcas_mencionadas": ["lista"],
    "marcas_faltantes": ["lista"],
    "cierre_exitoso": true,
    "tecnica_cierre_usada": "nombre o null",
    "quiebre_de_stock_detectado": false,
    "precio_correcto": true,
    "venta_perfecta_score": 75
  }},
  "coaching_insights": [
    {{
      "categoria": "portafolio | cierre | relacion_cliente | precio | general",
      "observacion": "qué ocurrió",
      "sugerencia_tactica": "qué hacer diferente"
    }}
  ],
  "resumen_ejecutivo": "2-3 oraciones en español",
  "score_visita": 75,
  "semaforo": "verde | amarillo | rojo",
  "tendencia_relacion_cliente": "positiva | neutral | negativa"
}}"""


def persist_visit_analysis(analysis: dict) -> dict:
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if supabase_url and "supabase.co" in supabase_url and supabase_key:
        try:
            from supabase import create_client
            sb = create_client(supabase_url, supabase_key)
            record = {k: v for k, v in analysis.items()}
            sb.table("visit_analyses").insert(record).execute()
            return {"persisted": "supabase"}
        except Exception as e:
            console.print(f"[yellow]⚠️  Supabase no disponible ({e}). Guardando en .tmp/[/yellow]")

    path = TMP_DIR / f"{analysis['audio_id']}_analysis.json"
    path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
    return {"persisted": "local_tmp", "path": str(path)}


def main():
    parser = argparse.ArgumentParser(description="Extracción de KPIs SADIMEX")
    parser.add_argument("--audio_id", required=True, help="UUID del audio ya diarizado")
    args = parser.parse_args()

    console.print(f"\n[cyan]📊 Extrayendo KPIs:[/cyan] {args.audio_id}")

    try:
        import google.genai as genai

        # 1. Cargar insumos
        diarization = load_diarization(args.audio_id)
        kb = load_knowledge_base()

        # 2. Gate: verificar segmentos VENDEDOR
        speakers = {s["speaker"] for s in diarization.get("segmentos", [])}
        if "VENDEDOR" not in speakers:
            console.print("[red]❌ Gate de diarización:[/red] No se detectó ningún segmento VENDEDOR.")
            sys.exit(1)

        # 3. Llamar Gemini 2.5 Flash
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL_ANALYSIS", "gemini-2.5-flash")
        client = genai.Client(api_key=api_key)

        prompt = build_kpi_prompt(diarization, kb)
        console.print(f"   [dim]Analizando con {model_name}...[/dim]")

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )

        # 4. Parsear
        raw = response.text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        gemini_output = json.loads(raw.strip())

        # 5. Construir VisitAnalysis
        analysis = {
            "id": str(uuid.uuid4()),
            "audio_id": args.audio_id,
            "vendedor_id": diarization["vendedor_id"],
            "ciudad": diarization["ciudad"],
            "fecha_analisis": datetime.utcnow().isoformat() + "Z",
            **gemini_output,
            "confianza_diarizacion": diarization.get("confianza_diarizacion", "desconocida"),
        }

        # 6. Persistir
        persist_visit_analysis(analysis)

        semaforo_color = {"verde": "green", "amarillo": "yellow", "rojo": "red"}.get(analysis["semaforo"], "white")
        console.print(
            f"[green]✅ VisitAnalysis generado:[/green] "
            f"Score: [{semaforo_color}]{analysis['score_visita']}/100[/{semaforo_color}] | "
            f"Semáforo: [{semaforo_color}]{analysis['semaforo'].upper()}[/{semaforo_color}]"
        )
        print("\n", json.dumps({"status": "ok", "analysis_id": analysis["id"], "result": analysis}, indent=2, ensure_ascii=False))
        sys.exit(0)

    except Exception as e:
        console.print(f"[red]❌ Error:[/red] {e}")
        print("\n", json.dumps({"status": "error", "audio_id": args.audio_id, "error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
