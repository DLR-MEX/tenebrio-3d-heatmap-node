"""
TelegramListener — long polling al Bot API de Telegram.

Vive en un thread daemon. Cada loop hace `getUpdates?offset=&timeout=15`,
procesa los mensajes nuevos del chat autorizado y responde:

  - Comandos rapidos sin LLM (no consumen tokens):
      /status   estado actual de TEMP y HUM
      /alerts   ultimas alertas (24 h por defecto)
      /help     listado de comandos
  - Cualquier otro mensaje => AgentService.chat() y manda la respuesta.

Defensa: rechaza silenciosamente mensajes de chat_ids distintos al
configurado. El bot_token solo vive en .env (jamas en runtime_config).

Persiste `telegram_last_update_id` en runtime_config.json para no
re-procesar mensajes en reinicios.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.agent import AgentService
    from app.service import PredictionService

log = logging.getLogger("telegram.listener")

TELEGRAM_API = "https://api.telegram.org"


HELP_TEXT = (
    "*Tenebris AI Sentinel — comandos*\n"
    "/status — estado actual de los sensores\n"
    "/alerts — alertas de las ultimas 24h\n"
    "/help — esta ayuda\n\n"
    "Tambien puedes preguntarme en lenguaje natural, ej:\n"
    "_¿como esta la temperatura?_\n"
    "_¿hubo anomalias en la humedad ayer?_\n"
    "_promedio de t1 en las ultimas 6 horas_"
)


class TelegramListener:
    """Long-polling thread daemon. start() arranca el thread; stop() lo detiene."""

    POLL_TIMEOUT = 15  # segundos que el server retiene el getUpdates si no hay mensajes
    POLL_RETRY_DELAY = 5  # tras error de red

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        agent: "AgentService",
        prediction_service: "PredictionService",
        alert_log,  # AlertLog (evita import circular en signature)
        save_offset_cb,  # callable(int) -> persiste last_update_id en runtime_config.json
        load_offset_cb,  # callable() -> int (lee last_update_id)
    ):
        self.bot_token = bot_token
        self.chat_id = str(chat_id) if chat_id else ""
        self.agent = agent
        self.prediction_service = prediction_service
        self.alert_log = alert_log
        self._save_offset = save_offset_cb
        self._load_offset = load_offset_cb
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._enabled = False

    # ---- public API ----

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def update_settings(self, chat_id: Optional[str] = None, enabled: Optional[bool] = None) -> None:
        """Hot-reload. Si enabled=True y no esta corriendo, arranca el thread."""
        with self._lock:
            if chat_id is not None:
                self.chat_id = str(chat_id).strip()
            if enabled is not None:
                self._enabled = bool(enabled and self.bot_token and self.chat_id and self.agent and self.agent.ready)

        if self._enabled and (self._thread is None or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="telegram-listener", daemon=True)
            self._thread.start()
            log.info("TelegramListener ACTIVO (chat_id=%s)", "***" if self.chat_id else "(vacio)")
        elif not self._enabled and self._thread and self._thread.is_alive():
            log.info("TelegramListener pidiendo stop (se detendra al siguiente poll)")
            self._stop.set()

    def start(self) -> None:
        """Arranca si la config (constructor) lo permite."""
        if self.bot_token and self.chat_id and self.agent and self.agent.ready:
            self.update_settings(enabled=True)
        else:
            log.info(
                "TelegramListener no arranco (bot_token=%s chat_id=%s agent_ready=%s)",
                bool(self.bot_token), bool(self.chat_id),
                self.agent.ready if self.agent else False,
            )

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            # No bloqueamos demasiado — el thread esta en long-polling
            self._thread.join(timeout=2.0)

    # ---- core loop ----

    def _run(self) -> None:
        offset = self._load_offset() or 0
        log.info("TelegramListener loop iniciado (offset=%d)", offset)
        while not self._stop.is_set():
            if not self.enabled:
                time.sleep(1)
                continue
            try:
                updates = self._get_updates(offset)
            except Exception as e:
                log.warning("getUpdates fallo: %s — retry en %ds", e, self.POLL_RETRY_DELAY)
                self._stop.wait(self.POLL_RETRY_DELAY)
                continue

            for upd in updates:
                upd_id = upd.get("update_id")
                if isinstance(upd_id, int):
                    offset = max(offset, upd_id + 1)
                self._handle_update(upd)

            if updates:
                try:
                    self._save_offset(offset)
                except Exception as e:
                    log.warning("No se pudo persistir last_update_id: %s", e)
        log.info("TelegramListener loop terminado")

    def _get_updates(self, offset: int) -> list[dict]:
        params = urllib.parse.urlencode({
            "offset": offset,
            "timeout": self.POLL_TIMEOUT,
            "allowed_updates": json.dumps(["message"]),
        })
        url = f"{TELEGRAM_API}/bot{self.bot_token}/getUpdates?{params}"
        # timeout HTTP > poll_timeout para que el server tenga margen de cerrar
        with urllib.request.urlopen(url, timeout=self.POLL_TIMEOUT + 10) as r:
            data = json.loads(r.read())
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API: {data.get('description')}")
        return data.get("result", []) or []

    def _handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id_in = str(chat.get("id") or "")
        text = (msg.get("text") or "").strip()
        if not text:
            return  # ignorar stickers, fotos, etc.

        # Defensa: solo aceptamos el chat_id configurado.
        if chat_id_in != self.chat_id:
            log.warning("Mensaje rechazado (chat_id %s no autorizado)", chat_id_in)
            return

        log.info("Mensaje entrante: %r", text[:120])
        try:
            reply = self._dispatch(text)
        except Exception as e:
            log.exception("Error procesando mensaje: %s", e)
            reply = "Disculpa, no pude procesar tu mensaje. Intenta de nuevo."

        if reply:
            self._send(chat_id_in, reply)

    def _dispatch(self, text: str) -> str:
        lowered = text.lower().strip()
        # Comandos rapidos (sin tokens del LLM)
        if lowered.startswith("/start") or lowered.startswith("/help"):
            return HELP_TEXT
        if lowered.startswith("/status"):
            return self._cmd_status()
        if lowered.startswith("/alerts"):
            return self._cmd_alerts()

        # Mensaje libre -> agente IA
        if not self.agent or not self.agent.ready:
            return "El agente IA no esta configurado. Usa /help para ver comandos disponibles."
        result = self.agent.chat([{"role": "user", "content": text}])
        return result.get("reply") or "(sin respuesta)"

    def _cmd_status(self) -> str:
        snap = self.prediction_service.snapshot()
        groups = snap.get("groups") or {}
        lines = ["*Estado actual del cuarto*"]
        for group_name, label, unit in (("TEMP", "Temperatura", "°C"), ("HUM", "Humedad", "%")):
            g = groups.get(group_name) or {}
            cur = g.get("current") or {}
            alerts = g.get("alerts") or {}
            lines.append(f"\n*{label}* ({unit}):")
            if not cur:
                lines.append("  _(sin datos aun)_")
                continue
            for var in g.get("vars") or []:
                v = cur.get(var)
                state = (alerts.get(var) or {}).get("current", "unknown")
                icon = "✅" if state == "ok" else ("🚨" if state == "abnormal" else "❔")
                v_str = f"{v:.2f}" if isinstance(v, (int, float)) else "?"
                lines.append(f"  {icon} {var}: `{v_str}`")
        return "\n".join(lines)

    def _cmd_alerts(self) -> str:
        since_ts = time.time() - 24 * 3600
        rows = self.alert_log.query(since_ts=since_ts, limit=10)
        if not rows:
            return "✅ Sin alertas en las ultimas 24 horas."
        lines = ["*Ultimas alertas (24h):*"]
        for r in rows:
            ts_str = time.strftime("%H:%M", time.localtime(r["ts"]))
            arrow = "→"
            v = r.get("value")
            v_str = f" `{v:.2f}`" if isinstance(v, (int, float)) else ""
            icon = "🚨" if r["new_state"] == "abnormal" else "✅"
            lines.append(
                f"{icon} {ts_str} *{r['var']}* ({r['kind']}): "
                f"{r['prev_state']} {arrow} {r['new_state']}{v_str}"
            )
        return "\n".join(lines)

    def _send(self, chat_id: str, text: str) -> None:
        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendMessage"
        body = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                if getattr(r, "status", 200) >= 300:
                    log.warning("sendMessage status=%s", r.status)
        except urllib.error.HTTPError as e:
            log.warning("sendMessage HTTP %s: %s", e.code, e.reason)
        except Exception as e:
            log.warning("sendMessage fallo: %s", e)
