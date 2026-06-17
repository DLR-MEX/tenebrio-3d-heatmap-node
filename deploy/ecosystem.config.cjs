// pm2 — gestiona los 3 procesos SIN sudo (auto-reinicio en crash + logs).
// Arranque: pm2 start deploy/ecosystem.config.cjs
// Los procesos heredan el entorno conda activando dentro de cada uno (bash -lc).
const HOME = process.env.HOME;
const ROOT = `${HOME}/tenebrio`;
const CONDA_ENV = 'tenebrio'; // env de conda con Python 3.12 + Node 20

// Activa conda y ejecuta el comando dado dentro del env.
const inEnv = (cmd) =>
  `source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate ${CONDA_ENV} && exec ${cmd}`;

module.exports = {
  apps: [
    {
      name: 'tenebrio-ai',
      cwd: `${ROOT}/ai-predictor`,
      script: 'bash',
      interpreter: 'none',
      args: ['-lc', inEnv('python -m uvicorn app.main:app --host 127.0.0.1 --port 8001')],
      autorestart: true,
      max_restarts: 10,
      // TensorFlow tarda en cargar; no lo marques caído antes de tiempo.
      min_uptime: '30s',
      out_file: `${ROOT}/logs/ai.out.log`,
      error_file: `${ROOT}/logs/ai.err.log`,
    },
    {
      name: 'tenebrio-node',
      cwd: `${ROOT}/tenebrios-node`,
      script: 'bash',
      interpreter: 'none',
      args: ['-lc', inEnv('node src/index.js')],
      env: { AI_PREDICTOR_BASE: 'http://127.0.0.1:8001' },
      autorestart: true,
      out_file: `${ROOT}/logs/node.out.log`,
      error_file: `${ROOT}/logs/node.err.log`,
    },
    {
      name: 'tenebrio-ngrok',
      cwd: ROOT,
      script: `${HOME}/bin/ngrok`,
      interpreter: 'none',
      args: `start --all --config ${ROOT}/ngrok.yml --log=stdout`,
      autorestart: true,
      out_file: `${ROOT}/logs/ngrok.out.log`,
      error_file: `${ROOT}/logs/ngrok.err.log`,
    },
  ],
};
