"""
main.py
-------
Entry point. Validates config, starts the Pyrogram client, and loads all
plugins from the /plugins package.
"""

from pyrogram import Client

from config import Config
from utils.logger import LOGGER

Config.validate()

app = Client(
    name="auto_caption_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins=dict(root="plugins"),
)

if __name__ == "__main__":
    LOGGER.info(f"Starting {Config.BOT_NAME}...")
    app.run()
    LOGGER.info("Bot stopped.")
