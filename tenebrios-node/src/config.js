// Modulo de configuracion para el sistema de mapa de calor en tiempo real.
// Replica exacta de backend/config.py manteniendo nombres y valores.

import 'dotenv/config';

// Configuracion MQTT / Ubidots
export const MQTT_BROKER = process.env.MQTT_BROKER || 'industrial.api.ubidots.com';
export const MQTT_PORT = parseInt(process.env.MQTT_PORT || '1883', 10);
export const UBIDOTS_TOKEN = process.env.UBIDOTS_TOKEN || '';
export const DEVICE_LABEL = process.env.DEVICE_LABEL || 'tenebrios';

// Topico MQTT base del dispositivo
export const MQTT_TOPIC = `/v1.6/devices/${DEVICE_LABEL}`;

// Etiquetas de sensores y sus coordenadas espaciales (x, y, z) en el cuarto
export const SENSOR_POSITIONS = {
  // Sensores superiores (centrados en Y=3)
  t1: [2, 3, 2.5],
  t2: [5, 3, 2.5],
  t3: [8, 3, 2.5],
  // Sensores interiores (centro, altura inferior)
  t4: [3, 3, 1.0],
  t5: [7, 3, 1.0],
};

// Posicion del sensor de temperatura exterior (sobre jardinera, pared trasera Y=6)
export const TEX_POSITION = [2, 6.15, 0.8];

// Limites del cuarto (metros)
export const ROOM_X_MIN = 0;
export const ROOM_X_MAX = 10;
export const ROOM_Y_MIN = 0;
export const ROOM_Y_MAX = 6;
export const ROOM_Z_MIN = 0;
export const ROOM_Z_MAX = 3;

// Etiquetas de variables adicionales
export const EXTERIOR_TEMP_LABEL = 'tex';
export const FAN_LABEL = 'ventilador';
export const EXTRACTOR_LABEL = 'extractor';

// Etiquetas de temperaturas promedio (superior e inferior)
export const AVG_TEMP_SUPERIOR_LABEL = 'tps';
export const AVG_TEMP_INFERIOR_LABEL = 'tpi';

// Etiquetas de sensores del piso radiante
export const RADIANT_FLOOR_LABELS = {
  temperatura1: 'Salida Piso',
  temperatura3: 'Medio Piso',
};

// Etiquetas de sensores de la sala de maquinas y solar
export const MACHINE_ROOM_LABELS = {
  temperatura2: 'Solar',
  temperatura4: 'Entrada Cuarto',
  temperatura5: 'Termo',
};

// Etiquetas de sensores de humedad
export const HUMIDITY_LABELS = ['h1', 'h2', 'h3', 'h4', 'h5', 'hum_general'];

// Etiqueta del sensor de amoniaco (PPM)
export const AMMONIA_LABEL = 'amoniaco';

// Resolucion de la grilla volumetrica 3D (puntos en X, Y, Z)
export const GRID_RES_X = 25;
export const GRID_RES_Y = 18;
export const GRID_RES_Z = 12;

// Rango de temperatura para visualizacion (ideal: 20-30 C)
export const HEATMAP_VMIN = 14.0;
export const HEATMAP_VMAX = 35.0;

// Rango valido de temperatura fisica (rechazar lecturas fuera de este rango)
export const TEMP_VALID_MIN = -10.0;
export const TEMP_VALID_MAX = 80.0;

// Intervalo de actualizacion del dashboard web en milisegundos
export const ANIMATION_INTERVAL_MS = 2000;

// Configuracion del servidor web
export const WEB_HOST = process.env.WEB_HOST || '0.0.0.0';
export const WEB_PORT = parseInt(process.env.WEB_PORT || '5000', 10);

// Nivel de log
export const LOG_LEVEL = process.env.LOG_LEVEL || 'info';
