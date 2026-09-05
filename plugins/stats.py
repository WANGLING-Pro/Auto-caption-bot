"""
plugins/stats.py
-----------------
Shows aggregate bot statistics to admins: total users, total channels,
and total edited messages.
"""

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from utils.filters import admin_only
from database.users import total_users
from database.channels import total_channels, total_edited_messages


@Client.on_callback_query(filters.regex("^stats$") & admin_only)
async def stats_handler(client: Client, query):
    users, channels, edited = (
        await total_users(),
        await total_channels(),
        await total_edited_messages(),
    )
    text = (
        "📊 <b>Bot Statistics</b>\n\n"
        f"👤 Total Users: <b>{users}</b>\n"
        f"📺 Total Channels: <b>{channels}</b>\n"
        f"✏️ Total Edited Messages: <b>{edited}</b>"
    )
    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]])
    )
