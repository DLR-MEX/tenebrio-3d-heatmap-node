// Polling hacia el sidecar Python (proxy en /api/predictor/state).
// Antes usaba SSE (EventSource) contra /api/predictor/stream, pero los
// tuneles "quick" de Cloudflare (trycloudflare.com) bufferean la respuesta
// hasta que termina, y un stream SSE nunca termina -> nunca llegaba nada.
// /api/predictor/state devuelve el mismo snapshot como JSON normal, que si
// atraviesa el tunel sin problema. No expone credenciales — el endpoint es
// del mismo origen, el token Ubidots vive solo en Python.

const POLL_MS = 4000;

let onSnapshotFn = null;
let onStatusFn = null;
let timer = null;
let stopped = false;

export function connectStream({ onSnapshot, onUpdate, onStatus }) {
    onSnapshotFn = onSnapshot;
    onStatusFn = onStatus;
    stopped = false;
    poll();
}

export function disconnectStream() {
    stopped = true;
    if (timer) {
        clearTimeout(timer);
        timer = null;
    }
}

async function poll() {
    if (stopped) return;
    try {
        const resp = await fetch('api/predictor/state');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        onStatusFn?.({ connected: true, label: 'online' });
        onSnapshotFn?.(data);
    } catch (err) {
        console.error('[predictor] poll error', err);
        onStatusFn?.({ connected: false, label: 'reconectando…' });
    } finally {
        if (!stopped) timer = setTimeout(poll, POLL_MS);
    }
}
