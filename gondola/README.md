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

2. **Consenso de dos lecturas baratas.** Toda foto pasa una vez por el
   modelo barato. Se pide una **segunda lectura al mismo modelo barato**
   —con un método de conteo distinto: recorrido bandeja por bandeja de
   abajo hacia arriba— cuando la primera reporta algo que sería caro si
   fuera falso. Solo si se contradicen de verdad se paga el modelo grande.

   **Qué dispara la verificación, y por qué no es la confianza del modelo.**
   En la primera prueba real, Qwen se declaró 95% seguro y reportó 12
   huecos que no existían. La autoevaluación de un modelo no mide su
   acierto. Lo que sí sirve es verificar **cuando equivocarse sale caro**
   (`riesgo.py`):

   | Señal en la primera lectura | Qué pasa si es falsa |
   |---|---|
   | Reporta un hueco | Un supervisor va a una sala donde no había problema |
   | Precio fuera de tolerancia | Se acusa a la sala de algo que no hizo |
   | Falta un SKU prioritario | Se dispara una reposición de urgencia en vano |

   Los tres cuestan trabajo humano y credibilidad, que valen mucho más que
   la décima de centavo de una segunda lectura. Una foto limpia se queda
   con una sola. En la prueba real, este cambio descartó **10 de los 12
   huecos inventados**.

   Esto es mejor *y* más barato que escalar directo:
   - Dos llamadas al chico cuestan menos que una al grande, sobre todo en
     tokens de salida (0.416 vs 1.90 por millón en Qwen3-VL 32B vs 235B).
   - El acuerdo entre dos lecturas independientes es mejor evidencia que
     la autoevaluación del modelo: un modelo puede estar seguro y
     equivocado, pero es raro que se equivoque igual dos veces con
     métodos distintos.
   - Donde no coinciden, sabemos exactamente qué **no** creer.

   La fusión (`consenso.py`) es conservadora donde el error es caro:

   | Situación | Qué hace | Por qué |
   |-----------|----------|---------|
   | SKU visto por una sola lectura | Confianza × 0.6 → deja de contar | No afirmar que un producto está |
   | Frentes distintos (4 vs 6) | Promedia | Contar unidades en fila es lo que peor hace un LLM |
   | Hueco visto por una sola | Se descarta | Un falso quiebre manda a un supervisor a una sala sin problema |
   | Precios distintos en la misma etiqueta | Descarta el precio, marca "ilegible" | Acusar a una sala de tener el precio mal por un dígito mal leído es el error más caro posible |
   | Una dice que el mueble sale cortado | No se evalúa la altura | No castigar por lo que la foto no dejaba ver |

   La confianza final no es el promedio: es el promedio **corregido por
   cuánto coincidieron**. Dos lecturas seguras que se contradicen dan
   confianza baja, que es lo correcto.

   Se controla con `ESTRATEGIA_BAJA_CONFIANZA` (`consenso` por defecto,
   `escalado` o `ninguna`), y `gondola_efecto_consenso` muestra cuántas
   fotos necesitan verificarse y qué cuesta eso.

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
│   ├── vision.py           Cliente OpenRouter: 1 lectura, o 2 en consenso
│   ├── riesgo.py           ★ Cuándo vale la pena leer la foto dos veces
│   ├── consenso.py         ★ Fusión conservadora de dos lecturas
│   ├── rules.py            ★ Motor determinístico de las 6 reglas
│   ├── pipeline.py         Orquestación foto → análisis persistido
│   ├── worker.py           Consumidor de la cola
│   ├── auth.py             Autorización por rol de los endpoints admin
│   ├── admin.py            Carga de catálogo y precios por cadena (CSV)
│   └── main.py             API FastAPI
├── tools/
│   ├── comparar_modelos.py         Compara modelos sobre TUS fotos con métricas reales
│   ├── importar_catalogo_canva.py  PDF de Canva → packshots + catálogo CSV
│   ├── normalizar_marcas.py        Unifica marcas escritas de varias formas
│   └── probar_foto.py              Analiza una foto sin base de datos
├── tests/                  182 tests: reglas, consenso, evidencia, costos, CSV
├── catalogo.ejemplo.json   Catálogo de arranque
├── Dockerfile
├── railway.json            Servicio API
└── railway.worker.json     Servicio worker
```

---

## Puesta en marcha

### 1. Migración

Aplica en Supabase, en este orden:

| Archivo | Qué crea |
|---------|----------|
| `003_gondola_schema.sql` | Tablas, RLS por ciudad, vistas de ranking, rol `reponedor` y el RPC `gondola_reclamar_foto` (con `SKIP LOCKED`, así corren varios workers sin que dos tomen la misma foto) |
| `004_gondola_cadenas_precios.sql` | Cadenas (Fidalga, Hipermaxi, Tía, IC Norte), carga de precios con historial y vistas de cobertura y costo |
| `005_gondola_consenso.sql` | Trazabilidad del consenso: cuántas lecturas por foto y qué pasó al fusionarlas |

### 2. Storage

Crea el bucket `gondola-fotos` en Supabase Storage. El frontend sube la
foto directo ahí, igual que hoy hace con los audios.

### 3. Catálogo — desde Canva, en un paso

El diseño de producto ya vive en Canva, una página por SKU. No hay que
transcribirlo a mano.

**El script corre en tu máquina, no en un servidor.** El PDF puede pesar
cientos de MB y nunca se sube a ningún lado: se procesa local y solo
viajan los packshots ya reducidos, a tu propio Storage.

```bash
# Canva → Archivo → Descargar → PDF estándar → todas las páginas
pip install -r gondola/requirements-tools.txt
export OPENROUTER_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...

# Probar con 5 páginas antes de gastar en todas
python -m gondola.tools.importar_catalogo_canva \
    --pdf ~/Descargas/PRODUCTOS_SDX.pdf --salida ./packshots --limite 5

# Si se ve bien, correr todo
python -m gondola.tools.importar_catalogo_canva \
    --pdf ~/Descargas/PRODUCTOS_SDX.pdf \
    --salida ./packshots \
    --categoria cafe \
    --subir
```

Esto corta el PDF en un PNG por producto, descarta las páginas en blanco
del diseño, recorta el fondo de Canva, sube cada packshot al Storage, y le
pide al modelo barato que lea cada envase para armar un **CSV borrador**
con marca, nombre, gramaje y `descripcion_visual`. La columna `revisar`
marca las filas donde la IA no estuvo segura.

**Es reanudable y nada se paga dos veces.** Los PNG extraídos y las
descripciones ya pagadas quedan en la carpeta de salida y se reutilizan.
Si se corta la conexión o cancelas con Ctrl-C, vuelve a correr el mismo
comando y sigue donde quedó. Para trabajar por tandas: `--desde 1 --hasta
100`, luego `--desde 101`; el CSV final se arma siempre con todos los
packshots de la carpeta, no solo con el último lote.

`--solo-extraer` corta el PDF en imágenes sin llamar a la IA, por si
quieres revisar el recorte antes de gastar.

Revisa el CSV —sobre todo la columna `codigo`, que debe quedar con el
código real de tu ERP— y cárgalo:

```bash
curl -X POST https://<servicio>.railway.app/api/gondola/admin/catalogo/csv \
     -H "Authorization: Bearer <jwt de un admin>" \
     -F archivo=@./packshots/catalogo.csv
```

También acepta `--imagenes ./carpeta` si prefieres exportar PNG de Canva.

Dos campos deciden la precisión del lector:

- `packshot_url` — foto del envase. Es lo que arma la hoja de referencia.
- `descripcion_visual` — los rasgos que distinguen la variante.
  *"frasco de vidrio con tapa verde y etiqueta roja"*, no
  *"café descafeinado"*. El modelo ve colores y formas, no sabores.

`GET /api/gondola/admin/catalogo/cobertura` dice cuánto del catálogo tiene
packshot: donde ese porcentaje sea bajo, el modelo no tendrá con qué
distinguir variantes parecidas.

### 3b. Precios por cadena

El administrador sube su planilla tal como la tiene. Columnas:
`sku_codigo, cadena, pvp` (más `moneda` y `tolerancia_pct` si hacen falta).
Dejar `cadena` vacía carga el **precio nacional**, que aplica donde la
cadena no tenga uno propio.

```csv
sku_codigo,cadena,pvp
COLCAFE-LIGERO-200G,Fidalga,42.50
COLCAFE-LIGERO-200G,Hipermaxi,44.90
COLCAFE-LIGERO-200G,Tía,43.00
COLCAFE-LIGERO-200G,IC Norte,44.00
NOEL-SALTIN-250,,15.00
```

```bash
curl -X POST https://<servicio>.railway.app/api/gondola/admin/precios/csv \
     -H "Authorization: Bearer <jwt de un admin>" \
     -F archivo=@precios_septiembre.csv
```

Acepta coma decimal, `;` como separador y el BOM que mete Excel en
Windows. Responde cuántos precios se crearon, se actualizaron, ya estaban
iguales y cuáles fallaron y por qué.

El precio anterior **no se borra, se cierra** (`vigente_hasta`): un
análisis de la semana pasada sigue siendo auditable contra el PVP que
regía ese día. `GET /api/gondola/admin/precios/faltantes` lista los SKU sin
precio — para esos se audita si la etiqueta está y es legible, pero no si
el monto es correcto.

Por último, `gondola_reglas` define qué se le exige a cada SKU (ver la
sección de reglas arriba).

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
MODELO_PRIMARIO=qwen/qwen3-vl-32b-instruct
MODELO_ESCALADO=qwen/qwen3-vl-235b-a22b-instruct
UMBRAL_ESCALADO=0.75
UMBRAL_DETECCION=0.60
ESCALADO_MAX_FRACCION_DIARIA=0.20
PACKSHOT_MAX_EN_HOJA=24
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

| Modelo | Entrada | Salida | |
|--------|---------|--------|---|
| `qwen/qwen3-vl-32b-instruct` | 0.104 | 0.416 | **primario por defecto** |
| `qwen/qwen3-vl-8b-instruct` | 0.117 | 0.455 | |
| `qwen/qwen3-vl-235b-a22b-instruct` | 0.21 | 1.90 | **escalado por defecto** |
| `google/gemini-2.5-flash-lite` | 0.10 | 0.40 | |
| `google/gemini-2.5-flash` | 0.30 | 2.50 | |

> OpenRouter cobra un margen sobre el proveedor. Ya tienes una API key de
> Gemini directa en el proyecto: si al final el ganador resulta ser un
> modelo de Google, llamarlo directo sale más barato. `vision.py` está
> aislado detrás de una función, así que cambiar de proveedor es tocar un
> solo archivo.

---

## Control de costo con volumen alto

Muchas categorías y muchas fotos hacen que la factura sea un KPI
operativo, no un detalle. Tres perillas la gobiernan:

**1. El tope de la hoja de referencia (`PACKSHOT_MAX_EN_HOJA`, default 24).**
El mosaico viaja en *cada* llamada, así que sus tokens de imagen se pagan
en todas las fotos. Con un catálogo de cientos de SKU el mosaico sería el
costo dominante. El sistema corta en el tope, priorizando los SKU marcados
como prioritarios, y avisa en el log cuáles quedaron fuera.
La solución real cuando eso pasa es **dividir la categoría**: una foto de
la góndola de café no necesita los packshots de galletas.

**2. El umbral de escalado (`UMBRAL_ESCALADO`, default 0.75).**
Subirlo escala más fotos al modelo grande y mejora el acierto; bajarlo
abarata. Su efecto se ve directamente en `gondola_costos_diarios`.

**3. El tope de escalado diario (`ESCALADO_MAX_FRACCION_DIARIA`, default 0.20).**
Un lote de fotos malas —una sala con contraluz, un reponedor nuevo— puede
mandar todo al modelo caro y multiplicar el gasto del día sin que nadie se
entere. Este tope corta el escalado al pasar del 20% de las fotos del día.
Se ve en vivo en `/health`.

Cada análisis guarda su costo real (el que reporta OpenRouter), así que
`GET /api/gondola/admin/costos` responde con datos, no con estimaciones.

---

## API

| Método | Ruta | Para qué |
|--------|------|----------|
| `GET` | `/health` | Healthcheck de Railway + estado de la cuota de escalado |
| `POST` | `/api/gondola/fotos` | Encola una foto ya subida al Storage |
| `POST` | `/api/gondola/fotos/{id}/analizar` | Fuerza el análisis sin esperar al worker |
| `GET` | `/api/gondola/analisis/{photo_id}` | Resultado (o el estado si sigue en cola) |
| `GET` | `/api/gondola/catalogo` | Catálogo activo, para armar la UI |

### Administración

Escribir exige rol `admin`; leer, rol `gerente` o `admin`. La autorización
usa el mismo JWT que ya emite Supabase Auth en el frontend, y se valida
contra Supabase en cada llamada (una sesión revocada deja de funcionar de
inmediato). Sin esto, cualquiera que alcanzara la URL de Railway podría
cambiar precios: el servicio corre con `service_role`.

| Método | Ruta | Para qué |
|--------|------|----------|
| `POST` | `/api/gondola/admin/precios/csv` | Carga masiva de PVP por cadena |
| `POST` | `/api/gondola/admin/precios` | Lo mismo, en JSON |
| `GET` | `/api/gondola/admin/precios` | Precios vigentes (filtrable por cadena) |
| `GET` | `/api/gondola/admin/precios/faltantes` | SKU sin PVP cargado |
| `POST` | `/api/gondola/admin/catalogo/csv` | Carga masiva de SKU |
| `GET` | `/api/gondola/admin/catalogo/cobertura` | % del catálogo con packshot |
| `GET` | `/api/gondola/admin/cadenas` | Fidalga, Hipermaxi, Tía, IC Norte |
| `GET` | `/api/gondola/admin/costos` | Gasto de IA por día, ciudad y modelo |

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

Vistas SQL creadas por las migraciones:

| Vista | Responde |
|-------|----------|
| `gondola_ranking_reponedores` | Score, fotos verdes/rojas, share, quiebres y salas cubiertas por reponedor (30 días) |
| `gondola_salud_salas` | Estado por sucursal. `ultima_auditoria` en NULL = sala sin visitar |
| `gondola_precios_vigentes` | Qué PVP rige hoy por SKU y cadena |
| `gondola_skus_sin_precio` | Qué falta cargar para poder auditar montos |
| `gondola_cobertura_catalogo` | % del catálogo con packshot, por categoría |
| `gondola_costos_diarios` | Gasto de IA por día, ciudad y modelo |

---

## Tests

```bash
python -m pytest gondola/tests -q
```

182 tests, sin red ni base de datos. Cubren el motor de reglas (incluidos
los casos que protegen al reponedor: sin PVP cargado no se penaliza, sin
mueble completo no se evalúa la altura), la jerarquía de resolución de
reglas y precios, el saneamiento de la respuesta del modelo, la validación
anti-fraude, los controles de costo y el parseo de las planillas de Excel.

---

## Qué falta para que esto sea completo

Estos puntos dependen de datos que todavía no están en el repo:

1. **Catálogo real** — el importador de Canva lo resuelve en un paso, pero
   hay que correrlo y revisar los códigos sugeridos.
2. **Lista de PVP por cadena** — el endpoint está listo; falta la planilla.
3. **Maestro de salas con GPS** — sin coordenadas no hay validación de
   ubicación, y el anti-fraude queda solo con el hash.
4. **Rutas y frecuencias** — permitiría medir cumplimiento de visita, no
   solo calidad de ejecución. Requiere una tabla nueva.
5. **Captura offline** — dentro del súper suele no haber señal; hoy el
   frontend asume conexión al subir.
6. **Deploy** — el código está listo; falta aplicar las migraciones en
   Supabase y levantar los dos servicios en Railway.

---

## Frontend

Dos pantallas nuevas en la app de Vercel, con el rol `reponedor` sumado al
sistema de usuarios:

| Vista | Quién | Qué hace |
|-------|-------|----------|
| **Auditar Góndola** (`gondola-captura`) | reponedor, supervisor, admin | Elegir sala y categoría, tomar la foto y ver el resultado |
| **Ejecución en Sala** (`gondola-dashboard`) | supervisor, gerente, admin | Qué corregir, ranking de reponedores, salud por sala, historial |

La pantalla de captura está pensada para usarse **de pie frente al mueble,
con una mano, en un supermercado con mala señal**: dos selectores, un botón
grande de cámara (`capture="environment"` abre la cámara directo en el
celular) y el GPS se pide al abrir la pantalla, no al enviar, para no hacer
esperar. Si el reponedor niega el permiso la foto se sube igual y queda
marcada como "sin geolocalización" en vez de bloquearse.

El tablero abre en **"Qué corregir"**, no en gráficos: lo primero que un
supervisor necesita es la lista de lo que hay que ir a arreglar hoy,
ordenada por severidad y con la sala de cada hallazgo.

Requiere `VITE_GONDOLA_API_URL` apuntando al servicio de Railway. Si falta,
la pantalla lo dice en lugar de fallar en silencio.
