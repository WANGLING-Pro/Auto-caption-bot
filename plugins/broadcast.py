"""
plugins/broadcast.py
---------------------
Simple /broadcast command for admins: reply to a message with /broadcast, or
send /broadcast <text>; it is copied to every user who has started the bot.

Review fixes
------------
* A FloodWait used to `sleep` and then silently SKIP that user (neither sent
  nor failed). The send is now retried once after the wait.
* Registered in group=-1 so it can never be shadowed by a text handler that
  lives in group 0.
"""

import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from utils.filters import admin_only
from database.users import get_all_user_ids
from utils.logger import LOGGER


async def _send(client: Client, source, text, uid: int):
    if source:
        await source.copy(uid)
    else:
        await client.send_message(uid, text)


@Client.on_message(filters.command("broadcast") & filters.private & admin_only, group=-1)
async def broadcast_handler(client: Client, message: Message):
    source = message.reply_to_message
    text_arg = message.text.split(None, 1)

    if not source and len(text_arg) < 2:
        await message.reply_text(
            "Usage: reply to a message with /broadcast, or /broadcast <text>."
        )
        return

    text = text_arg[1] if len(text_arg) > 1 else None
    user_ids = await get_all_user_ids()
    status = await message.reply_text(f"📣 Broadcasting to {len(user_ids)} users...")

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            try:
                await _send(client, source, text, uid)
            except FloodWait as e:
                LOGGER.warning(f"[broadcast] FloodWait {e.value}s, retrying user {uid} once")
                await asyncio.sleep(e.value)
                await _send(client, source, text, uid)
            sent += 1
        except Exception as e:
            failed += 1
            LOGGER.debug(f"[broadcast] failed for {uid}: {e}")
        await asyncio.sleep(0.05)  # gentle rate limiting

    await status.edit_text(f"✅ Broadcast complete.\nSent: {sent}\nFailed: {failed}")
