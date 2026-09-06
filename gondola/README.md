# 🛒 Lector de Góndola — SADIMEX

Audita la ejecución en sala a partir de una foto: qué SKU nuestros están,
a qué altura, con cuántos frentes, cuánto espacio ocupamos frente al total
del lineal, y si las etiquetas de precio están puestas y correctas.

Módulo independiente del pipeline de audio. Comparte la misma base
Supabase y el mismo modelo de acceso por ciudad. Se despliega aparte en
Railway para que la carga de imágenes no toque lo que ya está en producción.

---

## Las 6 reglas

Pocas, claras, y todas medibles desde una foto. Si algo no se puede
auditar mirando la imagen, no es una regla de este software.

| # | Regla | Qué mide | Peso |
|---|-------|----------|------|
| 1 | **presencia** | El SKU obligatorio está en la góndola | 30% |
| 2 | **nivel** | Está a la altura objetivo (ojos / manos) | 20% |
| 3 | **frentes** | Cumple los frentes mínimos y el share of shelf | 20% |
| 4 | **bloque** | Los SKU de la marca van contiguos, no dispersos | 10% |
| 5 | **etiqueta** | Etiqueta presente, legible y con el precio correcto | 15% |
| 6 | **sin_quiebre** | Sin huecos en nuestro espacio y producto frenteado | 5% |

Los pesos viven en la tabla `gondola_pesos` y se cambian sin tocar código.
Score de 0 a 100 → semáforo verde (≥80) / amarillo (60-79) / rojo (<60),
los mismos umbrales que el módulo de audio.

---

## La decisión de diseño que sostiene todo

**El modelo de IA observa. El código juzga.**

```
foto ──▶ modelo de visión ──▶ Observacion ──▶ rules.py ──▶ Evaluacion
                              (qué hay)      (Python puro)  (score + hallazgos)
```

Al modelo nunca se le pregunta "¿está bien ejecutada esta góndola?". Se le
pregunta "¿qué ves, dónde, y cuántos frentes?". El veredicto lo calcula
`rules.py`, en Python, sin IA. Esto compra tres cosas:

1. **Reproducibilidad** — la misma foto da siempre el mismo número.
2. **Recálculo gratis** — si cambian las reglas o los pesos, se recalcula
   el histórico completo sin pagar una sola llamada de visión de nuevo.
3. **Defendibilidad** — cuando un reponedor reclame su nota, cada punto
   sale de una regla escrita, no de la opinión de un modelo.

Además, una regla que la foto no permite evaluar (por ejemplo la altura,
cuando el mueble sale cortado) **se saca del denominador del score**.
Nunca se castiga a alguien por algo que la foto no dejaba ver.

---

## Cómo se logra precisión sin revisión humana

El flujo es 100% automático. Tres mecanismos sostienen el acierto:

1. **Hoja de referencia visual.** En vez de mandar N packshots (N veces el
   costo), se arma **una sola imagen** tipo mosaico con el envase de cada
   SKU rotulado con su código, y se envía antes de la foto de góndola. Es
   lo que distingue "Wild Protein Fresa" de "Wild Protein Vainilla" cuando
   solo cambia el color de la banda.

2. **Escalado automático de modelo.** Toda foto pasa por el modelo barato.
   Solo si el propio modelo reporta baja confianza (o la foto salió mala)
   se reintenta con el modelo grande. El costo promedio queda cerca del
   barato y el acierto cerca del caro.

3. **Saneamiento estricto.** Un SKU que no está en el catálogo se descarta
   antes de llegar al motor de reglas. El modelo no puede inventar
   productos nuestros donde no los hay.

> Nota honesta: esto rinde bien, pero no es 99% a nivel SKU en cualquier
> condición. Con fotos correctas y packshots cargados el acierto es alto;
> con contraluz, reflejo de tubo fluorescente o mueble cortado, baja. Por
> eso cada análisis guarda `confianza_global` y `calidad_foto`: **filtra
> los reportes por confianza antes de tomar decisiones de personal.**

---

## Integridad de la evidencia

Evaluar reponedores por foto sin esto es un sistema de honor: basta con
resubir la foto buena de la semana pasada. Cada foto se valida por

- **hash SHA-256** — un archivo idéntico ya subido antes se marca como
  posible reciclaje;
- **GPS contra las coordenadas de la sala** — fuera del radio configurado
  se marca la distancia;
- **ausencia de geolocalización** — también se marca.

Las alertas quedan en `gondola_photos.alerta_captura`. No bloquean el
análisis: lo dejan auditable.

---

## Estructura

```
gondola/
├── app/
│   ├── config.py           Variables de entorno (modelos, umbrales, límites)
│   ├── schemas.py          Contratos: Observacion (qué se ve) vs Evaluacion (veredicto)
│   ├── catalog.py          Catálogo + resolución de reglas y precios por jerarquía
│   ├── reference_sheet.py  Mosaico de packshots + normalizado de la foto
│   ├── prompt.py           Prompt de observación + JSON schema estricto
│   ├── vision.py           Cliente OpenRouter con escalado de modelo
│   ├── rules.py            ★ Motor determinístico de las 6 reglas
│   ├── pipeline.py         Orquestación foto → análisis persistido
│   ├── worker.py           Consumidor de la cola
│   └── main.py             API FastAPI
├── tools/
│   └── comparar_modelos.py Compara modelos sobre TUS fotos con métricas reales
├── tests/                  56 tests del motor de reglas, evidencia y saneamiento
├── catalogo.ejemplo.json   Catálogo de arranque
├── Dockerfile
├── railway.json            Servicio API
└── railway.worker.json     Servicio worker
```

---

## Puesta en marcha

### 1. Migración

Aplica `migrations/003_gondola_schema.sql` en Supabase. Crea las tablas,
las políticas RLS por ciudad, las vistas de ranking y el RPC
`gondola_reclamar_foto` (con `SKIP LOCKED`, así se pueden correr varios
workers en paralelo sin que dos tomen la misma foto).

También agrega el rol `reponedor` a `sadimex_profiles`.

### 2. Storage

Crea el bucket `gondola-fotos` en Supabase Storage. El frontend sube la
foto directo ahí, igual que hoy hace con los audios.

### 3. Catálogo

Carga `gondola_skus` con tus SKU reales. Dos campos deciden la precisión:

- `packshot_url` — foto del envase. Es lo que arma la hoja de referencia.
- `descripcion_visual` — los rasgos que distinguen la variante.
  Escribe *"pote negro con banda rosada y la palabra FRESA"*, no
  *"proteína sabor fresa"*. El modelo ve colores y formas, no sabores.

Después `gondola_precios` (sin PVP no se puede juzgar si un precio está
mal, solo si la etiqueta falta o es ilegible) y `gondola_reglas`.

### 4. Railway

Dos servicios sobre el mismo repo y el mismo `Dockerfile`:

| Servicio | Start command | Config |
|----------|---------------|--------|
| API | `uvicorn gondola.app.main:app --host 0.0.0.0 --port $PORT` | `railway.json` |
| Worker | `python -m gondola.app.worker` | `railway.worker.json` |

Variables de entorno en ambos:

```
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_BUCKET=gondola-fotos
OPENROUTER_API_KEY=...
MODELO_PRIMARIO=google/gemini-2.5-flash-lite
MODELO_ESCALADO=google/gemini-2.5-flash
UMBRAL_ESCALADO=0.75
UMBRAL_DETECCION=0.60
```

El worker escala horizontalmente subiendo réplicas; no requiere ningún
cambio de código.

---

## Elegir el modelo con datos

No elijas por benchmark público: una góndola de Ketal con reflejo de tubo
fluorescente no se parece a nada de un benchmark.

```bash
python -m gondola.tools.comparar_modelos \
    --fotos ./fotos_anotadas \
    --catalogo gondola/catalogo.ejemplo.json \
    --modelos google/gemini-2.5-flash-lite,qwen/qwen3-vl-32b-instruct,google/gemini-2.5-flash
```

Anota a mano unas 20-30 fotos (un `.json` al lado de cada `.jpg` con los
SKU que de verdad estaban) y la herramienta reporta precisión, recall,
acierto de nivel, acierto de precio, USD por cada 1.000 fotos y latencia.

**Prioriza recall.** Un falso quiebre manda a un supervisor a una sala
donde no había problema, y eso quema la confianza en el sistema más rápido
que cualquier otra cosa.

Precios de referencia en OpenRouter (USD por millón de tokens de entrada,
verificados contra su API — cámbialos por lo que te dé la comparación):

| Modelo | Entrada | Salida |
|--------|---------|--------|
| `google/gemini-2.5-flash-lite` | 0.10 | 0.40 |
| `qwen/qwen3-vl-32b-instruct` | 0.104 | 0.416 |
| `qwen/qwen3-vl-8b-instruct` | 0.117 | 0.455 |
| `google/gemini-2.5-flash` | 0.30 | 2.50 |
| `google/gemini-3.1-flash-lite` | 0.25 | 1.50 |

> OpenRouter cobra un margen sobre el proveedor. Ya tienes una API key de
> Gemini directa en el proyecto: si al final el ganador resulta ser un
> modelo de Google, llamarlo directo sale más barato. `vision.py` está
> aislado detrás de una función, así que cambiar de proveedor es tocar un
> solo archivo.

---

## API

| Método | Ruta | Para qué |
|--------|------|----------|
| `GET` | `/health` | Healthcheck de Railway |
| `POST` | `/api/gondola/fotos` | Encola una foto ya subida al Storage |
| `POST` | `/api/gondola/fotos/{id}/analizar` | Fuerza el análisis sin esperar al worker |
| `GET` | `/api/gondola/analisis/{photo_id}` | Resultado (o el estado si sigue en cola) |
| `GET` | `/api/gondola/catalogo` | Catálogo activo, para armar la UI |

### Ejemplo de resultado

```json
{
  "score": 72,
  "semaforo": "amarillo",
  "share_of_shelf_pct": 18.5,
  "quiebres_detectados": 1,
  "reglas": {
    "presencia": { "cumple": false, "cumplimiento": 0.75,
                   "detalle": "Faltan: WILD-VAINILLA" },
    "etiqueta":  { "cumple": false, "cumplimiento": 0.83,
                   "detalle": "NOEL-FESTIVAL-200: 15.9 BOB vs PVP 12.5 (27.2% sobre)" }
  },
  "hallazgos": [
    {
      "severidad": "critico",
      "regla": "etiqueta",
      "sku_codigo": "NOEL-FESTIVAL-200",
      "mensaje": "Galletas Festival 200g exhibido a 15.9 contra PVP 12.5 (27.2% de desvío).",
      "accion": "Corregir el precio en caja y en el riel el mismo día."
    }
  ]
}
```

Los `hallazgos` vienen ordenados por severidad: son la lista de tareas del
supervisor, no un informe para leer.

---

## Reportes listos

Dos vistas SQL creadas por la migración:

- `gondola_ranking_reponedores` — score promedio, fotos verdes/rojas,
  share promedio, quiebres y salas cubiertas por reponedor (30 días).
- `gondola_salud_salas` — estado por sucursal. `ultima_auditoria` en NULL
  es una sala que nadie visitó.

---

## Tests

```bash
python -m pytest gondola/tests -q
```

56 tests, sin red ni base de datos. Cubren el motor de reglas (incluidos
los casos que protegen al reponedor: sin PVP cargado no se penaliza, sin
mueble completo no se evalúa la altura), la jerarquía de resolución de
reglas y precios, y el saneamiento de la respuesta del modelo.

---

## Qué falta para que esto sea completo

Estos puntos dependen de datos que todavía no están en el repo:

1. **Catálogo real** — hoy solo hay 6 SKU de ejemplo (Noel, Wild Protein).
2. **Packshots** — sin ellos la hoja de referencia no se arma y la
   precisión entre variantes cae.
3. **Lista de PVP por cadena** — sin ella no se audita el monto del precio.
4. **Maestro de salas con GPS** — sin coordenadas no hay validación de
   ubicación.
5. **Rutas y frecuencias** — permitiría medir cumplimiento de visita, no
   solo calidad de ejecución. Requiere una tabla nueva.
6. **Captura offline** — dentro del súper suele no haber señal; hoy el
   frontend asume conexión al subir.
