"""
Render del reporte ejecutivo:
  Jinja2 templates → HTML → Playwright (chromium headless) → PDF

Playwright sustituye WeasyPrint (que tiene problemas con GTK en Windows).
Chromium produce PDFs con soporte CSS3 completo (incluyendo @page,
page-break-*, paginacion, etc).
"""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger("reports.render")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
CSS_FILE = TEMPLATES_DIR / "executive.css"


def render_pdf(data: dict, charts: dict, commentary: Optional[dict] = None,
               title: Optional[str] = None) -> bytes:
    """Renderiza el HTML del reporte y lo convierte a PDF binario.

    data: dict del collector
    charts: dict {chart_id: data_url} del modulo charts
    commentary: dict opcional {summary, events, infrastructure, recommendations}
                con HTML pre-renderizado por el LLM
    title: titulo opcional para portada
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("executive.html")

    css_content = CSS_FILE.read_text(encoding="utf-8")
    if title:
        data["meta"]["title"] = title

    # Pre-calcular % en rango por grupo (Jinja2 no maneja acumuladores bien)
    def pct_in_range(group_history: dict, exclude: set) -> int:
        total_n = 0
        total_outside_weighted = 0.0
        for var, stats in group_history.items():
            if var in exclude:
                continue
            n = stats.get("n", 0)
            outside_pct = stats.get("time_outside_pct", 0)
            total_n += n
            total_outside_weighted += outside_pct / 100 * n
        if total_n == 0:
            return 0
        return int(round(100 - (total_outside_weighted / total_n * 100)))

    ok_pct_temp = pct_in_range(data["history"].get("TEMP", {}), {"tex", "tps", "tpi"})
    ok_pct_hum = pct_in_range(data["history"].get("HUM", {}), {"hex"})

    # Hora más caliente del día (del perfil horario de temperatura)
    hot_hour = None
    hot_hour_val = None
    hourly = (data.get("aggregations", {}).get("TEMP", {}) or {}).get("hourly_profile") or []
    if hourly:
        peak = max(hourly, key=lambda h: h["avg"])
        hot_hour = peak["hour"]
        hot_hour_val = peak["avg"]

    html = template.render(
        meta=data["meta"],
        current=data["current"],
        thresholds=data["thresholds"],
        history=data["history"],
        alerts=data["alerts"],
        predictions_accuracy=data["predictions_accuracy"],
        infrastructure=data.get("infrastructure", {}),
        aggregations=data.get("aggregations", {}),
        charts=charts,
        commentary=commentary or {},
        css_content=css_content,
        ok_pct_temp=ok_pct_temp,
        ok_pct_hum=ok_pct_hum,
        hot_hour=hot_hour,
        hot_hour_val=hot_hour_val,
    )

    # Playwright en thread aparte porque su sync_api no convive con un
    # event loop activo (FastAPI ya tiene uno corriendo).
    from playwright.sync_api import sync_playwright

    pdf_bytes: list[bytes] = []
    def _render():
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                pdf = page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                    prefer_css_page_size=True,
                )
                pdf_bytes.append(pdf)
            finally:
                browser.close()

    import threading
    t = threading.Thread(target=_render)
    t.start()
    t.join(timeout=60)
    if t.is_alive():
        raise RuntimeError("Playwright timeout (>60s)")
    if not pdf_bytes:
        raise RuntimeError("Playwright no produjo PDF")

    log.info("PDF generado: %d bytes (%.1fKB)", len(pdf_bytes[0]), len(pdf_bytes[0]) / 1024)
    return pdf_bytes[0]


def save_pdf(pdf_bytes: bytes, output_dir: Path,
             start_ts: float, end_ts: float) -> Path:
    """Guarda el PDF con un nombre ilustrativo basado en el periodo.

    Formato: reporte-tenebrios_<inicio>_a_<fin>.pdf
      - Periodos de dias completos:  reporte-tenebrios_2026-05-20_a_2026-05-21.pdf
      - Periodos con hora especifica: reporte-tenebrios_2026-05-20-1430_a_2026-05-21-1430.pdf

    El periodo completo ES el identificador: el mismo rango siempre
    produce el mismo archivo (determinista, sobrescribe). Solo usa
    caracteres validos para report_id (letras, numeros, guion, guion-bajo).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    start_lt = time.localtime(start_ts)
    end_lt = time.localtime(end_ts)

    # Si ambos extremos caen exactamente en medianoche (rango de dias
    # completos) omitimos la hora — el nombre queda mas limpio.
    midnight_aligned = (
        start_lt.tm_hour == 0 and start_lt.tm_min == 0
        and end_lt.tm_hour == 0 and end_lt.tm_min == 0
    )
    if midnight_aligned:
        fmt = "%Y-%m-%d"
    else:
        fmt = "%Y-%m-%d-%H%M"

    start_str = time.strftime(fmt, start_lt)
    end_str = time.strftime(fmt, end_lt)
    filename = f"reporte-tenebrios_{start_str}_a_{end_str}.pdf"

    out_path = output_dir / filename
    out_path.write_bytes(pdf_bytes)
    return out_path


def generate_preview_png(pdf_path: Path) -> Optional[bytes]:
    """Genera un PNG de la primera pagina del PDF (para preview en widget)."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(pdf_path))
        if len(pdf) == 0:
            return None
        page = pdf[0]
        # Renderizar a ~640px de ancho (A4 ratio)
        # scale = 640 / 595 (A4 default points) ≈ 1.08
        bitmap = page.render(scale=1.5)
        pil_image = bitmap.to_pil()
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        log.warning("preview PNG fallo: %s", e)
        return None
