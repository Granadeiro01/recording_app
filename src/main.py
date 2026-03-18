"""Application entrypoint for the Telegram transcription bot."""

from __future__ import annotations

import logging
import sys

from src.telegram_bot import build_application


logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    """Run the PTB polling loop."""
    try:
        application = build_application()
        logger.info("Starting Telegram bot polling")
        application.run_polling()
    except Exception:
        logger.exception("Telegram bot failed to start")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
