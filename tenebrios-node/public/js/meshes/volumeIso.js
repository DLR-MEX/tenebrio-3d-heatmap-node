// Volumen 3D — slice planes apilados con DynamicTexture semitransparente.
//
// Plotly renderizaba el volumen completo en bandas con `isosurface(isomin..isomax)`
// — equivalente a un "volume rendering" con caps. Para reproducir el aspecto
// difuminado/translucido sin shaders custom, apilamos N planos horizontales
// perpendiculares al eje vertical, cada uno con una DynamicTexture rellena con
// los valores del volumen en esa altura. La interpolacion bilineal del GPU + la
// suma de N capas semitransparentes producen un degradado volumetrico continuo
// donde se ve el interior del cuarto.
//
// Mantiene el conteo de meshes constante (N planos preasignados, regla 14).

import { interpolateColorscale, TEMP_COLORSCALE, HUMIDITY_COLORSCALE } from '../colorScales.js';

const { Color3, Mesh, MeshBuilder, StandardMaterial, DynamicTexture, Vector3, Engine } = BABYLON;

// Resolucion del grid (debe coincidir con backend config.GRID_RES_*)
const NX = 25, NY = 18, NZ = 12;

// Numero de slices visibles. Mas slices = mas difuso. 14 da equilibrio entre
// suavidad y transparencia para ver el interior del cuarto.
const N_SLICES = 14;
// Resolucion de cada textura (filtra bilinealmente con el GPU)
const TEX_W = 64;
const TEX_H = 36;

// Limites del cuarto
const ROOM_X = [0, 10];
const ROOM_Y = [0, 6];
const ROOM_Z = [0, 3];

let _scene = null;
let _slices = []; // { mesh, tex, mat, zLevel }
let _devHidden = false; // flag de depuracion: oculta el volumen aunque haya datos

export function buildVolumeIso(scene) {
    _scene = scene;
    _slices = [];

    const dz = (ROOM_Z[1] - ROOM_Z[0]) / N_SLICES;
    for (let i = 0; i < N_SLICES; i++) {
        const zLevel = ROOM_Z[0] + (i + 0.5) * dz;

        const plane = MeshBuilder.CreatePlane(`volSlice_${i}`, {
            width: ROOM_X[1] - ROOM_X[0],
            height: ROOM_Y[1] - ROOM_Y[0],
            sideOrientation: Mesh.DOUBLESIDE,
        }, scene);
        // Plano horizontal (normal hacia arriba). En Babylon Y=arriba.
        plane.rotation.x = Math.PI / 2;
        plane.position.x = (ROOM_X[0] + ROOM_X[1]) / 2;
        plane.position.y = zLevel;
        plane.position.z = (ROOM_Y[0] + ROOM_Y[1]) / 2;
        plane.isPickable = false;
        plane.alphaIndex = 1000 + i; // forzar orden de blending top-down

        const tex = new DynamicTexture(`volTex_${i}`, { width: TEX_W, height: TEX_H }, scene, false);
        tex.hasAlpha = true;
        tex.wrapU = 0;
        tex.wrapV = 0;

        const mat = new StandardMaterial(`volMat_${i}`, scene);
        // Usar emissiveTexture en vez de diffuseTexture: rinde la textura "tal cual"
        // sin sumarla a un emissiveColor blanco que saturaba el color hacia blanco.
        mat.emissiveTexture = tex;
        mat.opacityTexture = tex;
        mat.disableLighting = true;
        mat.emissiveColor = new Color3(0, 0, 0);
        mat.diffuseColor = new Color3(0, 0, 0);
        mat.specularColor = new Color3(0, 0, 0);
        mat.ambientColor = new Color3(0, 0, 0);
        mat.backFaceCulling = false;
        plane.material = mat;
        plane.isVisible = false;

        _slices.push({ mesh: plane, tex, mat, zLevel });
    }
    return { meshes: _slices.map(s => s.mesh) };
}

/**
 * Reconstruye los slices a partir del array plano del volumen.
 * @param {object} volume - {x:[], y:[], z:[], value:[]} en orden x-mas-rapido.
 * @param {boolean} isTemp - true si es temperatura, false si es humedad.
 */
export function updateVolumeIso(volume, isTemp) {
    if (!_slices.length) return;
    if (_devHidden || !volume || !volume.value || volume.value.length === 0) {
        for (const s of _slices) s.mesh.isVisible = false;
        return;
    }

    const colorscale = isTemp ? TEMP_COLORSCALE : HUMIDITY_COLORSCALE;
    const cmin = isTemp ? 14 : 0;
    const cmax = isTemp ? 35 : 100;
    const range = cmax - cmin;
    const values = volume.value;

    // Coordenadas del grid en el sistema Plotly
    const dx = (ROOM_X[1] - ROOM_X[0]) / (NX - 1);
    const dy = (ROOM_Y[1] - ROOM_Y[0]) / (NY - 1);
    const dzGrid = (ROOM_Z[1] - ROOM_Z[0]) / (NZ - 1);

    for (const slice of _slices) {
        fillSliceTexture(slice, values, slice.zLevel, dx, dy, dzGrid, colorscale, cmin, range);
        slice.mesh.isVisible = true;
    }
}

function fillSliceTexture(slice, values, zLevel, dx, dy, dzGrid, colorscale, cmin, range) {
    const ctx = slice.tex.getContext();
    const imgData = ctx.createImageData(TEX_W, TEX_H);
    const data = imgData.data;

    // Coordenadas de la capa Z en el grid (interpolacion lineal entre 2 capas adyacentes)
    const izFloat = (zLevel - ROOM_Z[0]) / dzGrid;
    const izLow = Math.max(0, Math.min(NZ - 1, Math.floor(izFloat)));
    const izHi = Math.max(0, Math.min(NZ - 1, izLow + 1));
    const fz = izFloat - izLow;

    // Para cada texel del plano, calcular su valor por interpolacion trilineal
    for (let py = 0; py < TEX_H; py++) {
        // Coord Y-Plotly (0..6) en este pixel
        const yPlotly = ROOM_Y[0] + (py / (TEX_H - 1)) * (ROOM_Y[1] - ROOM_Y[0]);
        const iyFloat = (yPlotly - ROOM_Y[0]) / dy;
        const iyLow = Math.max(0, Math.min(NY - 1, Math.floor(iyFloat)));
        const iyHi = Math.max(0, Math.min(NY - 1, iyLow + 1));
        const fy = iyFloat - iyLow;

        for (let px = 0; px < TEX_W; px++) {
            const xPlotly = ROOM_X[0] + (px / (TEX_W - 1)) * (ROOM_X[1] - ROOM_X[0]);
            const ixFloat = (xPlotly - ROOM_X[0]) / dx;
            const ixLow = Math.max(0, Math.min(NX - 1, Math.floor(ixFloat)));
            const ixHi = Math.max(0, Math.min(NX - 1, ixLow + 1));
            const fx = ixFloat - ixLow;

            // Trilineal: 8 esquinas
            const v000 = values[ixLow + NX * (iyLow + NY * izLow)];
            const v100 = values[ixHi + NX * (iyLow + NY * izLow)];
            const v010 = values[ixLow + NX * (iyHi + NY * izLow)];
            const v110 = values[ixHi + NX * (iyHi + NY * izLow)];
            const v001 = values[ixLow + NX * (iyLow + NY * izHi)];
            const v101 = values[ixHi + NX * (iyLow + NY * izHi)];
            const v011 = values[ixLow + NX * (iyHi + NY * izHi)];
            const v111 = values[ixHi + NX * (iyHi + NY * izHi)];

            const v00 = v000 * (1 - fx) + v100 * fx;
            const v10 = v010 * (1 - fx) + v110 * fx;
            const v01 = v001 * (1 - fx) + v101 * fx;
            const v11 = v011 * (1 - fx) + v111 * fx;

            const v0 = v00 * (1 - fy) + v10 * fy;
            const v1 = v01 * (1 - fy) + v11 * fy;

            const v = v0 * (1 - fz) + v1 * fz;

            // Mapear valor a color
            const t = Math.max(0, Math.min(1, (v - cmin) / range));
            const rgb = interpolateColorscale(colorscale, t);
            const m = rgb.match(/\d+/g);
            const r = +m[0], g = +m[1], b = +m[2];

            // Alpha por texel — densidad reducida un poco para ver mejor los objetos
            // a traves del volumen. Suma acumulada de 14 capas ~ 60-75%.
            const alphaPerSlice = 0.07 + t * 0.05;
            const alpha = Math.round(alphaPerSlice * 255);

            const idx = (py * TEX_W + px) * 4;
            data[idx] = r;
            data[idx + 1] = g;
            data[idx + 2] = b;
            data[idx + 3] = alpha;
        }
    }

    ctx.putImageData(imgData, 0, 0);
    slice.tex.update(false);
}

export function setVolumeIsoVisibility(visible) {
    if (!_slices.length) return;
    for (const s of _slices) s.mesh.isVisible = visible && !_devHidden;
}

/** Toggle de depuracion para ocultar el mapa de calor sin cambiar de modo. */
export function setVolumeIsoDevHidden(hide) {
    _devHidden = !!hide;
    if (_devHidden) {
        for (const s of _slices) s.mesh.isVisible = false;
    }
}

export function isVolumeIsoDevHidden() {
    return _devHidden;
}

/** Estadisticas para la barra de color del HTML. */
export function getVolumeStats(volume, isTemp) {
    if (!volume || !volume.value) return null;
    let volMin = Infinity, volMax = -Infinity;
    for (let i = 0; i < volume.value.length; i++) {
        if (volume.value[i] < volMin) volMin = volume.value[i];
        if (volume.value[i] > volMax) volMax = volume.value[i];
    }
    return {
        volMin, volMax,
        cmin: isTemp ? 14 : 0,
        cmax: isTemp ? 35 : 100,
        unit: isTemp ? '°C' : '%',
    };
}
