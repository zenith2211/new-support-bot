"""
app/msg.py — message builder.

Telegram entity offsets are counted in UTF-16 code units, not python chars,
so every piece of text is measured with u16(). Building messages through this
class (instead of HTML/Markdown) means product names, coupon codes and user
supplied text never need escaping — they cannot break the markup.

    m = Msg()
    m.header("products", "Products")
    m.emoji("spark").text(" Open a category to see price, stock and delivery.")
    text, entities = m.build()
"""

from . import emoji as emo


def u16(s: str) -> int:
    """Length of s in UTF-16 code units (what Telegram counts)."""
    return len(s.encode("utf-16-le")) // 2


class Msg:
    def __init__(self):
        self._parts: list = []   # (kind, content, extra)
        self._buf = ""

    # ── plain text ────────────────────────────────────────────
    def _flush(self):
        if self._buf:
            self._parts.append(("text", self._buf, None))
            self._buf = ""

    def text(self, s) -> "Msg":
        self._buf += str(s)
        return self

    def nl(self, n: int = 1) -> "Msg":
        self._buf += "\n" * n
        return self

    def space(self, n: int = 1) -> "Msg":
        self._buf += " " * n
        return self

    # ── styled runs ───────────────────────────────────────────
    def _styled(self, kind: str, s, extra=None) -> "Msg":
        s = str(s)
        if s:
            self._flush()
            self._parts.append((kind, s, extra))
        return self

    def bold(self, s) -> "Msg":
        return self._styled("bold", s)

    def italic(self, s) -> "Msg":
        return self._styled("italic", s)

    def underline(self, s) -> "Msg":
        return self._styled("underline", s)

    def strike(self, s) -> "Msg":
        return self._styled("strikethrough", s)

    def code(self, s) -> "Msg":
        return self._styled("code", s)

    def pre(self, s, language: str = "") -> "Msg":
        return self._styled("pre", s, language or None)

    def spoiler(self, s) -> "Msg":
        return self._styled("spoiler", s)

    def link(self, s, url: str) -> "Msg":
        return self._styled("text_link", s, url)

    def quote(self, s) -> "Msg":
        return self._styled("blockquote", s)

    def emoji(self, name: str) -> "Msg":
        """A named emoji slot — premium custom emoji when an id is configured."""
        char = emo.char(name)
        eid = emo.premium_id(name)
        if eid:
            self._flush()
            self._parts.append(("custom_emoji", char, eid))
        else:
            self._buf += char
        return self

    # ── UI shorthands ─────────────────────────────────────────
    def header(self, emoji_name: str | None, title: str,
               divider: bool = True) -> "Msg":
        """`{emoji} {BOLD TITLE}` + the divider rule used across the UI."""
        if emoji_name:
            self.emoji(emoji_name).space()
        self.bold(title).nl()
        if divider:
            self.text(emo.DIVIDER).nl()
        return self

    def bar_header(self, title: str, trailing_emoji: str | None = None,
                   divider: bool = True) -> "Msg":
        """`▎TITLE 🔥` style header used by the channel posts."""
        self.text(emo.BAR).bold(title)
        if trailing_emoji:
            self.space().emoji(trailing_emoji)
        self.nl()
        if divider:
            self.text(emo.DIVIDER).nl()
        return self

    def kv(self, emoji_name: str | None, label: str, value,
           bold_value: bool = True) -> "Msg":
        """One `emoji Label: value` line (no trailing newline)."""
        if emoji_name:
            self.emoji(emoji_name).space()
        self.bold(f"{label}: ")
        return self.bold(value) if bold_value else self.text(value)

    def kvline(self, emoji_name: str | None, label: str, value,
               bold_value: bool = True) -> "Msg":
        return self.kv(emoji_name, label, value, bold_value).nl()

    def bullet(self, emoji_name: str | None, label: str,
               desc: str = "") -> "Msg":
        """`emoji **Label** — desc` menu line."""
        if emoji_name:
            self.emoji(emoji_name).space()
        self.bold(label)
        if desc:
            self.text(f" — {desc}")
        return self.nl()

    def rule(self) -> "Msg":
        return self.text(emo.DIVIDER).nl()

    # ── output ────────────────────────────────────────────────
    def build(self) -> tuple[str, list]:
        self._flush()
        text = ""
        entities: list = []
        offset = 0

        for kind, content, extra in self._parts:
            length = u16(content)
            if length == 0:
                continue

            if kind == "text":
                pass
            elif kind == "custom_emoji":
                eid = str(extra).strip()
                if eid.isdigit():
                    entities.append({
                        "type": "custom_emoji",
                        "offset": offset,
                        "length": length,
                        "custom_emoji_id": eid,
                    })
            elif kind == "text_link":
                if extra:
                    entities.append({
                        "type": "text_link",
                        "offset": offset,
                        "length": length,
                        "url": str(extra),
                    })
            elif kind == "pre":
                ent = {"type": "pre", "offset": offset, "length": length}
                if extra:
                    ent["language"] = str(extra)
                entities.append(ent)
            else:
                entities.append({
                    "type": kind,
                    "offset": offset,
                    "length": length,
                })

            text += content
            offset += length

        return text, entities


def strip_entities(entities: list, kinds: tuple = ("custom_emoji",)) -> list:
    """Entities minus the given kinds — used as the retry payload when
    Telegram rejects an unknown custom_emoji_id."""
    return [e for e in (entities or []) if e.get("type") not in kinds]
