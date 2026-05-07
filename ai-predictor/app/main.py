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

from app.agent import AgentService
from app.service import Config, PredictionService, setup_logging


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
INDEX_HTML = STATIC_DIR / "index.html"

service: Optional[PredictionService] = None
agent: Optional[AgentService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service, agent
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
    try:
        yield
    finally:
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
