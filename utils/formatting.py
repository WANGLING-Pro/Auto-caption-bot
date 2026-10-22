# utils/formatting.py
"""
utils/formatting.py
--------------------
ONE place that decides how an HTML string is sent to Telegram, so
auto_caption.py and the Preview button behave identically.

Strategy
--------
1. At first use, ask the installed Pyrogram's OWN HTML parser whether it
   understands <blockquote> and <blockquote expandable> (detect_capabilities).
   This is a real runtime probe, not a guess about version numbers.
2. If the native parser handles everything -> send with parse_mode=HTML.
3. Otherwise -> convert with utils/html_entities.parse_html() and send explicit
   entities (degrading expandable -> normal blockquote -> plain text, with a
   logged warning instead of an exception).

Run /diag in the bot to see the probe result.
"""

import inspect

from pyrogram.enums import ParseMode

from utils.html_entities import parse_html, entity_capabilities
from utils.logger import LOGGER

_state = {
    "checked": False,
    "native_blockquote": None,   # True / False / None (probe failed)
    "native_expandable": None,
    "error": None,
}


async def detect_capabilities(client=None) -> dict:
    """Probe the installed library once; cached afterwards."""
    if _state["checked"]:
        return dict(_state)
    _state["checked"] = True
    try:
        from pyrogram.parser import Parser

        parser = Parser(client)
        r1 = await parser.parse("<blockquote>a</blockquote>", ParseMode.HTML)
        r2 = await parser.parse("<blockquote expandable>a</blockquote>", ParseMode.HTML)
        e1 = r1.get("entities") or []
        e2 = r2.get("entities") or []
        _state["native_blockquote"] = any("blockquote" in type(e).__name__.lower() for e in e1)
        _state["native_expandable"] = any(
            "blockquote" in type(e).__name__.lower() and bool(getattr(e, "collapsed", False))
            for e in e2
        )
    except Exception as e:
        _state["error"] = f"{type(e).__name__}: {e}"
        LOGGER.warning(f"[formatting] capability probe failed ({_state['error']}); using native HTML mode")
    LOGGER.info(
        f"[formatting] probe: native_blockquote={_state['native_blockquote']} "
        f"native_expandable={_state['native_expandable']} "
        f"entity_caps={entity_capabilities()} error={_state['error']}"
    )
    return dict(_state)


def _should_use_entities(html_text: str) -> bool:
    if _state["native_blockquote"] is False:
        return True
    if _state["native_expandable"] is False and "expandable" in (html_text or ""):
        return True
    return False


def capability_warning() -> str:
    """Human-readable warning for the Preview screen ('' when everything works)."""
    caps = entity_capabilities()
    nb, ne = _state["native_blockquote"], _state["native_expandable"]
    if nb is False and not caps["blockquote"]:
        return ("⚠️ Installed Telegram library cannot render blockquotes at all. "
                "Upgrade it (see requirements.txt).")
    if ne is False and not caps["expandable_via_entities"]:
        return ("⚠️ Installed Telegram library cannot render <b>expandable</b> blockquotes; "
                "they are sent as normal blockquotes. Upgrade it (see requirements.txt).")
    return ""


def _accepts(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


async def edit_message_html(client, chat_id, message_id, html_text: str, *,
                            is_caption: bool, reply_markup=None):
    """Edit a message's text/caption from an HTML string. Raises Pyrogram errors as usual."""
    await detect_capabilities(client)
    extra = {"reply_markup": reply_markup} if reply_markup is not None else {}

    use_entities = _should_use_entities(html_text)
    plain, entities = parse_html(html_text) if use_entities else (None, None)

    if is_caption:
        fn = client.edit_message_caption
        if use_entities and _accepts(fn, "caption_entities"):
            LOGGER.debug(f"[formatting] caption {message_id}: sending via explicit entities ({len(entities)})")
            return await fn(chat_id, message_id, plain, caption_entities=entities, **extra)
        if use_entities:
            LOGGER.warning("[formatting] edit_message_caption has no caption_entities here; falling back to HTML parse_mode")
        return await fn(chat_id, message_id, html_text, parse_mode=ParseMode.HTML, **extra)

    fn = client.edit_message_text
    if use_entities:
        LOGGER.debug(f"[formatting] text {message_id}: sending via explicit entities ({len(entities)})")
        return await fn(chat_id, message_id, plain, entities=entities, **extra)
    return await fn(chat_id, message_id, html_text, parse_mode=ParseMode.HTML, **extra)
