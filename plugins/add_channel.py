"""
plugins/add_channel.py
-----------------------
"Add Channel" flow:

1. Admin taps "Add Channel" -> bot explains the steps.
2. Admin adds the bot as an admin of their channel (outside the bot).
3. Admin forwards any message FROM that channel to the bot.
4. Bot reads the forward origin to get the channel ID, then calls
   `get_chat_member` to VERIFY the bot is actually an admin there before
   saving anything.

Review fixes
------------
* `return` when the admin is not in the "awaiting_forward" state used to
  CONSUME the update (Pyrogram runs only the first matching handler per
  group; the old comment "let other handlers process it" was wrong). Now
  `message.continue_propagation()` really passes it on.
* Forward origin is read defensively (`forward_from_chat`, falling back to
  `forward_origin.chat`) because newer Pyrogram forks changed that API.
* Channel titles are HTML-escaped before being put in an HTML message.
* If the channel was already added by ANOTHER admin, say so instead of
  announcing success (database.add_channel just returns the existing doc).
* The prompt now has a Cancel button, so an admin can't get stuck in the
  "awaiting_forward" state.
"""

import html

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatMemberStatus

from utils.filters import admin_only
from utils.state import set_pending, get_pending, clear_pending
from database.channels import add_channel
from utils.logger import LOGGER


@Client.on_callback_query(filters.regex("^add_channel$") & admin_only)
async def add_channel_start(client: Client, query):
    set_pending(query.from_user.id, "awaiting_forward")
    LOGGER.info(f"[add_channel] user={query.from_user.id} is now awaiting a forward")
    await query.message.edit_text(
        "📌 <b>Add a Channel</b>\n\n"
        "1️⃣ Add me as <b>admin</b> in your channel (with permission to edit/post messages).\n"
        "2️⃣ Forward <b>any message</b> from that channel here.\n\n"
        "I'll verify my admin status automatically and save the channel.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Cancel", callback_data="main_menu")]]
        ),
    )


def _forward_origin_chat(message: Message):
    chat = getattr(message, "forward_from_chat", None)
    if chat is None:
        origin = getattr(message, "forward_origin", None)
        chat = getattr(origin, "chat", None)
    return chat


@Client.on_message(filters.private & filters.forwarded & admin_only)
async def add_channel_receive_forward(client: Client, message: Message):
    pending = get_pending(message.from_user.id)
    if not pending or pending.get("action") != "awaiting_forward":
        message.continue_propagation()  # not our flow -> let other handlers see it

    origin_chat = _forward_origin_chat(message)
    if not origin_chat or getattr(origin_chat.type, "name", "") != "CHANNEL":
        await message.reply_text("⚠️ That's not a forward from a channel. Try again.")
        return

    channel_id = origin_chat.id

    # --- Verify the bot is actually an admin of this channel ---
    try:
        me = await client.get_me()
        member = await client.get_chat_member(channel_id, me.id)
        is_admin = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception as e:
        LOGGER.warning(f"[add_channel] admin verification failed for {channel_id}: {e}")
        is_admin = False

    if not is_admin:
        await message.reply_text(
            "❌ I'm not an admin in that channel yet (or I can't verify it).\n"
            "Please add me as admin first, then forward the message again."
        )
        return

    doc = await add_channel(
        channel_id=channel_id,
        owner_id=message.from_user.id,
        title=origin_chat.title,
        username=origin_chat.username,
    )
    clear_pending(message.from_user.id)

    if doc.get("owner_id") != message.from_user.id:
        LOGGER.warning(
            f"[add_channel] {channel_id} already belongs to {doc.get('owner_id')}; "
            f"user {message.from_user.id} tried to add it"
        )
        await message.reply_text(
            "⚠️ This channel was already added by another admin, so it was not "
            "added to your list."
        )
        return

    LOGGER.info(f"[add_channel] user={message.from_user.id} added channel {channel_id}")
    await message.reply_text(
        f"✅ <b>Channel Added Successfully</b>\n\n"
        f"📺 {html.escape(origin_chat.title or '')}\n"
        f"🆔 <code>{channel_id}</code>\n\n"
        "Auto-caption is OFF by default. Open Edit Channel to configure it."
    )
