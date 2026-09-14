"""
app/view.py — a screen, and the buttons on it.

A View bundles everything one message needs: text, entities, an optional
poster image and a keyboard. Handlers build Views; tg.render() puts them on
screen. That split is what lets every screen work identically whether it was
reached by a command (fresh send) or a button (in-place edit).
"""

from dataclasses import dataclass, field

from . import config, emoji as emo
from .msg import Msg

# Button colours. Verified on Telegram Desktop 7.1.4 against a live bot:
# "style" is honoured ("success" renders green, "danger" red, "primary" teal)
# while a "color" field is silently ignored. Unknown reply_markup fields are
# dropped rather than rejected, so this is safe on older clients too — they
# just show the default colour.
SEND_BUTTON_STYLES = config._env_bool("BUTTON_STYLES", True)

# icon_custom_emoji_id is NOT verified — left off by default. With it off, a
# button's emoji comes from its label text, which works everywhere.
SEND_BUTTON_ICONS = config._env_bool("BUTTON_ICONS", False)

# The only values Telegram accepts. Anything else is rejected outright on a
# KeyboardButton ("Invalid button style"), so keep this list closed.
STYLE_PRIMARY = "primary"      # blue on reply keyboards, teal on inline ones
STYLE_SUCCESS = "success"      # green
STYLE_DANGER = "danger"        # red
STYLE_DEFAULT = "default"      # the normal dark button
STYLES = (STYLE_PRIMARY, STYLE_SUCCESS, STYLE_DANGER, STYLE_DEFAULT)


@dataclass
class View:
    text: str = ""
    entities: list = field(default_factory=list)
    keyboard: dict | None = None
    poster: str | None = None

    @classmethod
    def of(cls, m: Msg, keyboard: dict | None = None,
           poster: str | None = None) -> "View":
        text, entities = m.build()
        return cls(text=text, entities=entities,
                   keyboard=keyboard, poster=poster or None)


# ─── INLINE BUTTONS ───────────────────────────────────────────
def btn(text: str, data: str | None = None, url: str | None = None,
        emoji_name: str | None = None, style: str | None = None,
        switch_inline: str | None = None) -> dict:
    """One inline button. `emoji_name` prefixes the label with that slot's
    unicode emoji so the look survives on every client."""
    label = text
    if emoji_name:
        label = f"{emo.char(emoji_name)} {text}"

    b: dict = {"text": label}
    if url:
        b["url"] = url
    elif switch_inline is not None:
        b["switch_inline_query_current_chat"] = switch_inline
    else:
        b["callback_data"] = data or "noop"

    if emoji_name and SEND_BUTTON_ICONS and emo.premium_id(emoji_name):
        b["text"] = text
        b["icon_custom_emoji_id"] = emo.premium_id(emoji_name)
    if style and SEND_BUTTON_STYLES and style in STYLES:
        b["style"] = style
    return b


def kb(*rows) -> dict:
    """Inline keyboard from rows. Falsy buttons and empty rows are dropped, so
    callers can inline `cond and btn(...)`."""
    clean = []
    for row in rows:
        if not row:
            continue
        if isinstance(row, dict):
            row = [row]
        cells = [b for b in row if b]
        if cells:
            clean.append(cells)
    return {"inline_keyboard": clean}


# ─── REPLY (PERSISTENT) KEYBOARD ──────────────────────────────
def reply_kb(labels: list, placeholder: str = "",
             style: str | None = STYLE_PRIMARY) -> dict:
    """The persistent keyboard. `style` colours every button:
    primary renders blue, success green, danger red, default/None dark.

    Verified against the live API — unlike inline buttons, Telegram
    *validates* this field on KeyboardButton and rejects unknown values, so
    only the four names above are safe.
    """
    if not SEND_BUTTON_STYLES:
        style = None

    def cell(text: str) -> dict:
        button = {"text": text}
        if style:
            button["style"] = style
        return button

    return {
        "keyboard": [[cell(text) for text in row] for row in labels],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": placeholder or None,
    }


def remove_reply_kb() -> dict:
    return {"remove_keyboard": True}


def force_reply(placeholder: str = "") -> dict:
    return {
        "force_reply": True,
        "input_field_placeholder": placeholder or None,
    }
