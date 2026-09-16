# auto_caption.py
"""
plugins/auto_caption.py
-------------------------
Listens for new posts in channels the bot manages and rewrites their
caption/text according to that channel's saved settings.

Scope guard: this handler only acts on channels present in our `channels`
collection (i.e. explicitly added by their owner through the Add Channel
flow, which already verified the bot is an admin there). It never touches
messages in channels it hasn't been configured for.

FORMATTING FIX: captions are now converted to explicit MessageEntity
objects via utils/html_entities.parse_html() and sent with
entities=/caption_entities= instead of relying on the client's default
parse_mode. This was required because <blockquote> and
<blockquote expandable> render as literal text under this project's
current Pyrogram build (see the investigation notes in
utils/html_entities.py for the full root-cause explanation). Passing
entities explicitly makes formatting correct regardless of what that
build's HTML tag parser does or does not support.
"""

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified

from database.channels import get_channel, increment_edited_count
from utils.caption_builder import build_caption
from utils.html_entities import parse_html
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

    # Convert the HTML built by caption_builder.py into plain text +
    # explicit entities ourselves, instead of handing raw HTML to Pyrogram
    # and hoping its parse_mode default understands every tag we use.
    plain_text, entities = parse_html(new_text)

    try:
        if message.media:
            # Photos/videos/documents/etc. use caption editing.
            # NOTE: Pyrogram's edit_caption() takes the entities parameter
            # as `caption_entities` (mirroring the Bot API's distinct
            # `caption` / `caption_entities` fields), not `entities`.
            if plain_text != (message.caption or ""):
                await message.edit_caption(plain_text, caption_entities=entities)
                await increment_edited_count(message.chat.id)
        else:
            # Plain text messages use `entities`, not `caption_entities`.
            if plain_text != (message.text or ""):
                await message.edit_text(plain_text, entities=entities)
                await increment_edited_count(message.chat.id)
    except MessageNotModified:
        pass
    except Exception as e:
        LOGGER.error(f"Failed to edit message {message.id} in {message.chat.id}: {e}")