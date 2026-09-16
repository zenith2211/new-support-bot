"""
app/config.py — every tunable lives here.

NOTHING secret is hardcoded. Every credential, id and link is read from an
environment variable (see .env.example). The bot refuses to start if BOT_TOKEN
is missing, and simply hides a feature when its own config is blank
(e.g. no BINANCE_PAY_KEY -> Binance Pay button is not shown).
"""

import logging
import os

logger = logging.getLogger(__name__)

# ─── PATHS ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─── .env ─────────────────────────────────────────────────────
def load_env_file(path: str = "") -> int:
    """Read KEY=VALUE lines from a .env file into the environment.

    A real environment variable always wins, so `BOT_TOKEN=x python bot.py`
    still overrides the file. Done by hand rather than with python-dotenv to
    keep the dependency list at aiohttp.
    """
    path = path or os.environ.get("ENV_FILE") or os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return 0

    loaded = 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].lstrip()
                key, sep, value = line.partition("=")
                if not sep:
                    continue
                key = key.strip()
                value = value.strip()
                # strip one layer of matching quotes, then trailing comments
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                elif " #" in value:
                    value = value.split(" #", 1)[0].strip()
                if key and key not in os.environ:
                    os.environ[key] = value
                    loaded += 1
    except OSError as exc:
        logger.warning("could not read %s: %s", path, exc)
        return 0
    return loaded


ENV_LOADED = load_env_file()
ENV_FILE_PATH = os.environ.get("ENV_FILE") or os.path.join(BASE_DIR, ".env")

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

# Master switch for every poster image. Off by default: the storefront is
# text-only, and no stored file_id or env var below can override that.
POSTERS = _env_bool("POSTERS", False)

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

# ─── CRYPTOMUS ────────────────────────────────────────────────
# Merchant uuid + *payment* API key from the Cryptomus dashboard. Payouts use
# a separate key; this bot never pays out, so only the payment key is needed.
CRYPTOMUS_MERCHANT_ID = _env("CRYPTOMUS_MERCHANT_ID")
CRYPTOMUS_API_KEY = _env("CRYPTOMUS_API_KEY")
CRYPTOMUS_BASE = _env("CRYPTOMUS_BASE", "https://api.cryptomus.com")
CRYPTOMUS_LABEL = _env("CRYPTOMUS_LABEL", "Crypto")
# Invoice currency. The customer still picks which coin to pay with, unless
# CRYPTOMUS_TO_CURRENCY / CRYPTOMUS_NETWORK pin it down.
CRYPTOMUS_CURRENCY = _env("CRYPTOMUS_CURRENCY", "USD")
CRYPTOMUS_TO_CURRENCY = _env("CRYPTOMUS_TO_CURRENCY")    # e.g. USDT
CRYPTOMUS_NETWORK = _env("CRYPTOMUS_NETWORK")            # e.g. tron
# Share of Cryptomus' commission charged to the customer, 0-100. At 100 the
# buyer covers the fee and the full invoice amount reaches your balance.
CRYPTOMUS_SUBTRACT = max(0, min(100, _env_int("CRYPTOMUS_SUBTRACT", 100)))
# Invoice lifespan in seconds. Cryptomus accepts 300-43200; we default to the
# store's own order expiry so an abandoned invoice and an abandoned order die
# at the same time. There is no cancel-invoice API — expiry is the only way.
CRYPTOMUS_LIFETIME = max(
    300, min(43200, _env_int("CRYPTOMUS_LIFETIME",
                             max(1, ORDER_EXPIRY_MINUTES) * 60)),
)
# Optional. The bot polls for payment status, so a webhook is never required;
# set this only if you happen to have a public https URL and want one.
CRYPTOMUS_CALLBACK_URL = _env("CRYPTOMUS_CALLBACK_URL")

# ─── NOWPAYMENTS ──────────────────────────────────────────────
# One API key, no request signing. Non-custodial: NOWPayments forwards to the
# outcome wallet you set in their dashboard, so nothing sits in an account.
NOWPAYMENTS_API_KEY = _env("NOWPAYMENTS_API_KEY")
NOWPAYMENTS_BASE = _env("NOWPAYMENTS_BASE", "https://api.nowpayments.io")
NOWPAYMENTS_LABEL = _env("NOWPAYMENTS_LABEL", "USDT")
# What the price is quoted in...
NOWPAYMENTS_CURRENCY = _env("NOWPAYMENTS_CURRENCY", "usd").lower()
# ...and the single coin customers pay with. The bot asks NOWPayments for a
# deposit address in this coin and shows it in the chat, so the customer never
# leaves Telegram and we never need a public success_url.
#
# SET THIS TO MATCH YOUR OUTCOME WALLET. The minimum payment depends on the
# pair, not the coin, and a mismatch is brutal: measured against a BEP-20
# outcome wallet, usdtbsc has a floor of ~$0.09 while usdttrc20 has ~$11.95.
# Matching also avoids a conversion, which is the difference between the 1%
# and 1.5% service fee. Run tools/check_nowpayments.py after changing it.
NOWPAYMENTS_PAY_CURRENCY = _env("NOWPAYMENTS_PAY_CURRENCY", "usdtbsc").lower()
# The coin your outcome wallet holds. Only used to compute the true minimum
# for the pair; defaults to the pay currency, i.e. no conversion.
NOWPAYMENTS_OUTCOME_CURRENCY = _env("NOWPAYMENTS_OUTCOME_CURRENCY",
                                    NOWPAYMENTS_PAY_CURRENCY).lower()
# Optional; polling means it is never required.
NOWPAYMENTS_CALLBACK_URL = _env("NOWPAYMENTS_CALLBACK_URL")

# ─── RUNTIME ──────────────────────────────────────────────────
PORT = _env_int("PORT", 10000)
# 0.0.0.0 is what cloud hosts need. Set 127.0.0.1 to keep the HTTP server
# reachable only from this machine when running locally.
HTTP_HOST = _env("HTTP_HOST", "0.0.0.0")
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
