from __future__ import annotations

import os
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
                            "You are a trading advisor. Provide bullet explanations and risk warnings. "
                            "Never recommend executing trades directly; only explain or suggest parameter tweaks."
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
        lines = [line.strip("- ") for line in content.splitlines() if line.strip()]
        explanations = lines[:6] if lines else ["No advisory returned."]
        warnings = [line for line in lines if "risk" in line.lower()][:3]
        suggestions = [line for line in lines if "suggest" in line.lower()][:3]
        return AdvisorOutput(explanations=explanations, warnings=warnings, suggestions=suggestions)
