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
        # BUG FIX: `member.status` is a `pyrogram.enums.ChatMemberStatus` enum
        # member, not a plain string. The original code compared it against
        # the strings "left" and "kicked", which never matched -- Pyrogram
        # doesn't even use "kicked" as a name (it uses `BANNED`) -- so this
        # check silently evaluated to True for every status Telegram
        # returned without raising UserNotParticipant, including members who
        # had actually left. Comparing against the actual enum members below
        # makes this check behave as originally intended.
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

    # ROBUSTNESS FIX (related to the collision bug in edit_channel.py):
    # /start is the natural "escape hatch" out of any in-progress conversation
    # (Add Channel forward-wait, Edit Channel free-text prompts, etc). Clear
    # any stale pending state here so a leftover `awaiting_*` flag from an
    # abandoned flow can never be picked up by a later, unrelated message.
    # This does not remove or change any existing feature -- it only resets
    # state that would otherwise be orphaned.
    clear_pending(user.id)

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