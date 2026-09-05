"""
main.py
-------
Entry point. Validates config, starts the Pyrogram client, and loads all
plugins from the /plugins package.
"""

import asyncio

# --- Defensive asyncio shim (fallback only, not the primary fix) ---
# Pyrogram 2.0.106's `sync.py` calls asyncio.get_event_loop() at import time.
# Python 3.14 removed the implicit event-loop auto-creation that older
# Pythons provided, so this raises RuntimeError before pyrogram even
# finishes importing if the app ever ends up running on 3.14+.
#
# The real fix is pinning the interpreter to 3.11/3.12 via runtime.txt and
# the PYTHON_VERSION env var (see README/deployment notes). This shim exists
# only so a future accidental interpreter-version drift fails soft instead
# of crashing at import time -- it does not guarantee compatibility with
# every asyncio call pyrogram makes internally.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client  # noqa: E402  (must import after the shim above)

from config import Config
from utils.logger import LOGGER
from utils.keep_alive import start_keep_alive_server

Config.validate()

app = Client(
    name="auto_caption_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins=dict(root="plugins"),
)

if __name__ == "__main__":
    # Bind $PORT first so Render's port scan succeeds immediately, then
    # hand control to Pyrogram's blocking run() -- the HTTP server keeps
    # answering in its own thread for the lifetime of the process.
    start_keep_alive_server()

    LOGGER.info(f"Starting {Config.BOT_NAME}...")
    app.run()
    LOGGER.info("Bot stopped.")
