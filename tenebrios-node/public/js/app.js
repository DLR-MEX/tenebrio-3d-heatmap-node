// Punto de entrada del frontend. Inicializa Babylon, conecta indicadores,
// activa el polling cada ANIMATION_INTERVAL_MS y enlaza el modo + historial.
// Sustituye al bloque <script> embebido del index.html original.

// Marca de version visible en DevTools console — confirma que el navegador
// cargo el codigo actualizado (si NO ves esta linea con la fecha correcta,
// el browser sigue sirviendo del cache).
console.log('%cTENEBRIO frontend build 2026-04-27-v31 (inmersión: tablero hover derecho)',
    'color:#E8B830;font-weight:bold;background:#1a2630;padding:4px 8px;');

import { initScene, buildScene, isReady } from './scene.js';
import { updateDashboard, updateIndicators, updateConnectionStatus } from './indicators.js';
import { initHistoryUI, isHistoryMode, setLiveDataProvider } from './history.js';
import { initPredictorView, activatePredictorView, deactivatePredictorView } from './predictor/index.js';

const FETCH_TIMEOUT_MS = 5000;
let REFRESH_MS = 2000;

let lastData = null;
let heatmapMode = 'full-temp';

window.addEventListener('DOMContentLoaded', async () => {
    const canvas = document.getElementById('scene3d-canvas');
    initScene(canvas);

    // Cargar configuracion desde el backend (refresh_ms)
    try {
        const resp = await fetch('/api/config');
        if (resp.ok) {
            const cfg = await resp.json();
            if (cfg.refresh_ms) REFRESH_MS = cfg.refresh_ms;
        }
    } catch {}

    setupModeButtons();
    setupExpandButton();
    setupImmersivePanel();
    setupViewToggle();
    initPredictorView();
    initHistoryUI({ onFrame: handleHistoryFrame });
    setLiveDataProvider(() => lastData);

    fetchData();
    setInterval(fetchData, REFRESH_MS);
});

// Alternancia entre vista 3D y vista IA con fade cruzado de ~280ms.
// Ambos contenedores ocupan el mismo espacio (CSS); la animacion solo
// alterna opacity + pointer-events. El motor 3D y el predictor siguen
// vivos en background para que cambiar de vista sea instantaneo y
// no perdamos historial.
const VIEW_FADE_MS = 280;

function setupViewToggle() {
    const buttons = document.querySelectorAll('.view-toggle button');
    const view3d = document.getElementById('view-3d');
    const viewAi = document.getElementById('view-ai');
    if (!buttons.length || !view3d || !viewAi) return;

    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.view;
            // Si ya estamos en esa vista, no hacemos nada (evita re-trigger
            // de animacion y resize innecesarios).
            if (btn.classList.contains('active')) return;

            buttons.forEach((b) => b.classList.toggle('active', b.dataset.view === target));
            const showAi = target === 'view-ai';

            // Fase 1: fade-out de la vista actual
            const outgoing = showAi ? view3d : viewAi;
            const incoming = showAi ? viewAi : view3d;
            outgoing.classList.add('view-fading-out');

            setTimeout(() => {
                outgoing.classList.add('hidden');
                outgoing.classList.remove('view-fading-out');
                incoming.classList.remove('hidden');
                incoming.classList.add('view-fading-in');

                // Fase 2: la entrante hace su fade-in
                requestAnimationFrame(() => {
                    incoming.classList.remove('view-fading-in');
                });

                if (showAi) {
                    activatePredictorView();
                } else {
                    deactivatePredictorView();
                    // Forzar resize del canvas Babylon al volver del modo IA
                    window.dispatchEvent(new Event('resize'));
                }
            }, VIEW_FADE_MS);
        });
    });
}

function setupModeButtons() {
    const buttons = document.querySelectorAll('.mode-toggle button');
    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const mode = btn.dataset.mode;
            heatmapMode = mode;
            buttons.forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
            if (lastData) buildScene(lastData, heatmapMode);
        });
    });
}

function setupExpandButton() {
    const btn = document.getElementById('btn-expand');

    function setImmersive(on) {
        document.body.classList.toggle('immersive', on);
        btn.textContent = on ? '✕ SALIR' : '⛶ INMERSIÓN';
        if (!on) {
            // Al salir de inmersion, cerrar el tablero lateral si estaba abierto
            document.querySelector('.side-panel')?.classList.remove('panel-visible');
            document.body.classList.remove('panel-open');
        }
        setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
    }

    // Activacion via URL: ?immersive=1  (bookmark-friendly desde el celular)
    const params = new URLSearchParams(window.location.search);
    if (params.get('immersive') === '1') setImmersive(true);

    btn.addEventListener('click', () => {
        setImmersive(!document.body.classList.contains('immersive'));
    });

    // Escape sale del modo inmersion
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && document.body.classList.contains('immersive')) {
            setImmersive(false);
        }
    });
}

function setupImmersivePanel() {
    // Solo en dispositivos con mouse (pointer: fine). En tactil/movil no aplica.
    if (!window.matchMedia('(pointer: fine)').matches) return;

    const panel = document.querySelector('.side-panel');
    if (!panel) return;

    const PANEL_WIDTH = 300;  // px — debe coincidir con el CSS
    const TRIGGER_ZONE = 50;  // px desde el borde derecho que activa el panel
    let hideTimer = null;

    function showPanel() {
        clearTimeout(hideTimer);
        panel.classList.add('panel-visible');
        document.body.classList.add('panel-open');
    }

    function scheduleHide(delay = 350) {
        clearTimeout(hideTimer);
        hideTimer = setTimeout(() => {
            panel.classList.remove('panel-visible');
            document.body.classList.remove('panel-open');
        }, delay);
    }

    document.addEventListener('mousemove', (e) => {
        if (!document.body.classList.contains('immersive')) return;
        if (e.clientX >= window.innerWidth - TRIGGER_ZONE) {
            showPanel();
        } else if (e.clientX < window.innerWidth - PANEL_WIDTH - 10) {
            scheduleHide();
        }
    });

    // Mantener abierto mientras el mouse esta dentro del panel
    panel.addEventListener('mouseenter', () => clearTimeout(hideTimer));
    panel.addEventListener('mouseleave', () => scheduleHide(250));
}

async function fetchData() {
    if (isHistoryMode()) return; // mientras hay historial activo no actualizamos en vivo
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    try {
        const resp = await fetch('/api/data', { signal: controller.signal });
        clearTimeout(timeoutId);
        if (!resp.ok) throw new Error('API error');
        const data = await resp.json();
        lastData = data;
        updateDashboard(data);
        updateIndicators(data);
        if (isReady()) buildScene(data, heatmapMode);
    } catch {
        clearTimeout(timeoutId);
        updateConnectionStatus(false, false);
    }
}

function handleHistoryFrame(histData) {
    updateDashboard(histData);
    updateIndicators(histData);
    if (isReady()) buildScene(histData, heatmapMode);
}
