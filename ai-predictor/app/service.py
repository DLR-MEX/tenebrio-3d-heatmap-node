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


ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

TEMP_VARS = ["t1", "t2", "t3", "t4", "t5", "tex"]
HUM_VARS = ["h1", "h2", "h3", "h4", "h5", "hex"]
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

    def __init__(self, bot_token: str, chat_id: str, enabled: bool, cooldown_sec: float = 300.0):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(enabled and bot_token and chat_id)
        self.cooldown_sec = cooldown_sec
        self._prev_cur: dict[str, str] = {}   # var -> ultimo estado "current"
        self._prev_pred: dict[str, str] = {}  # var -> ultimo estado "predicted"
        self._last_sent: dict[tuple[str, str], float] = {}  # (var, kind) -> ts
        self._lock = threading.Lock()
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
        if not self.enabled:
            return
        now = time.time()
        unit = GROUP_UNITS.get(group, "")
        group_label = GROUP_LABELS.get(group, group)

        if group == "TEMP":
            lo, hi = TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX
        else:
            lo, hi = HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX

        with self._lock:
            for var in var_names:
                cur_state = alerts[var]["current"]
                pred_state = alerts[var]["predicted"]
                cur_val = current_values.get(var)
                pred_val = predicted_values.get(var)

                prev_cur = self._prev_cur.get(var)
                prev_pred = self._prev_pred.get(var)
                self._prev_cur[var] = cur_state
                self._prev_pred[var] = pred_state

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

        self.telegram = TelegramNotifier(
            bot_token=cfg.telegram_bot_token,
            chat_id=cfg.telegram_chat_id,
            enabled=cfg.telegram_enabled,
            cooldown_sec=cfg.telegram_cooldown_sec,
        )

        # estado compartido
        self._state_lock = threading.Lock()
        self.latest: dict[str, dict] = {
            "TEMP": {"current": {}, "predicted": {}, "alerts": {}, "ts": None},
            "HUM": {"current": {}, "predicted": {}, "alerts": {}, "ts": None},
        }
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
            }

    def start(self) -> None:
        self.started_at = time.time()
        if self.cfg.prefill_from_api:
            try:
                self._prefill_buffers()
            except Exception as e:
                self.log.warning("Prefill fallo (%s); continuando sin precarga", e)
        self.log.info(
            "Conectando a %s:%d (tls=%s) device=%s publish=%s",
            self.cfg.broker, self.cfg.port, self.cfg.tls,
            self.cfg.device_label, self.cfg.publish_predictions,
        )
        self.client.connect(self.cfg.broker, self.cfg.port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self._stop.set()
        self.client.loop_stop()
        self.client.disconnect()
        self.log.info("Servicio detenido.")

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
            sample = self.temp_bucket.update(var, value)
            if sample is not None:
                self._handle_sample(self.temp_predictor, sample, "TEMP")
        elif var in HUM_VARS:
            sample = self.hum_bucket.update(var, value)
            if sample is not None:
                self._handle_sample(self.hum_predictor, sample, "HUM")

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
