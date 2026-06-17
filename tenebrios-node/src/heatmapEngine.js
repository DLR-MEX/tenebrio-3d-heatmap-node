// Motor de interpolacion del mapa de calor (volumetrico 3D).
// Almacena las ultimas temperaturas/humedades de los sensores y produce
// un volumen 3D interpolado equivalente a scipy.interpolate.griddata.
// Replica de backend/heatmap_engine.py.

import {
  SENSOR_POSITIONS,
  TEMP_VALID_MIN,
  TEMP_VALID_MAX,
  HEATMAP_VMIN,
  HEATMAP_VMAX,
  ROOM_X_MIN,
  ROOM_X_MAX,
  ROOM_Y_MIN,
  ROOM_Y_MAX,
  ROOM_Z_MIN,
  ROOM_Z_MAX,
  GRID_RES_X,
  GRID_RES_Y,
  GRID_RES_Z,
  EXTERIOR_TEMP_LABEL,
  FAN_LABEL,
  EXTRACTOR_LABEL,
  AVG_TEMP_SUPERIOR_LABEL,
  AVG_TEMP_INFERIOR_LABEL,
  HUMIDITY_LABELS,
  RADIANT_FLOOR_LABELS,
  MACHINE_ROOM_LABELS,
  AMMONIA_LABEL,
} from './config.js';
import { getLogger } from './logger.js';
import {
  linspace,
  buildFlatGrid,
  interpolateGrid,
  clipInPlace,
} from './interpolation.js';

const logger = getLogger('heatmapEngine');

function isValidTemperature(value) {
  return value >= TEMP_VALID_MIN && value <= TEMP_VALID_MAX;
}

function nowTimestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

export class HeatmapEngine {
  constructor() {
    this._temperatures = {};
    this._exteriorTemp = null;
    this._fanState = false;
    this._extractorState = false;
    this._avgTempSuperior = null;
    this._avgTempInferior = null;
    this._humidity = {};
    this._ammoniaPpm = null;
    this._radiantFloor = {};
    this._machineRoom = {};
    this._lastUpdate = null;

    this._sensorLabels = Object.keys(SENSOR_POSITIONS);
    this._sensorCoords = this._sensorLabels.map((s) => SENSOR_POSITIONS[s]);

    // Pre-calcula la grilla 3D aplanada en orden x-mas-rapido.
    const gx = linspace(ROOM_X_MIN, ROOM_X_MAX, GRID_RES_X);
    const gy = linspace(ROOM_Y_MIN, ROOM_Y_MAX, GRID_RES_Y);
    const gz = linspace(ROOM_Z_MIN, ROOM_Z_MAX, GRID_RES_Z);
    const flat = buildFlatGrid(gx, gy, gz);
    this._gridX = flat.x;
    this._gridY = flat.y;
    this._gridZ = flat.z;
  }

  // -----------------------------------------------------------------
  // Ingesta de datos
  // -----------------------------------------------------------------

  update(data) {
    this._lastUpdate = nowTimestamp();

    for (const label of this._sensorLabels) {
      if (label in data) {
        const value = data[label];
        if (isValidTemperature(value)) {
          this._temperatures[label] = value;
        } else {
          logger.warn(`Rejected ${label}=${value.toFixed(1)}: outside valid range`);
        }
      }
    }

    if (EXTERIOR_TEMP_LABEL in data) {
      const value = data[EXTERIOR_TEMP_LABEL];
      if (isValidTemperature(value)) this._exteriorTemp = value;
      else logger.warn(`Rejected tex=${value.toFixed(1)}: outside valid range`);
    }

    if (FAN_LABEL in data) this._fanState = data[FAN_LABEL] >= 1.0;
    if (EXTRACTOR_LABEL in data) this._extractorState = data[EXTRACTOR_LABEL] >= 1.0;

    if (AVG_TEMP_SUPERIOR_LABEL in data) {
      const v = data[AVG_TEMP_SUPERIOR_LABEL];
      if (isValidTemperature(v)) this._avgTempSuperior = v;
    }
    if (AVG_TEMP_INFERIOR_LABEL in data) {
      const v = data[AVG_TEMP_INFERIOR_LABEL];
      if (isValidTemperature(v)) this._avgTempInferior = v;
    }

    for (const label of HUMIDITY_LABELS) {
      if (label in data) this._humidity[label] = data[label];
    }

    for (const label of Object.keys(RADIANT_FLOOR_LABELS)) {
      if (label in data) this._radiantFloor[label] = data[label];
    }

    for (const label of Object.keys(MACHINE_ROOM_LABELS)) {
      if (label in data) this._machineRoom[label] = data[label];
    }

    if (AMMONIA_LABEL in data) this._ammoniaPpm = data[AMMONIA_LABEL];
  }

  // -----------------------------------------------------------------
  // Interpolacion 3D
  // -----------------------------------------------------------------

  /**
   * Helper interno: interpolacion volumetrica con clip a [vmin, vmax].
   * Recibe pares (label, idx-en-_sensorCoords) para mapear el dato a una posicion.
   * Retorna {x, y, z, value} aplanados, o null si hay menos de 3 puntos.
   */
  _interpolate(pairs, lookup, vmin, vmax) {
    const coords = [];
    const values = [];
    for (const [label, idx] of pairs) {
      if (label in lookup && lookup[label] != null) {
        values.push(lookup[label]);
        coords.push(this._sensorCoords[idx]);
      }
    }
    if (values.length < 3) return null;

    const volume = interpolateGrid(coords, values, this._gridX, this._gridY, this._gridZ);
    clipInPlace(volume, vmin, vmax);

    return {
      x: Array.from(this._gridX),
      y: Array.from(this._gridY),
      z: Array.from(this._gridZ),
      value: Array.from(volume),
    };
  }

  interpolateVolume() {
    const pairs = this._sensorLabels.map((l, i) => [l, i]);
    return this._interpolate(pairs, this._temperatures, HEATMAP_VMIN, HEATMAP_VMAX);
  }

  interpolateHumidityVolume() {
    // h1..h5 comparten posicion con t1..t5 (indices 0..4)
    const map = [['h1', 0], ['h2', 1], ['h3', 2], ['h4', 3], ['h5', 4]];
    return this._interpolate(map, this._humidity, 0, 100);
  }

  // -----------------------------------------------------------------
  // Accesores expuestos para el endpoint de historial (parametrizado)
  // -----------------------------------------------------------------

  get gridX() { return this._gridX; }
  get gridY() { return this._gridY; }
  get gridZ() { return this._gridZ; }
  get sensorLabels() { return this._sensorLabels; }
  get sensorCoords() { return this._sensorCoords; }

  // -----------------------------------------------------------------
  // Accesores
  // -----------------------------------------------------------------

  getSensorValue(label) { return this._temperatures[label] ?? null; }
  getExteriorTemp() { return this._exteriorTemp; }
  getFanState() { return this._fanState; }
  getExtractorState() { return this._extractorState; }
  getAvgTempSuperior() { return this._avgTempSuperior; }
  getAvgTempInferior() { return this._avgTempInferior; }
  getHumidity(label) { return this._humidity[label] ?? null; }
  getAmmoniaPpm() { return this._ammoniaPpm; }
  getRadiantFloor(label) { return this._radiantFloor[label] ?? null; }
  getMachineRoom(label) { return this._machineRoom[label] ?? null; }
  getLastUpdate() { return this._lastUpdate; }
}
