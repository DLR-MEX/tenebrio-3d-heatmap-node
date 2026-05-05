# 🪲 Tenebris AI Sentinel - Documentación de Modelos Predictivos

Bienvenido al repositorio de **Tenebris AI Sentinel**, el núcleo de Inteligencia Artificial diseñado para la predicción, monitoreo y control automatizado de microclimas en cuartos de cría de *Tenebrio*.

Este documento explica la arquitectura de los modelos de Deep Learning utilizados, su proceso de entrenamiento y cómo el equipo de pruebas (Space) puede utilizar el cuaderno de Jupyter proporcionado para evaluar nuevos conjuntos de datos.

---

## 🧠 1. ¿Qué son estos modelos?

El sistema no utiliza un solo modelo, sino una **Arquitectura Dual** basada en Redes Neuronales Recurrentes (RNN), específicamente **GRU (Gated Recurrent Units)**. Las redes GRU son ideales para series temporales porque tienen "memoria" a corto y largo plazo.

Se dividió el problema en dos cerebros independientes para evitar que la IA confunda la inercia térmica (lenta) con los cambios de humedad (rápidos):
1.  **Modelo de Temperatura (`model_t.keras`):** Vigila 6 variables simultáneas (T1, T2, T3, T4, T5, Tex).
2.  **Modelo de Humedad (`model_h.keras`):** Vigila 6 variables simultáneas (H1, H2, H3, H4, H5, Hex).

Junto a cada modelo, existe un **Escalador Matemático** (`scaler_t.save` y `scaler_h.save`) que normaliza los datos (los convierte a valores entre 0 y 1) para que la red neuronal pueda procesarlos rápidamente y luego los devuelve a sus valores reales (grados o porcentajes).

---

## 📈 2. ¿Cómo se entrenaron y qué logran? (El Secreto Predictivo)

Los modelos fueron entrenados utilizando dos datasets históricos (`DATASET_TEMPERATURA.csv` y `DATASET_HUMEDAD.csv`). 

### El Problema del "Sesgo Ingenuo" (Naive Forecast Bias)
Normalmente, si entrenas a una IA en un cuarto donde la temperatura casi no cambia (ej. siempre a 24°C), la IA se vuelve "perezosa" y descubre que la forma de tener menos errores matemáticos es simplemente repetir el último número que vio. Esto provoca que la gráfica de predicción sea idéntica a la real, pero desfasada hacia la derecha.

### La Solución: Predicción Diferencial (Δ)
Para evitar esto y lograr que los modelos **realmente se anticipen al futuro**, no se les enseñó a adivinar el valor absoluto (ej. adivinar "25°C"). Se les enseñó a adivinar el **cambio (Δ)**.
* **Ventana de Observación (Look Back):** La IA observa los últimos 30 minutos de datos de todos los sensores.
* **Salto Predictivo (Step Ahead):** Intenta calcular cómo *cambiará* el valor dentro de 3 minutos en el futuro.
* **Ejemplo:** La IA no dice "Harán 28°C", sino "La tendencia marca que la temperatura **subirá +0.5°C** en los próximos 3 minutos". Ese cambio se suma al valor actual para obtener la gráfica predictiva final.

**¿Qué logran?** Permiten que el sistema se adelante al desastre. Si el modelo detecta que la curva de subida es agresiva, avisará que el límite óptimo (30°C) se romperá en 3 minutos, permitiendo que el Agente de OpenAI (LangGraph) ordene encender los ventiladores antes de que los insectos sufran estrés térmico.

---

## 💻 3. Explicación del Código de Prueba (Jupyter Notebook)

Para que el equipo de pruebas pueda validar la precisión de la IA sin montar el servidor de WebSockets, se creó un script estático (Batch Prediction) para Jupyter Notebook.

### ¿Qué hace el código internamente?
1.  **Carga Masiva:** Lee un archivo CSV nuevo por completo.
2.  **Ventaneo Rápido:** Corta el archivo en bloques de 30 minutos usando bucles optimizados.
3.  **Predicción por Lotes (Batching):** En lugar de predecir minuto a minuto, le pasa todos los miles de bloques a la tarjeta gráfica/procesador de un solo golpe (`batch_size=128`), lo que reduce el tiempo de análisis de horas a un par de segundos.
4.  **Cálculo Delta:** Suma las predicciones de cambio (Δ) a los valores reales correspondientes.
5.  **Renderizado Múltiple:** Genera un lienzo (Matplotlib) con 6 gráficas separadas donde superpone la línea de tiempo real (Azul) con la línea punteada de predicción (Rojo).

---

## 🚀 4. Guía de Uso Rápido para el Equipo

Para realizar pruebas estáticas con nuevos datasets, sigan estos pasos:

### Preparación del Entorno
1. Creen una carpeta para sus pruebas.
2. Dentro, creen una subcarpeta llamada `models/`.
3. Peguen dentro de `models/` los 4 archivos de la IA:
   * `model_t.keras`
   * `scaler_t.save`
   * `model_h.keras`
   * `scaler_h.save`
4. Abran su cuaderno de Jupyter en la raíz de la carpeta principal.

### Ejecución
1. En la **primera celda** de su Jupyter Notebook, copien, peguen y ejecuten el bloque de código base que contiene las funciones.
2. En una **nueva celda**, utilicen los comandos simplificados pasando la ruta de su archivo CSV de prueba:

```python
# Para probar un archivo de Temperaturas
prediccion_temperaturas("ruta/a/sus/datos/NUEVAS_TEMPERATURAS.csv")

# Para probar un archivo de Humedades
prediccion_humedades("ruta/a/sus/datos/NUEVAS_HUMEDADES.csv")
```

---

## 📡 5. Modo Tiempo Real (MQTT Ubidots)

Para validar la IA contra datos reales que ya están publicándose en Ubidots, usa el script `realtime_predictor.py`. Se suscribe al broker MQTT, mantiene la ventana deslizante de 30 muestras y emite la predicción a +3 minutos en cuanto se llena el buffer.

### Configuración

1. Crea y activa un entorno virtual:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   # source .venv/bin/activate     # Linux / macOS
   pip install -e .
   ```
2. Copia el archivo de ejemplo y rellena tus credenciales:
   ```bash
   cp .env.example .env
   ```
   Variables clave en `.env`:
   - `UBIDOTS_TOKEN` → token de tu cuenta Ubidots.
   - `UBIDOTS_DEVICE_LABEL` → label del device (no el nombre).
   - `UBIDOTS_PORT` → `1883` plano o `8883` con `UBIDOTS_TLS=true`.
   - `PUBLISH_PREDICTIONS` → si `true`, republica las predicciones a Ubidots como variables `{var}_pred`.

3. El device en Ubidots debe exponer las 12 variables con estos labels exactos (minúsculas):
   - Temperatura: `t1`, `t2`, `t3`, `t4`, `t5`, `tex`
   - Humedad: `h1`, `h2`, `h3`, `h4`, `h5`, `hex`

### Ejecución

```bash
python realtime_predictor.py
```

El script:
1. Se conecta al broker MQTT y se suscribe a todas las variables del device.
2. Va llenando dos buffers (temperatura y humedad). Verás logs `buffer N/30` mientras se llena.
3. Al alcanzar 30 muestras imprime una tabla con `Sensor | Actual | Predicho | Δ`.
4. Si `PUBLISH_PREDICTIONS=true`, además publica cada predicción de vuelta como `{var}_pred` en el mismo device.

Detén con `Ctrl+C` (cierre limpio).

---

## 🖥️ 6. Dashboard Live (FastAPI + SSE)

El mismo servicio expuesto en una UI dark, con cards por sensor (real, predicción +3min, delta y sparkline) y dos charts overlay (real vs predicho).

### Ejecución

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abre `http://localhost:8000`. La UI se conecta vía Server-Sent Events a `/api/stream` y se actualiza en cada nueva predicción sin refrescar.

### Endpoints disponibles

| Método | Path | Descripción |
|--------|------|-------------|
| `GET`  | `/` | Dashboard HTML |
| `GET`  | `/api/state` | Snapshot JSON (estado actual + última predicción + history) |
| `GET`  | `/api/stream` | SSE: emite `snapshot` al conectar y `update` por cada nueva predicción |
| `GET`  | `/healthz` | Liveness simple |

### Variables `.env` específicas
- `APP_HOST` / `APP_PORT` — bind del servidor (defaults: `0.0.0.0:8000`).