"""
tests/flow.py — drive real updates through the router with a faked Bot API.

    python -m tests.flow

Nothing leaves the process: app.tg.api is replaced by a recorder that returns
plausible Telegram responses. This exercises the parts the screen smoke test
cannot reach — callback routing, prompt state, the buy path, the low-balance
detour, gift codes and the admin panel.

Exit code is non-zero if any step fails.
"""

import asyncio
import os
import sys
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456:test-token-not-real")
os.environ.setdefault("ADMIN_IDS", "424242")
os.environ.setdefault("STORE_NAME", "ToolBox Store Bot")
os.environ.setdefault("SUPPORT_USERNAME", "your_support")
os.environ.setdefault("LOG_CHANNEL_ID", "-1009999999999")
# Gives the wallet one selectable payment method, so the two-step Add funds
# flow (method -> amount -> invoice) is exercised end to end.
os.environ.setdefault("MANUAL_PAY", "1")
os.environ.setdefault("MANUAL_PAY_LABEL", "Pay manually")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="storebot-flow-"))

# Same guard as tests/smoke.py: this suite buys, credits, bans and deletes.
_DATA_DIR = os.environ["DATA_DIR"]
if "storebot-flow-" not in _DATA_DIR and not os.environ.get("ALLOW_LIVE_DATA"):
    sys.stderr.write(
        f"refusing to run against DATA_DIR={_DATA_DIR!r}\n"
        "This suite writes test orders and balances. Unset DATA_DIR to use a\n"
        "temp dir, or set ALLOW_LIVE_DATA=1 if you really mean it.\n")
    raise SystemExit(2)

from app import config, screens, store, tg                    # noqa: E402
from app.handlers import router                                # noqa: E402

USER = {"id": 512345604, "first_name": "Coder", "username": "coder",
        "language_code": "en"}
ADMIN = {"id": 424242, "first_name": "Owner", "username": "owner",
         "language_code": "en"}
CHANNEL = -1009999999999

FAILURES: list = []
CALLS: list = []
_message_id = 1000
_update_id = 1


def fail(step: str, detail: str):
    FAILURES.append(f"{step}: {detail}")


# ─── FAKE BOT API ─────────────────────────────────────────────
async def fake_api(method: str, payload: dict | None = None,
                   files: dict | None = None, quiet: bool = False) -> dict:
    global _message_id
    payload = payload or {}
    CALLS.append((method, payload))

    if method == "getMe":
        return {"ok": True, "result": {"id": 777, "username": "teststorebot"}}
    if method in ("sendMessage", "sendPhoto", "sendDocument"):
        _message_id += 1
        result = {
            "message_id": _message_id,
            "chat": {"id": payload.get("chat_id"), "type": "private"},
        }
        if method == "sendPhoto":
            result["photo"] = [{"file_id": "fake"}]
        return {"ok": True, "result": result}
    if method == "getChatMember":
        return {"ok": True, "result": {"status": "member"}}
    return {"ok": True, "result": True}


def sent_to(chat_id) -> list:
    """Texts/captions sent to one chat, in order."""
    out = []
    for method, payload in CALLS:
        if payload.get("chat_id") != chat_id:
            continue
        if method in ("sendMessage", "editMessageText"):
            out.append(payload.get("text") or "")
        elif method in ("sendPhoto", "editMessageCaption"):
            out.append(payload.get("caption") or "")
        elif method == "editMessageMedia":
            out.append((payload.get("media") or {}).get("caption") or "")
    return out


def last_text(chat_id) -> str:
    texts = sent_to(chat_id)
    return texts[-1] if texts else ""


def last_keyboard(chat_id) -> list:
    for method, payload in reversed(CALLS):
        if payload.get("chat_id") != chat_id:
            continue
        markup = payload.get("reply_markup") or {}
        rows = markup.get("inline_keyboard")
        if rows:
            return [b for row in rows for b in row]
    return []


def callbacks(chat_id) -> list:
    return [b.get("callback_data") for b in last_keyboard(chat_id)
            if b.get("callback_data")]


def toasts() -> list:
    return [p.get("text") or "" for m, p in CALLS
            if m == "answerCallbackQuery"]


def reset():
    CALLS.clear()


# ─── UPDATE HELPERS ───────────────────────────────────────────
def message_update(text: str, user: dict = None) -> dict:
    global _update_id
    _update_id += 1
    user = user or USER
    return {
        "update_id": _update_id,
        "message": {
            "message_id": _update_id,
            "from": user,
            "chat": {"id": user["id"], "type": "private"},
            "text": text,
        },
    }


def callback_update(data: str, user: dict = None,
                    photo: bool = False) -> dict:
    global _update_id
    _update_id += 1
    user = user or USER
    message = {
        "message_id": 500,
        "chat": {"id": user["id"], "type": "private"},
        "text": "previous screen",
    }
    if photo:
        message["photo"] = [{"file_id": "fake"}]
    return {
        "update_id": _update_id,
        "callback_query": {
            "id": f"cq{_update_id}",
            "from": user,
            "message": message,
            "data": data,
        },
    }


async def send(text: str, user: dict = None):
    await router.handle_update(message_update(text, user))


async def press(data: str, user: dict = None, photo: bool = False):
    await router.handle_update(callback_update(data, user, photo))


def expect(step: str, condition: bool, detail: str = ""):
    if not condition:
        fail(step, detail or "condition was false")


def expect_in(step: str, needle: str, haystack: str):
    if needle.lower() not in (haystack or "").lower():
        fail(step, f"expected {needle!r} in:\n{haystack[:400]}")


# ─── SCENARIOS ────────────────────────────────────────────────
async def scenario_browse_and_buy():
    reset()
    await send("/start")
    text = last_text(USER["id"])
    expect_in("start", "Hello Coder", text)
    expect_in("start", "/products", text)
    expect_in("start", "/wallet", text)
    expect_in("start", "/gift", text)
    expect_in("start", "Keep enough balance", text)
    expect("start reply keyboard",
           any((p.get("reply_markup") or {}).get("keyboard")
               for _m, p in CALLS),
           "no persistent keyboard was sent")

    reset()
    await send("🎁 Products")
    expect_in("products via keyboard", "Categories", last_text(USER["id"]))
    expect("category buttons",
           any(str(c).startswith("cat:") for c in callbacks(USER["id"])),
           f"got {callbacks(USER['id'])}")

    reset()
    await press("cat:cspoti")
    expect_in("category", "SPOTIFY PREMIUM", last_text(USER["id"]))
    expect("product button", "p:pspot1" in callbacks(USER["id"]),
           f"got {callbacks(USER['id'])}")

    reset()
    await press("p:pspot1")
    text = last_text(USER["id"])
    expect_in("product", "Unit price: 1.500 USD", text)
    expect_in("product", "Sold: 31", text)
    expect_in("product", "SKU", text)
    expect("buy button", "buy:pspot1:1" in callbacks(USER["id"]),
           f"got {callbacks(USER['id'])}")

    # no money yet -> confirm, then the low-balance screen
    reset()
    await press("buy:pspot1:1")
    expect_in("confirm", "Confirm order", last_text(USER["id"]))
    expect("confirm buttons", "ok:pspot1:1" in callbacks(USER["id"]),
           f"got {callbacks(USER['id'])}")

    reset()
    await press("ok:pspot1:1")
    text = last_text(USER["id"])
    expect_in("low balance", "LOW BALANCE", text)
    expect_in("low balance", "Need 1.500 USD more", text)
    expect("pay button", "pay:pspot1:1" in callbacks(USER["id"]),
           f"got {callbacks(USER['id'])}")

    reset()
    await press("pay:pspot1:1")
    text = last_text(USER["id"])
    expect_in("pay methods", "Pay and get item", text)
    expect_in("shortfall shown", "Pay now: 1.500 USD", text)
    expect("gateway offered for the shortfall",
           any(c == "paym:manual:pspot1:1" for c in callbacks(USER["id"])),
           f"got {callbacks(USER['id'])}")

    # fund the wallet and buy for real
    store.credit(USER["id"], 5.0)
    reset()
    await press("ok:pspot1:1")
    text = last_text(USER["id"])
    expect_in("delivered", "DELIVERED", text)
    expect_in("delivered", "ORD-", text)
    expect("wallet debited",
           abs(store.balance_of(USER["id"]) - 3.5) < 1e-6,
           f"balance is {store.balance_of(USER['id'])}")
    expect("stock decremented", store.stock_count("pspot1") == 0,
           f"stock is {store.stock_count('pspot1')}")

    channel = sent_to(CHANNEL)
    expect("NEW ORDER posted", any("NEW ORDER" in t for t in channel),
           f"channel got {channel}")

    # out of stock now
    reset()
    await press("buy:pspot1:1")
    expect("sold out toast",
           any("out of stock" in t.lower() for t in toasts()),
           f"toasts were {toasts()}")


async def scenario_custom_qty_and_coupon():
    reset()
    await press("pq:pgemin1")
    expect_in("qty prompt", "Custom", last_text(USER["id"]))

    reset()
    await send("2")
    text = last_text(USER["id"])
    expect_in("qty applied", "Qty: 2", text)
    expect_in("qty applied", "Total: 5.000 USD", text)

    store.coupon_save("SAVE10", kind="percent", value=10, max_uses=5)
    reset()
    await press("pc:pgemin1")
    expect_in("coupon prompt", "Apply coupon", last_text(USER["id"]))

    reset()
    await send("save10")
    expect_in("coupon applied", "Coupon SAVE10 applied",
              last_text(USER["id"]))

    reset()
    await send("NOPE-NOT-A-CODE")
    await press("pc:pgemin1")
    reset()
    await send("NOPE-NOT-A-CODE")
    expect("bad coupon rejected",
           any("does not exist" in t.lower() for t in
               sent_to(USER["id"]) + toasts()),
           f"got {sent_to(USER['id'])} {toasts()}")

    # buy with the coupon: 2 x 2.5 less 10% = 4.5
    store.coupon_save("SAVE10", kind="percent", value=10, max_uses=5)
    await press("pc:pgemin1")
    await send("SAVE10")
    store.credit(USER["id"], 10.0)
    before = store.balance_of(USER["id"])
    reset()
    await press("ok:pgemin1:2:SAVE10")
    expect_in("coupon purchase", "DELIVERED", last_text(USER["id"]))
    spent = before - store.balance_of(USER["id"])
    expect("coupon discount applied", abs(spent - 4.5) < 1e-6,
           f"spent {spent}, expected 4.5")


async def scenario_wallet_and_gift():
    reset()
    await send("/wallet")
    expect_in("wallet", "Balance", last_text(USER["id"]))

    # Add funds is method-first, then amount.
    reset()
    await press("w:top")
    text = last_text(USER["id"])
    expect_in("add funds step 1", "Top up", text)
    expect_in("methods listed", "Pay manually", text)
    expect("method buttons",
           any(c == "wm:manual" for c in callbacks(USER["id"])),
           f"got {callbacks(USER['id'])}")

    reset()
    await press("wm:manual")
    expect_in("add funds step 2", "Pay manually", last_text(USER["id"]))
    expect("amount presets",
           any(str(c).startswith("wm:manual:") for c in callbacks(USER["id"])),
           f"got {callbacks(USER['id'])}")

    reset()
    await press("wm:manual:5")
    expect_in("invoice created", "Payment created", last_text(USER["id"]))
    expect("invoice buttons",
           any(str(c).startswith("paid:") for c in callbacks(USER["id"])),
           f"got {callbacks(USER['id'])}")

    # a custom amount remembers which method it was opened for
    reset()
    await press("w:topc:manual")
    await send("7.5")
    expect_in("custom amount -> invoice", "Payment created",
              last_text(USER["id"]))
    pending = [t for t in store.topups_of(USER["id"], limit=5)
               if abs(float(t["amount"]) - 7.5) < 1e-6]
    expect("custom top-up recorded", len(pending) == 1, f"found {pending}")
    if pending:
        expect("custom top-up kept the method",
               pending[0]["method"] == "manual",
               f"method is {pending[0]['method']}")

    reset()
    await press("w:topc:manual")
    await send("0.001")
    expect("below minimum rejected",
           any("minimum" in t.lower() for t in sent_to(USER["id"])),
           f"got {sent_to(USER['id'])}")

    reset()
    await press("w:topc:manual")
    await send("999999")
    expect("above maximum rejected",
           any("maximum" in t.lower() for t in sent_to(USER["id"])),
           f"got {sent_to(USER['id'])}")

    store.giftcode_save("GIFT-FLOW1234", amount=2.5, max_uses=1)
    before = store.balance_of(USER["id"])
    reset()
    await send("/gift GIFT-FLOW1234")
    expect_in("gift redeemed", "2.500 USD credited", last_text(USER["id"]))
    expect("gift credited",
           abs(store.balance_of(USER["id"]) - (before + 2.5)) < 1e-6,
           f"balance went {before} -> {store.balance_of(USER['id'])}")
    expect("WALLET FUNDED posted",
           any("WALLET FUNDED" in t for t in sent_to(CHANNEL)),
           f"channel got {sent_to(CHANNEL)}")

    reset()
    await send("GIFT-FLOW1234")
    expect("gift reuse blocked",
           any("already used" in t.lower() for t in sent_to(USER["id"])),
           f"got {sent_to(USER['id'])}")

    # ── customer id + wallet transfer ─────────────────────────
    code = store.customer_id(USER["id"])
    expect("customer id issued", code.startswith("#CX-") and len(code) == 10,
           f"got {code!r}")
    expect("customer id is stable", store.customer_id(USER["id"]) == code,
           "id changed between calls")

    store.user_upsert({"id": 777000111, "first_name": "Buyer",
                       "username": "buyer"})
    other = store.customer_id(777000111)
    expect("ids are unique", other != code, f"both {code}")

    store.credit(USER["id"], 5.0)
    before_me = store.balance_of(USER["id"])
    reset()
    await press("w:tr")
    expect_in("transfer prompt", "Customer ID", last_text(USER["id"]))
    await send(f"{other} 2")
    expect("sender debited",
           abs(store.balance_of(USER["id"]) - (before_me - 2)) < 1e-6,
           f"balance went {before_me} -> {store.balance_of(USER['id'])}")
    expect("recipient credited",
           abs(store.balance_of(777000111) - 2.0) < 1e-6,
           f"recipient has {store.balance_of(777000111)}")
    expect("recipient notified",
           any("arrived" in t.lower() for t in sent_to(777000111)),
           f"recipient got {sent_to(777000111)}")

    reset()
    await press("w:tr")
    await send(f"{code} 1")
    expect("cannot transfer to self",
           any("your own" in t.lower() for t in
               sent_to(USER["id"]) + toasts()),
           f"got {sent_to(USER['id'])} {toasts()}")

    reset()
    await press("w:tr")
    await send(f"{other} 99999")
    expect("overdraft blocked",
           any("not enough" in t.lower() for t in
               sent_to(USER["id"]) + toasts()),
           f"got {sent_to(USER['id'])} {toasts()}")
    expect("overdraft left balances alone",
           abs(store.balance_of(777000111) - 2.0) < 1e-6,
           f"recipient now has {store.balance_of(777000111)}")

    reset()
    await press("w:tr")
    await send("#CX-000000 1")
    expect("unknown customer id rejected",
           any("no user" in t.lower() for t in
               sent_to(USER["id"]) + toasts()),
           f"got {sent_to(USER['id'])} {toasts()}")


async def scenario_account_screens():
    for command, needle in (
        ("/orders", "Orders"),
        ("/profile", "Profile"),
        ("/support", "Support"),
        ("/help", "How this bot works"),
        ("/terms", "Terms"),
        ("/language", "Language"),
        ("/id", str(USER["id"])),
        ("/nonsense", "How this bot works"),
    ):
        reset()
        await send(command)
        expect_in(f"command {command}", needle, last_text(USER["id"]))

    reset()
    await press("lang:ru")
    expect("language switched", store.user_lang(USER["id"]) == "ru",
           f"lang is {store.user_lang(USER['id'])}")
    expect_in("russian start", "Привет", last_text(USER["id"]))

    # the persistent keyboard must still work in the new language
    reset()
    await send("🎁 Товары")
    expect_in("russian keyboard route", "Категории", last_text(USER["id"]))

    await press("lang:en")

    reset()
    await press("nav:orders")
    expect_in("orders list", "purchase", last_text(USER["id"]))
    orders = store.orders_of(USER["id"], limit=1)
    if orders:
        reset()
        await press(f"ord:{orders[0]['id']}")
        expect_in("order detail", "Status", last_text(USER["id"]))
        reset()
        await press(f"ordr:{orders[0]['id']}")
        expect_in("order resend", "DELIVERED", last_text(USER["id"]))


async def scenario_alerts():
    reset()
    await press("pa:pspot1")
    expect("alerts toggled off",
           not store.alerts_enabled(USER["id"], "pspot1"),
           "alerts should be off")
    expect("alerts toast", any("off" in t.lower() for t in toasts()),
           f"toasts {toasts()}")

    reset()
    await press("pa:pspot1")
    expect("alerts toggled on", store.alerts_enabled(USER["id"], "pspot1"),
           "alerts should be back on")


async def scenario_inventory_list():
    """/inventorylist attaches every stock line, i.e. every live credential.
    The admin check is the only thing standing between that file and a
    customer, so it is worth a test of its own."""
    pid = "pspot1"
    store.stock_add(pid, ["https://t.me/+SecretInviteXYZ",
                          "canary@example.com | canary-pass"])

    def documents(chat_id) -> list:
        return [payload for method, payload in CALLS
                if method == "sendDocument"
                and payload.get("chat_id") == chat_id]

    # A customer must get nothing.
    reset()
    await send("/inventorylist")
    expect("customer gets no inventory file", not documents(USER["id"]),
           "a stock dump was sent to a non-admin")
    expect("customer sees no stock line",
           "SecretInviteXYZ" not in last_text(USER["id"]),
           f"leaked: {last_text(USER['id'])[:200]}")

    # An admin gets the file, with the link stored verbatim.
    reset()
    await send("/inventorylist", ADMIN)
    docs = documents(ADMIN["id"])
    expect("admin gets the inventory file", bool(docs), "no document sent")
    caption = (docs[0].get("caption") or "") if docs else ""
    expect_in("caption counts the lines", "Deliverable lines", caption)
    expect("caption warns about forwarding", "forward" in caption.lower(),
           f"caption: {caption[:160]}")


async def scenario_force_join_two_chats():
    """Both chats must be listed, and joining only one must not open the
    gate — the earlier single-channel code would have let that through."""
    joined = {"-100111": False, "-100222": False}

    async def fake_is_member(chat_id, user_id):
        return joined.get(str(chat_id), False)

    real_is_member = tg.is_member
    real_chats = config.FORCE_JOIN_CHATS
    tg.is_member = fake_is_member
    config.FORCE_JOIN_CHATS = [
        {"id": -100111, "link": "https://t.me/first", "name": "First Group"},
        {"id": -100222, "link": "https://t.me/+priv", "name": "Second Group"},
    ]
    store.set_setting("force_join", True)
    try:
        reset()
        await send("/products")
        text = last_text(USER["id"])
        expect_in("names the first chat", "First Group", text)
        expect_in("names the second chat", "Second Group", text)
        expect("gate blocks the catalog", "Categories" not in text,
               f"catalog leaked: {text[:160]}")

        # Joined one of two: still gated, and only the missing one is offered.
        joined["-100111"] = True
        reset()
        await send("/products")
        text = last_text(USER["id"])
        expect("still gated after joining one", "Second Group" in text,
               f"got: {text[:200]}")
        expect("stops offering the joined chat", "First Group" not in text,
               f"still asking for the joined chat: {text[:200]}")

        # Both joined: through.
        joined["-100222"] = True
        reset()
        await send("/products")
        expect_in("through once both joined", "Categories",
                  last_text(USER["id"]))
    finally:
        tg.is_member = real_is_member
        config.FORCE_JOIN_CHATS = real_chats
        store.set_setting("force_join", False)


async def scenario_admin():
    reset()
    await send("/admin", ADMIN)
    text = last_text(ADMIN["id"])
    expect_in("admin panel", "admin", text)
    expect_in("admin panel stats", "Users", text)
    expect("admin buttons", "ad:cat" in callbacks(ADMIN["id"]),
           f"got {callbacks(ADMIN['id'])}")

    # a non-admin must be refused
    reset()
    await send("/admin")
    expect("non-admin refused",
           "admin" not in last_text(USER["id"]).lower()
           or "Users" not in last_text(USER["id"]),
           f"leaked the panel: {last_text(USER['id'])[:200]}")

    reset()
    await press("ad:cat", ADMIN)
    expect_in("admin categories", "Categories", last_text(ADMIN["id"]))

    # add a category, then a product, then stock
    reset()
    await press("ad:cat:add", ADMIN)
    await send("Test Category | key", ADMIN)
    cats = [c for c in store.category_list(include_hidden=True)
            if c["name"] == "Test Category"]
    expect("category created", len(cats) == 1, f"found {len(cats)}")
    if not cats:
        return
    cat_id = cats[0]["id"]

    reset()
    await press(f"ad:prod:add:{cat_id}", ADMIN)
    await send("Test Product | 2.25 | A test description", ADMIN)
    made = store.products_in(cat_id, include_hidden=True)
    expect("product created", len(made) == 1, f"found {len(made)}")
    if not made:
        return
    pid = made[0]["id"]
    expect("product price", abs(float(made[0]["price"]) - 2.25) < 1e-6,
           f"price is {made[0]['price']}")

    reset()
    await press(f"ad:stock:a:{pid}", ADMIN)
    await send("line-one\nline-two\nline-three", ADMIN)
    expect("stock added", store.stock_count(pid) == 3,
           f"stock is {store.stock_count(pid)}")
    expect("restock announced",
           any("Stock Alert" in t for t in sent_to(CHANNEL)),
           f"channel got {sent_to(CHANNEL)[-3:]}")
    expect("restock reports totals",
           any("New stock added: +3" in t and "Total available: 3" in t
               for t in sent_to(CHANNEL)),
           f"channel got {sent_to(CHANNEL)[-1:]}")

    # bulk / volume pricing
    reset()
    await press(f"ad:prod:f:bulk:{pid}", ADMIN)
    await send("5 | 0.25\n10 | 0.50", ADMIN)
    tiers = store.bulk_tiers(store.product_get(pid))
    expect("bulk tiers saved", len(tiers) == 2, f"got {tiers}")
    list_price = float(store.product_get(pid)["price"])
    priced = store.quote(pid, 5)
    want = round((list_price - 0.25) * 5, 6)
    expect("bulk price applied", abs(priced["total"] - want) < 1e-6,
           f"x5 total is {priced['total']}, expected {want}")
    expect("bulk saving reported",
           abs(priced["bulk_saved"] - 1.25) < 1e-6,
           f"saved {priced['bulk_saved']}, expected 1.25")
    plain = store.quote(pid, 4)
    expect("below tier pays list price",
           abs(plain["total"] - list_price * 4) < 1e-6,
           f"x4 total is {plain['total']}, expected {list_price * 4}")
    deep = store.quote(pid, 10)
    want10 = round((list_price - 0.50) * 10, 6)
    expect("second tier applied", abs(deep["total"] - want10) < 1e-6,
           f"x10 total is {deep['total']}, expected {want10}")
    presets = store.qty_presets(store.product_get(pid), 99)
    expect("tier thresholds offered", 5 in presets and 10 in presets,
           f"presets are {presets}")

    reset()
    await press(f"p:{pid}", ADMIN)
    text = last_text(ADMIN["id"])
    expect_in("bulk shown on product", "Bulk rate", text)
    expect_in("bulk tier line", "x5+", text)

    # a price drop announces itself
    reset()
    await press(f"ad:prod:f:price:{pid}", ADMIN)
    await send("2.00", ADMIN)
    expect("price drop announced",
           any("Price update" in t for t in sent_to(CHANNEL)),
           f"channel got {sent_to(CHANNEL)[-2:]}")
    reset()
    await press(f"ad:prod:f:price:{pid}", ADMIN)
    await send("9.99", ADMIN)
    expect("price rise stays quiet",
           not any("Price update" in t for t in sent_to(CHANNEL)),
           f"channel got {sent_to(CHANNEL)}")

    # edit the price through the field prompt
    reset()
    await press(f"ad:prod:f:price:{pid}", ADMIN)
    await send("3.5", ADMIN)
    expect("price edited",
           abs(float(store.product_get(pid)["price"]) - 3.5) < 1e-6,
           f"price is {store.product_get(pid)['price']}")

    # gift code creation
    reset()
    await press("ad:gift:add", ADMIN)
    await send("4 | 2 | GIFT-ADMINMADE", ADMIN)
    record = store.giftcodes.get("GIFT-ADMINMADE")
    expect("gift code created", record is not None, "not found")
    if record:
        expect("gift amount", abs(float(record["amount"]) - 4.0) < 1e-6,
               f"amount is {record['amount']}")

    # credit a user
    reset()
    before = store.balance_of(USER["id"])
    await press(f"ad:user:c:{USER['id']}", ADMIN)
    await send("1.25", ADMIN)
    expect("admin credit",
           abs(store.balance_of(USER["id"]) - (before + 1.25)) < 1e-6,
           f"balance went {before} -> {store.balance_of(USER['id'])}")

    # ban and unban
    reset()
    await press(f"ad:user:b:{USER['id']}", ADMIN)
    await send("testing", ADMIN)
    banned, reason = store.is_banned(USER["id"])
    expect("user banned", banned and reason == "testing",
           f"banned={banned} reason={reason!r}")

    reset()
    await send("/start")
    expect_in("banned user blocked", "blocked", last_text(USER["id"]))

    await press(f"ad:user:b:{USER['id']}", ADMIN)
    expect("user unbanned", not store.is_banned(USER["id"])[0],
           "still banned")

    # settings
    reset()
    await press("ad:set:f:store_name", ADMIN)
    await send("Renamed Store", ADMIN)
    expect("setting saved", store.store_name() == "Renamed Store",
           f"store name is {store.store_name()!r}")
    store.set_setting("store_name", "ToolBox Store Bot")

    # delete the test category and its product
    reset()
    await press(f"ad:cat:d:{cat_id}", ADMIN)
    expect("category deleted", store.categories.get(cat_id) is None,
           "still there")
    expect("product cascade deleted", store.product_get(pid) is None,
           "product survived its category")


async def scenario_photo_message_edit():
    """A screen reached from a poster message must still render."""
    reset()
    await press("nav:products", photo=True)
    methods = [m for m, _p in CALLS]
    expect("photo message handled",
           any(m in ("editMessageMedia", "editMessageCaption",
                     "sendMessage", "sendPhoto", "deleteMessage")
               for m in methods),
           f"methods were {methods}")
    expect("no crash", not any(m == "__error__" for m in methods))


async def main() -> int:
    tg.api = fake_api
    store.init()

    scenarios = [
        ("browse and buy", scenario_browse_and_buy),
        ("custom qty and coupon", scenario_custom_qty_and_coupon),
        ("wallet and gift codes", scenario_wallet_and_gift),
        ("account screens", scenario_account_screens),
        ("stock alerts", scenario_alerts),
        ("admin panel", scenario_admin),
        ("inventory list", scenario_inventory_list),
        ("force join two chats", scenario_force_join_two_chats),
        ("poster message edit", scenario_photo_message_edit),
    ]

    for name, runner in scenarios:
        before = len(FAILURES)
        try:
            await runner()
        except Exception as exc:                 # noqa: BLE001
            import traceback
            traceback.print_exc()
            fail(name, f"raised {type(exc).__name__}: {exc}")
        broke = len(FAILURES) - before
        marker = f"FAIL x{broke}" if broke else "ok"
        print(f"  [{marker:>7}] {name}")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for problem in FAILURES:
            print(f"  - {problem}")
        return 1
    print("all flows passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
