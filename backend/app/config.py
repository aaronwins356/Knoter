from __future__ import annotations

import json
from pathlib import Path

from .models import BotConfig

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "config.json"


def load_config() -> BotConfig:
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        return BotConfig(**data)
    return BotConfig()


def save_config(config: BotConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2))
