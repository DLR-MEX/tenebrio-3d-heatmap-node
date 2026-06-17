// Orquestador de la escena Babylon.js. Crea engine, escena, camara, luces y
// reune todos los grupos de meshes. Equivalente a buildScene() del Plotly original.
// Mantiene el conteo de meshes constante entre frames del mismo modo (regla 14).

import { createCamera, refreshCameraBounds, setCameraTargetPlotly } from './camera.js';
import { interpolateColorscale, TEMP_COLORSCALE, HUMIDITY_COLORSCALE } from './colorScales.js';
import {
    buildHouseWireframe,
    buildFurnitureBox,
    buildLamps,
    buildExtractor,
    setExtractorOn,
    buildFloorGrid,
} from './meshes/house.js';
import {
    buildSensors,
    updateSensors,
    setSensorsVisibility,
} from './meshes/sensors.js';
import {
    buildExtZone,
    updateExtZone,
} from './meshes/extZone.js';
import {
    buildRadiantFloor,
    updateRadiantFloor,
    setRadiantFloorVisibility,
} from './meshes/radiantFloor.js';
import {
    buildMachineRoom,
    updateMachineRoom,
    setMachineRoomVisibility,
} from './meshes/machineRoom.js';
import {
    buildVolumeIso,
    updateVolumeIso,
    setVolumeIsoVisibility,
    getVolumeStats,
} from './meshes/volumeIso.js';
import { initDebugOverlay } from './debugOverlay.js';
import { DEV_TOOLS_ENABLED } from './config.js';

const { Engine, Scene, Color3, Color4, HemisphericLight, Vector3, SSAO2RenderingPipeline } = BABYLON;

let _engine = null;
let _scene = null;
let _canvas = null;
let _groups = null;
let _initialized = false;

export function initScene(canvas) {
    _canvas = canvas;
    _engine = new Engine(canvas, true, { preserveDrawingBuffer: false, stencil: false });
    _scene = new Scene(_engine);
    _scene.clearColor = new Color4(26/255, 38/255, 48/255, 1);

    // Luz hemisferica suave (no proyecta sombras, evita drift de iluminacion)
    const light = new HemisphericLight('hemi', new Vector3(0, 1, 0), _scene);
    light.intensity = 0.95;
    light.groundColor = new Color3(0.4, 0.4, 0.45);

    const camera = createCamera(_scene, canvas);

    // SSAO2: oclusión ambiental — oscurece esquinas y crevices, añade profundidad
    if (SSAO2RenderingPipeline) {
        try {
            const ssao = new SSAO2RenderingPipeline('ssao2', _scene,
                { ssaoRatio: 0.5, blurRatio: 1 }, [camera]);
            ssao.radius = 0.4;
            ssao.totalStrength = 1.6;
            ssao.base = 0.35;
            ssao.maxZ = 100;
            ssao.expensiveBlur = false;
        } catch (e) {
            console.warn('SSAO2 no disponible:', e);
        }
    }

    // Construir grupos estaticos y dinamicos
    const xRange = [0, 10], yRange = [0, 6], zRange = [0, 3];
    _groups = {
        floorGrid: buildFloorGrid(_scene),
        houseWire: buildHouseWireframe(_scene, xRange, yRange, zRange),
        furniture: buildFurnitureBox(_scene),
        lamps: buildLamps(_scene, zRange[1]),
        extractor: buildExtractor(_scene),
        sensors: buildSensors(_scene),
        extZone: buildExtZone(_scene),
        radiantFloor: buildRadiantFloor(_scene),
        machineRoom: buildMachineRoom(_scene),
        volumeIso: buildVolumeIso(_scene),
    };

    _engine.runRenderLoop(() => {
        _scene.render();
    });

    window.addEventListener('resize', () => {
        _engine.resize();
        refreshCameraBounds(canvas);
    });

    // Overlay de coordenadas para depurar posiciones de objetos (solo si DEV_TOOLS_ENABLED)
    if (DEV_TOOLS_ENABLED) {
        const sceneContainer = document.getElementById('scene-container');
        if (sceneContainer) initDebugOverlay(sceneContainer, canvas, _scene);
    }

    _initialized = true;
}

export function isReady() {
    return _initialized;
}

/**
 * Reconstruye la escena segun el modo y los datos recibidos.
 * Equivalente a buildScene(data) del frontend Plotly original.
 */
export function buildScene(data, mode) {
    if (!_initialized) return;

    const isFloor = mode === 'floor';
    const isFull = mode === 'full-temp' || mode === 'full-hum';
    const isTemp = mode === 'temp' || mode === 'full-temp' || isFloor;
    const showRadiant = isFloor || isFull;
    const showMachine = isFull || isFloor;
    const showRoomSensors = !isFloor;

    // Centrar la camara segun el modo:
    //  - temp / hum: centro de la casa (sola, sin sala de maquinas)
    //  - floor / full-*: centro general del diseño (casa + sala de maquinas)
    if (mode === 'temp' || mode === 'humidity') {
        setCameraTargetPlotly([5, 3, 1.5]);
    } else if (isFloor || isFull) {
        setCameraTargetPlotly([1, 3, 1.5]);
    }

    // Volumen activo segun modo (temperatura o humedad)
    const vol = isFloor ? null : (isTemp ? data.volume_data : data.humidity_volume_data);

    // Sensores y zona exterior
    if (showRoomSensors) {
        updateSensors(_groups.sensors, data, isTemp, _scene);
        updateExtZone(_groups.extZone, data.tex_sensor);
    }
    setSensorsVisibility(_groups.sensors, showRoomSensors);
    _groups.extZone.isVisible = showRoomSensors;

    // Piso radiante
    if (showRadiant) {
        updateRadiantFloor(_groups.radiantFloor, data, _scene);
    }
    setRadiantFloorVisibility(_groups.radiantFloor, showRadiant);

    // Sala de maquinas
    if (showMachine) {
        updateMachineRoom(_groups.machineRoom, data, _scene);
    }
    setMachineRoomVisibility(_groups.machineRoom, showMachine);

    // Volumen / isosuperficies
    if (!isFloor && vol) {
        updateVolumeIso(vol, isTemp);
    } else {
        setVolumeIsoVisibility(false);
    }

    // Estado del extractor (giro de aspas)
    setExtractorOn(!!data.extractor_on);

    // Barra de color en el HTML
    updateColorbar(vol, isTemp, isFloor);
}

function updateColorbar(volume, isTemp, isFloor) {
    const wrap = document.getElementById('colorbar-wrap');
    const bar = document.getElementById('colorbar-bar');
    const scale = document.getElementById('colorbar-scale');
    if (!wrap || !bar || !scale) return;
    if (isFloor || !volume) {
        wrap.style.display = 'none';
        return;
    }
    wrap.style.display = 'flex';
    const stats = getVolumeStats(volume, isTemp);
    if (!stats) { wrap.style.display = 'none'; return; }
    const colorscale = isTemp ? TEMP_COLORSCALE : HUMIDITY_COLORSCALE;
    // Gradiente CSS top→bottom desde cmax hasta cmin. Los stops deben ir en
    // orden ASCENDENTE de %, asi que invertimos la colorscale (que va de t=0..1)
    // — sin reverse() los stops aparecen en orden descendente y CSS los colapsa.
    const stops = [...colorscale].reverse()
        .map(([t, c]) => `${c} ${(1 - t) * 100}%`).join(', ');
    bar.style.background = `linear-gradient(to bottom, ${stops})`;
    const unit = stats.unit;
    const min = stats.cmin, max = stats.cmax;
    const v75 = min + (max - min) * 0.25;
    const v50 = min + (max - min) * 0.50;
    const v25 = min + (max - min) * 0.75;
    scale.innerHTML = `
        <span>${max.toFixed(1)}${unit}</span>
        <span>${v75.toFixed(1)}${unit}</span>
        <span>${v50.toFixed(1)}${unit}</span>
        <span>${v25.toFixed(1)}${unit}</span>
        <span>${min.toFixed(1)}${unit}</span>
    `;
}
