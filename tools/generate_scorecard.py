#!/usr/bin/env python3
"""
tools/generate_scorecard.py — Phase 3: Generación de Scorecard Semanal
=======================================================================
Agrega todos los VisitAnalysis de la semana para un vendedor.
Genera el WeeklyScorecard con semáforo, tendencia y top coaching insights.
Persiste en Supabase o .tmp/.

Uso:
    python tools/generate_scorecard.py \
        --vendedor_id <uuid> \
        --semana_inicio 2026-02-16

El sistema calcula automáticamente semana_fin = semana_inicio + 6 días.
"""

import argparse
import json
import math
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv(Path(__file__).parent.parent / ".env")
console = Console()
TMP_DIR = Path(os.getenv("TMP_DIR", ".tmp"))
PROJECT_ROOT = Path(__file__).parent.parent


def load_knowledge_base() -> dict:
    kb_path = PROJECT_ROOT / "knowledge.json"
    return json.loads(kb_path.read_text())


def get_analyses_for_week(vendedor_id: str, semana_inicio: str, semana_fin: str) -> list[dict]:
    """
    Carga todos los VisitAnalysis del vendedor en el rango de fechas.
    Busca primero en Supabase, luego en .tmp/ como fallback.
    """
    analyses = []

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if supabase_url and "supabase.co" in supabase_url and supabase_key:
        try:
            from supabase import create_client
            sb = create_client(supabase_url, supabase_key)
            result = sb.table("visit_analyses") \
                .select("*") \
                .eq("vendedor_id", vendedor_id) \
                .gte("fecha_analisis", semana_inicio + "T00:00:00Z") \
                .lte("fecha_analisis", semana_fin + "T23:59:59Z") \
                .execute()
            analyses = result.data
            console.print(f"   [dim]Cargados {len(analyses)} análisis desde Supabase[/dim]")
            return analyses
        except Exception as e:
            console.print(f"[yellow]⚠️  Supabase no disponible ({e}). Buscando en .tmp/[/yellow]")

    # Fallback: buscar todos los _analysis.json en .tmp/
    ini = datetime.fromisoformat(semana_inicio)
    fin = datetime.fromisoformat(semana_fin) + timedelta(days=1)

    for path in TMP_DIR.glob("*_analysis.json"):
        try:
            data = json.loads(path.read_text())
            if data.get("vendedor_id") != vendedor_id:
                continue
            fecha = datetime.fromisoformat(data["fecha_analisis"].replace("Z", ""))
            if ini <= fecha < fin:
                analyses.append(data)
        except Exception:
            continue

    console.print(f"   [dim]Cargados {len(analyses)} análisis desde .tmp/[/dim]")
    return analyses


def compute_scorecard(vendedor_id: str, analyses: list[dict], semana_inicio: str, semana_fin: str) -> dict:
    """Calcula el WeeklyScorecard a partir de los VisitAnalysis de la semana."""
    kb = load_knowledge_base()
    umbrales = kb["umbrales_semaforo"]

    if not analyses:
        return None

    # Métricas básicas
    total = len(analyses)
    scores = [a["score_visita"] for a in analyses if "score_visita" in a]
    score_promedio = round(sum(scores) / len(scores), 1) if scores else 0

    # Marcas con brecha (marcas prioritarias que frecuentemente no se mencionan)
    marcas_faltantes_counter = Counter()
    for a in analyses:
        for m in a.get("kpis", {}).get("marcas_faltantes", []):
            marcas_faltantes_counter[m] += 1
    # Brecha = falta en >40% de las visitas
    umbral_brecha = max(1, math.ceil(total * 0.4))
    marcas_con_brecha = [m for m, c in marcas_faltantes_counter.items() if c >= umbral_brecha]

    # Tasa de cierre
    cierres_exitosos = sum(1 for a in analyses if a.get("kpis", {}).get("cierre_exitoso"))
    tasa_cierre = round(cierres_exitosos / total, 3) if total > 0 else 0

    # Quiebres detectados
    quiebres = sum(1 for a in analyses if a.get("kpis", {}).get("quiebre_de_stock_detectado"))

    # Venta perfecta rate (visitas con score >= 80)
    vp_rate = round(sum(1 for s in scores if s >= umbrales["verde"]) / len(scores), 3) if scores else 0

    # Semáforo semanal
    if score_promedio >= umbrales["verde"]:
        semaforo = "verde"
    elif score_promedio >= umbrales["amarillo"]:
        semaforo = "amarillo"
    else:
        semaforo = "rojo"

    # Top 3 coaching insights de la semana (más frecuentes por categoría)
    coaching_texts = []
    for a in analyses:
        for ins in a.get("coaching_insights", [])[:2]:  # Top 2 por visita
            coaching_texts.append(ins.get("sugerencia_tactica", ""))
    coaching_prioritario = list(dict.fromkeys(coaching_texts))[:3]  # Deduplicar y tomar top 3

    # Ciudad (del primer análisis, todos deberían ser la misma)
    ciudad = analyses[0].get("ciudad", "LPZ") if analyses else "LPZ"

    # Vendedor supervisor_id (si está disponible en análisis)
    supervisor_id = analyses[0].get("supervisor_id", None) if analyses else None

    return {
        "id": str(uuid.uuid4()),
        "vendedor_id": vendedor_id,
        "supervisor_id": supervisor_id,
        "ciudad": ciudad,
        "semana_inicio": semana_inicio,
        "semana_fin": semana_fin,
        "metricas_semana": {
            "total_visitas": total,
            "visitas_analizadas": total,
            "score_promedio": score_promedio,
            "marcas_con_brecha": marcas_con_brecha,
            "tasa_cierre": tasa_cierre,
            "quiebres_detectados": quiebres,
            "venta_perfecta_rate": vp_rate,
        },
        "tendencia": "estable",  # Se actualizará con histórico en versiones futuras
        "coaching_prioritario": coaching_prioritario,
        "semaforo_semana": semaforo,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def persist_scorecard(scorecard: dict) -> dict:
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if supabase_url and "supabase.co" in supabase_url and supabase_key:
        try:
            from supabase import create_client
            sb = create_client(supabase_url, supabase_key)
            sb.table("weekly_scorecards").insert(scorecard).execute()
            return {"persisted": "supabase"}
        except Exception as e:
            console.print(f"[yellow]⚠️  Supabase no disponible. Guardando en .tmp/[/yellow]")

    path = TMP_DIR / f"scorecard_{scorecard['vendedor_id']}_{scorecard['semana_inicio']}.json"
    path.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False))
    return {"persisted": "local_tmp", "path": str(path)}


def main():
    parser = argparse.ArgumentParser(description="Generación de Scorecard Semanal SADIMEX")
    parser.add_argument("--vendedor_id", required=True, help="UUID del vendedor")
    parser.add_argument("--semana_inicio", required=True, help="Fecha inicio de semana (YYYY-MM-DD, lunes)")
    args = parser.parse_args()

    # Calcular semana_fin
    inicio = datetime.strptime(args.semana_inicio, "%Y-%m-%d")
    fin = inicio + timedelta(days=6)
    semana_fin = fin.strftime("%Y-%m-%d")

    console.print(f"\n[cyan]📋 Generando Scorecard:[/cyan] Vendedor {args.vendedor_id[:8]}... | Semana {args.semana_inicio} → {semana_fin}")

    try:
        # 1. Cargar análisis de la semana
        analyses = get_analyses_for_week(args.vendedor_id, args.semana_inicio, semana_fin)

        if not analyses:
            console.print(f"[yellow]⚠️  No se encontraron análisis para este vendedor en la semana {args.semana_inicio}.[/yellow]")
            print("\n", json.dumps({"status": "no_data", "vendedor_id": args.vendedor_id, "semana_inicio": args.semana_inicio}, indent=2))
            sys.exit(0)

        # 2. Calcular scorecard
        scorecard = compute_scorecard(args.vendedor_id, analyses, args.semana_inicio, semana_fin)

        # 3. Persistir
        persistence = persist_scorecard(scorecard)

        semaforo_color = {"verde": "green", "amarillo": "yellow", "rojo": "red"}.get(scorecard["semaforo_semana"], "white")
        console.print(
            f"[green]✅ Scorecard generado:[/green] "
            f"{scorecard['metricas_semana']['total_visitas']} visitas | "
            f"Score promedio: [{semaforo_color}]{scorecard['metricas_semana']['score_promedio']}/100[/{semaforo_color}] | "
            f"Semáforo: [{semaforo_color}]{scorecard['semaforo_semana'].upper()}[/{semaforo_color}] | "
            f"Tasa cierre: {scorecard['metricas_semana']['tasa_cierre']*100:.0f}%"
        )
        print("\n", json.dumps({"status": "ok", "scorecard_id": scorecard["id"], "result": scorecard}, indent=2, ensure_ascii=False))
        sys.exit(0)

    except Exception as e:
        console.print(f"[red]❌ Error generando scorecard:[/red] {e}")
        print("\n", json.dumps({"status": "error", "error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
