"""Evalua el modelo en produccion (ai-predictor/models) contra datos reales
recientes de Ubidots y emite MAE/RMSE por sensor + comparativa con los
modelos viejos (CRT12 y Modelos_Tenebrios).

Metodo:
  1. Pulla ultimas N horas de t1..t5,tex y h1..h5,hex de Ubidots
  2. Alinea por minuto -> serie de 12 columnas
  3. Genera ventanas de LOOK_BACK=30 muestras
  4. Predice +3min con el modelo actual (formato delta)
  5. Compara contra el valor real observado 3min despues
  6. MAE/RMSE por sensor

Uso: python scripts/evaluate_current_model.py [--hours 24]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

# Silenciar logs ruidosos de TF antes del import
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

from tensorflow.keras.models import load_model  # noqa: E402
from app.service import UbidotsHTTP, TEMP_VARS, HUM_VARS, LOOK_BACK, STEP_AHEAD  # noqa: E402

MODELS_DIR = ROOT / "models"


def pull_aligned(http: UbidotsHTTP, var_map: dict, vars_list: list[str],
                 start_ms: int, end_ms: int) -> tuple[list[int], dict[str, list[float]]]:
    """Trae cada variable y la alinea por minuto. Devuelve (ts_min[], {var: [vals]}).
    Si una variable falta el minuto -> NaN."""
    raw: dict[str, dict[int, float]] = {}
    for var in vars_list:
        vid = var_map.get(var)
        if not vid:
            raw[var] = {}
            continue
        rows = http.get_values_range(vid, start_ms, end_ms, max_points=20000)
        # Indexar por minuto (timestamp ms -> minuto epoch)
        by_min: dict[int, float] = {}
        for ts_ms, val in rows:
            mk = int(ts_ms // 60000)
            by_min[mk] = val  # ultima muestra de ese minuto gana
        raw[var] = by_min

    if not any(raw.values()):
        return [], {}

    all_min = sorted(set().union(*(d.keys() for d in raw.values())))
    aligned = {var: [raw[var].get(mk, float("nan")) for mk in all_min] for var in vars_list}
    return all_min, aligned


def evaluate_group(group: str, vars_list: list[str], model, scaler,
                   minutes: list[int], series: dict[str, list[float]]) -> list[dict]:
    """Calcula MAE/RMSE por sensor del grupo en ventanas con datos completos."""
    n = len(minutes)
    if n < LOOK_BACK + STEP_AHEAD + 1:
        print(f"  {group}: insuficiente data ({n} minutos), necesito >={LOOK_BACK + STEP_AHEAD + 1}")
        return []

    arr = np.array([series[v] for v in vars_list], dtype=float).T  # (n, 6)

    # Reportar disponibilidad por sensor
    print(f"  {group}: {n} minutos descargados | NaN por sensor:")
    for i, v in enumerate(vars_list):
        nans = np.isnan(arr[:, i]).sum()
        print(f"      {v:5s} -> {nans}/{n} NaN ({(nans/n)*100:.1f}%)")

    # Errores acumulados por sensor
    abs_err: dict[str, list[float]] = {v: [] for v in vars_list}
    sq_err: dict[str, list[float]] = {v: [] for v in vars_list}
    preds_count = 0

    # Para cada ventana posible
    for i in range(n - LOOK_BACK - STEP_AHEAD):
        window = arr[i:i + LOOK_BACK]
        target = arr[i + LOOK_BACK + STEP_AHEAD - 1]
        current = arr[i + LOOK_BACK - 1]

        # Saltar ventana si tiene cualquier NaN (no podemos escalar)
        if np.isnan(window).any() or np.isnan(target).any() or np.isnan(current).any():
            continue

        # Escalar y predecir delta
        scaled = scaler.transform(window)
        delta_scaled = model.predict(scaled.reshape(1, LOOK_BACK, len(vars_list)),
                                     verbose=0)[0]
        # El modelo predice el delta en espacio escalado. Para invertirlo
        # comparamos contra (target - current) en espacio escalado o invertimos.
        # Mas simple: predecir el valor reescalado y comparar contra target.
        current_scaled = scaler.transform(current.reshape(1, -1))[0]
        predicted_scaled = current_scaled + delta_scaled
        predicted = scaler.inverse_transform(predicted_scaled.reshape(1, -1))[0]

        for j, v in enumerate(vars_list):
            err = predicted[j] - target[j]
            abs_err[v].append(abs(err))
            sq_err[v].append(err * err)
        preds_count += 1

    print(f"  {group}: {preds_count} predicciones evaluadas (ventanas completas)")

    rows = []
    for v in vars_list:
        ae = abs_err[v]
        se = sq_err[v]
        if not ae:
            rows.append({"sensor": v, "n": 0})
            continue
        mae = sum(ae) / len(ae)
        rmse = (sum(se) / len(se)) ** 0.5
        rows.append({"sensor": v, "n": len(ae), "MAE": mae, "RMSE": rmse})
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    args = p.parse_args()

    token = os.getenv("UBIDOTS_TOKEN", "")
    device = os.getenv("UBIDOTS_DEVICE_LABEL", "tenebrios")
    if not token:
        print("FALTA UBIDOTS_TOKEN"); return 1

    print(f"Cargando modelo actual ({MODELS_DIR})...")
    model_t = load_model(MODELS_DIR / "model_t.keras", compile=False)
    model_h = load_model(MODELS_DIR / "model_h.keras", compile=False)
    scaler_t = joblib.load(MODELS_DIR / "scaler_t.save")
    scaler_h = joblib.load(MODELS_DIR / "scaler_h.save")

    http = UbidotsHTTP(token)
    dev_id = http.get_device_id(device)
    var_map = http.get_variables(dev_id)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.hours * 3600 * 1000

    print(f"\nPulleando {args.hours}h de datos...")
    min_t, ser_t = pull_aligned(http, var_map, TEMP_VARS, start_ms, end_ms)
    min_h, ser_h = pull_aligned(http, var_map, HUM_VARS, start_ms, end_ms)

    print(f"\n--- TEMP (model_t.keras, LOOK_BACK={LOOK_BACK}, STEP_AHEAD={STEP_AHEAD}) ---")
    rows_t = evaluate_group("TEMP", TEMP_VARS, model_t, scaler_t, min_t, ser_t)

    print(f"\n--- HUM  (model_h.keras) ---")
    rows_h = evaluate_group("HUM", HUM_VARS, model_h, scaler_h, min_h, ser_h)

    print("\n" + "=" * 78)
    print(f"  RESULTADOS ({args.hours}h, prediccion a +{STEP_AHEAD} min)")
    print("=" * 78)
    print(f"  {'grupo':5s} {'sensor':6s} {'n':>6s} {'MAE':>10s} {'RMSE':>10s}")
    for r in rows_t:
        if r.get("n"):
            print(f"  TEMP  {r['sensor']:6s} {r['n']:6d} "
                  f"{r['MAE']:10.4f} {r['RMSE']:10.4f}")
        else:
            print(f"  TEMP  {r['sensor']:6s} {'SIN DATOS':>27s}")
    for r in rows_h:
        if r.get("n"):
            print(f"  HUM   {r['sensor']:6s} {r['n']:6d} "
                  f"{r['MAE']:10.4f} {r['RMSE']:10.4f}")
        else:
            print(f"  HUM   {r['sensor']:6s} {'SIN DATOS':>27s}")

    # Promedios para comparar con CSV viejos
    int_t = [r for r in rows_t if r.get("n") and r["sensor"] != "tex"]
    int_h = [r for r in rows_h if r.get("n") and r["sensor"] != "hex"]
    if int_t:
        mae_t = sum(r["MAE"] for r in int_t) / len(int_t)
        rmse_t = sum(r["RMSE"] for r in int_t) / len(int_t)
        print(f"\n  TEMP interior promedio (t1-t5): MAE={mae_t:.4f}  RMSE={rmse_t:.4f}")
    if int_h:
        mae_h = sum(r["MAE"] for r in int_h) / len(int_h)
        rmse_h = sum(r["RMSE"] for r in int_h) / len(int_h)
        print(f"  HUM  interior promedio (h1-h5): MAE={mae_h:.4f}  RMSE={rmse_h:.4f}")

    print("\n" + "-" * 78)
    print("  COMPARATIVA con modelos viejos (CRT12, Condusef)")
    print("-" * 78)
    print("  CRT12-t (un solo tanque):  LSTM RMSE=0.81 MAE=0.21 | GRU RMSE=0.26 MAE=0.085")
    print("  CRT12-h (un solo tanque):  LSTM RMSE=3.01 MAE=1.71 | GRU RMSE=2.00 MAE=1.13")
    print("  Notas:")
    print("   - Las cifras CRT12 son sobre TEST SET (split offline) -> no comparables 1:1")
    print("     con la evaluacion en vivo de arriba (datos no vistos del dispositivo real).")
    print("   - El modelo actual predice DELTA y vigila 6 sensores en paralelo;")
    print("     CRT12 era valor-absoluto y un solo tanque.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
