// Zona exterior (jardinera coloreada por sensor tex). Volumen rectangular
// que llena la jardinera completa: X[1..3], Y[6..6.3], Z[0..0.7].
// Color dinámico según tempColor(tex), llena el volumen con color uniforme
// como el mapa de calor. Cuando no hay valor, se mantiene invisible (regla 14).

import { tempColor } from '../colorScales.js';
import { p, parseColor } from './labels.js';

const { Color3, MeshBuilder, StandardMaterial } = BABYLON;

export function buildExtZone(scene) {
    // Volumen rectangular que coincide con la jardinera del wireframe
    const width = 2;    // X: [1..3]
    const depth = 0.3;  // Y: [6..6.3]
    const height = 0.7; // Z: [0..0.7]

    const box = MeshBuilder.CreateBox('extZone', { width, height, depth }, scene);
    box.position = p(2, 6.15, 0.35); // Centro de la jardinera

    const mat = new StandardMaterial('extZone_mat', scene);
    mat.diffuseColor = new Color3(0.5, 0.5, 0.5);
    mat.emissiveColor = new Color3(0.5, 0.5, 0.5); // Color visible sin iluminar
    mat.specularColor = new Color3(0, 0, 0);
    mat.alpha = 0;
    mat.backFaceCulling = false;
    box.material = mat;
    box.isPickable = false;

    return box;
}

export function updateExtZone(plane, texSensor) {
    const mat = plane.material;
    if (texSensor && texSensor.value !== null && texSensor.value !== undefined) {
        const [r, g, b] = parseColor(tempColor(texSensor.value));
        mat.diffuseColor.set(r, g, b);
        mat.emissiveColor.set(r, g, b); // Llena el volumen con color uniforme
        mat.alpha = 0.85;
    } else {
        mat.alpha = 0;
    }
}
