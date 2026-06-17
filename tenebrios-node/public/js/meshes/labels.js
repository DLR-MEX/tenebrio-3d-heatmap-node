// Utilidades para crear etiquetas de texto en world-space estables (no escalan
// con el zoom). Usan un Plane + DynamicTexture orientado al usuario via billboardMode.
// Equivalente al "scatter3d mode:'text'" de Plotly del frontend original.

const { Color3, Color4, Mesh, MeshBuilder, Vector3, StandardMaterial, DynamicTexture } = BABYLON;

/**
 * Convierte coordenadas del sistema Plotly original (X horizontal, Y profundidad,
 * Z vertical) al sistema Babylon (X horizontal, Y vertical, Z profundidad).
 * Permite copiar las coordenadas del frontend Plotly sin transformaciones manuales.
 */
export function p(x, y, z) {
    return new Vector3(x, z, y);
}

/** Variante que devuelve un array [x, y, z] en el sistema Babylon. */
export function pa(x, y, z) {
    return [x, z, y];
}

// Tamano del texto en metros del mundo 3D. Reducido para evitar empalme con los
// marcadores de los sensores y mantener proporcion respecto al cuarto.
const PLANE_HEIGHT = 0.35;
const TEXTURE_HEIGHT = 70;

/** Crea una etiqueta de texto estilo Arial Black, color blanco por defecto. */
export function createTextLabel(scene, name, text, position, color = '#ffffff', size = TEXTURE_HEIGHT, hPlane = PLANE_HEIGHT) {
    const fontFamily = 'Arial Black, monospace';
    const fontPx = Math.round(size * 0.7);

    // Medir ancho del texto para dimensionar el plano
    const tmpCanvas = document.createElement('canvas');
    const ctx = tmpCanvas.getContext('2d');
    ctx.font = `bold ${fontPx}px ${fontFamily}`;
    const metrics = ctx.measureText(text);
    const textWidth = Math.max(64, Math.ceil(metrics.width) + 12);
    const textureWidth = nextPow2(textWidth);

    const aspect = textureWidth / size;
    const planeWidth = hPlane * aspect;

    const plane = MeshBuilder.CreatePlane(name, { width: planeWidth, height: hPlane }, scene);
    // position llega en sistema Plotly [x horizontal, y profundidad, z vertical].
    // Convertir a Babylon: X horizontal, Y=z vertical (arriba), Z=y profundidad.
    plane.position = new Vector3(position[0], position[2], position[1]);
    plane.billboardMode = Mesh.BILLBOARDMODE_ALL;

    const texture = new DynamicTexture(`${name}_tex`, { width: textureWidth, height: size }, scene, false);
    texture.hasAlpha = true;
    const tctx = texture.getContext();
    tctx.clearRect(0, 0, textureWidth, size);
    tctx.fillStyle = 'rgba(0,0,0,0)';
    tctx.fillRect(0, 0, textureWidth, size);
    tctx.font = `bold ${fontPx}px ${fontFamily}`;
    tctx.textAlign = 'center';
    tctx.textBaseline = 'middle';
    tctx.strokeStyle = 'rgba(0, 0, 0, 0.8)';
    tctx.lineWidth = 4;
    tctx.strokeText(text, textureWidth / 2, size / 2);
    tctx.fillStyle = color;
    tctx.fillText(text, textureWidth / 2, size / 2);
    texture.update();

    const mat = new StandardMaterial(`${name}_mat`, scene);
    mat.diffuseTexture = texture;
    mat.opacityTexture = texture;
    mat.emissiveColor = Color3.White();
    mat.disableLighting = true;
    mat.backFaceCulling = false;
    plane.material = mat;
    plane.isPickable = false;

    return plane;
}

function nextPow2(n) {
    let p = 1;
    while (p < n) p *= 2;
    return p;
}

/** Crea un cilindro horizontal con eje en X (sistema Plotly: pies sobre Y/Z).
 *  Coords de entrada: (x0, x1) en X, cy en Y-Plotly, cz en Z-Plotly. */
export function buildHorizontalCylinder(scene, name, x0, x1, cy, cz, radius, segments, color, opacity) {
    const cyl = MeshBuilder.CreateCylinder(name, {
        height: x1 - x0,
        diameter: radius * 2,
        tessellation: segments,
    }, scene);
    // CreateCylinder genera cilindro a lo largo de Y. Rotamos para alinearlo con X.
    cyl.rotation.z = Math.PI / 2;
    // Posicion en Babylon: X centro, Y=cz (vertical), Z=cy (profundidad)
    cyl.position.set((x0 + x1) / 2, cz, cy);
    const mat = new StandardMaterial(`${name}_mat`, scene);
    const [r, g, b] = parseColor(color);
    mat.diffuseColor = new Color3(r, g, b);
    mat.alpha = opacity;
    mat.specularColor = new Color3(0.1, 0.1, 0.1);
    cyl.material = mat;
    return cyl;
}

/** Crea un cilindro vertical (eje Z-Plotly). cx,cy estan en Plotly. */
export function buildVerticalCylinder(scene, name, cx, cy, z0, z1, radius, segments, color, opacity) {
    const cyl = MeshBuilder.CreateCylinder(name, {
        height: z1 - z0,
        diameter: radius * 2,
        tessellation: segments,
    }, scene);
    // Eje Y de Babylon = vertical = Z-Plotly. No requiere rotacion.
    cyl.position.set(cx, (z0 + z1) / 2, cy);
    const mat = new StandardMaterial(`${name}_mat`, scene);
    const [r, g, b] = parseColor(color);
    mat.diffuseColor = new Color3(r, g, b);
    mat.alpha = opacity;
    cyl.material = mat;
    return cyl;
}

/** Convierte 'rgb(r,g,b)' o '#RRGGBB' a [r,g,b] en 0..1. */
export function parseColor(c) {
    if (typeof c !== 'string') return [0.5, 0.5, 0.5];
    if (c.startsWith('#')) {
        const h = c.slice(1);
        return [
            parseInt(h.slice(0, 2), 16) / 255,
            parseInt(h.slice(2, 4), 16) / 255,
            parseInt(h.slice(4, 6), 16) / 255,
        ];
    }
    const m = c.match(/\d+(\.\d+)?/g);
    if (!m) return [0.5, 0.5, 0.5];
    return [Number(m[0]) / 255, Number(m[1]) / 255, Number(m[2]) / 255];
}

/** Convierte 'rgb(r,g,b)' a Color3. */
export function toColor3(c) {
    const [r, g, b] = parseColor(c);
    return new Color3(r, g, b);
}

/** Convierte 'rgb(r,g,b)' a Color4 con alpha. */
export function toColor4(c, alpha = 1) {
    const [r, g, b] = parseColor(c);
    return new Color4(r, g, b, alpha);
}
