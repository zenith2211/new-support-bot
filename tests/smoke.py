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

# Force the JSON backend onto the temp DATA_DIR above. With DATABASE_URL set,
# store.py ignores DATA_DIR entirely and the guard below would wave this suite
# straight through to the live database. Empty rather than deleted, so
# config.load_env_file() does not put it back from .env.
os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

# This suite buys products, credits wallets and creates codes. Pointed at a
# real DATA_DIR it would corrupt live users, orders and stock — so refuse
# unless the directory is obviously a throwaway.
_DATA_DIR = os.environ["DATA_DIR"]
if "storebot-smoke-" not in _DATA_DIR and not os.environ.get("ALLOW_LIVE_DATA"):
    sys.stderr.write(
        f"refusing to run against DATA_DIR={_DATA_DIR!r}\n"
        "This suite writes test orders and balances. Unset DATA_DIR to use a\n"
        "temp dir, or set ALLOW_LIVE_DATA=1 if you really mean it.\n")
    raise SystemExit(2)

from app import broadcast, commands, emoji as emo, screens, \
    shop, store, util                                         # noqa: E402
from app.lang import LANGS, STRINGS, t                        # noqa: E402
from app.msg import u16                                       # noqa: E402
from app.tg import CAPTION_LIMIT, TEXT_LIMIT                  # noqa: E402
from app.view import View                                     # noqa: E402

FAILURES: list = []
CHECKED = 0


def fail(where: str, detail: str):
    FAILURES.append(f"{where}: {detail}")


def _check_membership_errors():
    """tg.is_member must fail CLOSED on a user error, OPEN on a chat error.

    Telegram has no "not a member" status for someone it has never seen in
    the chat — it returns Bad Request instead. Reading every Bad Request as
    "cannot check, let them in" silently disables force join for exactly the
    people it is meant to stop: first-time customers.
    """
    from app import tg

    cases = [
        # (description from Telegram, expected is_member, why)
        ("Bad Request: PARTICIPANT_ID_INVALID", False, "unknown user"),
        ("Bad Request: USER_NOT_PARTICIPANT", False, "explicit non-member"),
        ("Bad Request: user not found", False, "no such user"),
        ("Bad Request: chat not found", True, "our config is wrong"),
        ("Bad Request: CHAT_ADMIN_REQUIRED", True, "bot is not an admin"),
        ("Forbidden: bot is not a member of the channel chat", True,
         "bot was removed"),
    ]

    original = tg.api
    try:
        for description, expected, why in cases:
            async def stub(_method, _params=None, _desc=description):
                return {"ok": False, "description": _desc}

            tg.api = stub
            got = _run(tg.is_member(-100123, 999))
            if got != expected:
                fail("force_join",
                     f"{description!r} ({why}) -> is_member={got}, "
                     f"want {expected}")

        # A clean answer still decides on status alone.
        for status, expected in (("member", True), ("creator", True),
                                 ("left", False), ("kicked", False)):
            async def stub(_method, _params=None, _status=status):
                return {"ok": True, "result": {"status": _status}}

            tg.api = stub
            got = _run(tg.is_member(-100123, 999))
            if got != expected:
                fail("force_join",
                     f"status {status!r} -> is_member={got}, want {expected}")
    finally:
        tg.api = original


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
        check_view(f"topup_methods [{lang}]",
                   screens.topup_methods(lang, 0.0), loud)
        check_view(f"topup_methods+amount [{lang}]",
                   screens.topup_methods(lang, 0.0, 5.0), loud)
        check_view(f"topup_amounts [{lang}]",
                   screens.topup_amounts(lang, 0.0, "binance"), loud)
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

    # ── posters stay off unless POSTERS=1 ─────────────────────
    # Nothing — not a stored file_id, not an env var, not a product image —
    # may put an image back while the master switch is off.
    from app import config as config_mod
    if not config_mod.POSTERS:
        store.set_setting("poster_BANNER_START", "SOME-STALE-FILE-ID")
        store.product_save("pspot1", image="ANOTHER-STALE-FILE-ID")
        try:
            leaked = [
                name for name, view in (
                    ("start", screens.start(user, "en")),
                    ("categories", screens.categories("en")),
                    ("category", screens.category(cat, "en")),
                    ("product", screens.product(
                        store.product_get("pspot1"), "en", 0.0)),
                    ("wallet", screens.wallet(record, "en")),
                    ("orders", screens.orders(user["id"], "en")),
                    ("gift", screens.gift("en", 0.0)),
                    ("support", screens.support("en")),
                    ("profile", screens.profile(record, "en")),
                )
                if view.poster
            ]
            if leaked:
                fail("posters", f"POSTERS is off but these carry an image: "
                                f"{', '.join(leaked)}")
            if store.poster("BANNER_START"):
                fail("posters", "store.poster() returned a stale file_id")
            if store.product_poster(store.product_get("pspot1")):
                fail("posters", "store.product_poster() ignored the switch")
        finally:
            store.settings.delete("poster_BANNER_START")
            store.product_save("pspot1", image="")

    # ── a mapped slot puts its emoji in the icon, not the label ──
    # With no emoji.json (as here, on a temp DATA_DIR) the prefix fallback is
    # correct, so this only asserts the rule for slots that *are* mapped.
    from app import view as view_mod
    kb = screens.main_reply_kb("en")
    cells = [b for row in kb["keyboard"] for b in row]
    if len(cells) != len(screens.MENU):
        fail("buttons", f"{len(cells)} menu buttons, expected "
                        f"{len(screens.MENU)}")
    for (_route, key, slot), button in zip(screens.MENU, cells):
        mapped = bool(emo.premium_id(slot))
        has_icon = "icon_custom_emoji_id" in button
        plain = any(ord(ch) > 0x2000 for ch in button["text"])
        if view_mod.SEND_BUTTON_ICONS and mapped:
            if not has_icon:
                fail("buttons", f"{slot} is mapped but carries no icon id")
            if plain:
                fail("buttons",
                     f"{slot} has both an icon and a plain emoji in "
                     f"{button['text']!r}")
        elif not plain:
            fail("buttons", f"{slot} has neither an icon nor a plain emoji")
    # routing must survive either label spelling
    routes = screens.reply_labels("en")
    for route, key, slot in screens.MENU:
        for variant in view_mod.reply_label_variants(t(key, "en"), slot):
            if routes.get(variant) != route:
                fail("buttons", f"label {variant!r} does not route to {route}")

    # ── emoji integrity ───────────────────────────────────────
    for slot, char_text in emo.EMOJI.items():
        if not char_text:
            fail("emoji", f"slot {slot} has no character")
        if slot != "dot" and not emo.slots_for_char(char_text):
            fail("emoji", f"slot {slot} char {char_text!r} matches nothing")
    # a slot must never map to a non-numeric id
    for slot, eid in emo.PREMIUM.items():
        if not str(eid).isdigit():
            fail("emoji", f"{slot} has a non-numeric id {eid!r}")
        if slot not in emo.EMOJI:
            fail("emoji", f"{slot} is mapped but is not a real slot")

    # ── formatting ────────────────────────────────────────────
    if util.fmt_money(1.5) != "1.500 USD":
        fail("util", f"fmt_money(1.5) = {util.fmt_money(1.5)}")
    if util.mask_user_id(512345604) != "51******04":
        fail("util", f"mask_user_id = {util.mask_user_id(512345604)}")
    if util.parse_amount("$1,50") != 1.5:
        fail("util", f"parse_amount('$1,50') = {util.parse_amount('$1,50')}")
    if t("missing_key_xyz", "en") != "missing_key_xyz":
        fail("lang", "unknown keys should echo back")

    # ── force join actually gates ─────────────────────────────
    # getChatMember says "no" by erroring, and an error about the USER is not
    # an error about the CHAT. Conflating them let every new customer into
    # the shop without joining anything, because Telegram has no participant
    # row for someone who has never been in the chat.
    _check_membership_errors()

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
