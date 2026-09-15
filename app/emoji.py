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

# Every slot's plain unicode character. These are chosen to exist in widely
# available premium emoji sets, so a harvested id and the plain fallback
# always show the same picture (see slots_for_char).
EMOJI = {
    # accent bar used as a header prefix — a custom emoji in polished
    # storefronts, a plain block character otherwise
    "bar":        "▎",

    # main menu
    "products":   "\U0001F381",   # 🎁
    "wallet":     "\U0001F4B3",   # 💳
    "orders":     "\U0001F9FE",   # 🧾
    "gift":       "\U0001F49D",   # 💝
    "support":    "\U0001F3A7",   # 🎧
    "profile":    "\U0001F464",   # 👤
    "language":   "\U0001F310",   # 🌐
    "home":       "\U0001F3E0",   # 🏠
    "help":       "❓",       # ❓
    "terms":      "\U0001F4C4",   # 📄

    # money
    "money":      "\U0001F4B5",   # 💵
    "price":      "\U0001F3F7",   # 🏷
    "balance":    "\U0001F4B0",   # 💰
    "bank":       "\U0001F3E6",   # 🏦
    "card":       "\U0001F4B3",   # 💳
    "coin":       "\U0001FA99",   # 🪙

    # catalog
    "category":   "\U0001F4C1",   # 📁
    "box":        "\U0001F6CD",   # 🛍
    "catalog":    "\U0001F4D6",   # 📖
    "stock":      "✅",       # ✅
    "sold":       "\U0001F3C6",   # 🏆
    "sku":        "\U0001F3F7",   # 🏷
    "delivery":   "\U0001F9FE",   # 🧾
    "note":       "\U0001F4D1",   # 📑
    "qty":        "\U0001F9FE",   # 🧾
    "coupon":     "\U0001F516",   # 🔖

    # state
    "ok":         "✅",       # ✅
    "no":         "\U0001F6AB",   # 🚫
    "warn":       "⚠",       # ⚠
    "low":        "\U0001F53D",   # 🔽
    "fire":       "\U0001F525",   # 🔥
    "spark":      "✨",       # ✨
    "party":      "\U0001F389",   # 🎉
    "rocket":     "\U0001F680",   # 🚀
    "clock":      "⏰",       # ⏰
    "bell":       "\U0001F514",   # 🔔
    "bell_off":   "\U0001F4F4",   # 📴
    "lock":       "\U0001F512",   # 🔒
    "key":        "\U0001F511",   # 🔑
    "refresh":    "\U0001F504",   # 🔄
    "back":       "\U0001F519",   # 🔙
    "close":      "❌",       # ❌
    "star":       "⭐",       # ⭐
    "tip":        "\U0001F4A1",   # 💡
    "user":       "\U0001F465",   # 👥
    "id":         "\U0001F4C7",   # 📇
    "clipboard":  "\U0001F4CB",   # 📋
    "chart":      "\U0001F4CA",   # 📊 bulk/volume rate
    "admin":      "⚙",       # ⚙
    "link":       "\U0001F517",   # 🔗
    "mail":       "\U0001F4E7",   # 📧
    "search":     "\U0001F50D",   # 🔍
    "ban":        "\U0001F6D1",   # 🛑
    "broadcast":  "\U0001F4E3",   # 📣
    "plus":       "➕",       # ➕
    "minus":      "➖",       # ➖
    "trash":      "\U0001F5D1",   # 🗑
    "edit":       "✏",       # ✏
    "dot":        "•",       # • (a bullet, deliberately never an emoji)

    # product-flavour slots — pick one of these as a product's emoji and it
    # becomes the hero graphic on its generated poster
    "music":      "\U0001F3B5",   # 🎵
    "video":      "\U0001F3AC",   # 🎬
    "game":       "\U0001F3AE",   # 🎮
    "brain":      "\U0001F9E0",   # 🧠
    "cloud":      "☁",       # ☁
    "shield":     "\U0001F6E1",   # 🛡
    "bolt":       "⚡",       # ⚡
    "camera":     "\U0001F4F8",   # 📸
    "phone":      "\U0001F4F1",   # 📱
    "monitor":    "\U0001F5A5",   # 🖥
    "crown":      "\U0001F451",   # 👑
    "gem":        "\U0001F48E",   # 💎
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


def save_premium(mapping: dict) -> int:
    """Merge {slot: custom_emoji_id} into data/emoji.json and reload."""
    current = dict(PREMIUM)
    current.update({
        str(k): str(v).strip()
        for k, v in mapping.items()
        if str(v).strip().isdigit() and k in EMOJI
    })
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_EMOJI_JSON, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=2, sort_keys=True)
    load_premium()
    return len(PREMIUM)


def normalize(char_text: str) -> str:
    """Drop variation selectors and joiners so '✏️' matches '✏'."""
    return "".join(
        c for c in char_text
        if c not in ("️", "︎", "‍")
    )


def slots_for_char(char_text: str) -> list:
    """Slot names whose unicode char is this emoji (ignoring variation
    selectors), so a harvested id lands on the right slots."""
    target = normalize(char_text)
    if not target:
        return []
    return [
        slot for slot, value in EMOJI.items()
        if normalize(value) == target
    ]


async def audit(tg_module) -> dict:
    """Ask Telegram about every mapped id and drop the dead ones.

    This matters more than it looks: Telegram rejects a whole message if any
    custom_emoji_id in it is invalid, and the retry path strips *all* emoji
    entities — so one stale id silently turns the entire bot back to plain
    emoji. Pruning at startup keeps that from happening.

    -> {"total", "animated", "static", "dropped", "sets"}
    """
    ids = sorted(set(PREMIUM.values()))
    if not ids:
        return {"total": 0, "animated": 0, "static": 0, "dropped": 0,
                "sets": []}

    alive, animated, sets = {}, 0, []
    for start in range(0, len(ids), 200):
        data = await tg_module.api(
            "getCustomEmojiStickers",
            {"custom_emoji_ids": ids[start:start + 200]}, quiet=True)
        if not data.get("ok"):
            # Cannot verify right now — leave the map untouched.
            return {"total": len(ids), "animated": -1, "static": -1,
                    "dropped": 0, "sets": []}
        for sticker in data.get("result") or []:
            eid = str(sticker.get("custom_emoji_id"))
            alive[eid] = sticker
            if sticker.get("is_animated") or sticker.get("is_video"):
                animated += 1
            name = sticker.get("set_name")
            if name and name not in sets:
                sets.append(name)

    dropped = [slot for slot, eid in PREMIUM.items() if eid not in alive]
    if dropped:
        keep = {slot: eid for slot, eid in PREMIUM.items() if eid in alive}
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(_EMOJI_JSON, "w", encoding="utf-8") as fh:
            json.dump(keep, fh, ensure_ascii=False, indent=2, sort_keys=True)
        load_premium()
        logger.warning("dropped %d dead emoji id(s): %s",
                       len(dropped), ", ".join(dropped))

    return {
        "total": len(alive),
        "animated": animated,
        "static": len(alive) - animated,
        "dropped": len(dropped),
        "sets": sets,
    }


def char(name: str) -> str:
    """The plain unicode char for a slot, or a star if the slot is unknown."""
    return EMOJI.get(name, EMOJI["star"])


def premium_id(name: str) -> str | None:
    return PREMIUM.get(name)


load_premium()
