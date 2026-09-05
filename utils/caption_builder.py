"""
utils/caption_builder.py
-------------------------
Turns a channel's saved settings + an incoming Telegram message into the
final HTML caption/text that gets sent back to Telegram.

Design notes
------------
- This module is intentionally content-agnostic: it does not know or care
  what the media "is about". It only performs string operations the channel
  owner explicitly configured (template variables, header/footer/watermark,
  word replace, word remove) on messages posted in a channel where the bot
  has been added as an admin by that channel's own owner.
- Word replace / remove are for the owner's *own* editorial control over
  their *own* captions (typo fixes, consistent terminology, removing
  outdated promo text, adding branding) -- not for stripping attribution
  from third-party content. Nothing here inspects or targets source/credit
  lines specifically; it only executes literal, owner-defined replacements.
"""

import re
from datetime import datetime, timezone


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
        filesize = message.photo.file_size

    return {
        "filename": filename or "Unknown",
        "filesize": format_filesize(filesize),
        "duration": format_duration(duration),
    }


def apply_word_removals(text: str, remove_words: list[str]) -> str:
    """Delete each configured phrase (case-insensitive, whole phrase match)."""
    if not text:
        return text
    for phrase in remove_words:
        if not phrase:
            continue
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        text = pattern.sub("", text)
    # Collapse leftover blank lines/extra spaces created by removals
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def apply_word_replacements(text: str, replace_words: list[dict]) -> str:
    """Replace each configured `from` -> `to` pair (case-insensitive)."""
    if not text:
        return text
    for pair in replace_words:
        word_from, word_to = pair.get("from"), pair.get("to", "")
        if not word_from:
            continue
        pattern = re.compile(re.escape(word_from), re.IGNORECASE)
        text = pattern.sub(word_to, text)
    return text


def build_caption(message, channel: dict) -> str:
    """
    Build the final HTML caption for a message, using the channel's saved
    settings. `message` is a Pyrogram Message object; `channel` is the
    MongoDB channel document.
    """
    settings = channel.get("settings", {})

    original_caption = message.caption or message.text or ""
    # Clean the original caption first (owner's own edit rules)
    cleaned_caption = apply_word_removals(original_caption, settings.get("remove_words", []))
    cleaned_caption = apply_word_replacements(cleaned_caption, settings.get("replace_words", []))

    media_info = extract_media_info(message)
    now = datetime.now(timezone.utc)

    variables = {
        "filename": media_info["filename"],
        "filesize": media_info["filesize"],
        "duration": media_info["duration"],
        "caption": cleaned_caption,
        "default_caption": cleaned_caption,
        "channel_name": channel.get("title", ""),
        "channel_username": f"@{channel['username']}" if channel.get("username") else "",
        "message_id": str(message.id),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }

    template = settings.get("caption_template")
    if template:
        try:
            body = template.format(**variables)
        except (KeyError, IndexError):
            # Unknown variable in the template -- fall back safely rather
            # than crashing the whole pipeline on one bad template.
            body = cleaned_caption
    else:
        body = cleaned_caption

    parts = []
    if settings.get("header"):
        parts.append(settings["header"])
    parts.append(body)
    if settings.get("footer"):
        parts.append(settings["footer"])
    if settings.get("watermark"):
        parts.append(f"<blockquote>{settings['watermark']}</blockquote>")

    final_text = "\n\n".join(p for p in parts if p and p.strip())
    return final_text.strip()
