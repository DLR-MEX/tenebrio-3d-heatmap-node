"""Trae 48h de datos crudos de Ubidots para el sub-sistema de calefaccion
y compara estadisticas para validar que termo (temperatura5) y calentador
(temperatura2) estan reportando datos coherentes.

Uso: python scripts/verify_termo_vs_calentador.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from statistics import mean, median, stdev

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.service import UbidotsHTTP  # noqa: E402


VARS = [
    ("temperatura2", "Calentador solar"),
    ("temperatura5", "Termo"),
    ("temperatura4", "Entrada al cuarto"),
    ("temperatura3", "Medio del piso"),
    ("temperatura1", "Salida del piso"),
    ("tex",          "Exterior (tex)"),
]
HOURS = 48


def fmt_ts(ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))


def quartiles(vals: list[float]) -> tuple[float, float, float]:
    s = sorted(vals)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    return q1, s[n // 2], q3


def main() -> int:
    token = os.getenv("UBIDOTS_TOKEN", "")
    device = os.getenv("UBIDOTS_DEVICE_LABEL", "tenebrios")
    if not token:
        print("FALTA UBIDOTS_TOKEN")
        return 1

    http = UbidotsHTTP(token)
    dev_id = http.get_device_id(device)
    if not dev_id:
        print(f"no encontre device label={device}")
        return 1
    var_map = http.get_variables(dev_id)
    print(f"device={device} ({dev_id})  variables descubiertas={len(var_map)}")
    print()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - HOURS * 3600 * 1000

    series: dict[str, list[tuple[int, float]]] = {}
    for label, display in VARS:
        vid = var_map.get(label)
        if not vid:
            print(f"  {label:14s} ({display:18s})  -> NO existe en Ubidots")
            continue
        rows = http.get_values_range(vid, start_ms, end_ms, max_points=8000)
        series[label] = rows
        if not rows:
            print(f"  {label:14s} ({display:18s})  -> SIN DATOS en ultimas {HOURS}h")

    print()
    print("=" * 90)
    print(f"  Resumen estadistico ultimas {HOURS}h (orden cronologico)")
    print("=" * 90)
    print(f"  {'var':14s} {'display':22s} {'n':>5s} {'min':>7s} {'p25':>7s} {'med':>7s} "
          f"{'p75':>7s} {'max':>7s} {'avg':>7s} {'std':>6s}")
    for label, display in VARS:
        rows = series.get(label, [])
        if not rows:
            continue
        vals = [v for _, v in rows]
        q1, med, q3 = quartiles(vals)
        sd = stdev(vals) if len(vals) > 1 else 0.0
        print(f"  {label:14s} {display:22s} {len(vals):5d} "
              f"{min(vals):7.2f} {q1:7.2f} {med:7.2f} {q3:7.2f} "
              f"{max(vals):7.2f} {mean(vals):7.2f} {sd:6.2f}")

    # Coherencia fisica esperada (cadena de transmision de calor):
    #   Calentador solar (variable, +60C de dia, baja de noche)
    #   -> Termo (acumulador, suaviza, no deberia bajar tanto de noche si esta lleno)
    #   -> Entrada al cuarto (mas frio, perdidas en tuberia)
    #   -> Salida (sale aun mas frio: cedio calor al piso)
    print()
    print("=" * 90)
    print("  Chequeos de coherencia (deltas esperados Calentador -> Termo -> Entrada -> Salida)")
    print("=" * 90)

    # Tomamos los ultimos 60 minutos y promediamos para ver el estado actual
    cutoff_ms = end_ms - 60 * 60 * 1000
    recent = {}
    for label in ("temperatura2", "temperatura5", "temperatura4", "temperatura1"):
        rows = [v for ts, v in series.get(label, []) if ts >= cutoff_ms]
        recent[label] = mean(rows) if rows else None

    def show(label: str, name: str):
        v = recent.get(label)
        if v is None:
            print(f"  {name:22s} -> sin datos recientes")
        else:
            print(f"  {name:22s} -> {v:7.2f} °C")

    print("  Promedio ultimas 1h:")
    show("temperatura2", "Calentador solar")
    show("temperatura5", "Termo")
    show("temperatura4", "Entrada al cuarto")
    show("temperatura1", "Salida del piso")

    cal = recent.get("temperatura2")
    ter = recent.get("temperatura5")
    ent = recent.get("temperatura4")
    sal = recent.get("temperatura1")

    print()
    if cal is not None and ter is not None:
        delta_ct = cal - ter
        if abs(delta_ct) < 1.5:
            judge = "OK (estan cerca, sistema termalizado)"
        elif delta_ct > 0:
            judge = "OK (calentador mas caliente que termo: aporta calor)"
        else:
            judge = "raro (termo mas caliente que calentador): noche/sin sol, validar"
        print(f"  Delta Calentador - Termo = {delta_ct:+.2f}C  -> {judge}")

    if ter is not None and ent is not None:
        delta_te = ter - ent
        if delta_te < 0:
            judge = "RARO: entrada al cuarto mas alta que termo (revisar)"
        elif delta_te < 5:
            judge = "OK (perdida normal en tuberia)"
        else:
            judge = "OJO: perdida grande (>5C), bomba apagada o tuberia descubierta?"
        print(f"  Delta Termo - Entrada    = {delta_te:+.2f}C  -> {judge}")

    if ent is not None and sal is not None:
        delta_es = ent - sal
        if delta_es < 0:
            judge = "RARO: salida mas caliente que entrada (revisar circuito)"
        elif delta_es < 1:
            judge = "OJO: poca caida de temperatura, piso no cediendo calor (bomba parada?)"
        else:
            judge = "OK (piso radiante cediendo calor al cuarto)"
        print(f"  Delta Entrada - Salida   = {delta_es:+.2f}C  -> {judge}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
