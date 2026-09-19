"""
app/store.py — persistence and domain logic.

Records live wherever app/storage.py puts them: JSON files under DATA_DIR by
default, or Postgres when DATABASE_URL is set. Reads are served from an
in-memory cache; writes go straight through to the backend.

That cache is why money never goes through a plain read-modify-write here.
With one process the RLock below makes `balance = balance + x` safe. With
several — any serverless host — it does not, because each has its own cache
and its own lock. So every balance and stock change goes through
`_mutate()`, which on Postgres holds a row lock for the whole read-modify-
write. See app/storage.py for the mechanics.
"""

import logging
import os
import random
import threading

from . import config, storage, util

logger = logging.getLogger(__name__)

_lock = threading.RLock()

backend = storage.build()


def _path(name: str) -> str:
    return os.path.join(config.DATA_DIR, f"{name}.json")


def ensure_data_dir():
    backend.ensure()


class Table:
    """A dict of records, cached in memory and written through to `backend`."""

    def __init__(self, name: str):
        self.name = name
        self._cache: dict | None = None

    # ── io ────────────────────────────────────────────────────
    def all(self) -> dict:
        with _lock:
            if self._cache is None:
                self._cache = backend.load(self.name)
            return self._cache

    def save(self):
        """Write the whole table.

        Kept for the callers that mutate a record in place and then save. On
        Postgres this is a per-record rewrite of everything, so prefer put()
        or mutate() for anything hot.
        """
        with _lock:
            backend.replace_all(self.name, self.all())

    def reload(self):
        with _lock:
            self._cache = None

    # ── records ───────────────────────────────────────────────
    def get(self, key) -> dict | None:
        return self.all().get(str(key))

    def put(self, key, record, save: bool = True) -> dict:
        with _lock:
            self.all()[str(key)] = record
            if save:
                backend.put(self.name, str(key), record, self.all())
        return record

    def patch(self, key, **fields) -> dict | None:
        with _lock:
            record = self.get(key)
            if record is None:
                return None
            record.update(fields)
            backend.put(self.name, str(key), record, self.all())
            return record

    def delete(self, key, save: bool = True) -> bool:
        with _lock:
            existed = self.all().pop(str(key), None) is not None
            if existed and save:
                backend.delete(self.name, str(key), self.all())
            return existed

    def mutate(self, key, fn):
        """Read-modify-write one record safely, even with several writers.

        `fn(record)` returns the new record, or None to change nothing. On
        Postgres the read and the write share one transaction and a row lock,
        so a second writer waits rather than overwriting. Use this and not
        get()/save() for anything that adds to a number.
        """
        with _lock:
            result = backend.mutate(self.name, str(key), fn, self.all())
            if result is not None:
                self.all()[str(key)] = result
            return result

    def values(self) -> list:
        return list(self.all().values())

    def count(self) -> int:
        return len(self.all())


# Every table, in one place, so the migration tool and any future backend
# cannot drift from what the bot actually uses.
TABLE_NAMES = ("users", "categories", "products", "stock", "orders",
               "coupons", "giftcodes", "topups", "settings")

users = Table("users")
categories = Table("categories")
products = Table("products")
stock = Table("stock")
orders = Table("orders")
coupons = Table("coupons")
giftcodes = Table("giftcodes")
topups = Table("topups")
settings = Table("settings")


# ─── SETTINGS (runtime-editable, falls back to env config) ────
_SETTING_DEFAULTS = {
    "store_name": lambda: config.STORE_NAME,
    "support_username": lambda: config.SUPPORT_USERNAME,
    "channel_link": lambda: config.CHANNEL_LINK,
    "min_topup": lambda: config.MIN_TOPUP,
    "force_join": lambda: config.FORCE_JOIN,
    "terms": lambda: "",
    "api_note": lambda: "",
    "welcome_note": lambda: "",
}


def setting(key: str, default=None):
    record = settings.all().get(key)
    if isinstance(record, dict) and "value" in record:
        return record["value"]
    if key in _SETTING_DEFAULTS:
        return _SETTING_DEFAULTS[key]()
    return default


def set_setting(key: str, value):
    settings.put(key, {"value": value})


def store_name() -> str:
    return setting("store_name") or "Store Bot"


def min_topup() -> float:
    try:
        return float(setting("min_topup"))
    except (TypeError, ValueError):
        return config.MIN_TOPUP


def support_url() -> str:
    username = (setting("support_username") or "").lstrip("@")
    return f"https://t.me/{username}" if username else ""


def poster(slot: str) -> str:
    """The image for a poster slot, or "" for a text-only screen.

    Posters are off unless POSTERS=1. With them off this always returns
    nothing, so no stored value or env var can put an image back — the whole
    storefront stays text-only.

    `slot` is a config name like BANNER_START or POSTER_NEW_ORDER.
    """
    if not config.POSTERS:
        return ""
    saved = setting(f"poster_{slot}")
    if saved:
        return str(saved)
    return str(getattr(config, slot, "") or "")


def product_poster(product: dict) -> str:
    """A product's own image, honouring the same master switch."""
    if not config.POSTERS:
        return ""
    return str(product.get("image") or "")


# ─── USERS ────────────────────────────────────────────────────
def user_upsert(tg_user: dict) -> dict:
    uid = str(tg_user.get("id"))
    record = users.get(uid)
    if record is None:
        record = {
            "id": tg_user.get("id"),
            "username": tg_user.get("username") or "",
            "first_name": tg_user.get("first_name") or "",
            "last_name": tg_user.get("last_name") or "",
            "lang": (tg_user.get("language_code") or config.DEFAULT_LANG)[:2],
            "balance": 0.0,
            "spent": 0.0,
            "orders": 0,
            "topped_up": 0.0,
            "joined": util.now_ts(),
            "last_seen": util.now_ts(),
            "banned": False,
            "ban_reason": "",
            "terms_ok": False,
            "alerts_off": [],
            "referrer": None,
            "referrals": 0,
        }
        users.put(uid, record)
        return record

    changed = False
    for key in ("username", "first_name", "last_name"):
        value = tg_user.get(key) or ""
        if record.get(key) != value:
            record[key] = value
            changed = True
    if util.now_ts() - int(record.get("last_seen") or 0) > 300:
        record["last_seen"] = util.now_ts()
        changed = True
    if changed:
        users.save()
    return record


def user_get(user_id) -> dict:
    return users.get(user_id) or {}


def customer_id(user_id) -> str:
    """'#CX-201566' — a short public handle, safe to share for transfers
    (unlike a Telegram id, it reveals nothing and is stable per user)."""
    record = users.get(user_id)
    if record is None:
        return ""
    existing = record.get("customer_id")
    if existing:
        return existing
    with _lock:
        taken = {
            r.get("customer_id") for r in users.values()
            if r.get("customer_id")
        }
        while True:
            candidate = f"#CX-{random.randint(100000, 999999)}"
            if candidate not in taken:
                break
        record["customer_id"] = candidate
        users.save()
    return candidate


def find_by_customer_id(code: str) -> dict | None:
    wanted = util.normalize_code(code).lstrip("#")
    if not wanted:
        return None
    if not wanted.startswith("CX"):
        wanted = f"CX-{wanted}"
    wanted = wanted.replace("CX", "CX-").replace("--", "-")
    for record in users.values():
        stored = str(record.get("customer_id") or "").lstrip("#").upper()
        if stored and stored == wanted:
            return record
    return None


def transfer(from_id, to_id, amount: float) -> tuple[bool, str]:
    """Move wallet balance between users. -> (ok, error_key)"""
    amount = round(float(amount), 6)
    if amount <= 0:
        return False, "err_bad_number"
    if str(from_id) == str(to_id):
        return False, "transfer_self"
    if users.get(to_id) is None:
        return False, "transfer_no_user"

    with _lock:
        sender = users.get(from_id)
        if sender is None:
            return False, "err_not_found"
        if float(sender.get("balance") or 0.0) + 1e-9 < amount:
            return False, "transfer_short"
        sender["balance"] = round(
            float(sender.get("balance") or 0.0) - amount, 6)
        receiver = users.get(to_id)
        receiver["balance"] = round(
            float(receiver.get("balance") or 0.0) + amount, 6)
        users.save()
    return True, ""


def user_lang(user_id) -> str:
    return (user_get(user_id).get("lang") or config.DEFAULT_LANG)[:2]


def user_set_lang(user_id, lang: str):
    users.patch(user_id, lang=lang[:2])


def balance_of(user_id) -> float:
    try:
        return round(float(user_get(user_id).get("balance") or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def credit(user_id, amount: float, kind: str = "topup") -> float:
    """Add to a wallet. Returns the new balance.

    Goes through mutate() rather than get()/save(): two deposits landing at
    once must not both read the old balance and write back their own total.
    """
    def apply(record):
        if record is None:
            return None
        record = dict(record)
        record["balance"] = round(
            float(record.get("balance") or 0.0) + float(amount), 6)
        if kind == "topup":
            record["topped_up"] = round(
                float(record.get("topped_up") or 0.0) + float(amount), 6)
        return record

    result = users.mutate(user_id, apply)
    if result is None:
        return 0.0
    return float(result.get("balance") or 0.0)


def debit(user_id, amount: float) -> bool:
    """Spend from a wallet. False (and no change) when funds are short.

    The funds check and the deduction share one transaction, so a wallet
    cannot be spent twice by two requests that both saw enough balance.
    """
    charge = float(amount)

    def apply(record):
        if record is None:
            return None
        balance = float(record.get("balance") or 0.0)
        if balance + 1e-9 < charge:
            return None                 # rolls back, leaves the row untouched
        record = dict(record)
        record["balance"] = round(balance - charge, 6)
        record["spent"] = round(float(record.get("spent") or 0.0) + charge, 6)
        record["orders"] = int(record.get("orders") or 0) + 1
        return record

    return users.mutate(user_id, apply) is not None


def is_banned(user_id) -> tuple[bool, str]:
    record = user_get(user_id)
    return bool(record.get("banned")), record.get("ban_reason") or ""


def set_banned(user_id, banned: bool, reason: str = ""):
    users.patch(user_id, banned=banned, ban_reason=reason if banned else "")


def accept_terms(user_id):
    users.patch(user_id, terms_ok=True)


def alerts_enabled(user_id, pid: str) -> bool:
    return pid not in (user_get(user_id).get("alerts_off") or [])


def toggle_alerts(user_id, pid: str) -> bool:
    """Flip per-product alerts. Returns the new enabled state."""
    with _lock:
        record = users.get(user_id)
        if record is None:
            return True
        off = list(record.get("alerts_off") or [])
        if pid in off:
            off.remove(pid)
            enabled = True
        else:
            off.append(pid)
            enabled = False
        record["alerts_off"] = off
        users.save()
        return enabled


def alert_audience(pid: str) -> list:
    """User ids that still want alerts for this product and are not banned."""
    out = []
    for record in users.values():
        if record.get("banned"):
            continue
        if pid in (record.get("alerts_off") or []):
            continue
        out.append(record.get("id"))
    return [uid for uid in out if uid]


# ─── CATEGORIES ───────────────────────────────────────────────
def category_list(include_hidden: bool = False) -> list:
    items = [
        c for c in categories.values()
        if include_hidden or c.get("enabled", True)
    ]
    return sorted(items, key=lambda c: (int(c.get("position") or 0),
                                        str(c.get("name") or "")))


def category_save(cat_id: str, **fields) -> dict:
    record = categories.get(cat_id) or {
        "id": cat_id,
        "name": "",
        "emoji": "box",
        "position": len(categories.all()),
        "enabled": True,
        "created": util.now_ts(),
    }
    record.update(fields)
    categories.put(cat_id, record)
    return record


def category_delete(cat_id: str, cascade: bool = True):
    if cascade:
        for product in products_in(cat_id, include_hidden=True):
            product_delete(product["id"])
    categories.delete(cat_id)


# ─── PRODUCTS ─────────────────────────────────────────────────
def products_in(cat_id: str, include_hidden: bool = False) -> list:
    items = [
        p for p in products.values()
        if str(p.get("cat_id")) == str(cat_id)
        and (include_hidden or p.get("enabled", True))
    ]
    return sorted(items, key=lambda p: (int(p.get("position") or 0),
                                        str(p.get("name") or "")))


def product_get(pid: str) -> dict | None:
    return products.get(pid)


def product_save(pid: str, **fields) -> dict:
    record = products.get(pid) or {
        "id": pid,
        "cat_id": "",
        "name": "",
        "emoji": "box",
        "sku": util.gen_sku(),
        "price": 0.0,
        "description": "",
        "delivery_note": "",
        "image": "",
        "delivery_mode": "instant",     # instant | manual
        "delivery_channel": "chat",
        "stock_mode": "lines",          # lines | unlimited | manual
        "manual_stock": 0,
        "min_qty": 1,
        "max_qty": 10,
        # Volume discounts: [{"qty": 5, "off": 0.15}, ...] = buy 5 or more and
        # each unit costs 0.15 less. Highest matching tier wins.
        "bulk": [],
        "warranty": "",
        "sold": 0,
        "position": 0,
        "enabled": True,
        "created": util.now_ts(),
    }
    record.update(fields)
    products.put(pid, record)
    return record


def product_delete(pid: str):
    products.delete(pid)
    stock.delete(pid)


def bulk_tiers(product: dict) -> list:
    """Sorted, validated volume-discount tiers for a product."""
    tiers = []
    for tier in (product.get("bulk") or []):
        try:
            qty = int(tier.get("qty") or 0)
            off = float(tier.get("off") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if qty > 1 and off > 0:
            tiers.append({"qty": qty, "off": round(off, 6)})
    tiers.sort(key=lambda t: t["qty"])
    return tiers


def unit_price_for(product: dict, qty: int) -> tuple[float, dict | None]:
    """Per-unit price at this quantity. -> (price, tier applied or None)"""
    base = float(product.get("price") or 0.0)
    applied = None
    for tier in bulk_tiers(product):
        if qty >= tier["qty"]:
            applied = tier
    if not applied:
        return base, None
    return max(round(base - applied["off"], 6), 0.0), applied


def bulk_label(product: dict) -> str:
    """'Bulk x5+' for listings, or '' when the product has no tiers."""
    tiers = bulk_tiers(product)
    return f"Bulk x{tiers[0]['qty']}+" if tiers else ""


def quote(pid: str, qty: int, coupon_code: str = "") -> dict:
    """Price a basket without touching anything. -> dict of numbers.

    Volume tiers apply first (they change the per-unit price), then a coupon
    applies to the resulting subtotal. Lives here rather than in shop.py so
    both the screens and the checkout can price without a circular import.
    """
    product = product_get(pid) or {}
    qty = max(int(qty or 1), 1)
    list_price = float(product.get("price") or 0.0)
    price, tier = unit_price_for(product, qty)
    subtotal = round(price * qty, 6)

    discount = 0.0
    coupon = None
    if coupon_code:
        coupon, _err, discount = coupon_check(coupon_code, pid, subtotal)
    return {
        "list_price": list_price,
        "price": price,
        "tier": tier,
        "bulk_saved": round((list_price - price) * qty, 6),
        "qty": qty,
        "subtotal": subtotal,
        "discount": round(discount, 6),
        "total": round(subtotal - discount, 6),
        "coupon": coupon["code"] if coupon else "",
    }


def qty_presets(product: dict, available: int) -> list:
    """Quantity buttons to offer: the first few, plus each volume tier's
    threshold, so the cheaper per-unit prices are one tap away."""
    min_qty = max(int(product.get("min_qty") or 1), 1)
    max_qty = max(int(product.get("max_qty") or 1), min_qty)
    if product.get("stock_mode") != "unlimited":
        max_qty = min(max_qty, max(available, min_qty))

    wanted = [min_qty, min_qty + 1, min_qty + 2]
    wanted += [tier["qty"] for tier in bulk_tiers(product)]

    out = []
    for value in wanted:
        if min_qty <= value <= max_qty and value not in out:
            out.append(value)
    return sorted(out)[:6]


def product_count(include_hidden: bool = False) -> int:
    return len([
        p for p in products.values()
        if include_hidden or p.get("enabled", True)
    ])


# ─── STOCK ────────────────────────────────────────────────────
UNLIMITED = 10 ** 6


def stock_lines(pid: str) -> list:
    value = stock.get(pid)
    if isinstance(value, list):
        return value
    return []


def stock_count(pid: str) -> int:
    product = product_get(pid) or {}
    mode = product.get("stock_mode", "lines")
    if mode == "unlimited":
        return UNLIMITED
    if mode == "manual":
        try:
            return max(int(product.get("manual_stock") or 0), 0)
        except (TypeError, ValueError):
            return 0
    return len(stock_lines(pid))


def stock_display(pid: str) -> str:
    product = product_get(pid) or {}
    if product.get("stock_mode") == "unlimited":
        return "∞"
    return str(stock_count(pid))


def stock_is_unlimited(pid: str) -> bool:
    return (product_get(pid) or {}).get("stock_mode") == "unlimited"


def stock_add(pid: str, lines: list) -> int:
    with _lock:
        existing = list(stock_lines(pid))
        fresh = [str(line).strip() for line in lines if str(line).strip()]
        existing.extend(fresh)
        stock.put(pid, existing)
        return len(existing)


def stock_set_manual(pid: str, count: int):
    product_save(pid, manual_stock=max(int(count), 0))


def stock_clear(pid: str):
    stock.put(pid, [])


def stock_take(pid: str, qty: int) -> list | None:
    """Reserve `qty` units. Returns the delivered payload lines, or None when
    stock is short.

    The check and the decrement share one transaction, so two buyers cannot
    be handed the same account: whoever gets the row lock second sees the
    already-shortened list.
    """
    product = product_get(pid)
    if not product:
        return None
    mode = product.get("stock_mode", "lines")

    if mode == "unlimited":
        return [""] * qty

    if mode == "manual":
        # The counter lives on the product record, so lock that instead.
        def take_counter(record):
            if record is None:
                return None
            have = int(record.get("manual_stock") or 0)
            if have < qty:
                return None
            record = dict(record)
            record["manual_stock"] = have - qty
            return record

        if products.mutate(pid, take_counter) is None:
            return None
        return [""] * qty

    taken: list = []

    def take_lines(lines):
        available = list(lines or [])
        if len(available) < qty:
            return None
        taken.extend(available[:qty])
        return available[qty:]

    if stock.mutate(pid, take_lines) is None:
        return None
    return taken


def stock_return(pid: str, lines: list):
    """Put reserved lines back (used when delivery fails)."""
    with _lock:
        product = product_get(pid) or {}
        mode = product.get("stock_mode", "lines")
        if mode == "unlimited":
            return
        if mode == "manual":
            product_save(pid, manual_stock=stock_count(pid) + len(lines))
            return
        current = list(stock_lines(pid))
        stock.put(pid, [*lines, *current])


def stock_counts_by_category() -> dict:
    """{cat_id: total units in stock} for the categories screen."""
    totals: dict = {}
    for product in products.values():
        if not product.get("enabled", True):
            continue
        cat_id = str(product.get("cat_id"))
        totals[cat_id] = totals.get(cat_id, 0) + stock_count(product["id"])
    return totals


def low_stock_products(threshold: int | None = None) -> list:
    limit = config.LOW_STOCK_THRESHOLD if threshold is None else threshold
    out = []
    for product in products.values():
        if not product.get("enabled", True):
            continue
        if product.get("stock_mode") == "unlimited":
            continue
        count = stock_count(product["id"])
        if 0 < count <= limit:
            out.append((product, count))
    return out


# ─── ORDERS ───────────────────────────────────────────────────
def order_create(**fields) -> dict:
    order_id = fields.get("id") or util.gen_order_id()
    record = {
        "id": order_id,
        "user_id": None,
        "username": "",
        "pid": "",
        "product_name": "",
        "sku": "",
        "qty": 1,
        "unit_price": 0.0,
        "subtotal": 0.0,
        "discount": 0.0,
        "total": 0.0,
        "coupon": "",
        "status": "pending",
        "items": [],
        "method": "wallet",
        "created": util.now_ts(),
        "delivered": None,
    }
    record.update(fields)
    record["id"] = order_id
    orders.put(order_id, record)
    return record


def order_get(order_id: str) -> dict | None:
    return orders.get(order_id)


def orders_of(user_id, limit: int = 10) -> list:
    mine = [
        o for o in orders.values()
        if str(o.get("user_id")) == str(user_id)
    ]
    mine.sort(key=lambda o: int(o.get("created") or 0), reverse=True)
    return mine[:limit]


def orders_recent(limit: int = 20) -> list:
    every = sorted(orders.values(),
                   key=lambda o: int(o.get("created") or 0), reverse=True)
    return every[:limit]


def record_sale(pid: str, qty: int):
    product = product_get(pid)
    if product:
        product_save(pid, sold=int(product.get("sold") or 0) + int(qty))


# ─── COUPONS ──────────────────────────────────────────────────
def coupon_get(code: str) -> dict | None:
    return coupons.get(util.normalize_code(code))


def coupon_save(code: str, **fields) -> dict:
    code = util.normalize_code(code)
    record = coupons.get(code) or {
        "code": code,
        "kind": "percent",      # percent | fixed
        "value": 0.0,
        "uses": 0,
        "max_uses": 0,          # 0 = unlimited
        "expires": 0,           # unix ts, 0 = never
        "scope_pid": "",        # "" = every product
        "enabled": True,
        "created": util.now_ts(),
    }
    record.update(fields)
    coupons.put(code, record)
    return record


def coupon_check(code: str, pid: str, subtotal: float) -> tuple[dict | None, str, float]:
    """Validate a coupon. -> (record, error_key, discount_amount)."""
    record = coupon_get(code)
    if not record or not record.get("enabled", True):
        return None, "coupon_unknown", 0.0
    if record.get("expires") and util.now_ts() > int(record["expires"]):
        return None, "coupon_expired", 0.0
    max_uses = int(record.get("max_uses") or 0)
    if max_uses and int(record.get("uses") or 0) >= max_uses:
        return None, "coupon_used_up", 0.0
    scope = record.get("scope_pid") or ""
    if scope and scope != pid:
        return None, "coupon_other_product", 0.0

    if record.get("kind") == "fixed":
        discount = float(record.get("value") or 0.0)
    else:
        discount = subtotal * float(record.get("value") or 0.0) / 100.0
    discount = round(min(discount, subtotal), 6)
    if discount <= 0:
        return None, "coupon_zero", 0.0
    return record, "", discount


def coupon_consume(code: str):
    record = coupon_get(code)
    if record:
        coupon_save(record["code"], uses=int(record.get("uses") or 0) + 1)


# ─── GIFT CODES ───────────────────────────────────────────────
def giftcode_save(code: str, **fields) -> dict:
    code = util.normalize_code(code)
    record = giftcodes.get(code) or {
        "code": code,
        "amount": 0.0,
        "uses": 0,
        "max_uses": 1,
        "used_by": [],
        "expires": 0,
        "enabled": True,
        "created": util.now_ts(),
    }
    record.update(fields)
    giftcodes.put(code, record)
    return record


def giftcode_redeem(code: str, user_id) -> tuple[float, str]:
    """-> (credited_amount, error_key). Amount is 0 on failure."""
    with _lock:
        code = util.normalize_code(code)
        record = giftcodes.get(code)
        if not record or not record.get("enabled", True):
            return 0.0, "gift_unknown"
        if record.get("expires") and util.now_ts() > int(record["expires"]):
            return 0.0, "gift_expired"
        used_by = [str(x) for x in (record.get("used_by") or [])]
        if str(user_id) in used_by:
            return 0.0, "gift_already"
        max_uses = int(record.get("max_uses") or 0)
        if max_uses and int(record.get("uses") or 0) >= max_uses:
            return 0.0, "gift_used_up"

        amount = float(record.get("amount") or 0.0)
        if amount <= 0:
            return 0.0, "gift_unknown"

        record["uses"] = int(record.get("uses") or 0) + 1
        used_by.append(str(user_id))
        record["used_by"] = used_by
        giftcodes.put(code, record)

    credit(user_id, amount, kind="topup")
    return amount, ""


# ─── TOP-UPS ──────────────────────────────────────────────────
def topup_create(**fields) -> dict:
    topup_id = fields.get("id") or util.gen_id("TOP-", 8)
    record = {
        "id": topup_id,
        "user_id": None,
        "amount": 0.0,
        "method": "",
        "status": "pending",       # pending | paid | expired | cancelled
        "created": util.now_ts(),
        "paid": None,
        "provider_ref": "",
        "checkout_url": "",
        "intent_pid": "",
        "intent_qty": 0,
        "intent_coupon": "",
        "credited": False,
    }
    record.update(fields)
    record["id"] = topup_id
    topups.put(topup_id, record)
    return record


def topup_get(topup_id: str) -> dict | None:
    return topups.get(topup_id)


def topups_pending() -> list:
    return [t for t in topups.values() if t.get("status") == "pending"]


def topups_of(user_id, limit: int = 10) -> list:
    mine = [t for t in topups.values() if str(t.get("user_id")) == str(user_id)]
    mine.sort(key=lambda t: int(t.get("created") or 0), reverse=True)
    return mine[:limit]


def topup_mark_paid(topup_id: str, provider_ref: str = "") -> dict | None:
    """Flip a top-up to paid and credit the wallet exactly once."""
    with _lock:
        record = topups.get(topup_id)
        if not record or record.get("credited"):
            return None
        record["status"] = "paid"
        record["paid"] = util.now_ts()
        if provider_ref:
            record["provider_ref"] = provider_ref
        record["credited"] = True
        topups.put(topup_id, record)

    credit(record["user_id"], record["amount"], kind="topup")
    return record


# ─── STATS ────────────────────────────────────────────────────
def stats() -> dict:
    all_orders = orders.values()
    delivered = [o for o in all_orders if o.get("status") == "delivered"]
    revenue = sum(float(o.get("total") or 0.0) for o in delivered)
    wallets = sum(float(u.get("balance") or 0.0) for u in users.values())
    today = util.now_ts() - 86400
    return {
        "users": users.count(),
        "users_today": len([
            u for u in users.values() if int(u.get("joined") or 0) >= today
        ]),
        "banned": len([u for u in users.values() if u.get("banned")]),
        "categories": len(category_list(include_hidden=True)),
        "products": product_count(include_hidden=True),
        "stock_units": sum(stock_count(p["id"]) for p in products.values()
                           if p.get("stock_mode") != "unlimited"),
        "orders": len(all_orders),
        "orders_today": len([
            o for o in all_orders if int(o.get("created") or 0) >= today
        ]),
        "delivered": len(delivered),
        "revenue": round(revenue, 6),
        "wallets": round(wallets, 6),
        "pending_topups": len(topups_pending()),
        "coupons": coupons.count(),
        "giftcodes": giftcodes.count(),
    }


# ─── DEMO CATALOG ─────────────────────────────────────────────
_DEMO_CATEGORIES = [
    ("cgemini", "Gemini Pro", "spark"),
    ("cicloud", "iCloud Mail Account", "mail"),
    ("choutlk", "HotMail/Outlook Account", "mail"),
    ("cproxy", "CliProxy Residential Data", "key"),
    ("cspoti", "Spotify Premium", "star"),
    ("cduolg", "Duolingo", "box"),
]

_DEMO_SPOTIFY_DESC = (
    "Get a full-access Spotify Premium account with a 3-month subscription.\n\n"
    "• Duration: 3 Months\n"
    "• Warranty: 7 Days\n"
    "• Full Access Account\n\n"
    "Account Format:\n"
    "Email | Email Password | Email Link | Spotify Password\n"
    "Email | Email Password | Backup Mail | Spotify Password\n\n"
    "Enjoy ad-free music, offline downloads, unlimited skips, "
    "and premium features!"
)

_DEMO_PRODUCTS = [
    ("pgemin1", "cgemini", "Gemini Pro 1 Month (Own Mail)", "spark", 2.5,
     "Gemini Pro subscription activated on your own Google account.\n\n"
     "• Duration: 1 Month\n• Warranty: 3 Days\n• Activated on your mail"),
    ("picld1", "cicloud", "iCloud Mail Account – Fresh", "mail", 0.9,
     "Fresh iCloud mail account with full inbox access.\n\n"
     "• Fresh & unused\n• Warranty: Login only"),
    ("photm1", "choutlk", "HotMail/Outlook Account – Aged", "mail", 0.35,
     "Aged Outlook/HotMail account, ready for verification use.\n\n"
     "• Aged domain\n• Warranty: Login only"),
    ("pprox1", "cproxy", "CliProxy Residential 1 GB", "key", 3.0,
     "Residential proxy data for CliProxy.\n\n"
     "• 1 GB data\n• Rotating residential IPs\n• Warranty: Data only"),
    ("pspot1", "cspoti", "Spotify Premium Account – 3 Months Access "
     "(7 Day Warranty)", "star", 1.5, _DEMO_SPOTIFY_DESC),
    ("pduol1", "cduolg", "Duolingo Super 1 Month", "box", 1.2,
     "Duolingo Super on your own account.\n\n"
     "• Duration: 1 Month\n• Warranty: 3 Days"),
]


def seed_demo_catalog() -> bool:
    """Populate a sample catalog on first run so the storefront is browsable
    before you add anything. Delete it from the admin panel when you add your
    own products; it is never re-created once categories exist."""
    if categories.count() or products.count():
        return False

    for position, (cat_id, name, emoji_name) in enumerate(_DEMO_CATEGORIES):
        category_save(cat_id, name=name, emoji=emoji_name, position=position,
                      enabled=True)

    for position, (pid, cat_id, name, emoji_name, price, desc) in enumerate(
            _DEMO_PRODUCTS):
        product_save(
            pid,
            cat_id=cat_id,
            name=name,
            emoji=emoji_name,
            price=price,
            description=desc,
            delivery_note=desc.split("\n\n")[0],
            position=position,
            stock_mode="lines",
            min_qty=1,
            max_qty=5,
            sold=31 if pid == "pspot1" else 0,
        )
        stock_add(pid, [
            f"demo{position}{n}@example.com | demo-pass | link | spotify-pass"
            for n in range(1, 2 if pid == "pspot1" else 3)
        ])

    logger.info("seeded demo catalog (%d categories, %d products)",
                len(_DEMO_CATEGORIES), len(_DEMO_PRODUCTS))
    return True


def init():
    ensure_data_dir()
    for table in (users, categories, products, stock, orders, coupons,
                  giftcodes, topups, settings):
        table.all()          # warm the cache / create nothing until first save
    seed_demo_catalog()
