"""
Tenebris AI Sentinel - CLI standalone para correr el servicio sin dashboard.
La logica vive en app/service.py para que tambien la consuma FastAPI.
"""

from __future__ import annotations

import logging
import signal
import sys

from app.service import Config, PredictionService, setup_logging


def main() -> int:
    try:
        cfg = Config.load()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Sugerencia: copia .env.example a .env y rellena los campos.", file=sys.stderr)
        return 2

    setup_logging(cfg.log_level)
    service = PredictionService(cfg)

    def _handle_sigint(signum, frame):
        logging.getLogger("main").info("Senal recibida, cerrando...")
        service._stop.set()

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    service.run_blocking()
    return 0


if __name__ == "__main__":
    sys.exit(main())
