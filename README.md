# Mapa de Calor 3D en Tiempo Real — Node.js + Babylon.js + Agente IA

Aplicacion que combina:
- **Dashboard 3D** (Node.js + Babylon.js) — mapa de calor volumetrico en tiempo real
- **Predictor IA** (Python + GRU + agente conversacional) — forecast +3 min, alertas, chat

Migracion del proyecto original Python/Flask/Plotly, ahora con sidecar de IA.

## Documentación

Toda la documentación detallada vive en **[`docs/`](docs/README.md)**:

- **[Cambios agente IA](docs/AGENTE_IA_CAMBIOS.md)** — agente conversacional, bot Telegram bidireccional, widget de chat, gráficas, detector de saltos
- **[Reportes ejecutivos PDF](docs/REPORTES.md)** — PDFs on-demand y programados con cron, entrega Telegram
- **[Integración dashboard + sidecar](docs/INTEGRATION.md)** — arranque rápido, troubleshooting
- **[Predictor IA](docs/ai-predictor.md)** — modelos GRU, training
- **[Dashboard 3D](docs/node-dashboard.md)** — heatmap volumétrico, MQTT
- **[Instalación servicio Windows](docs/node-scripts-install.md)** — kiosko Chrome, autoarranque

## Stack tecnico

| Capa       | Original (Python)        | Migracion (Node) |
|------------|--------------------------|------------------|
| Servidor   | Flask 3                  | Express 4        |
| MQTT       | paho-mqtt                | mqtt 5           |
| Calculo 3D | scipy.griddata + numpy   | griddata propia (nearest + linear baricentrica con tetraedros) |
| Render 3D  | Plotly.js 2.35           | Babylon.js 7 (CDN) + Marching Cubes inline |
| Logging    | logging + TimedRotatingFileHandler | winston + winston-daily-rotate-file |

## Requisitos

- Node.js 20 LTS o superior
- npm

## Instalacion

```bash
cd tenebrios-node
npm install
cp .env.example .env
# editar .env con tu UBIDOTS_TOKEN y DEVICE_LABEL
```

## Ejecutar

```bash
npm start         # produccion
npm run dev       # con --watch
```

Abrir `http://localhost:5000`.

## Tests

```bash
npm test
```

Cubre interpolacion 3D y parser MQTT.

## Simulacion (pruebas sin Ubidots)

Con un broker MQTT local (Mosquitto):

```bash
# editar .env: MQTT_BROKER=localhost, UBIDOTS_TOKEN=
npm run simulator   # publica datos aleatorios cada 2s
# en otra terminal
npm start
```

## API

| Endpoint                       | Descripcion |
|-------------------------------|-------------|
| `GET /`                       | Dashboard con render 3D Babylon.js |
| `GET /api/config`             | `{refresh_ms}` — intervalo de polling |
| `GET /api/data`               | Datos JSON en tiempo real (mismo schema que el backend Python) |
| `GET /api/history?start&end`  | Historico desde Ubidots HTTP |
| `GET /api/history/interpolate?temps&hums` | Volumen 3D para un timestamp |

El contrato de `/api/data` es **identico** al del backend Python original
(mismas claves, mismo redondeo, misma estructura de `volume_data`).

## Estructura

```
tenebrios-node/
├── src/                     # backend Node
│   ├── config.js            # constantes (replica de config.py)
│   ├── logger.js            # winston con carpetas YYYY-MM
│   ├── mqttClient.js        # cliente MQTT (subscribe-only)
│   ├── interpolation.js     # nearest + linear baricentrica (~scipy.griddata)
│   ├── heatmapEngine.js     # almacen + interpolacion volumetrica
│   ├── ubidotsApi.js        # cliente HTTP historico
│   ├── server.js            # Express con los 4 endpoints
│   └── index.js             # main()
├── public/                  # frontend
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── app.js
│       ├── scene.js         # orquestador Babylon
│       ├── camera.js        # camara ortografica + rotacion horizontal
│       ├── colorScales.js   # paletas TEMP/HUM/termo/amoniaco
│       ├── indicators.js    # termometros, barras, ventilador/extractor
│       ├── history.js       # slider historial
│       └── meshes/
│           ├── labels.js    # texto world-space + cilindros + helpers
│           ├── house.js     # casa, mueble, jardinera, lamparas
│           ├── sensors.js   # diamantes + etiquetas + lineas de caida
│           ├── extZone.js   # zona exterior
│           ├── radiantFloor.js
│           ├── machineRoom.js
│           └── volumeIso.js # marching cubes (5 isosuperficies)
├── tests/
│   ├── interpolation.test.js
│   └── mqttParser.test.js
├── mqttSimulator.js
├── package.json
├── .env.example
└── README.md
```

## Despliegue en Raspberry Pi

```bash
# Instalar Node 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Clonar y configurar
cd /home/spaces/tenebrio-3d-heatmap/tenebrios-node
npm install
cp .env.example .env
# editar .env

# systemd
sudo tee /etc/systemd/system/tenebrio-node.service <<EOF
[Unit]
Description=Tenebrio 3D Heatmap (Node)
After=network.target

[Service]
User=spaces
WorkingDirectory=/home/spaces/tenebrio-3d-heatmap/tenebrios-node
ExecStart=/usr/bin/node src/index.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now tenebrio-node
journalctl -u tenebrio-node -f
```

## Reglas de desarrollo (heredadas del proyecto original)

- **No cambiar la arquitectura**: Sensores → MQTT → Motor → API → Frontend 3D.
- **Contrato JSON** identico al backend Python.
- **Posiciones de sensores** y **dimensiones del cuarto** invariantes.
- El sensor exterior `tex` **no** participa en la interpolacion volumetrica.
- Volumen 3D usa interpolacion equivalente a `scipy.griddata` (nearest + linear).
- Comentarios en **espanol**, variables/funciones en **ingles**.
- Conteo de meshes constante entre frames del mismo modo (placeholders invisibles).
