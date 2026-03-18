# recording_app

A small Telegram bot that transcribes voice notes and audio files into text.

## What it does

- You send the bot a voice note, audio file, or audio document in Telegram.
- The bot transcribes the audio using Groq.
- The bot sends the text back in chat.
- A TXT copy is also saved locally in the `output/` folder.

## What you need first

1. A Telegram bot token from [BotFather](https://t.me/BotFather).
2. A Groq API key.
3. Python installed on your computer.

## Quick setup

1. Open the project folder.
2. Create a file named `.env` if it does not already exist.
3. Put these values in `.env`:

```env
GROQ_API_KEY=your_groq_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GROQ_TRANSCRIPTION_MODEL=whisper-large-v3
```

4. Install the dependencies:

```bash
./.venv/bin/pip install -r requirements.txt
```

5. Start the bot:

```bash
./.venv/bin/python -m src.main
```

## How to use it

1. Open the Telegram chat with your bot.
2. Send a voice message, audio file, or supported audio document.
3. Wait a few seconds.
4. Read the transcript in chat.
5. Find the TXT file in `output/`.

## Supported audio types

- Voice notes
- Audio files like `.m4a`, `.mp3`, `.wav`, `.flac`, `.ogg`, `.webm`
- Audio documents sent through Telegram

## Optional access control

If you want only specific people to use the bot, add their Telegram user IDs to `.env`:

```env
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

Leave these empty if you want the bot to accept messages from anyone who can reach it.

## Settings inside Telegram

Use `/settings` in the Telegram chat to change how transcription behaves for your account.

You can:

- choose the transcription language
- leave it on `auto` for mixed or unknown language audio
- turn code-switch preservation on or off

The bot saves these choices in a local `.config` file for your Telegram user ID.
That means your settings stay the same after you restart the bot.

## Files you will touch most often

- `.env` for secrets and local settings
- `.config` for your Telegram transcription preferences
- `input/` if you want to keep sample audio files locally
- `output/` for saved TXT transcripts

## Notes

- Do not commit `.env` to GitHub.
- Use `.env.example` as the template if you need to recreate the settings.
