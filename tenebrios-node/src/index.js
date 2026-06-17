// Punto de entrada de la aplicacion de mapa de calor de temperatura.
// Inicializa el cliente MQTT (solo suscripcion) e inicia el servidor web.
// Replica de backend/main.py.

import { HeatmapEngine } from './heatmapEngine.js';
import { MqttClient } from './mqttClient.js';
import { createApp, setEngine, setMqttStatus, start } from './server.js';
import { WEB_HOST, WEB_PORT } from './config.js';
import { getLogger } from './logger.js';

const logger = getLogger('index');

async function main() {
  const engine = new HeatmapEngine();
  const client = new MqttClient((data) => engine.update(data));

  setEngine(engine);
  setMqttStatus(() => client.isConnected());

  client.start();
  logger.info('MQTT client started (subscribe-only). Launching web server...');

  const app = createApp();
  const server = await start(app, WEB_HOST, WEB_PORT);

  function shutdown() {
    logger.info('Shutting down...');
    client.stop();
    server.close(() => {
      logger.info('Application shut down.');
      process.exit(0);
    });
  }

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

main().catch((err) => {
  logger.error(`Fatal error: ${err.stack || err.message}`);
  process.exit(1);
});
