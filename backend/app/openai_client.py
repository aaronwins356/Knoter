from __future__ import annotations

import os
import json
from typing import Optional

import requests

from .models import AdvisorOutput


class OpenAIClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def configured(self) -> bool:
        return bool(self.api_key)

    def advise(self, prompt: str) -> Optional[AdvisorOutput]:
        if not self.configured():
            return None
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a trading advisor. Respond ONLY with JSON in the exact format: "
                            '{"sentiment": -1..1, "confidence": 0..1, "notes": "...", "veto": false}. '
                            "Never recommend executing trades directly."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        try:
            data = json.loads(content)
            return AdvisorOutput(**data)
        except json.JSONDecodeError:
            return AdvisorOutput(sentiment=0.0, confidence=0.0, notes="Advisor returned invalid JSON.", veto=False)
