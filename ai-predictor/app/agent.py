"""
Agente conversacional Tenebris AI Sentinel.

Wraps un LLM (Ollama Cloud — API REST) y le da 5 tools puras (sin
side-effects) para que pueda responder preguntas en lenguaje natural
sobre el cuarto:

  - get_current_state()             estado actual
  - get_thresholds()                rangos optimos
  - get_recent_alerts(...)          consulta SQLite
  - get_history_ubidots(var, hrs)   pulla histórico real desde Ubidots
  - get_predictions_history(...)    igual pero para variables _pred

Diseño:
  - Sin acciones (no puede modificar nada — pura consulta)
  - Si el LLM no esta configurado (sin OLLAMA_API_KEY), AgentService.ready
    queda en False y el endpoint devuelve 503 con mensaje claro
  - Cliente HTTP directo via httpx (ya en deps) — no usamos el paquete
    `ollama` para evitar dep extra; solo POST a {host}/api/chat con
    Authorization Bearer
  - Loop manual (no LangGraph) para mantener el codigo legible y debuggable;
    si en el futuro necesitamos branching, migramos a LangGraph.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

import httpx

from app.alert_log import AlertLog


if TYPE_CHECKING:
    from app.service import PredictionService


log = logging.getLogger("agent")


SYSTEM_PROMPT = """Eres Tenebris AI Sentinel, un asistente experto en el monitoreo \
de un cuarto de cría de tenebrios (escarabajos) que usa machine learning para \
predecir microclima.

ARQUITECTURA DEL CUARTO:
- Hay 5 sensores INTERIORES de temperatura: t1, t2, t3, t4, t5 (dentro del cuarto). Unidad: °C.
- Hay 5 sensores INTERIORES de humedad: h1, h2, h3, h4, h5 (dentro del cuarto). Unidad: %.
- Hay 1 sensor EXTERIOR de temperatura: tex (en la calle/intemperie). Unidad: °C.
- Hay 1 sensor EXTERIOR de humedad: hex (en la calle/intemperie). Unidad: %.

RANGOS ÓPTIMOS (aplican SOLO a sensores INTERIORES):
- TEMP interior (t1–t5): 15–30 °C. Fuera = "anormal" → requiere atención.
- HUM interior (h1–h5):  60–90 %. Fuera = "anormal" → requiere atención.

TRATAMIENTO DE SENSORES EXTERIORES (tex, hex):
- Son INFORMATIVOS. Reflejan el clima de afuera y NO se controlan.
- Aunque las tools internamente los marquen como "abnormal" usando el mismo umbral,
  NUNCA los reportes como alerta o problema. Es esperable que estén fuera del rango
  interior (afuera puede haber 5°C o 40°C, 10% o 95% humedad — eso es normal).
- Solo úsalos como contexto: "afuera hay 42°C, lo cual estresa los aires, pero el
  cuarto se mantiene en rango".

MODELO PREDICTIVO:
- Dos GRU duales predicen el valor de cada sensor en +3 minutos.
- Cuando un sensor INTERIOR sale del rango óptimo, el sistema registra una TRANSICIÓN.

LIMITACIÓN IMPORTANTE DEL ALERT LOG:
- get_recent_alerts SOLO devuelve transiciones (cambios de estado), no muestreos.
- Si un sensor ya estaba abnormal antes del periodo consultado y sigue abnormal,
  transitions_to_abnormal puede ser 0 a pesar de haber alerta CONTINUA.
- Por eso la tool también devuelve "currently_abnormal_interior_sensors": si esa
  lista tiene elementos pero transitions=0, significa que la anomalía es
  PERSISTENTE (lleva más tiempo del consultado).
- En ese caso NUNCA respondas "no hubo anomalías": responde algo como
  "no hubo nuevas transiciones en el periodo, pero h1, h2, ... siguen en
  alerta desde antes del inicio del periodo (anomalía persistente)".
- Lee también "interpretation_hint" si la tool lo devuelve — es una sugerencia
  de cómo redactar la respuesta.

TU ROL:
- Responde en español, conciso y técnico pero amigable.
- USA LAS TOOLS para consultar datos reales antes de responder. No inventes valores.
- Para preguntas sobre el estado actual: usa get_current_state.
- Para preguntas históricas (últimas X horas, ayer, esta semana): usa get_history_ubidots.
- Para preguntas sobre alertas/anomalías pasadas: usa get_recent_alerts.
- Para preguntas sobre rangos óptimos: usa get_thresholds.
- Si no tienes la información, di que no la tienes — no inventes.
- Si una pregunta es ambigua (qué sensor?), pide aclaración.
- No tienes capacidad de cambiar nada del sistema; eres solo informativo.
- Cuando reportes valores, distingue claramente entre interiores y exteriores.
  Ejemplo bueno: "Interiores: t1=28.5, t2=27.6 (todos en rango). Exterior tex=42 (calor afuera)."
  Ejemplo malo: "tex=42°C está fuera de rango óptimo".

ESTRATEGIA EFICIENTE (tienes maximo 10 tool calls por conversacion):
- NO consultes todos los sensores uno por uno cuando esten en el mismo grupo.
  Si quieres saber "desde cuando esta mal la humedad", basta con 1 sensor
  representativo (ej. h1) — todos los del cuarto reciben el mismo aire.
- Si get_history_ubidots devuelve range_start_state="abnormal" y no hay
  transicion ok->abnormal en el periodo, significa que la anomalia es mas
  vieja: re-llama con un hours mayor (ej. 6h -> 24h -> 72h -> 168h).
- get_history_ubidots ya devuelve "first_transition_ok_to_abnormal_ts_iso"
  y "interpretation". USA ESOS CAMPOS — no escanees las muestras a mano.
- Despues de 2-3 escalaciones sin encontrar inicio, di al usuario "lleva
  al menos N horas/dias fuera de rango, no pude encontrar el inicio exacto
  en los datos disponibles".
"""


def _tool_schemas() -> list[dict]:
    """Schemas de tools en formato Ollama (compatible con OpenAI tool calling)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_current_state",
                "description": (
                    "Devuelve el estado actual del cuarto: valores actuales y predichos "
                    "(+3 min) de los 12 sensores, sus etiquetas de alerta (ok/abnormal), "
                    "y el timestamp del último update. Úsalo para preguntas tipo "
                    "'¿cómo está la temperatura?' o '¿hay algún sensor en alerta?'."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_thresholds",
                "description": (
                    "Devuelve los rangos óptimos configurados: TEMP {min, max} en °C "
                    "y HUM {min, max} en %. Valores fuera de estos rangos se "
                    "consideran 'anormal'."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_recent_alerts",
                "description": (
                    "Devuelve registros de transiciones de estado de los sensores "
                    "(cuando un sensor pasó de ok→abnormal o abnormal→ok). Cada "
                    "registro tiene timestamp, sensor, estado anterior, estado nuevo "
                    "y el valor en ese momento. Úsalo para preguntas tipo "
                    "'¿hubo anomalías hoy?', '¿qué pasó con t1 ayer?'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "number",
                            "description": "Cuántas horas hacia atrás buscar (default 24).",
                        },
                        "group": {
                            "type": "string",
                            "enum": ["TEMP", "HUM"],
                            "description": (
                                "Filtrar por grupo (opcional). DEBE ser exactamente "
                                "'TEMP' o 'HUM' (en mayusculas), o omitirse. NO uses "
                                "'interior'/'exterior' aqui — ese es el atributo zone "
                                "de cada sensor, no un grupo."
                            ),
                        },
                        "var": {
                            "type": "string",
                            "description": "Filtrar por sensor especifico, ej. 't1' (opcional).",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_history_ubidots",
                "description": (
                    "Pulla el histórico real de un sensor desde Ubidots HTTP API y "
                    "devuelve un resumen estadístico (min, max, avg) más los puntos "
                    "muestreados. Úsalo para preguntas tipo '¿cuál fue la temperatura "
                    "promedio de t1 las últimas 6 horas?', '¿cuándo bajó la humedad?'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "var": {
                            "type": "string",
                            "description": "Sensor: t1..t5, tex, h1..h5, hex.",
                        },
                        "hours": {
                            "type": "number",
                            "description": "Horas hacia atrás (default 6, max 168 = 7 días).",
                        },
                    },
                    "required": ["var"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_predictions_history",
                "description": (
                    "Igual que get_history_ubidots pero para las variables predichas "
                    "(t1_pred, h1_pred, etc.). Útil para evaluar precisión histórica "
                    "o ver tendencias predichas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "var": {
                            "type": "string",
                            "description": "Sensor: t1..t5, tex, h1..h5, hex (sin _pred, se agrega).",
                        },
                        "hours": {
                            "type": "number",
                            "description": "Horas hacia atrás (default 6, max 168).",
                        },
                    },
                    "required": ["var"],
                },
            },
        },
    ]


class AgentService:
    """
    Wrapper sobre el cliente Ollama. No-op si OLLAMA_API_KEY no esta seteado.
    """

    MAX_TOOL_LOOPS = 10  # techo defensivo para no entrar en loop infinito

    def __init__(
        self,
        api_key: str,
        host: str,
        model: str,
        enabled: bool,
        prediction_service: "PredictionService",
        alert_log: AlertLog,
    ):
        self.api_key = api_key
        self.host = host
        self.model = model
        self.prediction_service = prediction_service
        self.alert_log = alert_log
        self.enabled = bool(enabled and api_key)
        self._client = None
        self._var_cache: dict[str, str] = {}  # var label -> Ubidots variable id

        if not self.enabled:
            log.info("Agente IA deshabilitado (AGENT_ENABLED=false o sin API key)")
            return
        # Cliente httpx hacia Ollama Cloud (REST). Timeout 60s porque
        # `gpt-oss:120b` puede tardar varios segundos en queries con tools.
        self._client = httpx.Client(
            base_url=host.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        log.info("Agente IA ACTIVO (host=%s, model=%s)", host, model)

    @property
    def ready(self) -> bool:
        return self.enabled and self._client is not None

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def chat(self, messages: list[dict]) -> dict:
        """
        messages: lista [{"role": "user"|"assistant"|"system", "content": str}].
        El system prompt se inyecta al inicio si no está.
        Devuelve {"reply": str, "tool_calls": [...], "model": str}.
        """
        if not self.ready:
            raise RuntimeError("Agente no está activo (revisa OLLAMA_API_KEY en .env)")

        # Inyectar system prompt si el caller no lo puso
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        tool_calls_summary: list[dict] = []
        tools = _tool_schemas()

        for loop_idx in range(self.MAX_TOOL_LOOPS):
            try:
                resp = self._client.post(
                    "/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "tools": tools,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                response = resp.json()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response is not None else ""
                log.error("Ollama Cloud HTTP %s en loop=%d: %s", e.response.status_code, loop_idx, body)
                raise RuntimeError(f"Ollama Cloud devolvio HTTP {e.response.status_code}") from e
            except Exception as e:
                log.error("Error en chat() loop=%d: %s", loop_idx, e)
                raise

            msg = response.get("message") or {}
            # Anexar la respuesta del assistant a la conversacion
            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": msg.get("tool_calls") or [],
            })

            calls = msg.get("tool_calls") or []
            if not calls:
                # No mas tool calls => respuesta final
                return {
                    "reply": msg.get("content") or "",
                    "tool_calls": tool_calls_summary,
                    "model": self.model,
                }

            # Ejecutar cada tool call y agregar su resultado a la conversacion
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                log.info("Tool call: %s(%s)", name, args)
                tool_calls_summary.append({"name": name, "args": args})
                try:
                    result = self._execute_tool(name, args)
                except Exception as e:
                    log.warning("Tool %s fallo: %s", name, e)
                    result = {"error": str(e)}
                messages.append({
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(result, default=str)[:8000],  # cap por si acaso
                })

        # Si llegamos aca, el modelo no termino. Devolvemos lo que tenemos.
        log.warning("Agente alcanzo MAX_TOOL_LOOPS=%d sin respuesta final", self.MAX_TOOL_LOOPS)
        return {
            "reply": "Disculpa, no pude completar la consulta (demasiados pasos). Intenta reformular la pregunta.",
            "tool_calls": tool_calls_summary,
            "model": self.model,
        }

    # ---------- ejecucion de tools ----------

    def _execute_tool(self, name: str, args: dict) -> Any:
        if name == "get_current_state":
            return self._tool_current_state()
        if name == "get_thresholds":
            return self._tool_thresholds()
        if name == "get_recent_alerts":
            return self._tool_recent_alerts(args)
        if name == "get_history_ubidots":
            return self._tool_history(args, predicted=False)
        if name == "get_predictions_history":
            return self._tool_history(args, predicted=True)
        return {"error": f"tool desconocida: {name}"}

    def _tool_current_state(self) -> dict:
        snap = self.prediction_service.snapshot()
        # Reducimos tamaño quitando history para no saturar el contexto del LLM
        out = {
            "device": snap.get("device"),
            "mqtt_connected": snap.get("mqtt_connected"),
            "now_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap.get("now") or time.time())),
            "groups": {},
            "thresholds": snap.get("thresholds"),
            "_note": (
                "tex y hex son sensores EXTERIORES (intemperie); aunque su flag "
                "'abnormal' use el mismo umbral interior, NO son alertas — son "
                "informativos del clima afuera."
            ),
        }
        for group_name in ("TEMP", "HUM"):
            g = (snap.get("groups") or {}).get(group_name) or {}
            vars_list = g.get("vars") or []
            # Etiquetamos cada sensor con su zona (interior vs exterior)
            sensors = []
            current = g.get("current") or {}
            predicted = g.get("predicted") or {}
            alerts = g.get("alerts") or {}
            for v in vars_list:
                is_exterior = v in ("tex", "hex")
                sensors.append({
                    "var": v,
                    "zone": "exterior" if is_exterior else "interior",
                    "current": current.get(v),
                    "predicted": predicted.get(v),
                    "current_state": (alerts.get(v) or {}).get("current"),
                    "predicted_state": (alerts.get(v) or {}).get("predicted"),
                    "applies_threshold": not is_exterior,
                })
            out["groups"][group_name] = {
                "sensors": sensors,
                "buffer_size": g.get("buffer_size"),
            }
        return out

    def _tool_thresholds(self) -> dict:
        snap = self.prediction_service.snapshot()
        return snap.get("thresholds") or {}

    def _tool_recent_alerts(self, args: dict) -> dict:
        hours = float(args.get("hours") or 24)
        hours = max(0.1, min(hours, 24 * 30))  # 0.1h .. 30 dias
        since_ts = time.time() - (hours * 3600)

        # El LLM a veces manda valores invalidos (ej. "interior", "all").
        # Validamos: solo aceptamos 'TEMP' o 'HUM', cualquier otra cosa = sin filtro.
        raw_group = args.get("group")
        group_filter = raw_group if raw_group in ("TEMP", "HUM") else None
        var_filter = args.get("var") or None
        # Sensor invalido = no filtramos (tolerancia)
        if var_filter and var_filter not in ("t1", "t2", "t3", "t4", "t5", "tex",
                                              "h1", "h2", "h3", "h4", "h5", "hex"):
            var_filter = None

        rows = self.alert_log.query(
            group_name=group_filter,
            var=var_filter,
            since_ts=since_ts,
            limit=100,
        )
        # Formato amigable para el LLM
        formatted = []
        for r in rows:
            formatted.append({
                "ts_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
                "group": r["group_name"],
                "var": r["var"],
                "transition": f'{r["prev_state"]}->{r["new_state"]}',
                "kind": r["kind"],
                "value": r["value"],
            })
        total = self.alert_log.count(
            group_name=group_filter,
            new_state="abnormal",
            since_ts=since_ts,
        )

        # CRITICO: el AlertLog solo registra TRANSICIONES (cambios de estado).
        # Si un sensor estaba abnormal antes del periodo Y sigue abnormal,
        # transitions=0 — pero eso NO significa "no hay anomalia". Por eso
        # ademas devolvemos que sensores estan ACTUALMENTE en estado abnormal,
        # filtrando los exteriores (tex/hex) que son informativos.
        snap = self.prediction_service.snapshot()
        currently_abnormal = []
        for group_name in ("TEMP", "HUM"):
            if group_filter and group_filter != group_name:
                continue
            g = (snap.get("groups") or {}).get(group_name) or {}
            current = g.get("current") or {}
            alerts = g.get("alerts") or {}
            for v in (g.get("vars") or []):
                if v in ("tex", "hex"):
                    continue  # exteriores: no son alerta legitima
                if var_filter and var_filter != v:
                    continue
                state = (alerts.get(v) or {}).get("current")
                if state == "abnormal":
                    currently_abnormal.append({
                        "var": v,
                        "group": group_name,
                        "current_value": current.get(v),
                    })

        # Cuanto historial REAL tiene el AlertLog. Si el sidecar arranco hace
        # poco, el log puede tener solo unas horas de data — el agente no debe
        # asumir que el log abarca todo el periodo consultado.
        oldest_ts = self.alert_log.oldest_ts()
        log_oldest_iso = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(oldest_ts))
            if oldest_ts else None
        )
        log_age_hours = (time.time() - oldest_ts) / 3600 if oldest_ts else 0.0
        # Si el log es mas reciente que el periodo solicitado, hay un gap:
        # los datos del log no cubren `hours` horas atras.
        log_covers_full_period = (oldest_ts is not None) and ((time.time() - oldest_ts) >= hours * 3600 - 60)

        # Pista interpretativa: si transitions_to_abnormal=0 pero hay
        # currently_abnormal, significa que el/los sensores YA estaban
        # fuera de rango antes de la ventana consultada y siguen asi.
        interpretation = ""
        if total == 0 and currently_abnormal and len(rows) == 0:
            sensors = ", ".join(s["var"] for s in currently_abnormal)
            if not log_covers_full_period:
                interpretation = (
                    f"NOTA CRITICA: 0 transiciones, PERO el AlertLog solo tiene "
                    f"{log_age_hours:.1f} h de historico (arranco en {log_oldest_iso}); "
                    f"NO cubre todo el periodo de {hours:.0f}h solicitado. Los sensores "
                    f"{sensors} estan abnormal AHORA. Para saber DESDE CUANDO la humedad "
                    "esta fuera de rango, usa get_history_ubidots(var='h1', hours=24) "
                    "y busca el primer punto bajo el umbral (60% para HUM, 15-30°C para TEMP)."
                )
            else:
                interpretation = (
                    f"NOTA: 0 transiciones en el periodo, PERO {sensors} estan "
                    "actualmente en estado abnormal. Como el AlertLog si cubre "
                    f"el periodo ({log_age_hours:.1f}h de historico), la anomalia "
                    "es persistente desde antes del inicio del periodo. Reportalo "
                    "como anomalia persistente. Si el usuario quiere saber el "
                    "momento exacto, sugiere usar get_history_ubidots para escanear "
                    "el time series de Ubidots."
                )

        return {
            "hours_back": hours,
            "filters": {k: args.get(k) for k in ("group", "var") if args.get(k)},
            "transitions_to_abnormal": total,
            "transitions_returned": len(formatted),
            "transitions": formatted,
            "currently_abnormal_interior_sensors": currently_abnormal,
            "alert_log_oldest_ts_iso": log_oldest_iso,
            "alert_log_covers_full_period": log_covers_full_period,
            "interpretation_hint": interpretation,
        }

    def _tool_history(self, args: dict, predicted: bool) -> dict:
        var = (args.get("var") or "").strip().lower()
        if not var:
            return {"error": "var requerido (ej. t1, h2, tex)"}
        hours = float(args.get("hours") or 6)
        hours = max(0.1, min(hours, 168))  # 0.1h .. 7 dias

        # Resolver variable_id desde Ubidots
        ubidots_label = f"{var}_pred" if predicted else var
        var_id = self._resolve_var_id(ubidots_label)
        if not var_id:
            return {
                "error": (
                    f"Variable '{ubidots_label}' no encontrada en Ubidots. "
                    "Si es _pred, asegurate que PUBLISH_PREDICTIONS=true y haya pasado al menos una prediccion."
                ),
            }

        from app.service import UbidotsHTTP  # import dentro para evitar circular
        http = UbidotsHTTP(self.prediction_service.cfg.token)
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - int(hours * 3600 * 1000)
        rows = http.get_values_range(var_id, start_ms, end_ms, max_points=2000)
        if not rows:
            return {"var": ubidots_label, "hours": hours, "samples": [], "error": "sin datos"}

        # Stats
        values = [v for _, v in rows]
        n = len(values)
        vmin = min(values)
        vmax = max(values)
        vavg = sum(values) / n

        # Detectar transiciones de estado en el time series. Para sensores
        # interiores aplicamos el umbral del grupo; para tex/hex no aplica.
        # Devolvemos un resumen ASI el LLM no tiene que escanear muestras.
        is_interior = var not in ("tex", "hex") and not predicted
        threshold_summary = None
        first_abnormal_ts_iso = None
        first_abnormal_after_normal_ts_iso = None
        time_outside_pct = None
        if is_interior:
            from app.service import (
                TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX,
                HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX,
            )
            if var.startswith("t"):
                lo, hi = TEMP_OPTIMAL_MIN, TEMP_OPTIMAL_MAX
            else:
                lo, hi = HUM_OPTIMAL_MIN, HUM_OPTIMAL_MAX

            outside_count = 0
            prev_state = None
            first_outside_ts = None
            first_transition_ts = None
            for ts_ms, val in rows:
                state = "ok" if lo <= val <= hi else "abnormal"
                if state == "abnormal":
                    outside_count += 1
                    if first_outside_ts is None:
                        first_outside_ts = ts_ms
                if (prev_state is not None
                        and prev_state == "ok"
                        and state == "abnormal"
                        and first_transition_ts is None):
                    first_transition_ts = ts_ms
                prev_state = state

            time_outside_pct = round((outside_count / n) * 100, 1) if n > 0 else 0.0
            if first_outside_ts is not None:
                first_abnormal_ts_iso = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(first_outside_ts / 1000)
                )
            if first_transition_ts is not None:
                first_abnormal_after_normal_ts_iso = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(first_transition_ts / 1000)
                )
            threshold_summary = {
                "min_optimal": lo,
                "max_optimal": hi,
                "current_outside_optimal": outside_count,
                "time_outside_pct": time_outside_pct,
            }

        # Submuestrear para no saturar al LLM (max 30 puntos)
        if n > 30:
            step = n // 30
            sampled = [
                {
                    "ts_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(rows[i][0] / 1000)),
                    "value": round(rows[i][1], 3),
                }
                for i in range(0, n, step)
            ][:30]
        else:
            sampled = [
                {
                    "ts_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(t / 1000)),
                    "value": round(v, 3),
                }
                for t, v in rows
            ]
        out = {
            "var": ubidots_label,
            "hours_back": hours,
            "samples_total": n,
            "samples_returned": len(sampled),
            "stats": {
                "min": round(vmin, 3),
                "max": round(vmax, 3),
                "avg": round(vavg, 3),
            },
            "samples": sampled,
        }
        if threshold_summary is not None:
            out["threshold_analysis"] = threshold_summary
            # Cuando empezo a estar fuera de rango (primer punto abnormal)
            out["first_abnormal_ts_iso"] = first_abnormal_ts_iso
            # Cuando hubo una TRANSICION (de ok a abnormal) en el periodo
            out["first_transition_ok_to_abnormal_ts_iso"] = first_abnormal_after_normal_ts_iso
            # Si el primer punto del rango ya era abnormal y nunca volvio a ok,
            # eso significa que el sensor lleva al menos `hours` fuera de rango.
            first_value = rows[0][1]
            last_value = rows[-1][1]
            first_state = "abnormal" if not (lo <= first_value <= hi) else "ok"
            last_state = "abnormal" if not (lo <= last_value <= hi) else "ok"
            out["range_start_state"] = first_state
            out["range_end_state"] = last_state
            if first_state == "abnormal" and first_abnormal_after_normal_ts_iso is None:
                out["interpretation"] = (
                    f"El sensor {var} ya estaba fuera de rango al inicio del periodo "
                    f"consultado ({hours}h atras) y no hubo transicion a ok. La anomalia "
                    f"comenzo ANTES de hace {hours}h. Para encontrar el inicio exacto, "
                    "vuelve a llamar get_history_ubidots con un hours mayor (max 168 = 7 dias)."
                )
        return out

    def _resolve_var_id(self, label: str) -> Optional[str]:
        """Cache de var label -> Ubidots variable ID. Llena toda la lista al primer miss."""
        if label in self._var_cache:
            return self._var_cache[label]
        from app.service import UbidotsHTTP
        cfg = self.prediction_service.cfg
        http = UbidotsHTTP(cfg.token)
        device_id = http.get_device_id(cfg.device_label)
        if not device_id:
            return None
        var_map = http.get_variables(device_id)
        self._var_cache.update(var_map)
        return self._var_cache.get(label)
