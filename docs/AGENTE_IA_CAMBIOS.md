# Agente IA Conversacional — Cambios y Funcionalidades

> **Rama:** `feature/agent-ia-conversacional` → mergeada a `main` en `5ef953b`
> **Período:** 2026-05-06 a 2026-05-08
> **Estado:** Producción

Documento técnico que cubre todo lo añadido al proyecto en torno al agente IA conversacional, sus dependencias, decisiones de diseño y operación.

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Arquitectura](#2-arquitectura)
3. [Componentes nuevos](#3-componentes-nuevos)
4. [El agente IA conversacional](#4-el-agente-ia-conversacional)
5. [Bot de Telegram bidireccional](#5-bot-de-telegram-bidireccional)
6. [Widget de chat en el dashboard](#6-widget-de-chat-en-el-dashboard)
7. [Detector de saltos abruptos](#7-detector-de-saltos-abruptos)
8. [Cache Ubidots compartido](#8-cache-ubidots-compartido)
9. [Otros cambios](#9-otros-cambios)
10. [Operación](#10-operación)
11. [Costos](#11-costos)
12. [Decisiones y trade-offs](#12-decisiones-y-trade-offs)
13. [Comandos útiles](#13-comandos-útiles)

---

## 1. Resumen ejecutivo

El proyecto **Tenebrio 3D Heatmap** ya tenía un dashboard 3D (Danny) + un predictor GRU dual (TEMP, HUM) corriendo como sidecar Python. Sobre eso añadimos:

- **Agente IA conversacional** (Ollama Cloud, `gpt-oss:120b`) con 7 herramientas que consultan estado actual, histórico Ubidots, alert log, infraestructura externa y generan gráficas inline.
- **Bot de Telegram bidireccional**: además de mandar alertas, ahora escucha y responde preguntas. Comandos rápidos (`/status`, `/alerts`, `/help`) y modo conversacional libre.
- **Widget de chat en la vista IA del dashboard**: botón flotante 💬, historial persistente en `localStorage`, sugerencias clickables, render inline de tablas markdown y gráficas ECharts, modo claro/oscuro.
- **Detector de saltos abruptos** (rate-of-change): capa reactiva complementaria al GRU que detecta cambios bruscos entre muestras consecutivas.
- **Cache Ubidots compartido** Express ↔ sidecar (TTL 60s) que elimina el doble consumo de la API HTTP de Ubidots.
- **Infraestructura externa expuesta al agente**: termo, calentador solar, bomba M2, válvulas, ventilador, extractor, NH3, sensores del piso radiante.
- **Métricas agregadas (tps/tpi)**: temperatura promedio superior/inferior visibles como chips en el dashboard y consultables por el agente.

---

## 2. Arquitectura

```
                    ┌──────────┐               ┌──────────┐
                    │ Telegram │               │ Browser  │
                    │   bot    │               │ widget💬 │
                    └────┬─────┘               └────┬─────┘
                         │ getUpdates poll          │ POST /api/predictor/agent/chat
                         │ + sendMessage/sendPhoto  │ GET  /api/predictor/state
                         ▼                          ▼ (proxy Express)
                ┌────────────────────────────────────────────┐
                │     FastAPI sidecar  (127.0.0.1:8001)      │
                │                                            │
                │  ┌─────────────────────────────────────┐   │
                │  │  AgentService  (httpx + Ollama)     │   │
                │  │  Tools (sin side-effects):          │   │
                │  │   - get_current_state               │   │
                │  │   - get_thresholds                  │   │
                │  │   - get_recent_alerts(filtros)      │   │
                │  │   - get_history_ubidots(var, hrs)   │   │
                │  │   - get_predictions_history(var, h) │   │
                │  │   - get_infrastructure_state(cat?)  │   │
                │  │   - plot_history(vars, hrs)         │   │
                │  └─────────────────────────────────────┘   │
                │              ↑                             │
                │   ┌──────────┴──────────┐                  │
                │   │ AlertLog  (sqlite3) │  transiciones    │
                │   │ alert_events table  │  + saltos        │
                │   └─────────────────────┘                  │
                │   ┌─────────────────────┐                  │
                │   │ Ubidots cache (60s) │  /api/ubidots-   │
                │   │ + UbidotsHTTP       │     history      │
                │   └─────────────────────┘                  │
                │   ┌─────────────────────┐                  │
                │   │ RateOfChangeDetector│  saltos en MQTT  │
                │   └─────────────────────┘                  │
                └────────────────────────────────────────────┘
                         │                          │
                         ▼                          ▼
                   Ollama Cloud              Ubidots HTTP+MQTT
                  (LLM gpt-oss:120b)         (sensores y predicciones)
```

**Roles:**

| Componente | Lenguaje | Puerto | Responsabilidad |
|---|---|---|---|
| Sidecar | Python (FastAPI) | 127.0.0.1:8001 | Predictor GRU + agente IA + bot Telegram + cache Ubidots |
| Proxy/Dashboard | Node.js (Express) | 0.0.0.0:5000 | Sirve frontend 3D + IA, proxea `/api/predictor/*` al sidecar |
| LLM | Ollama Cloud (HTTPS) | externo | Razonamiento y tool calling del agente |
| Telegram | API pública | externo | Bot de alertas + conversación |
| Ubidots | API + MQTT | externo | Lecturas de sensores y publicación de predicciones |

---

## 3. Componentes nuevos

### Archivos creados

| Archivo | Líneas | Propósito |
|---|---|---|
| `ai-predictor/app/agent.py` | ~750 | `AgentService` — cliente Ollama Cloud + tools + loop manual de tool-calls |
| `ai-predictor/app/alert_log.py` | ~200 | `AlertLog` — persistencia SQLite (WAL) de transiciones y saltos |
| `ai-predictor/app/telegram_bot.py` | ~370 | `TelegramListener` — long polling + sendPhoto + render PNG |
| `tenebrios-node/public/js/predictor/chat.js` | ~520 | Widget de chat (ECharts inline, markdown, sugerencias, persistencia) |

### Archivos modificados (resumen)

- `ai-predictor/app/service.py` — `RateOfChangeDetector`, hook AlertLog, `UbidotsHTTP.get_values_range_by_label`, `EXTRA_TEMP_VARS` (tps/tpi), `attach_agent`, `update_telegram_settings` extendido
- `ai-predictor/app/main.py` — endpoints `/api/agent/chat` y `/api/ubidots-history` con cache TTL, lifespan que crea `AgentService` y conecta listener Telegram
- `ai-predictor/pyproject.toml` — añadidas dependencias `httpx`, `langgraph` (langgraph instalado pero no usado en producción)
- `ai-predictor/.env.example` — variables `OLLAMA_*`, `AGENT_ENABLED`, `TELEGRAM_LISTENER_ENABLED`
- `tenebrios-node/src/server.js` — rutas `/api/predictor/agent/chat` con timeout 90s y `/api/predictor/ubidots-history`
- `tenebrios-node/src/ubidotsApi.js` — `fetchUbidotsValues` ahora pasa por sidecar (con fallback directo a Ubidots)
- `tenebrios-node/public/index.html` — chat widget, chips de promedios tps/tpi, modal telegram extendido
- `tenebrios-node/public/css/styles.css` — ~400 líneas: chat widget, charts inline, sugerencias, jump toasts, light mode fixes
- `tenebrios-node/public/js/predictor/index.js` — handlers para SSE `type='extra'`, `'jump'`, toast de saltos
- `tenebrios-node/public/js/predictor/alert_indicators.js` — excluir tex/hex del banner de alertas
- `tenebrios-node/public/js/predictor/cards.js` — pill "Exterior" para tex/hex
- `tenebrios-node/public/js/predictor/telegram_config.js` — checkbox `listener_enabled`

---

## 4. El agente IA conversacional

### Cliente Ollama Cloud

Comunicación HTTP directa vía `httpx` al endpoint `POST https://ollama.com/api/chat` con header `Authorization: Bearer <OLLAMA_API_KEY>`. Sin paquete `ollama` para evitar dependencia extra.

- Loop manual de tool-calls (no LangGraph): hasta `MAX_TOOL_LOOPS = 10` iteraciones.
- Reintentos en errores 5xx: 3 intentos con backoff exponencial (1.5s, 3s).
- Si el provider sigue fallando, devuelve respuesta amigable con los `tool_calls` ejecutados.
- Timeout HTTP: 60s por intento (suficiente para `gpt-oss:120b` con tool calls).

### Las 7 herramientas (tools)

Todas son **read-only** — el agente no puede modificar nada del sistema.

| Tool | Cuándo se invoca | Qué devuelve |
|---|---|---|
| `get_current_state` | "¿cómo está la temperatura?", "¿hay alertas?" | Snapshot reducido: zona (interior/exterior), valor actual, predicho, estado, threshold por sensor, extras (tps/tpi) |
| `get_thresholds` | "¿cuáles son los rangos óptimos?" | TEMP 15–30 °C, HUM 60–90 % |
| `get_recent_alerts(hours?, group?, var?)` | "¿hubo anomalías hoy?", "¿qué pasó con h1?" | transiciones ok↔abnormal + jumps detectados + sensores actualmente abnormal (clave para detectar anomalías persistentes) + alert_log_oldest_ts |
| `get_history_ubidots(var, hours?)` | "¿promedio de t1 en las últimas 6h?", "¿cuándo bajó la humedad?" | min/max/avg, ~30 muestras submuestreadas, threshold_analysis con primer punto abnormal y primera transición |
| `get_predictions_history(var, hours?)` | "¿cómo predijo el modelo h1 ayer?" | Igual que el anterior pero para variables `*_pred` |
| `get_infrastructure_state(category?)` | "¿cómo está el termo?", "¿flujo en la bomba?", "¿NH3?" | Últimas lecturas de calefacción (termo, calentador solar, bomba M2, válvulas, piso radiante), ventilación, calidad de aire |
| `plot_history(vars, hours?, title?, include_predictions?)` | "muéstrame la gráfica...", "plot de t1 últimas 6h" | `chart_spec` con series + thresholds + summary stats. Renderizado: ECharts inline en widget, matplotlib PNG en Telegram |

### System prompt

Indica al LLM:
- Arquitectura del cuarto (interiores t1-t5/h1-h5, exteriores tex/hex)
- Rangos óptimos solo aplican a interiores
- Métricas agregadas tps/tpi (estratificación térmica)
- Limitación del AlertLog: solo registra transiciones, no muestreos
- Cómo detectar anomalías persistentes (sin transiciones pero `currently_abnormal_interior_sensors` no vacío → escalar a `get_history_ubidots`)
- Infraestructura externa al cuarto (flujo solar → termo → bomba → piso)
- Estrategia eficiente: tope de 10 tool calls, usar 1 sensor representativo en lugar de iterar los 5

### Modelo

Default: `gpt-oss:120b` (free en Ollama Cloud, soporta tool calling).

Alternativas evaluadas:
- `gpt-oss:20b` — más rápido, también gratis
- `granite4.1:8b` — barato, optimizado para tool calling
- `kimi-k2.6:cloud` — **requiere suscripción de pago** (devolvió HTTP 403 con plan free)

Cambiar el modelo es solo editar `OLLAMA_MODEL` en `.env` y reiniciar el sidecar.

---

## 5. Bot de Telegram bidireccional

### Listener (long polling)

`TelegramListener` en `ai-predictor/app/telegram_bot.py`:

- Thread daemon hace `getUpdates?offset=...&timeout=15` (long polling, no webhooks).
- Solo responde al `chat_id` configurado (mensajes de otros chat_ids se ignoran silenciosamente).
- Persiste `last_update_id` en `runtime_config.json` para no re-procesar mensajes tras reinicio.
- Toggle desde el dashboard: modal Telegram → checkbox "Permitir consultas al bot". Default **off** (opt-in para no consumir tokens del LLM sin querer).

### Comandos rápidos (sin LLM)

- `/status` — bullet list TEMP y HUM con estado
- `/alerts` — últimas 10 transiciones de las últimas 24h
- `/help` — listado de comandos
- `/start` — alias de `/help`

### Modo conversacional

Cualquier mensaje libre va al `AgentService.chat()`. El listener muestra `sendChatAction("typing")` antes de despachar.

### Envío de gráficas (PNG)

Si el agente emite un `chart_spec` (tool `plot_history`):

1. `_render_chart_png()` usa matplotlib backend `Agg` (server-side, sin display) para generar PNG con estilo coherente con el dashboard (fondo `#1a2630`, paneles `#243B4A`, dorado `#E8B830`).
2. Se envía con `sendPhoto` (multipart/form-data) y la respuesta del agente como caption (Telegram limita captions a 1024 chars).
3. Si hay múltiples charts, cada uno como foto separada.

### Conversión de tablas markdown

Telegram Markdown no soporta tablas pipe-style. `_markdown_tables_to_bullets()` detecta el patrón `| col | col | / |---|---|` y lo convierte a:

```
• *t1* — Valor: 28.5 · Estado: ok
• *t2* — Valor: 27.6 · Estado: ok
```

Aplicado tanto a `sendMessage` como a captions de `sendPhoto`.

---

## 6. Widget de chat en el dashboard

### Ubicación

Botón flotante 💬 abajo a la derecha, **solo visible en la vista IA**. El panel del chat también vive dentro de `#view-ai` y se oculta automáticamente al cambiar a la vista 3D.

### Sugerencias en primer uso

6 chips en grilla 2x3 (1 columna en mobile) — `SUGGESTED_PROMPTS` en `chat.js`:

1. 🌡 ¿Cómo está el cuarto ahora? — showcase de estado
2. 🚨 ¿Hubo anomalías hoy? — showcase del fix de anomalías persistentes
3. 📈 Gráfica de temperaturas últimas 6 horas — showcase del feature de gráficas
4. 💧 ¿Desde cuándo está mal la humedad? — showcase de escalamiento a Ubidots
5. 🔥 ¿Cómo está el termo y el calentador? — showcase de infraestructura
6. 🌬 ¿Cómo está la calidad del aire? — showcase de NH3

Click en chip → inyecta el texto en el input y dispara submit inmediato.

### Persistencia

- Historial en `localStorage` (`ai-chat-history-v1`), máximo 30 mensajes.
- Sobrevive recarga y cambios de vista.
- Botón 🗑 para borrar la conversación (con confirmación `window.confirm`).

### Markdown lite (en `chat.js`)

Implementación manual sin librerías:

- `**bold**` → `<strong>`
- `*italic*` → `<em>`
- `` `code` `` → `<code>`
- `- item` (líneas) → `<ul><li>`
- Tablas pipe-style `| ... |` con separador `|---|` → `<table>` con header dorado, filas zebradas

### Gráficas inline (ECharts)

Cuando la respuesta incluye `charts: [...]`, cada `chart_spec` se renderiza con ECharts:

- Línea suave con paleta consistente al dashboard
- `markLine` para los umbrales en rojo punteado
- Tooltip con timestamp + valor + unidad
- Leyenda si hay múltiples series
- Auto-resize con `ResizeObserver` cuando cambia el tamaño del panel

### Atajos

- `C` — abrir/cerrar el chat (solo en vista IA, ignorado si el usuario está tipeando)
- `Enter` — enviar
- `Shift+Enter` — salto de línea
- `Esc` — cerrar el chat

### Toast de saltos abruptos

Cuando el rate-of-change detector dispara, se envía `{type: 'jump'}` por SSE → toast dorado arriba a la derecha con auto-dismiss 6s. Mostrado solo en vista IA.

---

## 7. Detector de saltos abruptos

### Motivación

El modelo GRU predice +3 min asumiendo continuidad — es bueno para tendencias suaves pero **debilísimo para saltos abruptos**. Ejemplo real observado:

```
15:38:23 — predicho 29.93 °C  →  15:41:27 real 30.20 °C  (error -0.27)
15:39:25 — predicho 29.94 °C  →  15:42:29 real 30.20 °C  (error -0.26)
```

El modelo no anticipó el salto; lo "vio" después que ocurrió.

### Implementación

`RateOfChangeDetector` en `service.py`:

- Mantiene última muestra `(ts, value)` por sensor.
- En cada lectura MQTT, calcula `delta = value - prev_value`.
- Si `|delta| ≥ threshold` y `dt ≤ 5 min` y fuera de cooldown → dispara.

**Umbrales por defecto** (configurables vía `DEFAULT_THRESHOLDS`):

| Grupo | Umbral | Razón |
|---|---|---|
| TEMP | 0.5 °C | Saltos térmicos súbitos = puerta abierta, ventilador apagado, etc. |
| HUM | 5 % | Cambios bruscos de humedad |

**Cooldown**: 5 min por sensor para no spammear si oscila.

**Excluye sensores exteriores** (tex, hex) — sus saltos son normales.

### Efectos al dispararse

1. **AlertLog**: persiste con `kind="jump"` (separado de las transiciones ok↔abnormal). `prev_state`/`new_state` guardan los valores numéricos como string, `predicted_value` guarda el delta.
2. **Telegram**: mensaje formato `📈 Salto detectado — Sensor t1: 29.80°C → 30.20°C (Δ +0.40°C)`.
3. **Dashboard**: SSE `{type:'jump'}` → toast en pantalla.
4. **Agente**: la tool `get_recent_alerts` devuelve los jumps en una lista separada.

### Las 3 capas de alerta complementarias

| Capa | Tipo | Latencia | Detecta |
|---|---|---|---|
| Predicción GRU | ML anticipativa | +3 min adelantado | Tendencias suaves que cruzarán umbral |
| Umbral fijo | Reactiva | inmediato (al siguiente sample) | Valor cruzó 30 °C / 60 % (sostenido) |
| Rate-of-change | Reactiva, derivada | inmediato (entre 2 samples) | Saltos ≥ 0.5 °C / ≥ 5 % |

---

## 8. Cache Ubidots compartido

### Problema

Antes, **Express y el sidecar Python pegaban a la API HTTP de Ubidots por separado**:

- Express: para el slider histórico del dashboard 3D (`/api/history?start=&end=` consulta ~22 variables)
- Sidecar: para el prefill del buffer al arranque + tool `get_history_ubidots` del agente

Duplicación de cuota y posible rate-limit en plan free.

### Solución (Opción B del análisis)

El sidecar expone `GET /api/ubidots-history?var=&start=&end=` con cache TTL 60s. Express consume **a través del sidecar** en lugar de pegarle directo a Ubidots. Si el sidecar está caído, hay **fallback automático a Ubidots directo** (degradación graceful).

### Implementación

- `ai-predictor/app/service.py`: nuevo método `UbidotsHTTP.get_values_range_by_label(device_label, var_label, start_ms, end_ms)` que usa el endpoint estilo Express (`/api/v1.6/devices/{label}/{var}/values`).
- `ai-predictor/app/main.py`: endpoint `/api/ubidots-history` con cache `dict[(var, start, end), (ts, results)]` y podado oportunista cuando supera 200 entradas. Validación: label regex `^[a-zA-Z0-9_\-]{1,64}$`, rango máximo 31 días.
- `tenebrios-node/src/ubidotsApi.js`: `fetchUbidotsValues` intenta primero el sidecar (timeout 12s); si 5xx o no responde, fallback a Ubidots directo.

### Resultados medidos

Endpoint `/api/history` del dashboard 3D (slider para últimas 24h, ~22 variables):

| Llamada | Tiempo | Notas |
|---|---|---|
| Primera | 11.96 s | Sidecar pulla 22 vars a Ubidots, cachea |
| Segunda | 0.31 s | **40× más rápida** desde cache |

---

## 9. Otros cambios

### Sensores interiores vs exteriores

Antes: `tex` (43°C en verano) y `hex` (10% humedad seca) se marcaban como "abnormal" usando el umbral interior — falso positivo.

Ahora:
- `EXTERIOR_VARS = {"tex", "hex"}` excluidos del banner de alertas (`alert_indicators.js`).
- Cards muestran pill `🌡 Exterior` (gris, informativo) en lugar de PELIGRO.
- `TelegramNotifier.on_alerts()` los saltea por completo (ni AlertLog ni Telegram).
- El agente los reporta como "informativos del clima exterior" en sus respuestas.

### Métricas agregadas tps/tpi

Variables del device Ubidots que representan promedios:
- `tps` — temperatura promedio superior (parte alta del cuarto)
- `tpi` — temperatura promedio inferior (parte baja del cuarto)

**Visibles** como chips dorados en la sección Temperatura de la vista IA. Actualizados en vivo vía SSE `{type: 'extra'}`. **Consultables** por el agente vía el campo `extras` de `get_current_state` — útil para preguntas tipo "¿cuál es la estratificación térmica?".

### Anomalías persistentes

Bug reportado: con la humedad fuera de rango toda la mañana, el agente respondía "no hubo anomalías" porque el AlertLog solo registra transiciones (cambios de estado), y si el sensor llegó abnormal antes del periodo consultado y sigue así, no hay transición que reportar.

Fix:
- `get_recent_alerts` ahora devuelve `currently_abnormal_interior_sensors` y `alert_log_oldest_ts_iso` (sabe hasta dónde alcanza el log).
- Si `transitions = 0` y `currently_abnormal` no vacío → `interpretation_hint` indica al LLM que reporte como "anomalía persistente".
- System prompt explica la limitación del log y cómo escalar a `get_history_ubidots` para encontrar el inicio real.

### Detección de inicio de anomalía

Cuando el AlertLog no cubre el periodo, el agente usa `get_history_ubidots` para buscar el primer punto bajo el umbral. La tool devuelve:
- `first_abnormal_ts_iso` — primer punto fuera de rango
- `first_transition_ok_to_abnormal_ts_iso` — primera transición ok→abnormal dentro del periodo
- `range_start_state` / `range_end_state`
- `interpretation` — si el rango empieza ya abnormal y nunca vuelve a ok, sugiere escalar a un `hours` mayor (escalación 6 → 24 → 72 → 168)

### Tablas markdown en chat y Telegram

- Widget: parser en `chat.js` detecta tablas pipe-style y las renderiza como `<table>` HTML con header dorado, filas zebradas, soporte light/dark mode.
- Telegram: `_markdown_tables_to_bullets()` las convierte a bullets antes de enviar (Telegram no soporta tablas).

### Light mode legible en alertas

Los tonos pastel de las pills (`#86efac` verde, `#fbbf24` ambar, `#fecaca` rojo claro) eran invisibles en fondo blanco. Se añadieron overrides `[data-theme="light"]` con tonos oscuros saturados (`#166534`, `#92400e`, `#991b1b`) que cumplen contraste WCAG AA.

### Retry en errores Ollama 5xx

Bug: `Agente fallo: Ollama Cloud devolvio HTTP 500`. Fix: `_post_with_retries` con 3 intentos y backoff (1.5s, 3s) en 5xx y errores de red transitorios. Si después de los retries sigue fallando, devuelve respuesta amigable preservando los `tool_calls` ya ejecutados.

### FAB chat solo icono

El botón flotante mostraba "💬 Preguntar" como pildora. Cambiado a redondo 56×56 solo con el ícono 💬.

### Botón de borrar conversación

Icono ⌫ poco discoverable. Cambiado a 🗑 universal con confirmación `window.confirm` que muestra el conteo de mensajes a borrar.

---

## 10. Operación

### Arranque

**Opción A — script automatizado:**

```cmd
start_all.bat
```

Hace:
1. Verifica que exista `ai-predictor/.env` (requerido).
2. Detecta Python (orden: `ai-predictor/.venv` → `C:\tnvenv` → `python` en PATH).
3. Abre el sidecar en una ventana nueva titulada "AI Predictor (puerto 8001)".
4. Espera con `curl /healthz` hasta 60s a que cargue TensorFlow.
5. Arranca Express en la ventana actual con `AI_PREDICTOR_BASE=http://127.0.0.1:8001`.

**Opción B — manual:**

```bash
# Terminal 1 — sidecar
cd ai-predictor
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# Terminal 2 — Express
cd tenebrios-node
AI_PREDICTOR_BASE=http://127.0.0.1:8001 npm start
```

### Configuración

Solo `ai-predictor/.env` es estrictamente requerido. Express usa defaults de `tenebrios-node/src/config.js` si no hay `.env`.

Variables clave en `ai-predictor/.env`:

```
UBIDOTS_TOKEN=BBFF-...                # requerido
UBIDOTS_DEVICE_LABEL=tenebrios

APP_PORT=8001                          # puerto del sidecar
PUBLISH_PREDICTIONS=true               # publica *_pred a Ubidots
PREFILL_FROM_API=true                  # buffer inicial desde HTTP

# Telegram (alertas + bot conversacional)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_LISTENER_ENABLED=false        # opt-in para conversación

# Agente IA
AGENT_ENABLED=true
OLLAMA_HOST=https://ollama.com
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_KEY=...                     # requerido si AGENT_ENABLED=true
```

### Puertos

- **Sidecar Python**: `127.0.0.1:8001` (loopback only — solo accesible desde la misma máquina).
- **Express Node.js**: `0.0.0.0:5000` (expuesto a la LAN).

El sidecar nunca debe exponerse fuera del host. Express es el único proxy con interfaz pública (HTTP `/api/predictor/*` se redirige al sidecar).

### Persistencia local

| Archivo | Contenido | Gitignored |
|---|---|---|
| `ai-predictor/alert_log.sqlite` | Transiciones de estado + saltos (SQLite WAL) | sí |
| `ai-predictor/runtime_config.json` | `telegram_chat_id`, `telegram_listener_enabled`, `telegram_last_update_id`, cooldown | sí |
| `localStorage('ai-chat-history-v1')` | Historial del chat (browser) | n/a |

### Logs

Logs del sidecar van a stdout/stderr de uvicorn (capturados por `start_all.bat` en `C:\Users\<user>\AppData\Local\Temp\tenebris-logs\sidecar.err`). Niveles configurables vía `LOG_LEVEL` en `.env`.

Loggers relevantes:
- `agent` — operaciones del agente IA
- `telegram` — envío de mensajes/alertas
- `telegram.listener` — recepción de mensajes
- `rate-of-change` — saltos detectados
- `ubidots` — predictor + MQTT

---

## 11. Costos

### Ollama Cloud

- Modelo `gpt-oss:120b`: **free tier**. Aproximadamente **$0.001-0.005 por query** según el plan.
- Conversación típica: 1000 input + 300 output tokens.
- 100 queries/día ≈ **$3-15/mes**.

Si los costos son altos, alternativas más baratas (sin cambio de código, solo `OLLAMA_MODEL` en `.env`):
- `gpt-oss:20b` — ~3× más rápido y más barato
- `granite4.1:8b` — optimizado para tool calling, muy económico

### Ubidots

Igual o menos que antes — el cache de 60s elimina los duplicados Express ↔ sidecar. En plan free no debería pegar el rate-limit.

### Telegram

Gratis (Bot API).

---

## 12. Decisiones y trade-offs

### Por qué httpx en lugar del paquete `ollama`

- `httpx` ya estaba en deps (FastAPI). Una dependencia menos.
- Más control sobre timeouts, retries, headers.
- El paquete `ollama` añade ~15KB y un layer de wrapping innecesario.

### Por qué loop manual en lugar de LangGraph

- `langgraph` está instalado pero **no usado en producción**.
- Loop manual (~30 líneas) es más fácil de debuggear y mantener.
- Para flujos más complejos (branching condicional, subprocesos), migrar a LangGraph sería natural.

### Por qué el listener Telegram es opt-in

- El agente consume tokens del LLM con cada query.
- Si el `chat_id` es un grupo y todos preguntan, el costo puede dispararse.
- Default OFF protege contra esto. El usuario lo activa cuando lo necesita.

### Por qué cache Ubidots TTL 60s

- El slider del dashboard típicamente repite el mismo rango (últimas 24h, última semana).
- 60s es suficiente para capturar repeticiones rápidas sin servir datos obsoletos.
- Podado oportunista a 200 entradas evita crecimiento descontrolado.

### Por qué guardar el chart_spec separado del reply al LLM

- El LLM **NO debe** ver los puntos del chart (saturaría su contexto).
- Solo recibe el `summary` (min/max/avg).
- El cliente recibe el `chart_spec` completo para renderizar.
- Resultado: respuestas concisas + visualización rica.

### Por qué tex/hex no son alerta pero sí informativos

- Son sensores **en la intemperie** — sus valores reflejan el clima de afuera.
- Esperable que estén fuera del rango interior (5°C o 40°C son normales afuera).
- Marcarlos como "abnormal" generaría falsas alarmas constantes.
- Pero su valor **es útil como contexto** ("afuera hay 42°C, eso estresa los aires").

### Por qué el detector RoC excluye exteriores

- Saltos en `tex` (sol que sale/se nubla) son normales.
- Solo nos importan los saltos en sensores interiores que indiquen problema (ventilador apagado, puerta abierta).

### Por qué infraestructura (termo, etc.) no entra al dashboard de IA

- Ya están **visualizadas en el dashboard 3D de Danny** — duplicarlas sería ruido.
- Solo necesitamos que el agente las **pueda consultar** para diagnosticar.
- `get_infrastructure_state` las pulla a Ubidots on-demand sin inflar la suscripción MQTT.

### Por qué sidecar solo en loopback

- Defensa en profundidad — el sidecar no necesita ser accesible desde fuera.
- Express actúa como único punto de entrada con validaciones.
- Reduce superficie de ataque significativamente.

---

## 13. Comandos útiles

### Verificar que el agente está funcionando

```bash
# Health del sidecar
curl http://127.0.0.1:8001/healthz

# Estado actual (proxy via Express)
curl http://localhost:5000/api/predictor/state | jq .

# Test del agente
curl -X POST http://localhost:5000/api/predictor/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'
```

### Inspeccionar el AlertLog

```bash
sqlite3 ai-predictor/alert_log.sqlite "SELECT datetime(ts, 'unixepoch') as t, group_name, var, kind, prev_state, new_state, value FROM alert_events ORDER BY ts DESC LIMIT 20"
```

### Ver logs del sidecar en vivo

```cmd
type "%TEMP%\tenebris-logs\sidecar.err"
```

### Resetear historial del chat

En el browser, abre DevTools (F12) → Console:

```js
localStorage.removeItem('ai-chat-history-v1');
```

O simplemente click en 🗑 del chat.

### Cambiar el modelo del agente sin reiniciar Express

```bash
# Editar ai-predictor/.env
OLLAMA_MODEL=gpt-oss:20b

# Reiniciar solo el sidecar (matar la ventana "AI Predictor")
# Express seguirá funcionando y reconectará cuando el sidecar esté de vuelta
```

### Detener todo

Cierra las ventanas de "AI Predictor" y "Express" (o Ctrl+C en ellas). Si quedó algo colgado:

```cmd
taskkill /F /IM python.exe /T
taskkill /F /IM node.exe /T
```

---

## Historial de commits

Cronología en `feature/agent-ia-conversacional` (mergeada a `main` en `5ef953b`):

| Commit | Descripción corta |
|---|---|
| `66bb26d` | Fase 1 — backend agente IA + alert log + endpoint REST |
| `8c08384` | Fase 2 — Telegram bidireccional con listener long-poll |
| `740dfb3` | Fase 3 — widget chat IA en vista IA del dashboard |
| `0749455` | Fase 4 — polish + INTEGRATION.md |
| `3057d93` | Fix: distinguir sensores interiores vs exteriores en el contexto |
| `1fcc660` | Feat: unificar histórico Ubidots via sidecar con cache TTL 60s |
| `222cbfd` | Fix UI: light mode legible en alertas + FAB chat solo icono |
| `57f59e3` | UX: icono trash claro + confirmacion al borrar conversacion |
| `4c4df3d` | Fix: detectar anomalias persistentes (no solo transiciones) |
| `04f5d37` | Fix: escalar a histórico Ubidots cuando el alert log no alcanza |
| `673c4c3` | Fix: tex/hex no son alerta + tablas markdown rinden bien |
| `33a57dc` | Fix: retry en errores 5xx de Ollama Cloud + respuesta amigable |
| `0939c52` | Feat: detector de saltos abruptos complementario al GRU |
| `43dd9c4` | Feat: tps/tpi (promedios superior/inferior) en vista IA + agente |
| `12b9748` | Feat: el agente puede generar graficas (widget ECharts + Telegram PNG) |
| `7931fb7` | Feat: tool get_infrastructure_state — termo, calentador, bomba, etc |
| `20ca997` | UX: chips de preguntas sugeridas en estado vacio |
| `5ef953b` | **Merge a main** |
| `3349c0e` | Chore: actualizar `start_all.bat` (puerto 8001 + venv corto + health-check) |
| `9bee76f` | Fix bat: tenebrios-node/.env opcional + simplificar sidecar launch |

---

*Última actualización: 2026-05-08*
