# utils/html_entities.py
"""
utils/html_entities.py
------------------------
Small, self-contained HTML -> (plain_text, entities) converter.

Why it exists
-------------
Used for two things:
  1. Getting the *plain text* of a caption (length limits, debugging).
  2. Building explicit MessageEntity objects when the installed Pyrogram
     build's own HTML parser does not understand <blockquote>
     (see utils/formatting.py, which decides which path to use).

What changed vs. the previous version (review fixes)
----------------------------------------------------
* NEVER raises on an unsupported library feature. The old version raised
  RuntimeError (no BLOCKQUOTE type) or TypeError (MessageEntity(...,
  collapsed=True) on a build whose MessageEntity has no such parameter),
  which killed auto-captioning and the Preview button outright.
  Now it degrades: expandable -> normal blockquote -> plain text, and logs
  one warning.
* The "expandable" flag is detected from the installed library instead of
  being a hard-coded guess (EXPANDABLE_BLOCKQUOTE enum member, or a
  `collapsed` / `expandable` MessageEntity parameter).
* Entities are sorted by (offset, -length) so an outer entity always comes
  before the inner one that starts at the same offset.
* Unclosed tags are closed at end of text instead of being dropped.
* Nested <blockquote> is flattened (Telegram does not allow it).
* Extra tags: <br>, <tg-spoiler>, <span class="tg-spoiler">,
  <pre language="...">.
"""

import html as _html
import inspect
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from pyrogram.types import MessageEntity
from pyrogram.enums import MessageEntityType

from utils.logger import LOGGER


def _enum(name: str):
    return getattr(MessageEntityType, name, None)


def _entity_params() -> set:
    try:
        return set(inspect.signature(MessageEntity.__init__).parameters)
    except (TypeError, ValueError):
        return set()


_PARAMS = _entity_params()
BLOCKQUOTE = _enum("BLOCKQUOTE")
EXPANDABLE_BLOCKQUOTE = _enum("EXPANDABLE_BLOCKQUOTE")
SPOILER = _enum("SPOILER")
_EXPANDABLE_KWARG = next((k for k in ("collapsed", "expandable") if k in _PARAMS), None)


def entity_capabilities() -> dict:
    """What the installed Pyrogram build can express through MessageEntity."""
    return {
        "blockquote": BLOCKQUOTE is not None or EXPANDABLE_BLOCKQUOTE is not None,
        "expandable_via_entities": EXPANDABLE_BLOCKQUOTE is not None
        or (BLOCKQUOTE is not None and _EXPANDABLE_KWARG is not None),
        "expandable_kwarg": _EXPANDABLE_KWARG,
        "has_EXPANDABLE_BLOCKQUOTE_enum": EXPANDABLE_BLOCKQUOTE is not None,
        "has_SPOILER_enum": SPOILER is not None,
    }


_TAG_TO_ENTITY = {
    name: etype
    for name, etype in {
        "b": _enum("BOLD"),
        "strong": _enum("BOLD"),
        "i": _enum("ITALIC"),
        "em": _enum("ITALIC"),
        "u": _enum("UNDERLINE"),
        "s": _enum("STRIKETHROUGH"),
        "strike": _enum("STRIKETHROUGH"),
        "del": _enum("STRIKETHROUGH"),
        "code": _enum("CODE"),
        "pre": _enum("PRE"),
        "tg-spoiler": SPOILER,
    }.items()
    if etype is not None
}

_warned: set = set()


def _warn_once(key: str, message: str):
    if key not in _warned:
        _warned.add(key)
        LOGGER.warning(f"[html_entities] {message}")


def _utf16_len(text: str) -> int:
    """Telegram entity offsets/lengths are UTF-16 code units, not Python chars."""
    return len(text.encode("utf-16-le")) // 2


@dataclass
class _OpenTag:
    name: str
    start_offset: int
    href: str | None = None
    language: str | None = None
    expandable: bool = False
    noop: bool = False  # e.g. a nested blockquote: parsed but emits nothing


class _EntityHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.plain_parts: list[str] = []
        self.entities: list[MessageEntity] = []
        self._offset = 0
        self._stack: list[_OpenTag] = []

    # ---- helpers -------------------------------------------------------
    def _add(self, **kwargs):
        try:
            self.entities.append(MessageEntity(**kwargs))
        except TypeError as e:  # unsupported kwarg on this build
            _warn_once("entity_typeerror", f"MessageEntity rejected {kwargs.keys()}: {e}")

    def _emit(self, tag: _OpenTag):
        length = self._offset - tag.start_offset
        if length <= 0 or tag.noop:
            return
        base = {"offset": tag.start_offset, "length": length}

        if tag.name == "a":
            if tag.href:
                self._add(type=_enum("TEXT_LINK"), url=tag.href, **base)
        elif tag.name == "blockquote":
            self._emit_blockquote(tag, base)
        elif tag.name == "pre":
            kwargs = dict(type=_TAG_TO_ENTITY.get("pre"), **base)
            if tag.language and "language" in _PARAMS:
                kwargs["language"] = tag.language
            if kwargs["type"] is not None:
                self._add(**kwargs)
        else:
            etype = _TAG_TO_ENTITY.get(tag.name)
            if etype is not None:
                self._add(type=etype, **base)

    def _emit_blockquote(self, tag: _OpenTag, base: dict):
        if BLOCKQUOTE is None and EXPANDABLE_BLOCKQUOTE is None:
            _warn_once(
                "no_blockquote",
                "Installed Pyrogram has no blockquote entity type at all -> "
                "blockquote text is sent as plain text. Upgrade the library "
                "(see requirements.txt).",
            )
            return

        if tag.expandable:
            if EXPANDABLE_BLOCKQUOTE is not None:
                self._add(type=EXPANDABLE_BLOCKQUOTE, **base)
                return
            if BLOCKQUOTE is not None and _EXPANDABLE_KWARG:
                self._add(type=BLOCKQUOTE, **{_EXPANDABLE_KWARG: True}, **base)
                return
            _warn_once(
                "no_expandable",
                "Installed Pyrogram cannot express an EXPANDABLE blockquote "
                "-> sending a normal blockquote instead. Upgrade the library "
                "(see requirements.txt).",
            )

        if BLOCKQUOTE is not None:
            self._add(type=BLOCKQUOTE, **base)
        elif EXPANDABLE_BLOCKQUOTE is not None:
            self._add(type=EXPANDABLE_BLOCKQUOTE, **base)

    # ---- HTMLParser callbacks -----------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)

        if tag == "br":
            self.handle_data("\n")
            return
        if tag == "span":
            if "tg-spoiler" in (a.get("class") or ""):
                tag = "tg-spoiler"
            else:
                return

        if tag == "a":
            self._stack.append(_OpenTag("a", self._offset, href=a.get("href")))
        elif tag == "blockquote":
            nested = any(t.name == "blockquote" for t in self._stack)
            # `expandable` is a valueless attribute -> (name, None); presence matters.
            self._stack.append(
                _OpenTag("blockquote", self._offset, expandable=("expandable" in a), noop=nested)
            )
        elif tag == "pre":
            self._stack.append(_OpenTag("pre", self._offset, language=a.get("language")))
        elif tag in _TAG_TO_ENTITY:
            self._stack.append(_OpenTag(tag, self._offset))
        # unknown tags: ignored (their text is kept)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "span":
            tag = "tg-spoiler"
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].name == tag:
                self._emit(self._stack.pop(i))
                return

    def handle_data(self, data):
        self.plain_parts.append(data)
        self._offset += _utf16_len(data)

    def finish(self):
        # close anything left open, innermost first
        while self._stack:
            self._emit(self._stack.pop())


_TAG_RE = re.compile(r"<[^>]*>")


def parse_html(html_text: str) -> tuple[str, list[MessageEntity]]:
    """
    Convert the bot's HTML into (plain_text, entities). Never raises.
    """
    html_text = html_text or ""
    try:
        parser = _EntityHTMLParser()
        parser.feed(html_text)
        parser.close()
        parser.finish()
        plain_text = "".join(parser.plain_parts)
        entities = sorted(parser.entities, key=lambda e: (e.offset, -e.length))
        return plain_text, entities
    except Exception as e:  # pragma: no cover - last-resort safety net
        LOGGER.exception(f"[html_entities] parse_html failed, stripping tags: {e}")
        return _html.unescape(_TAG_RE.sub("", html_text)), []
