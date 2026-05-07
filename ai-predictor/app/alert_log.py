"""
Persistencia local de transiciones de estado de los sensores.

El TelegramNotifier ya detecta transiciones (ok->abnormal o abnormal->ok)
pero solo las usaba para mandar mensajes Telegram en runtime. Aqui las
escribimos a un SQLite local para poder responder consultas tipo
"hubo anomalias ayer?" desde el agente IA, sin depender de la memoria
del proceso (sobrevive reinicios).

Tabla unica `alert_events`:
  id              INTEGER PRIMARY KEY AUTOINCREMENT
  ts              REAL NOT NULL          -- epoch seconds
  group_name      TEXT NOT NULL          -- "TEMP" | "HUM"
  var             TEXT NOT NULL          -- "t1", "h3", ...
  prev_state      TEXT NOT NULL          -- "ok" | "abnormal" | "unknown"
  new_state       TEXT NOT NULL
  kind            TEXT NOT NULL          -- "current" | "predicted"
  value           REAL                   -- valor actual al momento de la transicion
  predicted_value REAL                   -- valor predicho (para kind="predicted")

Indices: (ts), (group_name, ts), (var, ts) para queries comunes.

Concurrencia: una conexion compartida con `check_same_thread=False` y
un lock por escritura. Lecturas no necesitan lock con `journal_mode=WAL`.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    group_name      TEXT NOT NULL,
    var             TEXT NOT NULL,
    prev_state      TEXT NOT NULL,
    new_state       TEXT NOT NULL,
    kind            TEXT NOT NULL,
    value           REAL,
    predicted_value REAL
);
CREATE INDEX IF NOT EXISTS idx_alert_events_ts          ON alert_events(ts);
CREATE INDEX IF NOT EXISTS idx_alert_events_group_ts    ON alert_events(group_name, ts);
CREATE INDEX IF NOT EXISTS idx_alert_events_var_ts      ON alert_events(var, ts);
"""


class AlertLog:
    """Persistencia thread-safe de transiciones de estado."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        # check_same_thread=False porque la conexion la usan multiples threads
        # (el callback MQTT escribe, los handlers HTTP leen). Lo serializamos
        # con _lock para escrituras; lecturas concurrentes con WAL son seguras.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.commit()
        log.info("AlertLog en %s", self.db_path)

    def record(
        self,
        ts: float,
        group_name: str,
        var: str,
        prev_state: str,
        new_state: str,
        kind: str,
        value: Optional[float] = None,
        predicted_value: Optional[float] = None,
    ) -> None:
        """Escribe una transicion. Llamado desde el callback MQTT."""
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO alert_events
                       (ts, group_name, var, prev_state, new_state, kind, value, predicted_value)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ts, group_name, var, prev_state, new_state, kind, value, predicted_value),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                log.warning("AlertLog.record fallo: %s", e)

    def query(
        self,
        group_name: Optional[str] = None,
        var: Optional[str] = None,
        kind: Optional[str] = None,
        new_state: Optional[str] = None,
        since_ts: Optional[float] = None,
        until_ts: Optional[float] = None,
        limit: int = 50,
    ) -> list[dict]:
        """SELECT con filtros opcionales. Devuelve lista de dicts ordenados
        por ts descendente (mas reciente primero)."""
        clauses = []
        params: list = []
        if group_name:
            clauses.append("group_name = ?")
            params.append(group_name)
        if var:
            clauses.append("var = ?")
            params.append(var)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if new_state:
            clauses.append("new_state = ?")
            params.append(new_state)
        if since_ts is not None:
            clauses.append("ts >= ?")
            params.append(since_ts)
        if until_ts is not None:
            clauses.append("ts <= ?")
            params.append(until_ts)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM alert_events {where} ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))
        try:
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.Error as e:
            log.warning("AlertLog.query fallo: %s", e)
            return []

    def count(
        self,
        group_name: Optional[str] = None,
        new_state: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> int:
        """COUNT con filtros tipicos (cuantas transiciones a abnormal hoy)."""
        clauses = []
        params: list = []
        if group_name:
            clauses.append("group_name = ?")
            params.append(group_name)
        if new_state:
            clauses.append("new_state = ?")
            params.append(new_state)
        if since_ts is not None:
            clauses.append("ts >= ?")
            params.append(since_ts)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT COUNT(*) AS n FROM alert_events {where}"
        try:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
            return int(row["n"]) if row else 0
        except sqlite3.Error as e:
            log.warning("AlertLog.count fallo: %s", e)
            return 0

    def cleanup(self, older_than_days: int = 30) -> int:
        """Borra registros mas viejos que N dias. Devuelve filas borradas."""
        cutoff = time.time() - (older_than_days * 86400)
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM alert_events WHERE ts < ?", (cutoff,))
                self._conn.commit()
                deleted = cur.rowcount
                if deleted > 0:
                    log.info("AlertLog.cleanup borro %d filas mas viejas que %dd", deleted, older_than_days)
                return deleted
            except sqlite3.Error as e:
                log.warning("AlertLog.cleanup fallo: %s", e)
                return 0

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
