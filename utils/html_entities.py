# utils/html_entities.py
"""
utils/html_entities.py
------------------------
A small, self-contained HTML -> (plain_text, entities) converter.

WHY THIS EXISTS
----------------
Every caption in this bot is built as an HTML string by
utils/caption_builder.py and previously handed to Pyrogram's send/edit
methods relying on the client's *default* parse_mode. That is fine for
long-standing tags (<b>, <i>, <code>, ...), but <blockquote> and especially
<blockquote expandable> are a comparatively new Telegram feature (Bot API
7.5, ~April 2024), and whether a given Pyrogram build's *own* HTML parser
recognizes them is not guaranteed just because the tag looks syntactically
correct -- if the installed parser has no code path for "blockquote", the
literal tag text passes straight through unconverted, which is exactly the
"raw text" symptom being investigated.

This module removes that dependency entirely: it parses the bot's own HTML
itself, using Python's standard library `html.parser.HTMLParser`, and
returns plain text plus an explicit list of `pyrogram.types.MessageEntity`
objects. Callers pass `entities=`/`caption_entities=` directly instead of
`parse_mode=`, so Pyrogram never needs to parse the tags at all -- the
correctness of blockquote rendering now depends only on whether your
installed Pyrogram's *protocol layer* (MessageEntityType.BLOCKQUOTE) can
serialize the entity, not on its HTML tag parser.

SUPPORTED TAGS (matches README's documented "HTML formatting" section):
    <b> <strong>          -> bold
    <i> <em>               -> italic
    <u>                     -> underline
    <s> <strike> <del>       -> strikethrough
    <code>                    -> code
    <pre>                      -> pre
    <a href="...">              -> text link
    <blockquote>                  -> blockquote
    <blockquote expandable>        -> expandable/collapsible blockquote

VERIFY BEFORE RELYING ON THIS IN PRODUCTION:
    The exact keyword Pyrogram uses on `MessageEntity` for the "expandable"
    flag on a blockquote is NOT something I can confirm without your actual
    installed package (no network access in this environment). It is set
    below via the single constant `BLOCKQUOTE_EXPANDABLE_KWARG`. Run:

        import inspect
        from pyrogram.types import MessageEntity
        print(inspect.signature(MessageEntity.__init__))

    and change the constant below if your installed version reports a
    different name (e.g. "expandable" instead of "collapsed").
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from pyrogram.types import MessageEntity
from pyrogram.enums import MessageEntityType

# --- See "VERIFY BEFORE RELYING ON THIS IN PRODUCTION" above ---
BLOCKQUOTE_EXPANDABLE_KWARG = "collapsed"

# Detect at import time whether this Pyrogram build even has the entity
# type at all, so failures are loud and specific instead of a confusing
# traceback deep inside a send call.
BLOCKQUOTE_SUPPORTED = hasattr(MessageEntityType, "BLOCKQUOTE")

_TAG_TO_ENTITY = {
    "b": MessageEntityType.BOLD,
    "strong": MessageEntityType.BOLD,
    "i": MessageEntityType.ITALIC,
    "em": MessageEntityType.ITALIC,
    "u": MessageEntityType.UNDERLINE,
    "s": MessageEntityType.STRIKETHROUGH,
    "strike": MessageEntityType.STRIKETHROUGH,
    "del": MessageEntityType.STRIKETHROUGH,
    "code": MessageEntityType.CODE,
    "pre": MessageEntityType.PRE,
    # "a" and "blockquote" are handled specially below (need extra data).
}


def _utf16_len(text: str) -> int:
    """
    Telegram entity offsets/lengths are counted in UTF-16 code units, not
    Python string indices. A character outside the Basic Multilingual Plane
    (many emoji) is 1 Python codepoint but 2 UTF-16 code units, so this
    conversion is required for correct offsets whenever such characters can
    appear (channel titles, user-entered header/footer/watermark text, etc).
    """
    return len(text.encode("utf-16-le")) // 2


@dataclass
class _OpenTag:
    name: str
    start_offset: int
    href: str | None = None
    expandable: bool = False


class _EntityHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.plain_parts: list[str] = []
        self.entities: list[MessageEntity] = []
        self._offset = 0  # running UTF-16 offset into the plain text so far
        self._stack: list[_OpenTag] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag == "a":
            self._stack.append(_OpenTag(tag, self._offset, href=attrs_dict.get("href")))
        elif tag == "blockquote":
            # HTMLParser reports a valueless attribute like `expandable` as
            # (name, None) -- its mere presence is what matters, not a value.
            is_expandable = "expandable" in attrs_dict
            self._stack.append(_OpenTag(tag, self._offset, expandable=is_expandable))
        elif tag in _TAG_TO_ENTITY:
            self._stack.append(_OpenTag(tag, self._offset))
        # Unknown tags are silently ignored (no entity), matching graceful
        # degradation rather than raising on an unexpected tag.

    def handle_endtag(self, tag):
        tag = tag.lower()
        # Pop the most recent matching open tag (supports simple nesting).
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].name == tag:
                open_tag = self._stack.pop(i)
                length = self._offset - open_tag.start_offset
                if length <= 0:
                    return
                if tag == "a":
                    if open_tag.href:
                        self.entities.append(
                            MessageEntity(
                                type=MessageEntityType.TEXT_LINK,
                                offset=open_tag.start_offset,
                                length=length,
                                url=open_tag.href,
                            )
                        )
                elif tag == "blockquote":
                    if not BLOCKQUOTE_SUPPORTED:
                        raise RuntimeError(
                            "This Pyrogram installation has no "
                            "MessageEntityType.BLOCKQUOTE -- blockquote "
                            "entities are not supported at all by this "
                            "build. Upgrade Pyrogram to a version/fork "
                            "that implements Bot API 7.5's blockquote "
                            "entity; no client-side workaround is possible."
                        )
                    kwargs = {}
                    if open_tag.expandable:
                        kwargs[BLOCKQUOTE_EXPANDABLE_KWARG] = True
                    self.entities.append(
                        MessageEntity(
                            type=MessageEntityType.BLOCKQUOTE,
                            offset=open_tag.start_offset,
                            length=length,
                            **kwargs,
                        )
                    )
                else:
                    self.entities.append(
                        MessageEntity(
                            type=_TAG_TO_ENTITY[tag],
                            offset=open_tag.start_offset,
                            length=length,
                        )
                    )
                return

    def handle_data(self, data):
        self.plain_parts.append(data)
        self._offset += _utf16_len(data)


def parse_html(html_text: str) -> tuple[str, list[MessageEntity]]:
    """
    Convert an HTML string built by caption_builder.py into
    (plain_text, entities) using this module's own parser, independent of
    whatever the ambient Pyrogram build's parse_mode HTML support does or
    does not implement for <blockquote>.
    """
    parser = _EntityHTMLParser()
    parser.feed(html_text or "")
    parser.close()
    plain_text = "".join(parser.plain_parts)
    # Entities must be sorted by offset for Telegram to render them reliably.
    entities = sorted(parser.entities, key=lambda e: e.offset)
    return plain_text, entities