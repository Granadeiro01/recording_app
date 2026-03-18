"""Environment-backed configuration for the transcription pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# Load variables from a local .env file before reading environment values.
load_dotenv()


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
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
    TELEGRAM_PHONE_NUMBER = os.getenv("TELEGRAM_PHONE_NUMBER", "")
    TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "")
