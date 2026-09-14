"""
app/emoji.py — the emoji vocabulary of the UI.

Two layers:
  1. EMOJI  — the plain unicode character for every named slot. Always works.
  2. data/emoji.json — optional map of {name: custom_emoji_id} so a Premium
     bot renders animated custom emoji in the same slots. Missing or invalid
     ids fall back to layer 1 automatically (see app/msg.py).

To collect your own ids: forward a message containing the premium emoji to
@RawDataBot and copy "custom_emoji_id" out of the entities array.
"""

import json
import logging
import os

from . import config

logger = logging.getLogger(__name__)

# Accent bar + divider used by every header in the UI.
BAR = "▎"          # ▎
DIVIDER = "─" * 14  # ──────────────

EMOJI = {
    # main menu
    "products":   "\U0001F381",   # 🎁
    "wallet":     "\U0001F4B3",   # 💳
    "orders":     "\U0001F9FE",   # 🧾
    "gift":       "\U0001F39F",   # 🎟
    "support":    "\U0001F3A7",   # 🎧
    "profile":    "\U0001F194",   # 🆔
    "language":   "\U0001F310",   # 🌐
    "home":       "\U0001F3E0",   # 🏠
    "help":       "❓",       # ❓
    "terms":      "\U0001F4C3",   # 📃

    # money
    "money":      "\U0001F4B5",   # 💵
    "price":      "\U0001F3F7",   # 🏷
    "balance":    "\U0001F4B0",   # 💰
    "bank":       "\U0001F3DB",   # 🏛
    "card":       "\U0001F4B3",   # 💳
    "coin":       "\U0001FA99",   # 🪙

    # catalog
    "category":   "\U0001F5C2",   # 🗂
    "box":        "\U0001F4E6",   # 📦
    "catalog":    "\U0001F522",   # 🔢
    "stock":      "✅",       # ✅
    "sold":       "\U0001F3C6",   # 🏆
    "sku":        "\U0001F3F7",   # 🏷
    "delivery":   "\U0001F9FE",   # 🧾
    "note":       "\U0001F4D1",   # 📑
    "qty":        "\U0001F9FE",   # 🧾
    "coupon":     "\U0001F39F",   # 🎟

    # state
    "ok":         "✅",       # ✅
    "no":         "\U0001F6AB",   # 🚫
    "warn":       "⚠",       # ⚠
    "low":        "\U0001F53B",   # 🔻
    "fire":       "\U0001F525",   # 🔥
    "spark":      "✨",       # ✨
    "party":      "\U0001F389",   # 🎉
    "rocket":     "\U0001F680",   # 🚀
    "clock":      "\U0001F550",   # 🕐
    "bell":       "\U0001F514",   # 🔔
    "bell_off":   "\U0001F515",   # 🔕
    "lock":       "\U0001F512",   # 🔒
    "key":        "\U0001F511",   # 🔑
    "refresh":    "\U0001F504",   # 🔄
    "back":       "\U0001F519",   # 🔙
    "close":      "❌",       # ❌
    "star":       "⭐",       # ⭐
    "tip":        "\U0001F34B",   # 🍋
    "user":       "\U0001F464",   # 👤
    "id":         "\U0001F194",   # 🆔
    "clipboard":  "\U0001F4CB",   # 📋
    "chart":      "\U0001F4C8",   # 📈
    "admin":      "\U0001F6E0",   # 🛠
    "link":       "\U0001F517",   # 🔗
    "mail":       "\U0001F4E7",   # 📧
    "search":     "\U0001F50D",   # 🔍
    "ban":        "\U0001F6D1",   # 🛑
    "broadcast":  "\U0001F4E3",   # 📣
    "plus":       "➕",       # ➕
    "minus":      "➖",       # ➖
    "trash":      "\U0001F5D1",   # 🗑
    "edit":       "✏",       # ✏
    "dot":        "•",       # •
}

# Filled from data/emoji.json at import time.
PREMIUM: dict = {}

_EMOJI_JSON = os.path.join(config.DATA_DIR, "emoji.json")


def load_premium() -> dict:
    """(Re)read data/emoji.json. Safe to call at any time."""
    global PREMIUM
    if not os.path.exists(_EMOJI_JSON):
        PREMIUM = {}
        return PREMIUM
    try:
        with open(_EMOJI_JSON, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        PREMIUM = {
            str(k): str(v).strip()
            for k, v in raw.items()
            if str(v).strip().isdigit()
        }
    except (OSError, ValueError) as exc:
        logger.warning("emoji.json ignored (%s)", exc)
        PREMIUM = {}
    return PREMIUM


def char(name: str) -> str:
    """The plain unicode char for a slot, or a star if the slot is unknown."""
    return EMOJI.get(name, EMOJI["star"])


def premium_id(name: str) -> str | None:
    return PREMIUM.get(name)


load_premium()
