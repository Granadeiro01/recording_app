"""python-telegram-bot application wiring for the transcription bot."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from src.config import Config
from src.engine_audio import transcribe_file


logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {"m4a", "mp3", "wav", "flac", "ogg", "webm", "mp4", "mpeg", "oga"}
SUPPORTED_AUDIO_DOCUMENT_FILTER = filters.Document.AUDIO
for _extension in sorted(SUPPORTED_AUDIO_EXTENSIONS):
    SUPPORTED_AUDIO_DOCUMENT_FILTER |= filters.Document.FileExtension(_extension)

SUPPORTED_AUDIO_FILTER = filters.VOICE | filters.AUDIO | SUPPORTED_AUDIO_DOCUMENT_FILTER


@dataclass(frozen=True)
class DownloadedAttachment:
    """Metadata for a Telegram attachment that we download locally."""

    file_id: str
    file_name: str


def _ensure_output_dir() -> None:
    """Create the output directory before writing CSV exports."""
    Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _is_authorized(update: Update) -> bool:
    """Check whether the current user or chat is allowed to use the bot."""
    effective_user = update.effective_user
    effective_chat = update.effective_chat

    if Config.TELEGRAM_ALLOWED_USER_IDS and (
        effective_user is None or effective_user.id not in Config.TELEGRAM_ALLOWED_USER_IDS
    ):
        return False

    if Config.TELEGRAM_ALLOWED_CHAT_IDS and (
        effective_chat is None or effective_chat.id not in Config.TELEGRAM_ALLOWED_CHAT_IDS
    ):
        return False

    return True


def _suffix_for_mime_type(mime_type: str | None) -> str:
    """Infer a file suffix from a MIME type when no file name is available."""
    if not mime_type:
        return ".ogg"

    suffix = mimetypes.guess_extension(mime_type) or ""
    if suffix == ".oga":
        return ".ogg"
    return suffix or ".ogg"


def _attachment_from_message(update: Update) -> DownloadedAttachment | None:
    """Extract the audio attachment we want to process from the incoming message."""
    message = update.effective_message
    if message is None:
        return None

    if message.voice:
        return DownloadedAttachment(
            file_id=message.voice.file_id,
            file_name=f"{message.voice.file_unique_id}.ogg",
        )

    if message.audio:
        suffix = Path(message.audio.file_name).suffix if message.audio.file_name else _suffix_for_mime_type(message.audio.mime_type)
        file_name = message.audio.file_name or f"{message.audio.file_unique_id}{suffix}"
        return DownloadedAttachment(file_id=message.audio.file_id, file_name=file_name)

    if message.document:
        mime_type = message.document.mime_type or ""
        file_name = message.document.file_name
        if mime_type.startswith("audio/") or Path(file_name or "").suffix.lstrip(".").lower() in SUPPORTED_AUDIO_EXTENSIONS:
            suffix = Path(file_name).suffix if file_name else _suffix_for_mime_type(mime_type)
            resolved_name = file_name or f"{message.document.file_unique_id}{suffix}"
            return DownloadedAttachment(file_id=message.document.file_id, file_name=resolved_name)

    return None


async def _download_attachment(context: ContextTypes.DEFAULT_TYPE, attachment: DownloadedAttachment, target_dir: Path) -> Path:
    """Download the Telegram file into a temporary local directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    telegram_file = await context.bot.get_file(attachment.file_id)
    return await telegram_file.download_to_drive(custom_path=target_dir / attachment.file_name)


def _rows_to_text(rows: list[dict]) -> str:
    """Flatten segment rows into plain transcript text."""
    return "\n".join(row["text"] for row in rows if row.get("text"))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the user and explain how to use the bot."""
    message = update.effective_message
    if message is None:
        return

    await message.reply_text(
        "Send me a voice note, audio file, or audio document and I will transcribe it.\n"
        "If you add a caption, I will use it as extra transcription context."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain the accepted input types and the output behavior."""
    message = update.effective_message
    if message is None:
        return

    await message.reply_text(
        "Accepted inputs:\n"
        "- Voice notes\n"
        "- Audio messages\n"
        "- Audio documents such as .m4a, .mp3, .wav, .flac, .ogg, .webm\n\n"
        "Output:\n"
        "- A CSV file is saved in the configured output directory\n"
        "- A text transcript is returned in chat when it is short enough"
    )


async def transcribe_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download the audio, transcribe it, and send the result back to Telegram."""
    message = update.effective_message
    if message is None:
        return

    if not _is_authorized(update):
        await message.reply_text("This bot is restricted to approved users or chats.")
        return

    attachment = _attachment_from_message(update)
    if attachment is None:
        await message.reply_text("I could not find a supported audio attachment in that message.")
        return

    _ensure_output_dir()

    status_message = await message.reply_text("Transcribing audio...")
    temp_dir = Path(tempfile.mkdtemp(prefix="recording_app_"))

    try:
        audio_path = await _download_attachment(context, attachment, temp_dir)
        rows = await asyncio.to_thread(transcribe_file, str(audio_path), message.caption)

        df = pd.DataFrame(rows)
        output_file = Config.OUTPUT_DIR / f"{audio_path.stem}_transcription.csv"
        df.to_csv(output_file, index=False)

        transcript_text = _rows_to_text(rows)
        if transcript_text:
            if len(transcript_text) <= 3500:
                await message.reply_text(transcript_text)
            else:
                await message.reply_text("Transcript is too long for a single chat message, so I saved the CSV instead.")
        else:
            await message.reply_text("No speech was detected.")

        await message.reply_document(document=output_file, caption="Transcription CSV")
        try:
            await status_message.delete()
        except Exception:
            logger.debug("Could not delete status message", exc_info=True)
    except Exception as exc:
        logger.exception("Transcription failed")
        await message.reply_text(f"Transcription failed: {exc}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected handler exceptions."""
    logger.exception("Unhandled bot error: %s", context.error)


async def post_init(application: Application) -> None:
    """Set bot commands when the application starts."""
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show usage instructions"),
        ]
    )


def build_application() -> Application:
    """Create and configure the PTB application."""
    if not Config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in the environment")

    application = (
        ApplicationBuilder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(SUPPORTED_AUDIO_FILTER, transcribe_update))
    application.add_error_handler(on_error)
    return application
