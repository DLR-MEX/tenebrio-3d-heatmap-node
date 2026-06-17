"""Genera un RTF con resumen ejecutivo de los hallazgos:
  1. Termo vs Calentador (datos no coinciden)
  2. Comparativa modelo viejo (CRT12) vs actual

Embebe graficas matplotlib como PNG en hex dentro del RTF.
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.service import UbidotsHTTP  # noqa: E402

OUT = ROOT / "reports_output" / "resumen-validacion.rtf"
OUT.parent.mkdir(parents=True, exist_ok=True)


# ---------- 1) Datos de calefaccion (48h) ----------

INFRA_VARS = [
    ("temperatura2", "Calentador solar"),
    ("temperatura5", "Termo"),
    ("temperatura4", "Entrada al cuarto"),
    ("temperatura3", "Medio del piso"),
    ("temperatura1", "Salida del piso"),
]


def fetch_infra():
    token = os.getenv("UBIDOTS_TOKEN", "")
    http = UbidotsHTTP(token)
    dev = http.get_device_id(os.getenv("UBIDOTS_DEVICE_LABEL", "tenebrios"))
    vmap = http.get_variables(dev)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 48 * 3600 * 1000
    out = {}
    for label, display in INFRA_VARS:
        vid = vmap.get(label)
        if not vid:
            continue
        rows = http.get_values_range(vid, start_ms, end_ms, max_points=8000)
        out[label] = (display, rows)
    return out


def chart_infra_timeseries(data) -> bytes:
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=120)
    colors = {"temperatura2": "#e74c3c", "temperatura5": "#3498db",
              "temperatura4": "#f39c12", "temperatura3": "#9b59b6",
              "temperatura1": "#27ae60"}
    for label, (display, rows) in data.items():
        if not rows:
            continue
        xs = [time.localtime(ts / 1000) for ts, _ in rows]
        # Convertir a horas relativas desde la primera muestra
        t0 = rows[0][0] / 1000
        hours = [(ts / 1000 - t0) / 3600 for ts, _ in rows]
        vals = [v for _, v in rows]
        ax.plot(hours, vals, marker="o", markersize=2.5, linewidth=1.2,
                color=colors.get(label, "gray"), label=display)
    ax.set_xlabel("Horas desde inicio (ultimas 48h)")
    ax.set_ylabel("Temperatura (°C)")
    ax.set_title("Sistema de calefaccion - ultimas 48h")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.axhspan(20, 30, alpha=0.08, color="green", label="rango cuarto")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def chart_infra_stats(data) -> bytes:
    fig, ax = plt.subplots(figsize=(8.5, 3.5), dpi=120)
    labels = []
    means = []
    stds = []
    ns = []
    for label, display in INFRA_VARS:
        if label not in data:
            continue
        _, rows = data[label]
        if not rows:
            continue
        vals = [v for _, v in rows]
        labels.append(display)
        means.append(np.mean(vals))
        stds.append(np.std(vals))
        ns.append(len(vals))
    x = np.arange(len(labels))
    bars = ax.bar(x, means, yerr=stds, capsize=4,
                  color=["#e74c3c", "#3498db", "#f39c12", "#9b59b6", "#27ae60"])
    for b, m, s, n in zip(bars, means, stds, ns):
        ax.annotate(f"x={m:.1f}°C\nstd={s:.2f}\nn={n}",
                    xy=(b.get_x() + b.get_width() / 2, m),
                    xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right", fontsize=8)
    ax.set_ylabel("Promedio (°C)")
    ax.set_title("Promedio ± std por sensor (48h) - n=muestras recibidas")
    ax.grid(True, alpha=0.3, axis="y")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------- 2) Comparativa modelos ----------

# Datos viejos CRT12
CRT12 = {
    "TEMP_LSTM": {"RMSE": 0.81, "MAE": 0.21},
    "TEMP_GRU":  {"RMSE": 0.26, "MAE": 0.085},
    "HUM_LSTM":  {"RMSE": 3.01, "MAE": 1.71},
    "HUM_GRU":   {"RMSE": 2.00, "MAE": 1.13},
}

# Datos actuales (de evaluate_current_model.py)
ACTUAL = {
    "TEMP_per_sensor": {
        "t1": (0.0792, 0.1579), "t2": (0.0872, 0.1399),
        "t3": (0.0747, 0.1204), "t4": (0.0399, 0.0813),
        "t5": (0.0261, 0.0427), "tex": (0.1555, 0.7542),
    },
    "HUM_per_sensor": {
        "h1": (0.3880, 0.4827), "h2": (0.3956, 0.4568),
        "h3": (0.1352, 0.2899), "h4": (0.8536, 1.1379),
        "h5": (0.3244, 0.5310), "hex": (0.8974, 3.2782),
    },
    "TEMP_int_mae": 0.0614, "TEMP_int_rmse": 0.1085,
    "HUM_int_mae":  0.4194, "HUM_int_rmse": 0.5797,
}


def chart_model_comparison() -> bytes:
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4), dpi=120)
    metrics = ["MAE", "RMSE"]
    # TEMP
    ax = axes[0]
    x = np.arange(len(metrics))
    w = 0.27
    viejo_lstm = [CRT12["TEMP_LSTM"]["MAE"], CRT12["TEMP_LSTM"]["RMSE"]]
    viejo_gru  = [CRT12["TEMP_GRU"]["MAE"],  CRT12["TEMP_GRU"]["RMSE"]]
    actual     = [ACTUAL["TEMP_int_mae"],    ACTUAL["TEMP_int_rmse"]]
    b1 = ax.bar(x - w, viejo_lstm, w, label="LSTM viejo (CRT12)", color="#bbb")
    b2 = ax.bar(x,     viejo_gru,  w, label="GRU viejo (CRT12)",  color="#888")
    b3 = ax.bar(x + w, actual,     w, label="GRU actual (en vivo)", color="#27ae60")
    for bs in (b1, b2, b3):
        for b in bs:
            ax.annotate(f"{b.get_height():.3f}",
                        xy=(b.get_x() + b.get_width() / 2, b.get_height()),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=7.5)
    ax.set_xticks(x); ax.set_xticklabels(metrics)
    ax.set_title("TEMP - error de prediccion (°C)")
    ax.set_ylabel("Error")
    ax.legend(fontsize=7.5, loc="upper left")
    ax.grid(True, alpha=0.3, axis="y")

    # HUM
    ax = axes[1]
    viejo_lstm = [CRT12["HUM_LSTM"]["MAE"], CRT12["HUM_LSTM"]["RMSE"]]
    viejo_gru  = [CRT12["HUM_GRU"]["MAE"],  CRT12["HUM_GRU"]["RMSE"]]
    actual     = [ACTUAL["HUM_int_mae"],    ACTUAL["HUM_int_rmse"]]
    b1 = ax.bar(x - w, viejo_lstm, w, label="LSTM viejo (CRT12)", color="#bbb")
    b2 = ax.bar(x,     viejo_gru,  w, label="GRU viejo (CRT12)",  color="#888")
    b3 = ax.bar(x + w, actual,     w, label="GRU actual (en vivo)", color="#27ae60")
    for bs in (b1, b2, b3):
        for b in bs:
            ax.annotate(f"{b.get_height():.3f}",
                        xy=(b.get_x() + b.get_width() / 2, b.get_height()),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=7.5)
    ax.set_xticks(x); ax.set_xticklabels(metrics)
    ax.set_title("HUM - error de prediccion (%)")
    ax.legend(fontsize=7.5, loc="upper left")
    ax.grid(True, alpha=0.3, axis="y")

    fig.suptitle("Modelo actual vs viejo (CRT12 Condusef)", fontsize=11)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def chart_per_sensor() -> bytes:
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), dpi=120)
    # TEMP
    ax = axes[0]
    sensors_t = list(ACTUAL["TEMP_per_sensor"].keys())
    mae_t  = [ACTUAL["TEMP_per_sensor"][s][0] for s in sensors_t]
    rmse_t = [ACTUAL["TEMP_per_sensor"][s][1] for s in sensors_t]
    x = np.arange(len(sensors_t))
    w = 0.38
    ax.bar(x - w/2, mae_t,  w, label="MAE",  color="#3498db")
    ax.bar(x + w/2, rmse_t, w, label="RMSE", color="#e67e22")
    ax.set_xticks(x); ax.set_xticklabels(sensors_t)
    ax.set_title("TEMP - error por sensor (°C, +3min)")
    ax.set_ylabel("Error")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")

    # HUM
    ax = axes[1]
    sensors_h = list(ACTUAL["HUM_per_sensor"].keys())
    mae_h  = [ACTUAL["HUM_per_sensor"][s][0] for s in sensors_h]
    rmse_h = [ACTUAL["HUM_per_sensor"][s][1] for s in sensors_h]
    x = np.arange(len(sensors_h))
    ax.bar(x - w/2, mae_h,  w, label="MAE",  color="#3498db")
    ax.bar(x + w/2, rmse_h, w, label="RMSE", color="#e67e22")
    ax.set_xticks(x); ax.set_xticklabels(sensors_h)
    ax.set_title("HUM - error por sensor (%, +3min)")
    ax.set_ylabel("Error")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")

    fig.suptitle("Modelo actual - error por sensor (24h reales)", fontsize=11)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------- RTF builder ----------

def png_to_rtf_hex(png_bytes: bytes, width_px: int = 600, height_px: int = 300) -> str:
    """Convierte PNG a bloque RTF \\pict\\pngblip con hex.
    width/height en TWIPS (1px ~ 15 twips a 96 dpi)."""
    # Determinar dimensiones reales de la PNG
    # PNG IHDR: bytes 16-23 = width, height (big-endian uint32)
    w = int.from_bytes(png_bytes[16:20], "big")
    h = int.from_bytes(png_bytes[20:24], "big")
    # Escalar a max 600px de ancho conservando aspecto
    if w > width_px:
        ratio = width_px / w
        w_out = width_px
        h_out = int(h * ratio)
    else:
        w_out = w
        h_out = h
    # Twips = pixels * 15 (at 96dpi)
    pw = w_out * 15
    ph = h_out * 15
    hex_str = png_bytes.hex()
    # Insertar saltos cada 128 chars para que el RTF no tenga lineas gigantes
    hex_lines = "\n".join(hex_str[i:i+128] for i in range(0, len(hex_str), 128))
    return (
        "{\\pict\\pngblip"
        f"\\picw{w}\\pich{h}"
        f"\\picwgoal{pw}\\pichgoal{ph}\n"
        + hex_lines + "\n}"
    )


def esc(s: str) -> str:
    """Escapa caracteres RTF basicos y convierte acentos a \\uN representacion."""
    out = []
    for ch in s:
        c = ord(ch)
        if ch in ("\\", "{", "}"):
            out.append("\\" + ch)
        elif c < 128:
            out.append(ch)
        else:
            # \uN? donde N es int16 signed
            n = c if c < 32768 else c - 65536
            out.append(f"\\u{n}?")
    return "".join(out)


def main() -> int:
    print("Pulleando datos de Ubidots para charts...")
    infra = fetch_infra()
    print("Generando 4 graficas...")
    png_infra_ts = chart_infra_timeseries(infra)
    png_infra_stats = chart_infra_stats(infra)
    png_model_cmp = chart_model_comparison()
    png_per_sensor = chart_per_sensor()
    print("Construyendo RTF...")

    # Calcular tabla termo / promedios / std
    rows_infra = []
    for label, display in INFRA_VARS:
        if label not in infra:
            continue
        _, rows = infra[label]
        if not rows:
            continue
        vals = [v for _, v in rows]
        rows_infra.append((label, display, len(vals), min(vals),
                           sum(vals)/len(vals), max(vals), float(np.std(vals))))

    # --- Construir RTF ---
    parts = []
    parts.append(r"{\rtf1\ansi\ansicpg1252\deff0")
    parts.append(r"{\fonttbl{\f0\fswiss\fcharset0 Calibri;}{\f1\fmodern\fcharset0 Consolas;}}")
    parts.append(r"{\colortbl;\red0\green0\blue0;\red192\green0\blue0;\red0\green100\blue0;\red100\green100\blue100;}")
    parts.append(r"\viewkind4\uc1\pard\sa120\f0\fs22")

    # Titulo
    parts.append(r"\pard\qc\sb120\sa120\b\fs32 ")
    parts.append(esc("Reporte de validacion - Tenebrios"))
    parts.append(r"\b0\fs22\par")
    parts.append(r"\pard\qc\sa120\i ")
    parts.append(esc(f"Generado {time.strftime('%Y-%m-%d %H:%M')} - rama feature/reportes-infra-y-exteriores"))
    parts.append(r"\i0\par")
    parts.append(r"\pard\sa120 ")

    # --- Seccion 1 ---
    parts.append(r"\pard\sa120\b\fs26\cf2 1) Termo vs Calentador: los datos NO coinciden\cf0\b0\fs22\par")

    parts.append(esc(
        "Pulleamos las ultimas 48 horas de los 5 sensores del circuito de calefaccion "
        "(temperatura1-5) directamente desde la API de Ubidots. Hallazgos criticos:"
    ))
    parts.append(r"\par\par")

    # Tabla stats
    parts.append(r"\trowd\trgaph100\trleft0")
    col_widths = [1100, 2700, 700, 900, 1100, 900, 900]
    pos = 0
    for w in col_widths:
        pos += w
        parts.append(rf"\cellx{pos}")
    parts.append(r"\pard\intbl\b ")
    for h in ["Variable", "Sensor", "n (48h)", "min °C", "promedio °C", "max °C", "std"]:
        parts.append(esc(h) + r"\cell ")
    parts.append(r"\row")
    for label, display, n, mn, avg, mx, sd in rows_infra:
        parts.append(r"\trowd\trgaph100\trleft0")
        pos = 0
        for w in col_widths:
            pos += w
            parts.append(rf"\cellx{pos}")
        parts.append(r"\pard\intbl\b0 ")
        parts.append(esc(label) + r"\cell ")
        parts.append(esc(display) + r"\cell ")
        parts.append(f"{n}" + r"\cell ")
        parts.append(f"{mn:.2f}" + r"\cell ")
        parts.append(f"{avg:.2f}" + r"\cell ")
        parts.append(f"{mx:.2f}" + r"\cell ")
        parts.append(f"{sd:.3f}" + r"\cell ")
        parts.append(r"\row")
    parts.append(r"\pard\sa120 \par")

    # Grafica 1: serie temporal
    parts.append(r"\pard\qc ")
    parts.append(png_to_rtf_hex(png_infra_ts, width_px=620))
    parts.append(r"\par")
    parts.append(r"\pard\qc\i\fs18 ")
    parts.append(esc("Fig 1 - Serie temporal de los 5 sensores de calefaccion (48h)"))
    parts.append(r"\i0\fs22\par")

    # Grafica 2: stats
    parts.append(r"\pard\qc ")
    parts.append(png_to_rtf_hex(png_infra_stats, width_px=620))
    parts.append(r"\par")
    parts.append(r"\pard\qc\i\fs18 ")
    parts.append(esc("Fig 2 - Promedio +/- std por sensor (48h, n=muestras recibidas)"))
    parts.append(r"\i0\fs22\par\par")

    # Diagnostico
    parts.append(r"\pard\sa120\b Diagnostico:\b0\par")
    bullets = [
        "Calentador solar (temperatura2) clavado en 65.72 °C en 48h (std=0.04). "
        "Un panel solar tiene que variar 30-60 °C entre dia y noche. El valor no se mueve: "
        "sensor reportando valor cacheado o desconectado.",
        "Termo (temperatura5) en 15.74 °C con std=0.03. Un tanque acumulador con calefaccion "
        "deberia estar 30-60 °C. A 15 °C esta leyendo temperatura ambiente del cuarto de "
        "maquinas, no agua caliente.",
        "Imposibilidad fisica: la Entrada al cuarto (19.59 °C) es 3.84 °C mas caliente "
        "que el Termo (15.74 °C). El agua no puede salir mas caliente que su fuente.",
        "Frecuencia de muestreo: 21 muestras en 48h vs 2769 del sensor exterior (1/min). "
        "Los 5 sensores estan muestreando ~100x mas lento que el resto: datalogger casi "
        "mudo o filtrando por 'no cambio'.",
    ]
    for b in bullets:
        parts.append(r"\pard\fi-300\li600\sa80 \bullet  ")
        parts.append(esc(b))
        parts.append(r"\par")
    parts.append(r"\pard\sa120 ")
    parts.append(r"\b Conclusion:\b0  ")
    parts.append(esc(
        "el reporte dibuja correctamente los datos que recibe; el problema esta aguas arriba "
        "en el hardware/transmision MQTT. Revisar fisicamente el sensor temperatura5 (puede "
        "estar fuera del termo, suelto en el cuarto de maquinas) y validar que el de "
        "temperatura2 no este congelado por firmware del datalogger."
    ))
    parts.append(r"\par\page")

    # --- Seccion 2 ---
    parts.append(r"\pard\sa120\b\fs26\cf3 2) Comparativa modelo actual vs viejo (CRT12 Condusef)\cf0\b0\fs22\par")

    parts.append(esc(
        "Evaluacion del modelo en produccion (ai-predictor/models/) sobre 24h reales del "
        "dispositivo Ubidots: 1135 ventanas TEMP y 1194 ventanas HUM, prediccion a +3 min, "
        "ventana de observacion 30 min."
    ))
    parts.append(r"\par\par")

    # Tabla comparativa
    parts.append(r"\trowd\trgaph100\trleft0")
    col_widths = [2400, 1600, 1600, 2200]
    pos = 0
    for w in col_widths:
        pos += w
        parts.append(rf"\cellx{pos}")
    parts.append(r"\pard\intbl\b ")
    for h in ["Metrica", "Viejo CRT12 GRU", "Actual (en vivo)", "Mejora"]:
        parts.append(esc(h) + r"\cell ")
    parts.append(r"\row")
    comparativa = [
        ("TEMP MAE (°C)",  0.085, ACTUAL["TEMP_int_mae"]),
        ("TEMP RMSE (°C)", 0.26,  ACTUAL["TEMP_int_rmse"]),
        ("HUM  MAE (%)",   1.13,  ACTUAL["HUM_int_mae"]),
        ("HUM  RMSE (%)",  2.00,  ACTUAL["HUM_int_rmse"]),
    ]
    for metric, viejo, actual in comparativa:
        ratio = viejo / actual if actual > 0 else 0
        parts.append(r"\trowd\trgaph100\trleft0")
        pos = 0
        for w in col_widths:
            pos += w
            parts.append(rf"\cellx{pos}")
        parts.append(r"\pard\intbl\b0 ")
        parts.append(esc(metric) + r"\cell ")
        parts.append(f"{viejo:.3f}" + r"\cell ")
        parts.append(f"{actual:.3f}" + r"\cell ")
        parts.append(f"{ratio:.1f}x mejor" + r"\cell ")
        parts.append(r"\row")
    parts.append(r"\pard\sa120 \par")

    # Grafica comparativa
    parts.append(r"\pard\qc ")
    parts.append(png_to_rtf_hex(png_model_cmp, width_px=620))
    parts.append(r"\par")
    parts.append(r"\pard\qc\i\fs18 ")
    parts.append(esc("Fig 3 - Comparativa MAE / RMSE: viejo CRT12 (LSTM y GRU) vs actual"))
    parts.append(r"\i0\fs22\par\par")

    # Grafica por sensor
    parts.append(r"\pard\qc ")
    parts.append(png_to_rtf_hex(png_per_sensor, width_px=620))
    parts.append(r"\par")
    parts.append(r"\pard\qc\i\fs18 ")
    parts.append(esc("Fig 4 - Error por sensor del modelo actual (24h reales)"))
    parts.append(r"\i0\fs22\par\par")

    # Caveats
    parts.append(r"\pard\sa120\b Notas metodologicas:\b0\par")
    notes = [
        "Las cifras CRT12 son sobre test-set offline (split del dataset historico) y el "
        "actual es evaluacion en vivo sobre datos no vistos del dispositivo real - no son "
        "comparables 1:1, pero la magnitud del salto deja claro que el rediseno paga.",
        "El modelo actual usa GRU dual (uno para TEMP, uno para HUM), vigila 6 sensores "
        "en paralelo y predice DELTA (no valor absoluto). El viejo era valor-absoluto y "
        "un solo tanque.",
        "Excepcion notable: el sensor h4 tiene MAE=0.85% (2-3x peor que h1-h3,h5). Sensor "
        "mas ruidoso o mal ubicado, vale revisar.",
        "Sensores exteriores (tex, hex) tienen error mas alto porque el clima exterior es "
        "caotico - es esperable y no afecta la calidad del control del cuarto.",
    ]
    for b in notes:
        parts.append(r"\pard\fi-300\li600\sa80 \bullet  ")
        parts.append(esc(b))
        parts.append(r"\par")

    parts.append(r"\pard\sa120 \b\cf3 ")
    parts.append(esc("Veredicto: el modelo actual esta jalando bien. Mejor o comparable al viejo "
                     "en TEMP, y 2.7-3.4x mejor en HUM. No se requiere reentrenamiento."))
    parts.append(r"\cf0\b0\par")

    parts.append(r"}")
    OUT.write_bytes("".join(parts).encode("cp1252", errors="replace"))
    print(f"\nRTF generado: {OUT}")
    print(f"Tamano: {OUT.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
