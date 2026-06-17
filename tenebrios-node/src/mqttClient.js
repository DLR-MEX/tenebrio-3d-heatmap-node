// Cliente MQTT para comunicacion con Ubidots (solo suscripcion).
// Suscribe a /v1.6/devices/{device}/+/lv y reenvia las lecturas parseadas
// a un callback. Los payloads /lv son strings numericos planos, NO JSON.
// Replica de backend/mqtt_client.py.

import mqtt from 'mqtt';

import {
  MQTT_BROKER,
  MQTT_PORT,
  UBIDOTS_TOKEN,
  DEVICE_LABEL,
  SENSOR_POSITIONS,
  EXTERIOR_TEMP_LABEL,
  FAN_LABEL,
  EXTRACTOR_LABEL,
  AVG_TEMP_SUPERIOR_LABEL,
  AVG_TEMP_INFERIOR_LABEL,
  RADIANT_FLOOR_LABELS,
  MACHINE_ROOM_LABELS,
  HUMIDITY_LABELS,
  AMMONIA_LABEL,
} from './config.js';
import { getLogger } from './logger.js';

const logger = getLogger('mqttClient');

// Todas las etiquetas de variables que nos interesan
export const ALL_VARIABLES = [
  ...Object.keys(SENSOR_POSITIONS),
  EXTERIOR_TEMP_LABEL,
  FAN_LABEL,
  EXTRACTOR_LABEL,
  AVG_TEMP_SUPERIOR_LABEL,
  AVG_TEMP_INFERIOR_LABEL,
  ...Object.keys(RADIANT_FLOOR_LABELS),
  ...Object.keys(MACHINE_ROOM_LABELS),
  ...HUMIDITY_LABELS,
  AMMONIA_LABEL,
];

// Topico comodin para recibir todas las variables del dispositivo
export const SUBSCRIBE_TOPIC = `/v1.6/devices/${DEVICE_LABEL}/+/lv`;

/**
 * Parsea un mensaje /lv (ultimo valor) de Ubidots.
 * Formato del topico: /v1.6/devices/{device}/{variable}/lv
 * Payload: cadena numerica plana como "25.4"
 * Retorna un objeto de una sola clave como {t1: 25.4} o null.
 */
export function parseLvMessage(topic, payloadRaw) {
  if (!topic || typeof topic !== 'string') return null;
  const parts = topic.replace(/^\/+|\/+$/g, '').split('/');
  // Esperado: ["v1.6", "devices", "{device}", "{variable}", "lv"]
  if (parts.length < 5 || parts[parts.length - 1] !== 'lv') return null;
  const variableLabel = parts[3];
  if (!ALL_VARIABLES.includes(variableLabel)) {
    logger.debug(`Ignoring unknown variable: ${variableLabel}`);
    return null;
  }

  let str;
  try {
    str = (typeof payloadRaw === 'string' ? payloadRaw : payloadRaw.toString('utf-8')).trim();
  } catch {
    logger.warn(`Cannot decode payload for '${variableLabel}'`);
    return null;
  }

  const value = Number(str);
  if (!Number.isFinite(value)) {
    logger.warn(`Cannot parse value for '${variableLabel}': ${str}`);
    return null;
  }

  return { [variableLabel]: value };
}

// Administra la conexion MQTT a Ubidots
export class MqttClient {
  constructor(onData) {
    this._onData = onData;
    this._connected = false;
    this._client = null;
  }

  isConnected() {
    return this._connected;
  }

  start() {
    const url = `mqtt://${MQTT_BROKER}:${MQTT_PORT}`;
    logger.info(`Connecting to ${MQTT_BROKER}:${MQTT_PORT} ...`);

    this._client = mqtt.connect(url, {
      username: UBIDOTS_TOKEN,
      password: '',
      protocolVersion: 4, // MQTT 3.1.1
      keepalive: 60,
      reconnectPeriod: 1000, // 1s, se incrementa hasta 60s con backoff
      connectTimeout: 30 * 1000,
    });

    this._client.on('connect', () => {
      this._connected = true;
      logger.info(`Connected to MQTT broker at ${MQTT_BROKER}:${MQTT_PORT}`);
      this._client.subscribe(SUBSCRIBE_TOPIC, (err) => {
        if (err) {
          logger.error(`Subscribe failed: ${err.message}`);
        } else {
          logger.info(`Subscribed to: ${SUBSCRIBE_TOPIC}`);
        }
      });
    });

    this._client.on('reconnect', () => {
      logger.warn('MQTT reconnecting...');
    });

    this._client.on('close', () => {
      this._connected = false;
    });

    this._client.on('error', (err) => {
      logger.error(`MQTT error: ${err.message}`);
    });

    this._client.on('message', (topic, payload) => {
      const data = parseLvMessage(topic, payload);
      if (data) {
        logger.info(`Received: ${JSON.stringify(data)}`);
        this._onData(data);
      }
    });
  }

  stop() {
    if (this._client) {
      this._client.end(true);
      logger.info('MQTT client stopped.');
    }
  }
}
