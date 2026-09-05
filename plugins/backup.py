"""
plugins/backup.py
------------------
Export/import a channel's caption settings as a JSON file, so an admin can
back up a configuration or copy it between their own channels.
"""

import json
import io

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from utils.filters import admin_only
from utils.keyboards import channel_list
from utils.state import set_pending, get_pending, clear_pending
from database.channels import get_channel, get_user_channels, update_settings, DEFAULT_SETTINGS


@Client.on_callback_query(filters.regex("^backup_menu$") & admin_only)
async def backup_menu(client: Client, query):
    await query.message.edit_text(
        "💾 <b>Backup / Restore</b>\n\nExport a channel's settings to a JSON file, "
        "or import a previously exported file into one of your channels.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📤 Export Channel Config", callback_data="export_pick")],
                [InlineKeyboardButton("📥 Import Channel Config", callback_data="import_pick")],
                [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")],
            ]
        ),
    )


@Client.on_callback_query(filters.regex("^export_pick$") & admin_only)
async def export_pick(client: Client, query):
    channels = await get_user_channels(query.from_user.id)
    if not channels:
        await query.answer("You have no channels yet.", show_alert=True)
        return
    await query.message.edit_text(
        "Select a channel to export:", reply_markup=channel_list(channels, "export_channel")
    )


@Client.on_callback_query(filters.regex(r"^export_channel:(-?\d+)$") & admin_only)
async def export_channel(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    channel = await get_channel(channel_id)
    if not channel or channel["owner_id"] != query.from_user.id:
        await query.answer("Not found.", show_alert=True)
        return

    payload = {
        "channel_title": channel["title"],
        "settings": channel["settings"],
    }
    buf = io.BytesIO(json.dumps(payload, indent=2).encode("utf-8"))
    buf.name = f"{channel['title']}_config.json"
    await query.message.reply_document(buf, caption=f"📤 Exported settings for {channel['title']}")


@Client.on_callback_query(filters.regex("^import_pick$") & admin_only)
async def import_pick(client: Client, query):
    set_pending(query.from_user.id, "awaiting_import_file")
    await query.message.edit_text(
        "📥 Send the exported <code>.json</code> config file now.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancel", callback_data="main_menu")]]),
    )


@Client.on_message(filters.private & filters.document & admin_only)
async def receive_import_file(client: Client, message: Message):
    pending = get_pending(message.from_user.id)
    if not pending or pending.get("action") != "awaiting_import_file":
        return

    if not message.document.file_name.endswith(".json"):
        await message.reply_text("⚠️ Please send a .json config file.")
        return

    file_path = await message.download()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("Invalid config file: missing 'settings' object.")
    except Exception as e:
        await message.reply_text(f"❌ Failed to read config file: {e}")
        clear_pending(message.from_user.id)
        return

    # Merge with defaults so an old/partial export doesn't leave keys missing
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)

    channels = await get_user_channels(message.from_user.id)
    if not channels:
        await message.reply_text("You have no channels to import into.")
        clear_pending(message.from_user.id)
        return

    set_pending(message.from_user.id, "awaiting_import_target", parsed_settings=merged)
    await message.reply_text(
        "Select which channel to apply this configuration to:",
        reply_markup=channel_list(channels, "import_apply"),
    )


@Client.on_callback_query(filters.regex(r"^import_apply:(-?\d+)$") & admin_only)
async def import_apply(client: Client, query):
    pending = get_pending(query.from_user.id)
    if not pending or pending.get("action") != "awaiting_import_target":
        await query.answer("Session expired, please start the import again.", show_alert=True)
        return

    channel_id = int(query.matches[0].group(1))
    channel = await get_channel(channel_id)
    if not channel or channel["owner_id"] != query.from_user.id:
        await query.answer("Not found.", show_alert=True)
        return

    await update_settings(channel_id, **pending["parsed_settings"])
    clear_pending(query.from_user.id)
    await query.message.edit_text(f"✅ Configuration imported into <b>{channel['title']}</b>.")
