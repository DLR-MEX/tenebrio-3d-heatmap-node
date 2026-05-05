"""FastAPI app: dashboard + SSE de predicciones en tiempo real."""

from __future__ import annotations

import asyncio
import json
import logging
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
