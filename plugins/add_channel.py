"""
plugins/add_channel.py
-----------------------
"Add Channel" flow:

1. Admin taps "Add Channel" -> bot explains the steps.
2. Admin adds the bot as an admin of their channel (outside the bot, in
   Telegram's own UI).
3. Admin forwards any message FROM that channel to the bot.
4. Bot reads the forward origin to get the channel ID, then calls
   `get_chat_member` to VERIFY the bot is actually an admin there before
   saving anything. This is the enforcement point that keeps the bot's
   caption-editing limited to channels it has been legitimately granted
   admin access to -- it will refuse to save a channel it isn't an admin
   of, even if the forwarded message looks right.
"""

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus

from utils.filters import admin_only
from utils.state import set_pending, get_pending, clear_pending
from database.channels import add_channel
from utils.logger import LOGGER


@Client.on_callback_query(filters.regex("^add_channel$") & admin_only)
async def add_channel_start(client: Client, query):
    set_pending(query.from_user.id, "awaiting_forward")
    await query.message.edit_text(
        "📌 <b>Add a Channel</b>\n\n"
        "1️⃣ Add me as <b>admin</b> in your channel (with permission to edit/post messages).\n"
        "2️⃣ Forward <b>any message</b> from that channel here.\n\n"
        "I'll verify my admin status automatically and save the channel."
    )


@Client.on_message(filters.private & filters.forwarded & admin_only)
async def add_channel_receive_forward(client: Client, message: Message):
    pending = get_pending(message.from_user.id)
    if not pending or pending.get("action") != "awaiting_forward":
        return  # not in the middle of this flow -- let other handlers process it

    origin_chat = message.forward_from_chat
    if not origin_chat or origin_chat.type.name != "CHANNEL":
        await message.reply_text("⚠️ That's not a forward from a channel. Try again.")
        return

    channel_id = origin_chat.id

    # --- Verify the bot is actually an admin of this channel ---
    try:
        me = await client.get_me()
        member = await client.get_chat_member(channel_id, me.id)
        is_admin = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception as e:
        LOGGER.warning(f"Admin verification failed for {channel_id}: {e}")
        is_admin = False

    if not is_admin:
        await message.reply_text(
            "❌ I'm not an admin in that channel yet (or I can't verify it).\n"
            "Please add me as admin first, then forward the message again."
        )
        return

    await add_channel(
        channel_id=channel_id,
        owner_id=message.from_user.id,
        title=origin_chat.title,
        username=origin_chat.username,
    )
    clear_pending(message.from_user.id)

    await message.reply_text(
        f"✅ <b>Channel Added Successfully</b>\n\n"
        f"📺 {origin_chat.title}\n"
        f"🆔 <code>{channel_id}</code>\n\n"
        "Auto-caption is OFF by default. Open Edit Channel to configure it."
    )
