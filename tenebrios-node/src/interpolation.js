// Modulo de interpolacion volumetrica 3D equivalente a scipy.interpolate.griddata.
//
// Replica el comportamiento de griddata(method='linear') con fallback nearest:
//   1. Calcula NEAREST sobre todos los puntos de la grilla (siempre cubre el volumen).
//   2. Sobre el casco convexo de los sensores conocidos, sustituye por interpolacion
//      LINEAL baricentrica usando una triangulacion en tetraedros candidatos.
// Con un maximo de 5 sensores construimos los C(5,4)=5 tetraedros posibles y para
// cada punto buscamos el primero que lo contenga (coords baricentricas >= 0).
// Esto reproduce el resultado de scipy en este caso particular.

/**
 * Genera N valores equiespaciados entre a y b, equivalente a numpy.linspace.
 */
export function linspace(a, b, n) {
  if (n <= 1) return [a];
  const out = new Array(n);
  const step = (b - a) / (n - 1);
  for (let i = 0; i < n; i++) out[i] = a + i * step;
  return out;
}

/**
 * Construye los arreglos planos grid_x, grid_y, grid_z en el mismo orden que
 * numpy.meshgrid(gz, gy, gx, indexing='ij').ravel('C') — es decir Z mas lento,
 * X mas rapido (flat = ix + nx*(iy + ny*iz)).
 */
export function buildFlatGrid(gx, gy, gz) {
  const nx = gx.length, ny = gy.length, nz = gz.length;
  const total = nx * ny * nz;
  const x = new Float64Array(total);
  const y = new Float64Array(total);
  const z = new Float64Array(total);
  let idx = 0;
  for (let iz = 0; iz < nz; iz++) {
    const zz = gz[iz];
    for (let iy = 0; iy < ny; iy++) {
      const yy = gy[iy];
      for (let ix = 0; ix < nx; ix++) {
        x[idx] = gx[ix];
        y[idx] = yy;
        z[idx] = zz;
        idx++;
      }
    }
  }
  return { x, y, z };
}

/**
 * Determinante 3x3 (filas a, b, c).
 */
function det3(a, b, c) {
  return (
    a[0] * (b[1] * c[2] - b[2] * c[1]) -
    a[1] * (b[0] * c[2] - b[2] * c[0]) +
    a[2] * (b[0] * c[1] - b[1] * c[0])
  );
}

/**
 * Volumen con signo de un tetraedro (4 vertices 3D).
 */
function tetSignedVolume(p0, p1, p2, p3) {
  const a = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
  const b = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
  const c = [p3[0] - p0[0], p3[1] - p0[1], p3[2] - p0[2]];
  return det3(a, b, c) / 6.0;
}

/**
 * Coordenadas baricentricas de un punto p respecto al tetraedro v0..v3.
 * Devuelve [b0, b1, b2, b3] con suma 1. Si el tet es degenerado retorna null.
 */
function barycentric(p, v0, v1, v2, v3) {
  const vol = tetSignedVolume(v0, v1, v2, v3);
  if (Math.abs(vol) < 1e-12) return null;
  const b0 = tetSignedVolume(p, v1, v2, v3) / vol;
  const b1 = tetSignedVolume(v0, p, v2, v3) / vol;
  const b2 = tetSignedVolume(v0, v1, p, v3) / vol;
  const b3 = tetSignedVolume(v0, v1, v2, p) / vol;
  return [b0, b1, b2, b3];
}

/**
 * Interpolacion volumetrica nearest+linear sobre una nube de N sensores.
 *
 * @param {Array<[number,number,number]>} coords - posiciones de sensores.
 * @param {Array<number>} values - valores escalares correspondientes.
 * @param {Float64Array} gridX
 * @param {Float64Array} gridY
 * @param {Float64Array} gridZ
 * @returns {Float64Array} volumen interpolado en cada punto de la grilla.
 */
export function interpolateGrid(coords, values, gridX, gridY, gridZ) {
  const N = gridX.length;
  const K = coords.length;
  const out = new Float64Array(N);

  // 1) Nearest neighbor — cubre todos los puntos.
  for (let i = 0; i < N; i++) {
    const px = gridX[i], py = gridY[i], pz = gridZ[i];
    let bestIdx = 0;
    let bestDist = Infinity;
    for (let k = 0; k < K; k++) {
      const dx = coords[k][0] - px;
      const dy = coords[k][1] - py;
      const dz = coords[k][2] - pz;
      const d = dx * dx + dy * dy + dz * dz;
      if (d < bestDist) { bestDist = d; bestIdx = k; }
    }
    out[i] = values[bestIdx];
  }

  // 2) Linear baricentrica dentro del casco convexo.
  //    Generamos todos los subconjuntos de 4 sensores como tetraedros candidatos.
  if (K >= 4) {
    const tets = [];
    for (let a = 0; a < K - 3; a++) {
      for (let b = a + 1; b < K - 2; b++) {
        for (let c = b + 1; c < K - 1; c++) {
          for (let d = c + 1; d < K; d++) {
            tets.push([a, b, c, d]);
          }
        }
      }
    }

    const eps = 1e-9;
    const p = [0, 0, 0];
    for (let i = 0; i < N; i++) {
      p[0] = gridX[i]; p[1] = gridY[i]; p[2] = gridZ[i];
      for (const tet of tets) {
        const v0 = coords[tet[0]];
        const v1 = coords[tet[1]];
        const v2 = coords[tet[2]];
        const v3 = coords[tet[3]];
        const bc = barycentric(p, v0, v1, v2, v3);
        if (!bc) continue;
        if (bc[0] >= -eps && bc[1] >= -eps && bc[2] >= -eps && bc[3] >= -eps) {
          out[i] =
            bc[0] * values[tet[0]] +
            bc[1] * values[tet[1]] +
            bc[2] * values[tet[2]] +
            bc[3] * values[tet[3]];
          break;
        }
      }
    }
  }

  return out;
}

/**
 * Recorta in-place los valores del array a [min, max].
 */
export function clipInPlace(arr, min, max) {
  for (let i = 0; i < arr.length; i++) {
    if (arr[i] < min) arr[i] = min;
    else if (arr[i] > max) arr[i] = max;
  }
}
