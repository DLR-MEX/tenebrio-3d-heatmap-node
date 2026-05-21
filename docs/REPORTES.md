# Reportes Ejecutivos PDF

> **Rama**: `feature/reportes-ejecutivos` (pendiente merge a `main`)
> **Estado**: 6 fases completas, listo para producción

El agente IA puede generar reportes ejecutivos en PDF a demanda o de forma programada. Los reportes incluyen portada, resumen ejecutivo, gráficas, estadísticas por sensor, eventos destacados, precisión del modelo, estado de infraestructura externa y recomendaciones — todo con narrativa redactada por IA.

## Cómo usarlo

### Desde el chat del dashboard

Escríbele al agente cualquiera de estas frases (o equivalentes):

- *"Genera un reporte PDF de las últimas 24 horas"*
- *"Quiero un informe ejecutivo de la última semana"*
- *"Reporte del periodo del 1 al 7 de mayo"*
- *"Genera un reporte y mándalo a Telegram"*

El agente invoca la herramienta `generate_report`, que tarda **30-60 segundos** (recolecta datos, genera 4 gráficas con matplotlib, pide al LLM redactar 4 secciones de narrativa, renderiza HTML→PDF con Playwright). Al terminar, el chat muestra una tarjeta con preview de la primera página y botón de descarga.

### Desde Telegram

Manda al bot:

- *"reporte últimas 24 horas"* → el agente genera el PDF y lo envía como documento adjunto (sendDocument) con caption = resumen ejecutivo.

### Programar reportes recurrentes

- *"Prográmame un reporte diario a las 8am"*
- *"Quiero un reporte semanal los lunes a las 9am, mándamelo a Telegram"*
- *"¿Qué reportes tengo programados?"*
- *"Cancela el reporte semanal"*

El scheduler usa APScheduler con persistencia SQLite — los jobs **sobreviven reinicios del sidecar**.

Expresiones amigables soportadas (en español):

```
diario 8am
diario 9:30
lunes 7am
martes 6:30pm
viernes 10am
```

O cron estándar directo: `0 8 * * *`, `0 9 * * 1`, etc.

## Endpoints REST

### Reportes

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/predictor/reports/generate` | Genera un reporte. Body: `{hours?, start_iso?, end_iso?, title?, include_commentary?}`. Devuelve metadata + URL. Tarda 30-60s. |
| `GET` | `/api/predictor/reports` | Lista los últimos 50 reportes guardados. |
| `GET` | `/api/predictor/reports/<id>` | Descarga el PDF binario. |
| `GET` | `/api/predictor/reports/<id>/preview` | PNG de la primera página. |

### Schedules

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/schedules` | Lista schedules activos. |
| `POST` | `/api/schedules` | Crea schedule. Body: `{name, cron \| friendly_cron, period_kind, deliver_to?, title?}`. |
| `DELETE` | `/api/schedules/<id>` | Cancela schedule. |

Nota: los endpoints REST viven en el sidecar (`http://127.0.0.1:8001`). Desde el browser/dashboard se accede vía el proxy de Express en `http://localhost:5000/api/predictor/*`.

## Contenido de un reporte

Un reporte típico tiene **7-8 páginas**:

1. **Portada** (fondo dorado/oscuro estilo dashboard): logo, periodo, dispositivo, cards con alertas críticas, saltos abruptos, % temp y humedad en rango.
2. **Resumen ejecutivo** + estado actual del cuarto (tabla de sensores con códigos de color) + estratificación térmica (tps/tpi).
3. **Temperatura**: gráfica timeline t1-t5 con umbrales rojos punteados (15-30°C) + tabla de stats por sensor (min/max/avg/% fuera de rango).
4. **Humedad**: igual para h1-h5 (umbrales 60-90%).
5. **Eventos destacados**: análisis del LLM + bar chart de alertas por sensor + tabla cronológica de transiciones + tabla de saltos abruptos.
6. **Precisión del modelo**: bar chart MAE por sensor + tabla con MAE/RMSE/n.
7. **Infraestructura externa**: análisis del LLM (correlaciona temp del termo con calentador solar, etc.) + tablas por categoría (calefacción, ventilación, calidad de aire).
8. **Recomendaciones** (con disclaimer): 3-5 puntos accionables redactados por el LLM.

Cada página tiene footer con número de página, branding y fecha de generación.

## Configuración

En `ai-predictor/.env`:

```bash
# Genera reportes con commentary del LLM. Requiere OLLAMA_API_KEY.
# Si está desactivado, el reporte sale con narrativa estática (fallbacks).
AGENT_ENABLED=true
OLLAMA_API_KEY=tu_key

# Telegram (para entrega de reportes programados con deliver_to=['telegram'])
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### Persistencia

| Ruta | Contenido |
|---|---|
| `ai-predictor/reports/output/*.pdf` | PDFs generados (gitignored, TTL 30 días) |
| `ai-predictor/reports/output/*.preview.png` | Previews PNG (mismo TTL) |
| `ai-predictor/reports/jobs.sqlite` | Schedules persistidos (gitignored) |

El cleanup automático corre al iniciar el sidecar: archivos `>30 días` se borran.

## Costos estimados

Por reporte con commentary completo (4 llamadas al LLM):
- Ollama Cloud `gpt-oss:120b`: ~5-10K tokens total ≈ **$0.02-0.05 por reporte**
- Sin LLM commentary (parámetro `include_commentary=false`): $0

Casos típicos:
- 1 reporte diario × 30 días: ≈ **$0.60-1.50/mes**
- 1 reporte semanal × 4: ≈ **$0.10/mes**

## Tecnologías usadas

| Componente | Librería | Por qué |
|---|---|---|
| HTML → PDF | **Playwright** (chromium headless) | Soporta CSS3 completo (@page, page-break-*, paginación). Self-contained en Windows (vs WeasyPrint que necesita GTK). |
| Templating | **Jinja2** | Standard FastAPI, simple. |
| Gráficas | **matplotlib** (Agg backend) | Ya en deps. Server-side, estilo coherente con dashboard. |
| Scheduling | **APScheduler 3.x** + **SQLAlchemyJobStore** | Cron jobs persistentes en SQLite. Sobrevive reinicios. |
| Preview PNG | **pypdfium2** | Pure Python, sin dependencias externas (vs poppler/wkhtmltopdf). |
| LLM commentary | **Ollama Cloud** (`gpt-oss:120b`) | Mismo cliente que el resto del agente. |

## Arquitectura

```
Usuario → Chat / Telegram
              ↓
        AgentService
              ↓ tool generate_report
        ┌────────────────┐
        │ Collector      │  ← AlertLog + Ubidots HTTP + snapshot
        │ Charts         │  ← matplotlib (4 charts en base64)
        │ Commentary     │  ← Llamadas LLM (4 secciones)
        │ Render         │  ← Jinja2 + Playwright
        │ Save           │  ← reports/output/yyyy-mm-dd_<hash>.pdf
        │ Preview        │  ← pypdfium2 → PNG
        └────────────────┘
              ↓
        report_card → response al cliente
              ↓
        Widget: tarjeta + preview + descarga
        Telegram: sendDocument + caption
              ↓
        Scheduler ← APScheduler ← cron / friendly_cron
        (jobs en reports/jobs.sqlite)
```

## Limitaciones conocidas

- **Rango máximo**: 31 días por reporte. Periodos más largos hay que pedirlos fraccionados.
- **Generación**: 30-60s con LLM commentary, 5-10s sin. Mostramos al usuario que va a tardar.
- **Playwright**: ~150MB de chromium descargado una vez (vía `playwright install chromium`). Self-contained después.
- **Ollama 5xx**: si el provider falla durante el commentary, fallback a templates estáticos (el reporte sigue generándose, solo pierde la narrativa de esa sección).
