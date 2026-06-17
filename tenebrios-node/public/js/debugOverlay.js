// Overlay de depuracion: muestra coordenadas Plotly (X horizontal, Y profundidad,
// Z vertical) del mesh bajo el cursor y un toggle para ocultar el mapa de calor.

import { setVolumeIsoDevHidden, isVolumeIsoDevHidden } from './meshes/volumeIso.js';

const { Vector3, Plane } = BABYLON;

const STYLE_ID = 'debug-overlay-style';
const PANEL_ID = 'debug-overlay-panel';
const CONTROLS_ID = 'debug-overlay-controls';

function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const css = `
    #${CONTROLS_ID} {
        position: absolute; top: 8px; left: 8px; z-index: 51;
        background: rgba(20, 30, 38, 0.85);
        border: 1px solid rgba(232,184,48,0.5);
        border-radius: 4px;
        color: #E8B830;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 11px; line-height: 1.35;
        padding: 6px 9px;
        pointer-events: auto;
    }
    #${CONTROLS_ID} label {
        display: flex; align-items: center; gap: 6px;
        cursor: pointer; user-select: none;
    }
    #${CONTROLS_ID} input[type="checkbox"] { cursor: pointer; }
    #${PANEL_ID} {
        position: absolute; bottom: 8px; left: 8px; z-index: 50;
        background: rgba(20, 30, 38, 0.85);
        border: 1px solid rgba(232,184,48,0.5);
        border-radius: 4px;
        color: #E8B830;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 11px; line-height: 1.35;
        padding: 6px 9px;
        pointer-events: none;
        white-space: pre;
        min-width: 220px;
        text-shadow: 0 0 2px rgba(0,0,0,0.8);
    }
    #${PANEL_ID} .lbl { color: #8aa0b0; }
    #${PANEL_ID} .val { color: #ffffff; }
    `;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = css;
    document.head.appendChild(style);
}

function toPlotly(v) {
    return { x: v.x, y: v.z, z: v.y };
}

function fmt(n) {
    return (n >= 0 ? ' ' : '') + n.toFixed(2);
}

function buildControls(container) {
    let ctl = document.getElementById(CONTROLS_ID);
    if (ctl) return ctl;
    ctl = document.createElement('div');
    ctl.id = CONTROLS_ID;
    ctl.innerHTML = `
        <label>
            <input type="checkbox" id="dbg-hide-heatmap" ${isVolumeIsoDevHidden() ? 'checked' : ''}>
            <span>Ocultar mapa de calor (dev)</span>
        </label>
    `;
    container.appendChild(ctl);
    const cb = ctl.querySelector('#dbg-hide-heatmap');
    cb.addEventListener('change', (ev) => {
        setVolumeIsoDevHidden(ev.target.checked);
    });
    return ctl;
}

function buildPanel(container) {
    let panel = document.getElementById(PANEL_ID);
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = PANEL_ID;
    panel.textContent = 'DEBUG: pasa el cursor sobre la escena';
    container.appendChild(panel);
    return panel;
}

/**
 * Inicializa overlay de depuracion (panel de coordenadas + toggle de mapa).
 * @param {HTMLElement} container  contenedor con position:relative (scene-container)
 * @param {HTMLCanvasElement} canvas
 * @param {BABYLON.Scene} scene
 */
export function initDebugOverlay(container, canvas, scene) {
    injectStyle();
    buildControls(container);
    const panel = buildPanel(container);

    // Plano del piso (Plotly Z=0 → Babylon Y=0). Usado para X/Y en el suelo.
    const groundPlane = Plane.FromPositionAndNormal(Vector3.Zero(), new Vector3(0, 1, 0));
    // Plano "pared trasera" (Plotly Y=6 → Babylon Z=6). Permite ver Z variando.
    const wallPlane = Plane.FromPositionAndNormal(new Vector3(0, 0, 6), new Vector3(0, 0, 1));
    // Plano "centro Y=3" (Plotly Y=3 → Babylon Z=3). Z varia al mover cursor.
    const midPlane = Plane.FromPositionAndNormal(new Vector3(0, 0, 3), new Vector3(0, 0, 1));

    function projectOn(ray, plane) {
        const t = ray.intersectsPlane(plane);
        return (t !== null && t > 0)
            ? ray.origin.add(ray.direction.scale(t))
            : null;
    }

    canvas.addEventListener('pointermove', (ev) => {
        const rect = canvas.getBoundingClientRect();
        const x = ev.clientX - rect.left;
        const y = ev.clientY - rect.top;

        const pick = scene.pick(x, y, (m) => m.isPickable !== false && m.isVisible);
        const ray = scene.createPickingRay(x, y, null, scene.activeCamera);

        const lines = [];
        if (pick && pick.hit && pick.pickedMesh) {
            const name = pick.pickedMesh.name;
            const mp = toPlotly(pick.pickedMesh.absolutePosition);
            const hp = toPlotly(pick.pickedPoint);
            lines.push(`<span class="lbl">mesh </span><span class="val">${name}</span>`);
            lines.push(`<span class="lbl">  pos </span><span class="val">x=${fmt(mp.x)}  y=${fmt(mp.y)}  z=${fmt(mp.z)}</span>`);
            lines.push(`<span class="lbl">  hit </span><span class="val">x=${fmt(hp.x)}  y=${fmt(hp.y)}  z=${fmt(hp.z)}</span>`);
        } else {
            lines.push(`<span class="lbl">mesh </span><span class="val">--</span>`);
        }
        // Proyeccion sobre el suelo (Z=0): Z constante por definicion del plano.
        const groundPt = projectOn(ray, groundPlane);
        if (groundPt) {
            const gp = toPlotly(groundPt);
            lines.push(`<span class="lbl">piso </span><span class="val">x=${fmt(gp.x)}  y=${fmt(gp.y)}  z= 0.00</span>`);
        }
        // Proyeccion sobre plano vertical Y=3 (centro del cuarto): Z varia.
        const midPt = projectOn(ray, midPlane);
        if (midPt) {
            const mp = toPlotly(midPt);
            lines.push(`<span class="lbl">Y=3  </span><span class="val">x=${fmt(mp.x)}  y= 3.00     z=${fmt(mp.z)}</span>`);
        }
        // Proyeccion sobre pared trasera Y=6: tambien util para Z.
        const wallPt = projectOn(ray, wallPlane);
        if (wallPt) {
            const wp = toPlotly(wallPt);
            lines.push(`<span class="lbl">Y=6  </span><span class="val">x=${fmt(wp.x)}  y= 6.00     z=${fmt(wp.z)}</span>`);
        }
        panel.innerHTML = lines.join('\n');
    });

    canvas.addEventListener('pointerleave', () => {
        panel.textContent = 'DEBUG: pasa el cursor sobre la escena';
    });
}
