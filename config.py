"""
config.py
---------
Central configuration for the bot. All secrets/IDs are read from environment
variables so nothing sensitive is hardcoded into source control.

Set these in a `.env` file (loaded via python-dotenv in main.py) or directly
in your process environment / hosting platform's config panel.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get_int_list(env_name: str) -> list[int]:
    """Parse a comma-separated env var of integers into a list."""
    raw = os.environ.get(env_name, "")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


class Config:
    # --- Telegram API credentials (https://my.telegram.org) ---
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

    # --- MongoDB ---
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "caption_bot")

    # --- Admins allowed to use the bot's management panel ---
    # NOTE: this list controls who can add/manage channels through the bot.
    # The bot additionally requires it to be an actual admin of any Telegram
    # channel before it will touch that channel's content.
    ADMINS = _get_int_list("ADMINS")

    # --- Force Subscribe (optional) ---
    # Username (without @) of a channel users must join to use the bot.
    FORCE_SUB_CHANNEL = os.environ.get("FORCE_SUB_CHANNEL", "").lstrip("@")

    # --- Misc ---
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "0"))  # optional, 0 = disabled
    BOT_NAME = os.environ.get("BOT_NAME", "AutoCaptionBot")

    @classmethod
    def validate(cls):
        missing = []
        for field in ("API_ID", "API_HASH", "BOT_TOKEN"):
            if not getattr(cls, field):
                missing.append(field)
        if missing:
            raise RuntimeError(
                f"Missing required config values: {', '.join(missing)}. "
                "Set them as environment variables or in a .env file."
            )
