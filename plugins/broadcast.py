"""
plugins/broadcast.py
---------------------
Simple /broadcast command for admins: replies with the message to forward,
and it gets copied to every user who has started the bot.

Usage: reply to any message with /broadcast, or send /broadcast <text>.
"""

import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from utils.filters import admin_only
from database.users import get_all_user_ids
from utils.logger import LOGGER


@Client.on_message(filters.command("broadcast") & filters.private & admin_only)
async def broadcast_handler(client: Client, message: Message):
    source = message.reply_to_message
    text_arg = message.text.split(None, 1)

    if not source and len(text_arg) < 2:
        await message.reply_text(
            "Usage: reply to a message with /broadcast, or /broadcast <text>."
        )
        return

    user_ids = await get_all_user_ids()
    status = await message.reply_text(f"📣 Broadcasting to {len(user_ids)} users...")

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            if source:
                await source.copy(uid)
            else:
                await client.send_message(uid, text_arg[1])
            sent += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            failed += 1
            LOGGER.debug(f"Broadcast failed for {uid}: {e}")
        await asyncio.sleep(0.05)  # gentle rate limiting

    await status.edit_text(f"✅ Broadcast complete.\nSent: {sent}\nFailed: {failed}")
