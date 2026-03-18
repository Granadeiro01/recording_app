"""Environment-backed configuration for the transcription pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# Load variables from a local .env file before reading environment values.
load_dotenv()


def _parse_int_ids(raw_value: str) -> tuple[int, ...]:
    """Parse a comma-separated list of integer IDs from the environment."""
    if not raw_value.strip():
        return ()

    ids: list[int] = []
    for item in raw_value.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid integer ID value: {value!r}") from exc
    return tuple(ids)


class Config:
    """Simple config container populated from environment variables."""

    BASE_DIR = Path(__file__).resolve().parent.parent

    # Core runtime paths
    INPUT_DIR = Path(os.getenv("INPUT_DIR", BASE_DIR / "input"))
    OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))

    # Groq transcription runtime
    GROQ_TRANSCRIPTION_MODEL = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")

    # Service credentials and integration settings
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_ALLOWED_USER_IDS = _parse_int_ids(os.getenv("TELEGRAM_ALLOWED_USER_IDS", ""))
    TELEGRAM_ALLOWED_CHAT_IDS = _parse_int_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""))
