"""
main.py
-------
Entry point.

The keep-alive HTTP server is started FIRST (before importing pyrogram or
validating config) so Render's port scan always succeeds. Every boot phase
prints an unbuffered marker so the Render log shows exactly how far startup
got.

Review changes: logs Python / Pyrogram versions at boot (so you can see which
interpreter and library Render actually used), and tells you if the Python
version is not the one in .python-version.
"""

import sys

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("[BOOT] main.py execution started", flush=True)

from utils.keep_alive import start_keep_alive_server  # noqa: E402

print("[BOOT] keep_alive module imported", flush=True)

_keep_alive_server = start_keep_alive_server()

print("[BOOT] keep-alive server call returned -- port is now bound and listening", flush=True)

# --- asyncio shim (Python 3.14 compatibility guard; no-op on 3.11) ------
import asyncio  # noqa: E402

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import pyrogram  # noqa: E402
from pyrogram import Client  # noqa: E402

from config import Config  # noqa: E402
from utils.logger import LOGGER  # noqa: E402

print(f"[BOOT] python={sys.version.split()[0]} pyrogram={getattr(pyrogram, '__version__', '?')}", flush=True)
if sys.version_info[:2] != (3, 11):
    LOGGER.warning(
        f"Running on Python {sys.version.split()[0]}, but this project targets 3.11. "
        "Render ignores runtime.txt: add a .python-version file (or PYTHON_VERSION env var)."
    )

print("[BOOT] validating config...", flush=True)
Config.validate()
print("[BOOT] config OK", flush=True)

app = Client(
    name="auto_caption_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins=dict(root="plugins"),
)

if __name__ == "__main__":
    LOGGER.info(f"Starting {Config.BOT_NAME}...")
    print("[BOOT] calling app.run() -- this call blocks for the bot's lifetime", flush=True)
    try:
        app.run()
    except Exception:
        import traceback
        print("[FATAL] Pyrogram raised an exception during run():", flush=True)
        traceback.print_exc()
        raise
    LOGGER.info("Bot stopped.")
    print("[BOOT] app.run() returned -- process exiting", flush=True)
