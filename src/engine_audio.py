"""Audio transcription engine built on top of the Groq API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import groq
from groq import Groq

from src.config import Config
from src.settings_store import TranscriptionSettings


def _validate_audio_file(file_path: str) -> Path:
    """Validate that the requested audio file exists and is a file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Audio path is not a file: {path}")
    return path


def _build_client() -> Groq:
    """Create a Groq client using the configured API key."""
    if not Config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in the environment")
    return Groq(api_key=Config.GROQ_API_KEY)


def _segment_value(segment: Any, key: str) -> Any:
    """Read a value from either a dict-like or object-like segment."""
    if isinstance(segment, dict):
        return segment.get(key)
    return getattr(segment, key)


def _segment_to_dict(segment: Any) -> dict:
    """Convert a Groq segment into the flat dict shape used by the pipeline."""
    return {
        "start": float(_segment_value(segment, "start")),
        "end": float(_segment_value(segment, "end")),
        "text": str(_segment_value(segment, "text")).strip(),
    }


def _extract_segments(transcription: Any) -> list[Any]:
    """Return the list of segment objects from a Groq response."""
    if isinstance(transcription, dict):
        return list(transcription.get("segments", []))
    return list(getattr(transcription, "segments", []))


def transcribe_file(
    file_path: str,
    prompt: str | None = None,
    settings: TranscriptionSettings | None = None,
) -> list[dict]:
    """
    Transcribe a single audio file with Groq and return structured segments.

    The return format stays flat so it can be converted directly into a
    pandas.DataFrame in the main pipeline.
    """
    audio_path = _validate_audio_file(file_path)
    client = _build_client()
    active_settings = settings or TranscriptionSettings()
    request_prompt = active_settings.build_prompt(prompt)

    try:
        with audio_path.open("rb") as audio_file:
            request_kwargs: dict[str, Any] = {
                "file": audio_file,
                "model": Config.GROQ_TRANSCRIPTION_MODEL,
                "response_format": "verbose_json",
                "timestamp_granularities": ["segment"],
                "temperature": 0.0,
            }
            groq_language = active_settings.groq_language()
            if groq_language is not None:
                request_kwargs["language"] = groq_language
            if request_prompt is not None:
                request_kwargs["prompt"] = request_prompt

            transcription = client.audio.transcriptions.create(**request_kwargs)
    except groq.APIError as exc:
        raise RuntimeError(f"Groq transcription failed: {exc}") from exc

    transcription_rows: list[dict] = []
    for segment in _extract_segments(transcription):
        transcription_rows.append(_segment_to_dict(segment))

    return transcription_rows
