// Servidor web Express para visualizacion de mapa de calor volumetrico 3D.
// Sirve la pagina HTML con un render Babylon.js que se actualiza consultando
// el endpoint JSON. Replica de backend/visualization.py.

import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import express from 'express';

// Timestamp generado al arrancar el servidor; se inyecta como query string en
// los recursos HTML para forzar al navegador a refrescar su cache.
const BUILD_VERSION = Date.now().toString(36);

import {
  ANIMATION_INTERVAL_MS,
  ROOM_X_MIN,
  ROOM_X_MAX,
  ROOM_Y_MIN,
  ROOM_Y_MAX,
  ROOM_Z_MIN,
  ROOM_Z_MAX,
  HEATMAP_VMIN,
  HEATMAP_VMAX,
  SENSOR_POSITIONS,
  TEX_POSITION,
  HUMIDITY_LABELS,
  RADIANT_FLOOR_LABELS,
  MACHINE_ROOM_LABELS,
  EXTERIOR_TEMP_LABEL,
  FAN_LABEL,
  EXTRACTOR_LABEL,
  AVG_TEMP_SUPERIOR_LABEL,
  AVG_TEMP_INFERIOR_LABEL,
  AMMONIA_LABEL,
} from './config.js';
import { getLogger } from './logger.js';
import { fetchUbidotsValues } from './ubidotsApi.js';
import { interpolateGrid, clipInPlace } from './interpolation.js';

const logger = getLogger('server');
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PUBLIC_DIR = path.resolve(__dirname, '..', 'public');

// Sidecar Python (ai-predictor): se ejecuta en otro proceso. El frontend
// nunca lo llama directo; este server lo proxea para que el usuario solo
// vea localhost:5000 y el sidecar permanezca en 127.0.0.1.
const AI_PREDICTOR_BASE = process.env.AI_PREDICTOR_BASE || 'http://127.0.0.1:8000';

let _engine = null;
let _mqttStatusFn = () => false;

export function setEngine(engine) {
  _engine = engine;
}

export function setMqttStatus(fn) {
  _mqttStatusFn = fn;
}

/**
 * Redondea a N decimales o devuelve null si el valor no esta definido.
 */
function r(value, decimals = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const f = Math.pow(10, decimals);
  return Math.round(value * f) / f;
}

export function createApp() {
  const app = express();

  // Estaticos del frontend — sin cache para que los cambios en JS/CSS/HTML
  // se reflejen siempre al recargar (el dashboard pollea cada 2s, no necesita cache).
  app.use(express.static(PUBLIC_DIR, {
    etag: false,
    lastModified: false,
    index: false, // desactivar auto-servido de index.html — lo maneja app.get('/')
    setHeaders: (res) => {
      res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
      res.setHeader('Pragma', 'no-cache');
      res.setHeader('Expires', '0');
      res.setHeader('Surrogate-Control', 'no-store');
    },
  }));

  // Endpoint que el cliente lee al inicio para conocer el intervalo de refresco
  app.get('/api/config', (req, res) => {
    res.json({ refresh_ms: ANIMATION_INTERVAL_MS });
  });

  app.get('/', (req, res) => {
    // Inyectar BUILD_VERSION en los src de scripts/css para invalidar cache
    // del navegador cada vez que se reinicia el servidor.
    let html = fs.readFileSync(path.join(PUBLIC_DIR, 'index.html'), 'utf-8');
    html = html.replace(/(src|href)="\/(js|css)\/([^"]+)"/g,
      (_, attr, dir, file) => `${attr}="/${dir}/${file}?v=${BUILD_VERSION}"`);
    res.set('Content-Type', 'text/html; charset=utf-8');
    res.set('Cache-Control', 'no-store');
    res.send(html);
  });

  // --- /api/data ---------------------------------------------------------
  app.get('/api/data', (req, res) => {
    if (_engine === null) {
      return res.status(503).json({ error: 'Engine not initialized' });
    }

    const volume = _engine.interpolateVolume();
    const humidityVolume = _engine.interpolateHumidityVolume();

    const sensorValues = {};
    for (const label of Object.keys(SENSOR_POSITIONS)) {
      const v = _engine.getSensorValue(label);
      if (v !== null) sensorValues[label] = r(v, 1);
    }

    const extTemp = _engine.getExteriorTemp();
    const texSensor = {
      x: TEX_POSITION[0],
      y: TEX_POSITION[1],
      z: TEX_POSITION[2],
      value: r(extTemp, 1),
    };

    const sensorsBlock = {};
    for (const [label, pos] of Object.entries(SENSOR_POSITIONS)) {
      sensorsBlock[label] = {
        x: pos[0], y: pos[1], z: pos[2],
        value: sensorValues[label] ?? null,
      };
    }

    const humidityBlock = {};
    for (const label of HUMIDITY_LABELS) {
      humidityBlock[label] = r(_engine.getHumidity(label), 1);
    }

    const radiantBlock = {};
    for (const [label, desc] of Object.entries(RADIANT_FLOOR_LABELS)) {
      radiantBlock[label] = {
        value: r(_engine.getRadiantFloor(label), 1),
        name: desc,
      };
    }

    const machineBlock = {};
    for (const [label, desc] of Object.entries(MACHINE_ROOM_LABELS)) {
      machineBlock[label] = {
        value: r(_engine.getMachineRoom(label), 1),
        name: desc,
      };
    }

    res.json({
      volume_data: volume,
      humidity_volume_data: humidityVolume,
      x_range: [ROOM_X_MIN, ROOM_X_MAX],
      y_range: [ROOM_Y_MIN, ROOM_Y_MAX],
      z_range: [ROOM_Z_MIN, ROOM_Z_MAX],
      vmin: HEATMAP_VMIN,
      vmax: HEATMAP_VMAX,
      exterior_temp: extTemp,
      avg_temp_superior: r(_engine.getAvgTempSuperior(), 1),
      avg_temp_inferior: r(_engine.getAvgTempInferior(), 1),
      fan_on: _engine.getFanState(),
      extractor_on: _engine.getExtractorState(),
      mqtt_connected: _mqttStatusFn(),
      sensors: sensorsBlock,
      tex_sensor: texSensor,
      humidity: humidityBlock,
      amoniaco: r(_engine.getAmmoniaPpm(), 2),
      radiant_floor: radiantBlock,
      machine_room: machineBlock,
      last_update: _engine.getLastUpdate(),
    });
  });

  // --- /api/history ------------------------------------------------------
  app.get('/api/history', async (req, res) => {
    const startDate = req.query.start;
    const endDate = req.query.end;
    if (!startDate || !endDate) {
      return res.status(400).json({ error: 'Parametros start y end requeridos (YYYY-MM-DD)' });
    }

    const startDt = new Date(`${startDate}T00:00:00`);
    const endDt = new Date(`${endDate}T00:00:00`);
    if (Number.isNaN(startDt.getTime()) || Number.isNaN(endDt.getTime())) {
      return res.status(400).json({ error: 'Formato de fecha invalido, usar YYYY-MM-DD' });
    }

    const diffDays = Math.floor((endDt.getTime() - startDt.getTime()) / 86400000);
    if (diffDays > 31) {
      return res.status(400).json({ error: 'Rango maximo permitido: 31 dias' });
    }
    if (diffDays < 0) {
      return res.status(400).json({ error: 'Fecha de inicio debe ser anterior a fecha de fin' });
    }

    const startMs = startDt.getTime();
    const endMs = endDt.getTime() + 86400000;

    const tempVars = Object.keys(SENSOR_POSITIONS);
    const extraTempVars = [EXTERIOR_TEMP_LABEL, AVG_TEMP_SUPERIOR_LABEL, AVG_TEMP_INFERIOR_LABEL];
    const humVars = HUMIDITY_LABELS;
    const radiantVars = Object.keys(RADIANT_FLOOR_LABELS);
    const machineVars = Object.keys(MACHINE_ROOM_LABELS);
    const otherVars = [AMMONIA_LABEL, FAN_LABEL, EXTRACTOR_LABEL];

    const result = {
      timestamps: [],
      temperature: {},
      humidity: {},
      radiant_floor: {},
      machine_room: {},
      other: {},
    };

    const allTimestamps = new Set();

    async function fillCategory(vars, key) {
      for (const v of vars) {
        const values = await fetchUbidotsValues(v, startMs, endMs);
        result[key][v] = values.map((row) => ({
          timestamp: row.timestamp,
          value: row.value,
        }));
        for (const row of values) allTimestamps.add(row.timestamp);
      }
    }

    await fillCategory(tempVars, 'temperature');
    await fillCategory(extraTempVars, 'temperature');
    await fillCategory(humVars, 'humidity');
    await fillCategory(radiantVars, 'radiant_floor');
    await fillCategory(machineVars, 'machine_room');
    await fillCategory(otherVars, 'other');

    result.timestamps = Array.from(allTimestamps).sort((a, b) => a - b);

    res.json(result);
  });

  // --- /api/history/interpolate -----------------------------------------
  app.get('/api/history/interpolate', (req, res) => {
    if (_engine === null) {
      return res.status(503).json({ error: 'Engine not initialized' });
    }

    const tempData = req.query.temps;
    const humData = req.query.hums;
    if (!tempData) {
      return res.status(400).json({ error: 'Parametro temps requerido' });
    }

    let temps, hums;
    try {
      temps = JSON.parse(tempData);
      hums = humData ? JSON.parse(humData) : {};
    } catch {
      return res.status(400).json({ error: 'JSON invalido' });
    }

    const sensorLabels = _engine.sensorLabels;
    const sensorCoords = _engine.sensorCoords;
    const gridX = _engine.gridX;
    const gridY = _engine.gridY;
    const gridZ = _engine.gridZ;

    function buildVolume(valueMap, indexMap, vmin, vmax) {
      const coords = [];
      const values = [];
      for (const [label, idx] of indexMap) {
        if (label in valueMap && valueMap[label] !== null && valueMap[label] !== undefined) {
          values.push(valueMap[label]);
          coords.push(sensorCoords[idx]);
        }
      }
      if (values.length < 3) return null;
      const vol = interpolateGrid(coords, values, gridX, gridY, gridZ);
      clipInPlace(vol, vmin, vmax);
      return {
        x: Array.from(gridX),
        y: Array.from(gridY),
        z: Array.from(gridZ),
        value: Array.from(vol),
      };
    }

    const tempIndexMap = sensorLabels.map((l, i) => [l, i]);
    const humIndexMap = [['h1', 0], ['h2', 1], ['h3', 2], ['h4', 3], ['h5', 4]];

    const tempVol = buildVolume(temps, tempIndexMap, HEATMAP_VMIN, HEATMAP_VMAX);
    const humVol = buildVolume(hums, humIndexMap, 0, 100);

    res.json({
      volume_data: tempVol,
      humidity_volume_data: humVol,
    });
  });

  // Helper: proxy JSON simple hacia el sidecar Python. Timeout de 6s para
  // que si Python esta caido o muy lento, el frontend reciba 504 con un
  // mensaje claro en vez de quedar pegado.
  const PROXY_TIMEOUT_MS = 6000;
  async function proxyJson(method, path, req, res) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
    try {
      const init = { method, signal: controller.signal };
      if (method === 'POST') {
        init.headers = { 'Content-Type': 'application/json' };
        init.body = JSON.stringify(req.body || {});
      }
      const upstream = await fetch(`${AI_PREDICTOR_BASE}${path}`, init);
      const text = await upstream.text();
      res.status(upstream.status);
      res.set('Cache-Control', 'no-store');
      res.set('Content-Type', upstream.headers.get('content-type') || 'application/json');
      res.send(text);
    } catch (err) {
      const isAbort = err.name === 'AbortError';
      const status = isAbort ? 504 : 503;
      const reason = isAbort
        ? `timeout (>${PROXY_TIMEOUT_MS}ms) hablando con ${AI_PREDICTOR_BASE}${path}`
        : `${AI_PREDICTOR_BASE}${path} inalcanzable: ${err.message}`;
      logger.warn(`predictor ${method} ${path}: ${reason}`);
      res.status(status).json({ error: reason });
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // --- /api/predictor/state -------------------------------------------------
  // Proxy hacia el sidecar Python (FastAPI). Devuelve el snapshot del
  // predictor (current/predicted/history). Si el sidecar esta caido, el
  // frontend recibe 503 y muestra el indicador "offline" sin romper la UI 3D.
  app.get('/api/predictor/state', (req, res) => proxyJson('GET', '/api/state', req, res));

  // --- /api/predictor/telegram (GET) ---------------------------------------
  // Devuelve { enabled, chat_id, cooldown_sec, token_configured }.
  // NUNCA incluye el bot_token.
  app.get('/api/predictor/telegram', (req, res) => proxyJson('GET', '/api/telegram', req, res));

  // --- /api/predictor/telegram (POST) --------------------------------------
  // Acepta { chat_id?, enabled?, cooldown_sec? }. Rechaza intentos de
  // inyectar bot_token. Persiste a runtime_config.json en el sidecar.
  app.post('/api/predictor/telegram', express.json({ limit: '1kb' }), (req, res) =>
    proxyJson('POST', '/api/telegram', req, res));

  // --- /api/predictor/telegram/test ----------------------------------------
  // Manda un mensaje de prueba al chat configurado.
  app.post('/api/predictor/telegram/test', (req, res) =>
    proxyJson('POST', '/api/telegram/test', req, res));

  // --- /api/predictor/agent/chat -------------------------------------------
  // Proxy del agente IA conversacional. Body acepta hasta 32kb (mensajes
  // pueden incluir history). El timeout efectivo lo da el AbortController de
  // proxyJson; lo elevamos para chat porque las queries con tool calls pueden
  // tardar 5-15s (multiples roundtrips al LLM y a Ubidots).
  const agentJsonParser = express.json({ limit: '32kb' });
  // 200s: la mayoria de queries responden en 5-30s, pero generar un
  // reporte PDF (tool generate_report) recolecta histórico de Ubidots +
  // 4 llamadas LLM + render Playwright. Aun paralelizado puede tomar
  // 60-120s. El widget muestra progreso rotativo durante la espera.
  const AGENT_CHAT_TIMEOUT_MS = 200000;
  app.post('/api/predictor/agent/chat', agentJsonParser, async (req, res) => {
    const upstreamUrl = `${AI_PREDICTOR_BASE}/api/agent/chat`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), AGENT_CHAT_TIMEOUT_MS);
    try {
      const upstream = await fetch(upstreamUrl, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body || {}),
      });
      const text = await upstream.text();
      res.status(upstream.status);
      res.set('Cache-Control', 'no-store');
      res.set('Content-Type', upstream.headers.get('content-type') || 'application/json');
      res.send(text);
    } catch (err) {
      const isAbort = err.name === 'AbortError';
      logger.warn(`agent chat: ${isAbort ? `timeout (>${AGENT_CHAT_TIMEOUT_MS}ms)` : err.message}`);
      res.status(isAbort ? 504 : 503).json({
        error: isAbort
          ? `El agente tardó más de ${Math.round(AGENT_CHAT_TIMEOUT_MS / 1000)}s en responder. Intenta una pregunta más específica.`
          : `Agente inalcanzable: ${err.message}`,
      });
    } finally {
      clearTimeout(timeoutId);
    }
  });

  // --- /api/predictor/reports/* --------------------------------------------
  // Proxy de los endpoints de reportes ejecutivos. Incluye:
  //   POST /api/predictor/reports/generate   (genera, lento 30-60s)
  //   GET  /api/predictor/reports            (lista)
  //   GET  /api/predictor/reports/<id>       (descarga PDF binario)
  //   GET  /api/predictor/reports/<id>/preview (PNG primera pagina)
  // Para los binarios (PDF, PNG) hacemos stream pasa-through.
  const REPORTS_TIMEOUT_MS = 120000; // 2 min para generate (con LLM tarda)

  app.post('/api/predictor/reports/generate', agentJsonParser, async (req, res) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REPORTS_TIMEOUT_MS);
    try {
      const upstream = await fetch(`${AI_PREDICTOR_BASE}/api/reports/generate`, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body || {}),
      });
      const text = await upstream.text();
      res.status(upstream.status);
      res.set('Cache-Control', 'no-store');
      res.set('Content-Type', upstream.headers.get('content-type') || 'application/json');
      res.send(text);
    } catch (err) {
      const isAbort = err.name === 'AbortError';
      logger.warn(`report generate: ${isAbort ? 'timeout' : err.message}`);
      res.status(isAbort ? 504 : 503).json({
        error: isAbort
          ? `La generación del reporte tardó más de ${REPORTS_TIMEOUT_MS / 1000}s.`
          : `Sidecar inalcanzable: ${err.message}`,
      });
    } finally {
      clearTimeout(timeoutId);
    }
  });

  app.get('/api/predictor/reports', (req, res) =>
    proxyJson('GET', '/api/reports', req, res));

  // Proxy binarios (PDF y PNG): stream pasa-through
  async function proxyBinary(upstreamPath, req, res) {
    try {
      const upstream = await fetch(`${AI_PREDICTOR_BASE}${upstreamPath}`);
      if (!upstream.ok) {
        return res.status(upstream.status).json({ error: `upstream HTTP ${upstream.status}` });
      }
      res.status(200);
      res.set('Content-Type', upstream.headers.get('content-type') || 'application/octet-stream');
      const contentDisposition = upstream.headers.get('content-disposition');
      if (contentDisposition) res.set('Content-Disposition', contentDisposition);
      // Stream el body al cliente
      const arrayBuffer = await upstream.arrayBuffer();
      res.send(Buffer.from(arrayBuffer));
    } catch (err) {
      logger.warn(`proxy binary ${upstreamPath}: ${err.message}`);
      res.status(503).json({ error: 'sidecar inalcanzable' });
    }
  }

  app.get('/api/predictor/reports/:id', (req, res) => {
    const id = req.params.id;
    if (!/^[A-Za-z0-9_\-]{1,64}$/.test(id)) {
      return res.status(400).json({ error: 'id invalido' });
    }
    proxyBinary(`/api/reports/${encodeURIComponent(id)}`, req, res);
  });

  app.get('/api/predictor/reports/:id/preview', (req, res) => {
    const id = req.params.id;
    if (!/^[A-Za-z0-9_\-]{1,64}$/.test(id)) {
      return res.status(400).json({ error: 'id invalido' });
    }
    proxyBinary(`/api/reports/${encodeURIComponent(id)}/preview`, req, res);
  });

  // --- /api/predictor/stream ------------------------------------------------
  // Proxy SSE: pasa-through del stream del sidecar. Mantiene los eventos
  // (snapshot/update/ping) sin transformar; el cliente los consume con
  // EventSource exactamente igual que si hablara directo con FastAPI.
  app.get('/api/predictor/stream', async (req, res) => {
    let upstream;
    try {
      upstream = await fetch(`${AI_PREDICTOR_BASE}/api/stream`, {
        headers: { Accept: 'text/event-stream' },
      });
    } catch (err) {
      logger.warn(`predictor stream unreachable: ${err.message}`);
      return res.status(503).json({ error: 'predictor offline' });
    }
    if (!upstream.ok || !upstream.body) {
      return res.status(upstream.status || 502).json({ error: 'predictor upstream error' });
    }

    res.set({
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-store',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    res.flushHeaders?.();

    const reader = upstream.body.getReader();
    req.on('close', () => {
      try { reader.cancel(); } catch {}
    });

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) res.write(value);
      }
    } catch (err) {
      logger.warn(`predictor stream interrumpido: ${err.message}`);
    } finally {
      try { res.end(); } catch {}
    }
  });

  return app;
}

export function start(app, host, port) {
  return new Promise((resolve) => {
    const server = app.listen(port, host, () => {
      logger.info(`Starting web server on http://${host}:${port}`);
      resolve(server);
    });
  });
}
