// Piso radiante: losa de concreto, capa de aislamiento, tuberia serpentin,
// derivacion, malla de refuerzo y sensores T1 (Salida) y T3 (Medio Piso).
// Conserva posiciones, colores y dimensiones del frontend Plotly original.

import { tempColor } from '../colorScales.js';
import { p, parseColor, createTextLabel } from './labels.js';
import { applyOverride } from '../labelOverrides.js';

const { Color3, MeshBuilder, StandardMaterial, Vector3 } = BABYLON;

const SLAB_X0 = 1, SLAB_X1 = 9, SLAB_Y0 = 0.5, SLAB_Y1 = 5.5;
const SLAB_Z0 = 0, SLAB_Z1 = 0.5;
const PIPE_Z = 0.25;
const N_LOOPS = 8;
const PIPE_MARGIN = 0.5;

/** Calcula los puntos del serpentin (mismo algoritmo que el original). */
function buildSerpentinePoints() {
    const loopSpacing = (SLAB_Y1 - SLAB_Y0 - 2 * PIPE_MARGIN) / N_LOOPS;
    const points = [];
    for (let i = 0; i <= N_LOOPS; i++) {
        const y = SLAB_Y0 + PIPE_MARGIN + i * loopSpacing;
        if (i % 2 === 0) {
            points.push([SLAB_X0 + PIPE_MARGIN, y, PIPE_Z]);
            points.push([SLAB_X1 - PIPE_MARGIN, y, PIPE_Z]);
        } else {
            points.push([SLAB_X1 - PIPE_MARGIN, y, PIPE_Z]);
            points.push([SLAB_X0 + PIPE_MARGIN, y, PIPE_Z]);
        }
    }
    return points;
}

export function buildRadiantFloor(scene) {
    const group = { meshes: [], slab: null, slabMat: null, t1: null, t3: null };

    // Losa de concreto
    const slab = MeshBuilder.CreateBox('slab', {
        width: SLAB_X1 - SLAB_X0,
        depth: SLAB_Y1 - SLAB_Y0,
        height: SLAB_Z1 - SLAB_Z0,
    }, scene);
    slab.position = p((SLAB_X0+SLAB_X1)/2, (SLAB_Y0+SLAB_Y1)/2, (SLAB_Z0+SLAB_Z1)/2);
    const slabMat = new StandardMaterial('slabMat', scene);
    slabMat.diffuseColor = new Color3(0.5, 0.5, 0.5);
    slabMat.alpha = 0.45;
    slab.material = slabMat;
    slab.isPickable = false;
    group.slab = slab;
    group.slabMat = slabMat;
    group.meshes.push(slab);

    // Aislamiento
    const ins = MeshBuilder.CreateBox('insulation', {
        width: SLAB_X1 - SLAB_X0, depth: SLAB_Y1 - SLAB_Y0, height: 0.08,
    }, scene);
    ins.position = p((SLAB_X0+SLAB_X1)/2, (SLAB_Y0+SLAB_Y1)/2, -0.04);
    const insMat = new StandardMaterial('insMat', scene);
    const [ir, ig, ib] = parseColor('#C8A84E');
    insMat.diffuseColor = new Color3(ir, ig, ib);
    insMat.alpha = 0.3;
    ins.material = insMat;
    ins.isPickable = false;
    group.meshes.push(ins);

    // Serpentin (tubo 3D)
    const pipePts = buildSerpentinePoints();
    const serpTube = buildTube(scene, 'serpentine', pipePts.map(pt => p(pt[0], pt[1], pt[2])), 0.05, '#E05020', 1);
    group.meshes.push(serpTube);

    // Derivacion serpentin → V2 (tubo 3D)
    const derivTube = buildTube(scene, 'serpDeriv',
        [p(SLAB_X0+PIPE_MARGIN, 3, PIPE_Z), p(SLAB_X0+PIPE_MARGIN, 3, 0.5), p(0.5, 3, 0.5)],
        0.045, '#E05020', 1);
    group.meshes.push(derivTube);

    // Tuberia entrada (roja, tubo 3D)
    const inTube = buildTube(scene, 'pipeIn',
        [p(pipePts[0][0], pipePts[0][1], PIPE_Z), p(pipePts[0][0], pipePts[0][1], 0.5), p(pipePts[0][0]-0.3, pipePts[0][1], 0.5)],
        0.05, '#CC3300', 1);
    group.meshes.push(inTube);

    // Tuberia retorno (gris, tubo 3D)
    const last = pipePts[pipePts.length-1];
    const retTube = buildTube(scene, 'pipeOut',
        [p(last[0], last[1], PIPE_Z), p(last[0], last[1], 0.5), p(last[0]+0.3, last[1], 0.5)],
        0.05, '#999999', 1);
    group.meshes.push(retTube);

    // Malla de refuerzo (gris)
    const meshLines = [];
    for (let mx = SLAB_X0 + 1; mx < SLAB_X1; mx += 1) {
        meshLines.push([p(mx, SLAB_Y0+0.3, 0.2), p(mx, SLAB_Y1-0.3, 0.2)]);
    }
    for (let my = SLAB_Y0 + 0.5; my < SLAB_Y1; my += 0.8) {
        meshLines.push([p(SLAB_X0+0.3, my, 0.2), p(SLAB_X1-0.3, my, 0.2)]);
    }
    const reinforce = MeshBuilder.CreateLineSystem('reinforceMesh', { lines: meshLines }, scene);
    reinforce.color = new Color3(0.6, 0.6, 0.6);
    reinforce.alpha = 0.3;
    group.meshes.push(reinforce);

    // Sensor T3 (Medio Piso)
    const t3Marker = MeshBuilder.CreatePolyhedron('rfT3', { type: 1, size: 0.09 }, scene);
    t3Marker.position = p(5, 3, 0.65);
    const t3Mat = new StandardMaterial('rfT3_mat', scene);
    t3Mat.diffuseColor = new Color3(0.5, 0.5, 0.5);
    t3Marker.material = t3Mat;
    group.t3 = { marker: t3Marker, mat: t3Mat, label: null, probe: null };
    group.meshes.push(t3Marker);

    // Sonda T3 (tubo metalico fino)
    const t3Probe = buildTube(scene, 'rfT3_probe',
        [p(5, 3, PIPE_Z), p(5, 3, 0.65)], 0.02, '#aaaaaa', 1);
    group.t3.probe = t3Probe;
    group.meshes.push(t3Probe);

    // Sensor T1 (Salida)
    const t1x = last[0] + 0.3, t1y = last[1], t1z = 0.7;
    const t1Marker = MeshBuilder.CreatePolyhedron('rfT1', { type: 1, size: 0.09 }, scene);
    t1Marker.position = p(t1x, t1y, t1z);
    const t1Mat = new StandardMaterial('rfT1_mat', scene);
    t1Mat.diffuseColor = new Color3(0.5, 0.5, 0.5);
    t1Marker.material = t1Mat;
    group.t1 = { marker: t1Marker, mat: t1Mat, label: null, x: t1x, y: t1y, z: t1z };
    group.meshes.push(t1Marker);

    return group;
}

export function updateRadiantFloor(group, data, scene) {
    // Color de la losa segun promedio de sensores
    const rf = data.radiant_floor || {};
    const vals = ['temperatura1', 'temperatura3'].map(k => rf[k]).filter(v => v && v.value !== null).map(v => v.value);
    if (vals.length > 0) {
        const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
        const [r, g, b] = parseColor(tempColor(avg));
        group.slabMat.diffuseColor.set(r, g, b);
    } else {
        group.slabMat.diffuseColor.set(0.5, 0.5, 0.5);
    }

    // Sensor T3 — etiqueta separada del rombo
    const t3 = rf['temperatura3'];
    if (t3 && t3.value !== null) {
        const [r, g, b] = parseColor(tempColor(t3.value));
        group.t3.mat.diffuseColor.set(r, g, b);
        group.t3.marker.scaling.setAll(1);
        const pos = applyOverride('rf_t3', [5, 3, 0.65 + 0.20]);
        replaceLabel(scene, group.t3, 'label', `T3 MEDIO: ${t3.value.toFixed(1)}°C`, pos, '#ffffff');
    } else {
        group.t3.marker.scaling.setAll(0);
        const pos = applyOverride('rf_t3', [5, 3, 0.65 + 0.20]);
        replaceLabel(scene, group.t3, 'label', '', pos, '#ffffff');
    }

    // Sensor T1 — etiqueta separada del rombo
    const t1 = rf['temperatura1'];
    const t1info = group.t1;
    if (t1 && t1.value !== null) {
        const [r, g, b] = parseColor(tempColor(t1.value));
        t1info.mat.diffuseColor.set(r, g, b);
        t1info.marker.scaling.setAll(1);
        const pos = applyOverride('rf_t1', [t1info.x, t1info.y, t1info.z + 0.20]);
        replaceLabel(scene, t1info, 'label', `T1 SALIDA: ${t1.value.toFixed(1)}°C`, pos, '#ffffff');
    } else {
        t1info.marker.scaling.setAll(0);
        const pos = applyOverride('rf_t1', [t1info.x, t1info.y, t1info.z + 0.20]);
        replaceLabel(scene, t1info, 'label', '', pos, '#ffffff');
    }
}

export function setRadiantFloorVisibility(group, visible) {
    for (const m of group.meshes) m.isVisible = visible;
    if (group.t3.label) group.t3.label.isVisible = visible;
    if (group.t1.label) group.t1.label.isVisible = visible;
}

function replaceLabel(scene, holder, key, text, pos, color) {
    if (holder[key]) holder[key].dispose(false, true);
    if (!text) {
        holder[key] = null;
        return;
    }
    holder[key] = createTextLabel(scene, `lbl_${holder.marker.name}`, text, pos, color);
}

/** Construye un tubo 3D solido a partir de un path de Vector3. */
function buildTube(scene, name, path, radius, color, opacity) {
    const tube = MeshBuilder.CreateTube(name, {
        path,
        radius,
        tessellation: 12,
        cap: BABYLON.Mesh.CAP_ALL,
        sideOrientation: BABYLON.Mesh.DOUBLESIDE,
    }, scene);
    const mat = new StandardMaterial(`${name}_mat`, scene);
    const [r, g, b] = parseColor(color);
    mat.diffuseColor = new Color3(r, g, b);
    mat.specularColor = new Color3(0.2, 0.2, 0.2);
    mat.alpha = opacity;
    tube.material = mat;
    tube.isPickable = false;
    return tube;
}
