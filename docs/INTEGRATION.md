# Integración: Dashboard 3D + Predictor IA

Esta rama (`feature/ai-predictor-integration`) une **dos dashboards** complementarios sobre el mismo cuarto de cría de tenebrios:

- **Vista 3D** (Danny): mapa de calor volumétrico en tiempo real (Babylon.js).
- **Vista IA** (Tenebris AI Sentinel): predicción +3 min con modelo dual GRU.

El usuario alterna entre ellas con un botón en el header. La URL es siempre `http://localhost:5000`.

## Arquitectura

```
                    ┌────────────────────────┐
   Browser  ───────▶│  Express (puerto 5000) │
                    │  tenebrios-node        │
                    └─────────┬──────────────┘
                              │
                              │ proxy /api/predictor/*
                              ▼
                    ┌────────────────────────┐
                    │  FastAPI (127.0.0.1:8000) │
                    │  ai-predictor          │
                    │  - GRU temp + hum      │
                    │  - SSE /api/stream     │
                    └────────────────────────┘
                              │
                              ▼ MQTT subscribe
                          Ubidots
```

- El navegador **solo habla con `localhost:5000`**. No conoce el sidecar.
- El sidecar Python escucha **solo en `127.0.0.1`** (no expuesto a la red local).
- Cada servicio tiene su propio `.env` con credenciales separadas.

## Arranque rápido (Windows)

1. Configura `.env` en cada lado:
   ```
   tenebrios-node\.env       (UBIDOTS_TOKEN, DEVICE_LABEL, WEB_PORT, ...)
   ai-predictor\.env         (UBIDOTS_TOKEN, UBIDOTS_DEVICE_LABEL, ...)
   ```
   Ambos pueden usar el mismo token y device label.

2. Instala dependencias (una sola vez):
   ```bat
   cd tenebrios-node
   npm install

   cd ..\ai-predictor
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   ```

3. Lanza ambos con un solo comando:
   ```bat
   start_all.bat
   ```

   Se abrirá una ventana extra con el predictor IA. La principal arranca el server Node.

4. Abre `http://localhost:5000` y pulsa **🤖 IA +3min** en el header para ver la predicción.

## Arranque manual (sin `start_all.bat`)

Terminal 1:
```bat
cd ai-predictor
.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:
```bat
cd tenebrios-node
npm start
```

## Estructura de archivos

```
tenebrio-3d-heatmap-node/
├── tenebrios-node/                  (Danny — modificado mínimamente)
│   ├── src/server.js                +rutas /api/predictor/*
│   ├── public/index.html            +botón toggle + contenedor #view-ai
│   ├── public/css/styles.css        +estilos .ai-* (al final)
│   └── public/js/
│       ├── app.js                   +setupViewToggle()
│       └── predictor/               NUEVO
│           ├── index.js             orquestador
│           ├── cards.js             tarjetas por sensor
│           ├── charts.js            ECharts overlay real vs predicho
│           └── sse.js               cliente EventSource
├── ai-predictor/                    NUEVO (proyecto Python tal cual)
│   ├── app/                         FastAPI + service.py + agent.py + alert_log.py
│   ├── models/                      *.keras + *.save (≈636 KB total)
│   ├── pyproject.toml
│   └── .env.example
├── docs/                            NUEVA carpeta de documentacion
│   ├── README.md                    indice
│   ├── AGENTE_IA_CAMBIOS.md         cambios del agente IA + Telegram + chat
│   ├── INTEGRATION.md               este archivo
│   ├── ai-predictor.md              README del modulo Python (antes README_AI.md)
│   ├── node-dashboard.md            README del dashboard Node
│   ├── node-changelog.md            migracion Python -> Node
│   ├── node-requirements.md         requisitos del sistema
│   └── node-scripts-install.md      instalacion como servicio Windows
├── start_all.bat                    arranca sidecar + Express
├── README.md                        index general (apunta a docs/)
└── .gitignore                       +entradas Python
```

## Lo que NO se tocó del proyecto de Danny

- `src/config.js`, `src/mqttClient.js`, `src/heatmapEngine.js`, `src/interpolation.js`, `src/ubidotsApi.js`, `src/logger.js`, `src/index.js`
- `public/js/scene.js`, `camera.js`, `colorScales.js`, `indicators.js`, `history.js`, `meshes/*`
- `tests/`, `scripts/`, `mqttSimulator.js`, `package.json`, `package-lock.json`

Cero dependencias nuevas en `package.json`: el proxy usa `fetch` nativo de Node 20+.

## Detección de anomalías (umbrales)

El backend clasifica cada sensor contra rangos operativos óptimos:

| Grupo | Rango óptimo | Fuera = |
|---|---|---|
| Temperatura (`t1..t5`, `tex`) | 15–30 °C | `abnormal` |
| Humedad (`h1..h5`, `hex`) | 60–90 % | `abnormal` |

Los umbrales están como constantes en `ai-predictor/app/service.py` (`TEMP_OPTIMAL_MIN/MAX`, `HUM_OPTIMAL_MIN/MAX`). Para cambiarlos basta editar el archivo y reiniciar.

Cada evento `prediction` del SSE (y el snapshot inicial) incluye:

```json
"alerts": {
  "t1": { "current": "ok",       "predicted": "abnormal" },
  "t2": { "current": "abnormal", "predicted": "abnormal" }
}
```

**Visual en la vista IA:**
- Card con borde rojo → valor actual fuera de rango
- Card con borde naranja + ⚠ → valor actual ok pero predicho fuera de rango (alerta anticipada)
- Valor predicho en rojo cuando aplica
- **Pill de texto** debajo del valor predicho:
  - 🟢 `Normal` (verde)
  - 🟠 `Alerta +3min` (naranja, predicción saldrá del rango)
  - 🔴 `PELIGRO` (rojo, valor actual ya fuera de rango — con latido)
  - ⚪ `—` (sin clasificar, antes del primer dato)

Esta misma información llega a cualquier consumidor del SSE — si en el futuro se conecta el agente LangGraph mencionado en el README, ya tiene la señal estructurada lista para tomar decisiones.

## Alertas Telegram

El sidecar Python puede enviar alertas a un chat de Telegram cuando un sensor cambia de estado. Solo dispara en **transiciones** (ok→abnormal, abnormal→ok) y respeta un **cooldown** por sensor (default 5 min) para no spamear.

### Setup (una vez)

1. En Telegram, busca **@BotFather** → `/newbot` → te da un token tipo `1234567890:AAH...`.
2. Manda cualquier mensaje al bot creado (Telegram requiere primer contacto del usuario).
3. Para obtener tu `chat_id`:
   - **Chat privado:** busca **@userinfobot** y mira el campo `Id`.
   - **Grupo:** agrega **@RawDataBot** al grupo y mira `"chat":{"id": ...}` (suele ser negativo).
4. Edita `ai-predictor/.env`:
   ```
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=1234567890:AAH...
   TELEGRAM_CHAT_ID=123456789
   TELEGRAM_COOLDOWN_SEC=300
   ```
5. Reinicia el sidecar. En el log inicial debe aparecer:
   ```
   [INFO] telegram :: Telegram notifier ACTIVO (cooldown=300s)
   ```

### Tipos de mensaje

| Disparo | Mensaje (ejemplo) |
|---|---|
| `ok` → `abnormal` (actual) | 🚨 **PELIGRO** — Temperatura anormal · Sensor `t1` fuera de rango: `32.5°C` · Rango: 15–30 °C |
| `ok` y predicho `abnormal` (anticipado) | ⚠ **Alerta predictiva** — Sensor `t1` podría salirse en +3min: `28.5°C` → `30.8°C` |
| `abnormal` → `ok` (recuperación) | ✅ Temperatura normalizada · Sensor `t1` regresó al rango: `28.0°C` |

### Notas

- Si `TELEGRAM_ENABLED=false` o falta token/chat_id, el notifier es no-op (no crashea, no manda nada)
- El send va en thread daemon → no bloquea el procesamiento MQTT
- Si Telegram está caído o tarda, ese mensaje se pierde (timeout 5s) — el siguiente intento será en la siguiente transición

### Configuración desde el dashboard (sin reiniciar)

En el header de la vista IA hay un **botón ⚙** que abre un modal donde se puede:
- Cambiar el `chat_id` (ej. al rotar a un grupo distinto)
- Activar/desactivar las notificaciones
- Ajustar `cooldown_sec` (30–3600)
- Mandar un **mensaje de prueba** para verificar que el bot puede escribir al chat

Los cambios se aplican al instante (hot-reload) y se persisten en `ai-predictor/runtime_config.json` (gitignored). Al reiniciar el sidecar:
1. Carga `.env` (token + valores por defecto)
2. Sobrescribe con `runtime_config.json` (lo último guardado desde la UI)

**Importante (seguridad):** la UI **nunca** pide ni muestra el `TELEGRAM_BOT_TOKEN`. El token vive solo en `.env`. Si se intenta enviar `bot_token` por la API (`POST /api/telegram`), el backend devuelve 400. Si el modal detecta que no hay token configurado, muestra un aviso amarillo pidiendo editar `.env`.

**Endpoints expuestos:**
| Método | Path | Qué hace |
|---|---|---|
| GET | `/api/predictor/telegram` | Devuelve `{enabled, chat_id, cooldown_sec, token_configured}` (sin token) |
| POST | `/api/predictor/telegram` | Acepta `{chat_id?, enabled?, cooldown_sec?}`. Persiste a `runtime_config.json` |
| POST | `/api/predictor/telegram/test` | Manda un mensaje de prueba al chat configurado |

## Agente IA conversacional

A partir de la fase 1 del feature `agent-ia-conversacional` el sidecar incluye un agente que responde preguntas en lenguaje natural sobre el cuarto. Es accesible desde dos canales:

1. **Widget de chat en el dashboard** (icono 💬 abajo a la derecha de la vista IA, atajo `C`).
2. **Bot de Telegram bidireccional** (mismo bot que ya manda alertas, ahora también responde mensajes).

### Setup (5 minutos)

1. Crear cuenta en **Ollama Cloud**: <https://ollama.com>. Ir a *Settings → Keys* y generar una API key (formato `XXXXXXXX.YYYYY...`).
2. Pegarla en `ai-predictor/.env`:
   ```
   OLLAMA_API_KEY=tu-api-key
   AGENT_ENABLED=true
   OLLAMA_MODEL=gpt-oss:120b   # o granite4.1:8b para algo mas rapido/barato
   ```
3. Reiniciar el sidecar. En los logs verás `Agente IA ACTIVO (host=https://ollama.com, model=gpt-oss:120b)`.
4. Para usar Telegram bidireccional: abrir el modal Telegram en el dashboard (engrane ⚙) y marcar **"Permitir consultas al bot (agente IA conversacional)"**. Default es OFF para evitar consumir tokens sin querer.

### Tools que el agente puede usar

El agente decide automáticamente cuándo invocar cada una según la pregunta:

| Tool | Cuándo se invoca | Datos que devuelve |
|---|---|---|
| `get_current_state` | "¿cómo está la temperatura?", "¿hay sensores en alerta?" | snapshot actual + predicciones +3 min + flags ok/abnormal |
| `get_thresholds` | "¿cuáles son los rangos óptimos?" | TEMP 15–30 °C, HUM 60–90 % |
| `get_recent_alerts` | "¿hubo anomalías hoy?", "¿qué pasó con t1 ayer?" | transiciones de estado de las últimas N horas (de SQLite local) |
| `get_history_ubidots` | "¿promedio de t3 en las últimas 6 horas?", "¿cuándo bajó la humedad?" | min/max/avg + ~30 puntos muestreados de Ubidots HTTP |
| `get_predictions_history` | igual que el anterior pero para `*_pred` | precisión histórica del modelo |

Las tools son **puras** (solo consulta, ningún side-effect). El agente no puede modificar configuración, mandar mensajes ni tocar Ubidots.

### Comandos rápidos en Telegram

Sin consumir tokens del LLM:

- `/status` — bullet list con valores actuales y flags por sensor
- `/alerts` — últimas 10 transiciones a estado abnormal en 24 h
- `/help` — listado de comandos

Cualquier otro mensaje (lenguaje natural) pasa al agente IA.

### Persistencia

- **SQLite** `ai-predictor/alert_log.sqlite` (gitignored): registra cada transición ok↔abnormal con timestamp, sensor, valor, predicción. Auto-cleanup a 30 días en cada arranque.
- **Histórico real**: NO vive en el backend. El agente lo pulla desde Ubidots HTTP cuando se le pregunta. Tras el último merge, las predicciones también se publican (`t1_pred`, `h1_pred`, etc.) y son consultables.

### Costos estimados (Ollama Cloud)

- Modelo `gpt-oss:120b`: ~$0.001–0.005 por query (tarifa actual de Ollama Cloud, revisar en docs).
- Conversación típica: 1000 input + 300 output tokens.
- 100 queries/día ≈ $3–15/mes.

Si los costos son altos, se puede cambiar a `granite4.1:8b` editando solo `OLLAMA_MODEL` en `.env` (más rápido y barato; soporta tool calling igual).

### Defensa

- El listener de Telegram **solo responde al `chat_id` configurado**. Mensajes de otros chat_ids se ignoran silenciosamente y se loguean.
- El bot_token jamás se expone vía API. Solo vive en `ai-predictor/.env`.
- El agente no tiene tools que modifiquen estado: si el LLM intenta inventar un comando, no hay efecto.

### Endpoints REST

- `POST /api/predictor/agent/chat` — `{message, history?}` → `{reply, tool_calls, model}`. Timeout 30 s en Express.
- `GET /api/predictor/telegram` — devuelve `listener_enabled`, `listener_available`, etc.
- `POST /api/predictor/telegram` — acepta `listener_enabled` además de los campos previos.

## Personalización (white-label)

Los colores de marca están centralizados en `:root` al inicio de `tenebrios-node/public/css/styles.css`:

```css
:root {
  --ai-accent:        #E8B830;   /* Dorado de marca */
  --ai-bg-base:       #1a2630;   /* Fondo principal */
  --ai-bg-panel:      #243B4A;   /* Paneles, headers */
  --ai-border:        #3a5a6a;
  --ai-text:          #e8e0d8;
  --ai-text-muted:    #8aa0b0;
  --ai-text-dim:      #607888;
}
```

Cambiar estos valores rebrandea **toda la app** (vista 3D + vista IA) sin tocar reglas individuales. Si solo se quiere personalizar una vista en particular, sobreescribir con un selector más específico (`.ai-dashboard { --ai-accent: ... }`).

Los colores semánticos (`--ai-state-ok`, `--ai-state-warn`, `--ai-state-danger`) **no** se recomiendan cambiar — siguen convención universal verde/naranja/rojo.

## Seguridad

- ✅ Sidecar Python solo escucha en `127.0.0.1:8000`
- ✅ `.env` de ambos lados está en `.gitignore` (root y subcarpeta)
- ✅ Sin credenciales hardcoded en código nuevo
- ✅ Sin endpoints nuevos expuestos sin autenticación más allá de los del 3D original

## Troubleshooting

**El header muestra "🤖 IA +3min" pero la pantalla está vacía:**
- Verifica que `ai-predictor` esté corriendo en `127.0.0.1:8000` (`http://127.0.0.1:8000/healthz` debería responder JSON).

**Indicador "offline" en la vista IA:**
- El sidecar no está corriendo, o aún está cargando los modelos (~5–10 s).
- Mira la ventana del predictor: tiene que aparecer `Conectado a industrial.api.ubidots.com:1883`.

**"buffer N/30" persiste mucho tiempo:**
- El predictor necesita 30 muestras de los 6 sensores para emitir la primera predicción. Con `PREFILL_FROM_API=true` en `.env`, lo precarga de Ubidots. Si está en `false`, hay que esperar ~30 minutos de muestreo en vivo.

**Cambios al puerto del predictor:**
- Si necesitas mover el sidecar, exporta antes de arrancar Node: `set AI_PREDICTOR_BASE=http://127.0.0.1:9000`
