"""
plugins/menu.py
----------------
Handles returning to the main admin menu from anywhere in the panel.
"""

from pyrogram import Client, filters
from utils.filters import admin_only
from utils.keyboards import main_menu
from utils.state import clear_pending


@Client.on_callback_query(filters.regex("^main_menu$") & admin_only)
async def back_to_main_menu(client: Client, query):
    clear_pending(query.from_user.id)
    await query.message.edit_text("🏠 <b>Main Menu</b>", reply_markup=main_menu())
