"""
Servicio de prediccion en tiempo real:
  - Subscribe a Ubidots MQTT, ensambla muestras de los 6 sensores por grupo.
  - Mantiene una ventana deslizante de 30 muestras y predice +3 min.
  - Expone snapshot/state y un broadcast a suscriptores asyncio (SSE).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from tensorflow.keras.models import load_model

from app.alert_log import AlertLog


ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

TEMP_VARS = ["t1", "t2", "t3", "t4", "t5", "tex"]
HUM_VARS = ["h1", "h2", "h3", "h4", "h5", "hex"]

# Variables informativas adicionales del dispositivo (no entran al modelo,
# se muestran como contexto en el dashboard y son consultables por el agente).
# tps = temperatura promedio superior, tpi = temperatura promedio inferior.
# Provienen del mismo device Ubidots que t1..t5.
EXTRA_TEMP_VARS = ["tps", "tpi"]
EXTRA_VAR_LABELS = {
    "tps": "Promedio superior",
    "tpi": "Promedio inferior",
}
LOOK_BACK = 30
STEP_AHEAD = 3
HISTORY_MAX = 240  # ~ ultimas 240 predicciones por grupo en memoria

# Umbrales operativos (rango optimo por sensor). Fuera de este rango el
# valor se clasifica como "abnormal". El modelo GRU emite floats puros;
# la clasificacion vive aqui para que cualquier consumidor (dashboard,
# LangGraph, MQTT republish) reciba la misma senal.
TEMP_OPTIMAL_MIN = 15.0
TEMP_OPTIMAL_MAX = 30.0
HUM_OPTIMAL_MIN = 60.0
HUM_OPTIMAL_MAX = 90.0


def classify(value: float | None, group: str) -> str:
    """Devuelve 'ok' | 'abnormal' | 'unknown' segun el rango operativo."""
    if value is None or not isinstance(value, (int, float)):
        return "unknown"
    if group == "TEMP":
        lo, hi = TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX
    else:  # HUM (cualquier otro grupo cae aqui por simetria)
        lo, hi = HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX
    return "ok" if lo <= value <= hi else "abnormal"


def build_alerts(current: dict, predicted: dict, var_names: list[str], group: str) -> dict:
    """Construye {var: {current, predicted}} aplicando classify() a cada lado."""
    out = {}
    for var in var_names:
        out[var] = {
            "current": classify(current.get(var), group),
            "predicted": classify(predicted.get(var), group),
        }
    return out


# Etiquetas legibles para los grupos en mensajes Telegram
GROUP_LABELS = {"TEMP": "Temperatura", "HUM": "Humedad"}
GROUP_UNITS = {"TEMP": "°C", "HUM": "%"}

# Sensores exteriores (intemperie). Estan en el grupo TEMP/HUM por convenciencia
# del modelo, pero no son alerta legitima — reflejan el clima de afuera. NO se
# notifican via Telegram ni se registran como transiciones en el AlertLog.
EXTERIOR_VARS = {"tex", "hex"}

# Archivo de configuracion mutable en runtime (persiste cambios hechos
# desde la UI). Se sobrescribe sobre los valores de .env al inicio. Nunca
# guarda secretos: el bot_token solo vive en .env.
RUNTIME_CONFIG_PATH = ROOT / "runtime_config.json"
RUNTIME_ALLOWED_KEYS = {
    "telegram_enabled",
    "telegram_chat_id",
    "telegram_cooldown_sec",
    # Si el bot debe responder mensajes entrantes con el agente IA.
    # Default false (opt-in para evitar usar tokens del LLM sin querer).
    "telegram_listener_enabled",
    # Persistencia del cursor de getUpdates (no re-procesar mensajes en reinicio)
    "telegram_last_update_id",
}


def load_runtime_config() -> dict:
    """Lee runtime_config.json. Si no existe o esta corrupto, devuelve {}."""
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        # Filtrar solo claves permitidas (defensa contra payloads corruptos)
        return {k: v for k, v in data.items() if k in RUNTIME_ALLOWED_KEYS}
    except Exception as e:
        logging.getLogger(__name__).warning("runtime_config.json invalido: %s", e)
        return {}


def save_runtime_config(data: dict) -> None:
    """Guarda solo claves permitidas. Crea el archivo si no existe."""
    clean = {k: v for k, v in data.items() if k in RUNTIME_ALLOWED_KEYS}
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(clean, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


log = logging.getLogger(__name__)


# ---------- Telegram ----------

class TelegramNotifier:
    """
    Manda alertas a un chat de Telegram cuando un sensor cambia de estado.

    Diseño:
      - Solo dispara en TRANSICIONES de estado (ok->abnormal o abnormal->ok),
        nunca en cada prediccion. Esto evita spam.
      - Cooldown por sensor: si el valor oscila en la frontera del umbral,
        no manda mensajes hasta que pase `cooldown_sec`.
      - Send no-bloqueante: dispara un thread daemon por mensaje (volumen
        bajo, simple). Si Telegram esta caido, solo se pierde el mensaje.
      - Si esta deshabilitado o sin token, on_alerts() es no-op.
    """

    TELEGRAM_API = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool,
        cooldown_sec: float = 300.0,
        alert_log: Optional[AlertLog] = None,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(enabled and bot_token and chat_id)
        self.cooldown_sec = cooldown_sec
        self._prev_cur: dict[str, str] = {}   # var -> ultimo estado "current"
        self._prev_pred: dict[str, str] = {}  # var -> ultimo estado "predicted"
        self._last_sent: dict[tuple[str, str], float] = {}  # (var, kind) -> ts
        self._lock = threading.Lock()
        # AlertLog persiste TODAS las transiciones (independiente del estado del
        # notifier Telegram — incluso si Telegram esta apagado, queremos
        # registrar las transiciones para que el agente pueda consultarlas)
        self.alert_log = alert_log
        self.log = logging.getLogger("telegram")
        if self.enabled:
            self.log.info("Telegram notifier ACTIVO (cooldown=%.0fs)", cooldown_sec)
        else:
            self.log.info("Telegram notifier deshabilitado (TELEGRAM_ENABLED=false o credenciales vacias)")

    def on_alerts(
        self,
        group: str,
        var_names: list[str],
        current_values: dict,
        predicted_values: dict,
        alerts: dict,
    ) -> None:
        # AlertLog se actualiza SIEMPRE (independiente del estado del notifier
        # Telegram), asi el agente IA puede consultar transiciones aunque
        # Telegram este apagado. Telegram aplica cooldown adicional para
        # limitar mensajes; AlertLog registra cada transicion sin cooldown.
        now = time.time()
        unit = GROUP_UNITS.get(group, "")
        group_label = GROUP_LABELS.get(group, group)

        if group == "TEMP":
            lo, hi = TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX
        else:
            lo, hi = HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX

        with self._lock:
            for var in var_names:
                # Sensores exteriores: solo informativos, no son alerta.
                # Saltamos por completo (ni alert log ni Telegram).
                if var in EXTERIOR_VARS:
                    continue
                cur_state = alerts[var]["current"]
                pred_state = alerts[var]["predicted"]
                cur_val = current_values.get(var)
                pred_val = predicted_values.get(var)

                prev_cur = self._prev_cur.get(var)
                prev_pred = self._prev_pred.get(var)
                self._prev_cur[var] = cur_state
                self._prev_pred[var] = pred_state

                # Persistencia: SQLite alert log (sin cooldown, sin filtros)
                if self.alert_log is not None:
                    if prev_cur is not None and prev_cur != cur_state:
                        self.alert_log.record(
                            ts=now, group_name=group, var=var,
                            prev_state=prev_cur, new_state=cur_state, kind="current",
                            value=cur_val, predicted_value=pred_val,
                        )
                    if prev_pred is not None and prev_pred != pred_state:
                        self.alert_log.record(
                            ts=now, group_name=group, var=var,
                            prev_state=prev_pred, new_state=pred_state, kind="predicted",
                            value=cur_val, predicted_value=pred_val,
                        )

                # Telegram: solo si esta habilitado y con cooldown
                if not self.enabled:
                    continue

                # 1) PELIGRO inmediato: actual paso a abnormal
                if cur_state == "abnormal" and prev_cur != "abnormal":
                    if self._cooldown_ok(var, "current", now):
                        self._send_async(self._fmt_danger(group_label, var, cur_val, lo, hi, unit))
                        self._last_sent[(var, "current")] = now

                # 2) Recuperacion: actual paso de abnormal a ok
                elif cur_state == "ok" and prev_cur == "abnormal":
                    if self._cooldown_ok(var, "current", now):
                        self._send_async(self._fmt_recovered(group_label, var, cur_val, unit))
                        self._last_sent[(var, "current")] = now

                # 3) Alerta anticipada: predicho cambio a abnormal (y actual sigue ok)
                if cur_state == "ok" and pred_state == "abnormal" and prev_pred != "abnormal":
                    if self._cooldown_ok(var, "predicted", now):
                        self._send_async(self._fmt_warn(group_label, var, cur_val, pred_val, lo, hi, unit))
                        self._last_sent[(var, "predicted")] = now

    def _cooldown_ok(self, var: str, kind: str, now: float) -> bool:
        last = self._last_sent.get((var, kind))
        return last is None or (now - last) >= self.cooldown_sec

    def update_settings(
        self,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        cooldown_sec: Optional[float] = None,
    ) -> dict:
        """Hot-reload de la config sin reiniciar el servicio.
        El bot_token NO se acepta aqui — solo se cambia desde .env."""
        with self._lock:
            if chat_id is not None:
                self.chat_id = chat_id.strip()
            if cooldown_sec is not None:
                self.cooldown_sec = float(cooldown_sec)
            if enabled is not None:
                # enabled solo es efectivo si tenemos token y chat_id
                self.enabled = bool(enabled and self.bot_token and self.chat_id)
            else:
                # Si solo cambio chat_id, recalcular enabled
                self.enabled = bool(self.enabled and self.bot_token and self.chat_id)
            self.log.info(
                "Telegram config actualizada: enabled=%s chat_id=%s cooldown=%.0fs",
                self.enabled, "***" if self.chat_id else "(vacio)", self.cooldown_sec,
            )
            return self.snapshot()

    def snapshot(self) -> dict:
        """Estado publicable. Nunca expone el bot_token, solo si esta configurado."""
        return {
            "enabled": self.enabled,
            "chat_id": self.chat_id or "",
            "cooldown_sec": self.cooldown_sec,
            "token_configured": bool(self.bot_token),
        }

    def send_test_message(self) -> tuple[bool, str]:
        """Manda un mensaje de prueba sincronicamente. Devuelve (ok, mensaje)."""
        if not self.bot_token:
            return False, "TELEGRAM_BOT_TOKEN no configurado en .env"
        if not self.chat_id:
            return False, "chat_id no configurado"
        try:
            # Send sincrono para que la UI sepa si funciono
            url = f"{self.TELEGRAM_API}/bot{self.bot_token}/sendMessage"
            body = json.dumps({
                "chat_id": self.chat_id,
                "text": "✨ *Test* — Tenebris AI Sentinel funcionando.\nEste mensaje confirma que el bot puede escribir en este chat.",
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                if getattr(r, "status", 200) >= 300:
                    return False, f"Telegram respondio status={r.status}"
            return True, "Mensaje enviado"
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            return False, f"HTTP {e.code}: {err_body[:200]}"
        except Exception as e:
            return False, f"Error: {e}"

    @staticmethod
    def _fmt_danger(group_label: str, var: str, value, lo: float, hi: float, unit: str) -> str:
        v = f"{value:.2f}{unit}" if isinstance(value, (int, float)) else "?"
        return (
            f"\U0001F6A8 *PELIGRO* — {group_label} anormal\n"
            f"Sensor *{var}* fuera de rango: `{v}`\n"
            f"Rango optimo: {lo:g}–{hi:g} {unit}"
        )

    @staticmethod
    def _fmt_warn(group_label: str, var: str, cur, pred, lo: float, hi: float, unit: str) -> str:
        c = f"{cur:.2f}{unit}" if isinstance(cur, (int, float)) else "?"
        p = f"{pred:.2f}{unit}" if isinstance(pred, (int, float)) else "?"
        return (
            f"⚠️ *Alerta predictiva* — {group_label}\n"
            f"Sensor *{var}* podria salirse en +3min:\n"
            f"actual `{c}` -> predicho `{p}`\n"
            f"Rango optimo: {lo:g}–{hi:g} {unit}"
        )

    @staticmethod
    def _fmt_recovered(group_label: str, var: str, value, unit: str) -> str:
        v = f"{value:.2f}{unit}" if isinstance(value, (int, float)) else "?"
        return (
            f"✅ {group_label} normalizado\n"
            f"Sensor *{var}* regreso al rango: `{v}`"
        )

    def _send_async(self, text: str) -> None:
        # Daemon thread: no bloquea el procesamiento MQTT y al apagar el
        # servicio no impide la salida del proceso.
        threading.Thread(target=self._send, args=(text,), daemon=True).start()

    def _send(self, text: str) -> None:
        url = f"{self.TELEGRAM_API}/bot{self.bot_token}/sendMessage"
        body = json.dumps({
            "chat_id": self.chat_id,
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
            with urllib.request.urlopen(req, timeout=5) as r:
                if getattr(r, "status", 200) >= 300:
                    self.log.warning("Telegram respondio status=%s", r.status)
        except urllib.error.HTTPError as e:
            self.log.warning("Telegram HTTP %s: %s", e.code, e.reason)
        except Exception as e:  # red, timeout, etc.
            self.log.warning("Telegram envio fallo: %s", e)

    def send_document(self, pdf_bytes: bytes, filename: str, caption: str = "") -> None:
        """Envia un documento via sendDocument multipart/form-data. Usado por
        el ReportScheduler. Bloqueante — el caller decide si usar thread."""
        if not self.bot_token or not self.chat_id:
            self.log.warning("send_document sin token/chat_id configurado")
            return
        import uuid as _uuid
        boundary = _uuid.uuid4().hex
        if len(caption) > 1020:
            caption = caption[:1020] + "..."

        parts = []
        for field, value in (
            ("chat_id", self.chat_id),
            ("caption", caption),
            ("parse_mode", "Markdown"),
        ):
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode()
            )
            parts.append(value.encode("utf-8"))
            parts.append(b"\r\n")
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

        url = f"{self.TELEGRAM_API}/bot{self.bot_token}/sendDocument"
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if getattr(r, "status", 200) >= 300:
                    self.log.warning("sendDocument status=%s", r.status)
                else:
                    self.log.info("sendDocument OK: %s (%.1fKB)", filename, len(pdf_bytes) / 1024)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            self.log.warning("sendDocument HTTP %s: %s body=%s", e.code, e.reason, err_body[:200])
        except Exception as e:
            self.log.warning("sendDocument fallo: %s", e)


# ---------- Rate-of-change detector ----------

class RateOfChangeDetector:
    """Capa REACTIVA complementaria al modelo predictivo.

    El GRU predice +3min asumiendo continuidad — saltos abruptos los detecta
    tarde. Este detector mira la diferencia entre muestras CONSECUTIVAS por
    sensor y dispara alerta inmediata si supera el umbral.

    No reemplaza al modelo, lo complementa: el modelo capta tendencias suaves;
    este capta cambios bruscos. Excluye sensores exteriores (tex, hex).
    """

    # Umbral por grupo. Las muestras llegan ~cada 1 min vía MQTT, asi que estos
    # son delta entre lecturas consecutivas del mismo sensor.
    DEFAULT_THRESHOLDS = {"TEMP": 0.5, "HUM": 5.0}
    # Si la muestra previa es muy vieja, no comparamos (probablemente es el
    # primer dato tras reconexion MQTT u otra discontinuidad).
    MAX_GAP_SEC = 5 * 60
    # Cooldown por sensor para no spammear si el ambiente esta inestable.
    COOLDOWN_SEC = 5 * 60

    def __init__(self, alert_log: Optional[AlertLog], thresholds: Optional[dict] = None):
        self.alert_log = alert_log
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._last_seen: dict[str, tuple[float, float]] = {}  # var -> (ts_sec, value)
        self._last_alert: dict[str, float] = {}  # var -> ts_sec
        self._lock = threading.Lock()
        self.log = logging.getLogger("rate-of-change")
        # callback opcional inyectado por PredictionService
        self._on_jump = None  # type: Optional[callable]

    def set_jump_callback(self, cb) -> None:
        """cb(group, var, ts, prev_val, cur_val, delta) -> None
        Lo invoca el PredictionService para enviar Telegram + broadcast SSE."""
        self._on_jump = cb

    def observe(self, group: str, var: str, value: float, ts: Optional[float] = None) -> None:
        """Llamado en cada lectura MQTT. ts en epoch seconds (default: ahora)."""
        if var in EXTERIOR_VARS:
            return
        threshold = self.thresholds.get(group)
        if threshold is None:
            return
        if ts is None:
            ts = time.time()

        # Captura el estado para evaluar fuera del lock
        delta = None
        prev_val = None
        prev_ts = None
        with self._lock:
            prev = self._last_seen.get(var)
            self._last_seen[var] = (ts, value)
            if prev is None:
                return
            prev_ts, prev_val = prev
            dt = ts - prev_ts
            if dt <= 0 or dt > self.MAX_GAP_SEC:
                return
            delta = value - prev_val
            if abs(delta) < threshold:
                return
            last_alert = self._last_alert.get(var, 0.0)
            if (ts - last_alert) < self.COOLDOWN_SEC:
                return
            self._last_alert[var] = ts

        # Llegamos aqui: salto detectado fuera de cooldown
        direction = "subida" if delta > 0 else "bajada"
        self.log.warning(
            "SALTO %s en %s (%s): %.2f -> %.2f en %.0fs (delta %+.2f, umbral %.2f)",
            direction, var, group, prev_val, value, ts - prev_ts, delta, threshold,
        )
        # Persistir en alert_log con kind="jump" — el agente IA lo reportara
        # como evento separado de las transiciones ok<->abnormal.
        if self.alert_log is not None:
            self.alert_log.record(
                ts=ts,
                group_name=group,
                var=var,
                prev_state=f"{prev_val:.2f}",
                new_state=f"{value:.2f}",
                kind="jump",
                value=value,
                predicted_value=delta,  # delta absoluto en el campo predicted_value
            )
        if self._on_jump:
            try:
                self._on_jump(group, var, ts, prev_val, value, delta)
            except Exception as e:
                self.log.warning("on_jump callback fallo: %s", e)


# ---------- Config ----------

@dataclass
class Config:
    token: str
    device_label: str
    broker: str
    port: int
    tls: bool
    publish_predictions: bool
    prefill_from_api: bool
    log_level: str
    bucket_timeout_sec: float
    app_host: str
    app_port: int
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_cooldown_sec: float
    telegram_listener_enabled: bool
    agent_enabled: bool
    ollama_api_key: str
    ollama_host: str
    ollama_model: str

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(ROOT / ".env")
        token = os.getenv("UBIDOTS_TOKEN", "").strip()
        device = os.getenv("UBIDOTS_DEVICE_LABEL", "").strip()
        if not token or token.startswith("BBUS-xxxx"):
            raise RuntimeError("UBIDOTS_TOKEN no configurado en .env")
        if not device:
            raise RuntimeError("UBIDOTS_DEVICE_LABEL no configurado en .env")
        return cls(
            token=token,
            device_label=device,
            broker=os.getenv("UBIDOTS_BROKER", "industrial.api.ubidots.com"),
            port=int(os.getenv("UBIDOTS_PORT", "1883")),
            tls=os.getenv("UBIDOTS_TLS", "false").lower() == "true",
            publish_predictions=os.getenv("PUBLISH_PREDICTIONS", "false").lower() == "true",
            prefill_from_api=os.getenv("PREFILL_FROM_API", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            bucket_timeout_sec=float(os.getenv("BUCKET_TIMEOUT_SEC", "45")),
            app_host=os.getenv("APP_HOST", "0.0.0.0"),
            app_port=int(os.getenv("APP_PORT", "8000")),
            telegram_enabled=os.getenv("TELEGRAM_ENABLED", "false").lower() == "true",
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            telegram_cooldown_sec=float(os.getenv("TELEGRAM_COOLDOWN_SEC", "300")),
            telegram_listener_enabled=os.getenv("TELEGRAM_LISTENER_ENABLED", "false").lower() == "true",
            agent_enabled=os.getenv("AGENT_ENABLED", "true").lower() == "true",
            ollama_api_key=os.getenv("OLLAMA_API_KEY", "").strip(),
            ollama_host=os.getenv("OLLAMA_HOST", "https://ollama.com").strip(),
            ollama_model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b").strip(),
        )

    def with_runtime_overrides(self) -> "Config":
        """Devuelve una copia con runtime_config.json sobrepuesto al .env.
        Solo se sobrescriben claves seguras (nunca el bot_token)."""
        rt = load_runtime_config()
        if not rt:
            return self
        return Config(
            **{
                **self.__dict__,
                "telegram_enabled": bool(rt.get("telegram_enabled", self.telegram_enabled)),
                "telegram_chat_id": str(rt.get("telegram_chat_id", self.telegram_chat_id)),
                "telegram_cooldown_sec": float(rt.get("telegram_cooldown_sec", self.telegram_cooldown_sec)),
                "telegram_listener_enabled": bool(rt.get("telegram_listener_enabled", self.telegram_listener_enabled)),
            }
        )


# ---------- HTTP helper ----------

class UbidotsHTTP:
    def __init__(self, token: str, base: str = "https://industrial.api.ubidots.com"):
        self.token = token
        self.base = base.rstrip("/")
        self.log = logging.getLogger("ubidots.http")

    def _get(self, path: str) -> dict:
        url = f"{self.base}{path}"
        req = urllib.request.Request(url, headers={"X-Auth-Token": self.token})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def get_device_id(self, label: str) -> Optional[str]:
        try:
            data = self._get(f"/api/v2.0/devices/?label={label}")
        except urllib.error.HTTPError as e:
            self.log.error("Error consultando device %s: %s", label, e)
            return None
        results = data.get("results", [])
        if not results:
            return None
        return results[0]["id"]

    def get_variables(self, device_id: str) -> dict[str, str]:
        try:
            data = self._get(
                f"/api/v2.0/devices/{device_id}/variables/?page_size=200&fields=id,label"
            )
        except urllib.error.HTTPError as e:
            self.log.error("Error listando variables: %s", e)
            return {}
        return {v["label"]: v["id"] for v in data.get("results", [])}

    def get_last_values(self, variable_id: str, n: int) -> list[tuple[int, float]]:
        try:
            data = self._get(f"/api/v1.6/variables/{variable_id}/values/?page_size={n}")
        except urllib.error.HTTPError as e:
            self.log.error("Error fetching values var=%s: %s", variable_id, e)
            return []
        rows = [(int(r["timestamp"]), float(r["value"])) for r in data.get("results", [])]
        rows.reverse()
        return rows

    def get_values_range(
        self, variable_id: str, start_ms: int, end_ms: int, max_points: int = 5000
    ) -> list[tuple[int, float]]:
        """Devuelve (timestamp_ms, value) en el rango [start_ms, end_ms].
        Pagina la respuesta de Ubidots; corta en max_points para no inflar
        la memoria si el usuario pide rangos huge."""
        rows: list[tuple[int, float]] = []
        # Ubidots permite end y start en /values/?start=&end=&page_size=
        page_size = min(max_points, 1000)
        try:
            url = (
                f"/api/v1.6/variables/{variable_id}/values/"
                f"?start={start_ms}&end={end_ms}&page_size={page_size}"
            )
            data = self._get(url)
            for r in data.get("results", []):
                rows.append((int(r["timestamp"]), float(r["value"])))
                if len(rows) >= max_points:
                    break
        except urllib.error.HTTPError as e:
            self.log.error("Error fetching range var=%s: %s", variable_id, e)
            return []
        rows.reverse()  # Ubidots devuelve descendente; queremos ascendente
        return rows

    def get_values_range_by_label(
        self, device_label: str, var_label: str, start_ms: int, end_ms: int,
        max_points: int = 5000,
    ) -> list[dict]:
        """Igual que get_values_range pero usando device label + var label
        (no requiere var_id). Devuelve la lista cruda de Ubidots para ser
        consumida por Express (que ya espera ese formato).

        Cada item tiene al menos {timestamp, value}. Ascendente por ts.
        """
        page_size = min(max_points, 1000)
        try:
            url = (
                f"/api/v1.6/devices/{device_label}/{var_label}/values/"
                f"?start={start_ms}&end={end_ms}&page_size={page_size}"
            )
            data = self._get(url)
            results = data.get("results", []) or []
            # Ubidots devuelve descendente; ordenamos ascendente por ts.
            results.sort(key=lambda r: r.get("timestamp") or 0)
            if len(results) > max_points:
                results = results[:max_points]
            return results
        except urllib.error.HTTPError as e:
            self.log.error("Error fetching range device=%s var=%s: %s", device_label, var_label, e)
            return []
        except Exception as e:
            self.log.error("Error inesperado var=%s: %s", var_label, e)
            return []


# ---------- Buffer ----------

@dataclass
class SampleBucket:
    var_names: list[str]
    timeout_sec: float
    values: dict[str, float] = field(default_factory=dict)
    started_at: Optional[float] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def update(self, var: str, value: float) -> Optional[list[float]]:
        with self.lock:
            now = time.monotonic()
            if self.started_at is None or (now - self.started_at) > self.timeout_sec:
                self.values = {}
                self.started_at = now
            self.values[var] = value
            if all(v in self.values for v in self.var_names):
                vec = [self.values[v] for v in self.var_names]
                self.values = {}
                self.started_at = None
                return vec
            return None


# ---------- Predictor ----------

class Predictor:
    def __init__(self, model_path: Path, scaler_path: Path, var_names: list[str], group: str):
        self.log = logging.getLogger(f"predictor.{group}")
        self.log.info("Cargando modelo %s y scaler %s", model_path.name, scaler_path.name)
        self.model = load_model(model_path)
        self.scaler = joblib.load(scaler_path)
        self.var_names = var_names
        self.group = group
        self.window: deque[list[float]] = deque(maxlen=LOOK_BACK)

    def add_sample(self, sample: list[float]) -> Optional[dict]:
        self.window.append(sample)
        filled = len(self.window)
        if filled < LOOK_BACK:
            self.log.info("[%s] buffer %d/%d", self.group, filled, LOOK_BACK)
            return None
        return self._predict()

    def _predict(self) -> dict:
        raw = np.array(self.window, dtype=np.float32)
        scaled = self.scaler.transform(raw)
        delta = self.model.predict(scaled[None, ...], verbose=0)[0]
        future_scaled = scaled[-1] + delta
        pred = self.scaler.inverse_transform(future_scaled.reshape(1, -1))[0]
        current = raw[-1]
        return {
            "current": {var: float(current[i]) for i, var in enumerate(self.var_names)},
            "predicted": {var: float(pred[i]) for i, var in enumerate(self.var_names)},
        }


# ---------- Servicio principal ----------

class PredictionService:
    """MQTT + predictor + estado compartido + broadcast a suscriptores asyncio."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.log = logging.getLogger("ubidots")

        self.temp_predictor = Predictor(
            MODELS_DIR / "model_t.keras",
            MODELS_DIR / "scaler_t.save",
            TEMP_VARS,
            "TEMP",
        )
        self.hum_predictor = Predictor(
            MODELS_DIR / "model_h.keras",
            MODELS_DIR / "scaler_h.save",
            HUM_VARS,
            "HUM",
        )
        self.temp_bucket = SampleBucket(TEMP_VARS, cfg.bucket_timeout_sec)
        self.hum_bucket = SampleBucket(HUM_VARS, cfg.bucket_timeout_sec)

        # SQLite local para persistencia de transiciones de estado.
        # Alimenta al agente IA para responder "hubo anomalias ayer?".
        self.alert_log = AlertLog(ROOT / "alert_log.sqlite")

        # Detector de saltos abruptos (capa reactiva complementaria al GRU).
        # El GRU es buen prediciendo tendencias suaves pero suaviza saltos
        # — este detector dispara alerta inmediata cuando el delta entre
        # muestras consecutivas supera el umbral.
        self.rate_detector = RateOfChangeDetector(alert_log=self.alert_log)
        self.rate_detector.set_jump_callback(self._on_rate_jump)

        # Aplicar runtime_config.json (cambios persistidos desde la UI)
        # encima de los valores de .env. El bot_token nunca se sobrescribe.
        effective_cfg = cfg.with_runtime_overrides()
        self.effective_cfg = effective_cfg
        self.telegram = TelegramNotifier(
            bot_token=cfg.telegram_bot_token,  # siempre del .env
            chat_id=effective_cfg.telegram_chat_id,
            enabled=effective_cfg.telegram_enabled,
            cooldown_sec=effective_cfg.telegram_cooldown_sec,
            alert_log=self.alert_log,
        )
        # Listener bidireccional. Se construye en attach_agent() porque
        # depende del AgentService, que se crea despues del PredictionService
        # en main.lifespan().
        self.telegram_listener = None  # type: Optional["TelegramListener"]

        # estado compartido
        self._state_lock = threading.Lock()
        self.latest: dict[str, dict] = {
            "TEMP": {"current": {}, "predicted": {}, "alerts": {}, "ts": None},
            "HUM": {"current": {}, "predicted": {}, "alerts": {}, "ts": None},
        }
        # Variables informativas del device (no entran al predictor): tps/tpi.
        # var -> {"value": float, "ts": float}. Las refrescamos en cada msg MQTT.
        self.extras: dict[str, dict] = {}
        self.history: dict[str, deque[dict]] = {
            "TEMP": deque(maxlen=HISTORY_MAX),
            "HUM": deque(maxlen=HISTORY_MAX),
        }
        self.mqtt_connected = False
        self.started_at: Optional[float] = None

        # asyncio bridge
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: list[asyncio.Queue] = []
        self._sub_lock = threading.Lock()

        # mqtt client
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"tenebris-rt-{int(time.time())}",
        )
        self.client.username_pw_set(cfg.token, password="")
        if cfg.tls:
            self.client.tls_set()
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._stop = threading.Event()

    # ---- public API ----

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def attach_agent(self, agent) -> None:
        """Llamado desde main.lifespan() despues de crear el AgentService.
        Construye el TelegramListener si bot_token, chat_id y agent estan listos.
        """
        # Import dentro para evitar ciclos en tiempo de carga
        from app.telegram_bot import TelegramListener

        if not self.cfg.telegram_bot_token:
            self.log.info("TelegramListener no creado (sin TELEGRAM_BOT_TOKEN)")
            return

        def _save_offset(offset_int: int) -> None:
            current = load_runtime_config()
            current["telegram_last_update_id"] = int(offset_int)
            save_runtime_config(current)

        def _load_offset() -> int:
            current = load_runtime_config()
            try:
                return int(current.get("telegram_last_update_id") or 0)
            except (TypeError, ValueError):
                return 0

        self.telegram_listener = TelegramListener(
            bot_token=self.cfg.telegram_bot_token,
            chat_id=self.telegram.chat_id,
            agent=agent,
            prediction_service=self,
            alert_log=self.alert_log,
            save_offset_cb=_save_offset,
            load_offset_cb=_load_offset,
        )
        # Solo arranca si el flag runtime esta en true (opt-in)
        if self.effective_cfg.telegram_listener_enabled and agent and agent.ready:
            self.telegram_listener.update_settings(enabled=True)
        else:
            self.log.info(
                "TelegramListener creado pero no arrancado (listener_enabled=%s agent_ready=%s)",
                self.effective_cfg.telegram_listener_enabled,
                agent.ready if agent else False,
            )

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def snapshot(self) -> dict:
        with self._state_lock:
            return {
                "device": self.cfg.device_label,
                "mqtt_connected": self.mqtt_connected,
                "started_at": self.started_at,
                "now": time.time(),
                "groups": {
                    "TEMP": {
                        "vars": TEMP_VARS,
                        "current": dict(self.latest["TEMP"]["current"]),
                        "predicted": dict(self.latest["TEMP"]["predicted"]),
                        "alerts": dict(self.latest["TEMP"]["alerts"]),
                        "ts": self.latest["TEMP"]["ts"],
                        "buffer_size": len(self.temp_predictor.window),
                        "history": list(self.history["TEMP"]),
                    },
                    "HUM": {
                        "vars": HUM_VARS,
                        "current": dict(self.latest["HUM"]["current"]),
                        "predicted": dict(self.latest["HUM"]["predicted"]),
                        "alerts": dict(self.latest["HUM"]["alerts"]),
                        "ts": self.latest["HUM"]["ts"],
                        "buffer_size": len(self.hum_predictor.window),
                        "history": list(self.history["HUM"]),
                    },
                },
                "thresholds": {
                    "TEMP": {"min": TEMP_OPTIMAL_MIN, "max": TEMP_OPTIMAL_MAX},
                    "HUM":  {"min": HUM_OPTIMAL_MIN,  "max": HUM_OPTIMAL_MAX},
                },
                # Variables informativas adicionales (tps, tpi). Snapshot ligero;
                # los updates van por broadcast type='extra'.
                "extras": {
                    var: {
                        "label": EXTRA_VAR_LABELS.get(var, var),
                        "value": data.get("value"),
                        "ts": data.get("ts"),
                        "unit": "°C",
                    }
                    for var, data in self.extras.items()
                },
            }

    def start(self) -> None:
        self.started_at = time.time()
        # Limpiar registros mas viejos de 30 dias en cada arranque (no diario,
        # pero suficiente para que el SQLite no crezca indefinidamente)
        try:
            self.alert_log.cleanup(older_than_days=30)
        except Exception as e:
            self.log.warning("AlertLog cleanup fallo: %s", e)
        if self.cfg.prefill_from_api:
            try:
                self._prefill_buffers()
                # Tras llenar buffers con datos historicos, generar UNA prediccion
                # inicial por grupo asi el dashboard muestra datos al instante en
                # vez de quedarse en skeletons hasta que llegue el primer MQTT.
                self._emit_initial_predictions()
            except Exception as e:
                self.log.warning("Prefill fallo (%s); continuando sin precarga", e)
        self.log.info(
            "Conectando a %s:%d (tls=%s) device=%s publish=%s",
            self.cfg.broker, self.cfg.port, self.cfg.tls,
            self.cfg.device_label, self.cfg.publish_predictions,
        )
        self.client.connect(self.cfg.broker, self.cfg.port, keepalive=60)
        self.client.loop_start()

    def _emit_initial_predictions(self) -> None:
        """Genera prediccion sintetica tras prefill para que el snapshot
        inicial del SSE ya traiga datos. No publica a Ubidots ni dispara
        alertas Telegram (esas SOLO en transiciones reales)."""
        for group, predictor in [("TEMP", self.temp_predictor), ("HUM", self.hum_predictor)]:
            if len(predictor.window) < LOOK_BACK:
                self.log.info("[%s] sin prefill suficiente (%d/%d), no emitir inicial",
                              group, len(predictor.window), LOOK_BACK)
                continue
            try:
                result = predictor._predict()
            except Exception as e:
                self.log.warning("[%s] prediccion inicial fallo: %s", group, e)
                continue
            ts = time.time()
            alerts = build_alerts(result["current"], result["predicted"], predictor.var_names, group)
            with self._state_lock:
                self.latest[group]["current"] = result["current"]
                self.latest[group]["predicted"] = result["predicted"]
                self.latest[group]["alerts"] = alerts
                self.latest[group]["ts"] = ts
                self.history[group].append({
                    "ts": ts,
                    "current": result["current"],
                    "predicted": result["predicted"],
                    "alerts": alerts,
                })
            self.log.info("[%s] prediccion inicial emitida (snapshot listo para el dashboard)", group)
            # Tambien sembramos el estado previo del notifier asi una sensor
            # ya en abnormal al arranque NO dispara Telegram (no es transicion)
            for var in predictor.var_names:
                self.telegram._prev_cur[var] = alerts[var]["current"]
                self.telegram._prev_pred[var] = alerts[var]["predicted"]

    def stop(self) -> None:
        self._stop.set()
        if self.telegram_listener is not None:
            try:
                self.telegram_listener.stop()
            except Exception:
                pass
        self.client.loop_stop()
        self.client.disconnect()
        try:
            self.alert_log.close()
        except Exception:
            pass
        self.log.info("Servicio detenido.")

    def update_telegram_settings(
        self,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        cooldown_sec: Optional[float] = None,
        listener_enabled: Optional[bool] = None,
    ) -> dict:
        """Actualiza el notifier en memoria Y persiste a runtime_config.json.
        El listener se controla con listener_enabled (independiente del notifier
        de salida; uno puede mandar alertas sin escuchar y viceversa)."""
        snap = self.telegram.update_settings(
            chat_id=chat_id, enabled=enabled, cooldown_sec=cooldown_sec,
        )

        # Aplicar al listener si existe.
        if self.telegram_listener is not None:
            self.telegram_listener.update_settings(
                chat_id=self.telegram.chat_id,
                enabled=listener_enabled,
            )
            snap["listener_enabled"] = self.telegram_listener.enabled
        else:
            snap["listener_enabled"] = False

        # Persistir lo que el notifier acepto (no necesariamente lo que se pidio,
        # ej. enabled puede quedar false si no hay token o chat_id).
        try:
            persist = {
                "telegram_chat_id": self.telegram.chat_id,
                "telegram_enabled": self.telegram.enabled,
                "telegram_cooldown_sec": self.telegram.cooldown_sec,
            }
            if self.telegram_listener is not None:
                persist["telegram_listener_enabled"] = self.telegram_listener.enabled
            # Preservar last_update_id si existe
            existing = load_runtime_config()
            if "telegram_last_update_id" in existing:
                persist["telegram_last_update_id"] = existing["telegram_last_update_id"]
            save_runtime_config(persist)
        except Exception as e:
            self.log.warning("No se pudo guardar runtime_config.json: %s", e)
        return snap

    def run_blocking(self) -> None:
        """Para uso desde CLI: arranca y bloquea hasta stop()."""
        self.start()
        try:
            while not self._stop.is_set():
                self._stop.wait(timeout=1.0)
        finally:
            self.stop()

    # ---- prefill ----

    def _prefill_buffers(self) -> None:
        http = UbidotsHTTP(self.cfg.token)
        self.log.info("Prefill: consultando device %s...", self.cfg.device_label)
        device_id = http.get_device_id(self.cfg.device_label)
        if not device_id:
            self.log.warning("Prefill: device no encontrado, saltando precarga")
            return
        var_map = http.get_variables(device_id)
        for group, var_names, predictor in [
            ("TEMP", TEMP_VARS, self.temp_predictor),
            ("HUM", HUM_VARS, self.hum_predictor),
        ]:
            self._prefill_group(http, var_map, var_names, predictor, group)

    def _prefill_group(self, http, var_map, var_names, predictor, group):
        if not all(v in var_map for v in var_names):
            self.log.warning("[%s] prefill saltado (variables incompletas)", group)
            return
        series = {v: http.get_last_values(var_map[v], LOOK_BACK) for v in var_names}
        n = min(len(rows) for rows in series.values())
        if n == 0:
            self.log.warning("[%s] prefill saltado (sin datos historicos)", group)
            return
        if n < LOOK_BACK:
            self.log.warning(
                "[%s] solo %d/%d muestras historicas; el buffer arrancara parcial",
                group, n, LOOK_BACK,
            )
        recent = {v: series[v][-n:] for v in var_names}
        for i in range(n):
            sample = [recent[v][i][1] for v in var_names]
            predictor.window.append(sample)
        self.log.info("[%s] prefill: %d/%d muestras cargadas", group, len(predictor.window), LOOK_BACK)

    # ---- mqtt callbacks ----

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            self.log.error("Conexion MQTT rechazada: %s", reason_code)
            return
        self.mqtt_connected = True
        self.log.info("Conectado a %s:%d", self.cfg.broker, self.cfg.port)
        topic = f"/v1.6/devices/{self.cfg.device_label}/+/lv"
        client.subscribe(topic, qos=1)
        self.log.info("Suscrito a %s", topic)
        self._broadcast({"type": "status", "mqtt_connected": True})

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self.mqtt_connected = False
        self.log.warning("Desconectado (reason=%s). Reintentando...", reason_code)
        self._broadcast({"type": "status", "mqtt_connected": False})

    def _on_message(self, client, userdata, msg):
        try:
            var = msg.topic.split("/")[-2].lower()
            payload = msg.payload.decode("utf-8").strip()
            value = float(payload)
        except (UnicodeDecodeError, ValueError, IndexError) as e:
            self.log.warning("Mensaje invalido topic=%s payload=%r err=%s", msg.topic, msg.payload, e)
            return

        if var in TEMP_VARS:
            self.rate_detector.observe("TEMP", var, value)
            sample = self.temp_bucket.update(var, value)
            if sample is not None:
                self._handle_sample(self.temp_predictor, sample, "TEMP")
        elif var in HUM_VARS:
            self.rate_detector.observe("HUM", var, value)
            sample = self.hum_bucket.update(var, value)
            if sample is not None:
                self._handle_sample(self.hum_predictor, sample, "HUM")
        elif var in EXTRA_TEMP_VARS:
            # tps/tpi: solo informativo. Guardamos y broadcasteamos para que
            # el dashboard muestre el valor actual; no entra al predictor.
            ts = time.time()
            with self._state_lock:
                self.extras[var] = {"value": value, "ts": ts}
            self._broadcast({
                "type": "extra",
                "var": var,
                "label": EXTRA_VAR_LABELS.get(var, var),
                "value": value,
                "ts": ts,
                "unit": "°C",
            })

    def _on_rate_jump(self, group: str, var: str, ts: float, prev_val: float,
                     cur_val: float, delta: float) -> None:
        """Disparado por el RateOfChangeDetector. Notifica via SSE y Telegram."""
        unit = GROUP_UNITS.get(group, "")
        group_label = GROUP_LABELS.get(group, group)
        # Broadcast al dashboard (los clientes SSE pueden mostrar un toast)
        self._broadcast({
            "type": "jump",
            "group": group,
            "var": var,
            "ts": ts,
            "prev_value": prev_val,
            "current_value": cur_val,
            "delta": delta,
            "unit": unit,
        })
        # Telegram (usa la misma instancia y respeta su enabled)
        if self.telegram and self.telegram.enabled:
            arrow = "📈" if delta > 0 else "📉"
            text = (
                f"{arrow} *Salto detectado* — {group_label}\n"
                f"Sensor *{var}*: `{prev_val:.2f}{unit}` → `{cur_val:.2f}{unit}` "
                f"(Δ `{delta:+.2f}{unit}`)\n"
                f"_Cambio brusco entre muestras consecutivas — el modelo "
                f"predictivo no captura saltos de este tamaño._"
            )
            self.telegram._send_async(text)

    # ---- inferencia + broadcast ----

    def _handle_sample(self, predictor: Predictor, sample: list[float], group: str) -> None:
        result = predictor.add_sample(sample)
        if result is None:
            self._broadcast({
                "type": "buffer",
                "group": group,
                "size": len(predictor.window),
                "target": LOOK_BACK,
            })
            return

        ts = time.time()
        alerts = build_alerts(result["current"], result["predicted"], predictor.var_names, group)
        with self._state_lock:
            self.latest[group]["current"] = result["current"]
            self.latest[group]["predicted"] = result["predicted"]
            self.latest[group]["alerts"] = alerts
            self.latest[group]["ts"] = ts
            self.history[group].append({
                "ts": ts,
                "current": result["current"],
                "predicted": result["predicted"],
                "alerts": alerts,
            })

        self._log_prediction(predictor, result, group, alerts)
        if self.cfg.publish_predictions:
            self._publish_prediction(predictor, result)
        # Notificar a Telegram (solo en transiciones, con cooldown).
        # Si el notifier esta deshabilitado, esto es un no-op.
        try:
            self.telegram.on_alerts(
                group=group,
                var_names=predictor.var_names,
                current_values=result["current"],
                predicted_values=result["predicted"],
                alerts=alerts,
            )
        except Exception as e:
            self.log.warning("Telegram notifier fallo: %s", e)
        self._broadcast({
            "type": "prediction",
            "group": group,
            "ts": ts,
            "vars": predictor.var_names,
            "current": result["current"],
            "predicted": result["predicted"],
            "alerts": alerts,
        })

    def _log_prediction(self, predictor: Predictor, result: dict, group: str, alerts: dict) -> None:
        lines = [f"[{group}] Prediccion +{STEP_AHEAD} min:"]
        lines.append(f"  {'Sensor':<6} {'Actual':>10} {'Predicho':>10} {'Delta':>10} {'Estado':>20}")
        for var in predictor.var_names:
            cur = result["current"][var]
            pred = result["predicted"][var]
            cur_state = alerts[var]["current"]
            pred_state = alerts[var]["predicted"]
            badge = f"{cur_state}->{pred_state}"
            lines.append(f"  {var:<6} {cur:>10.3f} {pred:>10.3f} {pred-cur:>+10.3f} {badge:>20}")
        self.log.info("\n".join(lines))

    def _publish_prediction(self, predictor: Predictor, result: dict) -> None:
        for var in predictor.var_names:
            topic = f"/v1.6/devices/{self.cfg.device_label}/{var}_pred"
            payload = json.dumps({"value": result["predicted"][var]})
            info = self.client.publish(topic, payload, qos=0)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                self.log.warning("Fallo publicando %s rc=%s", topic, info.rc)

    def _broadcast(self, payload: dict) -> None:
        if self._loop is None:
            return
        with self._sub_lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                self._loop.call_soon_threadsafe(self._safe_put, q, payload)
            except RuntimeError:
                # loop cerrado
                pass

    @staticmethod
    def _safe_put(q: asyncio.Queue, payload: dict) -> None:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                pass


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
