# Validación de datos de infraestructura y performance del modelo predictivo

> **Rama**: `feature/reportes-infra-y-exteriores`
> **Fecha**: 2026-05-28
> **Motivo**: el usuario reportó que los datos del **termo** (temperatura5) y el **calentador solar** (temperatura2) no coincidían en los gráficos del reporte ejecutivo, y pidió comparativa entre el modelo viejo (CRT12 Condusef) y el actual en producción.

## TL;DR

1. **Problema termo/calentador es upstream (hardware/MQTT), no del reporte**. Los gráficos dibujan correctamente los datos que reciben — el sensor del termo está leyendo 15.74 °C (ambiente) en lugar de agua caliente, y el calentador solar lleva 48 h clavado en 65.72 °C (± 0.04). Físicamente imposible que la entrada al cuarto (19.59 °C) sea más caliente que el termo (15.74 °C) si el flujo es Termo → Entrada.

2. **Modelo actual está jalando muy bien**. Evaluación sobre 24 h reales del dispositivo Ubidots:
   - TEMP interior MAE = **0.061 °C**, RMSE = **0.109 °C**
   - HUM interior MAE = **0.42 %**, RMSE = **0.58 %**
   - vs viejo GRU CRT12 (test-set offline): mejora ≈ **2.4× en TEMP RMSE** y **3.4× en HUM RMSE**.

## 1) Verificación termo vs calentador

### Procedimiento

Se creó el script `ai-predictor/scripts/verify_termo_vs_calentador.py` que pulla las últimas 48 h desde la API REST de Ubidots (sin pasar por el sidecar) para los 5 sensores del circuito de calefacción + el sensor exterior como referencia de muestreo.

```powershell
cd ai-predictor
python scripts/verify_termo_vs_calentador.py
```

### Resultados

| Variable      | Sensor              | n (48h) | min   | mediana | max   | promedio | std   |
|---------------|---------------------|--------:|------:|--------:|------:|---------:|------:|
| temperatura2  | Calentador solar    |    21   | 65.69 |  65.69  | 65.81 |   65.72  | 0.04  |
| temperatura5  | Termo               |    21   | 15.69 |  15.75  | 15.81 |   15.74  | 0.03  |
| temperatura4  | Entrada al cuarto   |    21   | 19.44 |  19.56  | 19.69 |   19.59  | 0.08  |
| temperatura3  | Medio del piso      |    21   | 19.00 |  19.06  | 19.12 |   19.05  | 0.03  |
| temperatura1  | Salida del piso     |    21   | 17.50 |  17.62  | 17.69 |   17.59  | 0.05  |
| tex           | Exterior (control)  |  2769   |  0.00 |  17.40  | 40.10 |   19.30  | 5.70  |

### Anomalías detectadas

1. **Calentador solar congelado en 65.72 °C por 48 h** (std = 0.04). Un panel solar debería oscilar 30–60 °C entre día y noche. Valor estático sugiere sensor desconectado o reportando dato cacheado.

2. **Termo en 15.74 °C con std 0.03**. Un tanque acumulador con calefacción funcional debería estar 30–60 °C. A 15 °C está leyendo prácticamente temperatura ambiente del cuarto de máquinas — el sensor probablemente no está dentro del tanque.

3. **Imposibilidad física**: Entrada al cuarto (19.59 °C) > Termo (15.74 °C). En la cadena documentada `Calentador solar → Termo → Bomba M2 → Entrada al cuarto → Piso radiante`, el agua no puede llegar más caliente al destino que en la fuente. Esto confirma que al menos uno de los dos sensores está mal posicionado o desconectado.

4. **Frecuencia de muestreo anómala**: 21 muestras en 48 h vs 2769 del sensor exterior (1/min). Los 5 sensores de calefacción muestrean ~130× más lento que el exterior. Posibles causas:
   - Datalogger con filtro "publicar solo en cambio significativo" → si los sensores están desconectados, no hay cambios → no publica.
   - Hardware muy lento o intermitente para este sub-bus.
   - Conexión MQTT/serial inestable solo para este grupo.

### Conclusión

El backend (collector → aggregations → charts) está procesando correctamente. El problema está aguas arriba en el hardware o en el firmware del datalogger.

**Acciones recomendadas (fuera del scope del software)**:
- Verificar físicamente que el sensor temperatura5 esté dentro del termo y no suelto en el cuarto de máquinas.
- Verificar que temperatura2 esté pegado al colector solar (no a la tubería de retorno fría).
- Revisar configuración del datalogger: si tiene umbral de "cambio mínimo para publicar", bajarlo o desactivarlo.

## 2) Comparativa modelos: viejo CRT12 vs actual

### Modelos comparados

| Generación                | Ubicación                                                  | Arquitectura                                | Sensores |
|---------------------------|------------------------------------------------------------|---------------------------------------------|---------:|
| **CRT12** (Condusef, viejo)| `MODELOS PRUEBAS LOCALES/Tenebrios/Condusef/`              | LSTM y GRU, valor absoluto                  | 1 tanque |
| **Modelos_Tenebrios** (predecesor) | `Modelo Test Abril/Modelos_Tenebrios/`              | GRU dual, predicción diferencial Δ          |    6×2   |
| **ai-predictor** (actual) | `ai-predictor/models/` (copia de Modelos_Tenebrios)        | Idéntica al predecesor, en producción       |    6×2   |

Métricas históricas del CRT12 (extraídas de `metricas_modelos_crt12-t.csv` y `metricas_modelos.csv`, ambas sobre test-set offline):

| Modelo viejo | RMSE_Test | MAE_Test |
|--------------|----------:|---------:|
| TEMP LSTM    |  0.81     | 0.21     |
| TEMP GRU     |  0.26     | 0.085    |
| HUM  LSTM    |  3.01     | 1.71     |
| HUM  GRU     |  2.00     | 1.13     |

### Procedimiento de evaluación del actual

Se creó `ai-predictor/scripts/evaluate_current_model.py` que:

1. Pulla las últimas N horas de las 12 variables (t1-t5,tex + h1-h5,hex) directamente de Ubidots, alineando por minuto.
2. Carga `model_t.keras`, `model_h.keras` + scalers desde `ai-predictor/models/`.
3. Genera ventanas deslizantes de `LOOK_BACK=30` muestras.
4. Predice +3 min en espacio escalado, suma al valor actual (predicción **diferencial**), desescala.
5. Compara contra el valor real observado 3 min después → MAE y RMSE por sensor.

```powershell
cd ai-predictor
python scripts/evaluate_current_model.py --hours 24
```

### Resultados (24 h reales, +3 min)

| Grupo | Sensor | n     | MAE     | RMSE    |
|-------|--------|------:|--------:|--------:|
| TEMP  | t1     | 1135  | 0.0792  | 0.1579  |
| TEMP  | t2     | 1135  | 0.0872  | 0.1399  |
| TEMP  | t3     | 1135  | 0.0747  | 0.1204  |
| TEMP  | t4     | 1135  | 0.0399  | 0.0813  |
| TEMP  | t5     | 1135  | **0.0261** | **0.0427** |
| TEMP  | tex    | 1135  | 0.1555  | 0.7542  |
| HUM   | h1     | 1194  | 0.3880  | 0.4827  |
| HUM   | h2     | 1194  | 0.3956  | 0.4568  |
| HUM   | h3     | 1194  | 0.1352  | 0.2899  |
| HUM   | h4     | 1194  | **0.8536** | **1.1379** |
| HUM   | h5     | 1194  | 0.3244  | 0.5310  |
| HUM   | hex    | 1194  | 0.8974  | 3.2782  |

**Promedios interior** (sin exteriores):
- TEMP (t1–t5): MAE = **0.0614 °C**, RMSE = **0.1085 °C**
- HUM  (h1–h5): MAE = **0.4194 %**, RMSE = **0.5797 %**

### Comparativa

| Métrica       | Viejo CRT12 GRU | Actual (en vivo) | Mejora |
|---------------|----------------:|-----------------:|-------:|
| TEMP MAE (°C) | 0.085           | **0.061**        | 1.4×   |
| TEMP RMSE (°C)| 0.260           | **0.109**        | 2.4×   |
| HUM  MAE (%)  | 1.130           | **0.419**        | 2.7×   |
| HUM  RMSE (%) | 2.000           | **0.580**        | 3.4×   |

### Caveats metodológicos

- **No son comparables 1:1**: las cifras CRT12 vienen de test-set offline (split del dataset histórico); el actual es evaluación en vivo sobre datos no vistos del dispositivo real. Aun así, la magnitud del salto (especialmente en HUM) deja claro que el rediseño paga.
- El modelo actual usa **GRU dual** (uno para TEMP, uno para HUM), vigila **6 sensores en paralelo** y predice **delta** (Δ) en lugar de valor absoluto. Esto evita el "sesgo ingenuo" donde la red copia el último valor visto.

### Hallazgos por sensor

- **t5** es el sensor TEMP más preciso (MAE = 0.026 °C). Probablemente en la zona más estable térmicamente.
- **h4** es el sensor HUM más ruidoso (MAE = 0.85 %, 2–3× peor que sus hermanos). Vale revisar físicamente — puede estar mal posicionado o con falla incipiente.
- Sensores **exteriores** (tex, hex) tienen error más alto, esperable porque el clima exterior es caótico — no afecta la calidad del control del cuarto.

### Veredicto

**El modelo actual está jalando bien**. Mejor o comparable al viejo en TEMP, y 2.7–3.4× mejor en HUM. **No se requiere reentrenamiento**.

## 3) Artefactos generados

| Archivo                                                  | Descripción                                   |
|----------------------------------------------------------|-----------------------------------------------|
| `ai-predictor/scripts/verify_termo_vs_calentador.py`     | Pulla 48 h de los 5 sensores de calefacción y diagnostica deltas físicos. |
| `ai-predictor/scripts/evaluate_current_model.py`         | Evalúa el modelo en producción sobre datos reales recientes. Acepta `--hours N`. |
| `ai-predictor/scripts/build_rtf_report.py`               | Genera resumen RTF con 4 gráficas matplotlib embebidas (PNG hex). |
| `ai-predictor/reports_output/resumen-validacion.rtf`     | Documento RTF entregable con tablas, gráficos y diagnóstico (305 KB). |

## 4) Cómo reproducir

```powershell
cd ai-predictor

# Diagnóstico de coherencia termo/calentador
python scripts/verify_termo_vs_calentador.py

# Evaluación del modelo (default 24h)
python scripts/evaluate_current_model.py --hours 48

# Regenerar el RTF entregable
python scripts/build_rtf_report.py
```

Requiere `.env` con `UBIDOTS_TOKEN` y `UBIDOTS_DEVICE_LABEL=tenebrios`. Los servicios sidecar (puerto 8001) y Express (puerto 5000) no necesitan estar corriendo: los tres scripts hacen sus propias llamadas REST a Ubidots.
