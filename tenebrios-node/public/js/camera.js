// Camara ortografica + rotacion exclusivamente horizontal alrededor del centro
// del cuarto. Replica el comportamiento de la camara Plotly del frontend original.
// Usa pointer events (mouse + touch unificados) sobre el contenedor de la escena.

const { ArcRotateCamera, Vector3, Camera } = BABYLON;

// Centro inicial (Babylon coords). Cambia segun el modo via setCameraTargetPlotly.
const ROOM_CENTER = { x: 1, y: 1, z: 3 };

// Distancia en unidades de mundo (la camara es ortografica asi que no afecta zoom,
// solo posiciona la camara fuera del centro para que el clipping no corte la escena).
const CAM_DISTANCE = 25;

let _camera = null;
let _alpha = Math.atan2(-1.8, 1.6); // angulo horizontal inicial — vista isometrica desde Y- del Plotly original
let _beta = Math.PI / 2 - Math.atan2(0.8, Math.sqrt(1.6 * 1.6 + 1.8 * 1.8));

const AUTO_ROTATE_DELAY_MS = 12000; // 12 s sin interaccion -> comienza rotacion
const AUTO_ROTATE_SPEED = 0.004;    // ~14 deg/s a 60fps; vuelta completa en ~26 s
let _lastInteraction = Date.now();

export function createCamera(scene, canvas) {
    _camera = new ArcRotateCamera(
        'mainCamera',
        _alpha,
        _beta,
        CAM_DISTANCE,
        new Vector3(ROOM_CENTER.x, ROOM_CENTER.y, ROOM_CENTER.z),
        scene,
    );
    _camera.mode = Camera.ORTHOGRAPHIC_CAMERA;
    setOrthoBoundsForCanvas(canvas);

    // Bloquear beta (vertical) y radius para que solo cambie alpha
    _camera.lowerBetaLimit = _beta;
    _camera.upperBetaLimit = _beta;
    _camera.lowerRadiusLimit = CAM_DISTANCE;
    _camera.upperRadiusLimit = CAM_DISTANCE;

    setupHorizontalRotation(scene, canvas);

    return _camera;
}

function setOrthoBoundsForCanvas(canvas) {
    if (!_camera || !canvas) return;
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    const aspect = w / h;
    // worldHeight controla la zona visible: a mayor valor, objetos se ven mas
    // pequeños porque cabe mas mundo en el viewport. 9 → 10 = ~10% mas chico.
    const worldHeight = 10;
    const worldWidth = worldHeight * aspect;
    _camera.orthoLeft = -worldWidth / 2;
    _camera.orthoRight = worldWidth / 2;
    _camera.orthoTop = worldHeight / 2;
    _camera.orthoBottom = -worldHeight / 2;
}

export function refreshCameraBounds(canvas) {
    setOrthoBoundsForCanvas(canvas);
}

/**
 * Mueve el target de la camara a las coordenadas Plotly dadas (x, y=profundidad, z=altura).
 * Internamente convierte a Babylon: (x, z, y).
 * @param {[number, number, number]} plotlyPos
 */
export function setCameraTargetPlotly(plotlyPos) {
    if (!_camera) return;
    const [px, py, pz] = plotlyPos;
    _camera.target = new Vector3(px, pz, py);
}

function setupHorizontalRotation(scene, canvas) {
    // Adjuntamos los listeners al contenedor de la escena (cubre canvas + overlays)
    // y usamos pointer events para unificar mouse + touch + pen.
    const container = document.getElementById('scene-container') || canvas;

    let dragging = false;
    let startX = 0;
    let activePointerId = null;

    container.addEventListener('pointerdown', (e) => {
        // Ignorar clicks sobre botones, selectores y el panel de debug
        const target = e.target;
        if (target.closest && (target.closest('.mode-toggle') ||
                                target.closest('.history-panel') ||
                                target.closest('.btn-expand-render') ||
                                target.closest('#debug-overlay-controls'))) {
            return;
        }
        _lastInteraction = Date.now();
        dragging = true;
        startX = e.clientX;
        activePointerId = e.pointerId;
        try { container.setPointerCapture(e.pointerId); } catch {}
        e.preventDefault();
    });

    container.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        if (activePointerId !== null && e.pointerId !== activePointerId) return;
        const dx = e.clientX - startX;
        startX = e.clientX;
        _alpha -= dx * 0.005;
        _camera.alpha = _alpha;
    });

    const stopDrag = (e) => {
        if (!dragging) return;
        dragging = false;
        if (activePointerId !== null) {
            try { container.releasePointerCapture(activePointerId); } catch {}
        }
        activePointerId = null;
    };
    container.addEventListener('pointerup', stopDrag);
    container.addEventListener('pointercancel', stopDrag);
    container.addEventListener('pointerleave', stopDrag);

    // Teclado: ArrowLeft / ArrowRight
    document.addEventListener('keydown', (e) => {
        const step = 0.15;
        if (e.key === 'ArrowLeft') _alpha += step;
        else if (e.key === 'ArrowRight') _alpha -= step;
        else return;
        _lastInteraction = Date.now();
        e.preventDefault();
        _camera.alpha = _alpha;
    });

    // Auto-rotacion: gira suavemente cuando no hay interaccion por AUTO_ROTATE_DELAY_MS
    scene.onBeforeRenderObservable.add(() => {
        if (!dragging && Date.now() - _lastInteraction > AUTO_ROTATE_DELAY_MS) {
            _alpha -= AUTO_ROTATE_SPEED;
            _camera.alpha = _alpha;
        }
    });
}
