// Sensores interiores t1..t5 + tex (exterior) — diamantes coloreados con UNA
// etiqueta combinada "NOMBRE : VALOR" + lineas de caida punteadas hacia el piso.

import { tempColor, humidityColor } from '../colorScales.js';
import { p, parseColor, createTextLabel } from './labels.js';
import { applyOverride } from '../labelOverrides.js';

const { Color3, MeshBuilder, StandardMaterial } = BABYLON;

const HUM_LABEL_MAP = { t1: 'h1', t2: 'h2', t3: 'h3', t4: 'h4', t5: 'h5' };
const SENSOR_KEYS = ['t1', 't2', 't3', 't4', 't5'];

/**
 * Crea un grupo de meshes para los sensores interiores + tex. Conteo de meshes
 * constante entre frames (regla 14): solo se reasignan colores, posiciones y textos.
 */
export function buildSensors(scene) {
    const group = {
        markers: {},
        combinedLabels: {}, // unica etiqueta por sensor: "T1 : 26.8 °C"
        dropLines: {},
        meshes: [],
    };

    const allKeys = [...SENSOR_KEYS, 'tex'];
    for (const key of allKeys) {
        const isExt = key === 'tex';

        // Marker tipo diamante (octaedro). Tamano uniforme para todos los sensores.
        const marker = MeshBuilder.CreatePolyhedron(`marker_${key}`, {
            type: 1, size: 0.09,
        }, scene);
        const mat = new StandardMaterial(`marker_mat_${key}`, scene);
        mat.diffuseColor = new Color3(0.5, 0.5, 0.5);
        mat.specularColor = new Color3(0.8, 0.8, 0.8);
        mat.specularPower = 64;
        marker.material = mat;
        marker.isPickable = false;
        group.markers[key] = marker;
        group.meshes.push(marker);

        // Linea de caida punteada
        const drop = MeshBuilder.CreateLines(`drop_${key}`, {
            points: [p(0, 0, 0), p(0, 0, 0)],
            updatable: true,
        }, scene);
        drop.color = new Color3(1, 1, 1);
        drop.alpha = 0.25;
        drop.isPickable = false;
        group.dropLines[key] = drop;
        group.meshes.push(drop);

        // Etiqueta combinada (se actualiza en update)
        const initialText = isExt ? 'EXTERIOR : --' : key.toUpperCase() + ' : --';
        const labelColor = '#ffffff';
        const labelMesh = createTextLabel(scene, `lbl_${key}`, initialText, [0, 0, 0], labelColor);
        group.combinedLabels[key] = labelMesh;
        group.meshes.push(labelMesh);
    }

    return group;
}

/** Actualiza posiciones, colores y textos. */
export function updateSensors(group, data, isTemp, scene) {
    const sensors = data.sensors;

    for (const key of SENSOR_KEYS) {
        const info = sensors[key];
        const marker = group.markers[key];
        const drop = group.dropLines[key];

        marker.position = p(info.x, info.y, info.z);
        const colorRgb = computeColor(key, info, data, isTemp);
        const [r, g, b] = parseColor(colorRgb);
        marker.material.diffuseColor.set(r, g, b);

        recreateDropLine(drop, info.x, info.y, info.z);

        // Etiqueta combinada NOMBRE : VALOR
        const labelName = isTemp ? key.toUpperCase() : (HUM_LABEL_MAP[key] || key).toUpperCase();
        let valueText;
        if (isTemp) {
            valueText = info.value !== null ? info.value.toFixed(1) + ' °C' : '--';
        } else {
            const hKey = HUM_LABEL_MAP[key];
            const hVal = hKey && data.humidity[hKey] !== null ? data.humidity[hKey].toFixed(1) + ' %' : '--';
            valueText = hVal;
        }
        // T1/T2/T3 (sensores superiores): etiqueta DEBAJO del rombo (z-0.28)
        // T4/T5 (sensores inferiores): etiqueta encima del rombo (z+0.22)
        const isUpper = key === 't1' || key === 't2' || key === 't3';
        const labelZ = isUpper ? info.z - 0.28 : info.z + 0.22;
        const text = `${labelName} : ${valueText}`;
        const pos = applyOverride(key, [info.x, info.y, labelZ]);
        replaceTextLabel(scene, group, 'combinedLabels', key, text, pos, '#ffffff');
    }

    // Sensor exterior tex — el marcador visual se eleva a 1.5m para no quedar
    // oculto por el wireframe de la jardinera (que ocupa Y=[6, 6.3], Z=[0, 0.7]).
    // La posicion API real (tex.z = 0.8) sigue reflejada en la linea-sonda vertical
    // que conecta el suelo con el marcador elevado.
    if (data.tex_sensor) {
        const tex = data.tex_sensor;
        const m = group.markers.tex;
        const visualZ = 1.5;
        m.position = p(tex.x, tex.y, visualZ);
        const colorRgb = tex.value !== null ? tempColor(tex.value) : 'rgb(136,136,136)';
        const [r, g, b] = parseColor(colorRgb);
        m.material.diffuseColor.set(r, g, b);
        recreateDropLine(group.dropLines.tex, tex.x, tex.y, visualZ);

        const valTxt = tex.value !== null ? tex.value.toFixed(1) + ' °C' : '--';
        const text = `EXTERIOR : ${valTxt}`;
        const pos = applyOverride('tex', [tex.x, tex.y, visualZ + 0.22]);
        replaceTextLabel(scene, group, 'combinedLabels', 'tex', text, pos, '#ffffff');
    }
}

export function setSensorsVisibility(group, visible) {
    group._visible = visible;
    for (const m of group.meshes) m.isVisible = visible;
}

function computeColor(key, info, data, isTemp) {
    if (isTemp && info.value !== null) return tempColor(info.value);
    if (!isTemp) {
        const hk = HUM_LABEL_MAP[key];
        const hv = hk && data.humidity[hk] !== null ? data.humidity[hk] : null;
        return hv !== null ? humidityColor(hv) : 'rgb(136,136,136)';
    }
    return 'rgb(136,136,136)';
}

function recreateDropLine(line, x, y, z) {
    BABYLON.MeshBuilder.CreateLines(line.name, {
        points: [p(x, y, 0), p(x, y, z)],
        instance: line,
        updatable: true,
    });
}

function replaceTextLabel(scene, group, kind, key, text, pos, color) {
    const old = group[kind][key];
    if (old) old.dispose(false, true);
    const fresh = createTextLabel(scene, `${kind}_${key}`, text, pos, color);
    group[kind][key] = fresh;
    const idx = group.meshes.indexOf(old);
    if (idx >= 0) group.meshes[idx] = fresh;
    else group.meshes.push(fresh);
}
