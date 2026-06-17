# Despliegue en VPS SIN sudo (conda + pm2 + ngrok)

Para un VPS donde **no tienes root**: todo vive en tu `$HOME`, sin `apt`, sin `/opt`,
sin systemd del sistema. Se conservan los dos servicios; la "unificación" es solo
operativa (Node es el front público, Python queda interno en `localhost`).

```
Internet ──ngrok──► Node/Express (0.0.0.0:5000)  dashboard 3D + proxy
                          │ HTTP loopback
                          ▼
                    Python/FastAPI (127.0.0.1:8001)  modelos GRU, reportes, Telegram, agente
                          │ MQTT
                          ▼
                       Ubidots (broker externo)
```

## Stack sin root
| Pieza | Cómo |
|---|---|
| Python 3.12 + Node 20 | entorno **conda** `tenebrio` (sin apt ni system Python) |
| Procesos | **pm2** (auto-reinicio en crash) |
| Persistencia tras reboot | **crontab `@reboot`** personal (no necesita sudo) |
| Túnel público | **ngrok** como binario en `~/bin` |

## Archivos
| Archivo | Qué es |
|---|---|
| `setup_nosudo.sh` | Provisión idempotente en tu home: env conda, deps Python/Node, Chromium de Playwright, pm2 y ngrok. |
| `ecosystem.config.cjs` | Config de pm2 con los 3 procesos (activan conda por dentro). |

## Uso

```bash
# 1) Clonar en el home (NO en /opt)
git clone -b feature/reportes-infra-y-exteriores \
  https://github.com/DLR-MEX/tenebrio-3d-heatmap-node.git ~/tenebrio

# 2) Provisión sin sudo
bash ~/tenebrio/deploy/setup_nosudo.sh
```

Luego los pasos con secretos (el script los recuerda al final):

### 1. `~/tenebrio/ai-predictor/.env`
```
UBIDOTS_TOKEN=BBUS-...
UBIDOTS_DEVICE_LABEL=tenebrios
APP_HOST=127.0.0.1
APP_PORT=8001
LOG_LEVEL=INFO
TELEGRAM_ENABLED=false        # se activa luego desde la UI
AGENT_ENABLED=true
OLLAMA_API_KEY=...            # si AGENT_ENABLED
```

### 2. `~/tenebrio/tenebrios-node/.env`
```
UBIDOTS_TOKEN=BBUS-...
DEVICE_LABEL=tenebrios
WEB_HOST=0.0.0.0
WEB_PORT=5000
AI_PREDICTOR_BASE=http://127.0.0.1:8001
LOG_LEVEL=info
```

### 3. ngrok
```bash
~/bin/ngrok config add-authtoken TU_AUTHTOKEN
```
`~/tenebrio/ngrok.yml`:
```yaml
version: "3"
agent:
  authtoken: TU_AUTHTOKEN_DE_NGROK
tunnels:
  dashboard:
    proto: http
    addr: 5000
    # domain: tu-dominio.ngrok-free.app   # dominio reservado -> URL fija (recomendado)
```
```bash
chmod 600 ~/tenebrio/*/.env ~/tenebrio/ngrok.yml
```

### 4. Arrancar y persistir
```bash
conda activate tenebrio
pm2 start ~/tenebrio/deploy/ecosystem.config.cjs
pm2 save
# Persistencia tras reboot SIN sudo:
(crontab -l 2>/dev/null; echo "@reboot $(command -v pm2) resurrect") | crontab -
```

## Verificación
```bash
curl -s http://127.0.0.1:8001/healthz             # sidecar (espera ~25s tras start por carga de TF)
curl -s http://127.0.0.1:5000 | head              # dashboard Node
curl -s http://127.0.0.1:5000/api/predictor/state # proxy Node->Python
curl -s http://127.0.0.1:4040/api/tunnels         # URL pública de ngrok
pm2 status                                        # estado de los 3 procesos
pm2 logs tenebrio-ai                              # logs en vivo
```

## Operación diaria
```bash
pm2 restart tenebrio-node     # reiniciar un servicio
pm2 stop all                  # parar todo
pm2 start all                 # arrancar todo
pm2 logs                      # ver logs de los 3
```

## Notas / riesgos sin sudo
- **Playwright/Chromium (PDF de reportes):** es el único punto frágil sin root. El navegador
  se descarga a `~/.cache` sin problema, pero Chromium necesita libs de sistema. Si al generar
  un PDF ves un error tipo `error while loading shared libraries: libnss3.so`, instala las libs
  vía conda-forge en el env (sin sudo):
  ```bash
  conda install -y -n tenebrio -c conda-forge \
    nss nspr atk at-spi2-atk at-spi2-core cups-libs libxcomposite \
    libxdamage libxrandr libxkbcommon libgbm pango alsa-lib
  ```
  El resto del sistema (dashboard, predicción, MQTT, Telegram, agente) funciona aunque esto falle.
- **RAM:** TensorFlow consume varios cientos de MB → conviene ≥2 GB libres (recomendado 4 GB).
- **Arranque limpio:** las DBs (`alert_log.sqlite`, `reports/jobs.sqlite`) y `runtime_config.json`
  se crean vacías en el primer arranque. Telegram se reconfigura desde la UI.
- **ngrok gratis:** la URL cambia en cada reinicio y muestra una página intersticial la 1ª vez.
  Reserva un dominio ngrok (gratis, 1 por cuenta) para URL fija.
- **Persistencia:** pm2 reinicia procesos caídos mientras la sesión/host esté arriba; el
  `@reboot` de cron los resucita tras un reinicio del VPS — todo sin sudo.
