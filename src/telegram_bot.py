"""python-telegram-bot application wiring for the transcription bot."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import Config
from src.engine_audio import transcribe_file
from src.settings_store import SettingsStore, TranscriptionSettings, normalize_language, render_settings_summary


logger = logging.getLogger(__name__)
SETTINGS_ACTION_KEY = "settings_action"
SETTINGS_ACTION_WAIT_LANGUAGE = "await_language"

SETTINGS_CALLBACK_LANGUAGE = "settings:language"
SETTINGS_CALLBACK_TOGGLE_PRESERVE = "settings:toggle_preserve"
SETTINGS_CALLBACK_RESET = "settings:reset"
SETTINGS_CALLBACK_AUTO = "settings:auto"
SETTINGS_CALLBACK_CLOSE = "settings:close"

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
    """Create the output directory before writing transcript exports."""
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


def _build_output_text(transcript_text: str) -> str:
    """Return the final text written to disk and sent to the user."""
    if transcript_text.strip():
        return transcript_text.strip()
    return "No speech was detected."


def _settings_store(context: ContextTypes.DEFAULT_TYPE) -> SettingsStore:
    """Fetch the shared settings store from application state."""
    return context.application.bot_data["settings_store"]


def _user_id(update: Update) -> int | None:
    """Return the active Telegram user ID if available."""
    if update.effective_user is None:
        return None
    return update.effective_user.id


def _settings_keyboard() -> InlineKeyboardMarkup:
    """Build the inline keyboard for the settings menu."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Preferred language", callback_data=SETTINGS_CALLBACK_LANGUAGE),
                InlineKeyboardButton("Auto language", callback_data=SETTINGS_CALLBACK_AUTO),
            ],
            [
                InlineKeyboardButton("Toggle preserve", callback_data=SETTINGS_CALLBACK_TOGGLE_PRESERVE),
                InlineKeyboardButton("Reset", callback_data=SETTINGS_CALLBACK_RESET),
            ],
            [InlineKeyboardButton("Close", callback_data=SETTINGS_CALLBACK_CLOSE)],
        ]
    )


async def _send_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the current settings menu."""
    user_id = _user_id(update)
    message = update.effective_message
    if user_id is None or message is None:
        return

    settings = _settings_store(context).get(user_id)
    await message.reply_text(render_settings_summary(settings), reply_markup=_settings_keyboard())


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the settings menu."""
    if not _is_authorized(update):
        message = update.effective_message
        if message is not None:
            await message.reply_text("This bot is restricted to approved users or chats.")
        return

    context.user_data.pop(SETTINGS_ACTION_KEY, None)
    await _send_settings_menu(update, context)


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings menu button clicks."""
    query = update.callback_query
    if query is None or update.effective_user is None:
        return

    if not _is_authorized(update):
        await query.answer("This bot is restricted.", show_alert=True)
        return

    await query.answer()
    user_id = update.effective_user.id
    store = _settings_store(context)

    if query.data == SETTINGS_CALLBACK_LANGUAGE:
        context.user_data[SETTINGS_ACTION_KEY] = SETTINGS_ACTION_WAIT_LANGUAGE
        if query.message is not None:
            await query.message.reply_text(
                "Send the language code you want to use.\n"
                "Examples: `auto`, `en`, `es`, `pt-br`\n"
                "This is used only when 'Preserve spoken language' is Off.\n"
                "Reply with the code as a normal text message.",
                parse_mode="Markdown",
            )
        return

    if query.data == SETTINGS_CALLBACK_AUTO:
        updated = store.set_language(user_id, "auto")
        if query.message is not None:
            await query.message.reply_text(render_settings_summary(updated), reply_markup=_settings_keyboard())
        return

    if query.data == SETTINGS_CALLBACK_TOGGLE_PRESERVE:
        updated = store.toggle_preserve_spoken_language(user_id)
        if query.message is not None:
            await query.message.reply_text(render_settings_summary(updated), reply_markup=_settings_keyboard())
        return

    if query.data == SETTINGS_CALLBACK_RESET:
        updated = store.reset(user_id)
        if query.message is not None:
            await query.message.reply_text(render_settings_summary(updated), reply_markup=_settings_keyboard())
        return

    if query.data == SETTINGS_CALLBACK_CLOSE:
        if query.message is not None:
            await query.message.edit_text("Settings menu closed.")
        return


async def settings_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture the next text message as a language setting value."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    if context.user_data.get(SETTINGS_ACTION_KEY) != SETTINGS_ACTION_WAIT_LANGUAGE:
        return

    if not _is_authorized(update):
        await message.reply_text("This bot is restricted to approved users or chats.")
        context.user_data.pop(SETTINGS_ACTION_KEY, None)
        return

    raw_value = (message.text or "").strip()
    try:
        normalized_language = normalize_language(raw_value)
    except ValueError as exc:
        await message.reply_text(f"{exc}\n\nTry again with a valid code like `auto`, `en`, or `pt-br`.", parse_mode="Markdown")
        return

    updated = _settings_store(context).set_language(user.id, normalized_language)
    context.user_data.pop(SETTINGS_ACTION_KEY, None)
    await message.reply_text(render_settings_summary(updated), reply_markup=_settings_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the user and explain how to use the bot."""
    message = update.effective_message
    if message is None:
        return

    await message.reply_text(
        "Send me a voice note, audio file, or audio document and I will transcribe it.\n"
        "Use /settings to keep mixed-language speech in the original language.\n"
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
        "- A TXT file is saved in the configured output directory\n"
        "- A text transcript is returned in chat when it is short enough\n\n"
        "Use /settings to keep mixed-language speech in the original language.\n"
        "If preservation is Off, the preferred language will be used instead."
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
        user_id = _user_id(update)
        user_settings = _settings_store(context).get(user_id) if user_id is not None else TranscriptionSettings()
        rows = await asyncio.to_thread(
            transcribe_file,
            str(audio_path),
            message.caption,
            user_settings,
        )

        transcript_text = _rows_to_text(rows)
        output_text = _build_output_text(transcript_text)
        output_file = Config.OUTPUT_DIR / f"{audio_path.stem}_transcription.txt"
        output_file.write_text(output_text, encoding="utf-8")

        if transcript_text:
            if len(transcript_text) <= 3500:
                await message.reply_text(transcript_text)
            else:
                await message.reply_text("Transcript is too long for a single chat message, so I saved the TXT file instead.")
        else:
            await message.reply_text("No speech was detected.")

        await message.reply_document(document=output_file, caption="Transcription TXT")
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
            BotCommand("settings", "Change transcription settings"),
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

    application.bot_data["settings_store"] = SettingsStore(Config.USER_CONFIG_FILE)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^settings:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, settings_text))
    application.add_handler(MessageHandler(SUPPORTED_AUDIO_FILTER, transcribe_update))
    application.add_error_handler(on_error)
    return application
