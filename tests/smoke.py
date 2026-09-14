"""
tests/smoke.py — render every screen without touching Telegram.

    python -m tests.smoke

Builds each View against a temporary data dir seeded with the demo catalog and
checks the things that actually break in production: caption/text limits,
entity offsets that line up with the text, and callback_data under 64 bytes.
Prints each screen so you can eyeball the layout.

Exit code is non-zero if any check fails.
"""

import os
import sys
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456:test-token-not-real")
os.environ.setdefault("ADMIN_IDS", "424242")
os.environ.setdefault("STORE_NAME", "ToolBox Store Bot")
os.environ.setdefault("SUPPORT_USERNAME", "your_support")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="storebot-smoke-"))

from app import broadcast, commands, screens, shop, store, util   # noqa: E402
from app.lang import LANGS, STRINGS, t                        # noqa: E402
from app.msg import u16                                       # noqa: E402
from app.tg import CAPTION_LIMIT, TEXT_LIMIT                  # noqa: E402
from app.view import View                                     # noqa: E402

FAILURES: list = []
CHECKED = 0


def fail(where: str, detail: str):
    FAILURES.append(f"{where}: {detail}")


def check_view(name: str, view, show: bool = False):
    global CHECKED
    CHECKED += 1

    length = u16(view.text)
    limit = CAPTION_LIMIT if view.poster else TEXT_LIMIT
    if length > limit:
        fail(name, f"{length} units exceeds the {limit} limit")

    # Entity offsets must land inside the text and not overlap the end.
    for entity in view.entities:
        end = entity["offset"] + entity["length"]
        if entity["offset"] < 0 or end > length:
            fail(name, f"entity {entity['type']} runs to {end} of {length}")
        if entity["length"] <= 0:
            fail(name, f"zero-length {entity['type']} entity")

    for row in (view.keyboard or {}).get("inline_keyboard", []):
        for button in row:
            data = button.get("callback_data")
            if data and len(data.encode("utf-8")) > 64:
                fail(name, f"callback_data too long: {data}")
            if not button.get("text"):
                fail(name, "button with empty text")
            if not data and not button.get("url") \
                    and "switch_inline_query_current_chat" not in button:
                fail(name, f"button {button.get('text')} does nothing")

    if show:
        print(f"\n{'=' * 68}\n{name}   "
              f"[{length} units, poster={bool(view.poster)}]\n{'=' * 68}")
        print(view.text)
        for row in (view.keyboard or {}).get("inline_keyboard", []):
            print("   [" + "] [".join(b["text"] for b in row) + "]")
        for row in (view.keyboard or {}).get("keyboard", []):
            print("   |" + "| |".join(b["text"] for b in row) + "|")


def main() -> int:
    store.init()
    verbose = "-q" not in sys.argv

    user = {"id": 512345604, "first_name": "Coder", "username": "coder"}
    store.user_upsert(user)
    store.credit(user["id"], 0.0)
    record = store.user_get(user["id"])

    product = store.product_get("pspot1")
    cat = store.categories.get("cspoti")

    # ── the storefront, in every language ─────────────────────
    for lang in LANGS:
        loud = verbose and lang == "en"
        check_view(f"start [{lang}]",
                   screens.start(user, lang, is_admin=True), loud)
        check_view(f"categories [{lang}]", screens.categories(lang), loud)
        check_view(f"category [{lang}]", screens.category(cat, lang), loud)
        check_view(f"product [{lang}]",
                   screens.product(product, lang, 0.0), loud)
        check_view(f"confirm [{lang}]",
                   screens.confirm(product, lang, 1, 0.0), loud)
        check_view(f"low_balance [{lang}]",
                   screens.low_balance(product, lang, 1, 0.0, 1.5), loud)
        check_view(f"pay_methods [{lang}]",
                   screens.pay_methods(product, lang, 1, 0.0, 1.5), loud)
        check_view(f"wallet [{lang}]", screens.wallet(record, lang), loud)
        check_view(f"topup_amounts [{lang}]",
                   screens.topup_amounts(lang, 0.0), loud)
        check_view(f"topup_methods [{lang}]",
                   screens.topup_methods(lang, 5.0), loud)
        check_view(f"orders [{lang}]",
                   screens.orders(user["id"], lang), loud)
        check_view(f"gift [{lang}]", screens.gift(lang, 0.0), loud)
        check_view(f"support [{lang}]", screens.support(lang), loud)
        check_view(f"profile [{lang}]", screens.profile(record, lang), loud)
        check_view(f"language [{lang}]", screens.language(lang), loud)
        check_view(f"help [{lang}]", screens.help_screen(lang, True), loud)
        check_view(f"terms [{lang}]", screens.terms(lang), loud)
        check_view(f"api [{lang}]", screens.api_screen(lang), loud)
        check_view(f"force_join [{lang}]", screens.force_join(lang), loud)
        check_view(f"banned [{lang}]", screens.banned(lang, "spam"), loud)
        check_view(f"delivery_note [{lang}]",
                   screens.delivery_note(product, lang), loud)
        check_view(f"history [{lang}]",
                   screens.wallet_history(user["id"], lang), loud)

    # ── buy something for real ────────────────────────────────
    store.credit(user["id"], 10.0)
    order, err = _run(shop.checkout(user["id"], "pspot1", 1))
    if err or not order:
        fail("checkout", f"failed with {err!r}")
    else:
        if order["status"] != "delivered":
            fail("checkout", f"status is {order['status']}, expected delivered")
        if not order["items"]:
            fail("checkout", "delivered with no payload")
        if abs(store.balance_of(user["id"]) - 8.5) > 1e-6:
            fail("checkout",
                 f"balance is {store.balance_of(user['id'])}, expected 8.5")
        if store.stock_count("pspot1") != 0:
            fail("checkout", "stock was not decremented")
        check_view("delivered", screens.delivered(order, "en", 8.5), verbose)
        check_view("order_detail",
                   screens.order_detail(order, "en"), verbose)
        check_view("orders (after buying)",
                   screens.orders(user["id"], "en"), verbose)

    # out of stock now
    _order2, err2 = _run(shop.checkout(user["id"], "pspot1", 1))
    if err2 != "err_no_stock":
        fail("stock guard", f"expected err_no_stock, got {err2!r}")

    # ── coupons and gift codes ────────────────────────────────
    store.coupon_save("SAVE10", kind="percent", value=10, max_uses=2)
    priced = shop.quote("pgemin1", 2, "SAVE10")
    if abs(priced["total"] - 4.5) > 1e-6:
        fail("coupon", f"2 x 2.5 less 10% should be 4.5, got {priced['total']}")

    store.giftcode_save("GIFT-TEST1234", amount=3.0, max_uses=1)
    amount, gift_err = store.giftcode_redeem("GIFT-TEST1234", user["id"])
    if gift_err or abs(amount - 3.0) > 1e-6:
        fail("giftcode", f"redeem returned {amount!r} {gift_err!r}")
    _again, again_err = store.giftcode_redeem("GIFT-TEST1234", user["id"])
    if again_err != "gift_already":
        fail("giftcode", f"reuse should fail, got {again_err!r}")

    # ── invoice screen ────────────────────────────────────────
    topup = store.topup_create(user_id=user["id"], amount=1.5,
                               method="binance")
    check_view("invoice", screens.invoice(topup, "en", "Binance Pay",
                                          "https://pay.example/abc"), verbose)

    # ── channel posts ─────────────────────────────────────────
    funded = {"user_id": 512345604, "amount": 3.5, "method": "binance"}
    for name, built in (
        ("post: WALLET FUNDED", broadcast.build_wallet_funded(funded)),
        ("post: NEW ORDER", broadcast.build_new_order({
            "pid": "pspot1", "product_name": "Chatgpt Plus No Warranty (MoMo)",
            "qty": 1, "total": 3.5, "user_id": 512345604})),
        ("post: ALMOST GONE", broadcast.build_almost_gone(
            {"id": "pcap1", "name": "Capcut Pro Team 1 Month 1200 Credits",
             "emoji": "star", "price": 1.6}, 2)),
        ("post: BACK IN STOCK", broadcast.build_restocked(product, 5)),
    ):
        text, entities = built
        check_view(name, View(text=text, entities=entities), verbose)

    # ── commands and strings ──────────────────────────────────
    listed = {name for name, _k, _e, _a in commands.COMMANDS}
    if "start" not in listed or "products" not in listed:
        fail("commands", "core commands missing from the registry")
    for name, desc_key, emoji_name, _admin in commands.COMMANDS:
        if desc_key not in commands.DESCRIPTIONS:
            fail("commands", f"/{name} has no description")
    for lang in LANGS:
        for entry in commands.public_commands(lang):
            if len(entry["description"]) > 256:
                fail("commands", f"description too long for {entry['command']}")

    missing = [key for key, value in STRINGS.items()
               if isinstance(value, dict) and "en" not in value]
    if missing:
        fail("lang", f"no English text for: {', '.join(missing)}")

    # ── formatting ────────────────────────────────────────────
    if util.fmt_money(1.5) != "1.500 USD":
        fail("util", f"fmt_money(1.5) = {util.fmt_money(1.5)}")
    if util.mask_user_id(512345604) != "51******04":
        fail("util", f"mask_user_id = {util.mask_user_id(512345604)}")
    if util.parse_amount("$1,50") != 1.5:
        fail("util", f"parse_amount('$1,50') = {util.parse_amount('$1,50')}")
    if t("missing_key_xyz", "en") != "missing_key_xyz":
        fail("lang", "unknown keys should echo back")

    # ── report ────────────────────────────────────────────────
    print(f"\n{'=' * 68}")
    print(f"checked {CHECKED} views")
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for problem in FAILURES:
            print(f"  - {problem}")
        return 1
    print("all checks passed")
    return 0


def _run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    sys.exit(main())
