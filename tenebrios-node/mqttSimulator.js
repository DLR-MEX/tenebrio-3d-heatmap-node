// Simulador MQTT para pruebas locales — replica de mqtt_simulator.py.
// Publica datos de sensores aleatorios cada 2 segundos al mismo topico al que
// se suscribe la aplicacion real, usando un broker local (ej. Mosquitto).

import mqtt from 'mqtt';
import {
    MQTT_BROKER, MQTT_PORT, UBIDOTS_TOKEN, MQTT_TOPIC,
    SENSOR_POSITIONS, HUMIDITY_LABELS, RADIANT_FLOOR_LABELS, MACHINE_ROOM_LABELS,
} from './src/config.js';

const TEMP_BASE = 25.0;
const TEMP_VAR = 3.0;

function rand(base, variation) {
    return Math.round((base + (Math.random() * 2 - 1) * variation) * 10) / 10;
}

function generatePayload() {
    const out = {};
    for (const t of Object.keys(SENSOR_POSITIONS)) out[t] = rand(TEMP_BASE, TEMP_VAR);
    out.tex = rand(32, 2);
    out.tps = rand(26, 1);
    out.tpi = rand(22, 1);
    for (const h of HUMIDITY_LABELS) out[h] = rand(50, 10);
    for (const r of Object.keys(RADIANT_FLOOR_LABELS)) out[r] = rand(20, 2);
    for (const m of Object.keys(MACHINE_ROOM_LABELS)) {
        if (m === 'temperatura5') out[m] = rand(60, 10);
        else if (m === 'temperatura2') out[m] = rand(45, 10);
        else out[m] = rand(22, 2);
    }
    out.amoniaco = Math.round(Math.random() * 100) / 100;
    out.ventilador = Math.random() > 0.5 ? 1 : 0;
    out.extractor = Math.random() > 0.5 ? 1 : 0;
    return out;
}

const url = `mqtt://${MQTT_BROKER}:${MQTT_PORT}`;
console.log(`Connecting to ${url} ...`);
const client = mqtt.connect(url, {
    username: UBIDOTS_TOKEN,
    password: '',
});

client.on('connect', () => {
    console.log(`Publishing to topic: ${MQTT_TOPIC}  (Ctrl+C to stop)`);
    setInterval(() => {
        const payload = generatePayload();
        client.publish(MQTT_TOPIC, JSON.stringify(payload));
        console.log(`Published: ${JSON.stringify(payload)}`);
    }, 2000);
});

client.on('error', (err) => {
    console.error(`MQTT error: ${err.message}`);
    process.exit(1);
});
