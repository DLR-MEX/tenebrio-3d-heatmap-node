"""
Recolector de datos para reportes ejecutivos.

Unifica las fuentes existentes (AlertLog SQLite + Ubidots HTTP + snapshot
del PredictionService) en una estructura unica para el template Jinja2:

    {
        "meta": {"start_iso", "end_iso", "generated_iso", "hours", ...},
        "current": {snapshot reducido del cuarto AHORA},
        "thresholds": {TEMP, HUM},
        "alerts": {
            "transitions_total": int,
            "transitions_to_abnormal": int,
            "transitions_by_var": {var: count},
            "transitions": [...],     # detalle (max 50)
            "jumps_total": int,
            "jumps": [...],            # detalle (max 30)
        },
        "history": {
            "TEMP": {var: {"min", "max", "avg", "n", "time_outside_pct"}},
            "HUM":  {var: ...},
        },
        "predictions_accuracy": {
            "TEMP": {var: {"mae", "rmse", "n"}},  # error promedio del modelo
            "HUM":  {var: ...},
        },
        "infrastructure": {var: {"label", "value", "ts_iso"}},
        "time_series": {
            # raw para graficar
            "TEMP": [(ts_ms, {var: val})],
            "HUM":  [...],
        },
    }
"""

from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger("reports.collector")


def collect_period_data(
    service,                          # PredictionService (evita import circular)
    start_ts: float,                  # epoch seconds
    end_ts: float,
    include_time_series: bool = True,
    max_history_points: int = 500,
) -> dict:
    """Recolecta todos los datos necesarios para un reporte del periodo."""
    from app.service import (
        TEMP_VARS, HUM_VARS, EXTRA_TEMP_VARS, EXTERIOR_VARS,
        TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX,
        HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX,
        UbidotsHTTP,
    )
    from app.agent import INFRASTRUCTURE_VARS

    out: dict = {
        "meta": {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "start_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(start_ts)),
            "end_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(end_ts)),
            "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "hours": round((end_ts - start_ts) / 3600, 1),
            "days": round((end_ts - start_ts) / 86400, 2),
            "device": service.cfg.device_label,
        },
        "thresholds": {
            "TEMP": {"min": TEMP_OPTIMAL_MIN, "max": TEMP_OPTIMAL_MAX, "unit": "°C"},
            "HUM": {"min": HUM_OPTIMAL_MIN, "max": HUM_OPTIMAL_MAX, "unit": "%"},
        },
    }

    # --- Estado actual (snapshot ligero) ---
    snap = service.snapshot()
    out["current"] = {
        "mqtt_connected": snap.get("mqtt_connected"),
        "groups": {},
        "extras": snap.get("extras") or {},
    }
    for g_name in ("TEMP", "HUM"):
        g = (snap.get("groups") or {}).get(g_name) or {}
        out["current"]["groups"][g_name] = {
            "current": g.get("current") or {},
            "predicted": g.get("predicted") or {},
            "alerts": g.get("alerts") or {},
        }

    # --- AlertLog: transiciones y saltos en el periodo ---
    alert_log = service.alert_log
    rows = alert_log.query(since_ts=start_ts, limit=10_000) if alert_log else []
    # Filtrar al periodo (alert_log.query no acepta end_ts)
    rows = [r for r in rows if start_ts <= r["ts"] <= end_ts]

    transitions = [r for r in rows if r["kind"] != "jump"]
    jumps = [r for r in rows if r["kind"] == "jump"]

    transitions_by_var: dict[str, int] = {}
    for r in transitions:
        v = r["var"]
        if v in EXTERIOR_VARS:
            continue  # exteriores no son alerta
        transitions_by_var[v] = transitions_by_var.get(v, 0) + 1

    transitions_to_abnormal = sum(
        1 for r in transitions
        if r["new_state"] == "abnormal" and r["var"] not in EXTERIOR_VARS
    )

    out["alerts"] = {
        "transitions_total": len([r for r in transitions if r["var"] not in EXTERIOR_VARS]),
        "transitions_to_abnormal": transitions_to_abnormal,
        "transitions_by_var": transitions_by_var,
        "transitions": [_fmt_transition(r) for r in transitions[-50:] if r["var"] not in EXTERIOR_VARS],
        "jumps_total": len([r for r in jumps if r["var"] not in EXTERIOR_VARS]),
        "jumps": [_fmt_jump(r) for r in jumps[-30:] if r["var"] not in EXTERIOR_VARS],
    }

    # --- Histórico Ubidots: stats por sensor ---
    http = UbidotsHTTP(service.cfg.token)
    start_ms = int(start_ts * 1000)
    end_ms = int(end_ts * 1000)

    out["history"] = {"TEMP": {}, "HUM": {}}
    out["time_series"] = {"TEMP": [], "HUM": []}

    all_temp_vars = TEMP_VARS + EXTRA_TEMP_VARS  # incluye tps, tpi
    for var in all_temp_vars:
        stats, ts_data = _pull_var_stats(
            service, http, var, start_ms, end_ms,
            TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX,
            include_time_series and var not in ("tps", "tpi"),
            max_history_points,
        )
        if stats:
            out["history"]["TEMP"][var] = stats
        if ts_data:
            out["time_series"]["TEMP"].append({"var": var, "data": ts_data})

    for var in HUM_VARS:
        stats, ts_data = _pull_var_stats(
            service, http, var, start_ms, end_ms,
            HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX,
            include_time_series,
            max_history_points,
        )
        if stats:
            out["history"]["HUM"][var] = stats
        if ts_data:
            out["time_series"]["HUM"].append({"var": var, "data": ts_data})

    # --- Precisión del modelo predictivo (real vs _pred) ---
    out["predictions_accuracy"] = {"TEMP": {}, "HUM": {}}
    for var in TEMP_VARS:
        accuracy = _compute_prediction_accuracy(service, http, var, start_ms, end_ms)
        if accuracy:
            out["predictions_accuracy"]["TEMP"][var] = accuracy
    for var in HUM_VARS:
        accuracy = _compute_prediction_accuracy(service, http, var, start_ms, end_ms)
        if accuracy:
            out["predictions_accuracy"]["HUM"][var] = accuracy

    # --- Infraestructura: snapshot actual (no historico aqui, seria pesado) ---
    out["infrastructure"] = {}
    # Reutilizamos resolucion de var_ids: necesitamos device id + variables
    try:
        device_id = http.get_device_id(service.cfg.device_label)
        var_map = http.get_variables(device_id) if device_id else {}
    except Exception as e:
        log.warning("No se pudo cargar variable map: %s", e)
        var_map = {}

    for label, (display, unit, category, hint) in INFRASTRUCTURE_VARS.items():
        var_id = var_map.get(label)
        if not var_id:
            continue
        try:
            rows = http.get_last_values(var_id, 1)
            if rows:
                ts_ms, val = rows[-1]
                out["infrastructure"][label] = {
                    "label": display,
                    "category": category,
                    "value": round(val, 2),
                    "unit": unit,
                    "ts_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts_ms / 1000)),
                    "description": hint,
                }
        except Exception as e:
            log.warning("Error infra var=%s: %s", label, e)

    log.info(
        "Reporte recolectado: %.1fh, %d transiciones, %d saltos, %d sensores",
        out["meta"]["hours"],
        out["alerts"]["transitions_total"],
        out["alerts"]["jumps_total"],
        len(out["history"]["TEMP"]) + len(out["history"]["HUM"]),
    )
    return out


# ---------- helpers ----------

def _fmt_transition(r: dict) -> dict:
    return {
        "ts_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
        "group": r["group_name"],
        "var": r["var"],
        "from": r["prev_state"],
        "to": r["new_state"],
        "kind": r["kind"],
        "value": r["value"],
    }


def _fmt_jump(r: dict) -> dict:
    delta = r.get("predicted_value")
    return {
        "ts_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
        "group": r["group_name"],
        "var": r["var"],
        "from_value": r["prev_state"],
        "to_value": r["new_state"],
        "delta": round(delta, 2) if isinstance(delta, (int, float)) else None,
    }


def _pull_var_stats(
    service, http, var: str, start_ms: int, end_ms: int,
    lo: float, hi: float, include_ts: bool, max_points: int,
) -> tuple[Optional[dict], Optional[list]]:
    """Pulla histórico Ubidots para `var` y calcula stats + serie temporal."""
    var_id = _resolve(service, http, var)
    if not var_id:
        return None, None
    try:
        rows = http.get_values_range(var_id, start_ms, end_ms, max_points=max_points)
    except Exception as e:
        log.warning("get_values_range %s fallo: %s", var, e)
        return None, None
    if not rows:
        return None, None
    values = [v for _, v in rows]
    n = len(values)
    outside = sum(1 for v in values if not (lo <= v <= hi))
    stats = {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(sum(values) / n, 2),
        "n": n,
        "time_outside_pct": round((outside / n) * 100, 1),
    }
    ts_data = None
    if include_ts and var not in ("tex", "hex"):  # exteriores fuera de chart principal
        # Submuestrear si hay demasiados puntos
        if n > max_points:
            step = max(1, n // max_points)
            ts_data = rows[::step]
        else:
            ts_data = rows
    return stats, ts_data


def _compute_prediction_accuracy(service, http, var: str, start_ms: int, end_ms: int) -> Optional[dict]:
    """Compara `var` real vs `var`_pred en el periodo. MAE, RMSE."""
    real_id = _resolve(service, http, var)
    pred_id = _resolve(service, http, f"{var}_pred")
    if not real_id or not pred_id:
        return None
    try:
        real = http.get_values_range(real_id, start_ms, end_ms, max_points=2000)
        pred = http.get_values_range(pred_id, start_ms, end_ms, max_points=2000)
    except Exception:
        return None
    if not real or not pred:
        return None

    # Alinear: para cada pred (en ts T), buscar real mas cercano a T+180s
    import bisect
    real_ts = [r[0] for r in real]
    real_v = [r[1] for r in real]
    errs = []
    for ts_pred, v_pred in pred:
        target = ts_pred + 180 * 1000  # +3 min en ms
        idx = bisect.bisect_left(real_ts, target)
        if idx == 0 or idx >= len(real_ts):
            continue
        # mas cercano
        actual_idx = idx if abs(real_ts[idx] - target) < abs(real_ts[idx - 1] - target) else idx - 1
        errs.append(v_pred - real_v[actual_idx])

    if not errs:
        return None
    n = len(errs)
    mae = sum(abs(e) for e in errs) / n
    rmse = (sum(e * e for e in errs) / n) ** 0.5
    return {
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "n": n,
    }


_var_id_cache: dict = {}

def _resolve(service, http, label: str) -> Optional[str]:
    """Cache simple de var_id (compartido entre llamadas en este modulo)."""
    if label in _var_id_cache:
        return _var_id_cache[label]
    try:
        device_id = http.get_device_id(service.cfg.device_label)
        if not device_id:
            return None
        var_map = http.get_variables(device_id)
        _var_id_cache.update(var_map)
        return _var_id_cache.get(label)
    except Exception as e:
        log.warning("resolve %s fallo: %s", label, e)
        return None
