"""
plugins/start.py
-----------------
/start command: registers the user, enforces Force Subscribe if configured,
and shows the main admin panel (only admins get the management buttons;
everyone else gets a plain welcome message).

Review changes
--------------
* Registered with group=-1. In Pyrogram only the FIRST matching handler of a
  group runs, and plugin files load alphabetically (add_channel, auto_caption,
  backup, broadcast, edit_channel, ... start). The old edit_channel text
  handler matched "/start" for admins, returned, and start_handler (loaded
  later) never ran -- that was the original "/start does not respond" bug.
  Putting commands in their own group makes them independent of whatever
  group-0 text handlers exist or get added later.
* The user's first name is HTML-escaped (names like "A <b>" broke the message).
* Debug log line so you can see /start arriving in the Render log.
"""

import html

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant
from pyrogram.enums import ChatMemberStatus

from config import Config
from database.users import add_user_if_new
from utils.keyboards import main_menu
from utils.logger import LOGGER
from utils.state import clear_pending


async def is_subscribed(client: Client, user_id: int) -> bool:
    if not Config.FORCE_SUB_CHANNEL:
        return True
    try:
        member = await client.get_chat_member(Config.FORCE_SUB_CHANNEL, user_id)
        # `member.status` is a ChatMemberStatus enum member (not a string).
        return member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
    except UserNotParticipant:
        return False
    except Exception as e:
        LOGGER.warning(f"Force-sub check failed: {e}")
        return True  # fail-open so a misconfigured force-sub doesn't lock everyone out


def force_sub_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{Config.FORCE_SUB_CHANNEL}")],
            [InlineKeyboardButton("🔄 I've Joined", callback_data="check_sub")],
        ]
    )


@Client.on_message(filters.command("start") & filters.private, group=-1)
async def start_handler(client: Client, message: Message):
    user = message.from_user
    if not user:
        return
    LOGGER.info(f"[start] /start from user={user.id} admin={user.id in Config.ADMINS}")
    await add_user_if_new(user.id, user.first_name or "", user.username)

    if not await is_subscribed(client, user.id):
        await message.reply_text(
            "🔒 Please join our updates channel to use this bot.",
            reply_markup=force_sub_markup(),
        )
        return

    # /start is the escape hatch out of any in-progress conversation.
    clear_pending(user.id)

    name = html.escape(user.first_name or "", quote=False)
    if user.id in Config.ADMINS:
        await message.reply_text(
            f"👋 Welcome back, {name}!\n\n"
            "Manage your channels' auto-captioning below.",
            reply_markup=main_menu(),
        )
    else:
        await message.reply_text(
            f"👋 Hello {name}!\n\n"
            "This bot automatically formats captions for channels its "
            "administrators have configured it on."
        )


@Client.on_callback_query(filters.regex("^check_sub$"))
async def check_sub_callback(client: Client, query):
    if await is_subscribed(client, query.from_user.id):
        await query.message.delete()
        await query.message.reply_text("✅ Thanks for joining! Send /start again.")
    else:
        await query.answer("You haven't joined yet.", show_alert=True)
