"""
app/config.py — every tunable lives here.

NOTHING secret is hardcoded. Every credential, id and link is read from an
environment variable (see .env.example). The bot refuses to start if BOT_TOKEN
is missing, and simply hides a feature when its own config is blank
(e.g. no BINANCE_PAY_KEY -> Binance Pay button is not shown).
"""

import os

# ─── PATHS ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int = 0) -> int:
    raw = _env(name)
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float = 0.0) -> float:
    raw = _env(name)
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_ids(name: str) -> list:
    """Parse '123, 456 789' -> [123, 456, 789]."""
    raw = _env(name).replace(",", " ").split()
    out = []
    for chunk in raw:
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            out.append(int(chunk))
    return out


# ─── TELEGRAM ─────────────────────────────────────────────────
BOT_TOKEN = _env("BOT_TOKEN")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Admin user ids — comma separated. Without this nobody can open /admin.
ADMINS = _env_ids("ADMIN_IDS")

# Channel that receives NEW ORDER / WALLET FUNDED / ALMOST GONE posts.
LOG_CHANNEL_ID = _env_int("LOG_CHANNEL_ID", 0)

# Public channel users are pushed to join before they can shop.
FORCE_JOIN = _env_bool("FORCE_JOIN", False)
FORCE_JOIN_CHANNEL_ID = _env_int("FORCE_JOIN_CHANNEL_ID", 0)
FORCE_JOIN_LINK = _env("FORCE_JOIN_LINK")
FORCE_JOIN_NAME = _env("FORCE_JOIN_NAME", "our channel")

# ─── BRANDING ─────────────────────────────────────────────────
STORE_NAME = _env("STORE_NAME", "Store Bot")
BOT_LINK = _env("BOT_LINK")                      # https://t.me/yourbot
SUPPORT_USERNAME = _env("SUPPORT_USERNAME")      # without @
CHANNEL_LINK = _env("CHANNEL_LINK")
CURRENCY = _env("CURRENCY", "USD")

# Poster images shown above messages. Any of these may be:
#   * an https:// URL
#   * a Telegram file_id
#   * a path to a local file inside the repo
# Leave blank to send the message as plain text with no poster.
BANNER_START = _env("BANNER_START")
BANNER_PRODUCTS = _env("BANNER_PRODUCTS")
BANNER_WALLET = _env("BANNER_WALLET")
BANNER_ORDERS = _env("BANNER_ORDERS")
BANNER_GIFT = _env("BANNER_GIFT")
BANNER_SUPPORT = _env("BANNER_SUPPORT")
BANNER_PROFILE = _env("BANNER_PROFILE")
POSTER_NEW_ORDER = _env("POSTER_NEW_ORDER")
POSTER_WALLET_FUNDED = _env("POSTER_WALLET_FUNDED")
POSTER_ALMOST_GONE = _env("POSTER_ALMOST_GONE")
POSTER_DELIVERED = _env("POSTER_DELIVERED")

# ─── STORE RULES ──────────────────────────────────────────────
MIN_TOPUP = _env_float("MIN_TOPUP", 0.100)
MAX_TOPUP = _env_float("MAX_TOPUP", 5000.0)
PRICE_DECIMALS = _env_int("PRICE_DECIMALS", 3)
ORDER_EXPIRY_MINUTES = _env_int("ORDER_EXPIRY_MINUTES", 30)
LOW_STOCK_THRESHOLD = _env_int("LOW_STOCK_THRESHOLD", 3)
DEFAULT_LANG = _env("DEFAULT_LANG", "en")
REFERRAL_BONUS = _env_float("REFERRAL_BONUS", 0.0)

# Public read-only catalog API served by the health server (/api/catalog).
# Blank = endpoint disabled.
STORE_API_KEY = _env("STORE_API_KEY")

# ─── BINANCE PAY ──────────────────────────────────────────────
# Merchant credentials from https://merchant.binance.com -> Developers.
BINANCE_PAY_KEY = _env("BINANCE_PAY_KEY")
BINANCE_PAY_SECRET = _env("BINANCE_PAY_SECRET")
BINANCE_PAY_BASE = _env(
    "BINANCE_PAY_BASE", "https://bpay.binanceapi.com"
)
# Optional: Binance Pay ID shown to the user so they can also pay manually.
BINANCE_PAY_ID = _env("BINANCE_PAY_ID")

# ─── RUNTIME ──────────────────────────────────────────────────
PORT = _env_int("PORT", 10000)
POLL_TIMEOUT = _env_int("POLL_TIMEOUT", 30)
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()


def is_admin(user_id) -> bool:
    try:
        return int(user_id) in ADMINS
    except (TypeError, ValueError):
        return False


def support_url() -> str:
    if SUPPORT_USERNAME:
        return f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
    return ""


def missing_required() -> list:
    """Config the bot cannot run without."""
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN is not set")
    if not ADMINS:
        problems.append("ADMIN_IDS is not set (nobody can open the admin panel)")
    return problems
