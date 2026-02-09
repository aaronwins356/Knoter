from __future__ import annotations

import json
import os
from pathlib import Path

from .models import BotConfig

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "config.json"


def load_config() -> BotConfig:
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        config = BotConfig(**data)
    else:
        config = BotConfig()
    env_live = os.getenv("KNOTER_LIVE_TRADING_ENABLED", "false").lower() in {"1", "true", "yes"}
    config.live_trading_enabled = env_live
    return config


def save_config(config: BotConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2))
