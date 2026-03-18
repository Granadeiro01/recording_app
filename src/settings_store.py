"""File-backed per-user transcription settings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any


DEFAULT_LANGUAGE = "auto"
DEFAULT_PRESERVE_SPOKEN_LANGUAGE = True
SETTINGS_FILE_VERSION = 1
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(?:[-_][a-z0-9]{2,8})?$", re.IGNORECASE)


@dataclass(slots=True)
class TranscriptionSettings:
    """Per-user settings that influence the Groq transcription request."""

    language: str = DEFAULT_LANGUAGE
    preserve_spoken_language: bool = DEFAULT_PRESERVE_SPOKEN_LANGUAGE

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "TranscriptionSettings":
        """Create settings from a JSON-compatible mapping."""
        if not data:
            return cls()

        language = normalize_language(data.get("language", DEFAULT_LANGUAGE))
        preserve_spoken_language = bool(
            data.get("preserve_spoken_language", DEFAULT_PRESERVE_SPOKEN_LANGUAGE)
        )
        return cls(language=language, preserve_spoken_language=preserve_spoken_language)

    def to_mapping(self) -> dict[str, Any]:
        """Serialize the settings to a JSON-compatible mapping."""
        return {
            "language": self.language,
            "preserve_spoken_language": self.preserve_spoken_language,
        }

    def groq_language(self) -> str | None:
        """Return the language parameter for Groq, or None for auto-detection."""
        if self.language == DEFAULT_LANGUAGE:
            return None
        return self.language

    def build_prompt(self, base_prompt: str | None = None) -> str | None:
        """Build the final prompt sent to Groq."""
        parts: list[str] = []
        if base_prompt and base_prompt.strip():
            parts.append(base_prompt.strip())

        if self.preserve_spoken_language:
            parts.append(
                "Transcribe exactly as spoken. Preserve code-switching and keep all "
                "spoken languages as written. Do not translate or normalize the speech."
            )

        prompt = " ".join(parts).strip()
        return prompt or None


def normalize_language(raw_value: str) -> str:
    """Normalize and validate a language code."""
    value = raw_value.strip().lower()
    if not value:
        return DEFAULT_LANGUAGE
    if value in {"auto", "default"}:
        return DEFAULT_LANGUAGE
    if not LANGUAGE_PATTERN.match(value):
        raise ValueError(
            "Language must be 'auto' or a short ISO-style code such as 'en', 'es', or 'pt-br'."
        )
    return value.replace("_", "-")


def render_settings_summary(settings: TranscriptionSettings) -> str:
    """Format settings as a short human-readable summary."""
    language_label = "Auto" if settings.language == DEFAULT_LANGUAGE else settings.language.upper()
    preserve_label = "On" if settings.preserve_spoken_language else "Off"
    return (
        "Current transcription settings:\n"
        f"- Language: {language_label}\n"
        f"- Preserve spoken language: {preserve_label}\n\n"
        "Tap a button below to change them."
    )


class SettingsStore:
    """JSON-backed store for Telegram user settings."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()

    def get(self, user_id: int) -> TranscriptionSettings:
        """Return settings for a user, falling back to defaults."""
        data = self._load()
        user_blob = data.get("users", {}).get(str(user_id))
        return TranscriptionSettings.from_mapping(user_blob)

    def set_language(self, user_id: int, language: str) -> TranscriptionSettings:
        """Persist a user's transcription language preference."""
        with self._lock:
            data = self._load()
            settings = self._user_settings(data, user_id)
            settings.language = normalize_language(language)
            self._write_user_settings(data, user_id, settings)
            return settings

    def toggle_preserve_spoken_language(self, user_id: int) -> TranscriptionSettings:
        """Flip the preserve-spoken-language preference."""
        with self._lock:
            data = self._load()
            settings = self._user_settings(data, user_id)
            settings.preserve_spoken_language = not settings.preserve_spoken_language
            self._write_user_settings(data, user_id, settings)
            return settings

    def reset(self, user_id: int) -> TranscriptionSettings:
        """Reset a user's preferences to defaults."""
        with self._lock:
            data = self._load()
            settings = TranscriptionSettings()
            self._write_user_settings(data, user_id, settings)
            return settings

    def _load(self) -> dict[str, Any]:
        """Load the complete settings file."""
        if not self.path.exists():
            return self._default_payload()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid settings file: {self.path}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"Invalid settings file structure: {self.path}")

        payload.setdefault("version", SETTINGS_FILE_VERSION)
        payload.setdefault("defaults", TranscriptionSettings().to_mapping())
        payload.setdefault("users", {})
        return payload

    def _default_payload(self) -> dict[str, Any]:
        """Build the default file structure."""
        return {
            "version": SETTINGS_FILE_VERSION,
            "defaults": TranscriptionSettings().to_mapping(),
            "users": {},
        }

    def _user_settings(self, payload: dict[str, Any], user_id: int) -> TranscriptionSettings:
        """Read a user's settings from the loaded payload."""
        defaults = TranscriptionSettings.from_mapping(payload.get("defaults"))
        user_blob = payload.get("users", {}).get(str(user_id))
        user_settings = TranscriptionSettings.from_mapping(user_blob)
        return TranscriptionSettings(
            language=user_settings.language or defaults.language,
            preserve_spoken_language=user_settings.preserve_spoken_language,
        )

    def _write_user_settings(
        self,
        payload: dict[str, Any],
        user_id: int,
        settings: TranscriptionSettings,
    ) -> None:
        """Persist a single user's settings back to disk."""
        payload.setdefault("version", SETTINGS_FILE_VERSION)
        payload.setdefault("defaults", TranscriptionSettings().to_mapping())
        payload.setdefault("users", {})
        payload["users"][str(user_id)] = settings.to_mapping()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.path)
