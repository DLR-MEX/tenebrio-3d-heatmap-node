"""
Generacion de graficas para el reporte ejecutivo PDF.

Variedad de tipos (no solo lineas) para que el reporte sea entendible
por cualquier persona:
  - Heatmap hora x dia       (patron de temperatura por horario)
  - Barras promedio diario   (con banda min-max)
  - Perfil horario           (curva del dia tipico)
  - Comparativa semanal      (mejor vs peor semana del mes)
  - Donut % tiempo en rango
  - Barras alertas por sensor

Backend matplotlib Agg (server-side). Cada chart -> data URL base64.
"""

from __future__ import annotations

import base64
import io
import logging

log = logging.getLogger("reports.charts")

# Paleta — fondo claro para impresion
BG_LIGHT = "#fdfcf7"
GRID = "#cbd5e1"
TEXT = "#1a2630"
ACCENT = "#E8B830"
COL_TEMP = "#e07a3f"     # naranja calido para temperatura
COL_HUM = "#3b82f6"      # azul para humedad
COL_OK = "#16a34a"
COL_WARN = "#f59e0b"
COL_DANGER = "#ef4444"


def generate_all_charts(data: dict) -> dict[str, str]:
    """Genera todas las graficas y devuelve {chart_id: data_url}."""
    charts: dict[str, str] = {}
    agg_temp = (data.get("aggregations") or {}).get("TEMP") or {}
    agg_hum = (data.get("aggregations") or {}).get("HUM") or {}
    th_temp = (data.get("thresholds") or {}).get("TEMP") or {}
    th_hum = (data.get("thresholds") or {}).get("HUM") or {}

    _try(charts, "temp_heatmap", lambda: chart_heatmap(
        agg_temp.get("heatmap"), "Temperatura por hora y día", "°C", th_temp))
    _try(charts, "temp_daily", lambda: chart_daily_bars(
        agg_temp.get("daily"), "Temperatura promedio por día", "°C",
        COL_TEMP, th_temp))
    _try(charts, "temp_hourly", lambda: chart_hourly_profile(
        agg_temp.get("hourly_profile"), "Perfil del día — temperatura", "°C",
        COL_TEMP, th_temp))
    _try(charts, "temp_weekly", lambda: chart_weekly_compare(
        agg_temp.get("weekly"), "Comparativa semanal — temperatura", "°C"))
    _try(charts, "temp_donut", lambda: chart_range_donut(
        data.get("history", {}).get("TEMP", {}), ("tex", "tps", "tpi"),
        "Tiempo en rango óptimo — temperatura"))

    _try(charts, "hum_heatmap", lambda: chart_heatmap(
        agg_hum.get("heatmap"), "Humedad por hora y día", "%", th_hum))
    _try(charts, "hum_daily", lambda: chart_daily_bars(
        agg_hum.get("daily"), "Humedad promedio por día", "%",
        COL_HUM, th_hum))
    _try(charts, "hum_hourly", lambda: chart_hourly_profile(
        agg_hum.get("hourly_profile"), "Perfil del día — humedad", "%",
        COL_HUM, th_hum))
    _try(charts, "hum_weekly", lambda: chart_weekly_compare(
        agg_hum.get("weekly"), "Comparativa semanal — humedad", "%"))
    _try(charts, "hum_donut", lambda: chart_range_donut(
        data.get("history", {}).get("HUM", {}), ("hex",),
        "Tiempo en rango óptimo — humedad"))

    _try(charts, "alerts_by_sensor", lambda: chart_alerts_by_sensor(data))

    log.info("Charts generados: %s", list(charts.keys()))
    return charts


def _try(charts: dict, key: str, fn):
    try:
        png = fn()
        if png:
            charts[key] = _to_data_url(png)
    except Exception as e:
        log.warning("chart %s fallo: %s", key, e)


# ---------- charts ----------

def chart_heatmap(heatmap: dict, title: str, unit: str, thresholds: dict) -> bytes:
    """Heatmap dia (filas) x hora 0-23 (columnas). Color = valor promedio."""
    if not heatmap or not heatmap.get("values"):
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    days = heatmap["days"]
    values = heatmap["values"]  # [n_days][24]
    arr = np.array([[v if v is not None else np.nan for v in row] for row in values],
                   dtype=float)

    # Altura proporcional al numero de dias (min 2.5, max 7)
    h = max(2.5, min(0.42 * len(days) + 1.2, 7))
    fig, ax = plt.subplots(figsize=(8.5, h), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)

    # Colormap: azul (frio) -> verde (optimo) -> naranja/rojo (caliente)
    cmap = LinearSegmentedColormap.from_list(
        "clima", ["#2563eb", "#22c55e", "#facc15", "#ef4444"])
    im = ax.imshow(arr, aspect="auto", cmap=cmap, interpolation="nearest")

    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)], fontsize=7)
    ax.set_yticks(range(len(days)))
    ax.set_yticklabels(days, fontsize=7)
    ax.set_xlabel("Hora del día", fontsize=8, color=TEXT)
    ax.set_title(title, fontsize=11, fontweight="bold", color=TEXT, pad=10)
    ax.tick_params(colors=TEXT)

    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.ax.tick_params(labelsize=7, colors=TEXT)
    cbar.set_label(unit, fontsize=8, color=TEXT)

    fig.tight_layout()
    return _save(fig)


def chart_daily_bars(daily: list, title: str, unit: str,
                     color: str, thresholds: dict) -> bytes:
    """Barras de promedio diario con banda min-max (errorbar)."""
    if not daily:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [d["label"] for d in daily]
    avgs = [d["avg"] for d in daily]
    mins = [d["min"] for d in daily]
    maxs = [d["max"] for d in daily]
    # Error bars: distancia del avg al min y al max
    err_low = [a - m for a, m in zip(avgs, mins)]
    err_high = [m - a for a, m in zip(maxs, avgs)]

    fig, ax = plt.subplots(figsize=(8.5, 3.4), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    bars = ax.bar(labels, avgs, color=color, edgecolor="white", linewidth=1,
                  yerr=[err_low, err_high], capsize=3,
                  error_kw={"ecolor": "#94a3b8", "elinewidth": 1})
    for bar, a in zip(bars, avgs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{a:g}", ha="center", va="bottom", fontsize=7.5,
                color=TEXT, fontweight="bold")

    lo, hi = thresholds.get("min"), thresholds.get("max")
    if lo is not None:
        ax.axhline(lo, color=COL_DANGER, ls=":", lw=1, alpha=0.6)
    if hi is not None:
        ax.axhline(hi, color=COL_DANGER, ls=":", lw=1, alpha=0.6)

    ax.set_title(title, fontsize=11, fontweight="bold", color=TEXT, pad=10)
    ax.set_ylabel(unit, fontsize=9, color=TEXT)
    ax.tick_params(colors=TEXT, labelsize=8)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    _clean_axes(ax)
    fig.tight_layout()
    return _save(fig)


def chart_hourly_profile(hourly: list, title: str, unit: str,
                         color: str, thresholds: dict) -> bytes:
    """Curva del dia tipico: promedio por hora 0-23 con area sombreada
    min-max. Resalta la hora mas caliente."""
    if not hourly:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hours = [d["hour"] for d in hourly]
    avgs = [d["avg"] for d in hourly]
    mins = [d["min"] for d in hourly]
    maxs = [d["max"] for d in hourly]

    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    ax.fill_between(hours, mins, maxs, color=color, alpha=0.15, label="rango min-máx")
    ax.plot(hours, avgs, color=color, lw=2.2, marker="o", markersize=3,
            label="promedio")

    # Resaltar la hora pico (mayor promedio)
    peak_idx = avgs.index(max(avgs))
    ax.scatter([hours[peak_idx]], [avgs[peak_idx]], color=COL_DANGER,
               zorder=5, s=60, edgecolor="white", linewidth=1.2)
    ax.annotate(f"  pico {avgs[peak_idx]:g}{unit} @ {hours[peak_idx]:02d}h",
                (hours[peak_idx], avgs[peak_idx]), fontsize=8,
                color=COL_DANGER, fontweight="bold", va="center")

    lo, hi = thresholds.get("min"), thresholds.get("max")
    if hi is not None:
        ax.axhline(hi, color=COL_DANGER, ls=":", lw=1, alpha=0.6)
    if lo is not None:
        ax.axhline(lo, color=COL_DANGER, ls=":", lw=1, alpha=0.6)

    ax.set_title(title, fontsize=11, fontweight="bold", color=TEXT, pad=10)
    ax.set_xlabel("Hora del día", fontsize=9, color=TEXT)
    ax.set_ylabel(unit, fontsize=9, color=TEXT)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.legend(fontsize=7.5, facecolor=BG_LIGHT, edgecolor=GRID, labelcolor=TEXT)
    _clean_axes(ax)
    fig.tight_layout()
    return _save(fig)


def chart_weekly_compare(weekly: list, title: str, unit: str) -> bytes:
    """Barras por semana, % tiempo en rango. Mejor verde, peor roja."""
    if not weekly or len(weekly) < 2:
        return b""  # solo tiene sentido con 2+ semanas
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = []
    for w in weekly:
        # "2026-W21" -> "Sem 21"
        wk = w["week"].split("-W")[-1]
        labels.append(f"Sem {wk}")
    pcts = [w["in_range_pct"] for w in weekly]
    colors = []
    for w in weekly:
        if w.get("is_best"):
            colors.append(COL_OK)
        elif w.get("is_worst"):
            colors.append(COL_DANGER)
        else:
            colors.append("#94a3b8")

    fig, ax = plt.subplots(figsize=(8.5, 3.0), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    bars = ax.bar(labels, pcts, color=colors, edgecolor="white", linewidth=1)
    for bar, w in zip(bars, weekly):
        tag = ""
        if w.get("is_best"):
            tag = " ★ mejor"
        elif w.get("is_worst"):
            tag = " ▼ peor"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{w['in_range_pct']:g}%{tag}", ha="center", va="bottom",
                fontsize=8, color=TEXT, fontweight="bold")

    ax.set_title(title + " (% tiempo en rango óptimo)", fontsize=11,
                 fontweight="bold", color=TEXT, pad=10)
    ax.set_ylabel("% en rango", fontsize=9, color=TEXT)
    ax.set_ylim(0, 110)
    ax.tick_params(colors=TEXT, labelsize=8)
    _clean_axes(ax)
    fig.tight_layout()
    return _save(fig)


def chart_range_donut(group_history: dict, exclude: tuple, title: str) -> bytes:
    """Donut: % tiempo en rango vs fuera de rango (sensores interiores)."""
    if not group_history:
        return b""
    total_n = 0
    outside_weighted = 0.0
    for var, stats in group_history.items():
        if var in exclude:
            continue
        n = stats.get("n", 0)
        total_n += n
        outside_weighted += stats.get("time_outside_pct", 0) / 100 * n
    if total_n == 0:
        return b""
    out_pct = outside_weighted / total_n * 100
    in_pct = 100 - out_pct

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(4.0, 3.2), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)

    wedges, _ = ax.pie(
        [in_pct, out_pct],
        colors=[COL_OK, COL_DANGER],
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": BG_LIGHT, "linewidth": 2},
    )
    # Texto central
    ax.text(0, 0.08, f"{in_pct:.0f}%", ha="center", va="center",
            fontsize=24, fontweight="bold", color=COL_OK)
    ax.text(0, -0.22, "en rango", ha="center", va="center",
            fontsize=9, color=TEXT)
    ax.set_title(title, fontsize=10, fontweight="bold", color=TEXT, pad=8)
    fig.tight_layout()
    return _save(fig)


def chart_alerts_by_sensor(data: dict) -> bytes:
    """Barras horizontales: transiciones por sensor."""
    counts = (data.get("alerts") or {}).get("transitions_by_var") or {}
    if not counts:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    items = sorted(counts.items(), key=lambda kv: kv[1])
    vars_ = [k for k, _ in items]
    vals = [v for _, v in items]
    colors = [COL_TEMP if v.startswith("t") else COL_HUM for v in vars_]

    fig, ax = plt.subplots(figsize=(8.5, max(2.2, 0.45 * len(vars_) + 1)), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    bars = ax.barh(vars_, vals, color=colors, edgecolor="white", linewidth=1)
    for bar, v in zip(bars, vals):
        ax.text(v + 0.05, bar.get_y() + bar.get_height() / 2, str(v),
                va="center", fontsize=9, color=TEXT, fontweight="bold")

    ax.set_title("Veces que cada sensor cambió de estado", fontsize=11,
                 fontweight="bold", color=TEXT, pad=10)
    ax.set_xlabel("Número de cambios", fontsize=9, color=TEXT)
    ax.tick_params(colors=TEXT, labelsize=9)
    _clean_axes(ax)
    ax.spines["bottom"].set_visible(True)
    fig.tight_layout()
    return _save(fig)


# ---------- helpers ----------

def _clean_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(True, color=GRID, alpha=0.3, linewidth=0.5)
    ax.set_axisbelow(True)


def _save(fig) -> bytes:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG_LIGHT, dpi=120)
    plt.close(fig)
    return buf.getvalue()


def _to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"
