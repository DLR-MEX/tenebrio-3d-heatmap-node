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

import io
import json
import logging
import mimetypes
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
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
        # Si la query va al LLM (no es comando), mostrar "escribiendo..." en
        # Telegram para que el usuario sepa que el bot esta procesando.
        # sendChatAction expira a los ~5s; si el LLM tarda mas, no es critico.
        is_command = text.lstrip().lower().startswith("/")
        if not is_command:
            self._send_chat_action(chat_id_in, "typing")
        charts = []
        try:
            reply, charts = self._dispatch(text)
        except Exception as e:
            log.exception("Error procesando mensaje: %s", e)
            reply = "Disculpa, no pude procesar tu mensaje. Intenta de nuevo."

        # Si el agente emitio gráficas, las mandamos como fotos (con la
        # respuesta como caption de la primera). Si no, mandamos solo texto.
        if charts:
            self._send_photo_action(chat_id_in)
            for i, spec in enumerate(charts):
                try:
                    png = _render_chart_png(spec)
                except Exception as e:
                    log.warning("Render chart fallo: %s", e)
                    png = None
                if png is None:
                    continue
                caption = reply if i == 0 else ""
                self._send_photo(chat_id_in, png, caption)
            # Si no se pudo renderizar ninguna grafica pero hay texto, manda texto
            if reply and not any(charts):
                self._send(chat_id_in, reply)
        elif reply:
            self._send(chat_id_in, reply)

    def _send_chat_action(self, chat_id: str, action: str) -> None:
        """Manda sendChatAction (best-effort, sin esperar respuesta)."""
        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendChatAction"
        body = json.dumps({"chat_id": chat_id, "action": action}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3).close()
        except Exception:
            # No es critico — el indicador es nice-to-have
            pass

    def _send_photo_action(self, chat_id: str) -> None:
        self._send_chat_action(chat_id, "upload_photo")

    def _send_photo(self, chat_id: str, png_bytes: bytes, caption: str = "") -> None:
        """Manda una foto via sendPhoto (multipart/form-data)."""
        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendPhoto"
        boundary = uuid.uuid4().hex
        # Telegram limita caption a 1024 chars en sendPhoto. Truncamos con
        # ellipsis para no perder la respuesta entera.
        if len(caption) > 1020:
            caption = caption[:1020] + "..."
        # Convertir tablas markdown si vienen en el caption (consistencia
        # con _send normal)
        caption = _markdown_tables_to_bullets(caption) if caption else ""

        parts = []
        # Campos texto
        for field, value in (
            ("chat_id", chat_id),
            ("caption", caption),
            ("parse_mode", "Markdown"),
        ):
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode()
            )
            parts.append(value.encode("utf-8"))
            parts.append(b"\r\n")
        # Foto
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="photo"; filename="chart.png"\r\n'
            b"Content-Type: image/png\r\n\r\n"
        )
        parts.append(png_bytes)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if getattr(r, "status", 200) >= 300:
                    log.warning("sendPhoto status=%s", r.status)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            log.warning("sendPhoto HTTP %s: %s body=%s", e.code, e.reason, err_body[:200])
        except Exception as e:
            log.warning("sendPhoto fallo: %s", e)

    def send_document(self, pdf_bytes: bytes, filename: str, caption: str = "") -> None:
        """Envia un PDF via sendDocument (multipart/form-data). Usado por
        el scheduler para entregar reportes programados al chat configurado.
        Si chat_id no esta configurado, no hace nada."""
        if not self.chat_id:
            log.warning("send_document llamado sin chat_id configurado")
            return
        self._send_document(self.chat_id, pdf_bytes, filename, caption)

    def _send_document(self, chat_id: str, pdf_bytes: bytes,
                        filename: str, caption: str = "") -> None:
        """Telegram sendDocument con multipart/form-data."""
        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendDocument"
        boundary = uuid.uuid4().hex
        # Caption limit 1024 chars en Telegram
        caption = _markdown_tables_to_bullets(caption or "")
        if len(caption) > 1020:
            caption = caption[:1020] + "..."

        parts = []
        for field, value in (
            ("chat_id", chat_id),
            ("caption", caption),
            ("parse_mode", "Markdown"),
        ):
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode()
            )
            parts.append(value.encode("utf-8"))
            parts.append(b"\r\n")
        # Documento PDF
        safe_filename = filename.replace('"', "_")
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="document"; filename="{safe_filename}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n".encode()
        )
        parts.append(pdf_bytes)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)

        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        # Indicador de "subiendo documento"
        self._send_chat_action(chat_id, "upload_document")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if getattr(r, "status", 200) >= 300:
                    log.warning("sendDocument status=%s", r.status)
                else:
                    log.info("sendDocument OK: %s (%.1fKB)", filename, len(pdf_bytes) / 1024)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            log.warning("sendDocument HTTP %s: %s body=%s", e.code, e.reason, err_body[:200])
        except Exception as e:
            log.warning("sendDocument fallo: %s", e)

    def _dispatch(self, text: str) -> tuple[str, list[dict]]:
        """Devuelve (reply_text, chart_specs[])."""
        lowered = text.lower().strip()
        # Comandos rapidos (sin tokens del LLM)
        if lowered.startswith("/start") or lowered.startswith("/help"):
            return HELP_TEXT, []
        if lowered.startswith("/status"):
            return self._cmd_status(), []
        if lowered.startswith("/alerts"):
            return self._cmd_alerts(), []

        # Mensaje libre -> agente IA
        if not self.agent or not self.agent.ready:
            return ("El agente IA no esta configurado. Usa /help para ver comandos disponibles.", [])
        result = self.agent.chat([{"role": "user", "content": text}])
        return (result.get("reply") or "(sin respuesta)", result.get("charts") or [])

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
        # Telegram Markdown no soporta tablas pipe-style; las convertimos a
        # bullets para que se lean bien en el chat.
        text_for_telegram = _markdown_tables_to_bullets(text)
        body = json.dumps({
            "chat_id": chat_id,
            "text": text_for_telegram,
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


# --- Helpers --------------------------------------------------------------

def _markdown_tables_to_bullets(text: str) -> str:
    """Convierte tablas pipe-style (| col | col |) a bullets legibles.

    Telegram Markdown no renderiza tablas — las muestra como texto crudo con
    los pipes y los `---`, lo cual es ilegible. Cuando detectamos un bloque
    tabla, lo reemplazamos por:

        *Fila*: col1: val1 · col2: val2 · ...

    Si la primera columna no es relevante (todo "—" o vacia), se omite.
    """
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        # Detectar tabla: linea con | seguida de separador |---|---|
        is_table = (
            "|" in ln
            and i + 1 < len(lines)
            and _is_separator_row(lines[i + 1])
        )
        if not is_table:
            out.append(ln)
            i += 1
            continue

        headers = _split_pipe_row(ln)
        i += 2  # skip header + separator
        body = []
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            body.append(_split_pipe_row(lines[i]))
            i += 1

        # Render: si la primera col luce como un identificador (corta, sin
        # espacios), la usamos como label de cada fila; el resto va en pares
        # "header: valor".
        for row in body:
            if not row:
                continue
            label = row[0] if row else ""
            rest_pairs = []
            for j in range(1, len(headers)):
                if j < len(row) and row[j]:
                    rest_pairs.append(f"{headers[j]}: {row[j]}")
            if label and rest_pairs:
                out.append(f"• *{label}* — " + " · ".join(rest_pairs))
            elif label:
                out.append(f"• {label}")
            elif rest_pairs:
                out.append("• " + " · ".join(rest_pairs))
        # Nota: ignoramos los headers como linea suelta — los reincorporamos
        # como etiqueta de cada par.
    return "\n".join(out)


def _is_separator_row(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # | --- | :---: | --- |   o variantes sin pipes externos
    cells = s.strip("|").split("|")
    return all(re_match(r"^\s*:?-+:?\s*$", c) for c in cells if c is not None)


def _split_pipe_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


# Importado tarde para no traer `re` arriba si nadie lo usa; el modulo ya
# importa otras cosas, una mas no afecta. Lo mantenemos como funcion para
# que el modulo sea autocontenido.
import re as _re  # noqa: E402

def re_match(pattern: str, string: str) -> bool:
    return _re.match(pattern, string) is not None


def _render_chart_png(spec: dict) -> Optional[bytes]:
    """Renderiza un chart_spec a PNG via matplotlib. Devuelve bytes o None
    si el spec no es valido o falla la libreria."""
    if not isinstance(spec, dict):
        return None
    series = spec.get("series") or []
    if not series:
        return None
    try:
        # Backend non-interactive ('Agg') asi no requiere display
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.dates import DateFormatter
        from datetime import datetime
    except ImportError as e:
        log.error("matplotlib no disponible: %s", e)
        return None

    # Estilo oscuro consistente con el dashboard
    fig, ax = plt.subplots(figsize=(8, 4), dpi=110)
    fig.patch.set_facecolor("#1a2630")
    ax.set_facecolor("#243B4A")
    ax.tick_params(colors="#a1aab0", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#5b7888")
    ax.grid(True, color="#5b7888", alpha=0.18, linewidth=0.5)

    plotted = 0
    for s in series:
        data = s.get("data") or []
        if not data:
            continue
        xs = [datetime.fromtimestamp(p[0] / 1000) for p in data]
        ys = [p[1] for p in data]
        linestyle = "--" if s.get("dashed") else "-"
        ax.plot(xs, ys, linestyle=linestyle, color=s.get("color") or "#E8B830",
                linewidth=1.6, label=s.get("name", ""))
        plotted += 1

    if plotted == 0:
        plt.close(fig)
        return None

    # Lineas de umbral
    th = spec.get("thresholds") or {}
    if th.get("min") is not None:
        ax.axhline(y=th["min"], color="#ef4444", linestyle=":", linewidth=1, alpha=0.7)
    if th.get("max") is not None:
        ax.axhline(y=th["max"], color="#ef4444", linestyle=":", linewidth=1, alpha=0.7)

    # Titulo y labels
    title = spec.get("title") or ""
    if title:
        ax.set_title(title, color="#E8B830", fontsize=11, fontweight="bold", pad=10)
    unit = spec.get("unit") or ""
    if unit:
        ax.set_ylabel(unit, color="#a1aab0", fontsize=9)
    if plotted > 1:
        ax.legend(facecolor="#243B4A", edgecolor="#5b7888", labelcolor="#E0E5E8",
                  loc="best", fontsize=8, framealpha=0.85)

    ax.xaxis.set_major_formatter(DateFormatter("%H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)
    return buf.getvalue()
