// Wireframe de la casa (paredes, techo inclinado, ventanas, puerta), mueble de
// madera, jardinera y lamparas vintage. Replica de buildHouseStructure del frontend
// Plotly original. Mantiene posiciones, dimensiones y colores identicos.

import { p, parseColor } from './labels.js';

const { Color3, Color4, Mesh, MeshBuilder, Vector3, StandardMaterial, VertexData } = BABYLON;

const WIRE_COLOR = new Color4(180/255, 200/255, 220/255, 0.5);
const GRID_COLOR = new Color4(0.18, 0.28, 0.38, 0.55);

/**
 * Crea el wireframe completo de la casa como una unica LinesMesh.
 * Devuelve un objeto { dispose } para integrar con el ciclo de vida.
 */
export function buildHouseWireframe(scene, xRange, yRange, zRange) {
    const [x0, x1] = xRange;
    const [y0, y1] = yRange;
    const [z0, z1] = zRange;
    const roofPeak = z1 + 1.5;
    const doorZ1 = 2.0;

    const segments = [];
    const edge = (a, b) => { segments.push([a, b]); };

    // Piso
    edge([x0,y0,z0],[x1,y0,z0]); edge([x1,y0,z0],[x1,y1,z0]);
    edge([x1,y1,z0],[x0,y1,z0]); edge([x0,y1,z0],[x0,y0,z0]);
    // Techo
    edge([x0,y0,z1],[x1,y0,z1]); edge([x1,y0,z1],[x1,y1,z1]);
    edge([x1,y1,z1],[x0,y1,z1]); edge([x0,y1,z1],[x0,y0,z1]);
    // Pilares
    edge([x0,y0,z0],[x0,y0,z1]); edge([x1,y0,z0],[x1,y0,z1]);
    edge([x1,y1,z0],[x1,y1,z1]); edge([x0,y1,z0],[x0,y1,z1]);
    // Techo inclinado
    edge([x0,y0,roofPeak],[x1,y0,roofPeak]);
    edge([x0,y0,z1],[x0,y0,roofPeak]);
    edge([x1,y0,z1],[x1,y0,roofPeak]);
    edge([x0,y0,roofPeak],[x0,y1,z1]);
    edge([x1,y0,roofPeak],[x1,y1,z1]);
    // Puerta pared X=0
    const doorY0 = 2.5, doorY1 = 3.5;
    edge([x0,doorY0,z0],[x0,doorY0,doorZ1]);
    edge([x0,doorY0,doorZ1],[x0,doorY1,doorZ1]);
    edge([x0,doorY1,doorZ1],[x0,doorY1,z0]);

    // 3 ventanas pared Y=6
    const winY = y1, winZ0 = 1.0, winZ1 = 2.0;
    for (const wx of [1.75, 4.5, 7.25]) {
        edge([wx, winY, winZ0], [wx + 1, winY, winZ0]);
        edge([wx + 1, winY, winZ0], [wx + 1, winY, winZ1]);
        edge([wx + 1, winY, winZ1], [wx, winY, winZ1]);
        edge([wx, winY, winZ1], [wx, winY, winZ0]);
        edge([wx + 0.5, winY, winZ0], [wx + 0.5, winY, winZ1]);
        edge([wx, winY, (winZ0 + winZ1) / 2], [wx + 1, winY, (winZ0 + winZ1) / 2]);
    }

    // 2 ventanas altas Y=0
    const hiWinY = y0, hiWinZ0 = 3.3, hiWinZ1 = 4.1;
    for (const wx of [3, 6]) {
        edge([wx, hiWinY, hiWinZ0], [wx + 1, hiWinY, hiWinZ0]);
        edge([wx + 1, hiWinY, hiWinZ0], [wx + 1, hiWinY, hiWinZ1]);
        edge([wx + 1, hiWinY, hiWinZ1], [wx, hiWinY, hiWinZ1]);
        edge([wx, hiWinY, hiWinZ1], [wx, hiWinY, hiWinZ0]);
        edge([wx + 0.5, hiWinY, hiWinZ0], [wx + 0.5, hiWinY, hiWinZ1]);
        edge([wx, hiWinY, (hiWinZ0 + hiWinZ1) / 2], [wx + 1, hiWinY, (hiWinZ0 + hiWinZ1) / 2]);
    }

    // (El extractor ahora se construye en 3D con buildExtractor; ya no se dibuja
    //  como una X plana en el wireframe.)

    // Mueble de madera (wireframe)
    const mX0 = 1, mX1 = 9, mY0 = 5.5, mY1 = y1, mZ0 = 0.3, mZ1 = 1.0;
    edge([mX0,mY0,mZ0],[mX1,mY0,mZ0]); edge([mX1,mY0,mZ0],[mX1,mY1,mZ0]);
    edge([mX1,mY1,mZ0],[mX0,mY1,mZ0]); edge([mX0,mY1,mZ0],[mX0,mY0,mZ0]);
    edge([mX0,mY0,mZ1],[mX1,mY0,mZ1]); edge([mX1,mY0,mZ1],[mX1,mY1,mZ1]);
    edge([mX1,mY1,mZ1],[mX0,mY1,mZ1]); edge([mX0,mY1,mZ1],[mX0,mY0,mZ1]);
    edge([mX0,mY0,mZ0],[mX0,mY0,mZ1]); edge([mX1,mY0,mZ0],[mX1,mY0,mZ1]);
    edge([mX1,mY1,mZ0],[mX1,mY1,mZ1]); edge([mX0,mY1,mZ0],[mX0,mY1,mZ1]);
    // Patas
    edge([mX0,mY0,0],[mX0,mY0,mZ0]); edge([mX1,mY0,0],[mX1,mY0,mZ0]);
    edge([mX1,mY1,0],[mX1,mY1,mZ0]); edge([mX0,mY1,0],[mX0,mY1,mZ0]);
    // Divisores y tiradores
    const mZmid = (mZ0 + mZ1) / 2;
    const gabW = (mX1 - mX0) / 4;
    for (let g = 1; g < 4; g++) {
        const gx = mX0 + g * gabW;
        edge([gx,mY0,mZ0],[gx,mY0,mZ1]);
    }
    edge([mX0,mY0,mZmid],[mX1,mY0,mZmid]);
    for (let g = 0; g < 4; g++) {
        const gxc = mX0 + g * gabW + gabW / 2;
        edge([gxc - 0.15, mY0, mZmid + 0.12], [gxc + 0.15, mY0, mZmid + 0.12]);
        edge([gxc - 0.15, mY0, mZmid - 0.12], [gxc + 0.15, mY0, mZmid - 0.12]);
    }

    // Jardinera
    const px_p0 = 1, px_p1 = 3, py_p0 = y1, py_p1 = y1 + 0.3, pz1 = 0.7;
    edge([px_p0,py_p0,z0],[px_p1,py_p0,z0]); edge([px_p1,py_p0,z0],[px_p1,py_p1,z0]);
    edge([px_p1,py_p1,z0],[px_p0,py_p1,z0]); edge([px_p0,py_p1,z0],[px_p0,py_p0,z0]);
    edge([px_p0,py_p0,pz1],[px_p1,py_p0,pz1]); edge([px_p1,py_p0,pz1],[px_p1,py_p1,pz1]);
    edge([px_p1,py_p1,pz1],[px_p0,py_p1,pz1]); edge([px_p0,py_p1,pz1],[px_p0,py_p0,pz1]);
    edge([px_p0,py_p0,z0],[px_p0,py_p0,pz1]); edge([px_p1,py_p0,z0],[px_p1,py_p0,pz1]);
    edge([px_p1,py_p1,z0],[px_p1,py_p1,pz1]); edge([px_p0,py_p1,z0],[px_p0,py_p1,pz1]);

    // Construir LineSystem en Babylon
    const lines = segments.map(([a, b]) => [p(a[0],a[1],a[2]), p(b[0],b[1],b[2])]);
    const colors = segments.map(() => [WIRE_COLOR, WIRE_COLOR]);
    const mesh = MeshBuilder.CreateLineSystem('houseWire', { lines, colors }, scene);
    mesh.isPickable = false;
    return mesh;
}

/** Mueble solido (caja con color #6b4226 op 0.7). */
export function buildFurnitureBox(scene) {
    const fm = { x0: 1, x1: 9, y0: 5.5, y1: 6, z0: 0.3, z1: 1.0 };
    const cx = (fm.x0 + fm.x1) / 2;
    const cy = (fm.y0 + fm.y1) / 2;
    const cz = (fm.z0 + fm.z1) / 2;
    const box = MeshBuilder.CreateBox('furniture', {
        width: fm.x1 - fm.x0,
        depth: fm.y1 - fm.y0,
        height: fm.z1 - fm.z0,
    }, scene);
    box.position = p(cx, cy, cz);
    const mat = new StandardMaterial('furnMat', scene);
    const [r, g, b] = parseColor('#6b4226');
    mat.diffuseColor = new Color3(r, g, b);
    mat.alpha = 0.7;
    box.material = mat;
    box.isPickable = false;
    return box;
}

/** Lamparas vintage en (2,3) y (8,3) — cable + pantalla + bombilla. */
export function buildLamps(scene, zWall) {
    const meshes = [];
    const lampPositions = [{ x: 2, y: 3 }, { x: 8, y: 3 }];
    for (const lp of lampPositions) {
        const zCeil = zWall + 1.5 - (lp.y / 6) * 1.5;
        const lampBottom = zWall - 0.1;
        const shadeR = 0.35;
        // Cable
        const cable = MeshBuilder.CreateLines(`lampCable_${lp.x}_${lp.y}`, {
            points: [p(lp.x, lp.y, zCeil), p(lp.x, lp.y, lampBottom + 0.05)],
        }, scene);
        cable.color = new Color3(0.53, 0.53, 0.53);
        meshes.push(cable);
        // Pantalla — disco (CreateDisc)
        const disc = MeshBuilder.CreateDisc(`lampShade_${lp.x}_${lp.y}`, {
            radius: shadeR, tessellation: 16,
        }, scene);
        disc.position = p(lp.x, lp.y, lampBottom);
        disc.rotation.x = Math.PI / 2; // disco horizontal (normal en Y)
        const dm = new StandardMaterial(`lampShade_mat_${lp.x}`, scene);
        const [r, g, b] = parseColor('#8B6914');
        dm.diffuseColor = new Color3(r, g, b);
        dm.alpha = 0.6;
        dm.backFaceCulling = false;
        disc.material = dm;
        meshes.push(disc);
        // Bombilla
        const bulb = MeshBuilder.CreateSphere(`lampBulb_${lp.x}_${lp.y}`, {
            diameter: 0.18, segments: 8,
        }, scene);
        bulb.position = p(lp.x, lp.y, lampBottom - 0.12);
        const bm = new StandardMaterial(`lampBulb_mat_${lp.x}`, scene);
        const [br, bg, bb] = parseColor('#FFD700');
        bm.diffuseColor = new Color3(br, bg, bb);
        bm.emissiveColor = new Color3(br * 0.6, bg * 0.4, 0);
        bulb.material = bm;
        meshes.push(bulb);
    }
    return meshes;
}

// =============================================================================
// EXTRACTOR 3D animado (entre las dos ventanas altas en pared Y=0)
// =============================================================================

const { TransformNode } = BABYLON;

let _extBladeGroup = null;
let _extTargetSpeed = 0;     // rad/s objetivo
let _extCurrentSpeed = 0;    // rad/s actual (interpolado)

/**
 * Construye un extractor 3D real: marco cuadrado en la pared, carcasa cilindrica,
 * 5 aspas con paso (pitch) y cubo central. Las aspas giran cuando setExtractorOn(true).
 * Pared Y=0 (Plotly), centro del extractor entre las ventanas altas.
 */
export function buildExtractor(scene) {
    const meshes = [];
    const cx = 5.0;
    const cy = 0;        // pared frontal
    const cz = 3.7;
    const housingR = 0.27;
    const housingDepth = 0.10;
    const wallEmbed = 0.06; // que tanto entra al cuarto

    // Marco cuadrado exterior (placa de montaje)
    const frame = MeshBuilder.CreateBox('extFrame', {
        width: 0.62,
        height: 0.62,
        depth: 0.025,
    }, scene);
    frame.position = p(cx, cy + wallEmbed, cz);
    const frameMat = new StandardMaterial('extFrameMat', scene);
    const [fr, fg, fb] = parseColor('#3a4a55');
    frameMat.diffuseColor = new Color3(fr, fg, fb);
    frameMat.specularColor = new Color3(0.4, 0.4, 0.4);
    frame.material = frameMat;
    frame.isPickable = false;
    meshes.push(frame);

    // 4 pernos del marco (esquinas)
    for (const [bx, bz] of [[cx-0.27, cz-0.27], [cx+0.27, cz-0.27], [cx-0.27, cz+0.27], [cx+0.27, cz+0.27]]) {
        const bolt = MeshBuilder.CreateSphere(`extFrameBolt_${bx}_${bz}`, {
            diameter: 0.04, segments: 6,
        }, scene);
        bolt.position = p(bx, cy + wallEmbed - 0.012, bz);
        const bm = new StandardMaterial(`extFrameBoltMat_${bx}_${bz}`, scene);
        bm.diffuseColor = new Color3(0.75, 0.75, 0.78);
        bm.specularColor = new Color3(0.7, 0.7, 0.7);
        bolt.material = bm;
        bolt.isPickable = false;
        meshes.push(bolt);
    }

    // Carcasa cilindrica (housing) — eje en Y Plotly = Z Babylon
    const housing = MeshBuilder.CreateCylinder('extHousing', {
        height: housingDepth,
        diameter: housingR * 2,
        tessellation: 24,
    }, scene);
    housing.rotation.x = Math.PI / 2; // eje Y_up → Z_depth
    housing.position = p(cx, cy + wallEmbed, cz);
    const housingMat = new StandardMaterial('extHousingMat', scene);
    housingMat.diffuseColor = new Color3(0.32, 0.36, 0.42);
    housingMat.specularColor = new Color3(0.55, 0.55, 0.55);
    housing.material = housingMat;
    housing.isPickable = false;
    meshes.push(housing);

    // Cubo central / hub — esfera en el centro
    const hub = MeshBuilder.CreateSphere('extHub', {
        diameter: 0.10,
        segments: 12,
    }, scene);
    hub.position = p(cx, cy + wallEmbed + 0.005, cz);
    const hubMat = new StandardMaterial('extHubMat', scene);
    hubMat.diffuseColor = new Color3(0.18, 0.20, 0.24);
    hubMat.specularColor = new Color3(0.6, 0.6, 0.6);
    hub.material = hubMat;
    hub.isPickable = false;
    meshes.push(hub);

    // Grupo padre que rota: contiene las aspas
    const bladeGroup = new TransformNode('extBladeGroup', scene);
    bladeGroup.position = p(cx, cy + wallEmbed + 0.005, cz);
    _extBladeGroup = bladeGroup;

    // 5 aspas con paso (pitch) de 25°. Cada aspa es hijo de un nodo angular
    // pre-rotado alrededor del eje Z (eje del rotor) para distribuir uniformemente.
    const N_BLADES = 5;
    const innerR = 0.05;
    const outerR = housingR - 0.02;
    const bladeLen = outerR - innerR;
    const midR = (innerR + outerR) / 2;
    const pitch = (25 * Math.PI) / 180;
    const bladeMat = new StandardMaterial('extBladeMat', scene);
    bladeMat.diffuseColor = new Color3(0.85, 0.87, 0.90);
    bladeMat.specularColor = new Color3(0.6, 0.6, 0.6);

    for (let i = 0; i < N_BLADES; i++) {
        const angularNode = new TransformNode(`extBladeAng_${i}`, scene);
        angularNode.parent = bladeGroup;
        angularNode.rotation.z = (i * 2 * Math.PI) / N_BLADES;

        const blade = MeshBuilder.CreateBox(`extBlade_${i}`, {
            width: bladeLen,
            height: 0.10,    // chord
            depth: 0.012,    // espesor
        }, scene);
        blade.parent = angularNode;
        blade.position = new Vector3(midR, 0, 0);
        blade.rotation.x = pitch; // paso de la pala
        blade.material = bladeMat;
        blade.isPickable = false;
    }

    // Reja exterior (4 barras finas cruzadas en el frente, estilo grill)
    for (let i = 0; i < 4; i++) {
        const bar = MeshBuilder.CreateBox(`extGrill_${i}`, {
            width: housingR * 2 - 0.02,
            height: 0.012,
            depth: 0.012,
        }, scene);
        bar.position = p(cx, cy + 0.005, cz);
        bar.rotation.z = (i * Math.PI) / 4;
        const gm = new StandardMaterial(`extGrillMat_${i}`, scene);
        gm.diffuseColor = new Color3(0.25, 0.27, 0.30);
        bar.material = gm;
        bar.isPickable = false;
        meshes.push(bar);
    }

    // Loop de animacion: interpola velocidad, gira el bladeGroup
    scene.onBeforeRenderObservable.add(() => {
        const dt = scene.getEngine().getDeltaTime() / 1000; // segundos
        // Interpolacion exponencial hacia la velocidad objetivo
        const lerp = Math.min(1, dt * 1.5);
        _extCurrentSpeed += (_extTargetSpeed - _extCurrentSpeed) * lerp;
        if (_extBladeGroup) {
            _extBladeGroup.rotation.z += _extCurrentSpeed * dt;
        }
    });

    return { meshes, bladeGroup };
}

/**
 * Grid de referencia en el piso (Plotly z=0). Lineas cada unidad sobre X e Y.
 * Provee referencia espacial visual para percibir profundidad y escala.
 */
export function buildFloorGrid(scene) {
    const lines = [];
    const colors = [];

    // Lineas a lo largo de Plotly-X (Y varia 0..6, Z=0)
    for (let iy = 0; iy <= 6; iy++) {
        lines.push([p(0, iy, 0), p(10, iy, 0)]);
        colors.push([GRID_COLOR, GRID_COLOR]);
    }
    // Lineas a lo largo de Plotly-Y (X varia 0..10, Z=0)
    for (let ix = 0; ix <= 10; ix++) {
        lines.push([p(ix, 0, 0), p(ix, 6, 0)]);
        colors.push([GRID_COLOR, GRID_COLOR]);
    }

    const mesh = MeshBuilder.CreateLineSystem('floorGrid', { lines, colors }, scene);
    mesh.isPickable = false;
    return mesh;
}

/**
 * Activa o desactiva el giro del extractor.
 * @param {boolean} on
 */
export function setExtractorOn(on) {
    _extTargetSpeed = on ? 9 : 0; // rad/s ≈ 86 rpm cuando esta encendido
}
