"""
AI Chat Store Bot
Custom emoji via entities array (not HTML tg-emoji tags)
icon_custom_emoji_id for buttons
Python 3.14 compatible - raw aiohttp, no python-telegram-bot

FIX NOTES (ENTITY_TEXT_INVALID):
- Telegram rejects the WHOLE message if any custom_emoji_id in the
  entities array is not a real, existing custom emoji sticker id.
- Since we can't verify IDs without hitting the API, send_msg/edit_msg
  now automatically retry WITHOUT entities if the first attempt fails
  with an entity-related error, so the bot never just dies on a bad id.
- Also normalized custom_emoji_id to str() and guarded against
  zero-length entity content.
"""

import asyncio
import logging
import aiohttp
from aiohttp import web
import json
import os
import uuid
import re
import tempfile
from datetime import datetime, timedelta
from i18n import t as _t

# Web3 for direct BSC RPC verification (no API key needed)
try:
    from web3 import Web3
    _WEB3_AVAILABLE = True
except ImportError:
    _WEB3_AVAILABLE = False
    logger_placeholder = logging.getLogger(__name__)
    logger_placeholder.warning(
        "web3 library not installed. Direct RPC verification disabled. "
        "Run: pip install web3"
    )

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────
# NOTE: put your real token in an env var, don't hardcode it.
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "PUT_YOUR_NEW_BOT_TOKEN_HERE")
API        = f"https://api.telegram.org/bot{BOT_TOKEN}"
DB_PATH      = os.path.join(os.path.dirname(__file__), "users.json")
CAT_PATH     = os.path.join(os.path.dirname(__file__), "categories.json")
STOCK_PATH   = os.path.join(os.path.dirname(__file__), "stock.json")
ORDERS_PATH  = os.path.join(os.path.dirname(__file__), "orders.json")

ORDER_EXPIRY_MINUTES = 30

# ─── BSCSCAN AUTO-VERIFY CONFIG ───────────────────────────────
# Get your FREE API key at: https://bscscan.com/myapikey
# Free tier: 5 calls/sec, 100k calls/day — more than enough.
BSCSCAN_API_KEY = os.environ.get("BSCSCAN_API_KEY", "YourBscScanApiKeyHere")

# USDT BEP20 contract address on BSC (do NOT change this)
USDT_BEP20_CONTRACT = "0x55d398326f99059ff775485246999027b3197955"

# ─── WEB3 / BSC RPC CONFIG ────────────────────────────────────
# Free public BSC RPC nodes — no signup or API key needed.
# If one is rate-limited the code tries the next one automatically.
# Updated list: https://chainlist.org/chain/56
BSC_RPC_ENDPOINTS = [
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.defibit.io/",
    "https://bsc-dataseed1.ninicoin.io/",
    "https://bsc-dataseed2.defibit.io/",
    "https://bsc-dataseed2.ninicoin.io/",
]

# Minimum on-chain confirmations required before accepting a payment
MIN_CONFIRMATIONS = 3

# ERC-20 / BEP-20 Transfer event topic (keccak256 of the signature)
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Additional BEP20 tokens supported by Web3 path (BUSD etc.)
BEP20_TOKENS = {
    "USDT": {
        "contract": "0x55d398326f99059ff775485246999027b3197955",
        "decimals": 18,
    },
    "BUSD": {
        "contract": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
        "decimals": 18,
    },
    "BUSD-T": {
        "contract": "0x55d398326f99059ff775485246999027b3197955",
        "decimals": 18,
    },
}

# Used txn hashes stored here to prevent double-spend
USED_TXN_PATH = os.path.join(os.path.dirname(__file__), "used_txns.json")

# Track users who are waiting to submit a txn hash for BEP20
# { user_id: order_id }
_awaiting_txn_hash: dict = {}

# Track users who are waiting to submit a txn hash for TRC20 (TRON)
# { user_id: order_id }
_awaiting_trx_hash: dict = {}

# ─── TRC20 CONFIG ─────────────────────────────────────────────
# USDT TRC20 contract address on TRON (do NOT change this)
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# TronScan public API — no API key required, free to use
TRONSCAN_API_URL = "https://apilist.tronscanapi.com/api"

# Minimum confirmations for TRON transactions
TRC20_MIN_CONFIRMATIONS = 1

# ─── PAYMENT CONFIG ───────────────────────────────────────────
PAYMENTS_PATH = os.path.join(os.path.dirname(__file__), "payments.json")

# Payment QR images (optional — place matching images in bot folder)
USDT_BEP20_IMAGE    = os.path.join(os.path.dirname(__file__), "usdt_bep20.jpg")
USDT_TRX_IMAGE      = os.path.join(os.path.dirname(__file__), "usdt_trx.jpg")
BTC_IMAGE           = os.path.join(os.path.dirname(__file__), "btc.jpg")

# ─── BTC CONFIG ───────────────────────────────────────────────
BTC_ADDRESS = "bc1qltuq4ff037ne08ew2hwhfetttlqaepsyks87yc"

_PAY_IMAGES = {
    "bep20":   USDT_BEP20_IMAGE,
    "trx":     USDT_TRX_IMAGE,
    "btc":     BTC_IMAGE,
}

def _load_payments() -> dict:
    """Load payments.json — uses in-memory cache."""
    global _pay_cache
    if _pay_cache is not None:
        return _pay_cache
    default = {
        "bep20":   {"label": "USDT BEP20 (BSC)",   "network": "BNB Smart Chain", "address": "", "enabled": True},
        "trx":     {"label": "USDT TRC20 (TRON)",  "network": "TRON",            "address": "", "enabled": True},
        "btc":     {"label": "Bitcoin (BTC)",       "network": "Bitcoin",         "address": BTC_ADDRESS, "enabled": True},
    }
    if not os.path.exists(PAYMENTS_PATH):
        with open(PAYMENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
        _pay_cache = default
        return _pay_cache
    with open(PAYMENTS_PATH, "r", encoding="utf-8") as f:
        _pay_cache = json.load(f)
    return _pay_cache

def _save_payments(data: dict):
    global _pay_cache
    _pay_cache = data
    with open(PAYMENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_enabled_payments() -> dict:
    """Returns only enabled payment methods with non-empty addresses."""
    pays = _load_payments()
    return {k: v for k, v in pays.items() if v.get("enabled") and v.get("address", "").strip()}

def get_payment(network: str) -> dict | None:
    pays = _load_payments()
    return pays.get(network)

# Sales log channel (set to your channel's chat_id, e.g. -1001234567890)
# The bot must be an admin in this channel
LOG_CHANNEL_ID = -1004393660538  # Force-join channel / sales log channel

# Admin user IDs. Set the ADMIN_ID env var (comma-separated for multiple)
# to override the default without editing code.
_admin_env = os.environ.get("ADMIN_ID", "").replace(",", " ").split()
ADMINS = [int(x) for x in _admin_env if x.strip().isdigit()] or [8428366795]

# ─── FORCE JOIN ───────────────────────────────────────────────
FORCE_JOIN_CHANNEL_ID   = -1004393660538
FORCE_JOIN_CHANNEL_LINK = "https://t.me/star_chat_hub"
FORCE_JOIN_CHANNEL_NAME = "star_chat_hub"

# ─── TERMS & CONDITIONS ───────────────────────────────────────
TERMS_TEXT = """📃 Terms & Conditions

Welcome to AI Chat Store. By using our bot and services, you agree to the following terms:

🔥 Order Confirmation
Please check the product name, duration, price, and requirements before placing an order.

2️⃣ Payment
All payments must be completed using the payment methods shown in the bot. After payment, you must tap I've Paid or send payment proof/transaction ID.

3️⃣ Delivery Time
Delivery time depends on the product. Some products are instant, while others may take time for activation.

4️⃣ Correct Information
Customers must provide correct email, username, phone number, or account details when required. We are not responsible for delays or issues caused by incorrect information.

✅ Warranty
Warranty depends on the product. Some products include full warranty, some include activation warranty only, and some have no warranty after activation. Please read the product details before buying.

💰 Refund Policy
Refunds are only available if the product cannot be delivered or activated. Refunds are not available after successful delivery/activation unless the product has warranty.

🔑 Account Safety
Do not change passwords, emails, or account details during activation unless support tells you to do so.

💬 Support
If you face any issue, contact support with your order proof, payment proof, and problem details.

🎁 Stock Availability
Products may go out of stock at any time. If a product is unavailable, you can wait for restock or choose another product.

💰 By placing an order, you confirm that you have read and accepted these terms."""

# ─── PREMIUM EMOJIS ───────────────────────────────────────────
# IMPORTANT: These custom_emoji_ids must correspond to REAL Telegram
# Premium custom emoji stickers, or Telegram will reject the message
# with ENTITY_TEXT_INVALID. To get real ids: send/forward a message
# containing the premium emoji to @RawDataBot or @userinfobot and
# read the "custom_emoji_id" field from the returned entities JSON.
PREMIUM_EMOJIS = {
    # ✅ Confirmed valid IDs only
    "wave":     "6041921818896372382",
    "bot":      "6030400221232501136",
    "shop":     "5447387942995655277",
    "profile":  "5445174334031166029",
    "menu":     "5445260044398524944",
    "wallet":   "5447453226498552490",
    "referral": "6037175527846975726",
    "down":     "5893057118545646106",
    "bag":      "5226656353744862682",
    "back":     "5352759161945867747",
    # ✅ New user-facing premium emojis
    "balance":  "6233367447789899509",
    "check":    "5206607081334906820",
    "cart":     "5226656353744862682",
    "key":      "5278573677900752088",
    "box":      "5355193051193059834",
    "pop":      "5208541126583136130",
    "clock":    "5465248203718794436",
    "timer":    "5222175229681343920",
    "camera":   "5235837920081887219",
    "thunder":  "5258203794772085854",
    "arrow":    "5435955998479102657",
    "clipboard": "5197269100878907942",
    "cross":    "5210952531676504517",
    "checkmark": "5206607081334906820",
    # ✅ Payment instruction emojis
    "number1":  "5269520668524821648",
    "number2":  "5269293426100157176",
    "number3":  "5269412160471053597",
    "number4":  "5269624830071686015",
    "tick":     "5206607081334906820",
    "gift":     "5355193051193059834",
    "moneybag": "6233367447789899509",
    "user":     "6174508000489768736",
    "mobile":   "6177059060739741318",
    "instructions": "5458801848649532015",
    "bank":     "5332455502917949981",
    "cbe":      "5961054379350955385",
    "telebirr": "5960632377339285724",
    "channel":  "5891243564309942507",
    "support":  "5240464278464515740",
    "document": "5456163794017028654",
    "paywallet": "5769403330761593044",
    "usdt":     "5447453226498552490",
    "crypto":   "5258203794772085854",
    "bep20":    "5217811903685865303",
    "trx":      "5201692367437974073",
    "btc":      "5258203794772085854",
    "globe":    "5452064260437859029",
    "plus":     "5397916757333654639",
    "pencil":   "5395444784611480792",
    "minus":    "5287631609309189694",
}

# Unicode fallback chars for each emoji key
EMOJI_CHAR = {
    "wave":     "👋",
    "bot":      "🤖",
    "shop":     "🛒",
    "profile":  "👤",
    "menu":     "📋",
    "wallet":   "💰",
    "referral": "🎁",
    "down":     "⬇️",
    "back":     "⬅️",
    "home":     "🏠",
    "add":      "➕",
    "share":    "📤",
    "star":     "⭐",
    "bag":      "🛍️",
    "fire":     "🔥",
    "check":    "✅",
    "soon":     "🔜",
    "support":  "💬",
    "earn":     "💸",
    "id":       "🪪",
    "balance":  "💳",
    "status":   "🟢",
    "ping":     "📡",
    "cmd":      "📋",
    "other":    "🔧",
    "link":     "🔗",
    "cart":     "🛒",
    "key":      "🔑",
    "box":      "📦",
    "pop":      "🎉",
    "clock":    "🕐",
    "timer":    "⏳",
    "camera":   "📸",
    "thunder":  "⚡",
    "arrow":    "▶",
    "clipboard": "📋",
    "cross":    "❌",
    "checkmark": "✔️",
    "number1":  "1️⃣",
    "number2":  "2️⃣",
    "number3":  "3️⃣",
    "number4":  "4️⃣",
    "tick":     "✔️",
    "gift":     "🎁",
    "moneybag": "💰",
    "user":     "👤",
    "mobile":   "📱",
    "instructions": "📝",
    "bank":     "🏦",
    "cbe":      "🏦",
    "telebirr": "💙",
    "channel":  "💬",
    "support":  "🎙",
    "document": "📃",
    "paywallet": "💳",
    "usdt":     "💰",
    "crypto":   "⚡",
    "bep20":    "🟡",
    "trx":      "💵",
    "btc":      "₿",

    "plus":     "➕",
    "pencil":   "✏️",
    "minus":    "➖",
    "globe":    "🌐",
}

# ─── UTF-16 HELPER ────────────────────────────────────────────
def u16(s: str) -> int:
    """UTF-16-LE length (Telegram uses this for entity offsets)."""
    return len(s.encode("utf-16-le")) // 2

# ─── MESSAGE BUILDER ──────────────────────────────────────────
class Msg:
    """
    Build a message with premium emoji entities.

    Usage:
        m = Msg()
        m.emoji("wave")
        m.text("  Welcome to ")
        m.bold("AI Chat Store")
        m.text("\\n\\n")
        text, entities = m.build()
    """
    def __init__(self):
        self._parts   = []   # list of (kind, content, eid, key)
        self._current = ""

    def _flush(self):
        if self._current:
            self._parts.append(("text", self._current, None, None))
            self._current = ""

    def text(self, s: str):
        self._current += s
        return self

    def italic(self, s: str):
        self._flush()
        self._parts.append(("italic", s, None, None))
        return self

    def underline(self, s: str):
        self._flush()
        self._parts.append(("underline", s, None, None))
        return self

    def strike(self, s: str):
        self._flush()
        self._parts.append(("strike", s, None, None))
        return self

    def bold(self, s: str):
        self._flush()
        self._parts.append(("bold", s, None, None))
        return self

    def code(self, s: str):
        self._flush()
        self._parts.append(("code", s, None, None))
        return self

    def emoji(self, key: str):
        self._flush()
        char = EMOJI_CHAR.get(key, "⭐")
        eid  = PREMIUM_EMOJIS.get(key)
        # Only add emoji if we have a valid custom_emoji_id
        if eid:
            self._parts.append(("emoji", char, str(eid), key))
        else:
            # No custom emoji id, just add as regular text
            self._current += char
        return self

    def nl(self, n: int = 1):
        self._current += "\n" * n
        return self

    def build(self):
        self._flush()
        full_text = ""
        entities  = []
        offset    = 0

        for kind, content, eid, key in self._parts:
            length = u16(content)
            # Skip zero-length content to avoid invalid entities
            if length == 0:
                continue
                
            if kind == "emoji" and eid:
                # Ensure custom_emoji_id is valid string
                try:
                    emoji_id = str(eid).strip()
                    if emoji_id and emoji_id.isdigit():
                        entities.append({
                            "type":            "custom_emoji",
                            "offset":          offset,
                            "length":          length,
                            "custom_emoji_id": emoji_id,
                        })
                except:
                    # If anything fails, skip this entity
                    pass
            elif kind == "bold":
                entities.append({
                    "type":   "bold",
                    "offset": offset,
                    "length": length,
                })
            elif kind == "italic":
                entities.append({
                    "type":   "italic",
                    "offset": offset,
                    "length": length,
                })
            elif kind == "underline":
                entities.append({
                    "type":   "underline",
                    "offset": offset,
                    "length": length,
                })
            elif kind == "strike":
                entities.append({
                    "type":   "strikethrough",
                    "offset": offset,
                    "length": length,
                })
            elif kind == "code":
                entities.append({
                    "type":   "code",
                    "offset": offset,
                    "length": length,
                })
            full_text += content
            offset    += length

        return full_text, entities

# ─── BUTTON HELPERS ───────────────────────────────────────────
def btn(text: str, callback_data: str = None, url: str = None,
        emoji_key: str = None, style: str = None) -> dict:
    b: dict = {"text": text}
    if callback_data:
        b["callback_data"] = callback_data
    elif url:
        b["url"] = url
    else:
        b["callback_data"] = "noop"
    if emoji_key and PREMIUM_EMOJIS.get(emoji_key):
        b["icon_custom_emoji_id"] = str(PREMIUM_EMOJIS[emoji_key])
    if style:
        b["style"] = style
    return b

def build_keyboard(rows: list) -> dict:
    return {"inline_keyboard": rows}

# ─── HTTP SESSION ─────────────────────────────────────────────
_session: aiohttp.ClientSession | None = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(
            limit=100,           # max concurrent connections
            ttl_dns_cache=300,   # cache DNS for 5 min
        )
        _session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(
                total=10,       # per API call (not long-poll)
                connect=5,
            )
        )
    return _session

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()

# ─── RAW API ──────────────────────────────────────────────────
async def api_call(method: str, payload: dict):
    session = await get_session()
    # Long-polling needs a longer timeout than regular API calls
    if method == "getUpdates":
        timeout = aiohttp.ClientTimeout(total=45, connect=5)
    else:
        timeout = None  # use session default (10s)
    try:
        async with session.post(
            f"{API}/{method}", json=payload, timeout=timeout
        ) as r:
            data = await r.json()
            if not data.get("ok"):
                logger.error(f"[{method}] {data.get('description','?')}")
            return data
    except Exception as ex:
        logger.error(f"[{method}] {ex}")
        return {"ok": False}

def _is_entity_error(data: dict) -> bool:
    desc = (data.get("description") or "").upper()
    return "ENTITY" in desc

async def send_msg(chat_id, text: str, entities: list = None,
                   keyboard: dict = None):
    payload: dict = {
        "chat_id":                  chat_id,
        "text":                     text,
        "disable_web_page_preview": True,
    }
    if entities:
        payload["entities"] = entities
    if keyboard:
        payload["reply_markup"] = keyboard

    data = await api_call("sendMessage", payload)

    # Fallback: if entities caused the failure (e.g. bad custom_emoji_id),
    # retry once with plain text so the user still gets a reply.
    if not data.get("ok") and entities and _is_entity_error(data):
        logger.warning("Retrying sendMessage without entities (entity error).")
        logger.warning(f"Failing entities were: {entities}")
        logger.warning(f"Text was: {repr(text)}")
        payload.pop("entities", None)
        data = await api_call("sendMessage", payload)

    return data

async def send_photo(chat_id, photo_url: str, caption: str = "",
                     entities: list = None, keyboard: dict = None):
    payload: dict = {
        "chat_id": chat_id,
        "photo":   photo_url,
    }
    if caption:
        payload["caption"] = caption
    if entities:
        payload["caption_entities"] = entities
    if keyboard:
        payload["reply_markup"] = keyboard

    data = await api_call("sendPhoto", payload)

    # Fallback: if entities caused the failure
    if not data.get("ok") and entities and _is_entity_error(data):
        logger.warning("Retrying sendPhoto without entities.")
        payload.pop("caption_entities", None)
        data = await api_call("sendPhoto", payload)

    return data

async def send_local_photo(chat_id, file_path: str, caption: str = "",
                            keyboard: dict = None, caption_entities: list = None):
    """Upload a local image file as a photo with optional caption and entities."""
    session = await get_session()
    try:
        with open(file_path, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption)
            if caption_entities:
                form.add_field("caption_entities", json.dumps(caption_entities))
            if keyboard:
                form.add_field("reply_markup", json.dumps(keyboard))
            form.add_field(
                "photo", f,
                filename=os.path.basename(file_path),
                content_type="image/jpeg"
            )
            async with session.post(f"{API}/sendPhoto", data=form) as r:
                data = await r.json()
                if not data.get("ok"):
                    logger.error(f"[send_local_photo] {data.get('description','?')}")
                return data
    except Exception as ex:
        logger.error(f"[send_local_photo] {ex}")
        return {"ok": False}

async def send_document(chat_id, file_path: str, caption: str = "",
                        caption_entities: list = None, keyboard: dict = None):
    """Upload a local file as a document (e.g. .txt) to a chat."""
    session = await get_session()
    try:
        with open(file_path, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption)
            if caption_entities:
                form.add_field("caption_entities", json.dumps(caption_entities))
            if keyboard:
                form.add_field("reply_markup", json.dumps(keyboard))
            form.add_field(
                "document", f,
                filename=os.path.basename(file_path),
                content_type="text/plain"
            )
            async with session.post(f"{API}/sendDocument", data=form) as r:
                data = await r.json()
                if not data.get("ok"):
                    logger.error(f"[send_document] {data.get('description','?')}")
                return data
    except Exception as ex:
        logger.error(f"[send_document] {ex}")
        return {"ok": False}


async def get_user_profile_photos(user_id):
    """Get user profile photos. Returns list of photo objects."""
    data = await api_call("getUserProfilePhotos", {
        "user_id": user_id,
        "limit":   1,
    })
    if data.get("ok"):
        photos = data.get("result", {}).get("photos", [])
        return photos
    return []

async def edit_msg(chat_id, message_id: int, text: str,
                   entities: list = None, keyboard: dict = None):
    payload: dict = {
        "chat_id":                  chat_id,
        "message_id":               message_id,
        "text":                     text,
        "disable_web_page_preview": True,
    }
    if entities:
        payload["entities"] = entities
    if keyboard:
        payload["reply_markup"] = keyboard

    data = await api_call("editMessageText", payload)

    if not data.get("ok") and entities and _is_entity_error(data):
        logger.warning("Retrying editMessageText without entities (entity error).")
        payload.pop("entities", None)
        data = await api_call("editMessageText", payload)

    return data

async def send_profile(chat_id, user: dict, db_data: dict, keyboard: dict):
    """Send profile with photo if available, else plain text."""
    uid      = user.get("id")
    text, entities = build_profile(user, db_data)

    # Try to get profile photo
    photos = await get_user_profile_photos(uid)
    if photos:
        # Pick the largest size of the first photo
        best = max(photos[0], key=lambda s: s.get("width", 0))
        file_id = best.get("file_id")
        if file_id:
            # Send as photo with caption
            payload: dict = {
                "chat_id":          chat_id,
                "photo":            file_id,
                "caption":          text,
            }
            if entities:
                payload["caption_entities"] = entities
            if keyboard:
                payload["reply_markup"] = keyboard
            data = await api_call("sendPhoto", payload)
            if data.get("ok"):
                return
            # If sendPhoto fails with entity error, retry without entities
            if _is_entity_error(data):
                payload.pop("caption_entities", None)
                data = await api_call("sendPhoto", payload)
                if data.get("ok"):
                    return

    # Fallback: no photo or photo failed — send as plain text
    await send_msg(chat_id, text, entities, keyboard)


async def edit_profile(chat_id, message_id: int, user: dict,
                       db_data: dict, keyboard: dict):
    """Edit existing message — since we can't edit a photo back to text easily,
    just delete old and send fresh."""
    await api_call("deleteMessage", {
        "chat_id":    chat_id,
        "message_id": message_id,
    })
    await send_profile(chat_id, user, db_data, keyboard)

async def answer_cb(cq_id: str, text: str = "", alert: bool = False):
    return await api_call("answerCallbackQuery", {
        "callback_query_id": cq_id,
        "text":              text,
        "show_alert":        alert,
    })

# ─── FORCE JOIN HELPER ────────────────────────────────────────
async def check_membership(user_id) -> bool:
    """Returns True if user is a member/admin/creator of the channel."""
    data = await api_call("getChatMember", {
        "chat_id": FORCE_JOIN_CHANNEL_ID,
        "user_id": user_id,
    })
    if not data.get("ok"):
        # If check fails (e.g. bot not in channel), let user through
        logger.warning(f"[force_join] getChatMember failed: {data.get('description')}")
        return True
    status = data.get("result", {}).get("status", "")
    return status in ("member", "administrator", "creator")

async def send_join_prompt(chat_id, lang: str = "en"):
    """Send the force-join message asking user to join the channel."""
    m = Msg()
    m.emoji("wave").text(" ").bold(_t("join_welcome", lang)).nl(2)
    m.bold(_t("join_must_join", lang)).nl(2)
    m.emoji("channel").text(" ").bold(_t("join_channel_1", lang)).nl()
    m.emoji("channel").text(" ").bold(_t("join_channel_2", lang)).nl(2)
    m.bold(_t("join_after", lang))

    join_text, join_ent = m.build()

    await send_msg(
        chat_id,
        join_text,
        join_ent,
        keyboard=build_keyboard([
            [btn(_t("btn_join_channel", lang), url=FORCE_JOIN_CHANNEL_LINK,    emoji_key="channel", style="success")],
            [btn(_t("btn_ive_joined",   lang), "check_join",                   emoji_key="check",   style="success")],
        ])
    )

async def forward_photo_to_admins(file_id: str, order_id: str,
                                   order: dict, user: dict):
    """Forward payment screenshot to all admins with approve/reject buttons."""
    uname   = user.get("username", "")
    fname   = user.get("first_name", "User")
    uid     = user.get("id", "")
    uname_str = f"@{uname}" if uname else f"ID:{uid}"
    network   = order.get("network", "")
    net_label = {"bep20": "USDT BEP20", "trx": "USDT TRC20", "btc": "Bitcoin (BTC)"}.get(network, "USDT")
    currency  = "BTC" if network == "btc" else "USDT"

    caption = (
        f"🔔 New Payment — Order #{order_id[:8].upper()}\n\n"
        f"👤 User: {fname} ({uname_str})\n"
        f"📋 Type: {'💳 Wallet Top Up' if order.get('order_type') == 'topup' else '🛒 Purchase'}\n"
        f"💳 Network: {net_label}\n"
        f"🛒 Product: {order['cat_name']}\n"
        f"💰 Amount: $ {order['price']:.2f} {currency}\n"
        f"🕐 Ordered: {order['created_at']}"
    )
    kb = build_keyboard([
        [
            btn("✅  Approve", f"approve_{order_id}", style="success"),
            btn("❌  Reject",  f"reject_{order_id}",  style="danger"),
        ]
    ])
    for admin_id in ADMINS:
        await api_call("sendPhoto", {
            "chat_id":      admin_id,
            "photo":        file_id,
            "caption":      caption,
            "reply_markup": kb,
        })

# ─── TEXT / ENTITY BUILDERS ───────────────────────────────────
def build_welcome(lang: str = "en"):
    m = Msg()
    m.emoji("wave").text(" ").bold(_t("welcome_title", lang)).nl(2)
    m.emoji("thunder").text(" ").bold(_t("welcome_desc", lang)).nl(2)
    m.emoji("shop").text("  ").bold(_t("welcome_browse", lang)).nl()
    m.emoji("wallet").text("  ").bold(_t("welcome_wallet", lang)).nl()
    m.emoji("profile").text("  ").bold(_t("welcome_profile", lang)).nl()
    m.emoji("referral").text("  ").bold(_t("welcome_referral", lang)).nl(2)
    m.emoji("down").text(" ").bold(_t("welcome_choose", lang))
    return m.build()

def build_shop(lang: str = "en", categories: dict = None, stock_counts: dict = None):
    m = Msg()
    m.emoji("shop").text(" ").bold(_t("shop_title", lang)).nl(2)
    m.emoji("thunder").text(" ").bold(_t("shop_subtitle", lang))
    return m.build()

def build_profile(user: dict, db_data: dict = None, lang: str = "en"):
    username = user.get("username")
    uid      = user.get("id", "")
    fname    = user.get("first_name", "User")
    uname_str = f"@{username}" if username else "N/A"

    balance         = db_data.get("balance", 0.0)        if db_data else 0.0
    total_spent     = db_data.get("total_spent", 0.0)    if db_data else 0.0
    products_bought = db_data.get("products_bought", 0)  if db_data else 0

    m = Msg()
    m.emoji("profile").text(" ").bold(_t("profile_title", lang, fname=fname)).nl(2)
    m.emoji("id").text("  ").bold(_t("profile_user_id", lang)).code(str(uid)).nl()
    m.emoji("share").text("  ").bold(_t("profile_username", lang)).bold(uname_str).nl(2)
    m.emoji("balance").text("  ").bold(_t("profile_balance", lang)).bold(f"$ {balance:.2f}").nl()
    m.emoji("thunder").text("  ").bold(_t("profile_total_spent", lang)).bold(f"$ {total_spent:.2f}").nl(2)
    m.emoji("cart").text("  ").bold(_t("profile_products_bought", lang)).bold(str(products_bought))
    return m.build()

def build_wallet(balance: float = 0.0, lang: str = "en"):
    m = Msg()
    m.emoji("wallet").text(" ").bold(_t("wallet_title", lang)).nl(2)
    m.emoji("balance").text("  ").bold(_t("wallet_balance", lang)).bold(f"$ {balance:.2f}").nl(2)
    m.emoji("thunder").text("  ").bold(_t("wallet_topup_prompt", lang)).nl(2)
    m.emoji("down").text(" ").bold(_t("wallet_choose_action", lang))
    return m.build()

def build_topup_prompt(balance: float = 0.0, lang: str = "en"):
    m = Msg()
    m.emoji("add").text(" ").bold(_t("topup_title", lang)).nl(2)
    m.emoji("balance").text("  ").bold(_t("wallet_balance", lang)).bold(f"$ {balance:.2f}").nl(2)
    m.bold(_t("topup_enter_amount", lang)).nl()
    m.bold(_t("topup_example", lang)).nl(2)
    m.emoji("timer").text(" ").bold(_t("topup_minimum", lang))
    return m.build()

def build_referral(link: str, lang: str = "en"):
    m = Msg()
    m.emoji("referral").text(" ").bold(_t("referral_title", lang)).nl(2)
    m.emoji("thunder").text(" ").bold(_t("referral_invite", lang)).nl(2)
    m.emoji("profile").text("  ").bold(_t("referral_count", lang)).bold("0").nl()
    m.emoji("wallet").text("  ").bold(_t("referral_earnings", lang)).bold("$ 0.00").nl(2)
    m.emoji("link").text(" ").bold(_t("referral_link", lang)).nl()
    m.code(link)
    return m.build()

def build_menu(lang: str = "en"):
    m = Msg()
    m.emoji("menu").text(" ").bold(_t("menu_title", lang)).nl(2)
    m.emoji("shop").text("  ").bold(_t("menu_shop", lang)).nl()
    m.emoji("profile").text("  ").bold(_t("menu_profile", lang)).nl()
    m.emoji("wallet").text("  ").bold(_t("menu_wallet", lang)).nl()
    m.emoji("referral").text("  ").bold(_t("menu_referral", lang)).nl(2)
    m.emoji("down").text(" ").bold(_t("menu_choose", lang))
    return m.build()

def build_ping(lang: str = "en"):
    m = Msg()
    m.emoji("thunder").text(" ").bold(_t("ping", lang)).emoji("check")
    return m.build()

def build_help(lang: str = "en"):
    m = Msg()
    m.emoji("cmd").text(" ").bold(_t("help_title", lang)).nl(2)

    m.emoji("thunder").text(" ").bold(_t("help_main_cmds", lang)).nl()
    m.emoji("home").text("  ").bold(_t("help_cmd_start", lang)).nl()
    m.emoji("shop").text("  ").bold(_t("help_cmd_shop", lang)).nl()
    m.emoji("profile").text("  ").bold(_t("help_cmd_profile", lang)).nl()
    m.emoji("wallet").text("  ").bold(_t("help_cmd_wallet", lang)).nl()
    m.emoji("add").text("  ").bold(_t("help_cmd_deposit", lang)).nl()
    m.emoji("referral").text("  ").bold(_t("help_cmd_referral", lang)).nl()
    m.emoji("menu").text("  ").bold(_t("help_cmd_menu", lang)).nl(2)

    m.emoji("cart").text(" ").bold(_t("help_other", lang)).nl()
    m.emoji("thunder").text("  ").bold(_t("help_cmd_ping", lang)).nl()
    m.emoji("support").text("  ").bold(_t("help_cmd_help", lang))
    return m.build()

def build_terms():
    """Build terms and conditions message with premium emoji for first point only."""
    m = Msg()
    m.text("📃 ").bold("Terms & Conditions").nl(2)
    m.bold("Welcome to AI Chat Store. By using our bot and services, you agree to the following terms:").nl(2)
    
    m.emoji("number1").text(" ").bold("Order Confirmation").nl()
    m.bold("Please check the product name, duration, price, and requirements before placing an order.").nl(2)
    
    m.emoji("number2").text(" ").bold("Payment").nl()
    m.bold("All payments must be completed using the payment methods shown in the bot. After payment, you must tap I've Paid or send payment proof/transaction ID.").nl(2)
    
    m.emoji("number3").text(" ").bold("Delivery Time").nl()
    m.bold("Delivery time depends on the product. Some products are instant, while others may take time for activation.").nl(2)
    
    m.emoji("number4").text(" ").bold("Correct Information").nl()
    m.bold("Customers must provide correct email, username, phone number, or account details when required. We are not responsible for delays or issues caused by incorrect information.").nl(2)
    
    m.emoji("check").text(" ").bold("Warranty").nl()
    m.bold("Warranty depends on the product. Some products include full warranty, some include activation warranty only, and some have no warranty after activation. Please read the product details before buying.").nl(2)
    
    m.emoji("moneybag").text(" ").bold("Refund Policy").nl()
    m.bold("Refunds are only available if the product cannot be delivered or activated. Refunds are not available after successful delivery/activation unless the product has warranty.").nl(2)
    
    m.emoji("key").text(" ").bold("Account Safety").nl()
    m.bold("Do not change passwords, emails, or account details during activation unless support tells you to do so.").nl(2)
    
    m.emoji("support").text(" ").bold("Support").nl()
    m.bold("If you face any issue, contact support with your order proof, payment proof, and problem details.").nl(2)
    
    m.emoji("box").text(" ").bold("Stock Availability").nl()
    m.bold("Products may go out of stock at any time. If a product is unavailable, you can wait for restock or choose another product.").nl(2)
    
    m.emoji("moneybag").text(" ").bold("By placing an order, you confirm that you have read and accepted these terms.")
    
    text, entities = m.build()
    return text, entities


# ─── MULTI-LANGUAGE TERMS ─────────────────────────────────────
_TERMS_LANG = {
    "en": {
        "flag": "🇬🇧", "name": "English",
        "title": "📃 Terms & Conditions",
        "intro": "Welcome to AI Chat Store. By using our bot and services, you agree to the following terms:",
        "points": [
            ("Order Confirmation",  "Please check the product name, duration, price, and requirements before placing an order."),
            ("Payment",             "All payments must be completed using the payment methods shown in the bot. After payment, tap I've Paid or send payment proof/transaction ID."),
            ("Delivery Time",       "Delivery time depends on the product. Some products are instant, while others may take time for activation."),
            ("Correct Information", "Customers must provide correct email, username, phone number, or account details. We are not responsible for delays caused by incorrect information."),
            ("Warranty",            "Warranty depends on the product. Some include full warranty, some activation-only warranty, and some have no warranty after activation. Read product details before buying."),
            ("Refund Policy",       "Refunds are only available if the product cannot be delivered or activated. No refunds after successful delivery/activation unless covered by warranty."),
            ("Account Safety",      "Do not change passwords, emails, or account details during activation unless support tells you to do so."),
            ("Support",             "If you face any issue, contact support with your order proof, payment proof, and problem details."),
            ("Stock Availability",  "Products may go out of stock at any time. If unavailable, you can wait for restock or choose another product."),
        ],
        "footer": "By placing an order, you confirm that you have read and accepted these terms.",
        "agree": "I Agree",
        "decline": "Decline",
    },
    "zh": {
        "flag": "🇨🇳", "name": "中文",
        "title": "📃 服务条款",
        "intro": "欢迎使用 AI Chat Store。使用本机器人即表示您同意以下条款：",
        "points": [
            ("确认订单",   "下单前请确认产品名称、有效期、价格和相关要求。"),
            ("付款",       "所有付款必须通过机器人中显示的方式完成。付款后，请点击'已付款'或发送付款凭证/交易ID。"),
            ("交货时间",   "交货时间视产品而定。部分产品即时发货，其他可能需要时间激活。"),
            ("正确信息",   "客户必须提供正确的电子邮件、用户名、电话号码或账户信息。因信息有误造成的延误我们概不负责。"),
            ("质保",       "质保条款视产品而定。有些提供完整质保，有些仅限激活质保，有些激活后无质保。购买前请阅读产品详情。"),
            ("退款政策",   "仅当产品无法交付或激活时才可退款。成功交付/激活后不予退款（质保产品除外）。"),
            ("账户安全",   "除非客服告知，否则激活期间请勿更改密码、电子邮件或账户信息。"),
            ("客户支持",   "如遇问题，请携带订单凭证、付款凭证及问题描述联系客服。"),
            ("库存情况",   "产品可能随时缺货。如产品不可用，您可等待补货或选择其他产品。"),
        ],
        "footer": "下单即表示您已阅读并同意以上条款。",
        "agree": "我同意",
        "decline": "拒绝",
    },
    "ru": {
        "flag": "🇷🇺", "name": "Русский",
        "title": "📃 Условия использования",
        "intro": "Добро пожаловать в AI Chat Store. Используя наш бот, вы соглашаетесь со следующими условиями:",
        "points": [
            ("Подтверждение заказа",  "Перед оформлением заказа проверьте название продукта, срок, цену и требования."),
            ("Оплата",                "Все платежи должны быть выполнены способами, указанными в боте. После оплаты нажмите «Я оплатил» или отправьте подтверждение платежа / ID транзакции."),
            ("Время доставки",        "Время доставки зависит от продукта. Некоторые товары доставляются мгновенно, другие могут требовать времени для активации."),
            ("Правильные данные",     "Клиент обязан указать верный email, имя пользователя, номер телефона или данные аккаунта. Мы не несём ответственности за задержки из-за неверных данных."),
            ("Гарантия",              "Гарантия зависит от продукта: полная, только на активацию или отсутствует. Ознакомьтесь с описанием перед покупкой."),
            ("Политика возврата",     "Возврат возможен только если товар не удалось доставить или активировать. После успешной доставки/активации возврат не производится (если нет гарантии)."),
            ("Безопасность аккаунта", "Не меняйте пароль, email или данные аккаунта во время активации без указания службы поддержки."),
            ("Поддержка",             "При возникновении проблем обращайтесь в поддержку с подтверждением заказа, оплаты и описанием проблемы."),
            ("Наличие товара",        "Товары могут закончиться в любой момент. Если товар недоступен — ожидайте пополнения или выберите другой."),
        ],
        "footer": "Оформляя заказ, вы подтверждаете, что прочитали и приняли настоящие условия.",
        "agree": "Согласен",
        "decline": "Отклонить",
    },
    "vi": {
        "flag": "🇻🇳", "name": "Tiếng Việt",
        "title": "📃 Điều Khoản Dịch Vụ",
        "intro": "Chào mừng đến với AI Chat Store. Khi sử dụng bot, bạn đồng ý với các điều khoản sau:",
        "points": [
            ("Xác nhận đơn hàng",  "Vui lòng kiểm tra tên sản phẩm, thời hạn, giá cả và yêu cầu trước khi đặt hàng."),
            ("Thanh toán",         "Tất cả thanh toán phải được thực hiện qua các phương thức hiển thị trong bot. Sau khi thanh toán, nhấn 'Đã thanh toán' hoặc gửi bằng chứng giao dịch."),
            ("Thời gian giao hàng","Thời gian giao hàng tùy thuộc vào sản phẩm. Một số sản phẩm giao ngay, một số cần thời gian kích hoạt."),
            ("Thông tin chính xác","Khách hàng phải cung cấp đúng email, tên người dùng, số điện thoại hoặc thông tin tài khoản. Chúng tôi không chịu trách nhiệm về sự chậm trễ do thông tin sai."),
            ("Bảo hành",           "Bảo hành tùy thuộc vào sản phẩm: bảo hành đầy đủ, bảo hành kích hoạt hoặc không bảo hành. Đọc chi tiết sản phẩm trước khi mua."),
            ("Chính sách hoàn tiền","Chỉ hoàn tiền khi không thể giao hàng hoặc kích hoạt. Không hoàn tiền sau khi giao hàng/kích hoạt thành công (trừ sản phẩm có bảo hành)."),
            ("Bảo mật tài khoản",  "Không thay đổi mật khẩu, email hoặc thông tin tài khoản trong quá trình kích hoạt trừ khi bộ phận hỗ trợ yêu cầu."),
            ("Hỗ trợ",             "Nếu gặp sự cố, liên hệ hỗ trợ với bằng chứng đơn hàng, thanh toán và mô tả vấn đề."),
            ("Tình trạng kho hàng","Sản phẩm có thể hết hàng bất cứ lúc nào. Nếu không có hàng, bạn có thể chờ nhập thêm hoặc chọn sản phẩm khác."),
        ],
        "footer": "Khi đặt hàng, bạn xác nhận đã đọc và chấp nhận các điều khoản này.",
        "agree": "Tôi đồng ý",
        "decline": "Từ chối",
    },
}

_NUM_EMOJIS = ["number1", "number2", "number3", "number4",
               "check", "moneybag", "key", "support", "box"]

def build_language_select() -> tuple:
    """Build the language selection message — always in all languages."""
    m = Msg()
    m.emoji("wave").text(" ").bold(_t("lang_select_title", "en")).nl(2)
    m.emoji("globe").text(" ").bold(_t("lang_select_subtitle", "en"))
    return m.build()

def build_terms_lang(lang: str) -> tuple:
    """Build Terms & Conditions in the given language."""
    t = _TERMS_LANG.get(lang, _TERMS_LANG["en"])
    m = Msg()
    m.text(t["title"]).nl(2)
    m.bold(t["intro"]).nl(2)
    for i, (heading, body) in enumerate(t["points"]):
        emoji_key = _NUM_EMOJIS[i] if i < len(_NUM_EMOJIS) else "check"
        m.emoji(emoji_key).text(" ").bold(heading).nl()
        m.bold(body).nl(2)
    m.emoji("moneybag").text(" ").bold(t["footer"])
    return m.build()

def kb_lang_select() -> dict:
    """Keyboard for language selection."""
    return build_keyboard([
        [btn("🇬🇧  English",      "lang_select_en", style="success"),
         btn("🇨🇳  中文",         "lang_select_zh", style="success")],
        [btn("🇷🇺  Русский",      "lang_select_ru", style="success"),
         btn("🇻🇳  Tiếng Việt",   "lang_select_vi", style="success")],
    ])

def kb_terms_accept(lang: str) -> dict:
    """Keyboard for accepting/declining terms in chosen language."""
    t = _TERMS_LANG.get(lang, _TERMS_LANG["en"])
    return build_keyboard([
        [btn(t["agree"],   f"accept_terms_{lang}", emoji_key="check",  style="success")],
        [btn(t["decline"],  "decline_terms",        emoji_key="cross")],
    ])

def build_test():
    m = Msg()
    m.emoji("diamond").text(" ").bold("Premium Emoji Test").nl(2)
    m.emoji("check").text(" Button icons use ").bold("icon_custom_emoji_id").text(" — check the keyboards above.")
    return m.build()

def inject_stock_count(description: str, count: int) -> str:
    """Replace stock placeholder patterns in description with real count.
    Supports: ××, xx, XX, {{stock}}, {stock}
    For dm_activation (count=999) shows 'Available ✅' instead of 999.
    """
    display = "Available ✅" if count >= 999 else str(count)
    for placeholder in ("××", "xx", "XX", "{{stock}}", "{stock}"):
        description = description.replace(placeholder, display)
    return description

def get_bulk_price(base_price: float, qty: int) -> float:
    """No bulk discount — price is always fixed per unit."""
    return base_price

def build_qty_selector_msg(cat: dict, qty: int, stock: int, lang: str = "en") -> tuple:
    """Build the quantity selector message (shown before checkout)."""
    base_price = cat["price"]
    total      = round(base_price * qty, 2)
    cat_name   = cat["name"]

    m = Msg()
    m.text(f"{cat.get('emoji_char','🛒')} ").bold(cat_name).nl(2)
    m.emoji("balance").text("  ").bold(_t("qty_price_each", lang)).bold(f"${base_price:.2f} each").nl()
    m.emoji("box").text("  ").bold(_t("qty_in_stock", lang)).bold(
        "∞" if stock >= 999 else str(stock)).nl(2)

    m.emoji("clipboard").text("  ").bold(_t("qty_selected", lang)).bold(str(qty)).nl()
    m.emoji("thunder").text("  ").bold(_t("qty_total", lang)).bold(f"${total:.2f} USDT")
    return m.build()

def build_qty_keyboard(cat_id: str, qty: int, stock: int, unit_price: float, total: float, lang: str = "en") -> dict:
    """Inline keyboard for quantity selector."""
    can_dec = qty > 1
    can_inc = qty < stock or stock >= 999

    rows = [
        [
            btn(" ",  f"qty_dec_{cat_id}" if can_dec else "noop",
                emoji_key="minus",
                style="danger"),
            btn(str(qty), "noop"),
            btn(" ", f"qty_inc_{cat_id}" if can_inc else "noop",
                emoji_key="plus",
                style="success" if can_inc else "danger"),
        ],
        [btn(_t("btn_custom_quantity", lang), f"qty_custom_{cat_id}", emoji_key="pencil", style="success")],
        [btn(f"{_t('btn_buy_now', lang)} · ${total:.2f}", f"qty_buy_{cat_id}", emoji_key="cart", style="success")],
        [btn(_t("btn_back", lang), f"cat_{cat_id}", emoji_key="back")],
    ]
    return build_keyboard(rows)

def build_payment_caption(title: str, amount: float, product_name: str = None,
                          network: str = "bep20", lang: str = "en") -> tuple:
    """Load payment info from payments.json and build caption."""
    pay = get_payment(network)
    if not pay:
        pay = {"label": "USDT", "network": "Unknown", "address": "N/A"}
    net_name  = pay["network"]
    address   = pay.get("address", "N/A")

    is_btc = (network == "btc")
    currency_str = "BTC" if is_btc else "USDT"

    m = Msg()
    if product_name:
        m.emoji("check").text(" ").bold(title).nl(2)
        m.emoji("cart").text(" ").bold(_t("order_product", lang)).bold(product_name).nl()
        m.emoji("balance").text(" ").bold(_t("topup_amount_label", lang)).bold(f"$ {amount:.2f} {currency_str}").nl()
    else:
        m.emoji("balance").text(" ").bold(title).nl(2)
        m.emoji("balance").text(" ").bold(_t("topup_amount_label", lang)).bold(f"$ {amount:.2f} {currency_str}").nl()
    m.emoji("usdt").text(" ").bold(_t("pay_caption_network", lang)).bold(net_name).nl(2)
    m.emoji("thunder").text(" ").bold(_t("pay_caption_send", lang, amount=amount, currency=currency_str)).nl()
    m.emoji("mobile").text(" ").bold(_t("pay_caption_address", lang)).code(address).nl(2)
    m.emoji("instructions").text(" ").bold(_t("pay_caption_instructions", lang)).nl()
    m.emoji("number1").text(" ").bold(_t("pay_caption_step1", lang, network=net_name)).nl()
    m.emoji("number2").text(" ").bold(_t("pay_caption_step2", lang)).nl()
    m.emoji("number3").text(" ").bold(_t("pay_caption_step3", lang)).nl()
    if is_btc:
        m.emoji("number4").text(" ").bold(_t("pay_caption_step4_btc", lang)).nl(2)
    else:
        m.emoji("number4").text(" ").bold(_t("pay_caption_step4", lang)).nl(2)
    m.emoji("timer").text(" ").bold(_t("pay_caption_expiry", lang, minutes=ORDER_EXPIRY_MINUTES))
    return m.build()
# ─── BEP20 PAYMENT VERIFICATION FUNCTIONS ────────────────────
#
# Two verification paths are available:
#   1. Web3 / direct RPC  — reads BSC chain directly via public nodes.
#      No API key needed. Requires:  pip install web3
#   2. BSCScan HTTP API   — fallback when web3 is not installed.
#      Needs a free API key from https://bscscan.com/myapikey
#
# The bot always tries Web3 first. If web3 is not installed, or if all
# RPC nodes fail, it automatically falls back to BSCScan.
# ─────────────────────────────────────────────────────────────

def _load_used_txns() -> set:
    """Load set of already-used txn hashes from disk."""
    if not os.path.exists(USED_TXN_PATH):
        return set()
    with open(USED_TXN_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))

def _save_used_txns(txns: set):
    with open(USED_TXN_PATH, "w", encoding="utf-8") as f:
        json.dump(list(txns), f, indent=2)

def _mark_txn_used(txn_hash: str):
    txns = _load_used_txns()
    txns.add(txn_hash.lower())
    _save_used_txns(txns)

def _is_txn_used(txn_hash: str) -> bool:
    return txn_hash.lower() in _load_used_txns()

# ── Web3 helpers (only used when web3 library is installed) ──

def _get_web3():
    """
    Return a connected Web3 instance by trying each public BSC RPC node
    in order. Raises ConnectionError if none respond.
    """
    if not _WEB3_AVAILABLE:
        raise ImportError("web3 not installed")
    for rpc in BSC_RPC_ENDPOINTS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            if w3.is_connected():
                logger.info(f"[web3] connected via {rpc}")
                return w3
        except Exception as e:
            logger.warning(f"[web3] RPC {rpc} failed: {e}")
    raise ConnectionError("All BSC RPC nodes unreachable.")


def _web3_verify_token(w3, tx_hash: str, expected_to: str,
                        expected_amount: float) -> dict:
    """
    Verify a BEP20 token transfer (USDT / BUSD) directly from the chain
    by reading the transaction receipt logs.

    Returns the same dict shape as verify_bep20_txn():
        { "ok": True,  "amount": 9.99, "from": "0x..." }
        { "ok": False, "reason": "..." }
    """
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception as e:
        err = str(e).lower()
        if "not found" in err:
            return {
                "ok": False,
                "reason": (
                    "Transaction not found on BSC. Possible reasons:\n"
                    "1. Hash is wrong (missing/extra character)\n"
                    "2. Transaction is still pending — wait a moment and try again\n"
                    "3. Payment was sent on a different network (e.g. Ethereum, TRON)"
                ),
            }
        return {"ok": False, "reason": f"Chain lookup error: {e}"}

    if receipt is None:
        return {"ok": False, "reason": "Transaction is still pending. Wait for confirmation and try again."}

    if receipt.status != 1:
        return {"ok": False, "reason": "Transaction failed on-chain. Cannot accept a failed transaction."}

    # Confirm enough block confirmations
    try:
        confirmations = w3.eth.block_number - receipt.blockNumber
        if confirmations < MIN_CONFIRMATIONS:
            return {
                "ok": False,
                "reason": (
                    f"Only {confirmations} confirmation(s) so far "
                    f"(need {MIN_CONFIRMATIONS}). Please wait a bit and try again."
                ),
            }
    except Exception:
        pass  # Non-fatal — block number check is best-effort

    # Normalize topic to plain hex string without 0x prefix
    def to_hex(t) -> str:
        if isinstance(t, (bytes, bytearray)):
            return t.hex()
        s = str(t)
        return s[2:] if s.startswith("0x") else s

    # Debug: log all contract addresses found in this tx
    log_contracts = [log.address.lower() for log in receipt.logs]
    logger.info(f"[verify] tx has {len(receipt.logs)} logs, contracts: {log_contracts}")
    logger.info(f"[verify] expected_to={expected_to.lower()}")
    for tk, ti in BEP20_TOKENS.items():
        logger.info(f"[verify] checking {tk} contract={ti['contract'].lower()}")

    # Scan logs for a matching Transfer(from, to, value) event
    for log in receipt.logs:
        for token_name, info in BEP20_TOKENS.items():
            if log.address.lower() != info["contract"].lower():
                continue
            topics = log.topics
            if len(topics) < 3:
                continue

            # topics[0] = Transfer event signature
            topic0 = "0x" + to_hex(topics[0])
            if topic0.lower() != _TRANSFER_TOPIC.lower():
                logger.info(f"[verify] topic0 mismatch: {topic0}")
                continue

            # topics[2] = padded recipient address (last 40 hex chars = 20 bytes)
            to_addr = "0x" + to_hex(topics[2])[-40:]
            logger.info(f"[verify] to_addr={to_addr.lower()} expected={expected_to.lower()}")
            if to_addr.lower() != expected_to.lower():
                logger.info(f"[verify] to_addr mismatch — skipping")
                continue

            # log.data = ABI-encoded uint256 amount (32 bytes = 64 hex chars)
            raw_data = log.data
            if isinstance(raw_data, (bytes, bytearray)):
                raw_hex = raw_data.hex()
            else:
                raw_hex = str(raw_data)
                if raw_hex.startswith("0x"):
                    raw_hex = raw_hex[2:]
            raw_value = int(raw_hex, 16) if raw_hex else 0

            amount = raw_value / (10 ** info["decimals"])
            logger.info(f"[verify] amount={amount} expected={expected_amount}")

            # Allow ±1% tolerance for rounding
            tolerance = max(0.01, expected_amount * 0.01)
            if amount < (expected_amount - tolerance):
                return {
                    "ok": False,
                    "reason": (
                        f"Amount mismatch.\n"
                        f"Expected: ${expected_amount:.2f} USDT\n"
                        f"Received: ${amount:.4f} {token_name}"
                    ),
                }

            # topics[1] = padded sender address
            sender = "0x" + to_hex(topics[1])[-40:]
            return {"ok": True, "amount": amount, "from": sender, "token": token_name}

    return {
        "ok": False,
        "reason": (
            "No matching USDT/BEP20 transfer to our address found in this transaction."
        ),
    }


def _web3_verify_bnb(w3, tx_hash: str, expected_to: str,
                      expected_amount: float) -> dict:
    """
    Verify a native BNB transfer directly from the chain.
    Used as a secondary fallback inside _web3_verify_any().
    """
    try:
        tx      = w3.eth.get_transaction(tx_hash)
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception as e:
        return {"ok": False, "reason": f"Chain lookup error: {e}"}

    if receipt.status != 1:
        return {"ok": False, "reason": "Transaction failed on-chain."}

    to_addr = tx.get("to") or ""
    if to_addr.lower() != expected_to.lower():
        return {"ok": False, "reason": "This transaction was sent to a different address."}

    amount = float(w3.from_wei(tx["value"], "ether"))
    tolerance = max(0.001, expected_amount * 0.01)
    if amount < (expected_amount - tolerance):
        return {
            "ok": False,
            "reason": f"Amount mismatch. Expected {expected_amount:.4f} BNB, got {amount:.4f} BNB.",
        }

    return {"ok": True, "amount": amount, "from": tx.get("from", "unknown"), "token": "BNB"}


def _web3_verify_any(tx_hash: str, expected_to: str,
                      expected_amount: float) -> dict:
    """
    Attempt to verify a BEP20 token transfer, then fall back to native BNB.
    Tries all public RPC nodes before giving up.
    Returns the same dict shape as verify_bep20_txn().
    """
    try:
        w3 = _get_web3()
    except (ImportError, ConnectionError) as e:
        return {"ok": False, "reason": str(e)}

    # Try token transfer first (USDT / BUSD)
    result = _web3_verify_token(w3, tx_hash, expected_to, expected_amount)
    if result.get("ok"):
        return result

    # Fall back to native BNB
    bnb_result = _web3_verify_bnb(w3, tx_hash, expected_to, expected_amount)
    if bnb_result.get("ok"):
        return bnb_result

    # Return the token result's error (usually more informative)
    return result


# ── BSCScan fallback (HTTP API) ───────────────────────────────

async def _bscscan_verify(txn_hash: str, expected_to: str,
                           expected_amount: float) -> dict:
    """
    Verify a BEP20 USDT transaction via the BSCScan free HTTP API.
    Used as a fallback when web3 is not available.
    """
    bsc_url = "https://api.bscscan.com/api"
    params_tx = {
        "module": "proxy",
        "action": "eth_getTransactionByHash",
        "txhash": txn_hash,
        "apikey": BSCSCAN_API_KEY,
    }
    params_receipt = {
        "module": "proxy",
        "action": "eth_getTransactionReceipt",
        "txhash": txn_hash,
        "apikey": BSCSCAN_API_KEY,
    }

    try:
        session = await get_session()
        # Fire both requests in parallel
        async with session.get(bsc_url, params=params_tx,
                               timeout=aiohttp.ClientTimeout(total=15)) as r1, \
                   session.get(bsc_url, params=params_receipt,
                               timeout=aiohttp.ClientTimeout(total=15)) as r2:
            tx_data      = await r1.json()
            receipt_data = await r2.json()
    except Exception as ex:
        logger.error(f"[bscscan] request failed: {ex}")
        return {"ok": False, "reason": "Could not reach BSCScan. Please try again in a moment."}

    tx      = tx_data.get("result")
    receipt = receipt_data.get("result")

    if not tx or tx in (None, "0x0"):
        return {"ok": False, "reason": "Transaction not found on BSC. Double-check the hash."}

    if not receipt:
        return {"ok": False, "reason": "Transaction is still pending. Wait for confirmation and try again."}

    if receipt.get("status", "0x0") != "0x1":
        return {"ok": False, "reason": "Transaction failed on-chain (status = failed). Cannot accept."}

    # Confirm it is a call to the USDT BEP20 contract
    to_contract = (tx.get("to") or "").lower()
    if to_contract != USDT_BEP20_CONTRACT.lower():
        return {"ok": False, "reason": "This is not a USDT BEP20 transaction."}

    # Decode ERC-20 transfer(address,uint256) input:
    #   method id: 0xa9059cbb  (4 bytes = 8 hex chars)
    #   recipient: 32 bytes (64 hex chars), address is in last 40 chars
    #   amount:    32 bytes (64 hex chars)
    input_data = tx.get("input", "")
    if not input_data.startswith("0xa9059cbb"):
        return {"ok": False, "reason": "This is not a USDT transfer transaction."}

    try:
        payload     = input_data[10:]          # strip 0x + method id
        recv_hex    = payload[:64]
        amount_hex  = payload[64:128]
        recipient   = "0x" + recv_hex[-40:]
        usdt_amount = int(amount_hex, 16) / (10 ** 18)
    except Exception as ex:
        logger.error(f"[bscscan] decode error: {ex}")
        return {"ok": False, "reason": "Could not decode the transaction data. Please contact support."}

    if recipient.lower() != expected_to.lower():
        return {
            "ok": False,
            "reason": (
                f"Payment was sent to the wrong address.\n"
                f"Expected: `{expected_to[:6]}...{expected_to[-4:]}`\n"
                f"Received: `{recipient[:6]}...{recipient[-4:]}`"
            ),
        }

    tolerance = max(0.01, expected_amount * 0.01)
    if usdt_amount < (expected_amount - tolerance):
        return {
            "ok": False,
            "reason": (
                f"Amount mismatch.\n"
                f"Expected: ${expected_amount:.2f} USDT\n"
                f"Received: ${usdt_amount:.4f} USDT"
            ),
        }

    return {"ok": True, "amount": usdt_amount, "from": tx.get("from", "unknown")}


# ── Main entry point called by the bot ───────────────────────

async def verify_bep20_txn(txn_hash: str, expected_to: str,
                            expected_amount: float) -> dict:
    """
    Verify a BEP20 USDT payment. Automatically chooses the best method:

      1. Web3 direct RPC  — fastest, no API key, works offline from BSCScan.
         Requires: pip install web3
      2. BSCScan HTTP API — fallback if web3 is not installed or RPC nodes
         are unreachable. Needs BSCSCAN_API_KEY to be set.

    Returns:
        { "ok": True,  "amount": 9.99, "from": "0x...", "token": "USDT" }
        { "ok": False, "reason": "human-readable error" }
    """
    txn_hash = txn_hash.strip()

    # ── Format validation ─────────────────────────────────────
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", txn_hash):
        return {
            "ok": False,
            "reason": (
                "Invalid transaction hash format.\n"
                "A valid hash starts with 0x followed by exactly 64 hex characters (total 66 chars).\n"
                "Please copy the hash directly from BscScan and try again."
            ),
        }

    # ── Double-spend guard ────────────────────────────────────
    if _is_txn_used(txn_hash):
        return {"ok": False, "reason": "This transaction hash has already been used for another order."}

    # ── Try Web3 direct RPC first ─────────────────────────────
    if _WEB3_AVAILABLE:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                _web3_verify_any,
                txn_hash, expected_to, expected_amount
            )
            if result.get("ok"):
                logger.info(f"[verify] Web3 path succeeded for {txn_hash[:12]}…")
                return result
            # If the error looks like a connectivity issue, fall through to BSCScan
            reason = result.get("reason", "")
            if "unreachable" in reason.lower() or "rpc" in reason.lower():
                logger.warning(f"[verify] Web3 RPC failed, trying BSCScan fallback: {reason}")
            else:
                # Definitive failure (wrong address, amount, etc.) — no need to try BSCScan
                return result
        except Exception as ex:
            logger.warning(f"[verify] Web3 path raised exception, trying BSCScan: {ex}")

    # ── Fallback: BSCScan HTTP API ────────────────────────────
    logger.info(f"[verify] Using BSCScan fallback for {txn_hash[:12]}…")
    return await _bscscan_verify(txn_hash, expected_to, expected_amount)


# ─── TRC20 PAYMENT VERIFICATION ──────────────────────────────
# Uses TronScan public API — no API key needed.
# Verifies USDT TRC20 transfers on the TRON network.
# ─────────────────────────────────────────────────────────────

async def verify_trc20_txn(txn_hash: str, expected_to: str,
                            expected_amount: float) -> dict:
    """
    Verify a TRC20 USDT payment via TronScan public API.
    No API key required.

    Returns:
        { "ok": True,  "amount": 9.99, "from": "T...", "token": "USDT" }
        { "ok": False, "reason": "human-readable error" }
    """
    txn_hash = txn_hash.strip()

    # ── Format validation ─────────────────────────────────────
    # TRON txn hashes are 64 hex characters (no 0x prefix)
    clean = txn_hash[2:] if txn_hash.startswith("0x") else txn_hash
    if not re.fullmatch(r"[0-9a-fA-F]{64}", clean):
        return {
            "ok": False,
            "reason": (
                "Invalid TRON transaction hash format.\n"
                "A valid TRC20 hash is 64 hex characters (no 0x prefix needed).\n"
                "Please copy the TxID directly from TronScan and try again."
            ),
        }
    # Normalize: use lowercase for TronScan API
    txn_hash = clean.lower()

    # ── Double-spend guard ────────────────────────────────────
    if _is_txn_used(txn_hash):
        return {"ok": False, "reason": "This transaction hash has already been used for another order."}

    # ── Query TronScan API ────────────────────────────────────
    try:
        session = await get_session()
        # Build URL directly — avoids any encoding issues with hash
        url = f"{TRONSCAN_API_URL}/transaction-info?hash={txn_hash}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return {"ok": False, "reason": f"TronScan returned HTTP {resp.status}. Try again later."}
            data = await resp.json(content_type=None)
    except Exception as ex:
        logger.error(f"[trc20] TronScan request failed: {ex}")
        return {"ok": False, "reason": "Could not reach TronScan. Please try again in a moment."}

    # ── Check transaction exists ──────────────────────────────
    if not data or data.get("hash") is None:
        return {
            "ok": False,
            "reason": (
                "Transaction not found on TRON network. Possible reasons:\n"
                "1. Hash is incorrect (missing/extra character)\n"
                "2. Transaction is still pending — wait a moment and try again\n"
                "3. Payment was sent on a different network (BSC/ETH), not TRON"
            ),
        }

    # ── Check confirmation status ─────────────────────────────
    # Note: older confirmed txns may show confirmed=False after block pruning
    # We rely on contractRet=SUCCESS as the primary confirmation signal
    contract_ret = data.get("contractRet", "")
    if contract_ret != "SUCCESS":
        confirmed = data.get("confirmed", False)
        if not confirmed and not contract_ret:
            return {
                "ok": False,
                "reason": "Transaction is not confirmed yet. Wait a moment and try again.",
            }
        return {
            "ok": False,
            "reason": f"Transaction failed on TRON network (status: {contract_ret}). Cannot accept.",
        }

    # ── Look for USDT TRC20 transfer in trc20TransferInfo ─────
    trc20_transfers = data.get("trc20TransferInfo") or data.get("trc20_transfer_info") or []

    for transfer in trc20_transfers:
        contract_addr = transfer.get("contract_address", "")
        if contract_addr.upper() != USDT_TRC20_CONTRACT.upper():
            continue  # Not USDT

        to_addr = transfer.get("to_address", "")
        if to_addr.upper() != expected_to.upper():
            continue  # Sent to different address

        # Amount: TRC20 USDT has 6 decimals on TRON (also confirmed from API response)
        try:
            decimals = int(transfer.get("decimals", 6))
            raw_amount = int(transfer.get("amount_str", transfer.get("amount", "0")))
            amount = raw_amount / (10 ** decimals)
        except (ValueError, TypeError):
            continue

        # Allow ±1% tolerance for rounding
        tolerance = max(0.01, expected_amount * 0.01)
        if amount < (expected_amount - tolerance):
            return {
                "ok": False,
                "reason": (
                    f"Amount mismatch.\n"
                    f"Expected: ${expected_amount:.2f} USDT\n"
                    f"Received: ${amount:.4f} USDT (TRC20)"
                ),
            }

        from_addr = transfer.get("from_address", "unknown")
        return {"ok": True, "amount": amount, "from": from_addr, "token": "USDT (TRC20)"}

    # ── If no TRC20 transfer found, check if it's a plain TRX transfer ──
    # (user may have sent native TRX instead of USDT)
    owner_addr = data.get("ownerAddress", "")
    to_addr    = data.get("toAddress", "")
    if to_addr.upper() == expected_to.upper():
        return {
            "ok": False,
            "reason": (
                "You sent TRX (native coin), but we accept USDT TRC20 only.\n"
                "Please send USDT on the TRON network, not TRX."
            ),
        }

    return {
        "ok": False,
        "reason": "No USDT TRC20 transfer to our address found in this transaction.",
    }


def build_add_balance():
    m = Msg()
    m.emoji("add").text(" ").bold("Add Balance").nl(2)
    m.emoji("soon").text(" Payment options coming soon!").nl(2)
    m.emoji("support").text(" Please contact support to add balance.")
    return m.build()

async def post_sale_log(cat_name: str, price: float, order_type: str = "purchase",
                       user: dict = None, quantity: int = 1):
    """Send a premium-styled sale/topup notification to the log channel."""
    if not LOG_CHANNEL_ID:
        return
    try:
        bot_username = await get_bot_username()
        bot_link     = f"https://t.me/{bot_username}"
        now          = datetime.now().strftime("%d %b %Y  •  %H:%M")

        # ── Obfuscate username for privacy (like the reference image "**") ──
        uname = ""
        if user:
            raw = user.get("username") or user.get("first_name") or ""
            if raw:
                # Show first char + stars, e.g. "A***"
                uname = raw[0] + "*" * min(len(raw) - 1, 3)
            uid = user.get("id", "")
        else:
            uname = "**"
            uid   = ""

        m = Msg()
        if order_type == "topup":
            # ─── Wallet Top-Up log ───────────────────────────────────────
            m.emoji("balance").text(" ").bold("New Top Up!").nl(2)
            m.emoji("user").text("  ").bold("User: ").text(uname).nl()
            m.emoji("moneybag").text("  ").bold("Amount: ").text(f"$ {price:.2f} USDT").nl()
            m.emoji("clock").text("  ").italic(now).nl(2)
            m.italic("Thank you for choosing us ").emoji("check")
        elif order_type == "freebie":
            # ─── Freebie claim log ───────────────────────────────────────
            m.emoji("gift").text(" ").bold("Freebie Claimed!").nl(2)
            m.emoji("user").text("  ").bold("User: ").text(uname).nl()
            m.emoji("box").text("  ").bold("Product: ").text(cat_name).nl()
            m.emoji("clipboard").text("  ").bold("QTY: ").text(str(quantity)).nl()
            m.emoji("clock").text("  ").italic(now).nl(2)
            m.italic("Free claim ").emoji("check")
        else:
            # ─── Purchase log ────────────────────────────────────────────
            m.emoji("cart").text(" ").bold("New Purchase!").nl(2)
            m.emoji("user").text("  ").bold("User: ").text(uname).nl()
            m.emoji("box").text("  ").bold("Product: ").text(cat_name).nl()
            m.emoji("moneybag").text("  ").bold("QTY: ").text(str(quantity)).nl(2)
            m.italic("Thank you for choosing us ").emoji("check")

        text, entities = m.build()

        # ── "Buy now" button (only for purchases) ────────────────────────
        kb = build_keyboard([
            [btn("🛒  Buy now", url=bot_link, style="success")]
        ]) if order_type != "topup" else None

        await api_call("sendMessage", {
            "chat_id":                  LOG_CHANNEL_ID,
            "text":                     text,
            "entities":                 entities,
            "disable_web_page_preview": True,
            **({"reply_markup": kb} if kb else {}),
        })
    except Exception as ex:
        logger.warning(f"[sale_log] Failed to post sale log: {ex}")

async def post_stock_log(cat_name: str, quantity: int, cat_id: str):
    """Send a premium-styled stock addition notification to the log channel."""
    if not LOG_CHANNEL_ID:
        return
    try:
        bot_username = await get_bot_username()
        bot_link     = f"https://t.me/{bot_username}"

        # Get current stock for "Current stock" field
        current = await stock_get_count(cat_id)

        m = Msg()
        m.emoji("thunder").text(" ").bold(cat_name).nl(2)
        m.emoji("add").text("  ").bold("Added: ").text(str(quantity)).nl()
        m.emoji("box").text("  ").bold("Current stock: ").text(str(current))

        text, entities = m.build()

        kb = build_keyboard([
            [btn("🛒  Buy now", url=bot_link, style="success")]
        ])

        await api_call("sendMessage", {
            "chat_id":                  LOG_CHANNEL_ID,
            "text":                     text,
            "entities":                 entities,
            "disable_web_page_preview": True,
            "reply_markup":             kb,
        })
    except Exception as ex:
        logger.warning(f"[stock_log] Failed to post stock log: {ex}")


async def post_category_log(cat_name: str, price: float, cat_type: str):
    """Send a premium-styled notification when a new category is added."""
    if not LOG_CHANNEL_ID:
        return
    try:
        bot_username = await get_bot_username()
        bot_link     = f"https://t.me/{bot_username}"
        now          = datetime.now().strftime("%d %b %Y  •  %H:%M")
        type_label   = "🔗 Link" if cat_type == "link" else "🔐 ID & Pass"

        m = Msg()
        m.emoji("pop").text(" ").bold("New Category Added!").nl(2)
        m.emoji("bag").text("  ").bold("Name: ").text(cat_name).nl()
        m.emoji("moneybag").text("  ").bold("Price: ").text(f"$ {price:.2f} USDT").nl()
        m.emoji("box").text("  ").bold("Type: ").text(type_label).nl(2)
        m.emoji("clock").text("  ").italic(now)

        text, entities = m.build()

        kb = build_keyboard([
            [btn("🛒  Buy now", url=bot_link, style="success")]
        ])

        await api_call("sendMessage", {
            "chat_id":                  LOG_CHANNEL_ID,
            "text":                     text,
            "entities":                 entities,
            "disable_web_page_preview": True,
            "reply_markup":             kb,
        })
    except Exception as ex:
        logger.warning(f"[cat_log] Failed to post category log: {ex}")

# ─── ADMIN PANEL ──────────────────────────────────────────────

async def get_admin_stats() -> dict:
    """Gather all live stats for admin panel dashboard."""
    db       = _load_db()
    cats     = _load_categories()
    orders   = _load_orders()

    total_users    = len(db)
    banned_users   = sum(1 for u in db.values() if u.get("banned"))
    total_orders   = len(orders)
    pending_orders = sum(1 for o in orders.values() if o["status"] == "pending_approval")
    total_products = len(cats)

    # Total stock across all categories
    total_stock = 0
    for cat_id, cat in cats.items():
        if cat.get("cat_type") not in ("dm_activation", "freebies"):
            total_stock += await stock_get_count(cat_id)

    # Low stock categories (≤ 3 items, excluding dm_activation/freebies)
    low_stock = []
    for cat_id, cat in cats.items():
        if cat.get("cat_type") in ("dm_activation", "freebies"):
            continue
        count = await stock_get_count(cat_id)
        if count <= 3:
            low_stock.append((cat["name"], count))

    # Revenue stats
    total_revenue = sum(
        o["price"] for o in orders.values()
        if o["status"] == "approved"
    )
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_revenue = sum(
        o["price"] for o in orders.values()
        if o["status"] == "approved" and o.get("created_at", "").startswith(today_str)
    )

    return {
        "total_users":    total_users,
        "banned_users":   banned_users,
        "total_orders":   total_orders,
        "pending_orders": pending_orders,
        "total_products": total_products,
        "total_stock":    total_stock,
        "low_stock":      low_stock,
        "total_revenue":  total_revenue,
        "today_revenue":  today_revenue,
    }


async def build_admin_panel() -> tuple:
    """Build admin panel dashboard message + keyboard."""
    s   = await get_admin_stats()
    now = datetime.now().strftime("%d %b %Y  •  %H:%M")

    m = Msg()
    m.emoji("thunder").text(" ").bold("Admin Panel").nl(2)

    # Stats block
    m.emoji("profile").text("  ").bold("Users: ").text(str(s["total_users"]))
    if s["banned_users"]:
        m.text(f"  •  Banned: {s['banned_users']}")
    m.nl()

    m.emoji("shop").text("  ").bold("Products: ").text(str(s["total_products"]))
    m.text(f"  •  Stock: {s['total_stock']}")
    if s["low_stock"]:
        m.text(f"  •  ").bold(f"Low: {len(s['low_stock'])}")
    m.nl()

    m.emoji("clipboard").text("  ").bold("Orders: ").text(str(s["total_orders"]))
    if s["pending_orders"]:
        m.text("  •  ").bold(f"Pending: {s['pending_orders']}")
    m.nl()

    m.emoji("moneybag").text("  ").bold("Revenue: ").text(f"$ {s['total_revenue']:.2f}")
    m.text(f"  •  Today: $ {s['today_revenue']:.2f}").nl(2)

    m.emoji("clock").text("  ").italic(now)

    text, ents = m.build()

    # Low stock warning
    if s["low_stock"]:
        warn = "⚠️ Low Stock: " + ", ".join(f"{n}({c})" for n, c in s["low_stock"][:3])
        text += "\n" + warn

    # Keyboard — same layout as screenshot
    pending_lbl = f"Pending · {s['pending_orders']}" if s["pending_orders"] else "Pending Orders"
    low_lbl     = f"Low Stock · {len(s['low_stock'])}" if s["low_stock"] else "Low Stock"
    prod_lbl    = f"Products · {s['total_products']}"
    ord_lbl     = f"Orders · {s['total_orders']}"
    user_lbl    = f"Customers · {s['total_users']}"
    ban_lbl     = f"Banned · {s['banned_users']}" if s["banned_users"] else "Banned"

    kb = build_keyboard([
        # Row 1 — Payments & Pending orders (urgent)
        [btn("Payments",          "adm_payments",   emoji_key="wallet",    style="success"),
         btn(pending_lbl,         "adm_pending",    emoji_key="timer",
             style="danger" if s["pending_orders"] else "success")],
        # Row 2 — Stock management
        [btn(low_lbl,             "adm_low_stock",  emoji_key="box",
             style="danger" if s["low_stock"] else "success"),
         btn("Add Stock",         "adm_add_stock",  emoji_key="plus",      style="success")],
        # Row 3 — Products
        [btn(prod_lbl,            "adm_products",   emoji_key="shop",      style="success"),
         btn("New Product",       "adm_new_product",emoji_key="pencil",    style="success"),
         btn("Add Stock",         "adm_add_stock2", emoji_key="box",       style="success")],
        # Row 4 — Users
        [btn(user_lbl,            "adm_customers",  emoji_key="profile",   style="success"),
         btn("Find User",         "adm_find_user",  emoji_key="clipboard", style="success"),
         btn(ban_lbl,             "adm_banned",     emoji_key="cross",
             style="danger" if s["banned_users"] else "success")],
        # Row 5 — Orders & Revenue
        [btn(ord_lbl,             "adm_orders",     emoji_key="clipboard", style="success"),
         btn("Revenue",           "adm_revenue",    emoji_key="moneybag",  style="success"),
         btn("Broadcast",         "adm_broadcast",  emoji_key="thunder",   style="success")],
        # Row 6 — Settings
        [btn("Wallet Adjust",     "adm_wallet",     emoji_key="wallet",    style="success"),
         btn("Pay Settings",      "adm_pay_set",    emoji_key="usdt",      style="success"),
         btn("Audit Log",         "adm_audit",      emoji_key="document",  style="success")],
        # Row 7 — Refresh
        [btn("Refresh",           "adm_refresh",    emoji_key="arrow",     style="success")],
    ])

    return text, ents, kb


# ─── KEYBOARDS ────────────────────────────────────────────────
def kb_main(lang: str = "en"):
    return build_keyboard([
        [btn(_t("btn_shop",     lang), "shop",      emoji_key="shop",     style="success"),
         btn(_t("btn_freebies", lang), "freebies",  emoji_key="gift",     style="success")],
        [btn(_t("btn_profile",  lang), "profile",   emoji_key="profile"),
         btn(_t("btn_wallet",   lang), "wallet",    emoji_key="wallet")],
        [btn(_t("btn_history",  lang), "history",   emoji_key="menu"),
         btn(_t("btn_referral", lang), "referral",  emoji_key="referral")],
        [btn(_t("btn_channel",  lang), url=FORCE_JOIN_CHANNEL_LINK,  emoji_key="channel"),
         btn(_t("btn_support",  lang), url="https://t.me/John_support",     emoji_key="support")],
        [btn(_t("btn_change_language", lang), "change_language", emoji_key="globe")],
    ])

def kb_back(lang: str = "en"):
    return build_keyboard([
        [btn(_t("btn_back", lang), "back_main", emoji_key="back")]
    ])

def kb_shop(categories: dict, stock_counts: dict = None, lang: str = "en"):
    """Build inline keyboard with 3 buttons per row (image-style grid) + back."""
    cats_list = list(categories.values())
    rows = []
    row = []
    for cat in cats_list:
        cat_id = cat["id"]
        count  = (stock_counts or {}).get(cat_id, 0)
        if count > 0:
            b = {
                "text":          cat["name"],
                "callback_data": f"cat_{cat_id}",
                "style":         "success",
            }
        else:
            b = {
                "text":          f"❌ {cat['name']}",
                "callback_data": f"cat_{cat_id}",
                "style":         "danger",
            }
        if cat.get("emoji_id"):
            b["icon_custom_emoji_id"] = str(cat["emoji_id"])
        row.append(b)
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn(_t("btn_back_to_menu", lang), "back_main", emoji_key="back")])
    return build_keyboard(rows)

def kb_wallet(lang: str = "en"):
    return build_keyboard([
        [btn(_t("btn_top_up_wallet", lang), "topup_wallet", style="success")],
        [btn(_t("btn_back",         lang), "back_main",    emoji_key="back")],
    ])

def kb_referral(link: str, lang: str = "en"):
    return build_keyboard([
        [btn(_t("btn_share_link", lang), url=f"https://t.me/share/url?url={link}", emoji_key="share", style="success")],
        [btn(_t("btn_back",      lang), "back_main", emoji_key="back")],
    ])

def kb_menu(lang: str = "en"):
    return build_keyboard([
        [btn(_t("btn_shop",     lang), "shop",      emoji_key="shop",     style="success"),
         btn(_t("btn_profile",  lang), "profile",   emoji_key="profile")],
        [btn(_t("btn_wallet",   lang), "wallet",    emoji_key="wallet"),
         btn(_t("btn_referral", lang), "referral",  emoji_key="referral")],
        [btn(_t("btn_back",     lang), "back_main", emoji_key="back")],
    ])

def kb_profile(lang: str = "en"):
    return build_keyboard([
        [btn(_t("btn_wallet", lang), "wallet",    emoji_key="wallet")],
        [btn(_t("btn_back",   lang), "back_main", emoji_key="back")],
    ])

def kb_home(lang: str = "en"):
    return build_keyboard([
        [btn(_t("btn_home", lang), "back_main", emoji_key="back")]
    ])

# ─── ADMIN STATE (in-memory conversation state) ───────────────
# State keys: "addcat_step", "addcat_data", "addstock_step", "addstock_data"
_admin_state: dict = {}   # { user_id: { "step": ..., "data": {...} } }

# ─── USER PAYMENT STATE ───────────────────────────────────────
# Tracks users waiting to send a payment screenshot
# { user_id: order_id }
_awaiting_screenshot: dict = {}

# Tracks users who are entering a top-up amount
# { user_id: True }
_awaiting_topup_amount: dict = {}

# Tracks users entering a custom quantity for a product
# { user_id: {"cat_id": ..., "max_qty": ...} }
_awaiting_custom_qty: dict = {}

# In-memory quantity selection state (before checkout)
# { user_id: {"cat_id": ..., "qty": int} }
_qty_state: dict = {}

# Broadcast state: { admin_user_id: {"from_chat_id": ..., "message_id": ...} }
_pending_broadcast: dict = {}

def is_admin(user_id) -> bool:
    return int(user_id) in ADMINS

# ─── BOT USERNAME CACHE ───────────────────────────────────────
_bot_username: str | None = None

async def get_bot_username() -> str:
    global _bot_username
    if not _bot_username:
        data = await api_call("getMe", {})
        _bot_username = data.get("result", {}).get("username", "bot")
    return _bot_username

# ─── DATABASE ─────────────────────────────────────────────────
# ─── DATABASE (JSON) ──────────────────────────────────────────
_db_lock  = asyncio.Lock()
_cat_lock = asyncio.Lock()
_stk_lock = asyncio.Lock()

# ─── In-memory caches (avoid re-reading JSON from disk every request) ───
_db_cache:   dict | None = None
_cat_cache:  dict | None = None
_stk_cache:  dict | None = None
_ord_cache:  dict | None = None
_pay_cache:  dict | None = None

def _load_db() -> dict:
    """Load users.json — uses in-memory cache."""
    global _db_cache
    if _db_cache is None:
        if not os.path.exists(DB_PATH):
            _db_cache = {}
        else:
            with open(DB_PATH, "r", encoding="utf-8-sig") as f:
                _db_cache = json.load(f)
    return _db_cache

def _save_db(data: dict):
    """Write users.json to disk and update cache."""
    global _db_cache
    _db_cache = data
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_categories() -> dict:
    global _cat_cache
    if _cat_cache is None:
        if not os.path.exists(CAT_PATH):
            _cat_cache = {}
        else:
            with open(CAT_PATH, "r", encoding="utf-8-sig") as f:
                _cat_cache = json.load(f)
    return _cat_cache

def _save_categories(data: dict):
    global _cat_cache
    _cat_cache = data
    with open(CAT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_stock() -> dict:
    global _stk_cache
    if _stk_cache is None:
        if not os.path.exists(STOCK_PATH):
            _stk_cache = {}
        else:
            with open(STOCK_PATH, "r", encoding="utf-8-sig") as f:
                _stk_cache = json.load(f)
    return _stk_cache

def _save_stock(data: dict):
    global _stk_cache
    _stk_cache = data
    with open(STOCK_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def db_init():
    """Create JSON files if they don't exist."""
    for path, default in [(DB_PATH, {}), (CAT_PATH, {}), (STOCK_PATH, {}), (ORDERS_PATH, {})]:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)
    logger.info("Databases ready.")

async def db_upsert_user(user: dict):
    """Insert new user or update username/first_name and last_seen."""
    uid   = str(user.get("id"))
    uname = user.get("username") or ""
    fname = user.get("first_name") or ""
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with _db_lock:
        data = _load_db()
        if uid not in data:
            data[uid] = {
                "user_id":         uid,
                "username":        uname,
                "first_name":      fname,
                "balance":         0.0,
                "total_spent":     0.0,
                "products_bought": 0,
                "joined_at":       now,
                "last_seen":       now,
                "terms_accepted":  False,
            }
        else:
            data[uid]["username"]   = uname
            data[uid]["first_name"] = fname
            data[uid]["last_seen"]  = now
        _save_db(data)

async def db_get_user(user_id) -> dict | None:
    """Fetch a user dict, or None if not found."""
    async with _db_lock:
        data = _load_db()
        return data.get(str(user_id))

async def db_ban_user(user_id, reason: str = "No reason provided"):
    """Ban a user — sets banned=True and ban_reason."""
    async with _db_lock:
        data = _load_db()
        uid  = str(user_id)
        if uid not in data:
            data[uid] = {"user_id": uid}
        data[uid]["banned"]     = True
        data[uid]["ban_reason"] = reason
        _save_db(data)

async def db_unban_user(user_id):
    """Unban a user."""
    async with _db_lock:
        data = _load_db()
        uid  = str(user_id)
        if uid in data:
            data[uid]["banned"]     = False
            data[uid]["ban_reason"] = ""
            _save_db(data)

async def db_is_banned(user_id) -> tuple[bool, str]:
    """Returns (is_banned, reason)."""
    data   = _load_db()
    u      = data.get(str(user_id), {})
    banned = u.get("banned", False)
    reason = u.get("ban_reason", "No reason provided")
    return banned, reason

async def db_accept_terms(user_id, lang: str = "en"):
    """Mark user as having accepted terms and save their language."""
    uid = str(user_id)
    async with _db_lock:
        data = _load_db()
        if uid in data:
            data[uid]["terms_accepted"] = True
            data[uid]["language"] = lang
            _save_db(data)

async def db_get_lang(user_id) -> str:
    """Get user's language preference. Defaults to 'en'."""
    data = _load_db()
    u = data.get(str(user_id), {})
    return u.get("language", "en")

async def db_check_freebie_cooldown(user_id) -> tuple[bool, float]:
    """
    Check if user can claim a freebie.
    Returns (can_claim: bool, hours_remaining: float).
    24 hour cooldown between claims.
    """
    uid = str(user_id)
    async with _db_lock:
        data = _load_db()
        user = data.get(uid, {})
        last_claim = user.get("last_freebie_claim")
        if not last_claim:
            return True, 0.0
        try:
            last_dt = datetime.strptime(last_claim, "%Y-%m-%d %H:%M:%S")
            elapsed = (datetime.now() - last_dt).total_seconds()
            cooldown = 24 * 3600  # 24 hours
            if elapsed >= cooldown:
                return True, 0.0
            remaining = (cooldown - elapsed) / 3600
            return False, round(remaining, 1)
        except Exception:
            return True, 0.0

async def db_set_freebie_claim(user_id):
    """Record the timestamp of user's latest freebie claim."""
    uid = str(user_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with _db_lock:
        data = _load_db()
        if uid in data:
            data[uid]["last_freebie_claim"] = now
            _save_db(data)

async def db_add_balance(user_id, amount: float):
    """Add amount to user balance (use negative value to deduct)."""
    async with _db_lock:
        data = _load_db()
        uid  = str(user_id)
        if uid in data:
            data[uid]["balance"] = round(data[uid]["balance"] + amount, 2)
            _save_db(data)

async def db_record_purchase(user_id, amount: float):
    """Record a product purchase — deduct balance, add to spent & count."""
    async with _db_lock:
        data = _load_db()
        uid  = str(user_id)
        if uid in data:
            data[uid]["balance"]         = round(data[uid]["balance"] - amount, 2)
            data[uid]["total_spent"]     = round(data[uid]["total_spent"] + amount, 2)
            data[uid]["products_bought"] = data[uid]["products_bought"] + 1
            _save_db(data)

# ─── CATEGORY & STOCK DB HELPERS ──────────────────────────────
async def cat_get_all() -> dict:
    async with _cat_lock:
        return _load_categories()

async def cat_save(cat_id: str, name: str, price: float,
                   emoji_char: str, emoji_id: str, cat_type: str = "id_pass",
                   description: str = "", desc_entities: list = None):
    async with _cat_lock:
        data = _load_categories()
        data[cat_id] = {
            "id":          cat_id,
            "name":        name,
            "price":       price,
            "emoji_char":  emoji_char,
            "emoji_id":    emoji_id,
            "cat_type":    cat_type,   # "link" or "id_pass"
            "description": description,
            "desc_entities": desc_entities or [],  # Store premium emoji entities
            "created_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_categories(data)

async def stock_get(cat_id: str) -> list:
    async with _stk_lock:
        data = _load_stock()
        return data.get(cat_id, [])

async def stock_get_count(cat_id: str) -> int:
    """Get stock count — works for both list and int format in stock.json.
    For dm_activation categories (no stock), returns 999 so they always show as available."""
    # Check if this is a dm_activation category
    cats = _load_categories()
    cat  = cats.get(cat_id, {})
    if cat.get("cat_type") == "dm_activation" or cat.get("cat_type") == "freebies":
        return 999  # always available — no stock tracking needed

    async with _stk_lock:
        data = _load_stock()
        val = data.get(cat_id, [])
        if isinstance(val, list):
            return len(val)
        return int(val)  # legacy int format fallback

async def stock_set_count(cat_id: str, count: int):
    """Set stock count directly (legacy/admin use only)."""
    async with _stk_lock:
        data = _load_stock()
        # Preserve list if already a list — only set int if no list exists
        existing = data.get(cat_id, [])
        if isinstance(existing, list):
            # Trim or keep the list as-is based on count
            data[cat_id] = existing[:max(0, int(count))]
        else:
            data[cat_id] = max(0, int(count))
        _save_stock(data)

async def stock_decrement(cat_id: str) -> bool:
    """Decrement stock by 1. Returns True if successful, False if already empty."""
    async with _stk_lock:
        data = _load_stock()
        val = data.get(cat_id, [])
        if isinstance(val, list):
            if len(val) == 0:
                return False
            val.pop(0)
            data[cat_id] = val
        else:
            count = int(val)
            if count <= 0:
                return False
            data[cat_id] = count - 1
        _save_stock(data)
        return True

async def stock_add(cat_id: str, items: list):
    """Add a list of item dicts to a category's stock list."""
    async with _stk_lock:
        data = _load_stock()
        existing = data.get(cat_id, [])
        # Migrate from int to list if needed
        if not isinstance(existing, list):
            existing = []
        existing.extend(items)
        data[cat_id] = existing
        _save_stock(data)

    # Post to log channel (once)
    cats = _load_categories()
    cat = cats.get(cat_id)
    if cat:
        await post_stock_log(cat["name"], len(items), cat_id)

async def cat_delete(cat_id: str):
    async with _cat_lock:
        data = _load_categories()
        if cat_id in data:
            del data[cat_id]
            _save_categories(data)
    # Also remove its stock
    async with _stk_lock:
        data = _load_stock()
        if cat_id in data:
            del data[cat_id]
            _save_stock(data)

async def stock_count(cat_id: str) -> int:
    return await stock_get_count(cat_id)
    async with _cat_lock:
        data = _load_categories()
        if cat_id in data:
            del data[cat_id]
            _save_categories(data)
    # Also remove its stock
    async with _stk_lock:
        data = _load_stock()
        if cat_id in data:
            del data[cat_id]
            _save_stock(data)

# ─── ORDERS DB ────────────────────────────────────────────────
_ord_lock = asyncio.Lock()

def _load_orders() -> dict:
    global _ord_cache
    if _ord_cache is None:
        if not os.path.exists(ORDERS_PATH):
            _ord_cache = {}
        else:
            with open(ORDERS_PATH, "r", encoding="utf-8-sig") as f:
                _ord_cache = json.load(f)
    return _ord_cache

def _save_orders(data: dict):
    global _ord_cache
    _ord_cache = data
    with open(ORDERS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def order_create(user_id, cat_id: str, cat_name: str, price: float,
                       order_type: str = "purchase", network: str = "",
                       quantity: int = 1) -> str:
    """Create a new pending order. Returns order_id."""
    order_id = str(uuid.uuid4())
    now = datetime.now()
    async with _ord_lock:
        data = _load_orders()
        data[order_id] = {
            "order_id":           order_id,
            "user_id":            str(user_id),
            "cat_id":             cat_id,
            "cat_name":           cat_name,
            "price":              price,          # total price (unit_price × qty)
            "unit_price":         round(price / max(1, quantity), 4),
            "quantity":           quantity,
            "order_type":         order_type,
            "network":            network,
            "status":             "pending_payment",
            "created_at":         now.strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at":         (now + timedelta(minutes=ORDER_EXPIRY_MINUTES)).strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot_file_id": None,
        }
        _save_orders(data)
    return order_id

async def order_get(order_id: str) -> dict | None:
    async with _ord_lock:
        data = _load_orders()
        return data.get(order_id)

async def order_set_status(order_id: str, status: str):
    async with _ord_lock:
        data = _load_orders()
        if order_id in data:
            data[order_id]["status"] = status
            _save_orders(data)

async def order_set_network(order_id: str, network: str):
    """Set/update the payment network for an order (e.g. 'bep20')."""
    async with _ord_lock:
        data = _load_orders()
        if order_id in data:
            data[order_id]["network"] = network
            _save_orders(data)

async def order_set_screenshot(order_id: str, file_id: str):
    async with _ord_lock:
        data = _load_orders()
        if order_id in data:
            data[order_id]["screenshot_file_id"] = file_id
            data[order_id]["status"] = "pending_approval"
            _save_orders(data)

async def order_get_pending_by_user(user_id) -> dict | None:
    """Get the latest pending_payment order for a user."""
    async with _ord_lock:
        data = _load_orders()
        for oid, order in reversed(list(data.items())):
            if (order["user_id"] == str(user_id) and
                    order["status"] == "pending_payment"):
                return order
        return None

async def stock_pop(cat_id: str) -> dict | None:
    """Pop one stock item from cat_id. Returns item dict or None if empty."""
    async with _stk_lock:
        data = _load_stock()
        items = data.get(cat_id, [])
        if not isinstance(items, list) or not items:
            return None
        item = items.pop(0)
        data[cat_id] = items
        _save_stock(data)
        return item

async def auto_deliver(chat_id, user_id, order: dict) -> bool:
    """
    Automatically deliver product to user after payment.
    Returns True on success, False if stock empty (not applicable for dm_activation).

    Types:
      link          — sends activation link from stock
      id_pass       — sends email:password from stock
      dm_activation — tells user to DM admin, notifies admins
    """
    cat_id   = order["cat_id"]
    cat_name = order["cat_name"]

    # Fetch user's language for translated messages
    lang = await db_get_lang(user_id)

    # ── DM Activation type — no stock needed ─────────────────
    cats    = _load_categories()
    cat_obj = cats.get(cat_id, {})
    cat_type = cat_obj.get("cat_type", "id_pass")

    if cat_type == "dm_activation":
        dm = Msg()
        dm.emoji("check").text(" ").bold(_t("delivery_dm_title", lang)).nl(2)
        dm.emoji("cart").text(f" {_t('order_product', lang)}").bold(cat_name).nl(2)
        dm.emoji("mobile").text(" ").bold(_t("delivery_dm_next", lang)).nl()
        dm.italic(_t("delivery_dm_hint", lang)).nl(2)
        dm.emoji("timer").text(" ").italic(_t("delivery_dm_usually", lang))
        deliver_text, deliver_ent = dm.build()
        await send_msg(chat_id, deliver_text, deliver_ent,
            keyboard=build_keyboard([
                [btn(_t("btn_dm_admin", lang), url="https://t.me/John_support",
                     emoji_key="support", style="success")],
                [btn(_t("btn_home", lang), "back_main", emoji_key="back")],
            ])
        )
        # Notify admins (admin messages stay in English)
        uname_str = f"@{order.get('user_username','')}" if order.get("user_username") else f"ID: {order['user_id']}"
        for admin_id in ADMINS:
            am = Msg()
            am.emoji("mobile").text(" ").bold("DM Activation Required!").nl(2)
            am.emoji("cart").text(" Product: ").bold(cat_name).nl()
            am.emoji("balance").text(" Amount: ").bold(f"$ {order['price']:.2f} USDT").nl()
            am.emoji("user").text(" User: ").bold(uname_str).nl(2)
            am.italic("User has been told to DM you. Please activate their product.")
            at, ae = am.build()
            await send_msg(admin_id, at, ae)
        return True

    # ── Freebies — pop from stock, deliver for FREE ───────────
    if cat_type == "freebies":
        qty   = order.get("quantity", 1)
        items = []
        for _ in range(qty):
            item = await stock_pop(cat_id)
            if not item:
                break
            items.append(item)

        if not items:
            return False

        # Build .txt file content
        order_id  = order.get("order_id", "ORD-FREE")
        short_id  = order_id.replace("-", "")[:8].upper()
        now_str   = datetime.now().strftime("%b %d, %Y • %I:%M %p PKT")
        txt_lines = []
        txt_lines.append(_t("delivery_txt_header", lang))
        txt_lines.append("=" * 36)
        txt_lines.append(f"🧾 ORD-{short_id}")
        txt_lines.append(f"🕐 {now_str}")
        txt_lines.append(f"📦 {cat_name}")
        txt_lines.append(f"💰 Total: $0.00  •  Qty: ×{len(items)}  •  {_t('delivery_free_label', lang)}")
        txt_lines.append("🛡 Warranty: Non-warranty")
        txt_lines.append("=" * 36)
        txt_lines.append("")
        txt_lines.append(_t("delivery_txt_credentials_below", lang, qty=len(items)))
        txt_lines.append("")

        for i, item in enumerate(items, 1):
            if qty > 1:
                txt_lines.append(f"── #{i} ──")
            if "link" in item:
                txt_lines.append(f"🔗 Activation Link: {item['link']}")
            else:
                txt_lines.append(f"📧 Email:    {item.get('email', 'N/A')}")
                txt_lines.append(f"🔑 Password: {item.get('password', 'N/A')}")
            txt_lines.append("")

        txt_lines.append("=" * 36)
        txt_lines.append(_t("delivery_txt_free_thank_you", lang))

        txt_content  = "\n".join(txt_lines)
        txt_filename = f"ORD-{short_id}-{cat_name.replace(' ', '_')}.txt"
        txt_path     = os.path.join(tempfile.gettempdir(), txt_filename)

        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(txt_content)

            # Caption message
            cap = Msg()
            cap.emoji("check").text(" ").bold(_t("delivery_order_delivered", lang)).nl(2)
            cap.emoji("box").text(" ").bold(cat_name).nl()
            cap.emoji("clipboard").text(f" {_t('delivery_qty_label', lang, qty=len(items))}").bold(_t("delivery_free_label", lang)).nl(2)
            cap.text("📎 ").italic(_t("delivery_credentials_attached", lang))
            cap.nl(2)
            cap.italic(_t("delivery_thank_you", lang))
            cap_text, cap_ent = cap.build()

            await send_document(
                chat_id, txt_path,
                caption=cap_text,
                caption_entities=cap_ent,
                keyboard=build_keyboard([
                    [btn(_t("btn_shop_more", lang), "shop", emoji_key="shop", style="success")],
                    [btn(_t("btn_home", lang), "back_main", emoji_key="back")],
                ])
            )
        finally:
            try:
                os.remove(txt_path)
            except Exception:
                pass

        return True

    # ── Link / ID & Pass — pop from stock ────────────────────
    qty   = order.get("quantity", 1)
    items = []
    for _ in range(qty):
        item = await stock_pop(cat_id)
        if not item:
            break
        items.append(item)

    if not items:
        return False

    # Build .txt file content
    order_id  = order.get("order_id", "ORD-UNKNOWN")
    short_id  = order_id.replace("-", "")[:8].upper()
    now_str   = datetime.now().strftime("%b %d, %Y • %I:%M %p PKT")
    price     = order.get("price", 0.0)
    warranty  = "Non-warranty"

    txt_lines = []
    txt_lines.append(_t("delivery_txt_header", lang))
    txt_lines.append("=" * 36)
    txt_lines.append(f"🧾 ORD-{short_id}")
    txt_lines.append(f"🕐 {now_str}")
    txt_lines.append(f"📦 {cat_name}")
    txt_lines.append(f"💰 {_t('delivery_total_qty', lang, total=f'{price:.2f}', qty=qty)}  •  {order.get('network','').upper() or 'USDT'}")
    txt_lines.append(f"🛡 Warranty: {warranty}")
    txt_lines.append("=" * 36)
    txt_lines.append("")
    txt_lines.append(_t("delivery_txt_credentials_below", lang, qty=len(items)))
    txt_lines.append("")

    for i, item in enumerate(items, 1):
        if qty > 1:
            txt_lines.append(f"── #{i} ──")
        if "link" in item:
            txt_lines.append(f"🔗 Activation Link: {item['link']}")
        else:
            txt_lines.append(f"📧 Email:    {item.get('email', 'N/A')}")
            txt_lines.append(f"🔑 Password: {item.get('password', 'N/A')}")
        txt_lines.append("")

    txt_lines.append("=" * 36)
    txt_lines.append(_t("delivery_txt_thank_you", lang))

    txt_content  = "\n".join(txt_lines)
    txt_filename = f"ORD-{short_id}-{cat_name.replace(' ', '_')}.txt"
    txt_path     = os.path.join(tempfile.gettempdir(), txt_filename)

    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(txt_content)

        # Caption message
        cap = Msg()
        cap.emoji("check").text(" ").bold(_t("delivery_order_delivered", lang)).nl(2)
        cap.emoji("box").text(" ").bold(cat_name).nl()
        cap.text(f"💰 {_t('delivery_total_qty', lang, total=f'{price:.2f}', qty=qty)}").nl(2)
        cap.text("📎 ").italic(_t("delivery_credentials_attached", lang))
        cap.nl(2)
        cap.italic(_t("delivery_thank_you", lang))
        cap_text, cap_ent = cap.build()

        await send_document(
            chat_id, txt_path,
            caption=cap_text,
            caption_entities=cap_ent,
            keyboard=build_keyboard([[btn(_t("btn_home", lang), "back_main", emoji_key="back")]])
        )
    finally:
        try:
            os.remove(txt_path)
        except Exception:
            pass

    return True

# ─── HANDLERS ─────────────────────────────────────────────────

async def _handle_admin_state(chat_id, user_id, text: str, message: dict) -> bool:
    """
    Handle multi-step admin conversations.
    Returns True if the message was consumed by an admin flow.
    """
    state = _admin_state.get(user_id)
    if not state:
        return False

    step = state.get("step")

    # ── /ban flow ──────────────────────────────────────────────
    if step == "ban_reason":
        target_id = state["data"]["target_id"]
        reason    = text.strip() or "No reason provided"
        await db_ban_user(target_id, reason)
        del _admin_state[user_id]
        # Notify the banned user
        try:
            bm = Msg()
            bm.emoji("cross").text(" ").bold("You have been banned.").nl(2)
            bm.text("Reason: ").italic(reason).nl(2)
            bm.italic("Contact admin for support.")
            bt, be = bm.build()
            await send_msg(target_id, bt, be)
        except Exception:
            pass
        await send_msg(chat_id,
            f"✅ User `{target_id}` has been banned.\nReason: {reason}")
        return True

    # ── /addcategory flow ──────────────────────────────────────
    if step == "addcat_name":
        state["data"]["name"] = text.strip()
        state["step"] = "addcat_price"
        await send_msg(chat_id,
            "💰 Enter the price for this category in USD (e.g. 50):")
        return True

    if step == "addcat_price":
        try:
            price = float(text.strip())
        except ValueError:
            await send_msg(chat_id, "❌ Invalid price. Enter a number like 4.99:")
            return True
        state["data"]["price"] = price
        state["step"] = "addcat_emoji"
        await send_msg(chat_id,
            "✨ Now send the premium emoji for this category.\n"
            "(Just send the emoji as a message — bot will read its custom_emoji_id)")
        return True

    if step == "addcat_emoji":
        # Try to extract custom_emoji entity from the message
        entities   = message.get("entities") or []
        emoji_char = text.strip()
        emoji_id   = ""
        for ent in entities:
            if ent.get("type") == "custom_emoji":
                emoji_id = str(ent.get("custom_emoji_id", ""))
                # Extract the emoji character using offset/length
                offset = ent.get("offset", 0)
                length = ent.get("length", 1)
                # Convert UTF-16 offset to Python string index
                raw = text.encode("utf-16-le")
                emoji_char = raw[offset*2 : (offset+length)*2].decode("utf-16-le")
                break
        state["data"]["emoji_char"] = emoji_char
        state["data"]["emoji_id"]   = emoji_id
        state["step"] = "addcat_type"

        await send_msg(chat_id,
            "📦 Select the category type:\n\n"
            "🔗 Link — Admin uploads activation links. User receives a link after payment.\n"
            "🔐 ID & Pass — Admin uploads email:password accounts. User receives credentials after payment.\n"
            "💬 DM Activation — No stock needed. User is told to DM admin for activation after payment.\n"
            "🎁 Freebies — Free products! Users claim for free. Admin adds stock (link or id:pass).",
            keyboard=build_keyboard([
                [btn("🔗  Link",          "admincat_type_link",      style="success")],
                [btn("🔐  ID & Pass",     "admincat_type_id_pass",   style="success")],
                [btn("💬  DM Activation", "admincat_type_dm",        style="success")],
                [btn("🎁  Freebies",      "admincat_type_freebies",  style="success")],
            ])
        )
        return True

    if step == "addcat_type":
        # This step is handled via callback, not text
        # If admin types something here instead of pressing button, remind them
        await send_msg(chat_id,
            "⬆️ Please use the buttons above to select the category type.",
            keyboard=build_keyboard([
                [btn("🔗  Link",          "admincat_type_link",      style="success")],
                [btn("🔐  ID & Pass",     "admincat_type_id_pass",   style="success")],
                [btn("💬  DM Activation", "admincat_type_dm",        style="success")],
                [btn("🎁  Freebies",      "admincat_type_freebies",  style="success")],
            ])
        )
        return True

    if step == "addcat_desc":
        desc = text.strip()
        # "—" or "-" means skip, use empty
        if desc in ("-", "—"):
            desc = ""
            desc_entities = []
        else:
            # Capture premium emoji entities from the message
            entities = message.get("entities") or []
            desc_entities = [
                {
                    "type": ent.get("type"),
                    "offset": ent.get("offset"),
                    "length": ent.get("length"),
                    "custom_emoji_id": str(ent.get("custom_emoji_id", ""))
                }
                for ent in entities
                if ent.get("type") == "custom_emoji"
            ]
        state["data"]["description"] = desc
        state["data"]["desc_entities"] = desc_entities
        state["step"] = "addcat_confirm"

        d          = state["data"]
        type_label = "🔗 Link" if d.get("cat_type") == "link" else "🔐 ID & Pass"
        desc_preview = desc[:80] + ("…" if len(desc) > 80 else "") if desc else "(no description)"
        emoji_count = len(desc_entities)
        emoji_note = f" ({emoji_count} premium emoji{'s' if emoji_count != 1 else ''})" if emoji_count > 0 else ""
        await send_msg(chat_id,
            f"📋 Confirm new category:\n\n"
            f"{d['emoji_char']} Name: {d['name']}\n"
            f"💰 Price: $ {d['price']:.2f}\n"
            f"📦 Type: {type_label}\n"
            f"📝 Description: {desc_preview}{emoji_note}\n\n"
            f"Reply YES to confirm or NO to cancel."
        )
        return True

    if step == "addcat_confirm":
        if text.strip().upper() == "YES":
            d      = state["data"]
            cat_id = d["name"].lower().replace(" ", "_")
            await cat_save(cat_id, d["name"], d["price"],
                           d["emoji_char"], d["emoji_id"],
                           d.get("cat_type", "id_pass"),
                           d.get("description", ""),
                           d.get("desc_entities", []))
            # ── Post category-added log to channel ──────────
            await post_category_log(d["name"], d["price"], d.get("cat_type", "id_pass"))
            del _admin_state[user_id]
            type_label = "🔗 Link" if d.get("cat_type") == "link" else "🔐 ID & Pass"
            await send_msg(chat_id,
                f"✅ Category *{d['name']}* added successfully!\n"
                f"Type: {type_label}")
        else:
            del _admin_state[user_id]
            await send_msg(chat_id, "❌ Cancelled. Category was not added.")
        return True

    # ── /addstock flow ─────────────────────────────────────────
    if step == "addstock_type":
        # This step is handled via callback buttons, not text.
        await send_msg(chat_id,
            "⬆️ Please use the buttons above to select the stock type.",
            keyboard=build_keyboard([
                [btn("🔗  Link",      "addstock_type_link",      style="success")],
                [btn("🔐  ID & Pass", "addstock_type_id_pass",   style="success")],
                [btn("🎁  Freebies",  "addstock_type_freebies",  style="success")],
            ])
        )
        return True

    if step == "addstock_pick":
        # Admin typed a category number or name
        cats = _load_categories()
        cat_list = list(cats.values())
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(cat_list):
                raise ValueError
            chosen = cat_list[idx]
        except ValueError:
            chosen = next(
                (c for c in cat_list
                 if c["name"].lower() == text.strip().lower()), None)
        if not chosen:
            await send_msg(chat_id,
                "❌ Category not found. Send the number from the list:")
            return True

        state["data"]["cat_id"]   = chosen["id"]
        state["data"]["cat_name"] = chosen["name"]
        # Override cat_type with what category actually is
        state["data"]["cat_type"] = chosen.get("cat_type", "id_pass")
        state["data"]["items"]    = []

        current  = await stock_get_count(chosen["id"])
        cat_type = chosen.get("cat_type", "id_pass")

        # Freebies: ask admin to choose link or id:pass format
        if cat_type == "freebies":
            state["step"] = "addstock_freebies_format"
            await send_msg(chat_id,
                f"🎁 Adding stock to *{chosen['name']}* (Freebies)\n"
                f"Current stock: {current}\n\n"
                "What format is your stock?",
                keyboard=build_keyboard([
                    [btn("🔗  Links",      "addstock_freebies_link",    style="success")],
                    [btn("🔐  ID & Pass",  "addstock_freebies_id_pass", style="success")],
                ])
            )
        elif cat_type == "link":
            state["step"] = "addstock_items"
            await send_msg(chat_id,
                f"🔗 Adding links to *{chosen['name']}*\n"
                f"Current stock: {current}\n\n"
                "Send activation links — one per line.\n"
                "Example:\n"
                "https://t.me/+abcxyz123\n"
                "https://example.com/activate?code=xyz\n\n"
                "Type *DONE* when finished.")
        else:
            state["step"] = "addstock_items"
            await send_msg(chat_id,
                f"🔐 Adding accounts to *{chosen['name']}*\n"
                f"Current stock: {current}\n\n"
                "Send accounts — one per line in format:\n"
                "`email:password`\n\n"
                "Type *DONE* when finished.")
        return True

    if step == "addstock_freebies_format":
        # This step is handled via callback buttons
        await send_msg(chat_id,
            "⬆️ Please use the buttons to choose the stock format.",
            keyboard=build_keyboard([
                [btn("🔗  Links",      "addstock_freebies_link",    style="success")],
                [btn("🔐  ID & Pass",  "addstock_freebies_id_pass", style="success")],
            ])
        )
        return True

    if step == "addstock_items":
        if text.strip().upper() == "DONE":
            items    = state["data"]["items"]
            cat_name = state["data"]["cat_name"]
            cat_id   = state["data"]["cat_id"]
            cat_type = state["data"].get("cat_type", "id_pass")
            if items:
                await stock_add(cat_id, items)
                del _admin_state[user_id]
                label = "link(s)" if cat_type in ("link", "freebies_link") else "account(s)"
                await send_msg(chat_id,
                    f"✅ Added {len(items)} {label} to *{cat_name}*.\n"
                    f"New stock: {await stock_get_count(cat_id)}")
            else:
                del _admin_state[user_id]
                await send_msg(chat_id, "❌ No items added. Cancelled.")
            return True

        # Parse lines based on category type
        cat_type = state["data"].get("cat_type", "id_pass")
        added  = 0
        errors = 0

        if cat_type in ("link", "freebies_link"):
            for line in text.strip().splitlines():
                line = line.strip()
                if line.startswith("http://") or line.startswith("https://") or line.startswith("t.me"):
                    state["data"]["items"].append({"link": line})
                    added += 1
                elif line:
                    errors += 1
            msg_parts = [f"🔗 {added} link(s) received."]
        else:
            for line in text.strip().splitlines():
                line = line.strip()
                if ":" in line:
                    parts = line.split(":", 1)
                    state["data"]["items"].append({
                        "email":    parts[0].strip(),
                        "password": parts[1].strip(),
                    })
                    added += 1
                elif line:
                    errors += 1
            msg_parts = [f"➕ {added} account(s) received."]

        if errors:
            msg_parts.append(f"⚠️ {errors} line(s) skipped (bad format).")
        msg_parts.append(f"Total queued: {len(state['data']['items'])}. Send more or type *DONE* to save.")
        await send_msg(chat_id, "\n".join(msg_parts))
        return True

    # ── /removestock flow ──────────────────────────────────────────
    if step == "removestock_pick":
        # Expect admin to type category name or number shown in list
        cats = _load_categories()
        cat_list = list(cats.values())
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(cat_list):
                raise ValueError
            chosen = cat_list[idx]
        except ValueError:
            # Try matching by name
            chosen = next(
                (c for c in cat_list
                 if c["name"].lower() == text.strip().lower()), None)
        if not chosen:
            await send_msg(chat_id,
                "❌ Category not found. Send the number from the list:")
            return True
        
        current_stock = await stock_get_count(chosen["id"])
        if current_stock <= 0:
            await send_msg(chat_id,
                f"❌ *{chosen['name']}* has no stock to remove.\nCurrent stock: {current_stock}")
            del _admin_state[user_id]
            return True
            
        state["data"]["cat_id"]   = chosen["id"]
        state["data"]["cat_name"] = chosen["name"]
        state["data"]["current_stock"] = current_stock
        state["step"] = "removestock_quantity"

        cat_type  = chosen.get("cat_type", "id_pass")
        type_label = "🔗 Link" if cat_type == "link" else "🔐 ID & Pass"
        await send_msg(chat_id,
            f"🗑️ Remove Stock from *{chosen['name']}* ({type_label})\n"
            f"Current stock: *{current_stock}*\n\n"
            f"How many items to remove? (Enter a number)\n"
            f"Max: {current_stock}")
        return True

    if step == "removestock_quantity":
        try:
            remove_count = int(text.strip())
            if remove_count < 0:
                raise ValueError
        except ValueError:
            await send_msg(chat_id, "❌ Enter a valid number (0 or more):")
            return True

        cat_id = state["data"]["cat_id"]
        cat_name = state["data"]["cat_name"]
        current_stock = state["data"]["current_stock"]
        
        if remove_count > current_stock:
            await send_msg(chat_id, 
                f"❌ Cannot remove {remove_count} items. Current stock is only {current_stock}.\n"
                f"Max you can remove: {current_stock}")
            return True
        
        if remove_count == 0:
            await send_msg(chat_id, "❌ Cannot remove 0 items. Enter a number greater than 0:")
            return True
        
        # Calculate new stock count
        new_stock = current_stock - remove_count
        await stock_set_count(cat_id, new_stock)
        del _admin_state[user_id]

        await send_msg(chat_id,
            f"✅ Removed *{remove_count}* items from *{cat_name}*\n"
            f"Previous stock: {current_stock}\n"
            f"New stock: *{new_stock}*")
        return True

    # ── /deletecategory flow ───────────────────────────────────
    if step == "delcat_pick":
        cats = _load_categories()
        cat_list = list(cats.values())
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(cat_list):
                raise ValueError
            chosen = cat_list[idx]
        except ValueError:
            chosen = next(
                (c for c in cat_list
                 if c["name"].lower() == text.strip().lower()), None)
        if not chosen:
            await send_msg(chat_id,
                "❌ Category not found. Send the number from the list:")
            return True
        state["data"]["cat_id"]   = chosen["id"]
        state["data"]["cat_name"] = chosen["name"]
        state["step"] = "delcat_confirm"
        await send_msg(chat_id,
            f"⚠️ Are you sure you want to DELETE *{chosen['name']}*?\n"
            "This will remove the category AND all its stock.\n\n"
            "Reply YES to confirm or NO to cancel.")
        return True

    if step == "delcat_confirm":
        if text.strip().upper() == "YES":
            cat_name = state["data"]["cat_name"]
            cat_id   = state["data"]["cat_id"]
            await cat_delete(cat_id)
            del _admin_state[user_id]
            await send_msg(chat_id,
                f"✅ Category *{cat_name}* and its stock have been deleted.")
        else:
            del _admin_state[user_id]
            await send_msg(chat_id, "❌ Cancelled. Category was not deleted.")
        return True

    # ── deliver_link flow (after approving link-type order) ───
    if step == "deliver_link":
        d        = state["data"]
        order_id = d["order_id"]
        buyer_id = d["buyer_id"]
        cat_name = d["cat_name"]

        link = text.strip()
        if not (link.startswith("http") or link.startswith("t.me")):
            await send_msg(chat_id,
                "❌ That doesn't look like a valid link. Send a URL starting with https:// or t.me/")
            return True

        del _admin_state[user_id]

        # Send to buyer
        dm = Msg()
        dm.emoji("check").text(" ").bold("Payment ").italic("Approved!").nl(2)
        dm.emoji("cart").text(" Product: ").bold(cat_name).nl(2)
        dm.emoji("link").text(" ").italic("Your Activation Link:").nl()
        dm.text(link).nl(2)
        dm.text("Follow the activation instructions for this product.\n")
        dm.emoji("pop").text(" ").bold("Thank you").text(" for your purchase!")
        deliver_text, deliver_ent = dm.build()
        await send_msg(buyer_id, deliver_text, deliver_ent,
            keyboard=build_keyboard([[btn("Home", "back_main", emoji_key="back")]]))

        await send_msg(chat_id,
            f"✅ Link sent to user `{buyer_id}` for *{cat_name}*.")
        return True

    # ── deliver_creds flow (after approving id_pass order) ────
    if step == "deliver_creds":
        d        = state["data"]
        order_id = d["order_id"]
        buyer_id = d["buyer_id"]
        cat_name = d["cat_name"]

        line = text.strip()
        if ":" not in line:
            await send_msg(chat_id,
                "❌ Invalid format. Send credentials as:\n`email:password`")
            return True

        parts    = line.split(":", 1)
        email    = parts[0].strip()
        password = parts[1].strip()

        del _admin_state[user_id]

        # Send to buyer
        dm = Msg()
        dm.emoji("check").text(" ").bold("Payment ").italic("Approved!").nl(2)
        dm.emoji("cart").text(" Product: ").bold(cat_name).nl(2)
        dm.emoji("box").text(" ").italic("Your Account Details:").nl()
        dm.text("📧 Email: ").code(email).nl()
        dm.emoji("key").text(" Password: ").code(password).nl(2)
        dm.emoji("pop").text(" ").bold("Thank you").text(" for your purchase!")
        deliver_text, deliver_ent = dm.build()
        await send_msg(buyer_id, deliver_text, deliver_ent,
            keyboard=build_keyboard([[btn("Home", "back_main", emoji_key="back")]]))

        await send_msg(chat_id,
            f"✅ Credentials sent to user `{buyer_id}` for *{cat_name}*.")
        return True

    # ── updateprice flow ───────────────────────────────────────
    if step == "updateprice_pick":
        cats     = _load_categories()
        cat_list = list(cats.values())
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(cat_list):
                raise ValueError
            chosen = cat_list[idx]
        except ValueError:
            chosen = next(
                (c for c in cat_list
                 if c["name"].lower() == text.strip().lower()), None)
        if not chosen:
            await send_msg(chat_id,
                "❌ Category not found. Send the number from the list:")
            return True
        state["data"]["cat_id"]   = chosen["id"]
        state["data"]["cat_name"] = chosen["name"]
        state["data"]["old_price"] = chosen["price"]
        state["step"] = "updateprice_value"
        await send_msg(chat_id,
            f"💰 *{chosen['name']}*\n"
            f"Current price: $ {chosen['price']:.2f}\n\n"
            f"Enter the new price (USD):")
        return True

    if step == "updateprice_value":
        try:
            new_price = float(text.strip())
            if new_price <= 0:
                raise ValueError
        except ValueError:
            await send_msg(chat_id, "❌ Invalid price. Enter a positive number:")
            return True

        cat_id    = state["data"]["cat_id"]
        cat_name  = state["data"]["cat_name"]
        old_price = state["data"]["old_price"]

        async with _cat_lock:
            data = _load_categories()
            if cat_id in data:
                data[cat_id]["price"] = new_price
                _save_categories(data)

        del _admin_state[user_id]
        await send_msg(chat_id,
            f"✅ Price updated!\n\n"
            f"{cat_name}\n"
            f"Old: $ {old_price:.2f} → New: $ {new_price:.2f}")
        return True

    # ── /payments edit flow ────────────────────────────────────
    if step == "find_user":
        query = text.strip().lstrip("@")
        db    = _load_db()
        found = None
        # Search by ID
        if query.isdigit():
            found = db.get(query)
        # Search by username
        if not found:
            for u in db.values():
                if u.get("username","").lower() == query.lower():
                    found = u
                    break
        if not found:
            await send_msg(chat_id, f"❌ User `{query}` not found.")
            del _admin_state[user_id]
            return True
        uid     = found["user_id"]
        uname   = found.get("username") or found.get("first_name") or uid
        balance = found.get("balance", 0.0)
        spent   = found.get("total_spent", 0.0)
        bought  = found.get("products_bought", 0)
        banned  = "🔴 Yes" if found.get("banned") else "✅ No"
        del _admin_state[user_id]
        await send_msg(chat_id,
            f"👤 User: @{uname} (ID: {uid})\n"
            f"💰 Balance: $ {balance:.2f}\n"
            f"💳 Total Spent: $ {spent:.2f}\n"
            f"🛒 Products Bought: {bought}\n"
            f"🚫 Banned: {banned}\n"
            f"📅 Joined: {found.get('joined_at','-')}",
            keyboard=build_keyboard([
                [btn("Adjust Balance", f"adm_adjbal_{uid}", emoji_key="wallet", style="success"),
                 btn("Ban User",       f"adm_banuser_{uid}",emoji_key="cross",  style="danger")],
                [btn("Back to Panel",  "adm_back", emoji_key="back")],
            ])
        )
        return True

    if step == "wallet_adjust_uid":
        query = text.strip().lstrip("@")
        db    = _load_db()
        found = None
        if query.isdigit():
            found = db.get(query)
        if not found:
            for u in db.values():
                if u.get("username","").lower() == query.lower():
                    found = u
                    break
        if not found:
            await send_msg(chat_id, f"❌ User `{query}` not found.")
            del _admin_state[user_id]
            return True
        state["data"]["target_id"]   = found["user_id"]
        state["data"]["target_name"] = found.get("username") or found["user_id"]
        state["step"] = "wallet_adjust_amount"
        await send_msg(chat_id,
            f"💰 Adjust balance for @{state['data']['target_name']}\n"
            f"Current: $ {found.get('balance',0.0):.2f}\n\n"
            f"Send amount (e.g. +5 to add, -3 to deduct):")
        return True

    if step == "wallet_adjust_amount":
        raw = text.strip().replace(" ","")
        try:
            amount = float(raw)
        except ValueError:
            await send_msg(chat_id, "❌ Invalid amount. Send like +5 or -3:")
            return True
        tid  = state["data"]["target_id"]
        name = state["data"]["target_name"]
        await db_add_balance(tid, amount)
        updated = await db_get_user(tid)
        new_bal = updated.get("balance", 0.0) if updated else 0.0
        del _admin_state[user_id]
        sign = "+" if amount >= 0 else ""
        await send_msg(chat_id,
            f"✅ Balance adjusted!\n\n"
            f"User: @{name}\n"
            f"Change: {sign}{amount:.2f} USDT\n"
            f"New Balance: $ {new_bal:.2f}")
        # Notify user
        try:
            nm = Msg()
            nm.emoji("wallet").text(" ").bold("Wallet Updated!").nl(2)
            nm.emoji("balance").text(f" {sign}$ {abs(amount):.2f} USDT").nl()
            nm.emoji("thunder").text(f" New Balance: $ {new_bal:.2f} USDT")
            nt, ne = nm.build()
            await send_msg(int(tid), nt, ne)
        except Exception:
            pass
        return True

    if step == "pay_edit_address":
        network  = state["data"]["network"]
        new_addr = text.strip()
        if not new_addr:
            await send_msg(chat_id, "❌ Address cannot be empty. Send the wallet address:")
            return True
        pays = _load_payments()
        if network in pays:
            pays[network]["address"] = new_addr
            _save_payments(pays)
        del _admin_state[user_id]
        net_label = pays.get(network, {}).get("label", network.upper())
        await send_msg(chat_id,
            f"✅ Address updated!\n\n"
            f"Network: {net_label}\n"
            f"New Address: `{new_addr}`\n\n"
            f"Use /payments to manage all methods.")
        return True

    # ── /broadcast flow ────────────────────────────────────────
    if step == "broadcast_msg":
        # Store the entire raw message for copyMessage
        state["data"]["broadcast_msg"]       = message  # full message dict
        state["data"]["broadcast_from_chat"] = message["chat"]["id"]
        state["data"]["broadcast_message_id"] = message["message_id"]
        del _admin_state[user_id]

        # Send preview header to admin
        preview_m = Msg()
        preview_m.emoji("camera").text(" ").bold("Preview — this is what users will see:").nl()
        pt, pe = preview_m.build()
        await send_msg(chat_id, pt, pe)

        # Copy the message as preview
        await api_call("copyMessage", {
            "chat_id":      chat_id,
            "from_chat_id": message["chat"]["id"],
            "message_id":   message["message_id"],
        })

        # Count users
        db = _load_db()
        user_count = len(db)

        confirm_m = Msg()
        confirm_m.nl().emoji("thunder").text(" ").bold(f"Send to {user_count} users?")
        ct, ce = confirm_m.build()

        # Store broadcast info for confirm callback
        _pending_broadcast[user_id] = {
            "from_chat_id": message["chat"]["id"],
            "message_id":   message["message_id"],
        }

        await send_msg(chat_id, ct, ce, keyboard=build_keyboard([
            [btn("✅  Confirm — Send Now", f"broadcast_confirm_{user_id}", emoji_key="check", style="success")],
            [btn("❌  Cancel",             "broadcast_cancel",              emoji_key="cross",  style="danger")],
        ]))
        return True

    return False


async def handle_message(msg: dict):
    chat_id = msg["chat"]["id"]
    user    = msg.get("from", {})
    user_id = user.get("id")
    text    = msg.get("text", "") or ""

    # ── Only respond in private (DM) chats ────────────────────
    if msg.get("chat", {}).get("type") != "private":
        return

    logger.info(f"[MSG] user_id={user_id} text={repr(text[:50])}")

    # Save / update user in DB on every message
    await db_upsert_user(user)

    # ── Ban check (skip for admins) ────────────────────────────
    if not is_admin(user_id):
        banned, ban_reason = await db_is_banned(user_id)
        if banned:
            lang = await db_get_lang(user_id)
            bm = Msg()
            bm.emoji("cross").text(" ").bold(_t("banned_msg", lang)).nl(2)
            bm.text(_t("banned_reason", lang)).italic(ban_reason).nl(2)
            bm.italic(_t("banned_contact", lang))
            bt, be = bm.build()
            await send_msg(chat_id, bt, be)
            return

    # ── Force Join check (skip for admins) ────────────────────
    if not is_admin(user_id):
        is_member = await check_membership(user_id)
        logger.info(f"[MSG] user_id={user_id} is_member={is_member}")
        if not is_member:
            await send_join_prompt(chat_id)
            return
        
        # Check terms acceptance
        db_data = await db_get_user(user_id)
        terms_accepted = db_data.get("terms_accepted", False) if db_data else False
        logger.info(f"[MSG] user_id={user_id} terms_accepted={terms_accepted}")
        if not terms_accepted:
            lang_text, lang_ent = build_language_select()
            await send_msg(chat_id, lang_text, lang_ent, kb_lang_select())
            return

    # ── Fetch user language early (needed for all translated messages below) ──
    lang = await db_get_lang(user_id)

    # ── Admin multi-step state ─────────────────────────────────
    if is_admin(user_id):
        consumed = await _handle_admin_state(chat_id, user_id, text, msg)
        if consumed:
            return

    # ── Payment screenshot handler ─────────────────────────────
    # If user is in awaiting_screenshot state and sends a photo
    if user_id in _awaiting_screenshot and msg.get("photo"):
        order_id = _awaiting_screenshot.pop(user_id)
        order    = await order_get(order_id)
        if not order or order["status"] not in ("pending_payment", "pending_approval"):
            await send_msg(chat_id, _t("order_inactive", lang))
            return

        # Get the best quality photo (last = largest)
        photos  = msg["photo"]
        file_id = photos[-1]["file_id"]

        # Save screenshot to order
        await order_set_screenshot(order_id, file_id)

        # Forward to admins for approval
        await forward_photo_to_admins(file_id, order_id, order, user)

        # Confirm to user
        cm = Msg()
        cm.emoji("check").text(" ").bold(_t("screenshot_received_title", lang)).nl(2)
        cm.emoji("camera").text(f" {_t('screenshot_order_id', lang)}").code(f"#{order_id[:8].upper()}").nl(2)
        cm.emoji("timer").text(" ").italic(_t("screenshot_under_review", lang)).nl()
        cm.text(_t("screenshot_notify", lang)).nl(2)
        cm.emoji("clock").text(" ").italic(_t("screenshot_usually", lang))
        cm_text, cm_ent = cm.build()
        await send_msg(chat_id, cm_text, cm_ent,
            keyboard=build_keyboard([
                [btn(_t("btn_back_to_home", lang), "back_main", emoji_key="back")]
            ])
        )
        return

    # ── If user is awaiting screenshot but sends text instead ──
    if user_id in _awaiting_screenshot and text and not msg.get("photo"):
        await send_msg(chat_id, _t("screenshot_send_photo", lang))
        return

    # ── BEP20 Txn Hash auto-verify handler ────────────────────
    if user_id in _awaiting_txn_hash and text:
        order_id = _awaiting_txn_hash.get(user_id)
        order    = await order_get(order_id)

        if not order or order["status"] not in ("pending_payment",):
            _awaiting_txn_hash.pop(user_id, None)
            await send_msg(chat_id, _t("order_inactive", lang),
                keyboard=build_keyboard([[btn(_t("btn_shop", lang), "shop", emoji_key="shop")]]))
            return

        txn_hash = text.strip()

        # Show "verifying" message
        vm = Msg()
        vm.emoji("timer").text(" ").bold(_t("bep20_verifying", lang)).nl()
        vm.italic(_t("verify_please_wait", lang))
        vt, ve = vm.build()
        await send_msg(chat_id, vt, ve)

        # Get expected destination address from payments.json
        pay_info    = get_payment("bep20")
        expected_to = pay_info.get("address", "") if pay_info else ""

        if not expected_to:
            await send_msg(chat_id, _t("bep20_not_configured", lang))
            return

        # ── Run verification ──────────────────────────────────
        result = await verify_bep20_txn(txn_hash, expected_to, order["price"])

        if not result["ok"]:
            em = Msg()
            em.emoji("cross").text(" ").bold(_t("verify_failed_title", lang)).nl(2)
            em.text(result["reason"]).nl(2)
            em.emoji("clipboard").text(f" {_t('verify_failed_order', lang)}").bold(order["cat_name"]).nl()
            em.emoji("balance").text(f" {_t('verify_failed_required', lang)}").bold(f"$ {order['price']:.2f} USDT").nl(2)
            em.italic(_t("verify_failed_hint_bep20", lang))
            et, ee = em.build()
            await send_msg(chat_id, et, ee,
                keyboard=build_keyboard([
                    [btn(_t("btn_try_again", lang), f"bep20_retry_{order_id}", emoji_key="arrow", style="success")],
                    [btn(_t("btn_contact_support", lang), url="https://t.me/John_support", emoji_key="support")],
                    [btn(_t("btn_cancel_order", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")],
                ])
            )
            return

        # ── Payment verified ──────────────────────────────────
        _awaiting_txn_hash.pop(user_id, None)
        _mark_txn_used(txn_hash)
        order_type = order.get("order_type", "purchase")

        if order_type == "topup":
            await db_add_balance(user_id, order["price"])
            await order_set_status(order_id, "approved")
            buyer_data  = await db_get_user(user_id)
            new_balance = buyer_data.get("balance", 0.0) if buyer_data else order["price"]
            await post_sale_log(order["cat_name"], order["price"], order_type="topup", user=user)

            sm = Msg()
            sm.emoji("check").text(" ").bold(_t("topup_approved_title", lang)).nl(2)
            sm.emoji("balance").text(f" {_t('topup_approved_added', lang)}").bold(f"$ {order['price']:.2f} USDT").nl()
            sm.emoji("thunder").text(f" {_t('topup_approved_new_balance', lang)}").bold(f"$ {new_balance:.2f} USDT").nl(2)
            sm.emoji("cart").text(" ").italic(_t("topup_approved_hint", lang))
            st, se = sm.build()
            await send_msg(chat_id, st, se,
                keyboard=build_keyboard([[btn(_t("btn_go_to_shop", lang), "shop", emoji_key="shop", style="success")]]))

        else:
            cat_id = order["cat_id"]
            count  = await stock_get_count(cat_id)
            if count <= 0:
                await send_msg(chat_id, _t("stock_empty", lang),
                    keyboard=build_keyboard([[btn(_t("btn_contact_support", lang), url="https://t.me/John_support", emoji_key="support")]]))
                return

            await order_set_status(order_id, "approved")
            await db_record_purchase(user_id, order["price"])
            await post_sale_log(order["cat_name"], order["price"], user=user)

            delivered = await auto_deliver(chat_id, user_id, order)
            if not delivered:
                await send_msg(chat_id, _t("stock_race", lang),
                    keyboard=build_keyboard([[btn(_t("btn_home", lang), "back_main", emoji_key="back")]]))
                uname_str = f"@{user.get('username')}" if user.get("username") else f"ID:{user_id}"
                for admin_id in ADMINS:
                    await send_msg(admin_id,
                        f"⚠️ STOCK EMPTY — Manual Delivery Needed\n\n"
                        f"🛒 Product: {order['cat_name']}\n"
                        f"💰 Amount: $ {order['price']:.2f} USDT\n"
                        f"👤 User: {uname_str}\n"
                        f"🔗 Txn: {txn_hash}\n\n"
                        f"Please deliver manually and restock.")
            else:
                uname_str = f"@{user.get('username')}" if user.get("username") else f"ID:{user_id}"
                for admin_id in ADMINS:
                    await send_msg(admin_id,
                        f"✅ AUTO-DELIVERED — BEP20 Payment\n\n"
                        f"🛒 Product: {order['cat_name']}\n"
                        f"💰 Amount: $ {order['price']:.2f} USDT\n"
                        f"👤 User: {uname_str}\n"
                        f"🔗 Txn: {txn_hash[:20]}…\n"
                        f"📦 Stock remaining: {await stock_get_count(order['cat_id'])}"
                    )
        return

    # ── TRC20 Txn Hash auto-verify handler ────────────────────
    if user_id in _awaiting_trx_hash and text:
        order_id = _awaiting_trx_hash.get(user_id)
        order    = await order_get(order_id)

        if not order or order["status"] not in ("pending_payment",):
            _awaiting_trx_hash.pop(user_id, None)
            await send_msg(chat_id, _t("order_inactive", lang),
                keyboard=build_keyboard([[btn(_t("btn_shop", lang), "shop", emoji_key="shop")]]))
            return

        txn_hash = text.strip()

        # Show "verifying" message
        vm = Msg()
        vm.emoji("timer").text(" ").bold(_t("trx_verifying", lang)).nl()
        vm.italic(_t("verify_please_wait", lang))
        vt, ve = vm.build()
        await send_msg(chat_id, vt, ve)

        pay_info    = get_payment("trx")
        expected_to = pay_info.get("address", "") if pay_info else ""

        if not expected_to:
            await send_msg(chat_id, _t("trx_not_configured", lang))
            return

        result = await verify_trc20_txn(txn_hash, expected_to, order["price"])

        if not result["ok"]:
            em = Msg()
            em.emoji("cross").text(" ").bold(_t("verify_failed_title", lang)).nl(2)
            em.text(result["reason"]).nl(2)
            em.emoji("clipboard").text(f" {_t('verify_failed_order', lang)}").bold(order["cat_name"]).nl()
            em.emoji("balance").text(f" {_t('verify_failed_required', lang)}").bold(f"$ {order['price']:.2f} USDT").nl(2)
            em.italic(_t("verify_failed_hint_trx", lang))
            et, ee = em.build()
            await send_msg(chat_id, et, ee,
                keyboard=build_keyboard([
                    [btn(_t("btn_try_again", lang), f"trx_retry_{order_id}", emoji_key="arrow", style="success")],
                    [btn(_t("btn_contact_support", lang), url="https://t.me/John_support", emoji_key="support")],
                    [btn(_t("btn_cancel_order", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")],
                ])
            )
            return

        _awaiting_trx_hash.pop(user_id, None)
        _mark_txn_used(txn_hash)
        order_type = order.get("order_type", "purchase")

        if order_type == "topup":
            await db_add_balance(user_id, order["price"])
            await order_set_status(order_id, "approved")
            buyer_data  = await db_get_user(user_id)
            new_balance = buyer_data.get("balance", 0.0) if buyer_data else order["price"]
            await post_sale_log(order["cat_name"], order["price"], order_type="topup", user=user)

            sm = Msg()
            sm.emoji("check").text(" ").bold(_t("topup_approved_title", lang)).nl(2)
            sm.emoji("balance").text(f" {_t('topup_approved_added', lang)}").bold(f"$ {order['price']:.2f} USDT").nl()
            sm.emoji("thunder").text(f" {_t('topup_approved_new_balance', lang)}").bold(f"$ {new_balance:.2f} USDT").nl(2)
            sm.emoji("cart").text(" ").italic(_t("topup_approved_hint", lang))
            st, se = sm.build()
            await send_msg(chat_id, st, se,
                keyboard=build_keyboard([[btn(_t("btn_go_to_shop", lang), "shop", emoji_key="shop", style="success")]]))

        else:
            cat_id = order["cat_id"]
            count  = await stock_get_count(cat_id)
            if count <= 0:
                await send_msg(chat_id, _t("stock_empty", lang),
                    keyboard=build_keyboard([[btn(_t("btn_contact_support", lang), url="https://t.me/John_support", emoji_key="support")]]))
                return

            await order_set_status(order_id, "approved")
            await db_record_purchase(user_id, order["price"])
            await post_sale_log(order["cat_name"], order["price"], user=user)

            delivered = await auto_deliver(chat_id, user_id, order)
            if not delivered:
                await send_msg(chat_id, _t("stock_race", lang),
                    keyboard=build_keyboard([[btn(_t("btn_home", lang), "back_main", emoji_key="back")]]))
                uname_str = f"@{user.get('username')}" if user.get("username") else f"ID:{user_id}"
                for admin_id in ADMINS:
                    await send_msg(admin_id,
                        f"⚠️ STOCK EMPTY — Manual Delivery Needed\n\n"
                        f"🛒 Product: {order['cat_name']}\n"
                        f"💰 Amount: $ {order['price']:.2f} USDT\n"
                        f"👤 User: {uname_str}\n"
                        f"🔗 TxID (TRC20): {txn_hash}\n\n"
                        f"Please deliver manually and restock.")
            else:
                uname_str = f"@{user.get('username')}" if user.get("username") else f"ID:{user_id}"
                for admin_id in ADMINS:
                    await send_msg(admin_id,
                        f"✅ AUTO-DELIVERED — TRC20 Payment\n\n"
                        f"🛒 Product: {order['cat_name']}\n"
                        f"💰 Amount: $ {order['price']:.2f} USDT\n"
                        f"👤 User: {uname_str}\n"
                        f"🔗 TxID: {txn_hash[:20]}…\n"
                        f"📦 Stock remaining: {await stock_get_count(order['cat_id'])}"
                    )
        return

    # ── Custom quantity input ──────────────────────────────────
    if user_id in _awaiting_custom_qty and text:
        state  = _awaiting_custom_qty.get(user_id, {})
        cat_id = state.get("cat_id")
        max_qty = state.get("max_qty", 9999)
        try:
            qty = int(text.strip())
            if qty < 1:
                raise ValueError
        except ValueError:
            await send_msg(chat_id, _t("qty_invalid", lang, max=max_qty))
            return
        if qty > max_qty:
            await send_msg(chat_id, _t("qty_exceeds", lang, max=max_qty))
            return

        _awaiting_custom_qty.pop(user_id)
        _qty_state[user_id] = {"cat_id": cat_id, "qty": qty}

        cats  = _load_categories()
        cat   = cats.get(cat_id)
        count = await stock_count(cat_id)
        if not cat:
            await send_msg(chat_id, "❌ Product not found.")
            return

        unit_price = get_bulk_price(cat["price"], qty)
        total      = round(unit_price * qty, 2)
        msg_text, msg_ent = build_qty_selector_msg(cat, qty, count, lang)
        kb = build_qty_keyboard(cat_id, qty, count, unit_price, total, lang)
        await send_msg(chat_id, msg_text, msg_ent, kb)
        return

    # ── Top-up amount input ────────────────────────────────────
    if user_id in _awaiting_topup_amount and text:
        try:
            amount = float(text.strip())
        except ValueError:
            await send_msg(chat_id, _t("topup_invalid_amount", lang))
            return
        if amount < 0.1:
            await send_msg(chat_id, _t("topup_too_low", lang))
            return

        _awaiting_topup_amount.pop(user_id)

        order_id = await order_create(
            user_id, "wallet_topup", f"Wallet Top Up — $ {amount:.2f} USDT", amount,
            order_type="topup"
        )

        # Show payment method selection (same as buy flow)
        sm = Msg()
        sm.emoji("wallet").text(" ").bold(_t("topup_summary_title", lang)).nl(2)
        sm.emoji("balance").text(f" {_t('topup_amount_label', lang)}").bold(f"$ {amount:.2f}").text(" USDT").nl(2)
        sm.emoji("usdt").text(" ").bold(_t("topup_choose_network", lang))
        sm_text, sm_ent = sm.build()

        enabled_pays = get_enabled_payments()
        pay_emoji_map = {"bep20": "bep20"}
        pay_style_map = {"bep20": "success"}
        pay_btn_rows = [
            [btn(f"{v['label']}", f"topup_{k}_{order_id}",
                 emoji_key=pay_emoji_map.get(k), style=pay_style_map.get(k, "success"))]
            for k, v in enabled_pays.items()
        ]
        if not pay_btn_rows:
            pay_btn_rows = [[btn(_t("no_payment_methods", lang), "noop")]]
        pay_btn_rows.append([btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")])
        kb = build_keyboard(pay_btn_rows)
        await send_msg(chat_id, sm_text, sm_ent, kb)
        return

    # ── Admin commands ─────────────────────────────────────────

    if text == "/admin":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        t, ent, kb = await build_admin_panel()
        await send_msg(chat_id, t, ent, kb)
        return

    if text.startswith("/ban"):
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        parts     = text.split()
        target_id = parts[1].strip() if len(parts) > 1 else ""
        if not target_id:
            await send_msg(chat_id, "❌ Usage: /ban {user_id}\nExample: /ban 123456789")
            return
        # Check if user exists
        target_data = await db_get_user(target_id)
        target_name = target_data.get("username") or target_data.get("first_name") or target_id if target_data else target_id
        # Ask admin for reason
        _admin_state[user_id] = {
            "step": "ban_reason",
            "data": {"target_id": target_id}
        }
        await send_msg(chat_id,
            f"🔨 Banning user: {target_name} (`{target_id}`)\n\n"
            f"📝 Enter the ban reason:")
        return

    if text.startswith("/unban"):
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        parts     = text.split()
        target_id = parts[1].strip() if len(parts) > 1 else ""
        if not target_id:
            await send_msg(chat_id, "❌ Usage: /unban {user_id}\nExample: /unban 123456789")
            return
        await db_unban_user(target_id)
        # Notify the unbanned user
        try:
            user_lang = await db_get_lang(int(target_id))
            um = Msg()
            um.emoji("check").text(" ").bold(_t("unbanned_msg", user_lang)).nl(2)
            um.italic(_t("unbanned_hint", user_lang))
            ut, ue = um.build()
            await send_msg(int(target_id), ut, ue)
        except Exception:
            pass
        await send_msg(chat_id, f"✅ User `{target_id}` has been unbanned.")
        return

    if text == "/payments":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        pays = _load_payments()
        rows = []
        for k, v in pays.items():
            status_icon = "✅" if v.get("enabled") else "🔴"
            addr = v.get("address", "")
            addr_preview = addr[:10] + "..." if len(addr) > 10 else (addr if addr else "NOT SET")
            rows.append([btn(f"{status_icon} {v['label']} — {addr_preview}", f"pay_mgr_{k}")])
        rows.append([btn("Add / Update Address", "pay_mgr_menu", style="success")])
        rows.append([btn("Close", "noop", style="danger")])
        await send_msg(chat_id,
            "💳 Payment Methods Manager\n\nTap a method to Edit / Enable / Disable:",
            keyboard=build_keyboard(rows))
        return

    if text == "/addcategory":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        _admin_state[user_id] = {"step": "addcat_name", "data": {}}
        await send_msg(chat_id, "📝 Enter the category name:")
        return

    if text == "/addstock":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        cats = _load_categories()
        if not cats:
            await send_msg(chat_id, "❌ No categories yet. Use /addcategory first.")
            return
        # Step 1: Ask what type of stock to add
        _admin_state[user_id] = {"step": "addstock_type", "data": {}}
        await send_msg(chat_id,
            "📦 *Add Stock*\n\nWhat type of stock do you want to add?",
            keyboard=build_keyboard([
                [btn("🔗  Link",      "addstock_type_link",      style="success")],
                [btn("🔐  ID & Pass", "addstock_type_id_pass",   style="success")],
                [btn("🎁  Freebies",  "addstock_type_freebies",  style="success")],
            ])
        )
        return

    if text == "/removestock":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        cats = _load_categories()
        if not cats:
            await send_msg(chat_id, "❌ No categories found.")
            return
        lines = ["🗑️ Remove Stock - Select a category (send its number):\n"]
        for i, cat in enumerate(cats.values(), 1):
            count      = await stock_count(cat["id"])
            cat_type   = cat.get("cat_type", "id_pass")
            type_label = "🔗" if cat_type == "link" else "🔐"
            lines.append(f"{i}. {cat.get('emoji_char','🛒')} {cat['name']}"
                         f" — $ {cat['price']:.2f} USDT  |  Stock: {count}")
        _admin_state[user_id] = {"step": "removestock_pick", "data": {}}
        await send_msg(chat_id, "\n".join(lines))
        return

    if text == "/deletecategory":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        cats = _load_categories()
        if not cats:
            await send_msg(chat_id, "❌ No categories to delete.")
            return
        lines = ["🗑️ Select a category to DELETE (send its number):\n"]
        for i, cat in enumerate(cats.values(), 1):
            count = await stock_count(cat["id"])
            lines.append(f"{i}. {cat.get('emoji_char','🛒')} {cat['name']}"
                         f" — $ {cat['price']:.2f} USDT  |  Stock: {count}")
        _admin_state[user_id] = {"step": "delcat_pick", "data": {}}
        await send_msg(chat_id, "\n".join(lines))
        return

    if text == "/updateprice":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        cats = _load_categories()
        if not cats:
            await send_msg(chat_id, "❌ No categories yet. Use /addcategory first.")
            return
        lines = ["💰 Select a category to update its price (send its number):\n"]
        for i, cat in enumerate(cats.values(), 1):
            lines.append(f"{i}. {cat.get('emoji_char','🛒')} {cat['name']}"
                         f" — $ {cat['price']:.2f} USDT")
        _admin_state[user_id] = {"step": "updateprice_pick", "data": {}}
        await send_msg(chat_id, "\n".join(lines))
        return

    if text == "/broadcast":
        if not is_admin(user_id):
            await send_msg(chat_id, "⛔ You are not authorized.")
            return
        _admin_state[user_id] = {"step": "broadcast_msg", "data": {}}
        m = Msg()
        m.emoji("thunder").text(" ").bold("Broadcast Mode").nl(2)
        m.text("Send the message you want to broadcast to all users.").nl(2)
        m.emoji("check").text(" Text, photo, video — anything works").nl()
        m.emoji("check").text(" Premium emojis, bold, italic — all preserved").nl()
        m.emoji("check").text(" You'll get a preview before sending")
        t, ent = m.build()
        await send_msg(chat_id, t, ent, keyboard=build_keyboard([[btn("Cancel", "broadcast_cancel", emoji_key="cross", style="danger")]]))
        return

    # ── Regular commands ───────────────────────────────────────
    # lang already fetched above

    if text.startswith("/start"):
        t, ent = build_welcome(lang)
        await send_msg(chat_id, t, ent, kb_main(lang))

    elif text == "/home":
        t, ent = build_welcome(lang)
        await send_msg(chat_id, t, ent, kb_main(lang))

    elif text == "/shop":
        cats   = await cat_get_all()
        counts = {cid: await stock_count(cid) for cid in cats}
        t, ent = build_shop(lang, cats, counts)
        kb     = kb_shop(cats, counts, lang) if cats else kb_back(lang)
        await send_msg(chat_id, t, ent, kb)

    elif text == "/profile":
        db_data = await db_get_user(user_id)
        await send_profile(chat_id, user, db_data, kb_profile(lang))

    elif text == "/wallet" or text == "/balance":
        db_data = await db_get_user(user_id)
        balance = db_data.get("balance", 0.0) if db_data else 0.0
        t, ent  = build_wallet(balance, lang)
        await send_msg(chat_id, t, ent, kb_wallet(lang))

    elif text == "/deposit" or text == "/topup":
        db_data = await db_get_user(user_id)
        balance = db_data.get("balance", 0.0) if db_data else 0.0
        t, ent  = build_topup_prompt(balance, lang)
        _awaiting_topup_amount[user_id] = True
        await send_msg(chat_id, t, ent,
            keyboard=build_keyboard([[btn(_t("btn_cancel", lang), "wallet", emoji_key="cross", style="danger")]])
        )

    elif text == "/referral" or text == "/refer" or text == "/invite":
        uname = await get_bot_username()
        link  = f"https://t.me/{uname}?start=ref_{user_id}"
        t, ent = build_referral(link, lang)
        await send_msg(chat_id, t, ent, kb_referral(link, lang))

    elif text == "/menu":
        t, ent = build_menu(lang)
        await send_msg(chat_id, t, ent, kb_menu(lang))

    elif text == "/ping":
        t, ent = build_ping(lang)
        await send_msg(chat_id, t, ent)

    elif text == "/history":
        async with _ord_lock:
            all_orders = _load_orders()
        user_orders = [
            o for o in all_orders.values()
            if o["user_id"] == str(user_id)
        ]
        user_orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        recent = user_orders[:5]

        m = Msg()
        m.emoji("clipboard").text(" ").bold(_t("history_title", lang)).nl(2)
        if not recent:
            m.emoji("box").text(" ").italic(_t("history_empty", lang)).nl(2)
            m.text(_t("history_start_shopping", lang))
        else:
            for o in recent:
                status = o["status"]
                if status == "approved":
                    m.emoji("check")
                elif status in ("pending_payment", "pending_approval"):
                    m.emoji("timer")
                else:
                    m.emoji("cross")
                m.text(" ").bold(o["cat_name"]).nl()
                m.emoji("balance").text(f" $ {o['price']:.2f}").text(f"  •  {o['created_at'][:10]}").nl(2)
        t, ent = m.build()
        await send_msg(chat_id, t, ent,
            keyboard=build_keyboard([[btn("Home", "back_main", emoji_key="back")]])
        )

    elif text == "/help" or text == "/commands":
        t, ent = build_help(lang)
        await send_msg(chat_id, t, ent, kb_home(lang))

    elif text == "/test":
        t, ent = build_test()
        await send_msg(chat_id, t, ent)

    # ── Product shortcut commands ──────────────────────────────
    elif text.startswith("/"):
        # Try to match command with product name (e.g., /telegram, /netflix)
        command = text[1:].lower().strip()
        cats = _load_categories()
        
        # Try to find matching category by command
        matched_cat = None
        for cat_id, cat in cats.items():
            cat_name_clean = cat["name"].lower().replace(" ", "").replace("-", "")
            # Check if command matches category ID or simplified name
            if cat_id.lower() == command or command in cat_name_clean:
                matched_cat = (cat_id, cat)
                break
        
        if matched_cat:
            cat_id, cat = matched_cat
            count = await stock_count(cat_id)
            
            # Build product detail message
            description = cat.get("description", "").strip()
            desc_entities = cat.get("desc_entities", [])
            if count >= 999:
                stock_status_text = _t("prod_stock_available", lang)
            elif count > 0:
                stock_status_text = _t("prod_stock_count", lang, count=count)
            else:
                stock_status_text = _t("prod_stock_out", lang)

            if description:
                # Replace stock placeholders with real count
                description = inject_stock_count(description, count)

                # Check if description has stored entities (new system) or placeholders (old system)
                if desc_entities:
                    # NEW SYSTEM: Use stored premium emoji entities
                    cat_emoji = cat.get('emoji_char', '🛒')
                    header = f"{cat_emoji} "
                    
                    m = Msg()
                    m.text(header).bold(cat["name"]).nl(2)
                    header_text, header_entities = m.build()
                    
                    desc_offset = u16(header_text)
                    
                    footer = Msg()
                    footer.nl().text("━━━━━━━━━━━━━━━━").nl()
                    footer.emoji("balance").text(f" {_t('prod_price', lang)}").bold(f"$ {cat['price']:.2f} USDT").nl()
                    footer.emoji("box").text(f" {_t('prod_stock', lang)}{stock_status_text}")
                    footer_text, footer_entities = footer.build()
                    
                    full_text = header_text + description + footer_text
                    
                    adjusted_desc_entities = []
                    for ent in desc_entities:
                        adjusted_ent = {
                            "type": ent.get("type"),
                            "offset": ent.get("offset", 0) + desc_offset,
                            "length": ent.get("length", 1),
                            "custom_emoji_id": str(ent.get("custom_emoji_id", ""))
                        }
                        adjusted_desc_entities.append(adjusted_ent)
                    
                    footer_offset = desc_offset + u16(description)
                    adjusted_footer_entities = []
                    for ent in footer_entities:
                        adjusted_ent = dict(ent)
                        adjusted_ent["offset"] = ent.get("offset", 0) + footer_offset
                        adjusted_footer_entities.append(adjusted_ent)
                    
                    text = full_text
                    entities = header_entities + adjusted_desc_entities + adjusted_footer_entities
                else:
                    # OLD SYSTEM: Process {{placeholder}} style descriptions
                    m = Msg()
                    cat_emoji = cat.get('emoji_char', '🛒')
                    m.text(f"{cat_emoji} ").bold(cat["name"]).nl(2)
                    
                    placeholder_map = {
                        "{{balance}}": "balance", "{{check}}": "check", "{{cart}}": "cart",
                        "{{key}}": "key", "{{box}}": "box", "{{pop}}": "pop",
                        "{{clock}}": "clock", "{{timer}}": "timer", "{{camera}}": "camera",
                        "{{thunder}}": "thunder", "{{arrow}}": "arrow", "{{clipboard}}": "clipboard",
                        "{{cross}}": "cross", "{{checkmark}}": "checkmark",
                    }
                    
                    for line in description.splitlines():
                        stripped = line.strip()
                        if not stripped:
                            m.nl()
                            continue
                        
                        has_placeholder = any(p in stripped for p in placeholder_map.keys())
                        
                        if has_placeholder:
                            remaining = stripped
                            while remaining:
                                first_pos = len(remaining)
                                first_placeholder = None
                                first_key = None
                                
                                for placeholder, emoji_key in placeholder_map.items():
                                    pos = remaining.find(placeholder)
                                    if pos != -1 and pos < first_pos:
                                        first_pos = pos
                                        first_placeholder = placeholder
                                        first_key = emoji_key
                                
                                if first_placeholder:
                                    if first_pos > 0:
                                        m.text(remaining[:first_pos])
                                    m.emoji(first_key)
                                    remaining = remaining[first_pos + len(first_placeholder):]
                                else:
                                    m.text(remaining)
                                    break
                            m.nl()
                        else:
                            if stripped.startswith(("•", "-", "▶", "▸")):
                                m.text(stripped).nl()
                            elif stripped.endswith(":") and len(stripped) <= 40:
                                m.bold(stripped).nl()
                            else:
                                m.text(stripped).nl()
                    
                    m.nl().text("━━━━━━━━━━━━━━━━").nl()
                    m.emoji("balance").text(f" {_t('prod_price', lang)}").bold(f"$ {cat['price']:.2f} USDT").nl()
                    m.emoji("box").text(f" {_t('prod_stock', lang)}{stock_status_text}")
                    text, entities = m.build()
            else:
                m = Msg()
                m.text(f"{cat.get('emoji_char', '🛒')} ").bold(cat["name"]).nl(2)
                m.emoji("balance").text(f"  {_t('prod_price', lang)}").bold(f"$ {cat['price']:.2f} USDT").nl()
                m.emoji("box").text(f"  {_t('prod_stock', lang)}{stock_status_text}").nl(2)
                if count > 0:
                    m.emoji("check").text(f" {_t('prod_tap_buy', lang)}")
                else:
                    m.emoji("timer").text(f" {_t('prod_check_back', lang)}")
                text, entities = m.build()

            kb = build_keyboard([
                [btn(_t("btn_buy_now", lang), f"buy_{cat_id}", emoji_key="cart", style="success")] if count > 0 else
                [btn(_t("btn_out_of_stock", lang), "noop", emoji_key="cross", style="danger")],
                [btn(_t("btn_back_to_shop", lang), "shop", emoji_key="back")],
            ])
            await send_msg(chat_id, text, entities or None, kb)


async def handle_callback(cq: dict):
    cq_id   = cq["id"]
    user    = cq.get("from", {})
    data    = cq.get("data", "")
    msg     = cq.get("message", {})
    mid     = msg.get("message_id")
    chat_id = msg.get("chat", {}).get("id")

    # ── Only respond in private (DM) chats ────────────────────
    if msg.get("chat", {}).get("type") != "private":
        await answer_cb(cq_id)
        return

    # Save / update user in DB on every callback
    await db_upsert_user(user)

    user_id = user.get("id")

    # ── Ban check (skip for admins) ────────────────────────────
    if not is_admin(user_id):
        banned, ban_reason = await db_is_banned(user_id)
        if banned:
            await answer_cb(cq_id, "🚫 You are banned from this bot.", alert=True)
            return

    # ── Language / Terms callbacks — handle BEFORE membership check ──
    if data.startswith("lang_select_"):
        new_lang = data[12:]  # en, zh, ru, vi
        if new_lang not in ("en", "zh", "ru", "vi"):
            await answer_cb(cq_id, "❌ Unknown language.", alert=True)
            return
        await answer_cb(cq_id)
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})

        # If user already accepted terms, just change language and go home
        db_data = await db_get_user(user_id)
        if db_data and db_data.get("terms_accepted"):
            await db_accept_terms(user_id, new_lang)
            t, ent = build_welcome(new_lang)
            await send_msg(chat_id, t, ent, kb_main(new_lang))
        else:
            # New user — show terms in selected language
            t, ent = build_terms_lang(new_lang)
            await send_msg(chat_id, t, ent, kb_terms_accept(new_lang))
        return

    if data.startswith("accept_terms"):
        user_id = user.get("id")
        # Extract lang from callback: accept_terms_en / accept_terms_zh etc.
        lang = "en"
        if "_" in data[len("accept_terms"):]:
            lang = data.split("_")[-1]
            if lang not in ("en", "zh", "ru", "vi"):
                lang = "en"
        await db_accept_terms(user_id, lang)
        await answer_cb(cq_id, _t("terms_welcome", lang), alert=False)
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        t, ent = build_welcome(lang)
        await send_msg(chat_id, t, ent, kb_main(lang))
        return

    if data == "decline_terms":
        # Extract lang from callback data if available, else default to en
        cb_lang = data.split("_")[-1] if data.endswith(("_en","_zh","_ru","_vi")) else "en"
        await answer_cb(cq_id, _t("decline_terms", cb_lang), alert=True)
        return

    # ── check_join + Force Join + Terms gate (non-admins only) ──
    if not is_admin(user_id):
        user_id   = user.get("id")
        is_member = await check_membership(user_id)

        if data == "check_join":
            if is_member:
                db_data = await db_get_user(user_id)
                terms_accepted = db_data.get("terms_accepted", False) if db_data else False
                if not terms_accepted:
                    await answer_cb(cq_id, _t("check_join_verified", "en"), alert=False)
                    await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
                    lang_text, lang_ent = build_language_select()
                    await send_msg(chat_id, lang_text, lang_ent, kb_lang_select())
                else:
                    ul = await db_get_lang(user_id)
                    await answer_cb(cq_id, _t("check_join_welcome_back", ul), alert=False)
                    await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
                    t, ent = build_welcome(ul)
                    await send_msg(chat_id, t, ent, kb_main(ul))
            else:
                await answer_cb(cq_id, _t("check_join_not_joined", "en"), alert=True)
            return

        if not is_member:
            await answer_cb(cq_id)
            await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
            await send_join_prompt(chat_id)
            return

        db_data = await db_get_user(user_id)
        terms_accepted = db_data.get("terms_accepted", False) if db_data else False
        if not terms_accepted:
            await answer_cb(cq_id)
            await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
            lang_text, lang_ent = build_language_select()
            await send_msg(chat_id, lang_text, lang_ent, kb_lang_select())
            return

    await answer_cb(cq_id)

    lang = await db_get_lang(user.get("id"))

    if data == "back_main":
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        t, ent = build_welcome(lang)
        await send_msg(chat_id, t, ent, kb_main(lang))

    elif data == "change_language":
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        lang_text, lang_ent = build_language_select()
        await send_msg(chat_id, lang_text, lang_ent, kb_lang_select())

    elif data == "shop":
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        cats   = await cat_get_all()
        counts = {cid: await stock_count(cid) for cid in cats}
        t, ent = build_shop(lang, cats, counts)
        kb     = kb_shop(cats, counts, lang) if cats else kb_back(lang)
        await send_msg(chat_id, t, ent, kb)

    elif data == "freebies":
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        all_cats = await cat_get_all()
        # Filter only freebies categories
        cats   = {k: v for k, v in all_cats.items() if v.get("cat_type") == "freebies"}
        counts = {cid: await stock_count(cid) for cid in cats}

        m = Msg()
        m.emoji("gift").text(" ").bold(_t("freebies_title", lang)).nl(2)
        m.emoji("thunder").text(" ").bold(_t("freebies_subtitle", lang))
        t, ent = m.build()

        if cats:
            kb = kb_shop(cats, counts, lang)
        else:
            m2 = Msg()
            m2.emoji("timer").text(" ").italic(_t("freebies_empty", lang))
            t, ent = m2.build()
            kb = build_keyboard([[btn(_t("btn_back", lang), "back_main", emoji_key="back")]])
        await send_msg(chat_id, t, ent, kb)

    elif data == "profile":
        db_data = await db_get_user(user.get("id"))
        await edit_profile(chat_id, mid, user, db_data, kb_profile(lang))

    elif data == "wallet":
        db_data = await db_get_user(user.get("id"))
        balance = db_data.get("balance", 0.0) if db_data else 0.0
        t, ent  = build_wallet(balance, lang)
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        await send_msg(chat_id, t, ent, kb_wallet(lang))

    elif data == "referral":
        uname = await get_bot_username()
        link  = f"https://t.me/{uname}?start=ref_{user.get('id')}"
        t, ent = build_referral(link, lang)
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        await send_msg(chat_id, t, ent, kb_referral(link, lang))

    elif data == "menu":
        t, ent = build_menu(lang)
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        await send_msg(chat_id, t, ent, kb_menu(lang))

    elif data == "add_balance":
        user_id = user.get("id")
        db_data = await db_get_user(user_id)
        balance = db_data.get("balance", 0.0) if db_data else 0.0
        t, ent  = build_topup_prompt(balance, lang)
        _awaiting_topup_amount[user_id] = True
        await edit_msg(chat_id, mid, t, ent,
            keyboard=build_keyboard([[btn(_t("btn_cancel", lang), "wallet", emoji_key="cross", style="danger")]])
        )

    elif data == "topup_wallet":
        user_id = user.get("id")
        db_data = await db_get_user(user_id)
        balance = db_data.get("balance", 0.0) if db_data else 0.0
        t, ent  = build_topup_prompt(balance, lang)
        _awaiting_topup_amount[user_id] = True
        await edit_msg(chat_id, mid, t, ent,
            keyboard=build_keyboard([[btn(_t("btn_cancel", lang), "wallet", emoji_key="cross", style="danger")]])
        )

    elif data.startswith("topup_bep20_") or data.startswith("topup_trx_") or data.startswith("topup_btc_"):
        # Show payment details for top-up (any network)
        if data.startswith("topup_bep20_"):
            network = "bep20"; order_id = data[12:]
        elif data.startswith("topup_trx_"):
            network = "trx"; order_id = data[10:]
        else:
            network = "btc"; order_id = data[10:]

        order   = await order_get(order_id)
        user_id = user.get("id")

        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["user_id"] != str(user_id):
            await answer_cb(cq_id, "⛔ Unauthorized.", alert=True)
            return
        if order["status"] not in ("pending_payment",):
            await answer_cb(cq_id, "⚠️ Order already processed.", alert=True)
            return

        # Save selected network to order
        await order_set_network(order_id, network)

        caption, cap_entities = build_payment_caption(_t("pay_topup_title", lang), order["price"],
                                                       network=network)
        net_images = {
            "bep20": USDT_BEP20_IMAGE, "trx": USDT_TRX_IMAGE,
            "btc": BTC_IMAGE,
        }
        qr_image = net_images[network]

        if network == "bep20":
            done_btn_text = _t("btn_ive_paid_txhash", lang)
        else:
            done_btn_text = _t("btn_ive_paid_screenshot", lang)

        kb = build_keyboard([
            [btn(done_btn_text, f"done_{order_id}", emoji_key="check", style="success")],
            [btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")],
        ])
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        if os.path.exists(qr_image):
            await send_local_photo(chat_id, qr_image, caption, kb, cap_entities)
        else:
            await send_msg(chat_id, caption, cap_entities, kb)

    elif data.startswith("cat_"):
        cat_id = data[4:]
        cats   = _load_categories()
        cat    = cats.get(cat_id)
        if not cat:
            await answer_cb(cq_id, "❌ Category not found.", alert=True)
            return
        count = await stock_count(cat_id)

        # ── Build product detail message ──────────────────────
        description = cat.get("description", "").strip()
        desc_entities = cat.get("desc_entities", [])
        if count >= 999:
            stock_status_text = _t("prod_stock_available", lang)
        elif count > 0:
            stock_status_text = _t("prod_stock_count", lang, count=count)
        else:
            stock_status_text = _t("prod_stock_out", lang)

        if description:
            # Replace stock placeholders with real count
            description = inject_stock_count(description, count)

            # Check if description has stored entities (new system) or placeholders (old system)
            if desc_entities:
                # NEW SYSTEM: Use stored premium emoji entities
                cat_emoji = cat.get('emoji_char', '🛒')
                header = f"{cat_emoji} "
                
                m = Msg()
                m.text(header).bold(cat["name"]).nl(2)
                header_text, header_entities = m.build()
                
                desc_offset = u16(header_text)
                
                footer = Msg()
                footer.nl().text("━━━━━━━━━━━━━━━━").nl()
                footer.emoji("balance").text(f" {_t('prod_price', lang)}").bold(f"$ {cat['price']:.2f} USDT").nl()
                footer.emoji("box").text(f" {_t('prod_stock', lang)}{stock_status_text}")
                footer_text, footer_entities = footer.build()
                
                full_text = header_text + description + footer_text
                
                adjusted_desc_entities = []
                for ent in desc_entities:
                    adjusted_ent = {
                        "type": ent.get("type"),
                        "offset": ent.get("offset", 0) + desc_offset,
                        "length": ent.get("length", 1),
                        "custom_emoji_id": str(ent.get("custom_emoji_id", ""))
                    }
                    adjusted_desc_entities.append(adjusted_ent)
                
                footer_offset = desc_offset + u16(description)
                adjusted_footer_entities = []
                for ent in footer_entities:
                    adjusted_ent = dict(ent)
                    adjusted_ent["offset"] = ent.get("offset", 0) + footer_offset
                    adjusted_footer_entities.append(adjusted_ent)
                
                text = full_text
                entities = header_entities + adjusted_desc_entities + adjusted_footer_entities
            else:
                # OLD SYSTEM: Process {{placeholder}} style descriptions
                m = Msg()
                cat_emoji = cat.get('emoji_char', '🛒')
                m.text(f"{cat_emoji} ").bold(cat["name"]).nl(2)
                
                placeholder_map = {
                    "{{balance}}": "balance", "{{check}}": "check", "{{cart}}": "cart",
                    "{{key}}": "key", "{{box}}": "box", "{{pop}}": "pop",
                    "{{clock}}": "clock", "{{timer}}": "timer", "{{camera}}": "camera",
                    "{{thunder}}": "thunder", "{{arrow}}": "arrow", "{{clipboard}}": "clipboard",
                    "{{cross}}": "cross", "{{checkmark}}": "checkmark",
                }
                
                for line in description.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        m.nl()
                        continue
                    
                    has_placeholder = any(p in stripped for p in placeholder_map.keys())
                    
                    if has_placeholder:
                        remaining = stripped
                        while remaining:
                            first_pos = len(remaining)
                            first_placeholder = None
                            first_key = None
                            
                            for placeholder, emoji_key in placeholder_map.items():
                                pos = remaining.find(placeholder)
                                if pos != -1 and pos < first_pos:
                                    first_pos = pos
                                    first_placeholder = placeholder
                                    first_key = emoji_key
                            
                            if first_placeholder:
                                if first_pos > 0:
                                    m.text(remaining[:first_pos])
                                m.emoji(first_key)
                                remaining = remaining[first_pos + len(first_placeholder):]
                            else:
                                m.text(remaining)
                                break
                        m.nl()
                    else:
                        if stripped.startswith(("•", "-", "▶", "▸")):
                            m.text(stripped).nl()
                        elif stripped.endswith(":") and len(stripped) <= 40:
                            m.bold(stripped).nl()
                        else:
                            m.text(stripped).nl()
                
                m.nl().text("━━━━━━━━━━━━━━━━").nl()
                m.emoji("balance").text(f" {_t('prod_price', lang)}").bold(f"$ {cat['price']:.2f} USDT").nl()
                m.emoji("box").text(f" {_t('prod_stock', lang)}{stock_status_text}")
                text, entities = m.build()
        else:
            # No description fallback
            m = Msg()
            m.text(f"{cat.get('emoji_char', '🛒')} ").bold(cat["name"]).nl(2)
            if cat.get("cat_type") == "freebies":
                m.emoji("gift").text(f"  {_t('prod_price', lang)}").bold("FREE 🎁").nl()
            else:
                m.emoji("balance").text(f"  {_t('prod_price', lang)}").bold(f"$ {cat['price']:.2f} USDT").nl()
            m.emoji("box").text(f"  {_t('prod_stock', lang)}{stock_status_text}").nl(2)
            if count > 0:
                if cat.get("cat_type") == "freebies":
                    m.emoji("gift").text(f" {_t('prod_tap_claim', lang)}")
                else:
                    m.emoji("check").text(f" {_t('prod_tap_buy', lang)}")
            else:
                m.emoji("timer").text(f" {_t('prod_check_back', lang)}")
            text, entities = m.build()

        is_freebie = cat.get("cat_type") == "freebies"
        kb = build_keyboard([
            [btn(_t("btn_claim_free", lang), f"buy_{cat_id}", emoji_key="gift", style="success")] if (count > 0 and is_freebie) else
            [btn(_t("btn_buy_now", lang), f"buy_{cat_id}", emoji_key="cart", style="success")] if count > 0 else
            [btn(_t("btn_out_of_stock", lang), "noop", emoji_key="cross", style="danger")],
            [btn(_t("btn_back_to_shop", lang), "shop", emoji_key="back")],
        ])
        await edit_msg(chat_id, mid, text, entities or None, kb)
        pass

    elif data.startswith("buy_"):
        cat_id = data[4:]
        cats   = _load_categories()
        cat    = cats.get(cat_id)
        if not cat:
            await answer_cb(cq_id, "❌ Product not found.", alert=True)
            return
        count = await stock_count(cat_id)
        if count == 0:
            await answer_cb(cq_id, "❌ Out of stock!", alert=True)
            return

        user_id = user.get("id")

        # Initialize qty state at 1
        _qty_state[user_id] = {"cat_id": cat_id, "qty": 1}

        unit_price = get_bulk_price(cat["price"], 1)
        total      = round(unit_price * 1, 2)
        msg_text, msg_ent = build_qty_selector_msg(cat, 1, count, lang)
        kb = build_qty_keyboard(cat_id, 1, count, unit_price, total, lang)

        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        await send_msg(chat_id, msg_text, msg_ent, kb)

    elif data.startswith("qty_inc_") or data.startswith("qty_dec_"):
        # Increment or decrement quantity
        inc    = data.startswith("qty_inc_")
        cat_id = data[8:]
        cats   = _load_categories()
        cat    = cats.get(cat_id)
        if not cat:
            await answer_cb(cq_id, "❌ Product not found.", alert=True)
            return

        user_id = user.get("id")
        state   = _qty_state.get(user_id, {"cat_id": cat_id, "qty": 1})
        count   = await stock_count(cat_id)
        qty     = state.get("qty", 1)

        if inc:
            max_qty = count if count < 999 else 9999
            qty = min(qty + 1, max_qty)
        else:
            qty = max(1, qty - 1)

        _qty_state[user_id] = {"cat_id": cat_id, "qty": qty}
        unit_price = get_bulk_price(cat["price"], qty)
        total      = round(unit_price * qty, 2)

        msg_text, msg_ent = build_qty_selector_msg(cat, qty, count, lang)
        kb = build_qty_keyboard(cat_id, qty, count, unit_price, total, lang)
        await answer_cb(cq_id)
        await edit_msg(chat_id, mid, msg_text, msg_ent, kb)

    elif data.startswith("qty_custom_"):
        # Ask user to type a custom quantity
        cat_id  = data[11:]
        user_id = user.get("id")
        cats    = _load_categories()
        cat     = cats.get(cat_id)
        if not cat:
            await answer_cb(cq_id, "❌ Product not found.", alert=True)
            return
        count = await stock_count(cat_id)
        max_qty = count if count < 999 else 9999
        _awaiting_custom_qty[user_id] = {"cat_id": cat_id, "max_qty": max_qty}
        await answer_cb(cq_id)
        await send_msg(chat_id,
            f"✏️ {_t('qty_enter', lang, max=max_qty)}",
            keyboard=build_keyboard([
                [btn(_t("btn_cancel", lang), f"buy_{cat_id}", emoji_key="cross", style="danger")]
            ])
        )

    elif data.startswith("qty_buy_"):
        # Proceed to payment with selected quantity
        cat_id  = data[8:]
        user_id = user.get("id")
        cats    = _load_categories()
        cat     = cats.get(cat_id)
        if not cat:
            await answer_cb(cq_id, "❌ Product not found.", alert=True)
            return
        count = await stock_count(cat_id)
        if count == 0:
            await answer_cb(cq_id, "❌ Out of stock!", alert=True)
            return

        state  = _qty_state.pop(user_id, {"qty": 1})
        qty    = state.get("qty", 1)
        # Cap to available stock
        if count < 999:
            qty = min(qty, count)
        qty = max(1, qty)

        unit_price = get_bulk_price(cat["price"], qty)
        total      = round(unit_price * qty, 2)

        db_data = await db_get_user(user_id)
        balance = db_data.get("balance", 0.0) if db_data else 0.0

        # Create order with quantity and total price
        order_id = await order_create(
            user_id, cat_id, cat["name"], total, quantity=qty
        )

        # ── Freebies — skip payment, auto-deliver immediately ─
        if cat.get("cat_type") == "freebies":
            # 24-hour cooldown check
            can_claim, hours_left = await db_check_freebie_cooldown(user_id)
            if not can_claim:
                await order_set_status(order_id, "cancelled")
                await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
                m = Msg()
                m.emoji("timer").text(" ").bold(_t("freebie_cooldown_title", lang)).nl(2)
                m.text(_t("freebie_cooldown_body", lang)).nl(2)
                m.emoji("clock").text(f" {_t('freebie_cooldown_time', lang)}").bold(f"{hours_left} {_t('freebie_hours', lang)}")
                t, e = m.build()
                await send_msg(chat_id, t, e,
                    keyboard=build_keyboard([
                        [btn(_t("btn_shop", lang), "shop", emoji_key="shop", style="success")],
                        [btn(_t("btn_home", lang), "back_main", emoji_key="back")],
                    ])
                )
                return

            await order_set_status(order_id, "approved")
            await db_set_freebie_claim(user_id)
            await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
            order = await order_get(order_id)
            delivered = await auto_deliver(chat_id, user_id, order)
            if not delivered:
                await send_msg(chat_id,
                    _t("freebie_oos", lang),
                    keyboard=build_keyboard([[btn(_t("btn_shop", lang), "shop", emoji_key="shop")]]))
            else:
                await post_sale_log(cat["name"], 0.0, order_type="freebie", user=user, quantity=qty)
            return

        # ── Paid product — show payment options ──────────────
        pay_rows = []
        if balance >= total:
            pay_rows.append(
                [btn(_t("btn_pay_wallet", lang, bal=balance), f"paywallet_{order_id}",
                     emoji_key="paywallet", style="success")]
            )
        enabled_pays = get_enabled_payments()
        pay_emoji_map = {"bep20": "bep20"}
        pay_style_map = {"bep20": "success"}
        for k, v in enabled_pays.items():
            pay_rows.append([btn(f"{v['label']}", f"pay_{k}_{order_id}",
                                 emoji_key=pay_emoji_map.get(k), style=pay_style_map.get(k, "success"))])
        if not [r for r in pay_rows if "paywallet" not in str(r)]:
            pay_rows.append([btn(_t("no_payment_methods", lang), "noop")])
        pay_rows.append([btn(_t("btn_cancel_order", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")])

        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})

        sm = Msg()
        sm.emoji("check").text(" ").bold(_t("order_summary_title", lang)).nl(2)
        sm.emoji("cart").text(f" {_t('order_product', lang)}").bold(cat["name"]).nl()
        sm.emoji("clipboard").text(f" {_t('order_quantity', lang)}").bold(str(qty)).nl()
        sm.emoji("balance").text(f" {_t('order_unit_price', lang)}").bold(f"$ {unit_price:.2f} USDT").nl()
        sm.emoji("thunder").text(f" {_t('order_total', lang)}").bold(f"$ {total:.2f} USDT").nl(2)
        sm.emoji("usdt").text(" ").bold(_t("order_choose_payment", lang))
        sm_text, sm_ent = sm.build()
        await send_msg(chat_id, sm_text, sm_ent, build_keyboard(pay_rows))

    elif data.startswith("pay_bep20_") or data.startswith("pay_trx_") or data.startswith("pay_btc_"):
        # Show payment details for purchase (any network)
        if data.startswith("pay_bep20_"):
            network = "bep20"; order_id = data[10:]
        elif data.startswith("pay_trx_"):
            network = "trx"; order_id = data[9:]
        else:
            network = "btc"; order_id = data[9:]

        order   = await order_get(order_id)
        user_id = user.get("id")

        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["user_id"] != str(user_id):
            await answer_cb(cq_id, "⛔ Unauthorized.", alert=True)
            return
        if order["status"] not in ("pending_payment",):
            await answer_cb(cq_id, "⚠️ Order already processed.", alert=True)
            return

        # Save selected network to order (needed for auto-verify routing)
        await order_set_network(order_id, network)

        caption, cap_entities = build_payment_caption(
            _t("pay_order_summary_title", lang), order["price"], order["cat_name"], network=network
        )
        net_images = {
            "bep20": USDT_BEP20_IMAGE, "trx": USDT_TRX_IMAGE,
            "btc": BTC_IMAGE,
        }
        qr_image = net_images[network]

        if network == "bep20":
            done_btn_text = _t("btn_ive_paid_txhash", lang)
        elif network == "trx":
            done_btn_text = _t("btn_ive_paid_screenshot", lang)
        else:
            done_btn_text = _t("btn_ive_paid_screenshot", lang)

        kb = build_keyboard([
            [btn(done_btn_text, f"done_{order_id}", emoji_key="check", style="success")],
            [btn(_t("btn_back", lang), f"buy_{order['cat_id']}", emoji_key="back"),
             btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross")],
        ])
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        if os.path.exists(qr_image):
            await send_local_photo(chat_id, qr_image, caption, kb, cap_entities)
        else:
            await send_msg(chat_id, caption, cap_entities, kb)

    elif data.startswith("done_"):
        order_id = data[5:]
        order    = await order_get(order_id)
        user_id  = user.get("id")

        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["user_id"] != str(user_id):
            await answer_cb(cq_id, "⛔ Unauthorized.", alert=True)
            return
        if order["status"] not in ("pending_payment",):
            await answer_cb(cq_id,
                "⚠️ This order has already been submitted.", alert=True)
            return

        # ── Check if this was a BEP20 payment — use auto-verify ──
        network = order.get("network", "")
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})

        if network == "bep20":
            _awaiting_txn_hash[user_id] = order_id
            m = Msg()
            m.emoji("thunder").text(" ").bold(_t("bep20_verify_title", lang)).nl(2)
            m.emoji("clipboard").text(f" {_t('verify_failed_order', lang)}").bold(order["cat_name"]).nl()
            m.emoji("balance").text(f" {_t('topup_amount_label', lang)}").bold(f"$ {order['price']:.2f} USDT").nl(2)
            m.emoji("key").text(" ").bold(_t("bep20_send_txhash", lang)).nl()
            m.italic(_t("bep20_txhash_example", lang)).code("0x4a3b...f9e2").nl(2)
            m.emoji("number1").text(f" {_t('bep20_step1', lang)}").nl()
            m.emoji("number2").text(f" {_t('bep20_step2', lang)}").nl()
            m.emoji("number3").text(f" {_t('bep20_step3', lang)}").nl()
            m.emoji("number4").text(f" {_t('bep20_step4', lang)}").emoji("check")
            st, se = m.build()
            await send_msg(chat_id, st, se,
                keyboard=build_keyboard([
                    [btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")]
                ])
            )
        elif network == "trx":
            _awaiting_screenshot[user_id] = order_id
            m = Msg()
            m.emoji("camera").text(" ").bold(_t("trx_screenshot_title", lang)).nl(2)
            m.emoji("clipboard").text(f" {_t('verify_failed_order', lang)}").bold(order["cat_name"]).nl()
            m.emoji("balance").text(f" {_t('topup_amount_label', lang)}").bold(f"$ {order['price']:.2f}").text(" USDT").nl(2)
            m.italic(_t("trx_screenshot_hint", lang))
            ss_text, ss_ent = m.build()
            await send_msg(chat_id, ss_text, ss_ent,
                keyboard=build_keyboard([
                    [btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")]
                ])
            )
        else:
            _awaiting_screenshot[user_id] = order_id
            m = Msg()
            m.emoji("camera").text(" ").bold(_t("btc_screenshot_title", lang)).nl(2)
            m.emoji("clipboard").text(f" {_t('verify_failed_order', lang)}").bold(order["cat_name"]).nl()
            m.emoji("balance").text(f" {_t('topup_amount_label', lang)}").bold(f"$ {order['price']:.2f} USD").nl(2)
            m.emoji("thunder").text(f" {_t('btc_address_label', lang)}").nl()
            m.code(BTC_ADDRESS).nl(2)
            m.emoji("number1").text(f" {_t('btc_step1', lang)}").nl()
            m.emoji("number2").text(f" {_t('btc_step2', lang)}").nl()
            m.emoji("number3").text(" ").bold(_t("btc_step3", lang)).nl(2)
            m.emoji("timer").text(" ").italic(_t("btc_admin_verify", lang))
            ss_text, ss_ent = m.build()
            await send_msg(chat_id, ss_text, ss_ent,
                keyboard=build_keyboard([
                    [btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")]
                ])
            )

    elif data.startswith("paywallet_"):
        # Instant wallet payment — no screenshot needed
        order_id = data[10:]
        order    = await order_get(order_id)
        user_id  = user.get("id")

        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["user_id"] != str(user_id):
            await answer_cb(cq_id, "⛔ Unauthorized.", alert=True)
            return
        if order["status"] != "pending_payment":
            await answer_cb(cq_id, "⚠️ Order already processed.", alert=True)
            return
        if order.get("order_type") == "topup":
            await answer_cb(cq_id, "❌ Cannot pay a top-up with wallet.", alert=True)
            return

        # Re-check balance at payment time
        db_data = await db_get_user(user_id)
        balance = db_data.get("balance", 0.0) if db_data else 0.0
        price   = order["price"]

        if balance < price:
            await answer_cb(cq_id,
                _t("wallet_insufficient", lang, bal=balance, need=price),
                alert=True)
            return

        cats     = _load_categories()
        cat_obj  = cats.get(order["cat_id"], {})
        cat_type = cat_obj.get("cat_type", "id_pass")

        count = await stock_get_count(order["cat_id"])
        if count <= 0:
            await answer_cb(cq_id, _t("wallet_oos", lang), alert=True)
            await order_set_status(order_id, "cancelled")
            return

        await order_set_status(order_id, "approved")
        await db_record_purchase(user_id, price)
        await post_sale_log(order["cat_name"], price, user=user)

        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        delivered = await auto_deliver(chat_id, user_id, order)
        if not delivered:
            await send_msg(chat_id,
                _t("wallet_stock_race", lang),
                keyboard=build_keyboard([[btn(_t("btn_home", lang), "back_main", emoji_key="back")]]))
            for admin_id in ADMINS:
                await send_msg(admin_id,
                    f"⚠️ STOCK EMPTY — Manual Delivery Needed\n\n"
                    f"💳 Wallet Payment — Order #{order_id[:8].upper()}\n"
                    f"🛒 Product: {order['cat_name']}\n"
                    f"💰 Amount: $ {price:.2f} USDT\n"
                    f"👤 User ID: {order['user_id']}\n\n"
                    f"Please deliver manually and restock.")
        else:
            for admin_id in ADMINS:
                await send_msg(admin_id,
                    f"✅ AUTO-DELIVERED — Wallet Payment\n\n"
                    f"🛒 Product: {order['cat_name']}\n"
                    f"💰 Amount: $ {price:.2f} USDT\n"
                    f"👤 User ID: {order['user_id']}\n"
                    f"📦 Stock remaining: {await stock_get_count(order['cat_id'])}"
                )

    elif data.startswith("bep20_retry_"):
        # User wants to try submitting txn hash again
        order_id = data[12:]
        order    = await order_get(order_id)
        user_id  = user.get("id")

        if not order or order["user_id"] != str(user_id):
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["status"] != "pending_payment":
            await answer_cb(cq_id, "⚠️ Order is no longer active.", alert=True)
            return

        _awaiting_txn_hash[user_id] = order_id
        m = Msg()
        m.emoji("key").text(" ").bold(_t("bep20_retry_title", lang)).nl(2)
        m.emoji("clipboard").text(f" {_t('verify_failed_order', lang)}").bold(order["cat_name"]).nl()
        m.emoji("balance").text(f" {_t('topup_amount_label', lang)}").bold(f"$ {order['price']:.2f} USDT").nl(2)
        m.italic(_t("bep20_retry_hint", lang)).code("0x")
        st, se = m.build()
        await edit_msg(chat_id, mid, st, se,
            keyboard=build_keyboard([
                [btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")]
            ])
        )

    elif data.startswith("trx_retry_"):
        # User wants to try submitting TRC20 TxID again
        order_id = data[10:]
        order    = await order_get(order_id)
        user_id  = user.get("id")

        if not order or order["user_id"] != str(user_id):
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["status"] != "pending_payment":
            await answer_cb(cq_id, "⚠️ Order is no longer active.", alert=True)
            return

        _awaiting_trx_hash[user_id] = order_id
        m = Msg()
        m.emoji("key").text(" ").bold(_t("trx_retry_title", lang)).nl(2)
        m.emoji("clipboard").text(f" {_t('verify_failed_order', lang)}").bold(order["cat_name"]).nl()
        m.emoji("balance").text(f" {_t('topup_amount_label', lang)}").bold(f"$ {order['price']:.2f} USDT").nl(2)
        m.italic(_t("trx_retry_hint", lang))
        st, se = m.build()
        await edit_msg(chat_id, mid, st, se,
            keyboard=build_keyboard([
                [btn(_t("btn_cancel", lang), f"cancel_{order_id}", emoji_key="cross", style="danger")]
            ])
        )

    elif data.startswith("cancel_"):
        order_id = data[7:]
        order    = await order_get(order_id)
        user_id  = user.get("id")

        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["user_id"] != str(user_id):
            await answer_cb(cq_id, "⛔ Unauthorized.", alert=True)
            return

        # Remove from awaiting state if present
        _awaiting_screenshot.pop(user_id, None)
        _awaiting_txn_hash.pop(user_id, None)
        _awaiting_trx_hash.pop(user_id, None)
        await order_set_status(order_id, "cancelled")

        # May be a photo message — delete and send fresh
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        await send_msg(chat_id,
            _t("order_cancelled", lang),
            keyboard=build_keyboard([
                [btn(_t("btn_back_to_shop", lang), "shop", emoji_key="back")],
                [btn(_t("btn_home", lang), "back_main", emoji_key="back")],
            ])
        )

    elif data.startswith("approve_"):
        # Admin only
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        order_id = data[8:]
        order    = await order_get(order_id)
        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["status"] not in ("pending_approval",):
            await answer_cb(cq_id,
                f"⚠️ Order status is already: {order['status']}", alert=True)
            return

        buyer_id   = int(order["user_id"])
        order_type = order.get("order_type", "purchase")

        # ── TOPUP ORDER ───────────────────────────────────────
        if order_type == "topup":
            await db_add_balance(buyer_id, order["price"])
            await order_set_status(order_id, "approved")
            buyer_data = await db_get_user(buyer_id)
            await post_sale_log(order["cat_name"], order["price"], order_type="topup", user=buyer_data)
            new_balance = buyer_data.get("balance", 0.0) if buyer_data else order["price"]
            buyer_lang  = await db_get_lang(buyer_id)
            dm = Msg()
            dm.emoji("check").text(" ").bold(_t("topup_approved_title", buyer_lang)).nl(2)
            dm.emoji("balance").text(f" {_t('topup_approved_amount_added', buyer_lang)}").bold(f"$ {order['price']:.2f} USDT").nl()
            dm.emoji("thunder").text(f" {_t('topup_approved_new_balance', buyer_lang)}").bold(f"$ {new_balance:.2f} USDT").nl(2)
            dm.emoji("cart").text(" ").italic(_t("topup_approved_can_pay", buyer_lang))
            deliver_text, deliver_ent = dm.build()
            await send_msg(buyer_id, deliver_text, deliver_ent,
                keyboard=build_keyboard([[btn(_t("btn_go_to_shop", buyer_lang), "shop", emoji_key="shop", style="success")]]))
            await api_call("editMessageCaption", {
                "chat_id":    chat_id,
                "message_id": mid,
                "caption":    (
                    f"✅ TOPUP APPROVED — #{order_id[:8].upper()}\n\n"
                    f"💳 Amount: $ {order['price']:.2f} USDT\n"
                    f"👤 User ID: {order['user_id']}"
                ),
            })
            await answer_cb(cq_id, f"✅ Top up of $ {order['price']:.2f} USDT added!")
            return

        # ── PURCHASE ORDER ────────────────────────────────────
        # Auto-deliver from stock
        await order_set_status(order_id, "approved")
        await db_record_purchase(buyer_id, order["price"])
        buyer_data = await db_get_user(buyer_id)
        await post_sale_log(order["cat_name"], order["price"], user=buyer_data)

        # Update admin message caption
        await api_call("editMessageCaption", {
            "chat_id":    chat_id,
            "message_id": mid,
            "caption":    (
                f"✅ APPROVED — Order #{order_id[:8].upper()}\n\n"
                f"🛒 {order['cat_name']}\n"
                f"💰 $ {order['price']:.2f} USDT\n"
                f"👤 User ID: {order['user_id']}"
            ),
        })

        delivered = await auto_deliver(buyer_id, buyer_id, order)
        if not delivered:
            await send_msg(chat_id,
                f"⚠️ Payment approved but *stock is empty* for {order['cat_name']}!\n"
                f"👤 User ID: `{buyer_id}`\n\n"
                f"Please deliver manually and restock.")
            await answer_cb(cq_id, "⚠️ Approved but stock is empty — deliver manually!")
        else:
            await answer_cb(cq_id, "✅ Approved & product auto-delivered to user!")

    elif data.startswith("deliver_"):
        # Admin only — triggered after approving a link-type order
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        order_id = data[8:]
        order    = await order_get(order_id)
        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return

        cats     = _load_categories()
        cat_obj  = cats.get(order["cat_id"], {})
        cat_type = cat_obj.get("cat_type", "id_pass")
        buyer_id = int(order["user_id"])

        if cat_type == "link":
            # Put admin in state to type the link
            _admin_state[int(user.get("id"))] = {
                "step": "deliver_link",
                "data": {
                    "order_id":  order_id,
                    "buyer_id":  buyer_id,
                    "cat_name":  order["cat_name"],
                }
            }
            await send_msg(chat_id,
                f"🔗 Send the *activation link* for:\n"
                f"🛒 {order['cat_name']}\n"
                f"👤 User ID: `{buyer_id}`\n\n"
                f"Just type or paste the link:")
        else:
            # id_pass — put admin in deliver_creds state
            _admin_state[int(user.get("id"))] = {
                "step": "deliver_creds",
                "data": {
                    "order_id":  order_id,
                    "buyer_id":  buyer_id,
                    "cat_name":  order["cat_name"],
                    "cat_type":  cat_type,
                }
            }
            await send_msg(chat_id,
                f"🔐 Send the *credentials* for:\n"
                f"🛒 {order['cat_name']}\n"
                f"👤 User ID: `{buyer_id}`\n\n"
                f"Format: `email:password`")

    elif data.startswith("reject_"):
        # Admin only
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        order_id = data[7:]
        order    = await order_get(order_id)
        if not order:
            await answer_cb(cq_id, "❌ Order not found.", alert=True)
            return
        if order["status"] not in ("pending_approval",):
            await answer_cb(cq_id,
                f"⚠️ Order status is already: {order['status']}", alert=True)
            return

        await order_set_status(order_id, "rejected")
        buyer_id   = int(order["user_id"])
        buyer_lang = await db_get_lang(buyer_id)

        bm = Msg()
        bm.emoji("cross").text(" ").bold(_t("payment_rejected_title", buyer_lang)).nl(2)
        bm.text(f"{_t('payment_rejected_product', buyer_lang)}").bold(order["cat_name"]).nl()
        bm.text(f"{_t('payment_rejected_amount', buyer_lang)}").bold(f"$ {order['price']:.2f} USDT").nl(2)
        bm.text(_t("payment_rejected_body", buyer_lang))
        bm_text, bm_ent = bm.build()
        await send_msg(buyer_id, bm_text, bm_ent,
            keyboard=build_keyboard([
                [btn(_t("btn_back_to_home", buyer_lang), "back_main", emoji_key="back")]
            ])
        )

        # Update admin message
        await api_call("editMessageCaption", {
            "chat_id":    chat_id,
            "message_id": mid,
            "caption":    (
                f"❌ REJECTED — Order #{order_id[:8].upper()}\n\n"
                f"🛒 {order['cat_name']}\n"
                f"💰 $ {order['price']:.2f} USDT\n"
                f"👤 User ID: {order['user_id']}"
            ),
        })
        await answer_cb(cq_id, "❌ Order rejected. User has been notified.")

    elif data == "history":
        user_id = user.get("id")
        async with _ord_lock:
            all_orders = _load_orders()
        user_orders = [
            o for o in all_orders.values()
            if o["user_id"] == str(user_id)
        ]
        user_orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        recent = user_orders[:5]

        m = Msg()
        m.emoji("clipboard").text(" ").bold(_t("history_title", lang)).nl(2)
        if not recent:
            m.emoji("box").text(" ").italic(_t("history_empty", lang)).nl(2)
            m.text(_t("history_start_shopping", lang))
        else:
            for o in recent:
                status = o["status"]
                if status == "approved":
                    m.emoji("check")
                elif status in ("pending_payment", "pending_approval"):
                    m.emoji("timer")
                else:
                    m.emoji("cross")
                m.text(" ").bold(o["cat_name"]).nl()
                m.emoji("balance").text(f" $ {o['price']:.2f}").text(f"  •  {o['created_at'][:10]}").nl(2)
        t, ent = m.build()
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
        await send_msg(chat_id, t, ent,
            keyboard=build_keyboard([[btn(_t("btn_home", lang), "back_main", emoji_key="back")]])
        )

    # ── Payment Manager callbacks (admin only) ───────────────
    elif data == "pay_mgr_menu":
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        pays = _load_payments()
        rows = []
        for k, v in pays.items():
            status_icon = "✅" if v.get("enabled") else "🔴"
            addr = v.get("address", "")
            addr_preview = addr[:10] + "..." if len(addr) > 10 else (addr if addr else "NOT SET")
            rows.append([btn(f"{status_icon} {v['label']} — {addr_preview}", f"pay_mgr_{k}")])
        rows.append([btn("Close", "noop", style="danger")])
        await answer_cb(cq_id)
        await edit_msg(chat_id, mid,
            "💳 Payment Methods Manager\n\nTap a method to Edit / Enable / Disable:",
            keyboard=build_keyboard(rows))

    elif data.startswith("pay_mgr_"):
        # Show detail/management for one payment method
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        network = data[8:]  # e.g. "bep20", "trx"
        pays    = _load_payments()
        if network not in pays:
            await answer_cb(cq_id, "❌ Unknown payment method.", alert=True)
            return
        v           = pays[network]
        status_text = "✅ Enabled" if v.get("enabled") else "🔴 Disabled"
        addr        = v.get("address", "") or "NOT SET"
        toggle_lbl  = "🔴 Disable" if v.get("enabled") else "✅ Enable"
        toggle_cb   = f"pay_disable_{network}" if v.get("enabled") else f"pay_enable_{network}"
        info = (
            f"💳 {v['label']}\n\n"
            f"🌐 Network: {v['network']}\n"
            f"📋 Status: {status_text}\n"
            f"📬 Address:\n`{addr}`\n\n"
            f"Choose an action below:"
        )
        kb = build_keyboard([
            [btn("✏️  Edit Address",  f"pay_edit_{network}", style="success")],
            [btn(toggle_lbl,         toggle_cb,             style="danger" if v.get("enabled") else "success")],
            [btn("Back",             "pay_mgr_menu",        emoji_key="back")],
        ])
        await answer_cb(cq_id)
        await edit_msg(chat_id, mid, info, keyboard=kb)

    elif data.startswith("pay_enable_"):
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        network = data[11:]
        pays    = _load_payments()
        if network not in pays:
            await answer_cb(cq_id, "❌ Unknown payment method.", alert=True)
            return
        pays[network]["enabled"] = True
        _save_payments(pays)
        v    = pays[network]
        addr = v.get("address", "") or "NOT SET"
        info = (
            f"💳 {v['label']}\n\n"
            f"🌐 Network: {v['network']}\n"
            f"📋 Status: ✅ Enabled\n"
            f"📬 Address:\n`{addr}`\n\n"
            f"Choose an action below:"
        )
        kb = build_keyboard([
            [btn("✏️  Edit Address", f"pay_edit_{network}",   style="success")],
            [btn("Disable",          f"pay_disable_{network}", style="danger")],
            [btn("Back",              "pay_mgr_menu",           emoji_key="back")],
        ])
        await answer_cb(cq_id, f"✅ {v['label']} enabled!")
        await edit_msg(chat_id, mid, info, keyboard=kb)

    elif data.startswith("pay_disable_"):
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        network = data[12:]
        pays    = _load_payments()
        if network not in pays:
            await answer_cb(cq_id, "❌ Unknown payment method.", alert=True)
            return
        pays[network]["enabled"] = False
        _save_payments(pays)
        v    = pays[network]
        addr = v.get("address", "") or "NOT SET"
        info = (
            f"💳 {v['label']}\n\n"
            f"🌐 Network: {v['network']}\n"
            f"📋 Status: 🔴 Disabled\n"
            f"📬 Address:\n`{addr}`\n\n"
            f"Choose an action below:"
        )
        kb = build_keyboard([
            [btn("✏️  Edit Address", f"pay_edit_{network}",  style="success")],
            [btn("Enable",           f"pay_enable_{network}", style="success")],
            [btn("Back",              "pay_mgr_menu",          emoji_key="back")],
        ])
        await answer_cb(cq_id, f"🔴 {v['label']} disabled!")
        await edit_msg(chat_id, mid, info, keyboard=kb)

    elif data.startswith("pay_edit_"):
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        network = data[9:]
        pays    = _load_payments()
        if network not in pays:
            await answer_cb(cq_id, "❌ Unknown payment method.", alert=True)
            return
        uid = user.get("id")
        _admin_state[uid] = {
            "step": "pay_edit_address",
            "data": {"network": network},
        }
        v = pays[network]
        await answer_cb(cq_id)
        await edit_msg(chat_id, mid,
            f"✏️ Edit address for *{v['label']}*\n\n"
            f"Current address:\n`{v.get('address','NOT SET')}`\n\n"
            f"Send the new wallet address now:"
        )

    elif data in ("admincat_type_link", "admincat_type_id_pass", "admincat_type_dm", "admincat_type_freebies"):
        # Admin pressed type button during /addcategory flow
        uid = user.get("id")
        if not is_admin(uid):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        state = _admin_state.get(uid)
        if not state or state.get("step") != "addcat_type":
            await answer_cb(cq_id, "⚠️ No active category creation flow.", alert=True)
            return

        if data == "admincat_type_link":
            cat_type   = "link"
            type_label = "🔗 Link"
        elif data == "admincat_type_id_pass":
            cat_type   = "id_pass"
            type_label = "🔐 ID & Pass"
        elif data == "admincat_type_freebies":
            cat_type   = "freebies"
            type_label = "🎁 Freebies"
        else:
            cat_type   = "dm_activation"
            type_label = "💬 DM Activation"

        state["data"]["cat_type"] = cat_type
        state["step"] = "addcat_desc"

        await answer_cb(cq_id, f"Selected: {type_label}")
        await edit_msg(chat_id, mid,
            f"✅ Type selected: {type_label}\n\n"
            f"📝 Now send the product description.\n\n"
            f"This will be shown to users on the product detail page.\n"
            f"You can use multiple lines. Example:\n\n"
            f"📦 Product Details\n"
            f"Includes 1 month Netflix Premium access.\n\n"
            f"  Requirements\n"
            f"• Active internet connection\n"
            f"• Mobile or PC\n\n"
            f"Or send — to skip and use a default description."
        )

    elif data in ("addstock_type_link", "addstock_type_id_pass", "addstock_type_freebies"):
        # Admin pressed type button during /addstock flow
        # Note: dm_activation has no stock — not shown here
        uid = user.get("id")
        if not is_admin(uid):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        state = _admin_state.get(uid)
        if not state or state.get("step") != "addstock_type":
            await answer_cb(cq_id, "⚠️ No active addstock flow. Use /addstock first.", alert=True)
            return

        if data == "addstock_type_link":
            cat_type   = "link"
            type_label = "🔗 Link"
        elif data == "addstock_type_freebies":
            cat_type   = "freebies"
            type_label = "🎁 Freebies"
        else:
            cat_type   = "id_pass"
            type_label = "🔐 ID & Pass"
        state["data"]["cat_type"] = cat_type
        state["step"] = "addstock_pick"

        # Filter categories to matching type (exclude dm_activation)
        cats = _load_categories()
        matching = [(i, cat) for i, cat in enumerate(cats.values(), 1)
                    if cat.get("cat_type", "id_pass") == cat_type]

        if not matching:
            del _admin_state[uid]
            await answer_cb(cq_id)
            await edit_msg(chat_id, mid,
                f"❌ No *{type_label}* categories found.\n"
                f"Add a category with /addcategory first.")
            return

        await answer_cb(cq_id, f"Selected: {type_label}")
        lines = [f"✅ Type: {type_label}\n\n📦 Select a category (send its number):\n"]
        for i, cat in matching:
            count = await stock_get_count(cat["id"])
            lines.append(f"{i}. {cat.get('emoji_char','🛒')} {cat['name']}"
                         f" — $ {cat['price']:.2f} USDT  |  Stock: {count}")
        await edit_msg(chat_id, mid, "\n".join(lines))

    elif data in ("addstock_freebies_link", "addstock_freebies_id_pass"):
        uid = user.get("id")
        if not is_admin(uid):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return
        state = _admin_state.get(uid)
        if not state or state.get("step") != "addstock_freebies_format":
            await answer_cb(cq_id, "⚠️ No active flow.", alert=True)
            return

        # Set internal format for parsing — freebies_link or freebies_id_pass
        fmt        = "freebies_link" if data == "addstock_freebies_link" else "freebies_id_pass"
        fmt_label  = "🔗 Links" if fmt == "freebies_link" else "🔐 ID & Pass"
        state["data"]["cat_type"] = fmt
        state["step"] = "addstock_items"

        cat_name = state["data"]["cat_name"]
        current  = await stock_get_count(state["data"]["cat_id"])

        await answer_cb(cq_id, f"Selected: {fmt_label}")
        if fmt == "freebies_link":
            await edit_msg(chat_id, mid,
                f"🔗 Adding links to *{cat_name}* (Freebies)\n"
                f"Current stock: {current}\n\n"
                "Send activation links — one per line.\n"
                "Example:\n"
                "https://t.me/+abcxyz123\n\n"
                "Type *DONE* when finished.")
        else:
            await edit_msg(chat_id, mid,
                f"🔐 Adding accounts to *{cat_name}* (Freebies)\n"
                f"Current stock: {current}\n\n"
                "Send accounts — one per line:\n"
                "`email:password`\n\n"
                "Type *DONE* when finished.")

    elif data == "broadcast_cancel":
        user_id = user.get("id")
        if not is_admin(user_id):
            await answer_cb(cq_id, "⛔ Unauthorized.", alert=True)
            return
        _admin_state.pop(user_id, None)
        _pending_broadcast.pop(user_id, None)
        await answer_cb(cq_id)
        await edit_msg(chat_id, mid, "❌ Broadcast cancelled.")

    elif data.startswith("broadcast_confirm_"):
        admin_id = user.get("id")
        if not is_admin(admin_id):
            await answer_cb(cq_id, "⛔ Unauthorized.", alert=True)
            return

        bc = _pending_broadcast.pop(admin_id, None)
        if not bc:
            await answer_cb(cq_id, "❌ No pending broadcast.", alert=True)
            return

        from_chat_id = bc["from_chat_id"]
        message_id   = bc["message_id"]

        await answer_cb(cq_id)
        # Delete confirm message
        await api_call("deleteMessage", {"chat_id": chat_id, "message_id": mid})

        db = _load_db()
        all_users = list(db.keys())
        total  = len(all_users)
        sent   = 0
        failed = 0

        # Send progress message
        prog_data = await send_msg(chat_id, f"📡 Broadcasting... 0 / {total}")
        prog_mid  = prog_data.get("result", {}).get("message_id")

        for i, uid in enumerate(all_users, 1):
            try:
                result = await api_call("copyMessage", {
                    "chat_id":      int(uid),
                    "from_chat_id": from_chat_id,
                    "message_id":   message_id,
                })
                if result.get("ok"):
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

            # Update progress every 50 users
            if prog_mid and i % 50 == 0:
                try:
                    await api_call("editMessageText", {
                        "chat_id":    chat_id,
                        "message_id": prog_mid,
                        "text":       f"📡 Broadcasting... {i} / {total}",
                    })
                except Exception:
                    pass

            await asyncio.sleep(0.05)  # 20 msgs/sec — safe rate

        # Final report
        done_m = Msg()
        done_m.emoji("check").text(" ").bold("Broadcast Complete!").nl(2)
        done_m.emoji("thunder").text(" Sent: ").bold(str(sent)).nl()
        done_m.emoji("cross").text(" Failed: ").bold(str(failed)).nl()
        done_m.emoji("clipboard").text(" Total: ").bold(str(total))
        dt, de = done_m.build()

        if prog_mid:
            await edit_msg(chat_id, prog_mid, dt, de)
        else:
            await send_msg(chat_id, dt, de)

    # ── Admin Panel callbacks ──────────────────────────────────
    elif data.startswith("adm_"):
        if not is_admin(user.get("id")):
            await answer_cb(cq_id, "⛔ Admins only.", alert=True)
            return

        # ── Payments shortcut ─────────────────────────────────
        if data in ("adm_payments",):
            await answer_cb(cq_id)
            pays = _load_payments()
            rows = []
            for k, v in pays.items():
                status = "✅" if v.get("enabled") else "🔴"
                addr   = v.get("address", "")
                addr_p = addr[:12] + "..." if len(addr) > 12 else (addr or "NOT SET")
                rows.append([btn(f"{status} {v['label']} — {addr_p}", f"pay_mgr_{k}")])
            rows.append([btn("Back", "adm_back", emoji_key="back")])
            await edit_msg(chat_id, mid,
                "💳 Payment Methods\n\nTap a method to edit/enable/disable:",
                keyboard=build_keyboard(rows))

        # ── Refresh / main panel ──────────────────────────────
        elif data in ("adm_refresh",):
            await answer_cb(cq_id, "🔄 Refreshed!")
            t, ent, kb = await build_admin_panel()
            await edit_msg(chat_id, mid, t, ent, kb)

        # ── Pending orders ────────────────────────────────────
        elif data == "adm_pending":
            await answer_cb(cq_id)
            orders = _load_orders()
            pending = [(oid, o) for oid, o in orders.items()
                       if o["status"] == "pending_approval"]
            if not pending:
                await edit_msg(chat_id, mid,
                    "✅ No pending orders right now.",
                    keyboard=build_keyboard([[btn("Back", "adm_back", emoji_key="back")]]))
                return
            m = Msg()
            m.emoji("timer").text(" ").bold(f"Pending Orders · {len(pending)}").nl(2)
            for oid, o in pending[-10:]:
                uname = o.get("user_id", "?")
                m.emoji("clipboard").text(f" #{oid[:8].upper()} — ").bold(o["cat_name"])
                m.text(f" — $ {o['price']:.2f} — User {uname}").nl()
            t, ent = m.build()
            rows = []
            for oid, o in pending[-5:]:
                rows.append([btn(f"#{oid[:8].upper()} — {o['cat_name'][:20]}",
                                 f"adm_order_{oid}", style="success")])
            rows.append([btn("Back", "adm_back", emoji_key="back")])
            await edit_msg(chat_id, mid, t, ent, build_keyboard(rows))

        # ── Single order view ─────────────────────────────────
        elif data.startswith("adm_order_"):
            await answer_cb(cq_id)
            oid   = data[10:]
            order = await order_get(oid)
            if not order:
                await answer_cb(cq_id, "❌ Order not found.", alert=True)
                return
            db_data  = await db_get_user(order["user_id"])
            uname    = db_data.get("username", "") if db_data else ""
            uname_str = f"@{uname}" if uname else f"ID:{order['user_id']}"
            m = Msg()
            m.emoji("clipboard").text(" ").bold(f"Order #{oid[:8].upper()}").nl(2)
            m.emoji("cart").text(" Product: ").bold(order["cat_name"]).nl()
            m.emoji("moneybag").text(f" Amount: $ {order['price']:.2f}").nl()
            m.emoji("profile").text(f" User: {uname_str}").nl()
            m.emoji("usdt").text(f" Network: {order.get('network','?').upper()}").nl()
            m.emoji("timer").text(f" Status: {order['status']}").nl()
            m.emoji("clock").text(f" Time: {order['created_at']}")
            t, ent = m.build()
            kb_rows = []
            if order["status"] == "pending_approval":
                kb_rows.append([
                    btn("✅ Approve", f"approve_{oid}", style="success"),
                    btn("❌ Reject",  f"reject_{oid}",  style="danger"),
                ])
            kb_rows.append([btn("Back", "adm_pending", emoji_key="back")])
            await edit_msg(chat_id, mid, t, ent, build_keyboard(kb_rows))

        # ── Products list ─────────────────────────────────────
        elif data in ("adm_products",):
            await answer_cb(cq_id)
            cats = _load_categories()
            if not cats:
                await edit_msg(chat_id, mid, "❌ No products yet. Use New Product to add one.",
                    keyboard=build_keyboard([
                        [btn("New Product", "adm_new_product", emoji_key="plus", style="success")],
                        [btn("Back", "adm_back", emoji_key="back")],
                    ]))
                return
            m = Msg()
            m.emoji("shop").text(" ").bold(f"Products · {len(cats)}").nl(2)
            for cat in cats.values():
                count    = await stock_get_count(cat["id"])
                cat_type = cat.get("cat_type", "id_pass")
                type_lbl = {"link": "🔗", "id_pass": "🔐", "dm_activation": "💬", "freebies": "🎁"}.get(cat_type, "📦")
                stock_lbl = "∞" if cat_type in ("dm_activation", "freebies") else str(count)
                m.text(f"{cat.get('emoji_char','📦')} {cat['name']} — $ {cat['price']:.2f} — {type_lbl} Stock: {stock_lbl}").nl()
            t, ent = m.build()
            rows = []
            for cat in list(cats.values())[:8]:
                rows.append([btn(f"{cat.get('emoji_char','')} {cat['name']} · $ {cat['price']:.2f}",
                                 f"adm_cat_{cat['id']}", style="success")])
            rows.append([btn("New Product", "adm_new_product", emoji_key="plus", style="success")])
            rows.append([btn("Back", "adm_back", emoji_key="back")])
            await edit_msg(chat_id, mid, t, ent, build_keyboard(rows))

        # ── Single product management ─────────────────────────
        elif data.startswith("adm_cat_"):
            await answer_cb(cq_id)
            cat_id = data[8:]
            cats   = _load_categories()
            cat    = cats.get(cat_id)
            if not cat:
                await answer_cb(cq_id, "❌ Category not found.", alert=True)
                return
            count    = await stock_get_count(cat_id)
            cat_type = cat.get("cat_type", "id_pass")
            type_lbl = {"link": "🔗 Link", "id_pass": "🔐 ID & Pass", "dm_activation": "💬 DM", "freebies": "🎁 Freebies"}.get(cat_type, "📦")
            m = Msg()
            m.emoji("shop").text(f" {cat.get('emoji_char','')} ").bold(cat["name"]).nl(2)
            m.emoji("moneybag").text(f" Price: $ {cat['price']:.2f}").nl()
            m.emoji("box").text(f" Type: {type_lbl}").nl()
            m.emoji("clipboard").text(f" Stock: {count}").nl()
            m.emoji("clock").text(f" Created: {cat.get('created_at','-')}")
            t, ent = m.build()
            await edit_msg(chat_id, mid, t, ent, build_keyboard([
                [btn("Add Stock",     f"adm_stk_{cat_id}",  emoji_key="plus",   style="success"),
                 btn("Remove Stock",  f"adm_rmstk_{cat_id}",emoji_key="minus",  style="danger")],
                [btn("Update Price",  f"adm_price_{cat_id}",emoji_key="pencil", style="success"),
                 btn("Delete",        f"adm_del_{cat_id}",  emoji_key="cross",  style="danger")],
                [btn("Back", "adm_products", emoji_key="back")],
            ]))

        # ── Quick add stock from panel ────────────────────────
        elif data.startswith("adm_stk_"):
            await answer_cb(cq_id)
            cat_id = data[8:]
            cats   = _load_categories()
            cat    = cats.get(cat_id)
            if not cat:
                return
            _admin_state[user.get("id")] = {"step": "addstock_items",
                "data": {"cat_id": cat_id, "cat_name": cat["name"],
                         "cat_type": cat.get("cat_type","id_pass"), "items": []}}
            count = await stock_get_count(cat_id)
            await edit_msg(chat_id, mid,
                f"📦 Adding stock to *{cat['name']}*\nCurrent: {count}\n\n"
                f"Send items one per line. Type *DONE* when finished.")

        # ── Quick remove stock from panel ─────────────────────
        elif data.startswith("adm_rmstk_"):
            await answer_cb(cq_id)
            cat_id = data[10:]
            cats   = _load_categories()
            cat    = cats.get(cat_id)
            if not cat:
                return
            count = await stock_get_count(cat_id)
            _admin_state[user.get("id")] = {"step": "removestock_quantity",
                "data": {"cat_id": cat_id, "cat_name": cat["name"], "current_stock": count}}
            await edit_msg(chat_id, mid,
                f"🗑️ Remove stock from *{cat['name']}*\nCurrent: {count}\n\nHow many to remove?")

        # ── Quick update price from panel ─────────────────────
        elif data.startswith("adm_price_"):
            await answer_cb(cq_id)
            cat_id = data[10:]
            cats   = _load_categories()
            cat    = cats.get(cat_id)
            if not cat:
                return
            _admin_state[user.get("id")] = {"step": "updateprice_value",
                "data": {"cat_id": cat_id, "cat_name": cat["name"], "old_price": cat["price"]}}
            await edit_msg(chat_id, mid,
                f"💰 *{cat['name']}*\nCurrent: $ {cat['price']:.2f}\n\nEnter new price:")

        # ── Quick delete product from panel ───────────────────
        elif data.startswith("adm_del_"):
            await answer_cb(cq_id)
            cat_id = data[8:]
            cats   = _load_categories()
            cat    = cats.get(cat_id)
            if not cat:
                return
            _admin_state[user.get("id")] = {"step": "delcat_confirm",
                "data": {"cat_id": cat_id, "cat_name": cat["name"]}}
            await edit_msg(chat_id, mid,
                f"⚠️ Delete *{cat['name']}*?\nThis removes the category AND all its stock.\n\nReply YES to confirm.")

        # ── New product shortcut ──────────────────────────────
        elif data == "adm_new_product":
            await answer_cb(cq_id)
            _admin_state[user.get("id")] = {"step": "addcat_name", "data": {}}
            await edit_msg(chat_id, mid, "📝 Enter the new category name:")

        # ── Add stock shortcut ────────────────────────────────
        elif data in ("adm_add_stock", "adm_add_stock2"):
            await answer_cb(cq_id)
            cats = _load_categories()
            if not cats:
                await edit_msg(chat_id, mid, "❌ No categories yet.",
                    keyboard=build_keyboard([[btn("Back", "adm_back", emoji_key="back")]]))
                return
            _admin_state[user.get("id")] = {"step": "addstock_type", "data": {}}
            await edit_msg(chat_id, mid,
                "📦 What type of stock?",
                keyboard=build_keyboard([
                    [btn("🔗 Link",      "addstock_type_link",    style="success")],
                    [btn("🔐 ID & Pass", "addstock_type_id_pass", style="success")],
                    [btn("🎁 Freebies",  "addstock_type_freebies",style="success")],
                ]))

        # ── Low stock view ────────────────────────────────────
        elif data == "adm_low_stock":
            await answer_cb(cq_id)
            cats = _load_categories()
            m    = Msg()
            m.emoji("box").text(" ").bold("Low Stock Report").nl(2)
            found = False
            for cat in cats.values():
                if cat.get("cat_type") in ("dm_activation", "freebies"):
                    continue
                count = await stock_get_count(cat["id"])
                if count <= 5:
                    found = True
                    icon = "🔴" if count == 0 else "🟡"
                    m.text(f"{icon} {cat.get('emoji_char','')} {cat['name']} — Stock: {count}").nl()
            if not found:
                m.text("✅ All products have sufficient stock.")
            t, ent = m.build()
            await edit_msg(chat_id, mid, t, ent,
                keyboard=build_keyboard([[btn("Back", "adm_back", emoji_key="back")]]))

        # ── Customers list ────────────────────────────────────
        elif data == "adm_customers":
            await answer_cb(cq_id)
            db     = _load_db()
            total  = len(db)
            buyers = [u for u in db.values() if u.get("products_bought", 0) > 0]
            m = Msg()
            m.emoji("profile").text(" ").bold(f"Customers · {total}").nl(2)
            m.emoji("cart").text(f" Buyers: {len(buyers)}").nl()
            m.emoji("thunder").text(f" New (no purchase): {total - len(buyers)}").nl(2)
            # Top 5 by spending
            top = sorted(db.values(), key=lambda u: u.get("total_spent", 0), reverse=True)[:5]
            if top:
                m.bold("Top Spenders:").nl()
                for u in top:
                    uname = u.get("username") or u.get("first_name") or u["user_id"]
                    m.text(f"  @{uname} — $ {u.get('total_spent',0):.2f}").nl()
            t, ent = m.build()
            await edit_msg(chat_id, mid, t, ent,
                keyboard=build_keyboard([
                    [btn("Find User",  "adm_find_user", emoji_key="clipboard", style="success")],
                    [btn("Back",       "adm_back",      emoji_key="back")],
                ]))

        # ── Find user ─────────────────────────────────────────
        elif data == "adm_find_user":
            await answer_cb(cq_id)
            _admin_state[user.get("id")] = {"step": "find_user", "data": {}}
            await edit_msg(chat_id, mid,
                "🔍 Send the user's Telegram ID or @username to look them up:")

        # ── Banned users ──────────────────────────────────────
        elif data == "adm_banned":
            await answer_cb(cq_id)
            db     = _load_db()
            banned = [(uid, u) for uid, u in db.items() if u.get("banned")]
            m = Msg()
            m.emoji("cross").text(" ").bold(f"Banned Users · {len(banned)}").nl(2)
            if banned:
                for uid, u in banned[:10]:
                    uname = u.get("username") or u.get("first_name") or uid
                    m.text(f"🔴 {uname} ({uid}) — {u.get('ban_reason','?')[:30]}").nl()
            else:
                m.text("✅ No banned users.")
            t, ent = m.build()
            rows = []
            for uid, u in banned[:5]:
                uname = u.get("username") or u.get("first_name") or uid
                rows.append([btn(f"Unban {uname[:15]}", f"adm_unban_{uid}", style="success")])
            rows.append([btn("Back", "adm_back", emoji_key="back")])
            await edit_msg(chat_id, mid, t, ent, build_keyboard(rows))

        # ── Quick unban from panel ────────────────────────────
        elif data.startswith("adm_unban_"):
            target_id = data[10:]
            await db_unban_user(target_id)
            await answer_cb(cq_id, f"✅ User {target_id} unbanned!", alert=False)
            # Refresh banned list
            db     = _load_db()
            banned = [(uid, u) for uid, u in db.items() if u.get("banned")]
            m = Msg()
            m.emoji("cross").text(" ").bold(f"Banned Users · {len(banned)}").nl(2)
            if banned:
                for uid, u in banned[:10]:
                    uname = u.get("username") or u.get("first_name") or uid
                    m.text(f"🔴 {uname} ({uid}) — {u.get('ban_reason','?')[:30]}").nl()
            else:
                m.text("✅ No banned users.")
            t, ent = m.build()
            rows = [[btn(f"Unban {u.get('username', uid)[:15]}", f"adm_unban_{uid}", style="success")]
                    for uid, u in banned[:5]]
            rows.append([btn("Back", "adm_back", emoji_key="back")])
            await edit_msg(chat_id, mid, t, ent, build_keyboard(rows))
        # ── Adjust balance from user profile ─────────────────
        elif data.startswith("adm_adjbal_"):
            await answer_cb(cq_id)
            target_id = data[11:]
            target    = await db_get_user(target_id)
            name      = (target.get("username") or target_id) if target else target_id
            _admin_state[user.get("id")] = {
                "step": "wallet_adjust_amount",
                "data": {"target_id": target_id, "target_name": name}
            }
            bal = target.get("balance", 0.0) if target else 0.0
            await edit_msg(chat_id, mid,
                f"💰 Adjust balance for @{name}\n"
                f"Current: $ {bal:.2f}\n\n"
                f"Send amount (e.g. +5 to add, -3 to deduct):")

        # ── Ban user from user profile ────────────────────────
        elif data.startswith("adm_banuser_"):
            await answer_cb(cq_id)
            target_id = data[12:]
            _admin_state[user.get("id")] = {
                "step": "ban_reason",
                "data": {"target_id": target_id}
            }
            await edit_msg(chat_id, mid,
                f"🔨 Banning user {target_id}\n\nSend the ban reason:")

        # ── Orders overview ───────────────────────────────────
        elif data == "adm_orders":
            await answer_cb(cq_id)
            orders  = _load_orders()
            total   = len(orders)
            approved = sum(1 for o in orders.values() if o["status"] == "approved")
            pending  = sum(1 for o in orders.values() if o["status"] == "pending_approval")
            rejected = sum(1 for o in orders.values() if o["status"] == "rejected")
            cancelled= sum(1 for o in orders.values() if o["status"] == "cancelled")
            m = Msg()
            m.emoji("clipboard").text(" ").bold(f"Orders · {total}").nl(2)
            m.emoji("check").text(f"  Approved: {approved}").nl()
            m.emoji("timer").text(f"  Pending:  {pending}").nl()
            m.emoji("cross").text(f"  Rejected: {rejected}").nl()
            m.emoji("minus").text(f"  Cancelled:{cancelled}").nl(2)
            # Recent 5
            recent = list(reversed(list(orders.values())))[:5]
            if recent:
                m.bold("Recent Orders:").nl()
                for o in recent:
                    m.text(f"  #{o['order_id'][:8].upper()} {o['cat_name'][:15]} — {o['status']}").nl()
            t, ent = m.build()
            rows = []
            if pending:
                rows.append([btn(f"Pending · {pending}", "adm_pending", emoji_key="timer", style="danger")])
            rows.append([btn("Back", "adm_back", emoji_key="back")])
            await edit_msg(chat_id, mid, t, ent, build_keyboard(rows))

        # ── Revenue stats ─────────────────────────────────────
        elif data == "adm_revenue":
            await answer_cb(cq_id)
            orders = _load_orders()
            today_str   = datetime.now().strftime("%Y-%m-%d")
            month_str   = datetime.now().strftime("%Y-%m")
            total_rev   = sum(o["price"] for o in orders.values() if o["status"] == "approved")
            today_rev   = sum(o["price"] for o in orders.values()
                             if o["status"] == "approved" and o.get("created_at","").startswith(today_str))
            month_rev   = sum(o["price"] for o in orders.values()
                             if o["status"] == "approved" and o.get("created_at","").startswith(month_str))
            total_orders = sum(1 for o in orders.values() if o["status"] == "approved")
            m = Msg()
            m.emoji("moneybag").text(" ").bold("Revenue Report").nl(2)
            m.emoji("thunder").text(f"  Today:    $ {today_rev:.2f}").nl()
            m.emoji("balance").text(f"  This Month: $ {month_rev:.2f}").nl()
            m.emoji("wallet").text(f"  All Time:  $ {total_rev:.2f}").nl(2)
            m.emoji("cart").text(f"  Total Sales: {total_orders} orders")
            t, ent = m.build()
            await edit_msg(chat_id, mid, t, ent,
                keyboard=build_keyboard([[btn("Back", "adm_back", emoji_key="back")]]))

        # ── Wallet adjust ─────────────────────────────────────
        elif data == "adm_wallet":
            await answer_cb(cq_id)
            _admin_state[user.get("id")] = {"step": "wallet_adjust_uid", "data": {}}
            await edit_msg(chat_id, mid,
                "💰 *Wallet Adjust*\n\nSend the user ID to adjust their balance:")

        # ── Payment settings shortcut ─────────────────────────
        elif data == "adm_pay_set":
            await answer_cb(cq_id)
            pays = _load_payments()
            rows = []
            for k, v in pays.items():
                status = "✅" if v.get("enabled") else "🔴"
                addr   = v.get("address","")
                addr_p = addr[:10] + "..." if len(addr) > 10 else (addr or "NOT SET")
                rows.append([btn(f"{status} {v['label']} — {addr_p}", f"pay_mgr_{k}")])
            rows.append([btn("Back", "adm_back", emoji_key="back")])
            await edit_msg(chat_id, mid,
                "💳 Payment Settings\n\nTap a method to edit:",
                keyboard=build_keyboard(rows))

        # ── Broadcast shortcut ────────────────────────────────
        elif data == "adm_broadcast":
            await answer_cb(cq_id)
            _admin_state[user.get("id")] = {"step": "broadcast_msg", "data": {}}
            m = Msg()
            m.emoji("thunder").text(" ").bold("Broadcast Mode").nl(2)
            m.text("Send the message you want to broadcast to all users.")
            t, ent = m.build()
            await edit_msg(chat_id, mid, t, ent,
                keyboard=build_keyboard([[btn("Cancel", "broadcast_cancel", emoji_key="cross", style="danger")]]))

        # ── Audit log ─────────────────────────────────────────
        elif data == "adm_audit":
            await answer_cb(cq_id)
            orders  = _load_orders()
            db      = _load_db()
            recent  = list(reversed(list(orders.values())))[:10]
            m = Msg()
            m.emoji("document").text(" ").bold("Audit Log — Last 10 Events").nl(2)
            for o in recent:
                uid   = o["user_id"]
                udata = db.get(uid, {})
                uname = udata.get("username") or uid
                status_icon = {"approved":"✅","rejected":"❌","cancelled":"➖","pending_approval":"⏳","pending_payment":"🕐"}.get(o["status"],"?")
                m.text(f"{status_icon} {o['cat_name'][:15]} — @{uname} — {o['created_at'][:16]}").nl()
            t, ent = m.build()
            await edit_msg(chat_id, mid, t, ent,
                keyboard=build_keyboard([[btn("Back", "adm_back", emoji_key="back")]]))

        # ── Back to admin panel ───────────────────────────────
        elif data == "adm_back":
            await answer_cb(cq_id)
            t, ent, kb = await build_admin_panel()
            await edit_msg(chat_id, mid, t, ent, kb)

        else:
            await answer_cb(cq_id, "⚙️ Coming soon!", alert=True)

    else:
        await answer_cb(cq_id, "✅ Coming soon!", alert=True)

# ─── POLLING ──────────────────────────────────────────────────
async def _safe_handle(upd: dict):
    """Run a single update handler, catching all exceptions."""
    try:
        if "message" in upd:
            await handle_message(upd["message"])
        elif "callback_query" in upd:
            await handle_callback(upd["callback_query"])
    except Exception as ex:
        logger.exception(f"Handler error: {ex}")

async def poll():
    offset = 0
    logger.info("Polling started — bot is running!")
    while True:
        try:
            data = await api_call("getUpdates", {
                "offset":          offset,
                "timeout":         30,
                "allowed_updates": ["message", "callback_query"],
            })
            if not data.get("ok"):
                desc = data.get("description", "")
                if "Conflict" in desc:
                    logger.warning(f"Conflict detected — another instance running. Waiting 15s...")
                    await asyncio.sleep(15)
                else:
                    await asyncio.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                # Fire-and-forget: each update runs concurrently
                asyncio.create_task(_safe_handle(upd))
        except asyncio.CancelledError:
            break
        except Exception as ex:
            logger.error(f"Poll error: {ex}")
            await asyncio.sleep(5)

# ─── SET BOT COMMANDS (Hamburger Menu) ───────────────────────
async def set_bot_commands():
    """Register bot commands so they appear in Telegram's hamburger menu."""
    commands = [
        {"command": "start",    "description": "🏠 Main menu — Welcome screen"},
        {"command": "shop",     "description": "🛒 Browse products & buy"},
        {"command": "profile",  "description": "👤 View your profile"},
        {"command": "wallet",   "description": "💰 Check wallet balance"},
        {"command": "topup",    "description": "➕ Top up your wallet"},
        {"command": "referral", "description": "🎁 Referral program — earn rewards"},
        {"command": "history",  "description": "📋 View your order history"},
        {"command": "help",     "description": "❓ All commands & help"},
        {"command": "ping",     "description": "📡 Check if bot is online"},
    ]
    data = await api_call("setMyCommands", {"commands": commands})
    if data.get("ok"):
        logger.info("✅ Bot commands (hamburger menu) set successfully.")
    else:
        logger.warning(f"⚠️ Failed to set bot commands: {data.get('description','?')}")

# ─── KEEP-ALIVE HTTP SERVER ──────────────────────────────────
# Render (and most PaaS) web services must bind to $PORT or the deploy
# is marked failed ("no open ports detected"). This tiny server also
# gives an external uptime pinger something to hit to prevent free-tier
# spin-down. It does NOT affect the Telegram polling loop.
async def _health(request):
    return web.Response(text="OK — bot is running")

async def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server listening on 0.0.0.0:{port}")
    return runner

# ─── MAIN — Python 3.14 compatible ───────────────────────────
async def main():
    logger.info("=" * 50)
    logger.info("AI Chat Store Bot Starting...")
    logger.info("=" * 50)
    # Bind $PORT first so the platform detects an open port quickly
    await start_health_server()
    await db_init()
    # Register hamburger menu commands
    await set_bot_commands()
    # Clear any active webhook so polling works cleanly
    await api_call("deleteWebhook", {"drop_pending_updates": False})
    try:
        await poll()
    finally:
        await close_session()
        logger.info("Bot stopped.")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            loop.close()
        except Exception:
            pass





