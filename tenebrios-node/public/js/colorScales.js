// Colorscales y funciones de color extraidas verbatim del frontend Plotly original.
// Mantienen los mismos rangos, mismos colores y misma interpolacion para preservar
// la equivalencia visual del render.

// Temperatura: azul (frio) -> verde (ideal 20-30) -> rojo (caliente). VMIN=14, VMAX=35.
export const TEMP_COLORSCALE = [
    [0,    'rgb(0,0,200)'],
    [0.1,  'rgb(0,80,255)'],
    [0.2,  'rgb(0,180,220)'],
    [0.3,  'rgb(0,210,140)'],
    [0.4,  'rgb(0,200,0)'],
    [0.5,  'rgb(140,220,0)'],
    [0.6,  'rgb(255,220,0)'],
    [0.75, 'rgb(255,140,0)'],
    [0.9,  'rgb(220,40,0)'],
    [1,    'rgb(160,0,0)'],
];

// Humedad: azul fuerte -> azul claro -> verde -> naranja -> rojo (0..100%).
export const HUMIDITY_COLORSCALE = [
    [0,    'rgb(0,40,220)'],
    [0.4,  'rgb(0,200,255)'],
    [0.6,  'rgb(0,200,100)'],
    [0.7,  'rgb(0,220,0)'],
    [0.8,  'rgb(0,200,0)'],
    [0.9,  'rgb(220,160,0)'],
    [1,    'rgb(220,40,0)'],
];

/** Interpola un color a lo largo de una colorscale en t normalizado [0,1]. */
export function interpolateColorscale(colorscale, t) {
    t = Math.max(0, Math.min(1, t));
    let i = 0;
    for (; i < colorscale.length - 1; i++) {
        if (t <= colorscale[i + 1][0]) break;
    }
    const [t0, c0] = colorscale[i];
    const [t1, c1] = colorscale[Math.min(i + 1, colorscale.length - 1)];
    const p = t1 > t0 ? (t - t0) / (t1 - t0) : 0;
    const parse = (s) => s.match(/\d+/g).map(Number);
    const [r0, g0, b0] = parse(c0);
    const [r1, g1, b1] = parse(c1);
    const r = Math.round(r0 + p * (r1 - r0));
    const g = Math.round(g0 + p * (g1 - g0));
    const b = Math.round(b0 + p * (b1 - b0));
    return `rgb(${r},${g},${b})`;
}

/** Devuelve [r,g,b] como floats 0..1, util para BABYLON.Color3. */
export function rgbToColor3(rgbStr) {
    const [r, g, b] = rgbStr.match(/\d+/g).map(Number);
    return [r / 255, g / 255, b / 255];
}

/** Color de temperatura segun TEMP_COLORSCALE (rango 14..35). */
export function tempColor(value) {
    const t = (value - 14) / (35 - 14);
    return interpolateColorscale(TEMP_COLORSCALE, t);
}

/** Color de humedad (rango 0..100). */
export function humidityColor(value) {
    return interpolateColorscale(HUMIDITY_COLORSCALE, value / 100);
}

/** Escala especial para termo y calentador (15..90 C). */
export function termoScaleColor(value) {
    const v = Math.max(15, Math.min(90, value));
    let r, g, b;
    if (v < 25) { r = 0; g = 60; b = 220; }
    else if (v < 40) { const p = (v - 25) / 15; r = 0; g = Math.round(60 + p * 140); b = 220; }
    else if (v < 55) { const p = (v - 40) / 15; r = 0; g = 200; b = Math.round(220 - p * 220); }
    else if (v < 70) { const p = (v - 55) / 15; r = Math.round(p * 255); g = Math.round(200 - p * 60); b = 0; }
    else { const p = (v - 70) / 20; r = 220; g = Math.round(Math.max(40, 140 - p * 100)); b = 0; }
    return `rgb(${r},${g},${b})`;
}

/** Color de amoniaco: 0-1 verde, 1-2 amarillo, 2-3 naranja, >3 rojo. */
export function ammoniaColor(value) {
    const a = Math.max(0, Math.min(5, value));
    let r, g, b;
    if (a <= 1) { r = 0; g = 200; b = 0; }
    else if (a <= 2) { const p = a - 1; r = Math.round(p * 240); g = Math.round(200 + p * 20); b = 0; }
    else if (a <= 3) { const p = a - 2; r = Math.round(240 - p * 20); g = Math.round(220 - p * 180); b = 0; }
    else { r = 220; g = 40; b = 0; }
    return `rgb(${r},${g},${b})`;
}

/** Color especial del calentador en barra horizontal (30..90 C). */
export function calentadorBarColor(cv) {
    if (cv < 30) return 'rgb(0,60,220)';
    if (cv < 45) return 'rgb(0,' + Math.round(60 + ((cv - 30) / 15) * 140) + ',220)';
    if (cv < 60) return 'rgb(0,200,' + Math.round(220 - ((cv - 45) / 15) * 220) + ')';
    if (cv < 75) return 'rgb(' + Math.round(((cv - 60) / 15) * 255) + ',' + Math.round(200 - ((cv - 60) / 15) * 60) + ',0)';
    return 'rgb(220,' + Math.round(140 - ((cv - 75) / 15) * 100) + ',0)';
}
