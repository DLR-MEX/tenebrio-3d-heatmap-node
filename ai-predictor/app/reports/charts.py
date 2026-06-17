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

# Escalas de color FIJAS para los heatmaps (asi un mismo valor = mismo color
# entre graficas y entre reportes). Feedback de Dani: unificar temperaturas.
TEMP_HEATMAP_MAX = 45    # todas las temperaturas (cuarto, exterior, piso, termo)
HEATER_HEATMAP_MAX = 90  # excepcion: el calentador solar corre mucho mas caliente
HUM_HEATMAP_MAX = 100    # humedad siempre 0-100 %


def generate_all_charts(data: dict) -> dict[str, str]:
    """Genera todas las graficas y devuelve {chart_id: data_url}."""
    charts: dict[str, str] = {}
    agg_temp = (data.get("aggregations") or {}).get("TEMP") or {}
    agg_hum = (data.get("aggregations") or {}).get("HUM") or {}
    th_temp = (data.get("thresholds") or {}).get("TEMP") or {}
    th_hum = (data.get("thresholds") or {}).get("HUM") or {}
    # Series exteriores para overlay (interior vs exterior)
    ext_temp = (data.get("exterior") or {}).get("TEMP") or {}
    ext_hum = (data.get("exterior") or {}).get("HUM") or {}
    # Periodo: se imprime como subtitulo en cada grafica
    meta = data.get("meta") or {}
    period = f"{meta.get('start_iso', '')} — {meta.get('end_iso', '')}"

    _try(charts, "temp_heatmap", lambda: chart_heatmap(
        agg_temp.get("heatmap"), "Temperatura por hora y día", "°C", period,
        vmin=0, vmax=TEMP_HEATMAP_MAX,
        opt_lo=th_temp.get("min"), opt_hi=th_temp.get("max")))
    _try(charts, "temp_daily", lambda: chart_daily_bars(
        agg_temp.get("daily"), "Temperatura promedio por día", "°C",
        COL_TEMP, th_temp, period, exterior_daily=ext_temp.get("daily")))
    _try(charts, "temp_hourly", lambda: chart_hourly_profile(
        agg_temp.get("hourly_profile"), "Perfil del día — temperatura", "°C",
        COL_TEMP, th_temp, period,
        exterior_hourly=ext_temp.get("hourly_profile")))
    _try(charts, "temp_in_range", lambda: chart_in_range_bars(
        agg_temp.get("daily"), "Tiempo en rango óptimo por día — temperatura",
        period))
    _try(charts, "temp_weekly", lambda: chart_weekly_compare(
        agg_temp.get("weekly"), "Comparativa semanal — temperatura", period))

    _try(charts, "hum_heatmap", lambda: chart_heatmap(
        agg_hum.get("heatmap"), "Humedad por hora y día", "%", period,
        vmin=0, vmax=HUM_HEATMAP_MAX,
        opt_lo=th_hum.get("min"), opt_hi=th_hum.get("max")))
    _try(charts, "hum_daily", lambda: chart_daily_bars(
        agg_hum.get("daily"), "Humedad promedio por día", "%",
        COL_HUM, th_hum, period, exterior_daily=ext_hum.get("daily")))
    _try(charts, "hum_hourly", lambda: chart_hourly_profile(
        agg_hum.get("hourly_profile"), "Perfil del día — humedad", "%",
        COL_HUM, th_hum, period,
        exterior_hourly=ext_hum.get("hourly_profile")))
    _try(charts, "hum_in_range", lambda: chart_in_range_bars(
        agg_hum.get("daily"), "Tiempo en rango óptimo por día — humedad",
        period))
    _try(charts, "hum_weekly", lambda: chart_weekly_compare(
        agg_hum.get("weekly"), "Comparativa semanal — humedad", period))

    # --- Heatmaps de exterior (TEMP y HUM) ---
    _try(charts, "temp_ext_heatmap", lambda: chart_heatmap(
        ext_temp.get("heatmap"),
        "Temperatura exterior por hora y día", "°C", period,
        vmin=0, vmax=TEMP_HEATMAP_MAX))
    _try(charts, "hum_ext_heatmap", lambda: chart_heatmap(
        ext_hum.get("heatmap"),
        "Humedad exterior por hora y día", "%", period,
        vmin=0, vmax=HUM_HEATMAP_MAX))

    # --- Amoniaco (NH3) ---
    nh3 = ((data.get("air_quality") or {}).get("nh3")) or None
    if nh3:
        _try(charts, "nh3_timeline", lambda: chart_nh3_timeline(nh3, period))
        _try(charts, "nh3_daily", lambda: chart_nh3_daily(nh3, period))

    # --- Heatmaps de infraestructura (termo, calentador, entrada y salida del piso) ---
    infra_hist = data.get("infrastructure_history") or {}
    # (var, chart_id, display, vmax) — el calentador solar usa 0-90; el resto 0-45.
    INFRA_ORDER = [
        ("temperatura5", "infra_termo",       "Termo",                     TEMP_HEATMAP_MAX),
        ("temperatura2", "infra_calentador",  "Calentador solar",          HEATER_HEATMAP_MAX),
        ("temperatura4", "infra_entrada",     "Entrada al piso radiante",  TEMP_HEATMAP_MAX),
        ("temperatura1", "infra_salida",      "Salida del piso radiante",  TEMP_HEATMAP_MAX),
    ]
    for var, chart_id, display, vmax in INFRA_ORDER:
        item = infra_hist.get(var)
        if not item:
            continue
        heatmap = _infra_to_heatmap(item["data"])
        _try(charts, chart_id, lambda hm=heatmap, d=display, vx=vmax: chart_heatmap(
            hm, f"{d} — temperatura por hora y día", "°C", period,
            vmin=0, vmax=vx))

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

def _ideal_anchored_cmap(vmin: float, vmax: float, lo: float, hi: float):
    """Colormap azul->verde->amarillo->rojo donde el VERDE coincide con la
    banda ideal [lo, hi] dentro de la escala [vmin, vmax].

    - Por debajo del ideal: azul -> verde (frio/bajo).
    - Dentro del ideal: verde plano (bueno).
    - Por encima del ideal: verde -> amarillo -> rojo (caliente/alto).
    """
    from matplotlib.colors import LinearSegmentedColormap

    blue, green, yellow, red = "#2563eb", "#22c55e", "#facc15", "#ef4444"
    span = (vmax - vmin) or 1.0
    lo_n = (lo - vmin) / span
    hi_n = (hi - vmin) / span
    # Acotar a (0,1) y garantizar posiciones estrictamente crecientes.
    lo_c = min(max(lo_n, 0.02), 0.90)
    hi_c = min(max(hi_n, lo_c + 0.02), 0.94)
    # Mantener el verde un poco MAS ALLA del tope ideal: asi el limite superior
    # (ej. 30 C / 90 %) se sigue viendo claramente verde y el amarillo entra de
    # forma gradual, no justo en el borde.
    green_end = min(hi_c + (1.0 - hi_c) * 0.18, 0.97)
    stops = [(0.0, blue), (lo_c, green), (green_end, green)]
    yellow_pos = green_end + (1.0 - green_end) * 0.5
    if yellow_pos < 0.999:
        stops.append((yellow_pos, yellow))
    stops.append((1.0, red))
    return LinearSegmentedColormap.from_list("ideal", stops)


def chart_heatmap(heatmap: dict, title: str, unit: str, period: str,
                  vmin: float | None = None, vmax: float | None = None,
                  opt_lo: float | None = None, opt_hi: float | None = None) -> bytes:
    """Heatmap dia (filas) x hora 0-23. Color = valor. Cada celda
    etiquetada con su valor (redondeado).

    Si se pasan vmin/vmax, la escala de color queda FIJA en ese rango (util
    para que un valor signifique siempre el mismo color entre reportes, ej.
    humedad 0-100%). Si se omiten, la escala se auto-ajusta a los datos.

    Si ademas se pasan opt_lo/opt_hi (la banda ideal), el VERDE se ancla a ese
    rango: por debajo del ideal -> azul, dentro del ideal -> verde, por encima
    -> amarillo/rojo. Asi el color coincide con lo que es bueno/malo en vez de
    repartirse linealmente por toda la escala."""
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

    if (opt_lo is not None and opt_hi is not None
            and vmin is not None and vmax is not None):
        cmap = _ideal_anchored_cmap(vmin, vmax, opt_lo, opt_hi)
    else:
        cmap = LinearSegmentedColormap.from_list(
            "clima", ["#2563eb", "#22c55e", "#facc15", "#ef4444"])
    im = ax.imshow(arr, aspect="auto", cmap=cmap, interpolation="nearest",
                   vmin=vmin, vmax=vmax)

    # Etiquetar cada celda con su valor (#3 del feedback)
    import numpy as _np
    valid = arr[~_np.isnan(arr)]
    # Contraste del texto: si la escala es FIJA (vmin/vmax) decidimos segun la
    # posicion normalizada en la rampa de color (los extremos azul/rojo son
    # oscuros -> texto blanco; el centro verde/amarillo es claro -> texto
    # oscuro). Si la escala es automatica, mantenemos la regla previa.
    if vmin is not None and vmax is not None:
        _span = (vmax - vmin) or 1.0

        def _txt_color(v):
            n = (v - vmin) / _span
            return "white" if (n <= 0.18 or n >= 0.82) else "#1a2630"
    else:
        vmid = (float(valid.min()) + float(valid.max())) / 2 if valid.size else 0

        def _txt_color(v):
            return "white" if (v > vmid) else "#1a2630"
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
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=5.5, color=_txt_color(v))

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
                     color: str, thresholds: dict, period: str,
                     exterior_daily: list | None = None) -> bytes:
    """Barras de promedio diario. La banda verde marca el rango IDEAL
    para comparar de un vistazo si cada dia estuvo dentro de lo deseado.

    Si `exterior_daily` viene, dibuja una linea gris encima con el promedio
    diario del exterior (tex/hex) — contexto del clima de afuera.
    """
    if not daily:
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [d["label"] for d in daily]
    avgs = [d["avg"] for d in daily]
    mins = [d["min"] for d in daily]
    maxs = [d["max"] for d in daily]
    # Clamp a 0: si por redondeo (los stats vienen ya redondeados a 2 dec
    # desde aggregations) avg cae fuera del min/max por epsilon, matplotlib
    # rechaza yerr negativo. Clampar evita perder la barra entera.
    err_low = [max(0.0, a - m) for a, m in zip(avgs, mins)]
    err_high = [max(0.0, m - a) for a, m in zip(maxs, avgs)]

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
                  label="interior (promedio diario)",
                  error_kw={"ecolor": "#94a3b8", "elinewidth": 1})
    for bar, a in zip(bars, avgs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{a:g}", ha="center", va="bottom", fontsize=7.5,
                color=TEXT, fontweight="bold")

    # Overlay del exterior: linea gris punteada por dia (si hay datos
    # exteriores que coincidan con los labels).
    if exterior_daily:
        ext_by_label = {d["label"]: d["avg"] for d in exterior_daily}
        ext_vals = [ext_by_label.get(lbl) for lbl in labels]
        if any(v is not None for v in ext_vals):
            xs = [i for i, v in enumerate(ext_vals) if v is not None]
            ys = [v for v in ext_vals if v is not None]
            ax.plot(xs, ys, color=SUBTLE, linestyle="--", marker="o",
                    markersize=4, lw=1.4, label="exterior", zorder=4)

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
                         color: str, thresholds: dict, period: str,
                         exterior_hourly: list | None = None) -> bytes:
    """Curva del dia tipico con area min-max. Marca la hora pico.

    Si `exterior_hourly` viene, dibuja una segunda linea gris punteada con
    el promedio horario del exterior — sirve para ver como el clima de
    afuera influye en el interior.
    """
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
            label="interior (promedio)", zorder=2)

    # Overlay exterior: linea gris punteada del promedio horario afuera
    if exterior_hourly:
        ext_hours = [d["hour"] for d in exterior_hourly]
        ext_avgs = [d["avg"] for d in exterior_hourly]
        if ext_hours:
            ax.plot(ext_hours, ext_avgs, color=SUBTLE, linestyle="--",
                    marker="s", markersize=3, lw=1.5,
                    label="exterior", zorder=3)

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


# ---------- amoniaco (NH3) ----------

def chart_nh3_timeline(nh3: dict, period: str) -> bytes:
    """Linea temporal del NH3 con banda roja sobre el umbral sanitario (25 ppm).
    Marca el pico maximo del periodo."""
    if not nh3 or not nh3.get("data"):
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import datetime

    rows = nh3["data"]
    threshold = nh3.get("threshold", 25.0)
    times = [datetime.fromtimestamp(ts_ms / 1000) for ts_ms, _ in rows]
    vals = [v for _, v in rows]

    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=130)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    # Banda peligrosa por encima del umbral
    top = max(max(vals) * 1.1, threshold * 1.2)
    ax.axhspan(threshold, top, color=COL_DANGER, alpha=0.12, zorder=0,
               label=f"sobre {threshold:g} ppm (alerta)")
    ax.axhline(threshold, color=COL_DANGER, lw=1, linestyle="--", zorder=1)

    ax.plot(times, vals, color="#7c3aed", lw=1.6, zorder=2,
            label="amoniaco (NH3)")
    ax.fill_between(times, [0] * len(vals), vals, color="#7c3aed",
                    alpha=0.12, zorder=1)

    # Marcar pico
    peak_idx = vals.index(max(vals))
    ax.scatter([times[peak_idx]], [vals[peak_idx]], color=COL_DANGER,
               zorder=5, s=55, edgecolor="white", linewidth=1.2)
    ax.annotate(f"  pico: {vals[peak_idx]:.1f} ppm",
                (times[peak_idx], vals[peak_idx]), fontsize=8,
                color=COL_DANGER, fontweight="bold", va="center")

    ax.set_ylabel("ppm", fontsize=9, color=TEXT)
    ax.set_ylim(0, top)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %Hh"))
    fig.autofmt_xdate(rotation=30, ha="right")
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.legend(fontsize=7.5, facecolor=BG_LIGHT, edgecolor=GRID,
              labelcolor=TEXT, loc="upper right")
    _clean_axes(ax)
    _titles(fig, "Amoniaco (NH3) — evolución en el periodo", period)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    return _save(fig)


def chart_nh3_daily(nh3: dict, period: str) -> bytes:
    """Barras del promedio diario de NH3 con linea de umbral."""
    if not nh3 or not nh3.get("data"):
        return b""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import time as _time

    threshold = nh3.get("threshold", 25.0)
    buckets: dict[str, list[float]] = {}
    for ts_ms, v in nh3["data"]:
        day = _time.strftime("%Y-%m-%d", _time.localtime(ts_ms / 1000))
        buckets.setdefault(day, []).append(v)
    if not buckets:
        return b""
    days_sorted = sorted(buckets)
    labels = []
    for d in days_sorted:
        # "Lun 19 may"
        from datetime import datetime
        dt = datetime.strptime(d, "%Y-%m-%d")
        _dow_es = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        _mon_es = ["", "ene", "feb", "mar", "abr", "may", "jun",
                   "jul", "ago", "sep", "oct", "nov", "dic"]
        labels.append(f"{_dow_es[dt.weekday()]} {dt.day} {_mon_es[dt.month]}")
    avgs = [sum(buckets[d]) / len(buckets[d]) for d in days_sorted]
    maxs = [max(buckets[d]) for d in days_sorted]

    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=130)
    fig.patch.set_facecolor(BG_LIGHT)
    ax.set_facecolor(BG_LIGHT)

    colors = [COL_DANGER if mx > threshold else "#7c3aed" for mx in maxs]
    bars = ax.bar(labels, avgs, color=colors, edgecolor="white", linewidth=1,
                  label="promedio del día")
    for bar, a, mx in zip(bars, avgs, maxs):
        tag = "" if mx <= threshold else f" (pico {mx:.0f})"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{a:.1f}{tag}", ha="center", va="bottom", fontsize=7.5,
                color=TEXT, fontweight="bold")

    ax.axhline(threshold, color=COL_DANGER, lw=1.2, linestyle="--",
               label=f"umbral sanitario {threshold:g} ppm")
    ax.set_ylabel("ppm", fontsize=9, color=TEXT)
    ax.tick_params(colors=TEXT, labelsize=8)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    ax.legend(fontsize=7.5, facecolor=BG_LIGHT, edgecolor=GRID,
              labelcolor=TEXT, loc="upper right")
    _clean_axes(ax)
    _titles(fig, "Amoniaco (NH3) — promedio por día", period)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    return _save(fig)


# ---------- helper: serie infra cruda → matriz dia x hora ----------

def _infra_to_heatmap(data: list) -> dict | None:
    """Convierte una serie cruda [(ts_ms, val)] del termo/calentador/piso
    en la misma estructura {days, day_keys, values} que produce el
    aggregations._heatmap del interior, para reusar chart_heatmap()."""
    if not data:
        return None
    import time as _time
    from datetime import datetime

    _DOW_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    cells: dict[tuple, list[float]] = {}
    days_seen: dict[str, str] = {}
    for ts_ms, val in data:
        ts = ts_ms / 1000
        lt = _time.localtime(ts)
        day_key = _time.strftime("%Y-%m-%d", lt)
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
        "values": values,
    }


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
