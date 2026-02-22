#!/usr/bin/env python3
"""
tools/verify_gemini.py — Phase 2: Link Verification
=====================================================
Handshake script: verifica que la API de Gemini responde correctamente
antes de proceder con cualquier procesamiento de audio real.

Uso:
    python tools/verify_gemini.py

resultado esperado:
    ✅ Gemini API conectada correctamente
    {model, status, response_preview}

Si falla → revisar GEMINI_API_KEY en .env

Self-Annealing Note (2026-02-21):
  google-generativeai está DEPRECATED. Usar google-genai (google.genai).
  Modelos disponibles: gemini-2.5-flash (análisis), gemini-2.5-pro (transcripción).
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env desde el directorio raíz del proyecto
load_dotenv(Path(__file__).parent.parent / ".env")

try:
    import google.genai as genai
except ImportError:
    print("❌ ERROR: google-genai no está instalado.")
    print("   Ejecuta: pip install -r requirements.txt")
    sys.exit(1)

from rich.console import Console
from rich.panel import Panel

console = Console()


def verify_gemini_connection() -> dict:
    """
    Envía un prompt de texto simple a Gemini para verificar conectividad.
    Retorna un diccionario con el resultado del handshake.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL_ANALYSIS", "gemini-2.5-flash")

    if not api_key or api_key == "your_gemini_api_key_here":
        return {
            "status": "error",
            "error": "GEMINI_API_KEY no configurada en .env",
            "action": "Copia .env.example como .env y rellena tu API key"
        }

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents="Responde únicamente con: SADIMEX_OK"
        )
        response_text = response.text.strip()
        success = "SADIMEX_OK" in response_text

        return {
            "status": "ok" if success else "unexpected_response",
            "model": model_name,
            "response_raw": response_text,
            "api_key_masked": f"{api_key[:8]}...{api_key[-4:]}",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "model": model_name
        }


def main():
    console.print("\n[bold cyan]🛰️  SADIMEX — Fase 2: Verificación de Link[/bold cyan]")
    console.print("[dim]Probando conexión con Gemini API...[/dim]\n")

    result = verify_gemini_connection()

    if result["status"] == "ok":
        console.print(Panel(
            f"[bold green]✅ Gemini API conectada correctamente[/bold green]\n\n"
            f"  Modelo : [cyan]{result['model']}[/cyan]\n"
            f"  API Key: [dim]{result['api_key_masked']}[/dim]\n"
            f"  Respuesta: [green]{result['response_raw']}[/green]",
            title="[green]LINK ✓[/green]",
            border_style="green"
        ))
        print("\n", json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)

    elif result["status"] == "unexpected_response":
        console.print(Panel(
            f"[bold yellow]⚠️  Gemini responde pero con resultado inesperado[/bold yellow]\n\n"
            f"  Respuesta recibida: [yellow]{result['response_raw']}[/yellow]\n"
            f"  El modelo funciona pero el comportamiento es impredecible.",
            title="[yellow]LINK: ADVERTENCIA[/yellow]",
            border_style="yellow"
        ))
        print("\n", json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)

    else:
        console.print(Panel(
            f"[bold red]❌ Error al conectar con Gemini API[/bold red]\n\n"
            f"  Error: [red]{result.get('error', 'Desconocido')}[/red]\n"
            f"  Acción: {result.get('action', 'Revisa el stack trace y tu .env')}",
            title="[red]LINK ✗[/red]",
            border_style="red"
        ))
        print("\n", json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
