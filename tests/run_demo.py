#!/usr/bin/env python3
"""
tests/run_demo.py — Demo Completo de la Pipeline SADIMEX
=========================================================
Ejecuta los 4 pasos de la pipeline en secuencia con un audio de prueba.
Muestra el resultado de cada etapa con output formateado.

Uso:
    # Opción 1: Usar el fixture generado automáticamente
    python3 tests/run_demo.py

    # Opción 2: Usar un audio real de campo
    python3 tests/run_demo.py --audio /ruta/a/tu/audio.mp3 --ciudad CBBA

Este script requiere que .env esté configurado con GEMINI_API_KEY.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from datetime import datetime

# Colores para output de consola
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"

PROJECT_ROOT = Path(__file__).parent.parent
TMP_DIR = PROJECT_ROOT / ".tmp"


def header(text: str):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")


def step(n: int, text: str):
    print(f"\n{BOLD}[Paso {n}/4]{RESET} {text}")
    print(f"{DIM}{'─'*50}{RESET}")


def success(text: str):
    print(f"{GREEN}✅ {text}{RESET}")


def warn(text: str):
    print(f"{YELLOW}⚠️  {text}{RESET}")


def error(text: str):
    print(f"{RED}❌ {text}{RESET}")
    sys.exit(1)


def run_tool(args: list[str], step_name: str) -> dict:
    """Ejecuta un tool de Python y retorna el JSON de output."""
    cmd = [sys.executable] + args
    print(f"  {DIM}$ {' '.join(args)}{RESET}")

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True
    )

    # Buscar el bloque JSON en el output (el último JSON válido)
    output_json = None
    for line in result.stdout.split('\n'):
        line = line.strip()
        if line.startswith('{') or line.startswith('['):
            try:
                output_json = json.loads(line)
            except json.JSONDecodeError:
                pass

    # También buscar en bloques multilínea
    if not output_json:
        try:
            # Buscar la última ocurrencia de un bloque JSON
            text = result.stdout
            start = text.rfind('\n {')
            if start == -1:
                start = text.rfind('\n{')
            if start != -1:
                output_json = json.loads(text[start:].strip())
        except Exception:
            pass

    if result.returncode != 0:
        stderr_msg = result.stderr[:300] if result.stderr else "Sin mensaje de error"
        error(f"{step_name} falló (código {result.returncode}):\n{stderr_msg}\n\nSTDOUT:\n{result.stdout[:500]}")

    return output_json or {"status": "ok", "_raw": result.stdout[:200]}


def check_env():
    """Verifica que .env existe y tiene GEMINI_API_KEY."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        error(
            ".env no encontrado.\n"
            f"  Ejecuta: cp \".env.example\" \".env\"\n"
            f"  Luego edita .env y añade tu GEMINI_API_KEY"
        )

    from dotenv import load_dotenv
    load_dotenv(env_path)
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        error(
            "GEMINI_API_KEY no configurada en .env.\n"
            f"  Edita el archivo .env y añade: GEMINI_API_KEY=tu_clave_aqui"
        )
    success(f"  .env cargado | API Key: {api_key[:8]}...{api_key[-4:]}")
    return api_key


def ensure_fixture_audio() -> Path:
    """Genera o localiza el audio de prueba."""
    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures"

    # Buscar audio existente
    for ext in ["*.mp3", "*.wav", "*.m4a"]:
        found = list(fixtures_dir.glob(ext))
        if found:
            return found[0]

    # Generar fixture sintético
    print(f"  {DIM}No se encontró fixture. Generando audio sintético...{RESET}")
    subprocess.run([sys.executable, "tests/generate_fixture.py"], cwd=str(PROJECT_ROOT))

    for ext in ["*.mp3", "*.wav"]:
        found = list(fixtures_dir.glob(ext))
        if found:
            return found[0]

    error("No se pudo crear el fixture de audio.")


def main():
    parser = argparse.ArgumentParser(description="Demo completo de la pipeline SADIMEX")
    parser.add_argument("--audio", help="Ruta a un audio real de campo (.mp3/.wav/.m4a)")
    parser.add_argument("--ciudad", default="LPZ", choices=["LPZ", "CBBA", "SCZ"])
    parser.add_argument("--cliente", default="Tienda Demo - Canal Tradicional")
    args = parser.parse_args()

    header("🚀 SADIMEX SALES INTELLIGENCE — DEMO PIPELINE")
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Ciudad: {args.ciudad}")
    print(f"  Cliente: {args.cliente}")

    # Pre-check: .env
    check_env()

    # Pre-check: .tmp directory
    TMP_DIR.mkdir(exist_ok=True)

    # Determinar audio a usar
    if args.audio:
        audio_path = Path(args.audio)
        if not audio_path.exists():
            error(f"Audio no encontrado: {audio_path}")
    else:
        print(f"\n  {DIM}Buscando fixture de audio...{RESET}")
        audio_path = ensure_fixture_audio()

    print(f"\n  {BOLD}Audio:{RESET} {audio_path.name} ({audio_path.stat().st_size / 1024:.1f} KB)")

    # ID de vendedor de prueba
    vendedor_id = "demo-vendedor-" + str(uuid.uuid4())[:8]
    print(f"  {BOLD}Vendedor ID:{RESET} {vendedor_id}")

    # ─────────────────────────────────────────
    # PASO 1: Verificación de Gemini (Link)
    # ─────────────────────────────────────────
    step(1, "Verificando conexión con Gemini API (Phase 2: Link)")
    result = run_tool(["tools/verify_gemini.py"], "verify_gemini")
    if result.get("status") == "ok":
        success(f"Gemini conectado | Modelo: {result.get('model', '?')}")
    else:
        error(f"Gemini no responde: {result}")

    # ─────────────────────────────────────────
    # PASO 2: Ingesta de Audio
    # ─────────────────────────────────────────
    step(2, "Ingesta de audio y creación de AudioRecord")
    result = run_tool([
        "tools/ingest_audio.py",
        "--file", str(audio_path),
        "--vendedor_id", vendedor_id,
        "--ciudad", args.ciudad,
        "--cliente_nombre", args.cliente
    ], "ingest_audio")

    audio_id = result.get("audio_id")
    if not audio_id:
        error(f"No se obtuvo audio_id: {result}")
    success(f"AudioRecord creado | ID: {audio_id}")
    print(f"  Estado: {result.get('estado', '?')} | Persistencia: {result.get('persistence', {}).get('persisted', '?')}")

    # ─────────────────────────────────────────
    # PASO 3: Transcripción y Diarización
    # ─────────────────────────────────────────
    step(3, "Transcripción y diarización con Gemini Pro")
    print(f"  {YELLOW}⏳ Esto puede tomar 20-60 segundos...{RESET}")
    result = run_tool(["tools/transcribe_diarize.py", "--audio_id", audio_id], "transcribe_diarize")

    if result.get("status") == "ok":
        preview = result.get("preview", {})
        n_segs = len(preview.get("segmentos", []))
        speakers = {s.get("speaker") for s in preview.get("segmentos", [])}
        confianza = preview.get("confianza_diarizacion", "?")
        success(f"Diarización completa | {n_segs} segmentos | Speakers: {speakers} | Confianza: {confianza}")

        # Mostrar primeros 3 segmentos
        print(f"\n  {DIM}Primeros segmentos:{RESET}")
        for seg in preview.get("segmentos", [])[:3]:
            sp = seg.get("speaker", "?")
            color = CYAN if sp == "VENDEDOR" else YELLOW
            print(f"  {color}[{sp}]{RESET}: {seg.get('texto', '')[:80]}")
    else:
        warn("Resultado parcial del step de diarización (revisar .tmp/)")

    # ─────────────────────────────────────────
    # PASO 4: Extracción de KPIs
    # ─────────────────────────────────────────
    step(4, "Extracción de KPIs y generación de coaching insights")
    print(f"  {YELLOW}⏳ Analizando con Gemini Flash...{RESET}")
    result = run_tool(["tools/extract_kpis.py", "--audio_id", audio_id], "extract_kpis")

    if result.get("status") == "ok":
        analysis = result.get("result", result.get("analysis", {}))
        score = analysis.get("score_visita", "?")
        semaforo = analysis.get("semaforo", "?")
        kpis = analysis.get("kpis", {})

        sem_color = {"verde": GREEN, "amarillo": YELLOW, "rojo": RED}.get(semaforo, RESET)
        success(f"VisitAnalysis generado")
        print(f"\n  {'─'*50}")
        print(f"  {BOLD}SCORE VISITA:{RESET}    {sem_color}{score}/100{RESET}")
        print(f"  {BOLD}SEMÁFORO:{RESET}        {sem_color}{'●'} {semaforo.upper()}{RESET}")
        print(f"  {BOLD}CIERRE EXITOSO:{RESET}  {'✅' if kpis.get('cierre_exitoso') else '❌'}")
        print(f"  {BOLD}MARCAS MENC.:{RESET}    {', '.join(kpis.get('marcas_mencionadas', [])) or 'Ninguna'}")
        print(f"  {BOLD}MARCAS BRECHA:{RESET}   {', '.join(kpis.get('marcas_faltantes', [])) or 'Ninguna'}")
        print(f"  {BOLD}QUIEBRE STOCK:{RESET}   {'Sí' if kpis.get('quiebre_de_stock_detectado') else 'No'}")
        print(f"  {'─'*50}")
        print(f"\n  {BOLD}RESUMEN EJECUTIVO:{RESET}")
        print(f"  {analysis.get('resumen_ejecutivo', '—')}")
        print(f"\n  {BOLD}COACHING INSIGHTS:{RESET}")
        for i, ins in enumerate(analysis.get("coaching_insights", []), 1):
            cat = ins.get("categoria", "").upper()
            obs = ins.get("sugerencia_tactica", ins.get("observacion", ""))
            print(f"  {i}. [{CYAN}{cat}{RESET}] {obs}")
    else:
        warn(f"KPI extraction parcial: {result}")

    # ─────────────────────────────────────────
    # RESUMEN FINAL
    # ─────────────────────────────────────────
    header("✅ DEMO COMPLETADO")
    print(f"\n  Audio ID procesado: {audio_id}")
    print(f"  Archivos generados en .tmp/:")
    for f in TMP_DIR.glob(f"{audio_id}*"):
        print(f"    - {f.name}")
    print(f"\n{BOLD}  Pipeline funcional. Listo para Phase 4: Dashboard React.{RESET}\n")


if __name__ == "__main__":
    main()
