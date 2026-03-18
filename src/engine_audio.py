"""Audio transcription engine built on top of faster-whisper."""

from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel

from src.config import Config


def _validate_audio_file(file_path: str) -> Path:
    """Validate that the requested audio file exists and is a file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Audio path is not a file: {path}")
    return path


def _load_model() -> WhisperModel:
    """Create the Whisper model using the configured size and device."""
    return WhisperModel(
        Config.WHISPER_MODEL_SIZE,
        device=Config.COMPUTE_DEVICE,
    )


def _segment_to_dict(segment) -> dict:
    """Convert a faster-whisper segment into a plain dictionary."""
    return {
        "start": float(segment.start),
        "end": float(segment.end),
        "text": segment.text.strip(),
    }


def transcribe_file(file_path: str) -> list[dict]:
    """
    Transcribe a single audio file and return structured segments.

    The return format is intentionally flat so it can be converted directly
    into a pandas.DataFrame in the main pipeline.
    """
    audio_path = _validate_audio_file(file_path)
    model = _load_model()

    segments, _info = model.transcribe(str(audio_path))

    transcription: list[dict] = []
    for segment in segments:
        transcription.append(_segment_to_dict(segment))

    return transcription

