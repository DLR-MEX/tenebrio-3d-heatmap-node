"""
Scheduler de reportes ejecutivos.

Usa APScheduler con SQLAlchemyJobStore para persistencia. Los jobs
sobreviven reinicios del sidecar.

Cada job al disparar:
  1) Calcula el rango temporal (ej. 'ultimo dia', 'ultima semana')
  2) Llama al generador de reportes
  3) Opcionalmente entrega via Telegram

API publica (usada por endpoints REST y tools del agente):
  - ReportScheduler.add(name, cron, period_kind, deliver_to)
  - ReportScheduler.list()
  - ReportScheduler.remove(schedule_id)
  - ReportScheduler.start()
  - ReportScheduler.stop()
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("reports.scheduler")


# Periodos predefinidos: el cliente solo elige el tipo, calculamos el
# rango temporal al disparar. Esto permite que "ultimo dia" siempre
# signifique las 24h previas al disparo, no las 24h previas a la creacion.
PERIOD_KINDS = {
    "daily": 24,      # ultimas 24 horas
    "weekly": 168,    # ultimas 7 dias (168h)
    "monthly": 720,   # ultimos 30 dias (~720h)
}


class ReportScheduler:
    """Encapsula APScheduler para reportes ejecutivos."""

    def __init__(self, db_path: Path, generator_fn, telegram_sender=None):
        """
        db_path: ruta al SQLite del jobstore (persiste jobs).
        generator_fn: callable(start_ts, end_ts, title) -> report_card dict
                      (basicamente _generate_report_sync de main.py)
        telegram_sender: callable(pdf_bytes, filename, caption) -> None
                         (opcional; si esta, schedules con deliver_to=['telegram']
                         envian via Telegram).
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.generator_fn = generator_fn
        self.telegram_sender = telegram_sender

        jobstores = {
            "default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}"),
        }
        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
        )

    # ---- lifecycle ----
    def start(self) -> None:
        self.scheduler.start()
        log.info("ReportScheduler iniciado (jobs persistidos en %s)", self.db_path)

    def stop(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception as e:
            log.warning("Scheduler shutdown fallo: %s", e)

    # ---- API publica ----
    def add(self, name: str, cron: str, period_kind: str,
            deliver_to: Optional[list[str]] = None,
            title: Optional[str] = None) -> dict:
        """Registra un nuevo schedule. Devuelve {schedule_id, next_run_iso}."""
        if period_kind not in PERIOD_KINDS:
            raise ValueError(f"period_kind invalido: {period_kind}. Valores: {list(PERIOD_KINDS)}")
        deliver_to = deliver_to or ["disk"]
        for d in deliver_to:
            if d not in ("disk", "telegram"):
                raise ValueError(f"deliver_to invalido: {d}. Valores: 'disk', 'telegram'")

        try:
            trigger = CronTrigger.from_crontab(cron)
        except Exception as e:
            raise ValueError(f"cron invalido: {cron} ({e})")

        schedule_id = f"report_{uuid.uuid4().hex[:10]}"
        job = self.scheduler.add_job(
            func=_run_scheduled_report,
            trigger=trigger,
            id=schedule_id,
            name=name,
            args=[schedule_id],  # los kwargs van en job.kwargs (persistible)
            kwargs={
                "name": name,
                "cron": cron,
                "period_kind": period_kind,
                "deliver_to": deliver_to,
                "title": title,
            },
            replace_existing=True,
        )
        log.info("Schedule '%s' agregado (next=%s, cron='%s')",
                 schedule_id, job.next_run_time, cron)
        return {
            "schedule_id": schedule_id,
            "name": name,
            "cron": cron,
            "period_kind": period_kind,
            "deliver_to": deliver_to,
            "next_run_iso": job.next_run_time.isoformat() if job.next_run_time else None,
        }

    def list(self) -> list[dict]:
        """Lista todos los schedules registrados."""
        out = []
        for job in self.scheduler.get_jobs():
            kwargs = job.kwargs or {}
            out.append({
                "schedule_id": job.id,
                "name": kwargs.get("name") or job.name or job.id,
                "cron": kwargs.get("cron"),
                "period_kind": kwargs.get("period_kind"),
                "deliver_to": kwargs.get("deliver_to"),
                "next_run_iso": job.next_run_time.isoformat() if job.next_run_time else None,
            })
        return out

    def remove(self, schedule_id: str) -> bool:
        """Cancela un schedule. Devuelve True si existia."""
        try:
            self.scheduler.remove_job(schedule_id)
            log.info("Schedule '%s' removido", schedule_id)
            return True
        except Exception as e:
            log.warning("remove %s fallo: %s", schedule_id, e)
            return False


# Globals para que el job persistido pueda re-acceder a la instancia tras
# reinicios. APScheduler serializa funciones por nombre, asi que el job
# llama a esta funcion top-level que mira un singleton.
_scheduler_instance: Optional[ReportScheduler] = None


def set_global_scheduler(s: ReportScheduler) -> None:
    global _scheduler_instance
    _scheduler_instance = s


def _run_scheduled_report(schedule_id: str, **kwargs) -> None:
    """Punto de entrada de cada job. Resuelve el rango temporal y llama
    al generador. APScheduler lo invoca por nombre (esta funcion es
    serializable por referencia)."""
    if _scheduler_instance is None:
        log.error("Job %s disparo pero no hay scheduler global", schedule_id)
        return

    period_kind = kwargs.get("period_kind", "daily")
    hours = PERIOD_KINDS.get(period_kind, 24)
    name = kwargs.get("name", schedule_id)
    deliver_to = kwargs.get("deliver_to") or ["disk"]
    title = kwargs.get("title") or f"Reporte {name}"

    end_ts = time.time()
    start_ts = end_ts - hours * 3600

    log.info("Job '%s' (%s) disparo: %.1fh, deliver_to=%s",
             schedule_id, name, hours, deliver_to)
    try:
        result = _scheduler_instance.generator_fn(start_ts, end_ts, title, True)
    except Exception as e:
        log.exception("Job '%s' fallo al generar: %s", schedule_id, e)
        return

    log.info("Job '%s' genero %s (%.1fKB)",
             schedule_id, result.get("filename"), result.get("size_kb", 0))

    # Entrega Telegram (Fase 5 — sender no implementado todavia)
    if "telegram" in deliver_to and _scheduler_instance.telegram_sender:
        try:
            from pathlib import Path as _Path
            pdf_path = _Path(__file__).resolve().parent.parent.parent / "reports" / "output" / result["filename"]
            if pdf_path.exists():
                pdf_bytes = pdf_path.read_bytes()
                summary = result.get("summary") or {}
                caption = (
                    f"📊 *{name}*\n"
                    f"Periodo: {result['meta']['start_iso']} a {result['meta']['end_iso']}\n"
                    f"Alertas críticas: {summary.get('transitions_to_abnormal', 0)} · "
                    f"Saltos: {summary.get('jumps_total', 0)}"
                )
                _scheduler_instance.telegram_sender(pdf_bytes, result["filename"], caption)
                log.info("Job '%s' entregado a Telegram", schedule_id)
        except Exception as e:
            log.warning("Job '%s' fallo Telegram delivery: %s", schedule_id, e)


# ---- Cron helper: parsear lenguaje natural simple ----

def parse_friendly_cron(spec: str) -> Optional[str]:
    """Convierte expresiones tipo 'diario 8am', 'lunes 7am', 'mensual primer dia 9am'
    a una cron expression. Devuelve None si no reconoce el patron."""
    spec = (spec or "").lower().strip()
    import re

    # diario H[am|pm] o solo H
    m = re.match(r"^diari[oa]\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", spec)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and h < 12: h += 12
        if ampm == "am" and h == 12: h = 0
        return f"{mm} {h} * * *"

    # semanal/<dia> H
    dias = {"lunes": 1, "martes": 2, "miercoles": 3, "miércoles": 3, "jueves": 4,
            "viernes": 5, "sabado": 6, "sábado": 6, "domingo": 0}
    m = re.match(r"^(?:semanal\s+)?(" + "|".join(dias) + r")\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", spec)
    if m:
        d = dias[m.group(1)]
        h = int(m.group(2))
        mm = int(m.group(3) or 0)
        ampm = m.group(4)
        if ampm == "pm" and h < 12: h += 12
        if ampm == "am" and h == 12: h = 0
        return f"{mm} {h} * * {d}"

    return None
