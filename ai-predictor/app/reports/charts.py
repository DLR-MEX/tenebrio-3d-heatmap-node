"""
Generacion de graficas para el reporte ejecutivo PDF.

Variedad de tipos para que cualquier persona lo entienda:
  - Heatmap hora x dia       (con valores etiquetados en cada celda)
  - Barras promedio diario   (con banda del rango ideal sombreada)
  - Perfil horario           (curva del dia tipico)
  - % en rango por dia       (barras, una por dia)
  - Comparativa semanal      (mejor vs peor semana)

Cada grafica lleva el PERIODO en que fue tomada como subtitulo.
Backend matplotlib Agg (server-side). Cada chart -> data URL base64.
Sin emojis — el reporte es un documento profesional.
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
SUBTLE = "#607888"
ACCENT = "#E8B830"
COL_TEMP = "#e07a3f"
COL_HUM = "#3b82f6"
COL_OK = "#16a34a"
COL_WARN = "#f59e0b"
COL_DANGER = "#ef4444"
COL_IDEAL = "#86efac"   # verde claro para la banda del rango ideal


def generate_all_charts(data: dict) -> dict[str, str]:
    """Genera todas las graficas y devuelve {chart_id: data_url}."""
    charts: dict[str, str] = {}
    agg_temp = (data.get("aggregations") or {}).get("TEMP") or {}
    agg_hum = (data.get("aggregations") or {}).get("HUM") or {}
    th_temp = (data.get("thresholds") or {}).get("TEMP") or {}
    th_hum = (data.get("thresholds") or {}).get("HUM") or {}
    # Periodo: se imprime como subtitulo en cada grafica
    meta = data.get("meta") or {}
    period = f"{meta.get('start_iso', '')} — {meta.get('end_iso', '')}"

    _try(charts, "temp_heatmap", lambda: chart_heatmap(
        agg_temp.get("heatmap"), "Temperatura por hora y día", "°C", period))
    _try(charts, "temp_daily", lambda: chart_daily_bars(
        agg_temp.get("daily"), "Temperatura promedio por día", "°C",
        COL_TEMP, th_temp, period))
    _try(charts, "temp_hourly", lambda: chart_hourly_profile(
        agg_temp.get("hourly_profile"), "Perfil del día — temperatura", "°C",
        COL_TEMP, th_temp, period))
    _try(charts, "temp_in_range", lambda: chart_in_range_bars(
        agg_temp.get("daily"), "Tiempo en rango óptimo por día — temperatura",
        period))
    _try(charts, "temp_weekly", lambda: chart_weekly_compare(
        agg_temp.get("weekly"), "Comparativa semanal — temperatura", period))

    _try(charts, "hum_heatmap", lambda: chart_heatmap(
        agg_hum.get("heatmap"), "Humedad por hora y día", "%", period))
    _try(charts, "hum_daily", lambda: chart_daily_bars(
        agg_hum.get("daily"), "Humedad promedio por día", "%",
        COL_HUM, th_hum, period))
    _try(charts, "hum_hourly", lambda: chart_hourly_profile(
        agg_hum.get("hourly_profile"), "Perfil del día — humedad", "%",
        COL_HUM, th_hum, period))
    _try(charts, "hum_in_range", lambda: chart_in_range_bars(
        agg_hum.get("daily"), "Tiempo en rango óptimo por día — humedad",
        period))
    _try(charts, "hum_weekly", lambda: chart_weekly_compare(
        agg_hum.get("weekly"), "Comparativa semanal — humedad", period))

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

def chart_heatmap(heatmap: dict, title: str, unit: str, period: str) -> bytes:
    """Heatmap dia (filas) x hora 0-23. Color = valor. Cada celda
    etiquetada con su valor (redondeado)."""
    if not heatmap or not heatmap.get("values"):
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    days = heatmap["days"]
    values = heatmap["values"]
    arr = np.array([[v if v is not None else np.nan for v in row] for row in values],
                   dtype=float)

    h = max(2.6, min(0.5 * len(days) + 1.4, 8))
    fig, ax = plt.subplots(figsize=(8.5, h), dpi=130)
    fig.patch.set_facecolor(BG_LIGHT)

    cmap = LinearSegmentedColormap.from_list(
        "clima", ["#2563eb", "#22c55e", "#facc15", "#ef4444"])
    im = ax.imshow(arr, aspect="auto", cmap=cmap, interpolation="nearest")

    # Etiquetar cada celda con su valor (#3 del feedback)
    import numpy as _np
    valid = arr[~_np.isnan(arr)]
    if valid.size:
        vmid = (float(valid.min()) + float(valid.max())) / 2
    else:
        vmid = 0
    n_days = len(days)
    # Si hay demasiados dias el texto se encima — lo mostramos solo si
    # la grilla no es excesiva.
    show_labels = n_days <= 16
    if show_labels:
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                v = arr[i, j]
                if _np.isnan(v):
                    continue
                # Texto oscuro sobre colores claros, blanco sobre oscuros
                txt_color = "white" if (v > vmid) else "#1a2630"
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=5.5, color=txt_color)

    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{hh:02d}h" for hh in range(0, 24, 2)], fontsize=7)
    ax.set_yticks(range(len(days)))
    ax.set_yticklabels(days, fontsize=7)
    ax.set_xlabel("Hora del día", fontsize=8, color=TEXT)
    ax.tick_params(colors=TEXT)

    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.ax.tick_params(labelsize=7, colors=TEXT)
    cbar.set_label(unit, fontsize=8, color=TEXT)

    _titles(fig, title, period)
    fig.tight_layout(rect=[0, 0.05, 1, 0.93])
    return _save(fig)


def chart_daily_bars(daily: list, title: str, unit: str,
                     color: str, thresholds: dict, period: str) -> bytes:
    """Barras de promedio diario. La banda verde marca el rango IDEAL
    para comparar de un vistazo si cada dia estuvo dentro de lo deseado."""
    if not daily:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [d["label"] for d in daily]
    avgs = [d["avg"] for d in daily]
    mins = [d["min"] for d in daily]
    maxs = [d["max"] for d in daily]
    err_low = [a - m for a, m in zip(avgs, mins)]
    err_high = [m - a for a, m in zip(maxs, avgs)]

    fig, ax = plt.subplots(figsize=(8.5, 3.6), dpi=130)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    # Banda del rango IDEAL (lo que se busca) — #5 del feedback
    lo, hi = thresholds.get("min"), thresholds.get("max")
    if lo is not None and hi is not None:
        ax.axhspan(lo, hi, color=COL_IDEAL, alpha=0.35, zorder=0,
                   label=f"rango ideal ({lo:g}–{hi:g}{unit})")

    bars = ax.bar(labels, avgs, color=color, edgecolor="white", linewidth=1,
                  yerr=[err_low, err_high], capsize=3, zorder=3,
                  error_kw={"ecolor": "#94a3b8", "elinewidth": 1})
    for bar, a in zip(bars, avgs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{a:g}", ha="center", va="bottom", fontsize=7.5,
                color=TEXT, fontweight="bold")

    ax.set_ylabel(unit, fontsize=9, color=TEXT)
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.legend(fontsize=7.5, facecolor=BG_LIGHT, edgecolor=GRID,
              labelcolor=TEXT, loc="upper right")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    _clean_axes(ax)
    _titles(fig, title, period)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    return _save(fig)


def chart_hourly_profile(hourly: list, title: str, unit: str,
                         color: str, thresholds: dict, period: str) -> bytes:
    """Curva del dia tipico con area min-max. Marca la hora pico."""
    if not hourly:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hours = [d["hour"] for d in hourly]
    avgs = [d["avg"] for d in hourly]
    mins = [d["min"] for d in hourly]
    maxs = [d["max"] for d in hourly]

    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=130)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    lo, hi = thresholds.get("min"), thresholds.get("max")
    if lo is not None and hi is not None:
        ax.axhspan(lo, hi, color=COL_IDEAL, alpha=0.3, zorder=0,
                   label=f"rango ideal")

    ax.fill_between(hours, mins, maxs, color=color, alpha=0.18,
                    label="rango min-máx", zorder=1)
    ax.plot(hours, avgs, color=color, lw=2.2, marker="o", markersize=3,
            label="promedio", zorder=2)

    peak_idx = avgs.index(max(avgs))
    ax.scatter([hours[peak_idx]], [avgs[peak_idx]], color=COL_DANGER,
               zorder=5, s=55, edgecolor="white", linewidth=1.2)
    ax.annotate(f"  hora más alta: {hours[peak_idx]:02d}h ({avgs[peak_idx]:g}{unit})",
                (hours[peak_idx], avgs[peak_idx]), fontsize=8,
                color=COL_DANGER, fontweight="bold", va="center")

    ax.set_xlabel("Hora del día", fontsize=9, color=TEXT)
    ax.set_ylabel(unit, fontsize=9, color=TEXT)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{hh:02d}h" for hh in range(0, 24, 2)])
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.legend(fontsize=7, facecolor=BG_LIGHT, edgecolor=GRID, labelcolor=TEXT)
    _clean_axes(ax)
    _titles(fig, title, period)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    return _save(fig)


def chart_in_range_bars(daily: list, title: str, period: str) -> bytes:
    """Barras: % del tiempo en rango óptimo, una barra por dia.
    Verde si el dia estuvo bien (>=80%), ambar medio, rojo si mal."""
    if not daily:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [d["label"] for d in daily]
    pcts = [d.get("in_range_pct", 0) for d in daily]
    colors = []
    for p in pcts:
        if p >= 80:
            colors.append(COL_OK)
        elif p >= 50:
            colors.append(COL_WARN)
        else:
            colors.append(COL_DANGER)

    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=130)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    bars = ax.bar(labels, pcts, color=colors, edgecolor="white", linewidth=1)
    for bar, p in zip(bars, pcts):
        ax.text(bar.get_x() + bar.get_width() / 2, p + 1.5,
                f"{p:g}%", ha="center", va="bottom", fontsize=8,
                color=TEXT, fontweight="bold")

    ax.set_ylabel("% del tiempo en rango", fontsize=9, color=TEXT)
    ax.set_ylim(0, 112)
    ax.tick_params(colors=TEXT, labelsize=8)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    _clean_axes(ax)
    _titles(fig, title, period)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    return _save(fig)


def chart_weekly_compare(weekly: list, title: str, period: str) -> bytes:
    """Barras por semana, % tiempo en rango. Mejor verde, peor roja."""
    if not weekly or len(weekly) < 2:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [f"Sem {w['week'].split('-W')[-1]}" for w in weekly]
    pcts = [w["in_range_pct"] for w in weekly]
    colors = []
    for w in weekly:
        if w.get("is_best"):
            colors.append(COL_OK)
        elif w.get("is_worst"):
            colors.append(COL_DANGER)
        else:
            colors.append("#94a3b8")

    fig, ax = plt.subplots(figsize=(8.5, 3.0), dpi=130)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    bars = ax.bar(labels, pcts, color=colors, edgecolor="white", linewidth=1)
    for bar, w in zip(bars, weekly):
        tag = ""
        if w.get("is_best"):
            tag = " (mejor)"
        elif w.get("is_worst"):
            tag = " (peor)"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{w['in_range_pct']:g}%{tag}", ha="center", va="bottom",
                fontsize=8, color=TEXT, fontweight="bold")

    ax.set_ylabel("% en rango", fontsize=9, color=TEXT)
    ax.set_ylim(0, 112)
    ax.tick_params(colors=TEXT, labelsize=8)
    _clean_axes(ax)
    _titles(fig, title + " (% tiempo en rango)", period)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    return _save(fig)


# ---------- helpers ----------

def _titles(fig, title: str, period: str):
    """Titulo principal arriba + periodo como footer discreto abajo
    (cuando fueron tomados los datos — #1 del feedback). El periodo va
    abajo para no competir con el titulo."""
    fig.suptitle(title, fontsize=11.5, fontweight="bold", color=TEXT, y=0.985)
    if period:
        fig.text(0.99, 0.015, f"Periodo de los datos: {period}",
                 ha="right", va="bottom", fontsize=6.5,
                 color=SUBTLE, style="italic")


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
    fig.savefig(buf, format="png", facecolor=BG_LIGHT, dpi=130)
    plt.close(fig)
    return buf.getvalue()


def _to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"
