"""
app/commands.py — one definition of every slash command.

This single list drives three things, so they can never drift apart:
  * the command list printed inside /start
  * Telegram's hamburger menu (setMyCommands, per language)
  * the router in app/handlers/router.py
"""

from .lang import LANGS, t

# (command, description key, emoji slot, admin only)
COMMANDS = [
    ("start",    "cmd_start",    "home",     False),
    ("products", "cmd_products", "products", False),
    ("wallet",   "cmd_wallet",   "wallet",   False),
    ("topup",    "cmd_topup",    "money",    False),
    ("orders",   "cmd_orders",   "orders",   False),
    ("gift",     "cmd_gift",     "gift",     False),
    ("support",  "cmd_support",  "support",  False),
    ("profile",  "cmd_profile",  "profile",  False),
    ("language", "cmd_language", "language", False),
    ("help",     "cmd_help",     "help",     False),
    ("terms",    "cmd_terms",    "terms",    False),
    ("id",       "cmd_id",       "id",       False),
    ("admin",    "cmd_admin",    "admin",    True),
    ("inventorylist", "cmd_inventory", "stock", True),
]

DESCRIPTIONS = {
    "cmd_start": {
        "en": "open the shop", "bn": "শপ খুলুন", "hi": "शॉप खोलें",
        "ru": "открыть магазин", "zh": "打开商店", "vi": "mở cửa hàng",
    },
    "cmd_products": {
        "en": "browse every category", "bn": "সব ক্যাটাগরি দেখুন",
        "hi": "सभी कैटेगरी देखें", "ru": "все категории",
        "zh": "浏览所有分类", "vi": "xem mọi danh mục",
    },
    "cmd_wallet": {
        "en": "balance and top-up", "bn": "ব্যালেন্স ও টপ-আপ",
        "hi": "बैलेंस और टॉप-अप", "ru": "баланс и пополнение",
        "zh": "余额与充值", "vi": "số dư và nạp tiền",
    },
    "cmd_topup": {
        "en": "add funds to the wallet", "bn": "ওয়ালেটে টাকা যোগ করুন",
        "hi": "वॉलेट में पैसे जोड़ें", "ru": "пополнить кошелёк",
        "zh": "为钱包充值", "vi": "nạp tiền vào ví",
    },
    "cmd_orders": {
        "en": "your last purchases", "bn": "আপনার সাম্প্রতিক কেনাকাটা",
        "hi": "आपकी पिछली खरीदारी", "ru": "ваши покупки",
        "zh": "你的购买记录", "vi": "các đơn gần đây",
    },
    "cmd_gift": {
        "en": "redeem a gift code", "bn": "গিফট কোড ব্যবহার করুন",
        "hi": "गिफ्ट कोड रिडीम करें", "ru": "активировать подарочный код",
        "zh": "兑换礼品码", "vi": "dùng mã quà tặng",
    },
    "cmd_support": {
        "en": "payments and missing items", "bn": "পেমেন্ট ও না-পাওয়া আইটেম",
        "hi": "भुगतान और न मिले आइटम", "ru": "оплата и проблемы с товаром",
        "zh": "付款与未收到商品", "vi": "thanh toán và hàng thiếu",
    },
    "cmd_profile": {
        "en": "your account and totals", "bn": "আপনার অ্যাকাউন্ট ও হিসাব",
        "hi": "आपका खाता और कुल", "ru": "ваш аккаунт и итоги",
        "zh": "你的账户与统计", "vi": "tài khoản và tổng kết",
    },
    "cmd_language": {
        "en": "change the language", "bn": "ভাষা বদলান",
        "hi": "भाषा बदलें", "ru": "сменить язык",
        "zh": "更改语言", "vi": "đổi ngôn ngữ",
    },
    "cmd_help": {
        "en": "how buying works", "bn": "কেনার নিয়ম",
        "hi": "खरीदारी कैसे होती है", "ru": "как купить",
        "zh": "如何购买", "vi": "cách mua hàng",
    },
    "cmd_terms": {
        "en": "store terms and warranty", "bn": "শর্ত ও ওয়ারেন্টি",
        "hi": "नियम और वारंटी", "ru": "условия и гарантия",
        "zh": "条款与保障", "vi": "điều khoản và bảo hành",
    },
    "cmd_id": {
        "en": "show your telegram id", "bn": "আপনার টেলিগ্রাম আইডি",
        "hi": "आपकी टेलीग्राम आईडी", "ru": "показать ваш telegram id",
        "zh": "显示你的 telegram id", "vi": "xem telegram id của bạn",
    },
    "cmd_admin": {
        "en": "admin panel", "bn": "অ্যাডমিন প্যানেল",
        "hi": "एडमिन पैनल", "ru": "админ-панель",
        "zh": "管理面板", "vi": "bảng quản trị",
    },
    "cmd_inventory": {
        "en": "full stock list", "bn": "সম্পূর্ণ স্টক তালিকা",
        "hi": "पूरी स्टॉक सूची", "ru": "весь склад",
        "zh": "完整库存清单", "vi": "toàn bộ kho",
    },
}


def describe(key: str, lang: str = "en") -> str:
    entry = DESCRIPTIONS.get(key)
    if not entry:
        return t(key, lang)
    return entry.get(lang[:2]) or entry["en"]


def public_commands(lang: str = "en") -> list:
    """Payload for setMyCommands (default scope)."""
    return [
        {"command": name, "description": describe(desc_key, lang)}
        for name, desc_key, _emoji, admin_only in COMMANDS
        if not admin_only
    ]


def admin_commands(lang: str = "en") -> list:
    """Payload for setMyCommands scoped to an admin chat."""
    return [
        {"command": name, "description": describe(desc_key, lang)}
        for name, desc_key, _emoji, _admin_only in COMMANDS
    ]


def listing(lang: str = "en", include_admin: bool = False) -> list:
    """(/command, emoji slot, description) rows for the /start screen."""
    return [
        (f"/{name}", emoji_name, describe(desc_key, lang))
        for name, desc_key, emoji_name, admin_only in COMMANDS
        if include_admin or not admin_only
    ]


def all_langs() -> list:
    return list(LANGS.keys())


# Admins who already have the admin-scoped menu registered this run.
_admin_menu_done: set = set()


async def ensure_admin_menu(user_id, tg_module) -> bool:
    """Register the admin command menu for one admin, once.

    A chat-scoped setMyCommands fails with "chat not found" until that admin
    has opened the bot, so this is called again on their first interaction
    rather than only at startup.
    """
    key = str(user_id)
    if key in _admin_menu_done:
        return False
    data = await tg_module.set_my_commands(
        admin_commands("en"),
        scope={"type": "chat", "chat_id": user_id},
        quiet=True,
    )
    if data.get("ok"):
        _admin_menu_done.add(key)
        return True
    return False
