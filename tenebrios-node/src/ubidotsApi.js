// Cliente HTTP para historico de Ubidots.
// Estrategia: pasamos por el sidecar Python (cache TTL 60s en /api/ubidots-history)
// asi un solo backend consulta Ubidots y nos ahorramos el rate-limit doble.
// Si el sidecar esta caido, hacemos fallback al Ubidots directo (degradacion
// graceful: el slider sigue funcionando, solo perdemos la cache compartida).

import { UBIDOTS_TOKEN, DEVICE_LABEL } from './config.js';
import { getLogger } from './logger.js';

const logger = getLogger('ubidotsApi');

const SIDECAR_BASE = process.env.AI_PREDICTOR_BASE || 'http://127.0.0.1:8000';
const SIDECAR_TIMEOUT_MS = 12000;
const UBIDOTS_TIMEOUT_MS = 15000;

/**
 * Consulta valores historicos de una variable en Ubidots entre dos timestamps en ms.
 * Retorna el array data.results o [] si hay error.
 */
export async function fetchUbidotsValues(variableLabel, startMs, endMs) {
  // Intentamos primero por el sidecar (cache compartido)
  const sidecarResult = await fetchViaSidecar(variableLabel, startMs, endMs);
  if (sidecarResult !== null) return sidecarResult;
  // Fallback: directo a Ubidots
  logger.warn(`Sidecar no disponible para ${variableLabel}; fallback a Ubidots directo`);
  return fetchDirectFromUbidots(variableLabel, startMs, endMs);
}

async function fetchViaSidecar(variableLabel, startMs, endMs) {
  const url = `${SIDECAR_BASE}/api/ubidots-history?var=${encodeURIComponent(variableLabel)}&start=${startMs}&end=${endMs}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), SIDECAR_TIMEOUT_MS);
  try {
    const resp = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) {
      // 5xx: sidecar caido / error, devolvemos null para activar fallback
      // 4xx: error del cliente (var invalido, rango muy grande), aceptamos como definitivo
      if (resp.status >= 500) return null;
      logger.warn(`Sidecar history ${resp.status} para ${variableLabel}`);
      return [];
    }
    const data = await resp.json();
    return Array.isArray(data?.results) ? data.results : [];
  } catch (e) {
    clearTimeout(timeoutId);
    // ECONNREFUSED, timeout, abort: sidecar caido. Fallback.
    return null;
  }
}

async function fetchDirectFromUbidots(variableLabel, startMs, endMs) {
  const url =
    `https://industrial.api.ubidots.com/api/v1.6/devices/` +
    `${DEVICE_LABEL}/${variableLabel}/values` +
    `?start=${startMs}&end=${endMs}&page_size=5000`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), UBIDOTS_TIMEOUT_MS);

  try {
    const resp = await fetch(url, {
      headers: { 'X-Auth-Token': UBIDOTS_TOKEN },
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!resp.ok) {
      logger.warn(`Ubidots respondio ${resp.status} para ${variableLabel}`);
      return [];
    }
    const data = await resp.json();
    return data.results || [];
  } catch (e) {
    clearTimeout(timeoutId);
    logger.warn(`Error consultando Ubidots para ${variableLabel}: ${e.message}`);
    return [];
  }
}
