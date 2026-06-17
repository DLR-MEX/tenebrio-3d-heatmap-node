// =============================================================================
// AJUSTES MANUALES DE POSICIONES DE ETIQUETAS (modo desarrollo)
// -----------------------------------------------------------------------------
// Edita los valores aqui para mover etiquetas a gusto sin tocar el resto del
// codigo. Sistema de coordenadas Plotly del proyecto:
//   x = horizontal (0..10),  y = profundidad (0..6),  z = vertical (0..3)
//
// Para activar un override, reemplaza `null` por { x: ?, y: ?, z: ? }
// Ejemplo:    t4: { x: 3.0, y: 3.0, z: 2.72 },
// Para regresar al valor calculado por el codigo, deja `null`.
// =============================================================================

export const LABEL_OVERRIDES = {
    // --- Sensores del cuarto (etiqueta combinada "NOMBRE : VALOR") -----------
    t1:  null,
    t2:  null,
    t3:  null, 
    t4:  null,
    t5:  null,
    tex: null,   // EXTERIOR

    // --- Piso radiante --------------------------------------------------------
    rf_t1: null,   // "T1 SALIDA"
    rf_t3: null,   // "T3 MEDIO"

    // --- Sala de maquinas -----------------------------------------------------
    m2:         null,   // bomba M2
    v1:         null,   // valvula V1
    v2:         null,   // valvula V2
    termo:      null,   // "TERMO: XX.X°C"
    calentador: null,   // "CALENTADOR: XX.X°C"
    entrada:    null,   // "ENTRADA: XX.X°C"
};

/**
 * Devuelve la posicion override si esta definida; sino, la default.
 * @param {string} key      clave en LABEL_OVERRIDES
 * @param {[number,number,number]} defaultPos  fallback en sistema Plotly [x,y,z]
 * @returns {[number,number,number]}
 */
export function applyOverride(key, defaultPos) {
    const ov = LABEL_OVERRIDES[key];
    if (ov && typeof ov === 'object'
        && Number.isFinite(ov.x) && Number.isFinite(ov.y) && Number.isFinite(ov.z)) {
        return [ov.x, ov.y, ov.z];
    }
    return defaultPos;
}
