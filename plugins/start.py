"""
plugins/start.py
-----------------
/start command: registers the user, enforces Force Subscribe if configured,
and shows the main admin panel (only admins get the management buttons;
everyone else gets a plain welcome message).
"""

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant

from config import Config
from database.users import add_user_if_new
from utils.keyboards import main_menu
from utils.logger import LOGGER


async def is_subscribed(client: Client, user_id: int) -> bool:
    if not Config.FORCE_SUB_CHANNEL:
        return True
    try:
        member = await client.get_chat_member(Config.FORCE_SUB_CHANNEL, user_id)
        return member.status not in ("left", "kicked")
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


@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user = message.from_user
    await add_user_if_new(user.id, user.first_name or "", user.username)

    if not await is_subscribed(client, user.id):
        await message.reply_text(
            "🔒 Please join our updates channel to use this bot.",
            reply_markup=force_sub_markup(),
        )
        return

    if user.id in Config.ADMINS:
        await message.reply_text(
            f"👋 Welcome back, {user.first_name}!\n\n"
            "Manage your channels' auto-captioning below.",
            reply_markup=main_menu(),
        )
    else:
        await message.reply_text(
            f"👋 Hello {user.first_name}!\n\n"
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
