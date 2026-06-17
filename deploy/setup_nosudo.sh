#!/usr/bin/env bash
#
# setup_nosudo.sh — Provisión del proyecto Tenebrio SIN sudo (todo en tu $HOME, vía conda).
#
# Pensado para un VPS donde NO tienes root: nada de apt, /opt ni systemd del sistema.
#   - Python 3.12 + Node 20  -> entorno conda 'tenebrio'
#   - Procesos               -> pm2 (auto-reinicio) + crontab @reboot (persistencia sin sudo)
#   - ngrok                  -> binario en ~/bin
#
# Requisitos previos:
#   - conda ya instalado y disponible (tienes el env 'deepseek', así que sí).
#   - Repo clonado en ~/tenebrio:
#       git clone -b feature/reportes-infra-y-exteriores \
#         https://github.com/DLR-MEX/tenebrio-3d-heatmap-node.git ~/tenebrio
#
# Uso:
#   bash ~/tenebrio/deploy/setup_nosudo.sh
#
# Idempotente: re-ejecutable sin romper nada.
#
set -euo pipefail

ROOT="$HOME/tenebrio"
CONDA_ENV="tenebrio"
PY_VER="3.12"
NODE_VER="20"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[[ -d "$ROOT" ]] || die "No existe $ROOT. Clona el repo primero (ver cabecera de este script)."
command -v conda >/dev/null 2>&1 || die "conda no está en PATH. Activa tu base de conda y reintenta."

mkdir -p "$ROOT/logs" "$HOME/bin"

# --- Cargar conda en este shell no-interactivo --------------------------------
source "$(conda info --base)/etc/profile.d/conda.sh"

# --- 1) Entorno conda: Python 3.12 + Node 20 ---------------------------------
log "1/6 Entorno conda '$CONDA_ENV' (Python $PY_VER + Node $NODE_VER)"
if ! conda env list | grep -qE "^\s*$CONDA_ENV\s"; then
  conda create -y -n "$CONDA_ENV" -c conda-forge "python=$PY_VER" "nodejs=$NODE_VER"
else
  conda install -y -n "$CONDA_ENV" -c conda-forge "nodejs=$NODE_VER"
fi
conda activate "$CONDA_ENV"
echo "python: $(python --version)  |  node: $(node -v)"

# --- 2) Sidecar Python (deps + Chromium de Playwright) -----------------------
log "2/6 Dependencias Python (ai-predictor)"
cd "$ROOT/ai-predictor"
pip install .
log "    Navegador de Playwright (para PDFs de reportes)"
# Descarga el Chromium de Playwright a ~/.cache (sin sudo).
python -m playwright install chromium || \
  echo "AVISO: 'playwright install chromium' falló; los PDF pueden no generarse. Ver nota en README."

# --- 3) Dashboard Node -------------------------------------------------------
log "3/6 Dependencias Node (tenebrios-node)"
cd "$ROOT/tenebrios-node"
npm install --omit=dev

# --- 4) pm2 (gestor de procesos, instalado dentro del env conda) -------------
log "4/6 pm2"
npm install -g pm2   # va al prefix de conda (escribible), no necesita sudo

# --- 5) ngrok (binario en ~/bin) --------------------------------------------
log "5/6 ngrok"
if [[ ! -x "$HOME/bin/ngrok" ]]; then
  case "$(uname -m)" in
    x86_64)        NG_ARCH="amd64" ;;
    aarch64|arm64) NG_ARCH="arm64" ;;
    *) die "Arquitectura $(uname -m) no soportada por este instalador de ngrok." ;;
  esac
  curl -fsSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${NG_ARCH}.tgz" -o /tmp/ngrok.tgz
  tar -xzf /tmp/ngrok.tgz -C "$HOME/bin"
  rm -f /tmp/ngrok.tgz
fi
"$HOME/bin/ngrok" version

# --- 6) Hecho. Pasos manuales (secretos) -------------------------------------
log "6/6 Provisión completada"
cat <<EOF

============================================================================
 FALTAN los pasos con secretos (no se versionan):

 1) .env de Python  -> $ROOT/ai-predictor/.env
      UBIDOTS_TOKEN=BBUS-...
      UBIDOTS_DEVICE_LABEL=tenebrios
      APP_HOST=127.0.0.1
      APP_PORT=8001
      LOG_LEVEL=INFO
      TELEGRAM_ENABLED=false
      AGENT_ENABLED=true
      OLLAMA_API_KEY=...

 2) .env de Node    -> $ROOT/tenebrios-node/.env
      UBIDOTS_TOKEN=BBUS-...
      DEVICE_LABEL=tenebrios
      WEB_HOST=0.0.0.0
      WEB_PORT=5000
      AI_PREDICTOR_BASE=http://127.0.0.1:8001
      LOG_LEVEL=info

 3) ngrok: autentica y crea el config:
      ~/bin/ngrok config add-authtoken TU_AUTHTOKEN
      # luego crea $ROOT/ngrok.yml (ver deploy/README.md)
    chmod 600 $ROOT/*/.env $ROOT/ngrok.yml

 4) Arranca con pm2:
      conda activate $CONDA_ENV
      pm2 start $ROOT/deploy/ecosystem.config.cjs
      pm2 save

 5) Persistencia tras reboot SIN sudo (crontab personal):
      (crontab -l 2>/dev/null; echo "@reboot \$(command -v pm2) resurrect") | crontab -
    Nota: pm2 debe estar en PATH al reiniciar; si no, usa la ruta absoluta de pm2.

 6) Verifica:
      curl -s http://127.0.0.1:8001/healthz
      curl -s http://127.0.0.1:5000 | head
      curl -s http://127.0.0.1:4040/api/tunnels   # URL pública de ngrok
============================================================================
EOF
