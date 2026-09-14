"""app/util.py — formatting and id helpers shared by every screen."""

import random
import re
import string
import time
from datetime import datetime, timezone

from . import config

_ALPHABET = string.ascii_uppercase + string.digits
_SAFE = "".join(c for c in _ALPHABET if c not in "O0I1")


# ─── MONEY ────────────────────────────────────────────────────
def fmt_amount(value) -> str:
    """1.5 -> '1.500' (three decimals, matching the storefront style)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    return f"{value:.{config.PRICE_DECIMALS}f}"


def fmt_money(value) -> str:
    """1.5 -> '1.500 USD'."""
    return f"{fmt_amount(value)} {config.CURRENCY}"


def fmt_money_short(value) -> str:
    """1.5 -> '$1.500' for button labels."""
    return f"${fmt_amount(value)}"


def parse_amount(raw: str) -> float | None:
    """Read a user-typed amount. Accepts '1.5', '$1,50', '1 500'."""
    if not raw:
        return None
    cleaned = str(raw).strip().replace("$", "").replace(" ", "")
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return round(value, 6)


def parse_qty(raw: str) -> int | None:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# ─── IDS ──────────────────────────────────────────────────────
def gen_id(prefix: str, length: int = 6) -> str:
    return prefix + "".join(random.choices(_SAFE, k=length))


def gen_sku() -> str:
    """'PRD–HYSA2X' — en dash, matching the storefront style."""
    return "PRD–" + "".join(random.choices(_SAFE, k=6))


def gen_code(prefix: str = "", length: int = 10) -> str:
    body = "".join(random.choices(_SAFE, k=length))
    return f"{prefix}{body}" if prefix else body


def gen_order_id() -> str:
    return "ORD-" + "".join(random.choices(_SAFE, k=8))


def normalize_code(raw: str) -> str:
    return re.sub(r"[^A-Z0-9\-_]", "", str(raw or "").strip().upper())


def mask_user_id(user_id) -> str:
    """512345604 -> '51******04' (used in public channel posts)."""
    text = str(user_id or "")
    if len(text) <= 4:
        return "*" * max(len(text), 2)
    return f"{text[:2]}{'*' * 6}{text[-2:]}"


def mask_secret(value: str, keep: int = 4) -> str:
    text = str(value or "")
    if len(text) <= keep:
        return "*" * len(text)
    return text[:keep] + "*" * (len(text) - keep)


# ─── TIME ─────────────────────────────────────────────────────
def now_ts() -> int:
    return int(time.time())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fmt_date(ts) -> str:
    """Unix seconds or ISO string -> 'Sep 14, 2026 · 23:51 UTC'."""
    dt = _to_dt(ts)
    if not dt:
        return "—"
    return dt.strftime("%b %d, %Y · %H:%M UTC")


def fmt_day(ts) -> str:
    dt = _to_dt(ts)
    return dt.strftime("%b %d, %Y") if dt else "—"


def ago(ts) -> str:
    dt = _to_dt(ts)
    if not dt:
        return "—"
    seconds = max(int(datetime.now(timezone.utc).timestamp() - dt.timestamp()), 0)
    for limit, div, unit in (
        (60, 1, "s"), (3600, 60, "m"), (86400, 3600, "h"), (2592000, 86400, "d"),
    ):
        if seconds < limit:
            return f"{seconds // div}{unit} ago"
    return fmt_day(ts)


def _to_dt(ts) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ─── TEXT ─────────────────────────────────────────────────────
def clip(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def display_name(user: dict) -> str:
    first = (user.get("first_name") or "").strip()
    last = (user.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    if name:
        return clip(name, 40)
    username = (user.get("username") or "").strip()
    return f"@{username}" if username else "there"


def user_handle(record: dict) -> str:
    username = (record.get("username") or "").strip()
    return f"@{username}" if username else f"ID {record.get('id', '?')}"


def plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many
