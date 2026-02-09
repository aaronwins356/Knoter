from __future__ import annotations

import os

import uvicorn

from app.main import app


def run() -> None:
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run()
