// Cliente SSE hacia el sidecar Python (proxy en /api/predictor/stream).
// Reconecta automáticamente con backoff simple. No expone credenciales —
// el endpoint es del mismo origen, el token Ubidots vive solo en Python.

const RECONNECT_MS = 2000;

let es = null;
let onSnapshotFn = null;
let onUpdateFn = null;
let onStatusFn = null;
let stopped = false;

export function connectStream({ onSnapshot, onUpdate, onStatus }) {
    onSnapshotFn = onSnapshot;
    onUpdateFn = onUpdate;
    onStatusFn = onStatus;
    stopped = false;
    open();
}

export function disconnectStream() {
    stopped = true;
    if (es) {
        try { es.close(); } catch {}
        es = null;
    }
}

function open() {
    if (stopped) return;
    es = new EventSource('/api/predictor/stream');

    es.addEventListener('snapshot', (e) => {
        try { onSnapshotFn?.(JSON.parse(e.data)); } catch (err) { console.error('[predictor] snapshot parse', err); }
    });
    es.addEventListener('update', (e) => {
        try { onUpdateFn?.(JSON.parse(e.data)); } catch (err) { console.error('[predictor] update parse', err); }
    });
    es.addEventListener('ping', () => {});
    es.onopen = () => onStatusFn?.({ connected: true, label: 'online' });
    es.onerror = () => {
        onStatusFn?.({ connected: false, label: 'reconectando…' });
        try { es?.close(); } catch {}
        es = null;
        if (!stopped) setTimeout(open, RECONNECT_MS);
    };
}
