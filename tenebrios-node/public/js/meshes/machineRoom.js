// Sala de maquinas adyacente al cuarto principal: rotoplas, calentador solar,
// panel solar, termo, valvulas V1/V2, tuberias del circuito hidraulico y sensores.
// Replica posiciones, dimensiones y colores del frontend Plotly original.

import { tempColor, termoScaleColor } from '../colorScales.js';
import {
    p, parseColor, createTextLabel,
    buildVerticalCylinder, buildHorizontalCylinder,
} from './labels.js';
import { applyOverride } from '../labelOverrides.js';

const { Color3, MeshBuilder, StandardMaterial, Vector3 } = BABYLON;

const MR = { x0: -8, x1: -2, y0: 0, y1: 6, z0: 0, z1: 3 };
const COR = { x0: -2, x1: 0, y0: 0, y1: 6, z0: 0, z1: 2.5 };

// Cisterna desplazada de y=3 → y=4 para descongestionar el cruce de tuberias
// con el calentador solar (que vive en y=3). Las tuberias de retorno (gris) y
// bomba→solar (naranja) se reajustan automaticamente porque referencian RP.y.
const RP = { x: -5, y: 4, z0: 0, z1: 1.8, r: 0.6 };
const SOL = {
    x0: -7.5, x1: -3.5, y: 3, zBase: MR.z1 + 0.1,
    cylX0: -7.2, cylX1: -3.8, cylZ: MR.z1 + 0.1 + 0.8, cylR: 0.3,
    panelLen: 2.0,
};
const TERMO = { x0: -7, x1: -3.5, y: 1, r: 0.5, z: 0.6 };

export function buildMachineRoom(scene) {
    const group = { meshes: [], dynamic: {} };

    buildWireframe(scene, group);
    buildRotoplas(scene, group);
    buildSolarHeater(scene, group);
    buildTermo(scene, group);
    buildValvesAndPipes(scene, group);

    return group;
}

function buildWireframe(scene, group) {
    const segments = [];
    const edge = (a, b) => segments.push([p(a[0], a[1], a[2]), p(b[0], b[1], b[2])]);
    // Sala
    const m = MR;
    edge([m.x0,m.y0,m.z0],[m.x1,m.y0,m.z0]); edge([m.x1,m.y0,m.z0],[m.x1,m.y1,m.z0]);
    edge([m.x1,m.y1,m.z0],[m.x0,m.y1,m.z0]); edge([m.x0,m.y1,m.z0],[m.x0,m.y0,m.z0]);
    edge([m.x0,m.y0,m.z1],[m.x1,m.y0,m.z1]); edge([m.x1,m.y0,m.z1],[m.x1,m.y1,m.z1]);
    edge([m.x1,m.y1,m.z1],[m.x0,m.y1,m.z1]); edge([m.x0,m.y1,m.z1],[m.x0,m.y0,m.z1]);
    edge([m.x0,m.y0,m.z0],[m.x0,m.y0,m.z1]); edge([m.x0,m.y1,m.z0],[m.x0,m.y1,m.z1]);
    edge([m.x1,m.y0,m.z0],[m.x1,m.y0,m.z1]); edge([m.x1,m.y1,m.z0],[m.x1,m.y1,m.z1]);
    // Corredor
    const c = COR;
    edge([c.x0,c.y0,c.z0],[c.x1,c.y0,c.z0]); edge([c.x1,c.y0,c.z0],[c.x1,c.y1,c.z0]);
    edge([c.x1,c.y1,c.z0],[c.x0,c.y1,c.z0]); edge([c.x0,c.y1,c.z0],[c.x0,c.y0,c.z0]);
    edge([c.x0,c.y0,c.z1],[c.x1,c.y0,c.z1]); edge([c.x1,c.y0,c.z1],[c.x1,c.y1,c.z1]);
    edge([c.x1,c.y1,c.z1],[c.x0,c.y1,c.z1]); edge([c.x0,c.y1,c.z1],[c.x0,c.y0,c.z1]);
    edge([c.x0,c.y0,c.z0],[c.x0,c.y0,c.z1]); edge([c.x1,c.y0,c.z0],[c.x1,c.y0,c.z1]);
    edge([c.x0,c.y1,c.z0],[c.x0,c.y1,c.z1]); edge([c.x1,c.y1,c.z0],[c.x1,c.y1,c.z1]);

    const mesh = MeshBuilder.CreateLineSystem('mrWire', { lines: segments }, scene);
    mesh.color = new Color3(0.7, 0.78, 0.86);
    mesh.alpha = 0.4;
    mesh.isPickable = false;
    group.meshes.push(mesh);
}

function buildRotoplas(scene, group) {
    // ----- ROTOPLAS (cisterna estilo tinaco con cuerpo + hombro conico + tapa) -----
    const cyl = buildVerticalCylinder(scene, 'rotoplas', RP.x, RP.y, RP.z0, RP.z1, RP.r, 24, '#666666', 0.45);
    group.meshes.push(cyl);
    group.dynamic.rotoplasMat = cyl.material;

    // Hombro conico (transicion del cuerpo ancho a la tapa estrecha)
    const shoulderH = 0.13;
    const shoulder = MeshBuilder.CreateCylinder('rotoplasShoulder', {
        height: shoulderH,
        diameterBottom: RP.r * 2,
        diameterTop: 0.30 * 2,
        tessellation: 24,
    }, scene);
    shoulder.position = p(RP.x, RP.y, RP.z1 + shoulderH / 2);
    const shoulderMat = new StandardMaterial('rotoplasShoulderMat', scene);
    shoulderMat.diffuseColor = new Color3(0.40, 0.40, 0.40);
    shoulderMat.alpha = 0.55;
    shoulder.material = shoulderMat;
    shoulder.isPickable = false;
    group.meshes.push(shoulder);

    // Tapa (lid superior)
    const capH = 0.10;
    const capZBase = RP.z1 + shoulderH;
    const cap = MeshBuilder.CreateCylinder('rotoplasCap', {
        height: capH,
        diameter: 0.28 * 2,
        tessellation: 24,
    }, scene);
    cap.position = p(RP.x, RP.y, capZBase + capH / 2);
    const capMat = new StandardMaterial('rotoplasCapMat', scene);
    capMat.diffuseColor = new Color3(0.22, 0.18, 0.14); // marron oscuro
    capMat.specularColor = new Color3(0.3, 0.3, 0.3);
    cap.material = capMat;
    cap.isPickable = false;
    group.meshes.push(cap);

    // Aro / cuello superior de la tapa (anillo decorativo donde se enrosca)
    const capRing = MeshBuilder.CreateTorus('rotoplasCapRing', {
        diameter: 0.28 * 2 + 0.02,
        thickness: 0.02,
        tessellation: 24,
    }, scene);
    capRing.position = p(RP.x, RP.y, capZBase + capH);
    const capRingMat = new StandardMaterial('rotoplasCapRingMat', scene);
    capRingMat.diffuseColor = new Color3(0.30, 0.25, 0.20);
    capRing.material = capRingMat;
    capRing.isPickable = false;
    group.meshes.push(capRing);

    // ----- BOMBA M2 SUMERGIBLE (dentro de la cisterna, vertical) -----
    // Top de la tapa del rotoplas — usado para anclar el cable de poder.
    const cisternaCapTopZ_local = RP.z1 + shoulderH + capH;  // = 2.03

    const subX = RP.x, subY = RP.y;
    const subBottom = 0.04;
    const subTop = 0.42;
    const subR = 0.10;
    const subColor = '#252830';

    // Cuerpo principal (cilindro vertical) — motor + impulsor en una sola unidad
    const subBody = MeshBuilder.CreateCylinder('m2Body', {
        height: subTop - subBottom,
        diameter: subR * 2,
        tessellation: 20,
    }, scene);
    subBody.position = p(subX, subY, (subBottom + subTop) / 2);
    const subBodyMat = new StandardMaterial('m2BodyMat', scene);
    const [sbr, sbg, sbb] = parseColor(subColor);
    subBodyMat.diffuseColor = new Color3(sbr, sbg, sbb);
    subBodyMat.specularColor = new Color3(0.6, 0.6, 0.6);
    subBody.material = subBodyMat;
    subBody.isPickable = false;
    group.meshes.push(subBody);

    // Cono superior (cabeza, con la salida de descarga)
    const subTopCone = MeshBuilder.CreateCylinder('m2TopCone', {
        height: 0.06,
        diameterBottom: subR * 2,
        diameterTop: 0.08,
        tessellation: 18,
    }, scene);
    subTopCone.position = p(subX, subY, subTop + 0.03);
    subTopCone.material = subBodyMat;
    subTopCone.isPickable = false;
    group.meshes.push(subTopCone);

    // Strainer / pie filtro (cilindro corto y ancho en la base)
    const subStrainer = MeshBuilder.CreateCylinder('m2Strainer', {
        height: 0.04,
        diameter: subR * 2 + 0.06,
        tessellation: 18,
    }, scene);
    subStrainer.position = p(subX, subY, subBottom - 0.02);
    const subStrainerMat = new StandardMaterial('m2StrainerMat', scene);
    subStrainerMat.diffuseColor = new Color3(0.14, 0.14, 0.16);
    subStrainerMat.specularColor = new Color3(0.4, 0.4, 0.4);
    subStrainer.material = subStrainerMat;
    subStrainer.isPickable = false;
    group.meshes.push(subStrainer);

    // 3 anillos de refrigeracion / detalle del cuerpo
    for (let i = 0; i < 3; i++) {
        const ring = MeshBuilder.CreateCylinder(`m2Ring_${i}`, {
            height: 0.012,
            diameter: subR * 2 + 0.02,
            tessellation: 18,
        }, scene);
        ring.position = p(subX, subY, subBottom + 0.10 + i * 0.10);
        const rmat = new StandardMaterial(`m2RingMat_${i}`, scene);
        rmat.diffuseColor = new Color3(0.32, 0.34, 0.38);
        rmat.specularColor = new Color3(0.5, 0.5, 0.5);
        ring.material = rmat;
        ring.isPickable = false;
        group.meshes.push(ring);
    }

    // Cable de poder (linea fina del top del pump hasta el cap del rotoplas)
    const m2Cord = MeshBuilder.CreateLines('m2Cord', {
        points: [
            p(subX + 0.04, subY + 0.04, subTop + 0.06),
            p(subX + 0.04, subY + 0.04, cisternaCapTopZ_local),
        ],
    }, scene);
    m2Cord.color = new Color3(0.10, 0.10, 0.12);
    m2Cord.isPickable = false;
    group.meshes.push(m2Cord);

    // Etiqueta M2 (sobre el pump, dentro del agua/cisterna)
    const m2Lbl = createTextLabel(scene, 'm2Lbl', 'M2', applyOverride('m2', [subX, subY, subTop + 0.20]), '#ffffff');
    group.meshes.push(m2Lbl);
}

function buildSolarHeater(scene, group) {
    // Tanque solar (cilindro horizontal eje X)
    const tank = buildHorizontalCylinder(scene, 'solarTank', SOL.cylX0, SOL.cylX1, SOL.y, SOL.cylZ, SOL.cylR, 16, '#2266AA', 0.45);
    group.meshes.push(tank);
    group.dynamic.solarMat = tank.material;

    // Patas
    const legs = [];
    const tankLegX = [SOL.cylX0 + 0.3, SOL.cylX1 - 0.3];
    const tankLegY = [SOL.y - SOL.cylR - 0.05, SOL.y + SOL.cylR + 0.05];
    for (const lx of tankLegX) {
        for (const ly of tankLegY) {
            legs.push([p(lx, ly, SOL.zBase), p(lx, ly, SOL.cylZ - SOL.cylR)]);
        }
        legs.push([p(lx, tankLegY[0], SOL.cylZ-SOL.cylR), p(lx, tankLegY[1], SOL.cylZ-SOL.cylR)]);
    }
    const legMesh = MeshBuilder.CreateLineSystem('solLegs', { lines: legs }, scene);
    legMesh.color = new Color3(0.53, 0.53, 0.53);
    group.meshes.push(legMesh);

    // Panel inclinado
    const panelYtop = SOL.y + SOL.cylR + 0.05;
    const panelYbot = panelYtop + SOL.panelLen;
    const panelZtop = SOL.cylZ - SOL.cylR;
    const panelZbot = SOL.zBase;
    const panel = MeshBuilder.CreateRibbon('solPanel', {
        pathArray: [
            [p(SOL.cylX0, panelYtop, panelZtop), p(SOL.cylX1, panelYtop, panelZtop)],
            [p(SOL.cylX0, panelYbot, panelZbot), p(SOL.cylX1, panelYbot, panelZbot)],
        ],
    }, scene);
    const pm = new StandardMaterial('solPanelMat', scene);
    pm.diffuseColor = new Color3(...parseColor('#2266AA'));
    pm.alpha = 0.5;
    pm.backFaceCulling = false;
    panel.material = pm;
    group.meshes.push(panel);
    group.dynamic.panelMat = pm;

    // Tubos del panel
    const tubes = [];
    for (let tx = SOL.cylX0 + 0.2; tx <= SOL.cylX1 - 0.1; tx += 0.3) {
        tubes.push([p(tx, panelYtop + 0.1, panelZtop - 0.02), p(tx, panelYbot - 0.1, panelZbot + 0.02)]);
    }
    const tubeMesh = MeshBuilder.CreateLineSystem('solTubes', { lines: tubes }, scene);
    tubeMesh.color = new Color3(...parseColor('#CC4400'));
    group.meshes.push(tubeMesh);

    group.dynamic.solarPanel = { yTop: panelYtop, yBot: panelYbot, zTop: panelZtop, zBot: panelZbot };
}

function buildTermo(scene, group) {
    // Termo: cilindro horizontal con tapas hemisfericas + valvula de alivio +
    // 3 bandas de chapa (estilo calentador comercial / pressure vessel).
    const cz = TERMO.z + TERMO.r;

    // Cuerpo cilindrico
    const tank = buildHorizontalCylinder(scene, 'termoTank', TERMO.x0, TERMO.x1, TERMO.y, cz, TERMO.r, 24, '#3377AA', 0.55);
    group.meshes.push(tank);
    group.dynamic.termoMat = tank.material;

    // Tapas hemisfericas en cada extremo (esfera completa, mitad oculta dentro
    // del cilindro). Comparten el material del tanque para color sincronizado.
    for (const [tag, ex] of [['L', TERMO.x0], ['R', TERMO.x1]]) {
        const cap = MeshBuilder.CreateSphere(`termoCap${tag}`, {
            diameter: TERMO.r * 2,
            segments: 20,
        }, scene);
        cap.position = p(ex, TERMO.y, cz);
        cap.material = tank.material;
        cap.isPickable = false;
        group.meshes.push(cap);
    }

    // Bandas de refuerzo / chapa en el cuerpo (3 anillos perpendiculares al eje)
    const bandStep = (TERMO.x1 - TERMO.x0) / 4;
    for (let i = 1; i <= 3; i++) {
        const bx = TERMO.x0 + bandStep * i;
        const band = MeshBuilder.CreateCylinder(`termoBand${i}`, {
            height: 0.04,
            diameter: TERMO.r * 2 + 0.04,
            tessellation: 24,
        }, scene);
        band.rotation.z = Math.PI / 2;
        band.position = p(bx, TERMO.y, cz);
        const bMat = new StandardMaterial(`termoBand${i}Mat`, scene);
        bMat.diffuseColor = new Color3(0.45, 0.55, 0.65);
        bMat.specularColor = new Color3(0.4, 0.4, 0.4);
        band.material = bMat;
        band.isPickable = false;
        group.meshes.push(band);
    }

    // Valvula de alivio / venteo (pequeño tubo vertical sobre el cuerpo)
    const reliefX = (TERMO.x0 + TERMO.x1) / 2;
    const reliefBaseZ = cz + TERMO.r;
    const relief = buildVerticalCylinder(scene, 'termoRelief',
        reliefX, TERMO.y, reliefBaseZ - 0.05, reliefBaseZ + 0.30, 0.04, 12, '#666666', 1);
    group.meshes.push(relief);

    // Cabeza laton de la valvula
    const reliefHead = MeshBuilder.CreateSphere('termoReliefHead', {
        diameter: 0.10,
        segments: 12,
    }, scene);
    reliefHead.position = p(reliefX, TERMO.y, reliefBaseZ + 0.32);
    const rhMat = new StandardMaterial('termoReliefHeadMat', scene);
    rhMat.diffuseColor = new Color3(0.78, 0.55, 0.20);
    rhMat.specularColor = new Color3(0.6, 0.5, 0.3);
    reliefHead.material = rhMat;
    reliefHead.isPickable = false;
    group.meshes.push(reliefHead);

    // Soporte: 4 patas verticales con plato base (atornillado al piso) y
    // conector superior soldado al termo. Color = mismo del termo, asi parecen
    // parte de la estructura, no piezas separadas.
    const legColor  = '#3377AA';   // mismo que el cuerpo del termo
    const baseColor = '#3a4a55';   // gris oscuro para el plato anclado al piso
    const boltColor = '#cccccc';   // pernos plateados
    const legRadius = 0.05;
    const legOffsetY = TERMO.r * 0.75;
    const legXs = [TERMO.x0 + 0.6, TERMO.x1 - 0.6];
    const legYs = [TERMO.y - legOffsetY, TERMO.y + legOffsetY];

    for (const lx of legXs) {
        for (const ly of legYs) {
            const dy = ly - TERMO.y;
            const topZ = cz - Math.sqrt(TERMO.r * TERMO.r - dy * dy);

            // Pata vertical, color del termo (parece soldada al cuerpo)
            const leg = buildVerticalCylinder(scene, `termoLeg_${lx}_${ly}`,
                lx, ly, 0.03, topZ, legRadius, 14, legColor, 1);
            group.meshes.push(leg);

            // Plato base (disco grueso color hierro) anclado al piso
            const base = MeshBuilder.CreateCylinder(`termoLegBase_${lx}_${ly}`, {
                height: 0.03,
                diameter: 0.22,
                tessellation: 16,
            }, scene);
            base.position = p(lx, ly, 0.015);
            const baseMat = new StandardMaterial(`termoLegBaseMat_${lx}_${ly}`, scene);
            const [br, bg, bb] = parseColor(baseColor);
            baseMat.diffuseColor = new Color3(br, bg, bb);
            baseMat.specularColor = new Color3(0.5, 0.5, 0.5);
            base.material = baseMat;
            base.isPickable = false;
            group.meshes.push(base);

            // 4 pernos en el plato (esferas plateadas en posiciones diagonales)
            for (let bi = 0; bi < 4; bi++) {
                const ang = bi * Math.PI / 2 + Math.PI / 4;
                const bx = lx + Math.cos(ang) * 0.085;
                const by = ly + Math.sin(ang) * 0.085;
                const bolt = MeshBuilder.CreateSphere(`termoLegBolt_${lx}_${ly}_${bi}`, {
                    diameter: 0.025,
                    segments: 6,
                }, scene);
                bolt.position = p(bx, by, 0.035);
                const boltMat = new StandardMaterial(`termoLegBoltMat_${lx}_${ly}_${bi}`, scene);
                const [r, g, b] = parseColor(boltColor);
                boltMat.diffuseColor = new Color3(r, g, b);
                boltMat.specularColor = new Color3(0.7, 0.7, 0.7);
                bolt.material = boltMat;
                bolt.isPickable = false;
                group.meshes.push(bolt);
            }

            // Conector superior (disco plano que parece soldadura entre la pata
            // y la curvatura del termo). Mismo color que el termo.
            const top = MeshBuilder.CreateCylinder(`termoLegTop_${lx}_${ly}`, {
                height: 0.025,
                diameter: 0.13,
                tessellation: 14,
            }, scene);
            top.position = p(lx, ly, topZ - 0.012);
            const topMat = new StandardMaterial(`termoLegTopMat_${lx}_${ly}`, scene);
            const [tr, tg, tb] = parseColor(legColor);
            topMat.diffuseColor = new Color3(tr, tg, tb);
            topMat.specularColor = new Color3(0.4, 0.4, 0.4);
            top.material = topMat;
            top.isPickable = false;
            group.meshes.push(top);
        }
    }
}

function buildValvesAndPipes(scene, group) {
    // Tuberias del circuito hidraulico — convertidas a tubos 3D solidos.
    const pipeStart = [1 + 0.5, 0.5 + 0.5, 0.25];
    const pipeEnd   = [9 - 0.5, 5.5 - 0.5, 0.25];

    // Retorno → rotoplas (tubo gris). Termina en la TAPA del rotoplas, no en
    // el cuerpo, ahora que la cisterna tiene hombro conico + tapa encima.
    const cisternaCapTopZ = RP.z1 + 0.13 + 0.10;  // = 2.03 (shoulderH + capH)
    group.meshes.push(buildTubeMR(scene, 'pipeReturn', [
        p(pipeEnd[0]+0.3, pipeEnd[1], 0.5),
        p(0.3, pipeEnd[1], 0.5),
        p(0.3, pipeEnd[1], 2.4),
        p(-1, pipeEnd[1], 2.4),
        p(-1, RP.y, 2.4),
        p(-2, RP.y, 2.4),
        p(RP.x, RP.y, 2.4),
        p(RP.x, RP.y, cisternaCapTopZ),
    ], 0.06, '#999999'));

    // Bomba → solar (naranja). Justo despues de salir de la cisterna hace un
    // quiebre de 90° en -Y bajando a y=RP.y-0.6 (= y=3.4, fuera del plano y=4
    // del pipe gris). Sube vertical, vira a y=3 a la altura del techo, y baja
    // un poco antes de subir al solar — todos los giros son 90°.
    const bombaSalidaX = RP.x + RP.r;
    const bombaY = RP.y - RP.r;  // = 3.4, evita el pipe gris en y=4
    group.meshes.push(buildTubeMR(scene, 'pipeBombaSolar', [
        p(bombaSalidaX, RP.y, 0.3),                  // salida cisterna (flange +X)
        p(bombaSalidaX, bombaY, 0.3),                // 90° → -Y a y=3.4 (curvatura conexion)
        p(bombaSalidaX, bombaY, MR.z1 + 0.1),        // 90° → +Z (riser vertical)
        p(SOL.cylX0, bombaY, MR.z1 + 0.1),           // 90° → -X hacia columna del solar
        p(SOL.cylX0, SOL.y, MR.z1 + 0.1),            // 90° → -Y a y=3 (solar)
        p(SOL.cylX0, SOL.y, SOL.cylZ),               // 90° → +Z entrada solar
    ], 0.05, '#CC6600'));

    // Solar → termo (rojo intenso). Entra por la tapa derecha del termo
    // (dome a x=TERMO.x1 + TERMO.r).
    const termoCenterZ = TERMO.z + TERMO.r;
    const termoRightDomeX = TERMO.x1 + TERMO.r;
    const termoLeftDomeX  = TERMO.x0 - TERMO.r;
    group.meshes.push(buildTubeMR(scene, 'pipeSolarTermo', [
        p(SOL.cylX1, SOL.y, SOL.cylZ),
        p(SOL.cylX1, SOL.y, termoCenterZ),
        p(termoRightDomeX + 0.5, SOL.y, termoCenterZ),
        p(termoRightDomeX + 0.5, TERMO.y, termoCenterZ),
        p(termoRightDomeX, TERMO.y, termoCenterZ),
    ], 0.05, '#CC4400'));

    // Termo → entrada cuarto (azul). Sale por la tapa izquierda del termo.
    group.meshes.push(buildTubeMR(scene, 'pipeTermoEntrada', [
        p(termoLeftDomeX, TERMO.y, termoCenterZ),
        p(termoLeftDomeX, TERMO.y, 2.3),
        p(termoLeftDomeX, 3, 2.3),
        p(-2, 3, 2.3),
        p(-1, 3, 2.3),
        p(0.3, 3, 2.3),
        p(0.3, 3, 0.5),
        p(0.5, 3, 0.5),
    ], 0.06, '#4488BB'));

    // Distribuidor "H" (V1 ↔ V2) en azul
    const v1Y = pipeStart[1];
    group.meshes.push(buildTubeMR(scene, 'pipeDistH', [
        p(0.5, v1Y, 0.5),
        p(0.5, 3, 0.5),
    ], 0.05, '#4488BB'));
    group.meshes.push(buildTubeMR(scene, 'pipeV1Out', [
        p(0.5, v1Y, 0.5),
        p(pipeStart[0]-0.3, pipeStart[1], 0.5),
    ], 0.05, '#4488BB'));

    // Valvulas V1 y V2
    const v1Marker = MeshBuilder.CreatePolyhedron('v1', { type: 1, size: 0.09 }, scene);
    v1Marker.position = p(0.5, v1Y, 0.5);
    const v1Mat = new StandardMaterial('v1mat', scene);
    v1Mat.diffuseColor = new Color3(0.67, 0.67, 0.67);
    v1Marker.material = v1Mat;
    group.meshes.push(v1Marker);
    group.meshes.push(createTextLabel(scene, 'v1Lbl', 'V1', applyOverride('v1', [0.5, v1Y, 0.7]), '#ffffff'));

    const v2Marker = MeshBuilder.CreatePolyhedron('v2', { type: 1, size: 0.09 }, scene);
    v2Marker.position = p(0.5, 3, 0.5);
    const v2Mat = new StandardMaterial('v2mat', scene);
    v2Mat.diffuseColor = new Color3(0.67, 0.67, 0.67);
    v2Marker.material = v2Mat;
    group.meshes.push(v2Marker);
    group.meshes.push(createTextLabel(scene, 'v2Lbl', 'V2', applyOverride('v2', [0.5, 3, 0.7]), '#ffffff'));

    group.dynamic.pipeStart = pipeStart;
    group.dynamic.pipeEnd = pipeEnd;

    // --- Acoples / flanges en uniones tuberia ↔ tanque -----------------------
    // Cilindros cortos perpendiculares al pipe en cada conexion. Imitan los
    // acoples metalicos reales de plomeria.
    // axis 'x' = horizontal Plotly X (cilindros horizontales: solar, termo)
    // axis 'z' = vertical (Plotly Z = Babylon Y, tanque cisterna)
    group.meshes.push(buildFlange(scene, 'flgCisternaTop',  [RP.x, RP.y, cisternaCapTopZ], 'z', 0.10, 0.10));
    group.meshes.push(buildFlange(scene, 'flgCisternaSide', [bombaSalidaX, RP.y, 0.3],       'x', 0.10, 0.08));
    group.meshes.push(buildFlange(scene, 'flgSolarLeft',    [SOL.cylX0, SOL.y, SOL.cylZ],   'x', 0.15, 0.10));
    group.meshes.push(buildFlange(scene, 'flgSolarRight',   [SOL.cylX1, SOL.y, SOL.cylZ],   'x', 0.15, 0.10));
    group.meshes.push(buildFlange(scene, 'flgTermoRight',   [termoRightDomeX, TERMO.y, termoCenterZ], 'x', 0.12, 0.09));
    group.meshes.push(buildFlange(scene, 'flgTermoLeft',    [termoLeftDomeX,  TERMO.y, termoCenterZ], 'x', 0.12, 0.09));
}

export function updateMachineRoom(group, data, scene) {
    const mr = data.machine_room || {};
    const rf = data.radiant_floor || {};

    // Rotoplas color por temperatura1 (Salida)
    const t1 = rf['temperatura1'];
    if (t1 && t1.value !== null) {
        const [r, g, b] = parseColor(tempColor(t1.value));
        group.dynamic.rotoplasMat.diffuseColor.set(r, g, b);
    }

    // Solar color por temperatura2
    const t2 = mr['temperatura2'];
    if (t2 && t2.value !== null) {
        const c = termoScaleColor(t2.value);
        const [r, g, b] = parseColor(c);
        group.dynamic.solarMat.diffuseColor.set(r, g, b);
        group.dynamic.panelMat.diffuseColor.set(r, g, b);
    }

    // Termo color por temperatura5
    const t5 = mr['temperatura5'];
    if (t5 && t5.value !== null) {
        const c = termoScaleColor(t5.value);
        const [r, g, b] = parseColor(c);
        group.dynamic.termoMat.diffuseColor.set(r, g, b);
    }

    // Sensores: TERMO, CALENTADOR, ENTRADA — etiquetas dinamicas
    refreshSensorLabel(scene, group, 'termoSensorLbl',
        t5 && t5.value !== null ? `TERMO: ${t5.value.toFixed(1)}°C` : '',
        applyOverride('termo', [(TERMO.x0+TERMO.x1)/2, TERMO.y, TERMO.z + TERMO.r*2 + 0.25]), '#ffffff');

    refreshSensorLabel(scene, group, 'solSensorLbl',
        t2 && t2.value !== null ? `CALENTADOR: ${t2.value.toFixed(1)}°C` : '',
        applyOverride('calentador', [(SOL.x0+SOL.x1)/2, SOL.y, SOL.cylZ + SOL.cylR + 0.15]), '#ffffff');

    const t4 = mr['temperatura4'];
    refreshSensorLabel(scene, group, 'entradaSensorLbl',
        t4 && t4.value !== null ? `ENTRADA: ${t4.value.toFixed(1)}°C` : '',
        applyOverride('entrada', [group.dynamic.pipeStart[0]-0.3, group.dynamic.pipeStart[1], 0.8]), '#ffffff');
}

function refreshSensorLabel(scene, group, key, text, pos, color) {
    if (group.dynamic[key]) group.dynamic[key].dispose(false, true);
    if (!text) {
        group.dynamic[key] = null;
        return;
    }
    const lbl = createTextLabel(scene, key, text, pos, color);
    group.dynamic[key] = lbl;
    group.meshes.push(lbl);
}

export function setMachineRoomVisibility(group, visible) {
    for (const m of group.meshes) {
        if (m && m.isVisible !== undefined) m.isVisible = visible;
    }
}

/**
 * Acople / flange metalico en una union tuberia-tanque. Cilindro corto
 * perpendicular al pipe en el punto de conexion. axis 'x' = horizontal X
 * Plotly (eje de cilindros horizontales como solar/termo); axis 'z' = vertical
 * Plotly (cisterna). Posicion en sistema Plotly [x, y, z].
 */
function buildFlange(scene, name, plotlyPos, axis, length, radius, color = '#aaaaaa') {
    const f = MeshBuilder.CreateCylinder(name, {
        height: length,
        diameter: radius * 2,
        tessellation: 16,
    }, scene);
    f.position = p(plotlyPos[0], plotlyPos[1], plotlyPos[2]);
    if (axis === 'x') f.rotation.z = Math.PI / 2;
    // axis 'z' / 'y' = vertical, default Babylon (eje Y) — sin rotacion
    const mat = new StandardMaterial(`${name}_mat`, scene);
    const [r, g, b] = parseColor(color);
    mat.diffuseColor = new Color3(r, g, b);
    mat.specularColor = new Color3(0.6, 0.6, 0.6);
    f.material = mat;
    f.isPickable = false;
    return f;
}

/** Construye un tubo 3D solido a partir de un path de Vector3 (helper local). */
function buildTubeMR(scene, name, path, radius, color) {
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
    mat.specularColor = new Color3(0.25, 0.25, 0.25);
    tube.material = mat;
    tube.isPickable = false;
    return tube;
}
