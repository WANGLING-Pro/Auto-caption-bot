"""
utils/caption_builder.py
-------------------------
Turns a channel's saved settings + an incoming Telegram message into the
final HTML caption/text that gets sent back to Telegram.

Design notes
------------
- Content-agnostic: only performs string operations the channel owner
  explicitly configured (template variables, header/footer/watermark, word
  replace, word remove) on messages in channels the owner added the bot to.

Review fixes (vs. previous version)
-----------------------------------
* The original caption is now taken as HTML (`message.caption.html`) so its
  links/bold/etc. survive. Before, `message.caption` (plain text) was used,
  which silently stripped every hyperlink and format from every caption the
  bot rewrote. Plain-text fallback is HTML-escaped.
* All variables inserted into the HTML are escaped ({filename}, channel
  name...). Before, a caption/filename containing `<` or `&` could swallow
  text or break parsing.
* Word removal/replacement only touches text between tags (never tag names or
  attributes); the phrase is matched in its HTML-escaped form.
* Replacement text is inserted literally (re.sub with a plain string treated
  backslashes as escapes and could raise `re.error`).
* Whitespace collapsing only happens when a removal rule actually matched,
  instead of reformatting every caption.
* A template with a stray `{` / `}` (ValueError) no longer crashes the
  pipeline; `validate_template()` lets the UI reject it at save time.
* The watermark is not wrapped in a second <blockquote> if the owner already
  wrote one (nested blockquotes are invalid).
"""

import html as _html
import re
from datetime import datetime, timezone

from utils.logger import LOGGER

_TAG_SPLIT = re.compile(r"(<[^>]*>)")

SAMPLE_VARIABLES = {
    "filename": "sample_file.mp4",
    "filesize": "700.00 MB",
    "duration": "23:45",
    "caption": "sample caption",
    "default_caption": "sample caption",
    "channel_name": "Sample Channel",
    "channel_username": "@sample",
    "message_id": "123456",
    "date": "2026-01-01",
    "time": "12:00:00",
}


def _esc(value) -> str:
    return _html.escape(str(value or ""), quote=False)


def format_filesize(num_bytes: int | None) -> str:
    if not num_bytes:
        return "N/A"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "N/A"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def extract_media_info(message) -> dict:
    """Pull filename/filesize/duration out of whatever media type is present."""
    filename = None
    filesize = None
    duration = None

    media = (
        message.document
        or message.video
        or message.audio
        or message.voice
        or message.video_note
        or message.animation
    )
    if media:
        filename = getattr(media, "file_name", None)
        filesize = getattr(media, "file_size", None)
        duration = getattr(media, "duration", None)
    elif message.photo:
        filesize = getattr(message.photo, "file_size", None)

    return {
        "filename": filename or "Unknown",
        "filesize": format_filesize(filesize),
        "duration": format_duration(duration),
    }


def _map_text_segments(html_text: str, fn) -> str:
    """Apply `fn` only to the text between tags (even indexes of the split)."""
    parts = _TAG_SPLIT.split(html_text)
    for i in range(0, len(parts), 2):
        parts[i] = fn(parts[i])
    return "".join(parts)


def apply_word_removals(html_text: str, remove_words: list[str]) -> str:
    """Delete each configured phrase (case-insensitive) from the text parts."""
    if not html_text:
        return html_text
    changed = False
    for phrase in remove_words or []:
        if not phrase:
            continue
        pattern = re.compile(re.escape(_esc(phrase)), re.IGNORECASE)

        def _remove(seg, pattern=pattern):
            nonlocal changed
            new, n = pattern.subn("", seg)
            if n:
                changed = True
            return new

        html_text = _map_text_segments(html_text, _remove)

    if changed:
        # tidy leftovers created by removals
        html_text = _map_text_segments(html_text, lambda s: re.sub(r"[ \t]{2,}", " ", s))
        html_text = re.sub(r"\n{3,}", "\n\n", html_text)
    return html_text.strip()


def apply_word_replacements(html_text: str, replace_words: list[dict]) -> str:
    """Replace each configured `from` -> `to` pair (case-insensitive) in text parts."""
    if not html_text:
        return html_text
    for pair in replace_words or []:
        word_from, word_to = pair.get("from"), pair.get("to", "")
        if not word_from:
            continue
        pattern = re.compile(re.escape(_esc(word_from)), re.IGNORECASE)
        html_text = _map_text_segments(
            html_text, lambda seg, p=pattern, t=word_to: p.sub(lambda _m: t, seg)
        )
    return html_text


def _original_html(message) -> str:
    """Original caption/text as HTML (keeps links/formatting), escaped fallback."""
    obj = message.caption or message.text
    if not obj:
        return ""
    try:
        as_html = getattr(obj, "html", None)
        if isinstance(as_html, str):
            return as_html
    except Exception as e:  # pragma: no cover
        LOGGER.warning(f"[caption_builder] .html failed, using escaped plain text: {e}")
    return _esc(obj)


def validate_template(template: str) -> str | None:
    """Return an error string if `template` cannot be formatted, else None."""
    try:
        template.format(**SAMPLE_VARIABLES)
        return None
    except KeyError as e:
        return f"Unknown variable {{{e.args[0]}}}. Allowed: " + " ".join(
            "{" + k + "}" for k in SAMPLE_VARIABLES
        )
    except (IndexError, ValueError, AttributeError) as e:
        return f"Template error: {e}. Use {{name}} only for variables; literal braces are not allowed."


def build_caption(message, channel: dict) -> str:
    """
    Build the final HTML caption for a message, using the channel's saved
    settings. `message` is a Pyrogram Message (or a duck-typed stand-in).
    """
    settings = channel.get("settings", {})

    original_html = _original_html(message)
    cleaned = apply_word_removals(original_html, settings.get("remove_words", []))
    cleaned = apply_word_replacements(cleaned, settings.get("replace_words", []))

    media_info = extract_media_info(message)
    now = datetime.now(timezone.utc)

    variables = {
        "filename": _esc(media_info["filename"]),
        "filesize": media_info["filesize"],
        "duration": media_info["duration"],
        "caption": cleaned,
        "default_caption": cleaned,
        "channel_name": _esc(channel.get("title", "")),
        "channel_username": _esc(f"@{channel['username']}") if channel.get("username") else "",
        "message_id": str(message.id),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }

    template = settings.get("caption_template")
    if template:
        try:
            body = template.format(**variables)
        except (KeyError, IndexError, ValueError, AttributeError) as e:
            LOGGER.warning(
                f"[caption_builder] template for channel {channel.get('_id')} is invalid "
                f"({type(e).__name__}: {e}); falling back to the plain caption"
            )
            body = cleaned
    else:
        body = cleaned

    parts = []
    if settings.get("header"):
        parts.append(settings["header"])
    parts.append(body)
    if settings.get("footer"):
        parts.append(settings["footer"])
    watermark = settings.get("watermark")
    if watermark:
        if "<blockquote" in watermark.lower():
            parts.append(watermark)  # owner already formatted it; avoid nesting
        else:
            parts.append(f"<blockquote>{watermark}</blockquote>")

    final_text = "\n\n".join(p for p in parts if p and p.strip())
    return final_text.strip()
