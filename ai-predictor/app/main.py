"""FastAPI app: dashboard + SSE de predicciones en tiempo real."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.service import Config, PredictionService, setup_logging


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
INDEX_HTML = STATIC_DIR / "index.html"

service: Optional[PredictionService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    cfg = Config.load()
    setup_logging(cfg.log_level)
    service = PredictionService(cfg)
    service.attach_loop(asyncio.get_running_loop())
    service.start()
    try:
        yield
    finally:
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


# --- Telegram config ------------------------------------------------------
# La UI lee/edita estos endpoints para configurar el chat_id sin reiniciar.
# El bot_token JAMAS se expone ni se acepta por aqui — solo via .env.

CHAT_ID_PATTERN = re.compile(r"^-?\d{1,20}$")


@app.get("/api/telegram")
async def get_telegram():
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)
    return service.telegram.snapshot()


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
    )


@app.post("/api/telegram/test")
async def post_telegram_test():
    if service is None:
        return JSONResponse({"error": "service not ready"}, status_code=503)
    ok, message = service.telegram.send_test_message()
    if not ok:
        return JSONResponse({"sent": False, "error": message}, status_code=400)
    return {"sent": True, "message": message}
