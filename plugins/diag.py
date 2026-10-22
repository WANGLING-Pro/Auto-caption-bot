"""
plugins/diag.py
----------------
NEW admin-only /diag command: reports what is actually running on Render, so
library/version problems stop being guesses.

Shows: Python version, installed Pyrogram version, whether the library's own
HTML parser understands <blockquote> / <blockquote expandable>, what the
entity fallback can express, and your own pending-state (to debug the
"panel not updating" flow).
"""

import platform
import sys

import pyrogram
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from utils.filters import admin_only
from utils.formatting import detect_capabilities, capability_warning
from utils.html_entities import entity_capabilities
from utils.state import get_pending
from utils.logger import LOGGER


@Client.on_message(filters.command("diag") & filters.private & admin_only, group=-1)
async def diag_handler(client: Client, message: Message):
    LOGGER.info(f"[diag] requested by {message.from_user.id}")
    state = await detect_capabilities(client)
    caps = entity_capabilities()
    pending = get_pending(message.from_user.id)

    lines = [
        "🩺 <b>Diagnostics</b>",
        f"Python: <code>{sys.version.split()[0]}</code> ({platform.system()})",
        f"Pyrogram: <code>{getattr(pyrogram, '__version__', '?')}</code>",
        "",
        "<b>Native HTML parser</b>",
        f"blockquote: <code>{state['native_blockquote']}</code>",
        f"blockquote expandable: <code>{state['native_expandable']}</code>",
        f"probe error: <code>{state['error']}</code>",
        "",
        "<b>Entity fallback can express</b>",
        f"blockquote: <code>{caps['blockquote']}</code>",
        f"expandable: <code>{caps['expandable_via_entities']}</code> "
        f"(kwarg: <code>{caps['expandable_kwarg']}</code>)",
        "",
        f"Your pending state: <code>{pending}</code>",
    ]
    warning = capability_warning()
    if warning:
        lines += ["", warning]
    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
