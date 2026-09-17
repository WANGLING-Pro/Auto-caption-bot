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
from utils.html_entities import parse_html
from utils.logger import LOGGER
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

TEXT_FIELDS = {
    "set_template": ("caption_template", "📝 Send your caption template.\n\nAvailable variables:\n"
                      "<code>{filename} {filesize} {duration} {caption} {default_caption} "
                      "{channel_name} {channel_username} {message_id} {date} {time}</code>"),
    "set_header": ("header", "🔝 Send the header text to prepend to every caption."),
    "set_footer": ("footer", "🔻 Send the footer text to append to every caption."),
    "set_watermark": ("watermark", "💧 Send the watermark text (rendered as a blockquote)."),
}

NOT_COMMAND = filters.create(lambda _, __, m: not (m.text or "").startswith("/"))


async def _panel_text_and_markup(channel_id: int):
    channel = await get_channel(channel_id)
    if not channel:
        return "⚠️ Channel not found (it may have been removed).", None

    auto_on = channel["settings"].get("auto_caption", False)
    text = (
        f"⚙️ <b>{channel['title']}</b>\n"
        f"🆔 <code>{channel_id}</code>\n\n"
        "Configure auto-captioning below:"
    )
    markup = channel_panel(channel_id, auto_on)
    return text, markup


async def _render_panel(query_or_message, channel_id: int, edit: bool = True):
    text, markup = await _panel_text_and_markup(channel_id)

    if edit:
        await query_or_message.edit_text(text, reply_markup=markup)
        LOGGER.info(f"[edit_channel] _render_panel: EDITED existing message for channel {channel_id}")
    else:
        await query_or_message.reply_text(text, reply_markup=markup)
        LOGGER.info(f"[edit_channel] _render_panel: SENT NEW message for channel {channel_id}")


async def _edit_message(client: Client, chat_id: int, message_id: int, text: str, reply_markup=None):
    await client.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
    LOGGER.info(f"[edit_channel] _edit_message: EDITED message {message_id} in chat {chat_id}")


async def _render_panel_by_id(client: Client, chat_id: int, message_id: int, channel_id: int, prefix: str = ""):
    text, markup = await _panel_text_and_markup(channel_id)
    if prefix:
        text = f"{prefix}\n\n{text}"
    await _edit_message(client, chat_id, message_id, text, reply_markup=markup)


@Client.on_callback_query(filters.regex("^edit_channel_list$") & admin_only)
async def edit_channel_list(client: Client, query):
    LOGGER.info(f"[edit_channel] Handler=edit_channel_list user={query.from_user.id}")
    channels = await get_user_channels(query.from_user.id)
    if not channels:
        await query.message.edit_text(
            "You haven't added any channels yet. Use ➕ Add Channel first.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
            ),
        )
        LOGGER.info("[edit_channel] edit_channel_list: EDITED message (no channels)")
        return
    await query.message.edit_text(
        "📺 <b>Select a channel to edit:</b>", reply_markup=channel_list(channels, "select_edit")
    )
    LOGGER.info("[edit_channel] edit_channel_list: EDITED message (channel list)")


@Client.on_callback_query(filters.regex(r"^select_edit:(-?\d+)$") & admin_only)
async def select_edit(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=select_edit user={query.from_user.id} channel_id={channel_id}")
    await _render_panel(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^channel_panel:(-?\d+)$") & admin_only)
async def channel_panel_cb(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=channel_panel_cb user={query.from_user.id} channel_id={channel_id}")
    clear_pending(query.from_user.id)
    await _render_panel(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^toggle_caption:(-?\d+)$") & admin_only)
async def toggle_caption(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=toggle_caption user={query.from_user.id} channel_id={channel_id}")
    channel = await get_channel(channel_id)
    new_state = not channel["settings"].get("auto_caption", False)
    await update_settings(channel_id, auto_caption=new_state)
    await query.answer(f"Auto Caption turned {'ON' if new_state else 'OFF'}")
    await _render_panel(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^(set_template|set_header|set_footer|set_watermark):(-?\d+)$") & admin_only)
async def prompt_text_field(client: Client, query):
    action, channel_id = query.matches[0].group(1), int(query.matches[0].group(2))
    LOGGER.info(f"[edit_channel] Handler=prompt_text_field action={action} user={query.from_user.id} channel_id={channel_id}")
    _, prompt = TEXT_FIELDS[action]

    set_pending(
        query.from_user.id,
        "awaiting_text",
        field=action,
        channel_id=channel_id,
        panel_message_id=query.message.id,
    )
    await query.message.edit_text(
        f"{prompt}\n\nSend <code>-</code> to clear this field.",
        reply_markup=back_to_panel(channel_id),
    )
    LOGGER.info(f"[edit_channel] prompt_text_field: EDITED message {query.message.id}, stored as panel_message_id")


@Client.on_message(filters.private & filters.text & NOT_COMMAND & admin_only)
async def capture_text_input(client: Client, message: Message):
    pending = get_pending(message.from_user.id)
    if not pending:
        LOGGER.debug(f"[edit_channel] Handler=capture_text_input: no pending state for user {message.from_user.id}, ignoring")
        return

    action = pending.get("action")
    channel_id = pending.get("channel_id")
    panel_message_id = pending.get("panel_message_id")
    value = None if message.text.strip() == "-" else message.text

    LOGGER.info(
        f"[edit_channel] Handler=capture_text_input action={action} user={message.from_user.id} "
        f"channel_id={channel_id} panel_message_id={panel_message_id}"
    )

    if action == "awaiting_text":
        field_key, _ = TEXT_FIELDS[pending["field"]]
        await update_settings(channel_id, **{field_key: value})
        clear_pending(message.from_user.id)

        if panel_message_id:
            await _render_panel_by_id(client, message.chat.id, panel_message_id, channel_id, prefix="✅ Saved.")
        else:
            LOGGER.warning(
                "[edit_channel] capture_text_input(awaiting_text): no panel_message_id in pending state "
                "-- falling back to sending new messages"
            )
            await message.reply_text("✅ Saved.")
            await _render_panel(message, channel_id, edit=False)

    elif action == "awaiting_replace_from":
        set_pending(
            message.from_user.id,
            "awaiting_replace_to",
            channel_id=channel_id,
            word_from=message.text,
            panel_message_id=panel_message_id,
        )
        if panel_message_id:
            await _edit_message(
                client, message.chat.id, panel_message_id,
                f"Replace <b>{message.text}</b> with:",
                reply_markup=back_to_panel(channel_id),
            )
        else:
            LOGGER.warning(
                "[edit_channel] capture_text_input(awaiting_replace_from): no panel_message_id -- "
                "falling back to sending a new message"
            )
            await message.reply_text(f"Replace <b>{message.text}</b> with:")

    elif action == "awaiting_replace_to":
        await add_replace_word(channel_id, pending["word_from"], message.text)
        clear_pending(message.from_user.id)

        if panel_message_id:
            await _render_panel_by_id(
                client, message.chat.id, panel_message_id, channel_id,
                prefix="✅ Replacement rule added.",
            )
        else:
            LOGGER.warning(
                "[edit_channel] capture_text_input(awaiting_replace_to): no panel_message_id -- "
                "falling back to sending new messages"
            )
            await message.reply_text("✅ Replacement rule added.")
            await _render_panel(message, channel_id, edit=False)

    elif action == "awaiting_remove_word":
        await add_remove_word(channel_id, message.text)
        clear_pending(message.from_user.id)

        if panel_message_id:
            await _render_panel_by_id(
                client, message.chat.id, panel_message_id, channel_id,
                prefix="✅ Word/phrase added to removal list.",
            )
        else:
            LOGGER.warning(
                "[edit_channel] capture_text_input(awaiting_remove_word): no panel_message_id -- "
                "falling back to sending new messages"
            )
            await message.reply_text("✅ Word/phrase added to removal list.")
            await _render_panel(message, channel_id, edit=False)


@Client.on_callback_query(filters.regex(r"^replace_menu:(-?\d+)$") & admin_only)
async def replace_menu(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=replace_menu user={query.from_user.id} channel_id={channel_id}")
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
    LOGGER.info(f"[edit_channel] replace_menu: EDITED message {query.message.id}")


@Client.on_callback_query(filters.regex(r"^add_replace:(-?\d+)$") & admin_only)
async def add_replace_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=add_replace_prompt user={query.from_user.id} channel_id={channel_id}")
    set_pending(
        query.from_user.id,
        "awaiting_replace_from",
        channel_id=channel_id,
        panel_message_id=query.message.id,
    )
    await query.message.edit_text(
        "🔁 Send the word/phrase to find (in your own captions):",
        reply_markup=back_to_panel(channel_id),
    )
    LOGGER.info(f"[edit_channel] add_replace_prompt: EDITED message {query.message.id}, stored as panel_message_id")


@Client.on_callback_query(filters.regex(r"^del_replace:(-?\d+):(.+)$") & admin_only)
async def del_replace(client: Client, query):
    channel_id, word_from = int(query.matches[0].group(1)), query.matches[0].group(2)
    LOGGER.info(f"[edit_channel] Handler=del_replace user={query.from_user.id} channel_id={channel_id}")
    await remove_replace_word(channel_id, word_from)
    await query.answer("Removed.")
    await replace_menu(client, query)


@Client.on_callback_query(filters.regex(r"^remove_menu:(-?\d+)$") & admin_only)
async def remove_menu(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=remove_menu user={query.from_user.id} channel_id={channel_id}")
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
    LOGGER.info(f"[edit_channel] remove_menu: EDITED message {query.message.id}")


@Client.on_callback_query(filters.regex(r"^add_remove:(-?\d+)$") & admin_only)
async def add_remove_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=add_remove_prompt user={query.from_user.id} channel_id={channel_id}")
    set_pending(
        query.from_user.id,
        "awaiting_remove_word",
        channel_id=channel_id,
        panel_message_id=query.message.id,
    )
    await query.message.edit_text(
        "🗑 Send the word/phrase you want automatically deleted from your own captions "
        "(e.g. outdated promo text you posted earlier):",
        reply_markup=back_to_panel(channel_id),
    )
    LOGGER.info(f"[edit_channel] add_remove_prompt: EDITED message {query.message.id}, stored as panel_message_id")


@Client.on_callback_query(filters.regex(r"^del_remove:(-?\d+):(.+)$") & admin_only)
async def del_remove(client: Client, query):
    channel_id, phrase = int(query.matches[0].group(1)), query.matches[0].group(2)
    LOGGER.info(f"[edit_channel] Handler=del_remove user={query.from_user.id} channel_id={channel_id}")
    await remove_remove_word(channel_id, phrase)
    await query.answer("Removed.")
    await remove_menu(client, query)


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
    LOGGER.info(f"[edit_channel] Handler=preview user={query.from_user.id} channel_id={channel_id}")
    channel = await get_channel(channel_id)
    sample = _FakeMessage(
        "This is a sample caption with a common typo (recieved) and an outdated "
        "tagline: 'Best Quality Since 2019'."
    )
    rendered = build_caption(sample, channel)

    full_html = f"👁 <b>Preview</b> (using sample data)\n\n{'-' * 20}\n\n{rendered}"
    plain_text, entities = parse_html(full_html)

    await query.message.edit_text(
        plain_text,
        entities=entities,
        reply_markup=back_to_panel(channel_id),
    )
    LOGGER.info(f"[edit_channel] preview: EDITED message {query.message.id}")


@Client.on_callback_query(filters.regex(r"^reset_settings:(-?\d+)$") & admin_only)
async def reset_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=reset_prompt user={query.from_user.id} channel_id={channel_id}")
    await query.message.edit_text(
        "⚠️ This will reset ALL caption settings for this channel. Continue?",
        reply_markup=confirm_cancel("reset", channel_id),
    )
    LOGGER.info(f"[edit_channel] reset_prompt: EDITED message {query.message.id}")


@Client.on_callback_query(filters.regex(r"^confirm_reset:(-?\d+)$") & admin_only)
async def reset_confirm(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=reset_confirm user={query.from_user.id} channel_id={channel_id}")
    await reset_settings(channel_id)
    await query.answer("Settings reset.")
    await _render_panel(query.message, channel_id)