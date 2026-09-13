"""
main.py
-------
Entry point.

CRITICAL ORDERING: the keep-alive HTTP server is bound and started as the
FIRST executable code in this file -- before importing pyrogram, before
Config.validate(), before anything else that could conceivably raise,
hang, or take time. This makes it structurally impossible for bot-side
startup work (Telegram handshake, Mongo connection, plugin loading) to
delay or block Render's port scan.

Every phase below also prints an unbuffered marker line. This is
deliberate: Render pipes stdout, and Python block-buffers stdout when it
isn't a TTY, so print()/logging output can sit invisible in a buffer for
a long time. A process can be working correctly and still look "silent"
or "hung" in the dashboard purely because of buffering. These print(...,
flush=True) markers exist to give unambiguous, real-time proof of exactly
how far execution has gotten, on every deploy, from now on.
"""

import sys

# Force line-buffered (effectively unbuffered) stdout/stderr immediately,
# before anything else runs, so every print below actually reaches the log
# viewer in real time instead of sitting in a buffer.
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

from pyrogram import Client  # noqa: E402

from config import Config  # noqa: E402
from utils.logger import LOGGER  # noqa: E402

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
