# plugins/auto_caption.py
"""
plugins/auto_caption.py
-------------------------
Listens for new posts in channels the bot manages and rewrites their
caption/text according to that channel's saved settings.

Scope guard: only acts on channels present in our `channels` collection.

Review fixes (vs. previous version)
-----------------------------------
* The "is the new text identical to the old text?" shortcut is GONE. It
  compared PLAIN text only, so a formatting-only template such as
  `<blockquote>{default_caption}</blockquote>` produced identical plain text
  and was silently skipped (the blockquote never got applied). We now always
  attempt the edit; Telegram answers MESSAGE_NOT_MODIFIED when nothing
  changes, which is handled below.
* Text-vs-caption is decided by `message.text is not None`, not by
  `message.media`. A text post with a link preview has a truthy `.media`
  (WEB_PAGE) in Pyrogram, which sent it down the caption-editing path.
* parse_html() used to run OUTSIDE the try block, so any formatting problem
  escaped the handler and the post was left unedited with only a Pyrogram
  traceback. Everything is inside one try/except now, with logging.
* Sending goes through utils/formatting.edit_message_html(), which probes the
  installed library and picks native HTML or explicit entities (see
  utils/formatting.py). It also avoids relying on Message.edit_caption's
  `caption_entities` parameter, whose existence differs between builds.
* Length limits are checked (caption 1024, text 4096) with a clear log line
  instead of a MEDIA_CAPTION_TOO_LONG error after the fact.
* FloodWait is waited out and retried once.
"""

import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, MessageNotModified

from database.channels import get_channel, increment_edited_count
from utils.caption_builder import build_caption
from utils.formatting import edit_message_html
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

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


@Client.on_message(filters.channel & EDITABLE_MEDIA_FILTER)
async def auto_caption_handler(client: Client, message: Message):
    try:
        await _process(client, message)
    except Exception as e:
        LOGGER.exception(
            f"[auto_caption] unexpected failure for message {getattr(message, 'id', '?')} "
            f"in {getattr(message.chat, 'id', '?')}: {type(e).__name__}: {e}"
        )


async def _process(client: Client, message: Message):
    chat_id = message.chat.id
    channel = await get_channel(chat_id)
    if not channel:
        LOGGER.debug(f"[auto_caption] {chat_id}: channel not registered, ignoring")
        return
    if not channel["settings"].get("auto_caption", False):
        LOGGER.debug(f"[auto_caption] {chat_id}: auto_caption is OFF, ignoring")
        return

    new_html = build_caption(message, channel)
    if not new_html:
        LOGGER.debug(f"[auto_caption] {chat_id}/{message.id}: nothing to write")
        return

    is_text = message.text is not None
    plain, _ = parse_html(new_html)
    limit = TEXT_LIMIT if is_text else CAPTION_LIMIT
    if len(plain) > limit:
        LOGGER.warning(
            f"[auto_caption] {chat_id}/{message.id}: result is {len(plain)} chars "
            f"(limit {limit}) -- skipped. Shorten header/footer/template."
        )
        return

    LOGGER.info(
        f"[auto_caption] {chat_id}/{message.id}: editing "
        f"{'text' if is_text else 'caption'} ({len(plain)} chars)"
    )

    for attempt in (1, 2):
        try:
            await edit_message_html(client, chat_id, message.id, new_html, is_caption=not is_text)
            await increment_edited_count(chat_id)
            return
        except MessageNotModified:
            LOGGER.debug(f"[auto_caption] {chat_id}/{message.id}: already up to date")
            return
        except FloodWait as e:
            if attempt == 2:
                raise
            LOGGER.warning(f"[auto_caption] FloodWait {e.value}s, retrying once")
            await asyncio.sleep(e.value)
