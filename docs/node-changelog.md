# CHANGES — Migracion de Python/Flask/Plotly a Node.js/Express/Babylon.js

Fecha: 2026-04-27. Rama sugerida: `feat/babylon-migration`.

## Archivos creados

### Backend (`tenebrios-node/src/`)
- `config.js` — replica exacta de `backend/config.py` (constantes, sensores, rangos).
- `logger.js` — winston con rotacion diaria en `logs/YYYY-MM/YYYY-MM-DD.log` (replica de `log_config.py`).
- `mqttClient.js` — cliente MQTT subscribe-only + `parseLvMessage` equivalente a `parse_lv_message`.
- `interpolation.js` — `linspace`, `buildFlatGrid` (orden x-mas-rapido) e `interpolateGrid` (nearest + linear baricentrica con tetraedros C(n,4)).
- `heatmapEngine.js` — replica de `heatmap_engine.py` con `update`, `interpolateVolume`, `interpolateHumidityVolume` y los mismos accesores.
- `ubidotsApi.js` — `fetchUbidotsValues` (replica de `_fetch_ubidots_values`).
- `server.js` — Express con `/`, `/api/config`, `/api/data`, `/api/history`, `/api/history/interpolate`. JSON identico al backend Python (mismos redondeos, mismas claves, mismos errores en espanol).
- `index.js` — `main()` que instancia engine + mqtt + servidor con manejo de SIGINT/SIGTERM.

### Frontend (`tenebrios-node/public/`)
- `index.html` — HTML con la misma estructura visual (header, panel lateral, modos, historial, slider, expand movil) y carga Babylon.js 7 + GUI desde CDN.
- `css/styles.css` — estilos extraidos sin cambios visuales del `templates/index.html` original.
- `js/app.js` — polling cada `refresh_ms`, manejo de modos, expand movil, conexion historial.
- `js/scene.js` — orquestador Babylon: `initScene`, `buildScene(data, mode)`, `updateColorbar`.
- `js/camera.js` — `ArcRotateCamera` ortografica con rotacion exclusivamente horizontal (mouse, touch, ArrowLeft/ArrowRight).
- `js/colorScales.js` — `TEMP_COLORSCALE`, `HUMIDITY_COLORSCALE`, `tempColor`, `humidityColor`, `termoScaleColor`, `ammoniaColor`, `calentadorBarColor` (extraidos verbatim).
- `js/indicators.js` — `updateDashboard` + `updateIndicators` (termometros, barras, fan/extractor SVG).
- `js/history.js` — `loadHistory`, `onTimeSlider` con debounce 200ms, `renderHistoryFrame` (ventana 5 min para findClosest).
- `js/meshes/labels.js` — helper `p(x,y,z)` para mapear sistema Plotly→Babylon (Y↔Z), `createTextLabel` con `DynamicTexture` + billboard, `buildHorizontalCylinder`, `buildVerticalCylinder`.
- `js/meshes/house.js` — wireframe casa + techo inclinado + 5 ventanas + puerta + extractor + mueble + jardinera + 2 lamparas vintage.
- `js/meshes/sensors.js` — 6 marcadores diamante (t1..t5 + tex) + etiquetas nombre/valor + lineas de caida.
- `js/meshes/extZone.js` — plano vertical para la zona exterior (placeholder invisible cuando no hay valor).
- `js/meshes/radiantFloor.js` — losa, aislamiento, serpentin, malla de refuerzo, derivacion, sensores T1 SALIDA y T3 MEDIO.
- `js/meshes/machineRoom.js` — wireframe sala + corredor, rotoplas, calentador solar (tanque + panel + tubos + patas), termo (con soportes U), tuberias, valvulas V1/V2, sensores TERMO/CALENTADOR/ENTRADA, etiqueta "SALA DE MAQUINAS".
- `js/meshes/volumeIso.js` — implementacion completa de Marching Cubes (Edge + Tri Tables) con pool de 5 meshes reutilizables (no `dispose`/`new` cada frame). Genera 5 isosuperficies por nivel del volumen, opacidad 0.35.

### Tests (`tenebrios-node/tests/`)
- `interpolation.test.js` — port de `test_interpolation.py` (vitest).
- `mqttParser.test.js` — port de `test_mqtt_parser.py` (vitest).

### Otros
- `mqttSimulator.js` — replica de `mqtt_simulator.py`.
- `package.json` — dependencias express, mqtt, dotenv, winston, winston-daily-rotate-file + devDep vitest.
- `.env.example`, `.gitignore`.
- `README.md` — instrucciones de instalacion, ejecucion, tests, simulacion, despliegue Raspberry Pi (systemd).

## Archivos NO modificados

El backend Python original queda intacto en `backend/` y `templates/`. Esto
permite validar el JSON de `/api/data` lado a lado con `curl` antes de retirar
la version Python.

## Decisiones tecnicas relevantes

1. **Interpolacion lineal**: implementada por enumeracion de tetraedros C(K,4) sobre los K sensores conocidos. Para K=5 son 5 tetraedros. La cobertura del casco convexo es identica al algoritmo de scipy.griddata para este caso.
2. **Marching Cubes**: implementacion inline con tablas estandar (Paul Bourke). Pool de 5 meshes reutilizables — no se hace `dispose`/`new` por frame, solo `vertexData.applyToMesh` (regla 14 del proyecto).
3. **Sistema de coordenadas**: Babylon usa Y como eje vertical. Se introdujo el helper `p(x_plotly, y_plotly, z_plotly) → Vector3(x, z, y)` para portar coordenadas sin reordenarlas en cada uso.
4. **Texto world-space**: planos con `DynamicTexture` + `billboardMode = BILLBOARDMODE_ALL`. Tamanos en pixeles fijos en la textura; no escalan con el zoom — equivalente al fix de la regla 13 del proyecto.
5. **Conteo de meshes constante**: cada modo activa/desactiva grupos completos via `setVisibility`; los marcadores sin datos quedan en `scaling=0` para no romper el conteo.

## Riesgos / divergencias conocidas

- **Marching Cubes vs isosurface de Plotly**: Plotly usa su propio render volumetrico interno; Babylon recibe triangulos crudos. La apariencia es equivalente en cantidad de capas y opacidad, pero no es pixel-identica.
- **Etiquetas world-space**: posiciones aproximadas; ajustar offsets si el tamano del texto en pantalla varia respecto al original.
- **Geometria del distribuidor "H" de la sala de maquinas**: la version Node simplifica algunos trazados cosmeticos (tapas redondas, etiquetas decorativas) sin afectar funcionalidad ni datos.

## Criterios de aceptacion (a validar en QA)

- [ ] `/api/data` y endpoints retornan JSON identico al backend Python (curl side-by-side).
- [ ] Los 5 modos (full-temp, full-hum, temp, humidity, floor) funcionan.
- [ ] Las isosuperficies se renderizan con las 5 capas y la colorscale correcta.
- [ ] Termometros, barras y fan/extractor muestran los mismos valores y colores.
- [ ] Slider de historial carga y reproduce frames con interpolacion del lado del servidor.
- [ ] La camara solo rota horizontalmente (mouse, touch, flechas).
- [ ] El sistema arranca con `node src/index.js` y queda escuchando en :5000.
- [ ] `npm test` pasa.
