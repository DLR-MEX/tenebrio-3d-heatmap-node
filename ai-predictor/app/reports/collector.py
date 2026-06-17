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


def floor_to_local_midnight(ts: float) -> float:
    """Redondea un epoch hacia abajo al inicio del día local (00:00:00).

    Así los reportes (y el heatmap hora × día) arrancan a las 00:00 y no a
    media mañana — la primera fila del heatmap queda completa en vez de
    empezar a la hora en que se pidió el reporte."""
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                        0, 0, 0, lt.tm_wday, lt.tm_yday, -1))


def collect_period_data(
    service,                          # PredictionService (evita import circular)
    start_ts: float,                  # epoch seconds
    end_ts: float,
    include_time_series: bool = True,
    max_history_points: int = 15000,  # >1 semana a 1 muestra/min
) -> dict:
    """Recolecta todos los datos necesarios para un reporte del periodo."""
    # El periodo arranca al inicio del día local para que el heatmap empiece
    # a las 00:00 (idempotente si ya viene alineado).
    start_ts = floor_to_local_midnight(start_ts)
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
    # PARALELIZADO: las llamadas HTTP a Ubidots eran el cuello de botella
    # (~50 requests secuenciales = 150s+). Con un ThreadPoolExecutor las
    # hacemos concurrentes. urllib libera el GIL en I/O asi que threads
    # sirven perfecto aqui.
    from concurrent.futures import ThreadPoolExecutor

    http = UbidotsHTTP(service.cfg.token)
    start_ms = int(start_ts * 1000)
    end_ms = int(end_ts * 1000)

    out["history"] = {"TEMP": {}, "HUM": {}}
    out["time_series"] = {"TEMP": [], "HUM": []}
    # predictions_accuracy: el template ya no muestra precision del modelo
    # (se quito en el rework). Lo dejamos vacio para no romper render.py.
    out["predictions_accuracy"] = {"TEMP": {}, "HUM": {}}

    all_temp_vars = TEMP_VARS + EXTRA_TEMP_VARS  # incluye tps, tpi

    # Pre-cargar el var_id cache una sola vez (evita que cada thread lo
    # resuelva por separado).
    device_id = None
    var_map: dict = {}
    try:
        device_id = http.get_device_id(service.cfg.device_label)
        if device_id:
            var_map = http.get_variables(device_id)
            _var_id_cache.update(var_map)
    except Exception as e:
        log.warning("No se pudo cargar variable map: %s", e)

    def _pull_temp(var):
        stats, ts_data = _pull_var_stats(
            service, http, var, start_ms, end_ms,
            TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX,
            include_time_series and var not in ("tps", "tpi"),
            max_history_points,
        )
        return ("TEMP", var, stats, ts_data)

    def _pull_hum(var):
        stats, ts_data = _pull_var_stats(
            service, http, var, start_ms, end_ms,
            HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX,
            include_time_series, max_history_points,
        )
        return ("HUM", var, stats, ts_data)

    jobs = [(_pull_temp, v) for v in all_temp_vars] + [(_pull_hum, v) for v in HUM_VARS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for group, var, stats, ts_data in pool.map(lambda j: j[0](j[1]), jobs):
            if stats:
                out["history"][group][var] = stats
            if ts_data:
                out["time_series"][group].append({"var": var, "data": ts_data})
    # Ordenar time_series por nombre de var para consistencia visual
    for g in ("TEMP", "HUM"):
        out["time_series"][g].sort(key=lambda s: s["var"])

    # --- Infraestructura: ultima lectura de cada componente (paralelo) ---
    out["infrastructure"] = {}

    def _pull_infra(item):
        label, (display, unit, category, hint) = item
        var_id = var_map.get(label)
        if not var_id:
            return None
        try:
            rows = http.get_last_values(var_id, 1)
            if rows:
                ts_ms, val = rows[-1]
                return label, {
                    "label": display,
                    "category": category,
                    "value": round(val, 2),
                    "unit": unit,
                    "ts_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts_ms / 1000)),
                    "description": hint,
                }
        except Exception as e:
            log.warning("Error infra var=%s: %s", label, e)
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(_pull_infra, list(INFRASTRUCTURE_VARS.items())):
            if result:
                out["infrastructure"][result[0]] = result[1]

    # --- Amoniaco (NH3): stats + serie temporal para la seccion calidad de aire ---
    # Umbral sanitario: <25 ppm. Si la variable no existe en el dispositivo se
    # omite limpiamente y la seccion del PDF colapsa.
    NH3_MAX_PPM = 25.0
    out["air_quality"] = {"nh3": None}
    nh3_var_id = var_map.get("amoniaco")
    if nh3_var_id:
        try:
            nh3_rows = http.get_values_range(nh3_var_id, start_ms, end_ms,
                                             max_points=max_history_points)
            if nh3_rows:
                nh3_vals = [v for _, v in nh3_rows]
                n_nh3 = len(nh3_vals)
                over = sum(1 for v in nh3_vals if v > NH3_MAX_PPM)
                out["air_quality"]["nh3"] = {
                    "min": round(min(nh3_vals), 2),
                    "max": round(max(nh3_vals), 2),
                    "avg": round(sum(nh3_vals) / n_nh3, 2),
                    "n": n_nh3,
                    "threshold": NH3_MAX_PPM,
                    "time_over_pct": round(over / n_nh3 * 100, 1),
                    "data": nh3_rows,  # serie cruda para charts
                }
        except Exception as e:
            log.warning("NH3 pull fallo: %s", e)

    # --- Historia de infraestructura para heatmaps (termo, calentador,
    # entrada y salida del piso radiante). Una clave por sensor con
    # display_name + serie temporal cruda. Usa el mismo pull paralelo.
    INFRA_HISTORY_VARS = [
        ("temperatura5", "Termo"),
        ("temperatura2", "Calentador solar"),
        ("temperatura4", "Entrada al piso radiante"),
        ("temperatura1", "Salida del piso radiante"),
    ]

    def _pull_infra_history(item):
        label, display = item
        vid = var_map.get(label)
        if not vid:
            return None
        try:
            rows = http.get_values_range(vid, start_ms, end_ms,
                                         max_points=max_history_points)
            if not rows:
                return None
            return label, {"display": display, "data": rows, "n": len(rows)}
        except Exception as e:
            log.warning("infra_history %s fallo: %s", label, e)
            return None

    out["infrastructure_history"] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(_pull_infra_history, INFRA_HISTORY_VARS):
            if result:
                out["infrastructure_history"][result[0]] = result[1]

    # --- Agregaciones temporales (por dia, hora, semana) ---
    # Estas alimentan los charts variados del reporte: heatmap hora x dia,
    # promedio diario, perfil horario, comparativa semanal.
    from app.reports.aggregations import compute_aggregations, compute_exterior_series
    out["aggregations"] = {
        "TEMP": compute_aggregations(
            out["time_series"]["TEMP"], "TEMP",
            TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX,
        ),
        "HUM": compute_aggregations(
            out["time_series"]["HUM"], "HUM",
            HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX,
        ),
    }
    # Serie exterior (tex/hex) para overlay interior-vs-exterior en charts
    out["exterior"] = {
        "TEMP": compute_exterior_series(out["time_series"]["TEMP"], "TEMP"),
        "HUM": compute_exterior_series(out["time_series"]["HUM"], "HUM"),
    }

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
    if include_ts:
        # tex/hex se incluyen para que el reporte pueda comparar interior vs exterior.
        # El collector marca la serie con su `var` y aggregations decide si va al
        # promedio interior o a la serie exterior.
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
