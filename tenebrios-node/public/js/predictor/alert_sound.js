// Alerta sonora generada con Web Audio API (sin archivos binarios).
// Suena solo en transiciones a PELIGRO (current pasa de ok/unknown a
// abnormal), nunca en cada update — mismo principio que Telegram.
//
// Detalles:
//  - localStorage('ai-alert-sound-enabled') persiste preferencia por navegador
//  - El AudioContext debe crearse despues de un user gesture (autoplay
//    policy). Lo creamos perezosamente en el primer click del toggle o
//    en el primer playDanger() — si el browser lo bloquea, fallamos
//    silenciosamente
//  - Boton 🔔/🔕 en el header IA junto al engrane de Telegram

const STORAGE_KEY = 'ai-alert-sound-enabled';

let audioCtx = null;
let enabled = true;
let toggleEl = null;

export function initAlertSound() {
    enabled = readPref();

    toggleEl = document.getElementById('ai-sound-toggle');
    if (toggleEl) {
        renderToggle();
        toggleEl.addEventListener('click', () => {
            enabled = !enabled;
            writePref(enabled);
            renderToggle();
            // Primer click cuenta como user gesture; aprovechamos para
            // crear el AudioContext y un beep cortisimo de "preview" si
            // se acaba de activar.
            ensureCtx();
            if (enabled) playSoft();
        });
    }
}

export function playDanger() {
    if (!enabled) return;
    const ctx = ensureCtx();
    if (!ctx) return;
    // Dos beeps altos consecutivos (clasico alerta)
    beep(ctx, 880, 0.10, 0.00);
    beep(ctx, 660, 0.10, 0.18);
}

// ---------- internos ----------

function ensureCtx() {
    if (audioCtx) {
        if (audioCtx.state === 'suspended') {
            // Browser puede suspender despues de un rato; resume es seguro
            audioCtx.resume().catch(() => {});
        }
        return audioCtx;
    }
    try {
        const Ctor = window.AudioContext || window.webkitAudioContext;
        if (!Ctor) return null;
        audioCtx = new Ctor();
        return audioCtx;
    } catch {
        return null;
    }
}

function beep(ctx, freq, duration, delay) {
    const t0 = ctx.currentTime + delay;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    // Envelope con attack/release suaves para que no clickee
    gain.gain.setValueAtTime(0, t0);
    gain.gain.linearRampToValueAtTime(0.28, t0 + 0.01);
    gain.gain.linearRampToValueAtTime(0.28, t0 + duration - 0.02);
    gain.gain.linearRampToValueAtTime(0, t0 + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + duration + 0.02);
}

function playSoft() {
    // Click corto y suave para confirmar que el sonido esta activo
    const ctx = ensureCtx();
    if (!ctx) return;
    beep(ctx, 1000, 0.05, 0);
}

function renderToggle() {
    if (!toggleEl) return;
    toggleEl.textContent = enabled ? '🔔' : '🔕';
    toggleEl.title = enabled
        ? 'Sonido activo — click para silenciar'
        : 'Sonido silenciado — click para activar';
    toggleEl.setAttribute('aria-pressed', String(enabled));
    toggleEl.classList.toggle('muted', !enabled);
}

function readPref() {
    try {
        const v = localStorage.getItem(STORAGE_KEY);
        if (v === null) return true; // default: activo
        return v === '1';
    } catch {
        return true;
    }
}

function writePref(value) {
    try { localStorage.setItem(STORAGE_KEY, value ? '1' : '0'); } catch {}
}
