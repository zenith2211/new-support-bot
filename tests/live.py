"""
tests/live.py — guided live tour against the real Telegram API.

    BOT_TOKEN=... ADMIN_IDS=<your id> LIVE_CHAT=<your id> python -m tests.live

Feeds synthetic updates through the real router, so every screen you see in
Telegram was produced by the same handler code a real tap would run — and the
real Bot API validates every entity, keyboard and poster on the way.

LOG_CHANNEL_ID is pointed at your own chat during the tour, so the channel
posts (WALLET FUNDED / NEW ORDER / ALMOST GONE) are visible too.

Every API call is recorded; anything the API rejects is listed at the end.
"""

import asyncio
import os
import sys

from app import broadcast, config, shop, store, tg, util
from app.handlers import router
from app.msg import Msg

CHAT = int(os.environ.get("LIVE_CHAT") or os.environ.get("ADMIN_IDS", "0")
           .split(",")[0])
PAUSE = float(os.environ.get("LIVE_PAUSE", "1.35"))   # same-chat rate limit

USER = {"id": CHAT, "first_name": "Coder", "username": "Pagalworld_developer",
        "language_code": "en"}

_real_api = tg.api
CALLS: list = []
REJECTED: list = []
_update_id = 900000
STEPS: list = []


async def recording_api(method: str, payload: dict | None = None,
                        files: dict | None = None,
                        quiet: bool = False) -> dict:
    data = await _real_api(method, payload, files, quiet)
    CALLS.append(method)
    if not data.get("ok"):
        description = str(data.get("description", ""))
        if "not modified" not in description:
            REJECTED.append((method, description))
    return data


def _next_update_id() -> int:
    global _update_id
    _update_id += 1
    return _update_id


async def banner(number: int, label: str, detail: str = ""):
    m = Msg()
    m.rule()
    m.bold(f"TEST {number:02d} — {label}").nl()
    if detail:
        m.italic(detail).nl()
    m.rule()
    text, entities = m.build()
    await tg.send_message(CHAT, text, entities)
    STEPS.append(f"{number:02d} {label}")
    await asyncio.sleep(PAUSE)


async def send_text(text: str):
    """A message update, exactly as Telegram would deliver it."""
    await router.handle_update({
        "update_id": _next_update_id(),
        "message": {
            "message_id": _next_update_id(),
            "from": USER,
            "chat": {"id": CHAT, "type": "private"},
            "text": text,
        },
    })
    await asyncio.sleep(PAUSE)


async def tap(data: str):
    """A button press. A real placeholder message is sent first so the
    handler's in-place edit lands on a real message in the chat."""
    sent = await tg.send_message(CHAT, "…")
    if not sent.get("ok"):
        REJECTED.append(("placeholder", str(sent.get("description"))))
        return
    message = sent["result"]
    await asyncio.sleep(0.4)

    await router.handle_update({
        "update_id": _next_update_id(),
        # no "id": answerCallbackQuery is skipped, since a synthetic query id
        # would be rejected by Telegram.
        "callback_query": {
            "from": USER,
            "message": {
                "message_id": message["message_id"],
                "chat": {"id": CHAT, "type": "private"},
                "text": "…",
            },
            "data": data,
        },
    })
    await asyncio.sleep(PAUSE)


# ─── THE TOUR ─────────────────────────────────────────────────
async def tour():
    await banner(1, "START SCREEN", "greeting, menu, full command list")
    await send_text("/start")

    await banner(2, "PRODUCTS", "categories with live stock counts")
    await tap("nav:products")

    await banner(3, "ONE CATEGORY", "price and stock per product")
    await tap("cat:cspoti")

    await banner(4, "PRODUCT DETAIL", "price, stock, sold, SKU, delivery, qty")
    await tap("p:pspot1")

    await banner(5, "CUSTOM QUANTITY", "prompt, then a typed quantity")
    await tap("pq:pgemin1")
    await send_text("2")

    await banner(6, "COUPON", "SAVE20 applied to the product screen")
    store.coupon_save("SAVE20", kind="percent", value=20, max_uses=50)
    await tap("pc:pgemin1")
    await send_text("SAVE20")

    await banner(7, "LOW BALANCE", "confirming with an empty wallet")
    await tap("ok:pspot1:1")

    await banner(8, "PAY AND GET ITEM",
                 "no gateway configured yet, so it says so")
    await tap("pay:pspot1:1")

    await banner(9, "GIFT CODE -> WALLET FUNDED",
                 "real credit, plus the channel post")
    code = util.gen_code("GIFT-", 8)
    store.giftcode_save(code, amount=10.0, max_uses=1)
    await send_text(f"/gift {code}")

    await banner(10, "PURCHASE -> DELIVERED",
                 "real order, stock decrement and delivery")
    await tap("ok:pspot1:1")

    await banner(11, "SOLD OUT GUARD", "the same product cannot be bought twice")
    await tap("buy:pspot1:1")

    await banner(12, "WALLET", "balance, totals, top-up presets, history")
    await tap("nav:wallet")
    await tap("w:top")
    await tap("w:hist")

    await banner(13, "ORDERS", "list, then one order with its credentials")
    await tap("nav:orders")
    orders = store.orders_of(CHAT, limit=1)
    if orders:
        await tap(f"ord:{orders[0]['id']}")

    await banner(14, "ACCOUNT", "profile, support, help, terms, catalog API")
    await tap("nav:profile")
    await tap("nav:support")
    await tap("nav:help")
    await tap("nav:terms")
    await tap("nav:api")

    await banner(15, "LANGUAGE", "switch to Russian, then back to English")
    await tap("nav:language")
    await tap("lang:ru")
    await tap("lang:en")

    await banner(16, "STOCK ALERTS", "Stop Alerts, then Get Alerts")
    await tap("pa:pgemin1")
    await tap("pa:pgemin1")

    await banner(17, "ADMIN PANEL", "live stats and every section")
    await send_text("/admin")
    for section in ("ad:cat", "ad:prod", "ad:stock", "ad:gift", "ad:coup",
                    "ad:top", "ad:user", "ad:bc", "ad:set"):
        await tap(section)

    await banner(18, "ADMIN: BUILD A PRODUCT",
                 "add category, add product, add stock")
    await tap("ad:cat:add")
    await send_text("Live Test Category | key")
    made = [c for c in store.category_list(include_hidden=True)
            if c["name"] == "Live Test Category"]
    if made:
        cat_id = made[0]["id"]
        await tap(f"ad:prod:add:{cat_id}")
        await send_text("Live Test Product | 2.500 | Created during the live "
                        "test. Delivered instantly from stock.")
        products = store.products_in(cat_id, include_hidden=True)
        if products:
            pid = products[0]["id"]
            await tap(f"ad:stock:a:{pid}")
            await send_text("live-test-account-1 | password-1\n"
                            "live-test-account-2 | password-2")

            await banner(19, "BUY THE NEW PRODUCT",
                         "confirm and deliver what we just created")
            await tap(f"buy:{pid}:1")
            await tap(f"ok:{pid}:1")

            await banner(20, "ALMOST GONE",
                         "low stock post fires at the threshold")
            await shop.check_low_stock(pid)
            await asyncio.sleep(PAUSE)

            await banner(21, "ADMIN CLEANUP", "delete the test category")
            await tap(f"ad:cat:d:{cat_id}")

    await banner(22, "RESTOCK -> BACK IN STOCK",
                 "channel post plus a DM to subscribers")
    store.stock_add("pspot1", ["restocked-demo@example.com | pass | link"])
    store.product_save("pspot1", gone_posted=False)
    product = store.product_get("pspot1")
    await broadcast.restocked(product, 1)
    await asyncio.sleep(PAUSE)
    await broadcast.alert_restock_subscribers(product, 1)
    await asyncio.sleep(PAUSE)

    await banner(23, "BAN GATE", "a banned account is refused, then restored")
    store.set_banned(CHAT, True, "live test — restored immediately")
    await send_text("/start")
    store.set_banned(CHAT, False)
    await send_text("/start")


async def main() -> int:
    if not CHAT:
        print("set LIVE_CHAT to your telegram id")
        return 1

    tg.api = recording_api
    store.init()
    # Route channel posts to your own chat so they are visible in the tour.
    config.LOG_CHANNEL_ID = CHAT

    print(f"driving the bot into chat {CHAT} (pause {PAUSE}s)")
    await tour()

    m = Msg()
    m.rule()
    m.bold("LIVE TEST COMPLETE").nl()
    m.rule()
    m.text(f"Screens driven: {len(STEPS)}\n")
    m.text(f"API calls: {len(CALLS)}\n")
    m.text(f"Rejected: {len(REJECTED)}\n\n")
    m.kv("money", "Wallet now", util.fmt_money(store.balance_of(CHAT)))
    text, entities = m.build()
    await tg.send_message(CHAT, text, entities)

    await tg.close_session()

    print(f"\nsteps: {len(STEPS)}   api calls: {len(CALLS)}")
    if REJECTED:
        print(f"\nREJECTED BY TELEGRAM ({len(REJECTED)}):")
        for method, description in REJECTED:
            print(f"  - {method}: {description}")
        return 1
    print("every API call was accepted")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
