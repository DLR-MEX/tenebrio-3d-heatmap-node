"""FastAPI app: dashboard + SSE de predicciones en tiempo real."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.agent import AgentService
from app.service import Config, PredictionService, setup_logging


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
INDEX_HTML = STATIC_DIR / "index.html"

service: Optional[PredictionService] = None
agent: Optional[AgentService] = None
report_scheduler = None  # type: Optional['ReportScheduler']


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service, agent, report_scheduler
    cfg = Config.load()
    setup_logging(cfg.log_level)
    service = PredictionService(cfg)
    service.attach_loop(asyncio.get_running_loop())
    service.start()
    agent = AgentService(
        api_key=cfg.ollama_api_key,
        host=cfg.ollama_host,
        model=cfg.ollama_model,
        enabled=cfg.agent_enabled,
        prediction_service=service,
        alert_log=service.alert_log,
    )
    # Construir listener bidireccional (depende de agent + telegram_bot_token)
    service.attach_agent(agent)

    # ReportScheduler: persistencia SQLite, los jobs sobreviven reinicios.
    # Se inicia DESPUES de agent y service para que el callback pueda
    # accederlos.
    try:
        from app.reports.scheduler import ReportScheduler, set_global_scheduler
        jobs_db = Path(__file__).resolve().parent.parent / "reports" / "jobs.sqlite"

        # Telegram sender (Fase 5): si el notifier existe, usamos su metodo
        # send_document. El scheduler lo invoca cuando deliver_to incluye
        # 'telegram'. No requiere que el listener bidireccional este activo.
        def _telegram_sender(pdf_bytes: bytes, filename: str, caption: str) -> None:
            if service is not None and service.telegram and service.telegram.bot_token:
                service.telegram.send_document(pdf_bytes, filename, caption)
            else:
                logging.getLogger("reports.scheduler").info(
                    "Schedule queria mandar a Telegram pero notifier no configurado"
                )

        report_scheduler = ReportScheduler(
            db_path=jobs_db,
            generator_fn=_generate_report_sync,  # definido mas abajo
            telegram_sender=_telegram_sender,
        )
        set_global_scheduler(report_scheduler)
        report_scheduler.start()
        # Cleanup oportunista de PDFs viejos
        _cleanup_old_reports()
    except Exception as e:
        logging.getLogger("reports.scheduler").error("No se pudo iniciar scheduler: %s", e)
        report_scheduler = None

    try:
        yield
    finally:
        if report_scheduler is not None:
            report_scheduler.stop()
        if agent is not None:
            agent.close()
        service.stop()


app = FastAPI(title="Tenebris AI Sentinel", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(INDEX_HTML, media_type="text/html")


@app.get("/api/state")
async def api_state():
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)
    return service.snapshot()


@app.get("/api/stream")
async def api_stream(request: Request):
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)
    queue = service.subscribe()

    async def event_gen():
        try:
            # Envia snapshot inicial
            yield {"event": "snapshot", "data": json.dumps(service.snapshot())}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": "update", "data": json.dumps(payload)}
        finally:
            service.unsubscribe(queue)

    return EventSourceResponse(event_gen())


@app.get("/healthz")
async def healthz():
    if service is None:
        return {"ok": False}
    return {"ok": True, "mqtt_connected": service.mqtt_connected}


# --- Reportes ejecutivos PDF ---------------------------------------------
# El agente IA (via tool generate_report) o el cliente (via REST) pueden
# pedir un PDF ejecutivo para un periodo. Genera con Playwright a partir
# de un template Jinja2 + matplotlib charts embebidos.

from fastapi.responses import StreamingResponse  # noqa: E402

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "output"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
MAX_REPORT_DAYS = 31
REPORTS_RETENTION_DAYS = 30  # PDFs viejos se borran al arranque


def _cleanup_old_reports() -> int:
    """Borra PDFs y previews mas viejos que REPORTS_RETENTION_DAYS.
    Devuelve cuantos archivos borro."""
    cutoff = time.time() - REPORTS_RETENTION_DAYS * 86400
    deleted = 0
    for f in REPORTS_DIR.glob("*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except Exception:
            pass
    if deleted:
        logging.getLogger("reports").info(
            "Cleanup: %d archivos viejos borrados (>%d dias)",
            deleted, REPORTS_RETENTION_DAYS,
        )
    return deleted


@app.post("/api/reports/generate")
async def post_reports_generate(request: Request):
    """POST /api/reports/generate

    Body: {start_iso?, end_iso?, hours?, title?}
    - Si se da hours: end = now, start = now - hours
    - Si se dan start_iso/end_iso (formato 'YYYY-MM-DD' o ISO completo): usar esos
    - Default: ultimas 24h

    Returns: {report_id, filename, size_kb, url, preview_url}
    """
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "body debe ser objeto"}, status_code=400)

    # Resolver rango temporal
    now = time.time()
    if "hours" in body:
        try:
            hours = float(body["hours"])
        except (TypeError, ValueError):
            return JSONResponse({"error": "hours debe ser numerico"}, status_code=400)
        end_ts = now
        start_ts = now - hours * 3600
    elif "start_iso" in body and "end_iso" in body:
        try:
            from datetime import datetime
            start_ts = datetime.fromisoformat(body["start_iso"]).timestamp()
            end_ts = datetime.fromisoformat(body["end_iso"]).timestamp()
        except (TypeError, ValueError) as e:
            return JSONResponse({"error": f"fechas ISO invalidas: {e}"}, status_code=400)
    else:
        start_ts = now - 24 * 3600
        end_ts = now

    if end_ts <= start_ts:
        return JSONResponse({"error": "end debe ser mayor a start"}, status_code=400)
    if (end_ts - start_ts) > MAX_REPORT_DAYS * 86400:
        return JSONResponse(
            {"error": f"rango maximo {MAX_REPORT_DAYS} dias"}, status_code=400,
        )

    title = body.get("title")
    include_commentary = bool(body.get("include_commentary", True))

    # Generar en thread para no bloquear el event loop
    try:
        result = await asyncio.to_thread(
            _generate_report_sync, start_ts, end_ts, title, include_commentary,
        )
    except Exception as e:
        logging.getLogger("reports").exception("Error generando reporte")
        return JSONResponse({"error": f"Error: {e}"}, status_code=500)

    return result


def _generate_report_sync(start_ts: float, end_ts: float,
                          title: Optional[str], include_commentary: bool) -> dict:
    """Lo invoca generate_report del agente y el endpoint REST."""
    from app.reports.collector import collect_period_data
    from app.reports.charts import generate_all_charts
    from app.reports.render import render_pdf, save_pdf, generate_preview_png

    data = collect_period_data(service, start_ts, end_ts)
    charts = generate_all_charts(data)

    commentary = {}
    if include_commentary and agent is not None and agent.ready:
        try:
            from app.reports.commentary import generate_commentary
            commentary = generate_commentary(agent, data)
        except ImportError:
            pass  # Fase 2 todavia no implementada
        except Exception as e:
            logging.getLogger("reports").warning("commentary fallo: %s", e)

    pdf_bytes = render_pdf(data, charts, commentary, title)
    pdf_path = save_pdf(pdf_bytes, REPORTS_DIR, start_ts, end_ts)

    # Generar preview PNG (best-effort)
    preview_png = generate_preview_png(pdf_path)
    preview_path = None
    if preview_png:
        preview_path = pdf_path.with_suffix(".preview.png")
        preview_path.write_bytes(preview_png)

    report_id = pdf_path.stem
    return {
        "report_id": report_id,
        "filename": pdf_path.name,
        "size_kb": round(pdf_path.stat().st_size / 1024, 1),
        "url": f"/api/reports/{report_id}",
        "preview_url": f"/api/reports/{report_id}/preview" if preview_png else None,
        "meta": data["meta"],
        "summary": {
            "transitions_to_abnormal": data["alerts"]["transitions_to_abnormal"],
            "jumps_total": data["alerts"]["jumps_total"],
        },
    }


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    """Descarga el PDF binario."""
    if not _safe_report_id(report_id):
        return JSONResponse({"error": "report_id invalido"}, status_code=400)
    path = REPORTS_DIR / f"{report_id}.pdf"
    if not path.exists():
        return JSONResponse({"error": "reporte no encontrado"}, status_code=404)
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=f"{report_id}.pdf",
    )


@app.get("/api/reports/{report_id}/preview")
async def get_report_preview(report_id: str):
    """Devuelve PNG de la primera pagina del PDF (para mostrar en widget)."""
    if not _safe_report_id(report_id):
        return JSONResponse({"error": "report_id invalido"}, status_code=400)
    path = REPORTS_DIR / f"{report_id}.preview.png"
    if not path.exists():
        return JSONResponse({"error": "preview no disponible"}, status_code=404)
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/reports")
async def list_reports():
    """Lista los reportes guardados, ordenados por fecha desc."""
    reports = []
    for pdf in sorted(REPORTS_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = pdf.stat()
        report_id = pdf.stem
        reports.append({
            "report_id": report_id,
            "filename": pdf.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(stat.st_mtime)),
            "url": f"/api/reports/{report_id}",
            "preview_url": f"/api/reports/{report_id}/preview"
                if (REPORTS_DIR / f"{report_id}.preview.png").exists() else None,
        })
    return {"reports": reports[:50]}


_REPORT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_RESERVED_REPORT_IDS = {"schedule", "list", "generate"}

def _safe_report_id(report_id: str) -> bool:
    if report_id in _RESERVED_REPORT_IDS:
        return False
    return bool(_REPORT_ID_PATTERN.match(report_id))


# --- Scheduled reports ---------------------------------------------------

@app.get("/api/schedules")
async def list_schedules():
    if report_scheduler is None:
        return {"schedules": []}
    return {"schedules": report_scheduler.list()}


@app.post("/api/schedules")
async def create_schedule(request: Request):
    if report_scheduler is None:
        return JSONResponse({"error": "scheduler no disponible"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalido"}, status_code=400)

    name = (body.get("name") or "").strip()
    cron = (body.get("cron") or "").strip()
    period_kind = body.get("period_kind", "daily")
    deliver_to = body.get("deliver_to") or ["disk"]
    title = body.get("title")

    if not name:
        return JSONResponse({"error": "name requerido"}, status_code=400)
    # Si pasaron friendly_cron en vez de cron, parsearlo
    if not cron and body.get("friendly_cron"):
        from app.reports.scheduler import parse_friendly_cron
        cron = parse_friendly_cron(body["friendly_cron"])
        if not cron:
            return JSONResponse(
                {"error": f"No reconozco la expresion '{body['friendly_cron']}'. "
                          "Usa formato 'diario 8am', 'lunes 9am', etc."},
                status_code=400,
            )
    if not cron:
        return JSONResponse({"error": "cron o friendly_cron requeridos"}, status_code=400)

    try:
        result = report_scheduler.add(
            name=name, cron=cron, period_kind=period_kind,
            deliver_to=deliver_to, title=title,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Error: {e}"}, status_code=500)
    return result


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    if report_scheduler is None:
        return JSONResponse({"error": "scheduler no disponible"}, status_code=503)
    if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", schedule_id):
        return JSONResponse({"error": "schedule_id invalido"}, status_code=400)
    ok = report_scheduler.remove(schedule_id)
    if not ok:
        return JSONResponse({"error": "schedule no encontrado"}, status_code=404)
    return {"ok": True, "schedule_id": schedule_id}


# --- Ubidots history (cache compartido con Express) -----------------------
# Express tambien necesita histórico para el slider de la vista 3D. En lugar
# de que ambos pegen a Ubidots HTTP (rate-limit doble), Express consume este
# endpoint y nosotros cacheamos 60s. Si el sidecar se cae, Express tiene un
# fallback a Ubidots directo (degradacion graceful — solo se pierde la cache).

_HISTORY_CACHE: dict[tuple[str, int, int], tuple[float, list]] = {}
_HISTORY_CACHE_TTL = 60.0   # segundos
_HISTORY_CACHE_MAX_ENTRIES = 200
_HISTORY_CACHE_LOCK = threading.Lock()
_LABEL_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


@app.get("/api/ubidots-history")
async def get_ubidots_history(var: str, start: int, end: int):
    """GET /api/ubidots-history?var=<label>&start=<ms>&end=<ms>

    Devuelve la lista cruda de Ubidots: [{timestamp, value, ...}, ...].
    Cache TTL 60s por (var, start, end). Es seguro porque el dashboard
    Express normalmente pide rangos discretos (ultimo dia, ultima semana).
    """
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)

    if not _LABEL_PATTERN.match(var):
        return JSONResponse({"error": "var label invalido"}, status_code=400)
    try:
        start_ms = int(start)
        end_ms = int(end)
    except (TypeError, ValueError):
        return JSONResponse({"error": "start/end deben ser enteros (ms)"}, status_code=400)
    if end_ms <= start_ms:
        return JSONResponse({"error": "end debe ser mayor a start"}, status_code=400)
    # Cota razonable: 31 dias (Ubidots permite mas pero no queremos timeouts)
    if (end_ms - start_ms) > 31 * 24 * 3600 * 1000:
        return JSONResponse({"error": "rango maximo 31 dias"}, status_code=400)

    key = (var, start_ms, end_ms)
    now = time.time()

    # Hit?
    with _HISTORY_CACHE_LOCK:
        cached = _HISTORY_CACHE.get(key)
        if cached and (now - cached[0]) < _HISTORY_CACHE_TTL:
            return {"results": cached[1], "cached": True}

    # Miss -> pulla a Ubidots (en thread para no bloquear el loop)
    from app.service import UbidotsHTTP
    http = UbidotsHTTP(service.cfg.token)
    try:
        results = await asyncio.to_thread(
            http.get_values_range_by_label,
            service.cfg.device_label, var, start_ms, end_ms,
        )
    except Exception as e:
        logging.getLogger("ubidots.proxy").error("get_values_range_by_label fallo: %s", e)
        return JSONResponse({"error": str(e)}, status_code=502)

    with _HISTORY_CACHE_LOCK:
        _HISTORY_CACHE[key] = (now, results)
        # Cleanup oportunista: si crecio mucho, podamos los mas viejos
        if len(_HISTORY_CACHE) > _HISTORY_CACHE_MAX_ENTRIES:
            sorted_items = sorted(_HISTORY_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in sorted_items[: len(_HISTORY_CACHE) - _HISTORY_CACHE_MAX_ENTRIES]:
                _HISTORY_CACHE.pop(k, None)
    return {"results": results, "cached": False}


# --- Telegram config ------------------------------------------------------
# La UI lee/edita estos endpoints para configurar el chat_id sin reiniciar.
# El bot_token JAMAS se expone ni se acepta por aqui — solo via .env.

CHAT_ID_PATTERN = re.compile(r"^-?\d{1,20}$")


@app.get("/api/telegram")
async def get_telegram():
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)
    snap = service.telegram.snapshot()
    # Estado del listener bidireccional (puede no existir si no hay bot_token)
    listener = service.telegram_listener
    snap["listener_enabled"] = bool(listener and listener.enabled)
    snap["listener_available"] = listener is not None and bool(agent and agent.ready)
    return snap


@app.post("/api/telegram")
async def post_telegram(request: Request):
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalido"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body debe ser un objeto"}, status_code=400)

    # Rechazar intentos de inyectar bot_token via la API
    if "bot_token" in body or "telegram_bot_token" in body:
        return JSONResponse(
            {"error": "bot_token no se acepta por API. Usa .env"},
            status_code=400,
        )

    chat_id = body.get("chat_id")
    enabled = body.get("enabled")
    cooldown = body.get("cooldown_sec")
    listener_enabled = body.get("listener_enabled")

    # Validacion
    if chat_id is not None:
        chat_id = str(chat_id).strip()
        if chat_id and not CHAT_ID_PATTERN.match(chat_id):
            return JSONResponse(
                {"error": "chat_id debe ser un numero entero (positivo o negativo)"},
                status_code=400,
            )
    if enabled is not None and not isinstance(enabled, bool):
        return JSONResponse({"error": "enabled debe ser true/false"}, status_code=400)
    if listener_enabled is not None and not isinstance(listener_enabled, bool):
        return JSONResponse({"error": "listener_enabled debe ser true/false"}, status_code=400)
    if cooldown is not None:
        try:
            cooldown = float(cooldown)
        except (TypeError, ValueError):
            return JSONResponse({"error": "cooldown_sec debe ser numerico"}, status_code=400)
        if not (30.0 <= cooldown <= 3600.0):
            return JSONResponse({"error": "cooldown_sec debe estar entre 30 y 3600"}, status_code=400)

    return service.update_telegram_settings(
        chat_id=chat_id,
        enabled=enabled,
        cooldown_sec=cooldown,
        listener_enabled=listener_enabled,
    )


@app.post("/api/telegram/test")
async def post_telegram_test():
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)
    ok, message = service.telegram.send_test_message()
    if not ok:
        return JSONResponse({"sent": False, "error": message}, status_code=400)
    return {"sent": True, "message": message}


# --- Agente IA conversacional ---------------------------------------------
# Recibe un mensaje y opcionalmente historial conversacional. Devuelve
# la respuesta del LLM despues de invocar las tools necesarias.

MAX_HISTORY = 20  # mensajes maximos en el array history
MAX_MESSAGE_LEN = 2000


@app.post("/api/agent/chat")
async def post_agent_chat(request: Request):
    if agent is None or not agent.ready:
        return JSONResponse(
            {
                "error": (
                    "Agente IA no configurado. Setea OLLAMA_API_KEY en .env "
                    "y reinicia el sidecar."
                ),
            },
            status_code=503,
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON invalido"}, status_code=400)

    message = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not message:
        return JSONResponse({"error": "campo 'message' es requerido"}, status_code=400)
    if len(message) > MAX_MESSAGE_LEN:
        return JSONResponse(
            {"error": f"message excede {MAX_MESSAGE_LEN} caracteres"},
            status_code=400,
        )
    if not isinstance(history, list):
        return JSONResponse({"error": "history debe ser lista"}, status_code=400)
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    # Sanitizar history: solo dejar role/content
    clean_history = []
    for m in history:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            clean_history.append({"role": role, "content": content[:MAX_MESSAGE_LEN]})

    # Construir mensajes para el agente: history + nueva pregunta
    messages = clean_history + [{"role": "user", "content": message}]

    # chat() es bloqueante (HTTP a Ollama), corremos en thread para no bloquear
    # el event loop de FastAPI
    try:
        result = await asyncio.to_thread(agent.chat, messages)
    except Exception as e:
        logging.getLogger("agent").error("chat() error: %s", e)
        return JSONResponse(
            {"error": f"Agente fallo: {e}"},
            status_code=502,
        )
    return result
