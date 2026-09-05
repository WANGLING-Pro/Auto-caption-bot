"""
plugins/auto_caption.py
-------------------------
Listens for new posts in channels the bot manages and rewrites their
caption/text according to that channel's saved settings.

Scope guard: this handler only acts on channels present in our `channels`
collection (i.e. explicitly added by their owner through the Add Channel
flow, which already verified the bot is an admin there). It never touches
messages in channels it hasn't been configured for.
"""

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified

from database.channels import get_channel, increment_edited_count
from utils.caption_builder import build_caption
from utils.logger import LOGGER

EDITABLE_MEDIA_FILTER = (
    filters.photo
    | filters.video
    | filters.animation
    | filters.document
    | filters.audio
    | filters.voice
    | filters.video_note
    | filters.text
)


@Client.on_message(filters.channel & EDITABLE_MEDIA_FILTER)
async def auto_caption_handler(client: Client, message: Message):
    channel = await get_channel(message.chat.id)
    if not channel or not channel["settings"].get("auto_caption", False):
        return  # channel not registered, or auto-caption disabled

    new_text = build_caption(message, channel)
    if not new_text:
        return

    try:
        if message.media:
            # Photos/videos/documents/etc. use caption editing
            if new_text != (message.caption or ""):
                await message.edit_caption(new_text)
                await increment_edited_count(message.chat.id)
        else:
            # Plain text messages
            if new_text != (message.text or ""):
                await message.edit_text(new_text)
                await increment_edited_count(message.chat.id)
    except MessageNotModified:
        pass
    except Exception as e:
        LOGGER.error(f"Failed to edit message {message.id} in {message.chat.id}: {e}")
