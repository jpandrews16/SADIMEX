# 🏛️ gemini.md — SADIMEX SALES INTELLIGENCE: Project Constitution

> **Status:** 🟡 BLUEPRINT PHASE — Schema locked. Awaiting user approval to begin execution.
> **Protocol:** B.L.A.S.T. | **Architecture:** A.N.T. 3-Layer
> **Last Updated:** 2026-02-21

---

## 1. North Star ⭐

> **"Un Scorecard de Ventas semanal automatizado por vendedor que identifique brechas de portafolio, efectividad de cierre y oportunidades de coaching, centralizado en un dashboard nacional multinivel."**

El objetivo final es **transformar la voz del mercado captada en terreno en KPIs accionables** para supervisores y gerencia. La unidad central de análisis es la **visita comercial de campo**, registrada como audio.

---

## 2. Integrations

| Servicio | Rol | Credenciales |
|---------|-----|-------------|
| **Gemini API 1.5 Flash/Pro** | Transcripción multimodal, diarización, extracción de KPIs, análisis de texto | ✅ Disponibles |
| **React (Antigravity Frontend)** | Dashboard multinivel (Gerente / Supervisor / Vendedor) | — |
| **Python Backend (Antigravity)** | Orquestación de herramientas, procesamiento de audio, API REST | — |
| **Sistema de Archivos Local** | Lectura de `.mp3`, `.wav`, `.m4a` desde dispositivo (flujo offline-first) | — |
| **BD Relacional (Supabase / SQLite)** | Jerarquía de usuarios, historial de análisis, knowledge base | — |
| **PDF / Google Sheets** | Exportación del Weekly Digest para supervisores *(opcional, Fase 4)* | Por definir |

---

## 3. Users & Access Control

| Rol | Ciudad Scope | Puede ver | Puede editar config |
|-----|-------------|-----------|-------------------|
| **Gerente General** | Nacional (LPZ + CBBA + SCZ) | Todo | ❌ No |
| **Supervisor** | Su ciudad únicamente | Solo su equipo | ❌ No |
| **Vendedor** | Su propia data | Solo su historial | ❌ No |

**Regla de acceso:** Un supervisor de CBBA **nunca** puede ver audios ni scorecards de LPZ o SCZ.

---

## 4. Data Schema (LOCKED — No coding before this is defined)

### 4.1 `AudioRecord` — Registro de Audio (Input)
```json
{
  "id": "uuid",
  "vendedor_id": "uuid",
  "ciudad": "LPZ | CBBA | SCZ",
  "fecha_visita": "ISO8601 datetime",
  "cliente_nombre": "string",
  "archivo_local_path": "string (.mp3/.wav/.m4a)",
  "duracion_segundos": "integer",
  "estado": "pendiente | procesando | completado | error",
  "created_at": "ISO8601 datetime"
}
```

### 4.2 `DiarizationSegment` — Diarización (Intermediate, stored in `.tmp/`)
```json
{
  "audio_id": "uuid",
  "segmentos": [
    {
      "speaker": "VENDEDOR | CLIENTE",
      "inicio_ms": "integer",
      "fin_ms": "integer",
      "texto": "string"
    }
  ]
}
```

### 4.3 `VisitAnalysis` — Análisis de Visita (Core Output)
```json
{
  "id": "uuid",
  "audio_id": "uuid",
  "vendedor_id": "uuid",
  "fecha_analisis": "ISO8601 datetime",
  "kpis": {
    "saludo_adecuado": "boolean",
    "marcas_mencionadas": ["string"],
    "marcas_faltantes": ["string"],
    "cierre_exitoso": "boolean",
    "tecnica_cierre_usada": "string | null",
    "quiebre_de_stock_detectado": "boolean",
    "precio_correcto": "boolean",
    "venta_perfecta_score": "0-100"
  },
  "coaching_insights": [
    {
      "categoria": "portafolio | cierre | relacion_cliente | precio | general",
      "observacion": "string",
      "sugerencia_tactica": "string"
    }
  ],
  "resumen_ejecutivo": "string (2-3 oraciones en español)",
  "score_visita": "0-100",
  "semaforo": "verde | amarillo | rojo"
}
```

### 4.4 `WeeklyScorecard` — Scorecard Semanal por Vendedor (Payload)
```json
{
  "id": "uuid",
  "vendedor_id": "uuid",
  "supervisor_id": "uuid",
  "semana_inicio": "YYYY-MM-DD",
  "semana_fin": "YYYY-MM-DD",
  "ciudad": "LPZ | CBBA | SCZ",
  "metricas_semana": {
    "total_visitas": "integer",
    "visitas_analizadas": "integer",
    "score_promedio": "float",
    "marcas_con_brecha": ["string"],
    "tasa_cierre": "float (0-1)",
    "quiebres_detectados": "integer",
    "venta_perfecta_rate": "float (0-1)"
  },
  "tendencia": "mejorando | estable | deteriorando",
  "coaching_prioritario": ["string (top 3 insights de la semana)"],
  "semaforo_semana": "verde | amarillo | rojo",
  "created_at": "ISO8601 datetime"
}
```

### 4.5 `KnowledgeBase` — Catálogo Sadimex (Source of Truth)
```json
{
  "marcas": [
    {
      "nombre": "string",
      "skus": ["string"],
      "precio_vigente": "float",
      "es_marca_prioritaria": "boolean"
    }
  ],
  "definicion_venta_perfecta": {
    "criterios": [
      {
        "nombre": "string",
        "peso_ponderacion": "float (0-1)",
        "descripcion": "string"
      }
    ]
  },
  "jerga_boliviana": ["caserita", "bono", "combo", "quiebre de stock", "..."]
}
```

### 4.6 `User` — Jerarquía de Usuarios
```json
{
  "id": "uuid",
  "nombre": "string",
  "email": "string",
  "rol": "gerente | supervisor | vendedor",
  "ciudad": "LPZ | CBBA | SCZ | ALL",
  "supervisor_id": "uuid | null",
  "activo": "boolean"
}
```

---

## 5. Behavioral Rules (LAW)

1. **Español siempre:** Todas las respuestas, insights, labels y UI strings deben ser en español.
2. **Jerga boliviana:** El modelo debe reconocer y no confundir las expresiones del canal tradicional boliviano (ver `KnowledgeBase.jerga_boliviana`).
3. **Tono de Consultor Senior:** Los `coaching_insights` nunca son punitivos. Siempre son sugerencias tácticas constructivas.
4. **Diarización antes de juicio:** El sistema no puede generar `VisitAnalysis` si los segmentos de `DiarizationSegment` no han sido etiquetados con speaker `VENDEDOR` o `CLIENTE`.
5. **Semáforo = Acción:** `rojo` implica intervención del supervisor en ≤ 48h. `amarillo` = coaching programado. `verde` = reconocimiento positivo.
6. **Acceso por ciudad es hardcoded en el backend:** El frontend no controla esto. La lógica de filtro de ciudad va en la API, no en el cliente.
7. **El Gerente no puede editar config:** Solo lectura. La configuración del sistema (umbral de semáforo, pesos de venta perfecta) la edita el Administrador del sistema.

---

## 6. Architectural Invariants (ALWAYS ACTIVE)

1. No scripts en `tools/` hasta que este schema esté aprobado.
2. Todas las credenciales en `.env`. Cero hardcoding.
3. Archivos intermedios (transcripciones crudas, diarizaciones) en `.tmp/`.
4. Cuando un tool falla: Analizar → Parchear → Testear → Actualizar SOP en `architecture/`.
5. El proyecto es "Completo" solo cuando el Scorecard está en su destino cloud final.

---

## 7. Maintenance Log

| Fecha | Evento | Autor |
|-------|--------|-------|
| 2026-02-21 | Constitución inicializada (skeleton) | System Pilot |
| 2026-02-21 | Schema LOCKED tras Discovery completo | System Pilot |
