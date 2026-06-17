// Actualizacion de indicadores ambientales (termometros, barras, ventilador, extractor).
// Logica equivalente a updateIndicators + updateDashboard del frontend Plotly original.

import {
    tempColor,
    humidityColor,
    ammoniaColor,
    termoScaleColor,
    calentadorBarColor,
} from './colorScales.js';

const TEMP_BAR_MIN = 14, TEMP_BAR_MAX = 35;
const AMMONIA_BAR_MAX = 5;

// Rangos de alerta
const TEMP_ALERT_HIGH = 28; // °C
const TEMP_ALERT_LOW = 20;  // °C
const HUMIDITY_ALERT_HIGH = 70; // %
const HUMIDITY_ALERT_LOW = 40;  // %
const AMMONIA_ALERT = 3; // ppm

function setAlertClass(element, isAlert) {
    if (!element) return;
    element.parentElement?.classList.toggle('alert', isAlert);
}

export function updateConnectionStatus(httpOk, mqttConnected) {
    const dot = document.getElementById('conn-dot');
    const label = document.getElementById('conn-status');
    if (!httpOk) {
        dot.className = 'connection-dot err';
        label.textContent = 'Server unreachable';
    } else if (!mqttConnected) {
        dot.className = 'connection-dot warn';
        label.textContent = 'MQTT disconnected — reconnecting...';
    } else {
        dot.className = 'connection-dot ok';
        label.textContent = 'Receiving data';
    }
}

export function updateDashboard(data) {
    updateConnectionStatus(true, data.mqtt_connected);

    document.getElementById('mqtt-timestamp').textContent = data.last_update || '--';

    const fanEl = document.getElementById('fan-status');
    const fanBlade = document.getElementById('fan-blade');
    fanEl.textContent = data.fan_on ? 'ON' : 'OFF';
    fanEl.className = 'device-status ' + (data.fan_on ? 'on' : 'off');
    fanBlade.classList.toggle('spinning', !!data.fan_on);

    const extSt = document.getElementById('ext-status');
    const extBlade = document.getElementById('ext-blade');
    extSt.textContent = data.extractor_on ? 'ON' : 'OFF';
    extSt.className = 'device-status ' + (data.extractor_on ? 'on' : 'off');
    extBlade.classList.toggle('spinning', !!data.extractor_on);
}

export function updateIndicators(data) {
    // Termometros verticales (rango 14..35)
    for (const [label, info] of Object.entries(data.sensors)) {
        const valEl = document.getElementById('thermo-val-' + label);
        const fillEl = document.getElementById('thermo-fill-' + label);
        if (!valEl || !fillEl) continue;
        if (info.value !== null) {
            valEl.innerHTML = info.value.toFixed(1) + '<small>°C</small>';
            const pct = Math.max(0, Math.min(100,
                (info.value - TEMP_BAR_MIN) / (TEMP_BAR_MAX - TEMP_BAR_MIN) * 100));
            fillEl.style.height = pct + '%';
            fillEl.style.background = tempColor(info.value);
            setAlertClass(valEl, info.value > TEMP_ALERT_HIGH || info.value < TEMP_ALERT_LOW);
        } else {
            valEl.innerHTML = '--<small>°C</small>';
            fillEl.style.height = '0%';
            setAlertClass(valEl, false);
        }
    }

    // Humedad (0..100)
    if (data.humidity) {
        for (const [label, value] of Object.entries(data.humidity)) {
            const valEl = document.getElementById('hbar-val-' + label);
            const fillEl = document.getElementById('hbar-fill-' + label);
            if (!valEl || !fillEl) continue;
            if (value !== null) {
                valEl.innerHTML = value.toFixed(1) + '<small>%</small>';
                fillEl.style.width = Math.max(0, Math.min(100, value)) + '%';
                fillEl.style.background = humidityColor(value);
                setAlertClass(valEl, value > HUMIDITY_ALERT_HIGH || value < HUMIDITY_ALERT_LOW);
            } else {
                valEl.innerHTML = '--<small>%</small>';
                fillEl.style.width = '0%';
                setAlertClass(valEl, false);
            }
        }
    }

    // Temperaturas promedio
    const avgTemps = {
        tex: data.exterior_temp,
        tps: data.avg_temp_superior,
        tpi: data.avg_temp_inferior,
    };
    for (const [key, value] of Object.entries(avgTemps)) {
        const valEl = document.getElementById('hbar-val-' + key);
        const fillEl = document.getElementById('hbar-fill-' + key);
        if (!valEl || !fillEl) continue;
        if (value !== null && value !== undefined) {
            valEl.textContent = value.toFixed(1) + ' °C';
            const pct = Math.max(0, Math.min(100,
                (value - TEMP_BAR_MIN) / (TEMP_BAR_MAX - TEMP_BAR_MIN) * 100));
            fillEl.style.width = pct + '%';
            fillEl.style.background = tempColor(value);
            setAlertClass(valEl, value > TEMP_ALERT_HIGH || value < TEMP_ALERT_LOW);
        } else {
            valEl.innerHTML = '--<small>°C</small>';
            fillEl.style.width = '0%';
            setAlertClass(valEl, false);
        }
    }

    // Sala de maquinas
    if (data.machine_room) {
        const mrNormal = { temperatura4: 'mr-t4' };
        for (const [label, id] of Object.entries(mrNormal)) {
            const mr = data.machine_room[label];
            const valEl = document.getElementById('hbar-val-' + id);
            const fillEl = document.getElementById('hbar-fill-' + id);
            if (!valEl || !fillEl || !mr) continue;
            if (mr.value !== null) {
                valEl.textContent = mr.value.toFixed(1) + ' °C';
                const pct = Math.max(0, Math.min(100,
                    (mr.value - TEMP_BAR_MIN) / (TEMP_BAR_MAX - TEMP_BAR_MIN) * 100));
                fillEl.style.width = pct + '%';
                fillEl.style.background = tempColor(mr.value);
            } else {
                valEl.innerHTML = '--<small>°C</small>';
                fillEl.style.width = '0%';
            }
        }
        // Calentador (30..90)
        const t2mr = data.machine_room['temperatura2'];
        const t2ValEl = document.getElementById('hbar-val-mr-t2');
        const t2FillEl = document.getElementById('hbar-fill-mr-t2');
        if (t2ValEl && t2FillEl && t2mr) {
            if (t2mr.value !== null) {
                t2ValEl.textContent = t2mr.value.toFixed(1) + ' °C';
                const pct = Math.max(0, Math.min(100, (t2mr.value - 30) / (90 - 30) * 100));
                t2FillEl.style.width = pct + '%';
                t2FillEl.style.background = calentadorBarColor(t2mr.value);
            } else {
                t2ValEl.textContent = '-- °C';
                t2FillEl.style.width = '0%';
            }
        }
        // Termo (15..90)
        const TERMO_MIN = 15, TERMO_MAX = 90;
        const t5mr = data.machine_room['temperatura5'];
        const t5ValEl = document.getElementById('hbar-val-mr-t5');
        const t5FillEl = document.getElementById('hbar-fill-mr-t5');
        if (t5ValEl && t5FillEl && t5mr) {
            if (t5mr.value !== null) {
                t5ValEl.textContent = t5mr.value.toFixed(1) + ' °C';
                const pct = Math.max(0, Math.min(100, (t5mr.value - TERMO_MIN) / (TERMO_MAX - TERMO_MIN) * 100));
                t5FillEl.style.width = pct + '%';
                t5FillEl.style.background = termoScaleColor(t5mr.value);
            } else {
                t5ValEl.textContent = '-- °C';
                t5FillEl.style.width = '0%';
            }
        }
    }

    // Piso radiante
    if (data.radiant_floor) {
        const rfMap = { temperatura1: 'rf-t1', temperatura3: 'rf-t3' };
        for (const [label, id] of Object.entries(rfMap)) {
            const rf = data.radiant_floor[label];
            const valEl = document.getElementById('hbar-val-' + id);
            const fillEl = document.getElementById('hbar-fill-' + id);
            if (!valEl || !fillEl || !rf) continue;
            if (rf.value !== null) {
                valEl.textContent = rf.value.toFixed(1) + ' °C';
                const pct = Math.max(0, Math.min(100,
                    (rf.value - TEMP_BAR_MIN) / (TEMP_BAR_MAX - TEMP_BAR_MIN) * 100));
                fillEl.style.width = pct + '%';
                fillEl.style.background = tempColor(rf.value);
            } else {
                valEl.innerHTML = '--<small>°C</small>';
                fillEl.style.width = '0%';
            }
        }
    }

    // Amoniaco
    const amValEl = document.getElementById('hbar-val-ammonia');
    const amFillEl = document.getElementById('hbar-fill-ammonia');
    if (amValEl && amFillEl) {
        if (data.amoniaco !== null && data.amoniaco !== undefined) {
            amValEl.innerHTML = data.amoniaco.toFixed(2) + '<small>ppm</small>';
            const pct = Math.max(0, Math.min(100, data.amoniaco / AMMONIA_BAR_MAX * 100));
            amFillEl.style.width = pct + '%';
            amFillEl.style.background = ammoniaColor(data.amoniaco);
            setAlertClass(amValEl, data.amoniaco > AMMONIA_ALERT);
        } else {
            amValEl.innerHTML = '--<small>ppm</small>';
            amFillEl.style.width = '0%';
            setAlertClass(amValEl, false);
        }
    }
}
