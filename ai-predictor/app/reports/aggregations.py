"""
Agregaciones temporales para reportes ejecutivos.

A partir de las series temporales crudas (lista de (ts_ms, value) por
sensor) calcula vistas que un lector NO especialista entiende:

  - Promedio interior por DIA          ¿qué días estuvieron más calientes?
  - Perfil por HORA del día (0-23h)    ¿a qué horas hace más calor?
  - Agregación por SEMANA              ¿cuál fue la mejor/peor semana?
  - Matriz hora x día (heatmap)        vista completa de patrones
  - Hora y día PICO                    el momento más crítico

Todo se calcula sobre el PROMEDIO de los sensores interiores (t1-t5 para
temperatura, h1-h5 para humedad) — el reporte ejecutivo busca el panorama,
no el detalle sensor por sensor.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

log = logging.getLogger("reports.aggregations")

# Sensores interiores por grupo (los exteriores tex/hex no entran)
_INTERIOR = {
    "TEMP": ("t1", "t2", "t3", "t4", "t5"),
    "HUM": ("h1", "h2", "h3", "h4", "h5"),
}
_DOW_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_MONTH_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]


def compute_aggregations(time_series_group: list, group: str,
                         lo: float, hi: float) -> dict:
    """time_series_group: lista de {var, data:[(ts_ms,val)]} del collector.
    group: 'TEMP' o 'HUM'.
    lo/hi: umbrales optimos.

    Devuelve dict con daily, hourly_profile, weekly, heatmap, peaks.
    """
    interior = _INTERIOR.get(group, ())
    # Construir serie de PROMEDIO interior: para cada timestamp, promedio
    # de los sensores interiores que tengan dato en ese instante.
    # Como los sensores se muestrean casi sincronizados, agrupamos por
    # minuto redondeado y promediamos.
    by_minute: dict[int, list[float]] = {}
    for s in time_series_group:
        if s["var"] not in interior:
            continue
        for ts_ms, val in s["data"]:
            minute_key = int(ts_ms // 60000)  # minuto epoch
            by_minute.setdefault(minute_key, []).append(val)

    if not by_minute:
        return _empty()

    # Serie promedio: (ts_seconds, avg_value)
    avg_series = sorted(
        (mk * 60, sum(vals) / len(vals))
        for mk, vals in by_minute.items()
    )

    daily = _by_day(avg_series, lo, hi)
    return {
        "daily": daily,
        "hourly_profile": _by_hour_of_day(avg_series),
        "weekly": _by_week(avg_series, lo, hi),
        "heatmap": _heatmap(avg_series),
        "peaks": _peaks(avg_series),
        "overall": _overall(avg_series, daily),
        "samples": len(avg_series),
    }


def _empty() -> dict:
    return {"daily": [], "hourly_profile": [], "weekly": [],
            "heatmap": None, "peaks": {}, "overall": {}, "samples": 0}


def _by_day(series: list, lo: float, hi: float) -> list[dict]:
    """Promedio/min/max y % tiempo en rango por día calendario."""
    buckets: dict[str, list[float]] = {}
    for ts, val in series:
        day_key = time.strftime("%Y-%m-%d", time.localtime(ts))
        buckets.setdefault(day_key, []).append(val)
    out = []
    for day in sorted(buckets):
        vals = buckets[day]
        n = len(vals)
        in_range = sum(1 for v in vals if lo <= v <= hi)
        # Etiqueta legible: "Lun 19 may"
        dt = datetime.strptime(day, "%Y-%m-%d")
        label = f"{_DOW_ES[dt.weekday()]} {dt.day} {_MONTH_ES[dt.month]}"
        out.append({
            "date": day,
            "label": label,
            "avg": round(sum(vals) / n, 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "in_range_pct": round(in_range / n * 100, 1),
            "n": n,
        })
    return out


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _overall(series: list, daily: list) -> dict:
    """Estadisticas globales del periodo: promedio, mediana, dia mas
    caliente y mas frio (por promedio diario)."""
    if not series:
        return {}
    vals = [v for _, v in series]
    out = {
        "avg": round(sum(vals) / len(vals), 2),
        "median": round(_median(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
    }
    if daily:
        hottest = max(daily, key=lambda d: d["avg"])
        coldest = min(daily, key=lambda d: d["avg"])
        out["hottest_day"] = {"label": hottest["label"], "avg": hottest["avg"]}
        out["coldest_day"] = {"label": coldest["label"], "avg": coldest["avg"]}
    return out


def _by_hour_of_day(series: list) -> list[dict]:
    """Promedio por hora del día (0-23), agregando todos los días."""
    buckets: dict[int, list[float]] = {}
    for ts, val in series:
        hour = time.localtime(ts).tm_hour
        buckets.setdefault(hour, []).append(val)
    out = []
    for h in range(24):
        vals = buckets.get(h, [])
        if vals:
            out.append({
                "hour": h,
                "label": f"{h:02d}:00",
                "avg": round(sum(vals) / len(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "n": len(vals),
            })
    return out


def _by_week(series: list, lo: float, hi: float) -> list[dict]:
    """Agregación por semana ISO. Calcula avg/min/max y % en rango.
    Marca la mejor y peor semana (por % tiempo en rango)."""
    buckets: dict[str, list[float]] = {}
    for ts, val in series:
        # Clave: año-semana ISO
        iso = time.localtime(ts)
        year, week, _ = datetime.fromtimestamp(ts).isocalendar()
        wkey = f"{year}-W{week:02d}"
        buckets.setdefault(wkey, []).append(val)

    weeks = []
    for wkey in sorted(buckets):
        vals = buckets[wkey]
        n = len(vals)
        in_range = sum(1 for v in vals if lo <= v <= hi)
        # Rango de fechas de la semana
        weeks.append({
            "week": wkey,
            "avg": round(sum(vals) / n, 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "in_range_pct": round(in_range / n * 100, 1),
            "n": n,
        })

    # Marcar mejor (mayor % en rango) y peor (menor % en rango)
    if len(weeks) >= 2:
        best = max(weeks, key=lambda w: w["in_range_pct"])
        worst = min(weeks, key=lambda w: w["in_range_pct"])
        for w in weeks:
            w["is_best"] = (w["week"] == best["week"])
            w["is_worst"] = (w["week"] == worst["week"] and w["week"] != best["week"])
    else:
        for w in weeks:
            w["is_best"] = False
            w["is_worst"] = False
    return weeks


def _heatmap(series: list) -> dict | None:
    """Matriz día x hora con el promedio de cada celda.
    Devuelve {days:[labels], values:[[24 valores] por dia]}."""
    # cell[(day, hour)] = lista de valores
    cells: dict[tuple, list[float]] = {}
    days_seen: dict[str, str] = {}  # day_key -> label
    for ts, val in series:
        lt = time.localtime(ts)
        day_key = time.strftime("%Y-%m-%d", lt)
        hour = lt.tm_hour
        cells.setdefault((day_key, hour), []).append(val)
        if day_key not in days_seen:
            dt = datetime.fromtimestamp(ts)
            days_seen[day_key] = f"{_DOW_ES[dt.weekday()]} {dt.day}"

    if not days_seen:
        return None

    sorted_days = sorted(days_seen)
    values = []
    for day in sorted_days:
        row = []
        for h in range(24):
            vals = cells.get((day, h))
            row.append(round(sum(vals) / len(vals), 2) if vals else None)
        values.append(row)

    return {
        "days": [days_seen[d] for d in sorted_days],
        "day_keys": sorted_days,
        "values": values,  # [n_days][24]
    }


def _peaks(series: list) -> dict:
    """Identifica el momento más caliente y más frío del periodo."""
    if not series:
        return {}
    hottest = max(series, key=lambda x: x[1])
    coldest = min(series, key=lambda x: x[1])
    return {
        "hottest": {
            "ts_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(hottest[0])),
            "value": round(hottest[1], 2),
        },
        "coldest": {
            "ts_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(coldest[0])),
            "value": round(coldest[1], 2),
        },
    }
