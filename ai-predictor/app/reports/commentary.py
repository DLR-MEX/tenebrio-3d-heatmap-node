"""
Generacion de narrativa de un reporte por el LLM.

Recibe los datos recolectados y pide al modelo que redacte 4 secciones:
  - summary          (resumen ejecutivo: 1-2 parrafos)
  - events           (analisis de eventos destacados: 2-3 parrafos)
  - infrastructure   (estado de calefaccion/ventilacion/calidad aire: 1 parrafo)
  - recommendations  (3-5 puntos accionables con disclaimer IA)

Cada seccion va en una llamada separada al LLM para evitar timeouts y
controlar el tamano de cada respuesta. Si una llamada falla, fallback
a templates estaticos para que el reporte siga siendo legible.

Output: dict {section_id: html_string} listo para inyectar en el
template Jinja2.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger("reports.commentary")

SYSTEM_PROMPT = """Eres un analista técnico que redacta secciones de un reporte ejecutivo \
sobre el monitoreo de un cuarto de cría de tenebrios. Tu rol:

- Escribe en español, tono profesional pero claro.
- Sé conciso: cumple el largo solicitado, ni más ni menos.
- USA los datos que se te pasan; NO inventes números ni eventos.
- Si los datos son escasos o nulos, dilo explícitamente.
- Distingue sensores INTERIORES (t1-t5, h1-h5) de EXTERIORES (tex, hex).
  Los exteriores son informativos, NO se reportan como alertas.
- Usa Markdown ligero: **negritas** para resaltar, listas con guiones
  para enumeraciones. NO incluyas headers (#, ##) — el reporte ya los
  tiene.
- NO repitas la introducción del reporte ni las fechas en cada sección.
"""


def generate_commentary(agent, data: dict) -> dict:
    """Genera las 4 secciones llamando al LLM via AgentService.

    `agent` es el AgentService ya configurado (acceso a Ollama Cloud).
    `data` es el dict del collector.

    Returns: {'summary', 'events', 'infrastructure', 'recommendations'}
             — cada uno un string HTML listo para inyectar.
    """
    sections = {}

    sections["summary"] = _safe_section(
        agent, data, "summary", _prompt_summary,
        fallback=_fallback_summary(data),
    )
    sections["events"] = _safe_section(
        agent, data, "events", _prompt_events,
        fallback=_fallback_events(data),
    )
    if data.get("infrastructure"):
        sections["infrastructure"] = _safe_section(
            agent, data, "infrastructure", _prompt_infrastructure,
            fallback=_fallback_infrastructure(data),
        )
    sections["recommendations"] = _safe_section(
        agent, data, "recommendations", _prompt_recommendations,
        fallback=_fallback_recommendations(data),
    )
    return sections


def _safe_section(agent, data: dict, name: str, prompt_fn, fallback: str) -> str:
    """Pide una seccion al LLM. Si falla, usa el fallback estatico."""
    try:
        prompt = prompt_fn(data)
        if not prompt:
            return fallback
        log.info("Pidiendo seccion '%s' al LLM (~%d chars context)", name, len(prompt))
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = agent.chat(messages)
        reply = (result or {}).get("reply") or ""
        if not reply.strip():
            log.warning("Seccion '%s' devolvio vacio — usando fallback", name)
            return fallback
        return _markdown_to_html(reply.strip())
    except Exception as e:
        log.warning("Seccion '%s' fallo (%s) — usando fallback", name, e)
        return fallback


# ---------- prompts por seccion ----------

def _prompt_summary(data: dict) -> str:
    meta = data["meta"]
    alerts = data["alerts"]
    history_temp = data["history"].get("TEMP", {})
    history_hum = data["history"].get("HUM", {})

    # Top 3 sensores fuera de rango
    out_summary = []
    for var, stats in history_temp.items():
        if var in ("tex", "tps", "tpi"):
            continue
        if stats.get("time_outside_pct", 0) > 0:
            out_summary.append(f"{var} ({stats['time_outside_pct']}% fuera, "
                              f"avg {stats['avg']}°C, rango {stats['min']}-{stats['max']}°C)")
    for var, stats in history_hum.items():
        if var == "hex":
            continue
        if stats.get("time_outside_pct", 0) > 0:
            out_summary.append(f"{var} ({stats['time_outside_pct']}% fuera, "
                              f"avg {stats['avg']}%, rango {stats['min']}-{stats['max']}%)")

    return f"""DATOS DEL PERIODO {meta['start_iso']} a {meta['end_iso']} ({meta['hours']}h):

- Transiciones a estado anormal: {alerts['transitions_to_abnormal']}
- Saltos abruptos detectados: {alerts['jumps_total']}
- Sensores que estuvieron fuera de rango (con %): {out_summary or 'ninguno — todo en rango'}

INSTRUCCIONES:
Redacta el RESUMEN EJECUTIVO del reporte. 1 a 2 párrafos cortos (máximo 120
palabras total). Comienza directamente con la información — NO escribas
"Resumen ejecutivo:" o frases introductorias. Menciona:
1. Cuántas alertas hubo y de qué severidad.
2. Si hubo sensores persistentemente fuera de rango, cuáles y por cuánto.
3. Estado general del cuarto (saludable / requiere atención / crítico).
"""


def _prompt_events(data: dict) -> str:
    alerts = data["alerts"]
    transitions = alerts.get("transitions", [])
    jumps = alerts.get("jumps", [])
    by_var = alerts.get("transitions_by_var", {})

    # Formatear ejemplos
    tx_examples = "\n".join(
        f"- {t['ts_iso']} {t['var']}: {t['from']} → {t['to']} (valor {t['value']:.2f})"
        for t in transitions[-10:] if isinstance(t.get('value'), (int, float))
    ) or "(sin transiciones)"

    jump_examples = "\n".join(
        f"- {j['ts_iso']} {j['var']}: {j['from_value']} → {j['to_value']} (Δ {j.get('delta', '?')})"
        for j in jumps[-10:]
    ) or "(sin saltos)"

    return f"""DATOS DE EVENTOS:

Transiciones por sensor:
{by_var or '(ninguna)'}

Últimas transiciones:
{tx_examples}

Saltos abruptos:
{jump_examples}

INSTRUCCIONES:
Redacta la sección "EVENTOS DESTACADOS". 2 a 3 párrafos. Si NO hubo eventos
significativos, dilo en 1 párrafo y termina. Si hubo eventos:
- Identifica el sensor más afectado y describe el patrón (transiciones
  repetidas, salto puntual, etc.)
- Si hay saltos abruptos, comenta posibles causas (ventilador apagado,
  puerta abierta, intervención manual) en tono especulativo.
- Conecta con horas del día si aplica (ej. "el martes a media tarde").
NO inventes causas — solo sugiere posibilidades plausibles.
"""


def _prompt_infrastructure(data: dict) -> str:
    infra = data.get("infrastructure", {})
    by_cat = {}
    for label, info in infra.items():
        cat = info.get("category", "otros")
        by_cat.setdefault(cat, []).append(f"{info['label']}: {info['value']} {info['unit']}")

    formatted = "\n".join(
        f"{cat}:\n  " + "\n  ".join(items)
        for cat, items in by_cat.items()
    )

    return f"""ESTADO ACTUAL DE LA INFRAESTRUCTURA EXTERNA:
{formatted}

CONTEXTO TECNICO:
- Calefacción: Solar -> Termo -> Bomba M2 -> Entrada -> Piso radiante (medio, salida)
- Una caída entre Entrada y Salida del piso indica circulación activa (bueno).
- Termo frío + Solar caliente puede indicar bomba apagada o válvula cerrada.
- Amoníaco >25 ppm es crítico; <25 ppm es normal.

INSTRUCCIONES:
Redacta UN solo párrafo (60-100 palabras) describiendo el estado de la
infraestructura. Si todo se ve normal, dilo. Si hay anomalías (ej. termo
frío vs solar caliente, NH3 alto, ventilación apagada), señálalo.
"""


def _prompt_recommendations(data: dict) -> str:
    alerts = data["alerts"]
    history_hum = data["history"].get("HUM", {})
    history_temp = data["history"].get("TEMP", {})
    by_var = alerts.get("transitions_by_var", {})

    out_hum = {v: s for v, s in history_hum.items()
               if v != "hex" and s.get("time_outside_pct", 0) > 20}
    out_temp = {v: s for v, s in history_temp.items()
                if v not in ("tex", "tps", "tpi") and s.get("time_outside_pct", 0) > 20}

    return f"""DATOS:

- Transiciones a abnormal totales: {alerts['transitions_to_abnormal']}
- Saltos abruptos: {alerts['jumps_total']}
- Sensores temp >20% tiempo fuera de rango: {out_temp or 'ninguno'}
- Sensores hum >20% tiempo fuera de rango: {out_hum or 'ninguno'}
- Transiciones por sensor: {by_var or 'ninguna'}

INSTRUCCIONES:
Redacta entre 3 y 5 recomendaciones accionables como **lista con guiones**
(cada item máximo 1 línea). Prioriza:
1. Sensores persistentemente fuera de rango (revisar humidificación,
   ventilación, calefacción).
2. Patrones repetidos (mismo sensor con muchas transiciones = revisar
   calibración o ubicación).
3. Si todo está OK, sugiere mantener calibración rutinaria y monitoreo.
NO incluyas el disclaimer — el template ya lo añade.
"""


# ---------- fallbacks estaticos ----------

def _fallback_summary(data: dict) -> str:
    alerts = data["alerts"]
    return (
        f"<p>Durante el periodo se registraron <strong>{alerts['transitions_to_abnormal']}</strong> "
        f"alertas críticas y <strong>{alerts['jumps_total']}</strong> saltos abruptos "
        f"en sensores interiores. Revise las tablas de las páginas siguientes para detalle "
        f"completo de cada evento.</p>"
    )


def _fallback_events(data: dict) -> str:
    n = data["alerts"]["transitions_total"]
    if n == 0:
        return "<p>No se registraron transiciones de estado en el periodo.</p>"
    return (
        f"<p>Se detectaron {n} transiciones de estado. Consulte la tabla a continuación "
        f"para el detalle cronológico.</p>"
    )


def _fallback_infrastructure(data: dict) -> str:
    n = len(data.get("infrastructure", {}))
    return f"<p>Estado actual de {n} componentes de infraestructura externa registrado.</p>"


def _fallback_recommendations(data: dict) -> str:
    return (
        "<ul>"
        "<li>Verifique las lecturas con inspección visual del cuarto.</li>"
        "<li>Mantenga calibración rutinaria de los sensores.</li>"
        "<li>Revise los sistemas de humidificación y ventilación si hay alertas persistentes.</li>"
        "</ul>"
    )


# ---------- markdown lite -> HTML ----------

def _markdown_to_html(md: str) -> str:
    """Convierte un subset de markdown a HTML para inyectar en el template.

    Soporta:
    - **bold**
    - *italic*
    - Listas con `- item`
    - Párrafos separados por línea en blanco
    Escapa < y > para evitar problemas.
    """
    # Escape HTML primero
    md = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Negritas e itálicas
    md = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", md)
    md = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", md)

    # Procesar líneas
    lines = md.split("\n")
    out_parts = []
    list_items = []
    para_lines = []

    def flush_para():
        nonlocal para_lines
        if para_lines:
            text = " ".join(line.strip() for line in para_lines).strip()
            if text:
                out_parts.append(f"<p>{text}</p>")
            para_lines = []

    def flush_list():
        nonlocal list_items
        if list_items:
            out_parts.append("<ul>" + "".join(f"<li>{it}</li>" for it in list_items) + "</ul>")
            list_items = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("• "):
            flush_para()
            list_items.append(stripped[2:].strip())
        elif not stripped:
            flush_para()
            flush_list()
        else:
            flush_list()
            para_lines.append(line)

    flush_para()
    flush_list()
    return "\n".join(out_parts)
