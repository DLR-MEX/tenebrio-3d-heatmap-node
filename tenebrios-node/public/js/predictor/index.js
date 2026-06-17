// Orquestador de la vista IA. Construye tarjetas y charts, mantiene el
// historial en memoria y aplica snapshots/updates del SSE. Se inicializa
// una vez al cargar la pagina; activate/deactivate solo afecta resize y
// la conexion SSE (para no consumir red mientras el usuario esta en 3D).

import { buildCards, updateCard, resizeSparks } from './cards.js';
import { initMainChart, refreshMainChart, resizeMainCharts } from './charts.js';
import { connectStream, disconnectStream } from './sse.js';
import { initTelegramConfig } from './telegram_config.js';
import { initAlertSound } from './alert_sound.js';
import { initTheme } from './theme.js';
import { initShortcuts } from './shortcuts.js';
import { initCsvExport } from './export_csv.js';
import { updateAlertIndicators } from './alert_indicators.js';
import { initChat } from './chat.js';

const TEMP_VARS = ['t1', 't2', 't3', 't4', 't5', 'tex'];
const HUM_VARS  = ['h1', 'h2', 'h3', 'h4', 'h5', 'hex'];
const TEMP_HUES = ['#38bdf8', '#22d3ee', '#a78bfa', '#f472b6', '#fb923c', '#facc15'];
const HUM_HUES  = ['#34d399', '#10b981', '#06b6d4', '#3b82f6', '#8b5cf6', '#f43f5e'];

const MAX_POINTS = 60;
const BUFFER_TARGET = 30;

const state = {
    TEMP: { history: [] },
    HUM:  { history: [] },
};

let initialized = false;
let active = false;

export function initPredictorView() {
    if (initialized) return;
    initialized = true;

    buildCards('TEMP', TEMP_VARS, TEMP_HUES);
    buildCards('HUM',  HUM_VARS,  HUM_HUES);
    initMainChart('TEMP', TEMP_VARS, TEMP_HUES, '°');
    initMainChart('HUM',  HUM_VARS,  HUM_HUES,  '%');
    initTelegramConfig();
    initAlertSound();
    initTheme();
    initShortcuts();
    initCsvExport({
        getHistory: (group) => state[group]?.history || [],
        getVars: (group) => group === 'TEMP' ? TEMP_VARS : HUM_VARS,
    });
    initChat();

    window.addEventListener('resize', () => {
        // Solo redibujamos si la vista esta visible; ECharts en contenedor
        // oculto reporta tamaño 0 y queda mal cuando se vuelve a mostrar.
        if (active) {
            resizeMainCharts();
            resizeSparks();
        }
    });
}

export function activatePredictorView() {
    active = true;
    // ECharts necesita un resize tras volverse visible para coger las
    // dimensiones reales del contenedor (estaba display:none).
    setTimeout(() => {
        resizeMainCharts();
        resizeSparks();
    }, 30);
    // Conectar SSE solo cuando el usuario entra a la vista IA. Asi no
    // consumimos ancho de banda mientras esta en la vista 3D.
    connectStream({
        onSnapshot: applySnapshot,
        onUpdate: applyUpdate,
        onStatus: applyStatus,
    });
}

export function deactivatePredictorView() {
    active = false;
    disconnectStream();
    // Indicador a "offline" para que sea obvio si el usuario vuelve mas tarde
    setStatus(false, 'standby');
}

// ---------- aplicacion de eventos ----------

function applySnapshot(snap) {
    setText('ai-device-label', snap.device || '—');
    setStatus(snap.mqtt_connected, snap.mqtt_connected ? 'online' : 'offline');

    // Cargar extras (tps, tpi) si vienen en el snapshot
    const extras = snap.extras || {};
    for (const [v, info] of Object.entries(extras)) {
        if (info && Number.isFinite(info.value)) {
            renderExtraChip(v, {
                label: info.label || v,
                value: info.value,
                unit: info.unit || '°C',
            });
        }
    }

    for (const group of ['TEMP', 'HUM']) {
        const g = snap.groups?.[group];
        if (!g) continue;
        state[group].history = (g.history || []).slice(-MAX_POINTS);
        setBufferChip(group, g.buffer_size, BUFFER_TARGET);
        const vars = g.vars || (group === 'TEMP' ? TEMP_VARS : HUM_VARS);
        const unit = group === 'TEMP' ? '°' : '%';
        if (g.ts && g.current && Object.keys(g.current).length) {
            for (let i = 0; i < vars.length; i++) {
                updateCard(group, vars, i, g.current, g.predicted, g.alerts || {}, state[group].history, unit);
            }
            updateAlertIndicators(group, {
                vars,
                current: g.current,
                predicted: g.predicted,
                alerts: g.alerts || {},
            });
        }
        refreshMainChart(group, vars, state[group].history);
    }
    if (snap.now) setText('ai-last-update', fmtTime(snap.now));
}

function applyUpdate(payload) {
    if (payload.type === 'status') {
        setStatus(payload.mqtt_connected, payload.mqtt_connected ? 'online' : 'offline');
        return;
    }
    if (payload.type === 'buffer') {
        setBufferChip(payload.group, payload.size, payload.target);
        return;
    }
    if (payload.type === 'jump') {
        showJumpToast(payload);
        return;
    }
    if (payload.type === 'extra') {
        renderExtraChip(payload.var, {
            label: payload.label,
            value: payload.value,
            unit: payload.unit || '°C',
        });
        return;
    }
    if (payload.type === 'prediction') {
        const group = payload.group;
        const vars = payload.vars;
        const unit = group === 'TEMP' ? '°' : '%';

        state[group].history.push({
            ts: payload.ts,
            current: payload.current,
            predicted: payload.predicted,
            alerts: payload.alerts || {},
        });
        if (state[group].history.length > MAX_POINTS) state[group].history.shift();

        for (let i = 0; i < vars.length; i++) {
            updateCard(group, vars, i, payload.current, payload.predicted, payload.alerts || {}, state[group].history, unit);
        }
        updateAlertIndicators(group, {
            vars,
            current: payload.current,
            predicted: payload.predicted,
            alerts: payload.alerts || {},
        });
        refreshMainChart(group, vars, state[group].history);
        setBufferChip(group, BUFFER_TARGET, BUFFER_TARGET);
        setText('ai-last-update', fmtTime(payload.ts));
    }
}

function applyStatus({ connected, label }) {
    setStatus(connected, label);
}

// ---------- helpers DOM ----------

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setStatus(connected, label) {
    const dot = document.getElementById('ai-status-dot');
    const text = document.getElementById('ai-status-text');
    if (dot) {
        dot.classList.remove('live', 'dead');
        dot.classList.add(connected ? 'live' : 'dead');
    }
    if (text) text.textContent = label;
}

function setBufferChip(group, size, target) {
    const chip = document.getElementById(`ai-buffer-${group.toLowerCase()}`);
    if (!chip) return;
    if (size >= target) {
        chip.classList.remove('visible');
        chip.textContent = '';
        return;
    }
    chip.classList.add('visible');
    chip.textContent = `buffer ${size}/${target}`;
}

function fmtTime(sec) {
    if (!sec) return '—';
    return new Date(sec * 1000).toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}

// Render/actualiza un chip de promedio agregado (tps, tpi). Idempotente:
// si el chip ya existe, solo actualiza el valor y le da un flash visual.
const EXTRA_ICONS = { tps: '🔼', tpi: '🔽' };

function renderExtraChip(varName, info) {
    const host = document.getElementById('ai-extras-temp');
    if (!host) return;
    let chip = host.querySelector(`[data-var="${varName}"]`);
    if (!chip) {
        chip = document.createElement('div');
        chip.className = 'ai-extra-chip';
        chip.dataset.var = varName;
        chip.innerHTML = `
            <span class="ai-extra-chip-icon">${EXTRA_ICONS[varName] || '·'}</span>
            <span class="ai-extra-chip-label" data-role="label"></span>
            <span class="ai-extra-chip-value" data-role="value"></span>
        `;
        host.appendChild(chip);
    }
    chip.querySelector('[data-role="label"]').textContent = info.label || varName;
    chip.querySelector('[data-role="value"]').textContent =
        `${Number(info.value).toFixed(2)}${info.unit || ''}`;
    // Flash breve para indicar update en vivo
    chip.classList.add('flash');
    setTimeout(() => chip.classList.remove('flash'), 600);
}

// Toast transitorio para eventos jump (rate-of-change). Aparece arriba a la
// derecha de la vista IA, ~6s. No modal, no bloqueante.
function showJumpToast(payload) {
    const arrow = payload.delta >= 0 ? '📈' : '📉';
    const sign = payload.delta >= 0 ? '+' : '';
    const unit = payload.unit || '';
    const text = `${arrow} Salto en ${payload.var}: ${payload.prev_value.toFixed(2)}${unit} → ${payload.current_value.toFixed(2)}${unit} (${sign}${payload.delta.toFixed(2)}${unit})`;

    let host = document.getElementById('ai-jump-toasts');
    if (!host) {
        host = document.createElement('div');
        host.id = 'ai-jump-toasts';
        host.className = 'ai-jump-toasts';
        document.getElementById('view-ai')?.appendChild(host);
    }
    const toast = document.createElement('div');
    toast.className = 'ai-jump-toast';
    toast.textContent = text;
    host.appendChild(toast);
    // Animacion entrada y salida
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 350);
    }, 6000);
}
