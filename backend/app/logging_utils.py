import json
import logging
from datetime import datetime
from typing import Any, Dict


def configure_logging() -> None:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]


def log_event(event: str, payload: Dict[str, Any]) -> None:
    message = json.dumps(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": event,
            **payload,
        },
        default=str,
    )
    logging.getLogger("kalshi_bot").info(message)
