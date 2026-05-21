"""
Generacion de graficas para el reporte ejecutivo PDF.

Usa matplotlib backend Agg (server-side) y devuelve cada chart como
data URL base64 para embed directo en el HTML del reporte.

Paleta consistente con el dashboard:
  - Fondo cuarto:   #1a2630 (no usado en charts del PDF — se usa blanco
                    para que el papel impreso se vea bien)
  - Accent dorado:  #E8B830
  - Texto oscuro:   #1a2630 (sobre blanco)
  - Estados:        ok #34d399, warn #f59e0b, danger #ef4444
"""

from __future__ import annotations

import base64
import io
import logging
import time
from datetime import datetime

log = logging.getLogger("reports.charts")

# Paleta para series multiples (consistente con cards.js del dashboard)
SERIES_COLORS = [
    "#0284c7", "#0891b2", "#7c3aed", "#db2777", "#ea580c", "#ca8a04",
    "#16a34a", "#0d9488", "#0369a1", "#1d4ed8", "#7e22ce", "#be123c",
]

THRESHOLD_COLOR = "#ef4444"
ACCENT = "#E8B830"
BG_LIGHT = "#fdfcf7"   # fondo muy claro, levemente crema
GRID_COLOR = "#cbd5e1"
TEXT_DARK = "#1a2630"


def generate_all_charts(data: dict) -> dict[str, str]:
    """Genera todas las graficas del reporte y devuelve dict
    {chart_id: data_url}. Si una falla, se omite (best-effort)."""
    charts: dict[str, str] = {}

    try:
        png = chart_temp_timeline(data)
        if png:
            charts["temp_timeline"] = _to_data_url(png)
    except Exception as e:
        log.warning("chart_temp_timeline fallo: %s", e)

    try:
        png = chart_hum_timeline(data)
        if png:
            charts["hum_timeline"] = _to_data_url(png)
    except Exception as e:
        log.warning("chart_hum_timeline fallo: %s", e)

    try:
        png = chart_alerts_by_sensor(data)
        if png:
            charts["alerts_by_sensor"] = _to_data_url(png)
    except Exception as e:
        log.warning("chart_alerts_by_sensor fallo: %s", e)

    try:
        png = chart_prediction_accuracy(data)
        if png:
            charts["prediction_accuracy"] = _to_data_url(png)
    except Exception as e:
        log.warning("chart_prediction_accuracy fallo: %s", e)

    log.info("Charts generados: %s", list(charts.keys()))
    return charts


# ---------- charts individuales ----------

def chart_temp_timeline(data: dict) -> bytes:
    """Time series de t1..t5 con lineas de umbral (15-30 C)."""
    series = [s for s in (data.get("time_series", {}).get("TEMP") or [])
              if s["var"] not in ("tex", "tps", "tpi") and s["data"]]
    if not series:
        return b""
    thresholds = data.get("thresholds", {}).get("TEMP", {})
    return _line_chart(
        series, "Temperatura interior — periodo del reporte",
        unit="°C",
        threshold_min=thresholds.get("min"),
        threshold_max=thresholds.get("max"),
    )


def chart_hum_timeline(data: dict) -> bytes:
    """Time series de h1..h5 con umbral 60-90%."""
    series = [s for s in (data.get("time_series", {}).get("HUM") or [])
              if s["var"] not in ("hex",) and s["data"]]
    if not series:
        return b""
    thresholds = data.get("thresholds", {}).get("HUM", {})
    return _line_chart(
        series, "Humedad interior — periodo del reporte",
        unit="%",
        threshold_min=thresholds.get("min"),
        threshold_max=thresholds.get("max"),
    )


def chart_alerts_by_sensor(data: dict) -> bytes:
    """Bar chart con conteo de transiciones por sensor."""
    counts = (data.get("alerts") or {}).get("transitions_by_var") or {}
    if not counts:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Ordenar por count desc
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    vars_ = [k for k, _ in items]
    vals = [v for _, v in items]

    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    # Color por tipo de sensor (temp = azulado, hum = rosado)
    colors = ["#0284c7" if v.startswith("t") else "#db2777" for v in vars_]
    bars = ax.bar(vars_, vals, color=colors, edgecolor="white", linewidth=1)

    for bar, val in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.1, str(val),
                ha="center", va="bottom", fontsize=9, color=TEXT_DARK, fontweight="bold")

    ax.set_title("Transiciones de estado por sensor (interior)",
                 color=TEXT_DARK, fontsize=11, fontweight="bold", pad=12)
    ax.set_ylabel("Transiciones", color=TEXT_DARK, fontsize=9)
    ax.tick_params(colors=TEXT_DARK, labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, alpha=0.4, linewidth=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG_LIGHT, dpi=120)
    plt.close(fig)
    return buf.getvalue()


def chart_prediction_accuracy(data: dict) -> bytes:
    """Bar chart con MAE por sensor (precision del modelo GRU)."""
    acc = data.get("predictions_accuracy") or {}
    items = []
    for group in ("TEMP", "HUM"):
        for var, stats in (acc.get(group) or {}).items():
            items.append((var, stats["mae"], group))
    if not items:
        return b""

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    items.sort(key=lambda x: (x[2], x[0]))
    vars_ = [x[0] for x in items]
    maes = [x[1] for x in items]
    colors = ["#0284c7" if g == "TEMP" else "#db2777" for _, _, g in items]

    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    bars = ax.bar(vars_, maes, color=colors, edgecolor="white", linewidth=1)
    for bar, val in zip(bars, maes):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.005, f"{val:.2f}",
                ha="center", va="bottom", fontsize=8, color=TEXT_DARK)

    ax.set_title("Precisión del modelo predictivo (error medio absoluto, +3 min)",
                 color=TEXT_DARK, fontsize=11, fontweight="bold", pad=12)
    ax.set_ylabel("MAE", color=TEXT_DARK, fontsize=9)
    ax.tick_params(colors=TEXT_DARK, labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, alpha=0.4, linewidth=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG_LIGHT, dpi=120)
    plt.close(fig)
    return buf.getvalue()


# ---------- helpers ----------

def _line_chart(series_list: list, title: str, unit: str,
                threshold_min: float = None, threshold_max: float = None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter, AutoDateLocator

    fig, ax = plt.subplots(figsize=(8.5, 3.5), dpi=120)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    for i, s in enumerate(series_list):
        data = s["data"]
        if not data:
            continue
        xs = [datetime.fromtimestamp(p[0] / 1000) for p in data]
        ys = [p[1] for p in data]
        color = SERIES_COLORS[i % len(SERIES_COLORS)]
        ax.plot(xs, ys, color=color, linewidth=1.5, label=s["var"])

    # Umbrales como lineas rojas punteadas
    if threshold_min is not None:
        ax.axhline(y=threshold_min, color=THRESHOLD_COLOR, linestyle=":",
                   linewidth=1, alpha=0.7, label=f"min {threshold_min}")
    if threshold_max is not None:
        ax.axhline(y=threshold_max, color=THRESHOLD_COLOR, linestyle=":",
                   linewidth=1, alpha=0.7, label=f"max {threshold_max}")

    ax.set_title(title, color=TEXT_DARK, fontsize=11, fontweight="bold", pad=10)
    ax.set_ylabel(unit, color=TEXT_DARK, fontsize=9)
    ax.tick_params(colors=TEXT_DARK, labelsize=8)
    ax.legend(loc="best", fontsize=7, frameon=True, facecolor=BG_LIGHT,
              edgecolor=GRID_COLOR, labelcolor=TEXT_DARK, ncol=3)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.grid(True, color=GRID_COLOR, alpha=0.3, linewidth=0.5)
    ax.set_axisbelow(True)

    locator = AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(DateFormatter("%d %b %H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG_LIGHT, dpi=120)
    plt.close(fig)
    return buf.getvalue()


def _to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"
