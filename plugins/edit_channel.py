"""
plugins/edit_channel.py
------------------------
"Edit Channel" flow: pick a channel -> management panel -> configure
auto-caption, template, header/footer/watermark, word replace/remove,
preview, and reset -- all via inline buttons plus short text prompts.

Review fixes (vs. previous version)
-----------------------------------
* Panel updates: every update of the panel goes through an EDIT of the stored
  panel message (callback `query.message` or `panel_message_id` from the
  pending state). The admin's own typed message is deleted (best effort) so
  the chat doesn't fill up. The "send a new message" fallbacks remain only for
  a missing panel_message_id and log a WARNING when used.
* MessageNotModified is swallowed (it used to bubble up as an unhandled error).
* callback_data for deleting replace/remove rules used the raw word. Telegram
  limits callback_data to 64 BYTES, so any longish/non-ASCII word made the
  whole menu fail with BUTTON_DATA_INVALID. Buttons now carry an index.
* All user/DB-provided text that goes into an HTML message is escaped
  (channel title, typed words). Before, `<` or `&` broke the message.
* Every channel callback verifies the channel exists and belongs to the
  clicking admin (toggle_caption used to crash on a missing channel).
* Saving a caption template validates it first ({unknown}, stray braces).
* Preview goes through utils/formatting (same path as real posts), never
  fails silently, and shows a warning if the installed library can't render
  expandable blockquotes.
* The text handler no longer swallows non-text states silently, and passes
  the update on (continue_propagation) when there is nothing pending.
"""

import html

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from utils.filters import admin_only
from utils.keyboards import channel_list, channel_panel, confirm_cancel, back_to_panel
from utils.state import set_pending, get_pending, clear_pending
from utils.caption_builder import build_caption, validate_template
from utils.formatting import edit_message_html, capability_warning
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
                      "{channel_name} {channel_username} {message_id} {date} {time}</code>\n\n"
                      "Telegram HTML is allowed (&lt;b&gt;, &lt;i&gt;, &lt;a href&gt;, "
                      "&lt;blockquote&gt;, &lt;blockquote expandable&gt;)."),
    "set_header": ("header", "🔝 Send the header text to prepend to every caption."),
    "set_footer": ("footer", "🔻 Send the footer text to append to every caption."),
    "set_watermark": ("watermark", "💧 Send the watermark text (rendered as a blockquote)."),
}

# Delete the admin's typed answer after processing it (keeps the chat tidy).
DELETE_USER_INPUT = True

NOT_COMMAND = filters.create(lambda _, __, m: not (m.text or "").startswith("/"))


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


def _short(value, n: int = 40) -> str:
    value = str(value)
    return value if len(value) <= n else value[: n - 1] + "…"


# ---------------------------------------------------------------- helpers
async def _get_owned_channel(query, channel_id: int):
    """Return the channel doc if it exists and belongs to the clicking admin."""
    channel = await get_channel(channel_id)
    if not channel:
        await query.answer("Channel not found (it may have been removed).", show_alert=True)
        return None
    if channel.get("owner_id") != query.from_user.id:
        LOGGER.warning(
            f"[edit_channel] user {query.from_user.id} tried to access channel "
            f"{channel_id} owned by {channel.get('owner_id')}"
        )
        await query.answer("This channel belongs to another admin.", show_alert=True)
        return None
    return channel


async def _safe_edit(message, text: str, reply_markup=None):
    """message.edit_text that ignores MessageNotModified."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except MessageNotModified:
        LOGGER.debug(f"[edit_channel] message {message.id} not modified (same content)")


async def _panel_text_and_markup(channel_id: int):
    channel = await get_channel(channel_id)
    if not channel:
        return "⚠️ Channel not found (it may have been removed).", None

    auto_on = channel["settings"].get("auto_caption", False)
    text = (
        f"⚙️ <b>{_esc(channel['title'])}</b>\n"
        f"🆔 <code>{channel_id}</code>\n\n"
        "Configure auto-captioning below:"
    )
    return text, channel_panel(channel_id, auto_on)


async def _render_panel(query_or_message, channel_id: int, edit: bool = True):
    text, markup = await _panel_text_and_markup(channel_id)

    if edit:
        await _safe_edit(query_or_message, text, markup)
        LOGGER.info(f"[edit_channel] _render_panel: EDITED existing message for channel {channel_id}")
    else:
        await query_or_message.reply_text(text, reply_markup=markup)
        LOGGER.info(f"[edit_channel] _render_panel: SENT NEW message for channel {channel_id}")


async def _edit_message(client: Client, chat_id: int, message_id: int, text: str, reply_markup=None):
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )
        LOGGER.info(f"[edit_channel] _edit_message: EDITED message {message_id} in chat {chat_id}")
    except MessageNotModified:
        LOGGER.debug(f"[edit_channel] _edit_message: message {message_id} not modified")


async def _render_panel_by_id(client: Client, chat_id: int, message_id: int, channel_id: int, prefix: str = ""):
    text, markup = await _panel_text_and_markup(channel_id)
    if prefix:
        text = f"{prefix}\n\n{text}"
    await _edit_message(client, chat_id, message_id, text, reply_markup=markup)


async def _cleanup_user_message(message: Message):
    if not DELETE_USER_INPUT:
        return
    try:
        await message.delete()
    except Exception as e:
        LOGGER.debug(f"[edit_channel] could not delete user message {message.id}: {e}")


# --------------------------------------------------------------- navigation
@Client.on_callback_query(filters.regex("^edit_channel_list$") & admin_only)
async def edit_channel_list(client: Client, query):
    LOGGER.info(f"[edit_channel] Handler=edit_channel_list user={query.from_user.id}")
    clear_pending(query.from_user.id)
    channels = await get_user_channels(query.from_user.id)
    if not channels:
        await _safe_edit(
            query.message,
            "You haven't added any channels yet. Use ➕ Add Channel first.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]),
        )
        return
    await _safe_edit(
        query.message, "📺 <b>Select a channel to edit:</b>", channel_list(channels, "select_edit")
    )


@Client.on_callback_query(filters.regex(r"^select_edit:(-?\d+)$") & admin_only)
async def select_edit(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=select_edit user={query.from_user.id} channel_id={channel_id}")
    if not await _get_owned_channel(query, channel_id):
        return
    await _render_panel(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^channel_panel:(-?\d+)$") & admin_only)
async def channel_panel_cb(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=channel_panel_cb user={query.from_user.id} channel_id={channel_id}")
    clear_pending(query.from_user.id)
    if not await _get_owned_channel(query, channel_id):
        return
    await _render_panel(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^toggle_caption:(-?\d+)$") & admin_only)
async def toggle_caption(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=toggle_caption user={query.from_user.id} channel_id={channel_id}")
    channel = await _get_owned_channel(query, channel_id)
    if not channel:
        return
    new_state = not channel["settings"].get("auto_caption", False)
    await update_settings(channel_id, auto_caption=new_state)
    await query.answer(f"Auto Caption turned {'ON' if new_state else 'OFF'}")
    await _render_panel(query.message, channel_id)


# ------------------------------------------------------- free-text fields
@Client.on_callback_query(filters.regex(r"^(set_template|set_header|set_footer|set_watermark):(-?\d+)$") & admin_only)
async def prompt_text_field(client: Client, query):
    action, channel_id = query.matches[0].group(1), int(query.matches[0].group(2))
    LOGGER.info(f"[edit_channel] Handler=prompt_text_field action={action} user={query.from_user.id} channel_id={channel_id}")
    if not await _get_owned_channel(query, channel_id):
        return
    _, prompt = TEXT_FIELDS[action]

    set_pending(
        query.from_user.id,
        "awaiting_text",
        field=action,
        channel_id=channel_id,
        panel_message_id=query.message.id,
    )
    await _safe_edit(
        query.message,
        f"{prompt}\n\nSend <code>-</code> to clear this field.",
        back_to_panel(channel_id),
    )
    LOGGER.info(f"[edit_channel] prompt_text_field: EDITED message {query.message.id}, stored as panel_message_id")


@Client.on_message(filters.private & filters.text & NOT_COMMAND & admin_only)
async def capture_text_input(client: Client, message: Message):
    pending = get_pending(message.from_user.id)
    if not pending:
        LOGGER.debug(f"[edit_channel] capture_text_input: no pending state for user {message.from_user.id}")
        message.continue_propagation()

    action = pending.get("action")
    channel_id = pending.get("channel_id")
    panel_message_id = pending.get("panel_message_id")
    value = None if message.text.strip() == "-" else message.text

    LOGGER.info(
        f"[edit_channel] Handler=capture_text_input action={action} user={message.from_user.id} "
        f"channel_id={channel_id} panel_message_id={panel_message_id}"
    )

    if action in ("awaiting_forward", "awaiting_import_file", "awaiting_import_target"):
        hint = {
            "awaiting_forward": "Please <b>forward a message from your channel</b> (or tap Cancel).",
            "awaiting_import_file": "Please send the exported <code>.json</code> file (or tap Cancel).",
            "awaiting_import_target": "Please pick a channel from the list above.",
        }[action]
        await message.reply_text(hint)
        return

    if action == "awaiting_text":
        field = pending.get("field")
        if field not in TEXT_FIELDS:
            LOGGER.error(f"[edit_channel] unknown field in pending state: {pending}")
            clear_pending(message.from_user.id)
            return
        field_key, prompt = TEXT_FIELDS[field]

        if field == "set_template" and value is not None:
            error = validate_template(value)
            if error:
                LOGGER.info(f"[edit_channel] template rejected for channel {channel_id}: {error}")
                text = f"⚠️ {_esc(error)}\n\n{prompt}\n\nSend <code>-</code> to clear this field."
                if panel_message_id:
                    await _edit_message(client, message.chat.id, panel_message_id, text,
                                        reply_markup=back_to_panel(channel_id))
                else:
                    await message.reply_text(text, reply_markup=back_to_panel(channel_id))
                await _cleanup_user_message(message)
                return  # keep the pending state so the admin can resend

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
        await _cleanup_user_message(message)

    elif action == "awaiting_replace_from":
        set_pending(
            message.from_user.id,
            "awaiting_replace_to",
            channel_id=channel_id,
            word_from=message.text,
            panel_message_id=panel_message_id,
        )
        text = f"Replace <b>{_esc(message.text)}</b> with:"
        if panel_message_id:
            await _edit_message(client, message.chat.id, panel_message_id, text,
                                reply_markup=back_to_panel(channel_id))
        else:
            LOGGER.warning(
                "[edit_channel] capture_text_input(awaiting_replace_from): no panel_message_id -- "
                "falling back to sending a new message"
            )
            await message.reply_text(text, reply_markup=back_to_panel(channel_id))
        await _cleanup_user_message(message)

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
        await _cleanup_user_message(message)

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
        await _cleanup_user_message(message)

    else:
        LOGGER.warning(f"[edit_channel] capture_text_input: unhandled pending action {action!r}")


# ------------------------------------------------------------ replace rules
async def _show_replace_menu(message, channel_id: int):
    channel = await get_channel(channel_id)
    pairs = channel["settings"].get("replace_words", []) if channel else []

    # callback_data carries the INDEX, never the word (64-byte limit).
    rows = [
        [InlineKeyboardButton(
            f"❌ {_short(p['from'], 18)} → {_short(p['to'], 18)}",
            callback_data=f"del_replace:{channel_id}:{i}",
        )]
        for i, p in enumerate(pairs)
    ]
    rows.append([InlineKeyboardButton("➕ Add Replacement", callback_data=f"add_replace:{channel_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"channel_panel:{channel_id}")])

    text = "🔁 <b>Word Replace Rules</b>\n\nTap a rule to delete it." if pairs else \
           "🔁 <b>Word Replace Rules</b>\n\nNo rules yet."
    await _safe_edit(message, text, InlineKeyboardMarkup(rows))
    LOGGER.info(f"[edit_channel] replace menu: EDITED message {message.id}")


@Client.on_callback_query(filters.regex(r"^replace_menu:(-?\d+)$") & admin_only)
async def replace_menu(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=replace_menu user={query.from_user.id} channel_id={channel_id}")
    if not await _get_owned_channel(query, channel_id):
        return
    await _show_replace_menu(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^add_replace:(-?\d+)$") & admin_only)
async def add_replace_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=add_replace_prompt user={query.from_user.id} channel_id={channel_id}")
    if not await _get_owned_channel(query, channel_id):
        return
    set_pending(
        query.from_user.id,
        "awaiting_replace_from",
        channel_id=channel_id,
        panel_message_id=query.message.id,
    )
    await _safe_edit(
        query.message,
        "🔁 Send the word/phrase to find (in your own captions):",
        back_to_panel(channel_id),
    )
    LOGGER.info(f"[edit_channel] add_replace_prompt: EDITED message {query.message.id}, stored as panel_message_id")


@Client.on_callback_query(filters.regex(r"^del_replace:(-?\d+):(\d+)$") & admin_only)
async def del_replace(client: Client, query):
    channel_id, index = int(query.matches[0].group(1)), int(query.matches[0].group(2))
    LOGGER.info(f"[edit_channel] Handler=del_replace user={query.from_user.id} channel_id={channel_id} index={index}")
    channel = await _get_owned_channel(query, channel_id)
    if not channel:
        return
    pairs = channel["settings"].get("replace_words", [])
    if 0 <= index < len(pairs):
        await remove_replace_word(channel_id, pairs[index]["from"])
        await query.answer("Removed.")
    else:
        await query.answer("That rule no longer exists.", show_alert=True)
    await _show_replace_menu(query.message, channel_id)


# ------------------------------------------------------------ remove words
async def _show_remove_menu(message, channel_id: int):
    channel = await get_channel(channel_id)
    words = channel["settings"].get("remove_words", []) if channel else []

    rows = [
        [InlineKeyboardButton(f"❌ {_short(w, 40)}", callback_data=f"del_remove:{channel_id}:{i}")]
        for i, w in enumerate(words)
    ]
    rows.append([InlineKeyboardButton("➕ Add Word/Phrase", callback_data=f"add_remove:{channel_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"channel_panel:{channel_id}")])

    text = "🗑 <b>Word Removal List</b>\n\nTap an entry to delete it." if words else \
           "🗑 <b>Word Removal List</b>\n\nNo entries yet."
    await _safe_edit(message, text, InlineKeyboardMarkup(rows))
    LOGGER.info(f"[edit_channel] remove menu: EDITED message {message.id}")


@Client.on_callback_query(filters.regex(r"^remove_menu:(-?\d+)$") & admin_only)
async def remove_menu(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=remove_menu user={query.from_user.id} channel_id={channel_id}")
    if not await _get_owned_channel(query, channel_id):
        return
    await _show_remove_menu(query.message, channel_id)


@Client.on_callback_query(filters.regex(r"^add_remove:(-?\d+)$") & admin_only)
async def add_remove_prompt(client: Client, query):
    channel_id = int(query.matches[0].group(1))
    LOGGER.info(f"[edit_channel] Handler=add_remove_prompt user={query.from_user.id} channel_id={channel_id}")
    if not await _get_owned_channel(query, channel_id):
        r