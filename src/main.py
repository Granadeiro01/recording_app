"""Application entrypoint for the transcription pipeline."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from src.config import Config
from src.engine_audio import transcribe_file


logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".webm"}


def _ensure_directories() -> None:
    """Create input and output directories if they do not already exist."""
    Config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _find_audio_file(input_dir: Path) -> Path | None:
    """Return the first supported audio file found in the input directory."""
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
            return path
    return None


def main() -> int:
    """Run the transcription pipeline end to end."""
    _ensure_directories()

    audio_file = _find_audio_file(Config.INPUT_DIR)
    if audio_file is None:
        logger.error(
            "No supported audio file found in %s. Expected one of: %s",
            Config.INPUT_DIR,
            ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS)),
        )
        return 1

    logger.info("Transcribing %s", audio_file)
    try:
        transcription = transcribe_file(str(audio_file))
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected transcription failure")
        return 1

    df = pd.DataFrame(transcription)
    print(df.head())

    output_file = Config.OUTPUT_DIR / f"{audio_file.stem}_transcription.csv"
    df.to_csv(output_file, index=False)
    logger.info("Saved transcription to %s", output_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())

