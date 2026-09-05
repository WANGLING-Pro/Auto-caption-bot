"""
plugins/edit_channel.py
------------------------
"Edit Channel" flow: pick a channel -> management panel -> configure
auto-caption, template, header/footer/watermark, word replace/remove,
preview, and reset -- all via inline buttons plus short text prompts for
free-form fields.
"""

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from utils.filters import admin_only
from utils.keyboards import channel_list, channel_panel, confirm_cancel, back_to_panel
from utils.state import set_pending, get_pending, clear_pending
from utils.caption_builder import build_caption
from database.channels import (
    get_channel,
    get_user_channels,
    update_settings,
    reset_settings,
    add_replace_word,
    remove_replace_word,
    add_remove_word,
    remove_remove_word,
)

# Fields that are simple "send me a text message" settings
TEXT_FIELDS = {
    "set_template": ("caption_template", "📝 Send your caption template.\n\nAvailable variables:\n"
                      "<code>{filename} {filesize} {duration} {caption} {default_caption} "
                      "{channel_name} {channel_username} {message_id} {date} {time}</code>"),
    "set_header": ("header", "🔝 Send the header text to prepend to every caption."),
    "set_footer": ("footer", "🔻 Send the footer text to append to every caption."),
    "set_watermark": ("watermark", "💧 Send the watermark text (rendered as a blockquote)."),
}


async def _render_panel(query_or_message, channel_id: int, edit: bool = True):
    channel = await get_channel(channel_id)
    if not channel:
        text = "⚠️ Channel not found (it may have been removed)."
        markup = None
    else:
        auto_on = channel["settings"].get("auto_caption", False)
        text = (
            f"⚙️ <b>{channel['title']}</b>\n"
            f"🆔 <code>{channel_id}</code>\n\n"
            "Configure auto-captioning below:"
        )
        markup = channel_panel(channel_id, auto_on)

    if edit:
        await query_or_message.edit_text(text, reply_markup=markup)
    else:
        await query_or_message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex("^edit_channel_list$") & admin_only)
async def edit_channel_list(client: Client, query):
    channels = await get_user_channels(query.from_user.id)
    if not channels:
        await query.message.edit_text(
            "You haven't added any channels yet. Use ➕ Add Channel first.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
            ),
        )
        return
    await query.message.edit_text(
        "📺 <b>Select a channel to edit:</b>", reply_markup=channel_list(channels, "select_edit")
    )


@Client.on_callback_query(filters.regex(r"^select_edit:(-?\d+)$") & admin_only)
async def select_edit(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    await _render_panel(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^channel_panel:(-?\d+)$") & admin_only)
async def channel_panel_cb(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    clear_pending(query.from_user.id)
    await _render_panel(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^toggle_caption:(-?\d+)$") & admin_only)
async def toggle_caption(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    channel = await get_channel(channel_id)
    new_state = not channel["settings"].get("auto_caption", False)
    await update_settings(channel_id, auto_caption=new_state)
    await query.answer(f"Auto Caption turned {'ON' if new_state else 'OFF'}")
    await _render_panel(query.message, channel_id)


# --- Free-text field setters (template/header/footer/watermark) ---

@Client.on_callback_query(filters.regex(r"^(set_template|set_header|set_footer|set_watermark):(-?\d+)$") & admin_only)
async def prompt_text_field(client: Client, query):
    action, channel_id = query.matches[0].group(1), int(query.matches[0].group(2))
    _, prompt = TEXT_FIELDS[action]
    set_pending(query.from_user.id, "awaiting_text", field=action, channel_id=channel_id)
    await query.message.edit_text(
        f"{prompt}\n\nSend <code>-</code> to clear this field.",
        reply_markup=back_to_panel(channel_id),
    )


@Client.on_message(filters.private & filters.text & admin_only)
async def capture_text_input(client: Client, message: Message):
    pending = get_pending(message.from_user.id)
    if not pending:
        return

    action = pending.get("action")
    channel_id = pending.get("channel_id")
    value = None if message.text.strip() == "-" else message.text

    if action == "awaiting_text":
        field_key, _ = TEXT_FIELDS[pending["field"]]
        await update_settings(channel_id, **{field_key: value})
        clear_pending(message.from_user.id)
        await message.reply_text("✅ Saved.")
        await _render_panel(message, channel_id, edit=False)

    elif action == "awaiting_replace_from":
        set_pending(message.from_user.id, "awaiting_replace_to", channel_id=channel_id, word_from=message.text)
        await message.reply_text(f"Replace <b>{message.text}</b> with:")

    elif action == "awaiting_replace_to":
        await add_replace_word(channel_id, pending["word_from"], message.text)
        clear_pending(message.from_user.id)
        await message.reply_text("✅ Replacement rule added.")
        await _render_panel(message, channel_id, edit=False)

    elif action == "awaiting_remove_word":
        await add_remove_word(channel_id, message.text)
        clear_pending(message.from_user.id)
        await message.reply_text("✅ Word/phrase added to removal list.")
        await _render_panel(message, channel_id, edit=False)


# --- Word Replace menu ---

@Client.on_callback_query(filters.regex(r"^replace_menu:(-?\d+)$") & admin_only)
async def replace_menu(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    channel = await get_channel(channel_id)
    pairs = channel["settings"].get("replace_words", [])

    rows = [
        [InlineKeyboardButton(f"❌ {p['from']} → {p['to']}", callback_data=f"del_replace:{channel_id}:{p['from']}")]
        for p in pairs
    ]
    rows.append([InlineKeyboardButton("➕ Add Replacement", callback_data=f"add_replace:{channel_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"channel_panel:{channel_id}")])

    text = "🔁 <b>Word Replace Rules</b>\n\nTap a rule to delete it." if pairs else \
           "🔁 <b>Word Replace Rules</b>\n\nNo rules yet."
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^add_replace:(-?\d+)$") & admin_only)
async def add_replace_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    set_pending(query.from_user.id, "awaiting_replace_from", channel_id=channel_id)
    await query.message.edit_text(
        "🔁 Send the word/phrase to find (in your own captions):",
        reply_markup=back_to_panel(channel_id),
    )


@Client.on_callback_query(filters.regex(r"^del_replace:(-?\d+):(.+)$") & admin_only)
async def del_replace(client: Client, query):
    channel_id, word_from = int(query.matches[0].group(1)), query.matches[0].group(2)
    await remove_replace_word(channel_id, word_from)
    await query.answer("Removed.")
    await replace_menu(client, query)


# --- Word Remove menu ---

@Client.on_callback_query(filters.regex(r"^remove_menu:(-?\d+)$") & admin_only)
async def remove_menu(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    channel = await get_channel(channel_id)
    words = channel["settings"].get("remove_words", [])

    rows = [
        [InlineKeyboardButton(f"❌ {w}", callback_data=f"del_remove:{channel_id}:{w}")] for w in words
    ]
    rows.append([InlineKeyboardButton("➕ Add Word/Phrase", callback_data=f"add_remove:{channel_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"channel_panel:{channel_id}")])

    text = "🗑 <b>Word Removal List</b>\n\nTap an entry to delete it." if words else \
           "🗑 <b>Word Removal List</b>\n\nNo entries yet."
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^add_remove:(-?\d+)$") & admin_only)
async def add_remove_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    set_pending(query.from_user.id, "awaiting_remove_word", channel_id=channel_id)
    await query.message.edit_text(
        "🗑 Send the word/phrase you want automatically deleted from your own captions "
        "(e.g. outdated promo text you posted earlier):",
        reply_markup=back_to_panel(channel_id),
    )


@Client.on_callback_query(filters.regex(r"^del_remove:(-?\d+):(.+)$") & admin_only)
async def del_remove(client: Client, query):
    channel_id, phrase = int(query.matches[0].group(1)), query.matches[0].group(2)
    await remove_remove_word(channel_id, phrase)
    await query.answer("Removed.")
    await remove_menu(client, query)


# --- Preview ---

class _FakeMedia:
    def __init__(self):
        self.file_name = "sample_file.mp4"
        self.file_size = 734_003_200
        self.duration = 1425


class _FakeMessage:
    """Stand-in message object so Preview works without needing a real upload."""
    def __init__(self, text: str):
        self.caption = text
        self.text = None
        self.id = 123456
        self.document = None
        self.audio = None
        self.voice = None
        self.video_note = None
        self.animation = None
        self.photo = None
        self.video = _FakeMedia()


@Client.on_callback_query(filters.regex(r"^preview:(-?\d+)$") & admin_only)
async def preview(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    channel = await get_channel(channel_id)
    sample = _FakeMessage(
        "This is a sample caption with a common typo (recieved) and an outdated "
        "tagline: 'Best Quality Since 2019'."
    )
    rendered = build_caption(sample, channel)
    await query.message.edit_text(
        f"👁 <b>Preview</b> (using sample data)\n\n{'-'*20}\n\n{rendered}",
        reply_markup=back_to_panel(channel_id),
    )


# --- Reset ---

@Client.on_callback_query(filters.regex(r"^reset_settings:(-?\d+)$") & admin_only)
async def reset_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    await query.message.edit_text(
        "⚠️ This will reset ALL caption settings for this channel. Continue?",
        reply_markup=confirm_cancel("reset", channel_id),
    )


@Client.on_callback_query(filters.regex(r"^confirm_reset:(-?\d+)$") & admin_only)
async def reset_confirm(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    await reset_settings(channel_id)
    await query.answer("Settings reset.")
    await _render_panel(query.message, channel_id)
