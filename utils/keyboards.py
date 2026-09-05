"""
utils/keyboards.py
-------------------
All inline keyboard layouts, kept in one place so UI changes don't require
hunting through handler files.
"""

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
            [InlineKeyboardButton("✏️ Edit Channel", callback_data="edit_channel_list")],
            [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
            [InlineKeyboardButton("💾 Backup / Restore", callback_data="backup_menu")],
        ]
    )


def channel_list(channels: list[dict], prefix: str) -> InlineKeyboardMarkup:
    """`prefix` distinguishes contexts, e.g. 'select_edit' vs 'select_export'."""
    rows = []
    for ch in channels:
        label = ch.get("title") or str(ch["_id"])
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}:{ch['_id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def channel_panel(channel_id: int, auto_caption_on: bool) -> InlineKeyboardMarkup:
    toggle_label = "🟢 Auto Caption: ON" if auto_caption_on else "🔴 Auto Caption: OFF"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(toggle_label, callback_data=f"toggle_caption:{channel_id}")],
            [InlineKeyboardButton("📝 Caption Template", callback_data=f"set_template:{channel_id}")],
            [InlineKeyboardButton("🔝 Header Text", callback_data=f"set_header:{channel_id}")],
            [InlineKeyboardButton("🔻 Footer Text", callback_data=f"set_footer:{channel_id}")],
            [InlineKeyboardButton("💧 Watermark Text", callback_data=f"set_watermark:{channel_id}")],
            [InlineKeyboardButton("🔁 Word Replace", callback_data=f"replace_menu:{channel_id}")],
            [InlineKeyboardButton("🗑 Word Remove", callback_data=f"remove_menu:{channel_id}")],
            [InlineKeyboardButton("👁 Preview Caption", callback_data=f"preview:{channel_id}")],
            [InlineKeyboardButton("♻️ Reset Settings", callback_data=f"reset_settings:{channel_id}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="edit_channel_list")],
        ]
    )


def confirm_cancel(action: str, channel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{action}:{channel_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"channel_panel:{channel_id}"),
            ]
        ]
    )


def back_to_panel(channel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back", callback_data=f"channel_panel:{channel_id}")]]
    )
