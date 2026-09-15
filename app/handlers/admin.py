"""
app/handlers/admin.py — the admin panel.

Design note: most actions are prompt-driven — tap a button, the bot shows the
expected syntax, you send one message. That keeps the whole catalog editable
from a phone without a maze of sub-menus, and keeps this module small enough
to read.
"""

import asyncio
import logging

from .. import broadcast, config, emoji as emo, payments, screens, \
    store, tg, util
from ..lang import t
from ..msg import Msg
from ..view import View, btn, kb
from .base import Ctx, send_new, show, toast
from . import pay_flow

logger = logging.getLogger(__name__)

BROADCAST_DELAY = 0.06


def _guard(ctx: Ctx) -> bool:
    return ctx.is_admin


def _parse_bulk(raw: str) -> list:
    """'5 | 0.15' per line -> [{"qty": 5, "off": 0.15}]"""
    if raw.strip() == "-":
        return []
    tiers = []
    for line in raw.splitlines():
        chunks = [c.strip() for c in line.replace("|", " ").split()]
        if len(chunks) < 2:
            continue
        qty = util.parse_qty(chunks[0])
        off = util.parse_amount(chunks[1])
        if qty and qty > 1 and off and off > 0:
            tiers.append({"qty": qty, "off": off})
    tiers.sort(key=lambda entry: entry["qty"])
    return tiers


def _panel_view() -> View:
    s = store.stats()
    m = Msg()
    m.header("admin", f"{store.store_name()} — admin")
    m.kvline("user", "Users", f"{s['users']} (+{s['users_today']} today)")
    m.kvline("category", "Categories", s["categories"])
    m.kvline("box", "Products", s["products"])
    m.kvline("stock", "Stock units", s["stock_units"])
    m.kvline("orders", "Orders", f"{s['orders']} (+{s['orders_today']} today)")
    m.kvline("money", "Revenue", util.fmt_money(s["revenue"]))
    m.kvline("card", "In wallets", util.fmt_money(s["wallets"]))
    m.kvline("clock", "Pending top-ups", s["pending_topups"])
    m.nl()
    m.emoji("bank").space().bold("Gateway: ")
    m.text(payments.methods_summary()).nl()
    m.emoji("broadcast").space().bold("Log channel: ")
    m.text(str(config.LOG_CHANNEL_ID or "not set")).nl()

    return View.of(m, kb(
        [btn("Categories", "ad:cat", emoji_name="category"),
         btn("Products", "ad:prod", emoji_name="box")],
        [btn("Stock", "ad:stock", emoji_name="stock"),
         btn("Gift codes", "ad:gift", emoji_name="gift")],
        [btn("Coupons", "ad:coup", emoji_name="coupon"),
         btn("Top-ups", "ad:top", emoji_name="card")],
        [btn("Users", "ad:user", emoji_name="user"),
         btn("Broadcast", "ad:bc", emoji_name="broadcast")],
        [btn("Settings", "ad:set", emoji_name="edit"),
         btn("Emoji", "ad:emoji", emoji_name="star")],
        [btn("Refresh", "ad:home", emoji_name="refresh")],
        [btn("Close", "nav:close", emoji_name="close", style="danger")],
    ))


async def panel(ctx: Ctx):
    if not _guard(ctx):
        await toast(ctx, t("err_admin_only", ctx.lang), alert=True)
        return
    await toast(ctx)
    await show(ctx, _panel_view())


def _back_row() -> list:
    return [btn("Admin", "ad:home", emoji_name="back")]


async def _prompt(ctx: Ctx, mode: str, title: str, syntax: str,
                  cancel_to: str = "ad:home", **data):
    from .. import state
    state.set_prompt(ctx.user_id, mode, **data)
    m = Msg()
    m.header("edit", title)
    m.text("Send one message:").nl()
    m.pre(syntax).nl()
    text, entities = m.build()
    await show(ctx, View(text=text, entities=entities, keyboard=kb(
        [btn("Cancel", cancel_to, emoji_name="no")],
    )))


# ─── CATEGORIES ───────────────────────────────────────────────
async def categories(ctx: Ctx):
    cats = store.category_list(include_hidden=True)
    m = Msg()
    m.header("category", "Categories")
    if not cats:
        m.italic("None yet.")
    for cat in cats:
        count = len(store.products_in(cat["id"], include_hidden=True))
        m.emoji(cat.get("emoji") or "box").space()
        m.bold(cat.get("name") or "—")
        m.text(f" · {count} products · ").code(cat["id"])
        if not cat.get("enabled", True):
            m.text(" · hidden")
        m.nl()

    rows = [[btn("Add category", "ad:cat:add", emoji_name="plus",
                 style="success")]]
    for cat in cats:
        rows.append([
            btn(util.clip(cat.get("name") or "—", 22), f"ad:cat:o:{cat['id']}",
                emoji_name=cat.get("emoji") or "box"),
            btn("Hide" if cat.get("enabled", True) else "Show",
                f"ad:cat:t:{cat['id']}"),
            btn("Delete", f"ad:cat:d:{cat['id']}", style="danger"),
        ])
    rows.append(_back_row())
    await show(ctx, View.of(m, kb(*rows)))


async def category_open(ctx: Ctx, cat_id: str):
    cat = store.categories.get(cat_id)
    if not cat:
        await toast(ctx, "Gone", alert=True)
        await categories(ctx)
        return
    items = store.products_in(cat_id, include_hidden=True)
    m = Msg()
    m.header(cat.get("emoji") or "box", cat.get("name") or "—")
    m.emoji("sku").space().bold("id: ").code(cat_id).nl()
    m.kvline("box", "Products", len(items))
    m.nl()
    for product in items:
        m.emoji("dot").space().text(util.clip(product.get("name"), 40))
        m.text(f" · {util.fmt_money(product.get('price'))}")
        m.text(f" · {store.stock_display(product['id'])}").nl()

    rows = [
        [btn("Add product", f"ad:prod:add:{cat_id}", emoji_name="plus",
             style="success")],
        [btn("Rename", f"ad:cat:r:{cat_id}", emoji_name="edit"),
         btn("Set emoji", f"ad:cat:e:{cat_id}", emoji_name="star")],
    ]
    for product in items:
        rows.append([btn(util.clip(product.get("name"), 34),
                         f"ad:prod:o:{product['id']}",
                         emoji_name=product.get("emoji") or "box")])
    rows.append([btn("Categories", "ad:cat", emoji_name="back")])
    await show(ctx, View.of(m, kb(*rows)))


# ─── PRODUCTS ─────────────────────────────────────────────────
async def products(ctx: Ctx):
    cats = store.category_list(include_hidden=True)
    m = Msg()
    m.header("box", "Products")
    m.text("Pick a category to add or edit its products.").nl(2)
    m.kvline("box", "Total", store.product_count(include_hidden=True))
    rows = [[btn(f"{cat.get('name')} "
                 f"({len(store.products_in(cat['id'], include_hidden=True))})",
                 f"ad:cat:o:{cat['id']}",
                 emoji_name=cat.get("emoji") or "box")] for cat in cats]
    if not cats:
        rows.append([btn("Add category first", "ad:cat:add",
                         emoji_name="plus", style="success")])
    rows.append(_back_row())
    await show(ctx, View.of(m, kb(*rows)))


async def product_open(ctx: Ctx, pid: str):
    product = store.product_get(pid)
    if not product:
        await toast(ctx, "Gone", alert=True)
        await products(ctx)
        return

    m = Msg()
    m.header(product.get("emoji") or "box", product.get("name") or "—")
    m.emoji("sku").space().bold("id: ").code(pid).nl()
    m.kvline("money", "Price", util.fmt_money(product.get("price")))
    m.kvline("stock", "Stock", store.stock_display(pid))
    m.kvline("sold", "Sold", int(product.get("sold") or 0))
    m.kvline("sku", "SKU", product.get("sku") or "—")
    m.kvline("delivery", "Mode",
             f"{product.get('stock_mode')} · {product.get('delivery_mode')}",
             bold_value=False)
    m.kvline("qty", "Qty range",
             f"{product.get('min_qty')}–{product.get('max_qty')}",
             bold_value=False)
    tiers = store.bulk_tiers(product)
    m.kvline("chart", "Bulk rates",
             ", ".join(f"x{tier['qty']}+ −{util.fmt_amount(tier['off'])}"
                       for tier in tiers) if tiers else "none",
             bold_value=False)
    m.kvline("ok", "Visible", "yes" if product.get("enabled", True) else "no",
             bold_value=False)
    if product.get("description"):
        m.nl().italic(util.clip(product["description"], 300))

    await show(ctx, View.of(m, kb(
        [btn("Add stock", f"ad:stock:a:{pid}", emoji_name="plus",
             style="success"),
         btn("Clear stock", f"ad:stock:c:{pid}", emoji_name="trash")],
        [btn("Name", f"ad:prod:f:name:{pid}", emoji_name="edit"),
         btn("Price", f"ad:prod:f:price:{pid}", emoji_name="money")],
        [btn("Description", f"ad:prod:f:description:{pid}",
             emoji_name="note"),
         btn("Delivery note", f"ad:prod:f:delivery_note:{pid}",
             emoji_name="delivery")],
        [btn("Emoji", f"ad:prod:f:emoji:{pid}", emoji_name="star")],
        [btn("Qty range", f"ad:prod:f:qty:{pid}", emoji_name="qty"),
         btn("Bulk rates", f"ad:prod:f:bulk:{pid}", emoji_name="chart")],
        [btn("Stock mode", f"ad:prod:f:stock_mode:{pid}",
             emoji_name="stock")],
        [btn("Hide" if product.get("enabled", True) else "Show",
             f"ad:prod:t:{pid}"),
         btn("Delete", f"ad:prod:d:{pid}", style="danger")],
        [btn("Category", f"ad:cat:o:{product.get('cat_id')}",
             emoji_name="back")],
    )))


# ─── STOCK ────────────────────────────────────────────────────
async def stock_menu(ctx: Ctx):
    m = Msg()
    m.header("stock", "Stock")
    low = store.low_stock_products()
    everything = sorted(store.products.values(),
                        key=lambda p: str(p.get("name") or ""))
    if low:
        m.emoji("low").space().bold("Low stock").nl()
        for product, count in low:
            m.text(f"• {util.clip(product.get('name'), 36)} — {count}").nl()
        m.nl()
    m.italic("Pick a product to add or clear lines.")

    rows = [[btn(f"{util.clip(product.get('name'), 30)} · "
                 f"{store.stock_display(product['id'])}",
                 f"ad:prod:o:{product['id']}",
                 emoji_name=product.get("emoji") or "box")]
            for product in everything[:20]]
    rows.append(_back_row())
    await show(ctx, View.of(m, kb(*rows)))


# ─── GIFT CODES ───────────────────────────────────────────────
async def gift_menu(ctx: Ctx):
    codes = sorted(store.giftcodes.values(),
                   key=lambda c: int(c.get("created") or 0), reverse=True)
    m = Msg()
    m.header("gift", "Gift codes")
    if not codes:
        m.italic("None yet.")
    for record in codes[:15]:
        m.emoji("ok" if record.get("enabled", True) else "no").space()
        m.code(record["code"])
        m.text(f" · {util.fmt_money(record.get('amount'))}")
        m.text(f" · {record.get('uses', 0)}/{record.get('max_uses') or '∞'}")
        m.nl()

    rows = [[btn("New gift code", "ad:gift:add", emoji_name="plus",
                 style="success")]]
    for record in codes[:10]:
        rows.append([
            btn(record["code"], f"ad:gift:o:{record['code']}",
                emoji_name="gift"),
            btn("Delete", f"ad:gift:d:{record['code']}", style="danger"),
        ])
    rows.append(_back_row())
    await show(ctx, View.of(m, kb(*rows)))


async def gift_open(ctx: Ctx, code: str):
    record = store.giftcodes.get(code)
    if not record:
        await toast(ctx, "Gone", alert=True)
        await gift_menu(ctx)
        return
    link = await tg.bot_link()
    m = Msg()
    m.header("gift", code)
    m.kvline("money", "Amount", util.fmt_money(record.get("amount")))
    m.kvline("user", "Used", f"{record.get('uses', 0)}/"
                             f"{record.get('max_uses') or '∞'}")
    if link:
        m.nl().emoji("link").space().code(f"{link}?start=gift_{code}").nl()
        m.italic("Share that link — it redeems the code in one tap.")
    await show(ctx, View.of(m, kb(
        [btn("Delete", f"ad:gift:d:{code}", emoji_name="trash",
             style="danger")],
        [btn("Gift codes", "ad:gift", emoji_name="back")],
    )))


# ─── COUPONS ──────────────────────────────────────────────────
async def coupon_menu(ctx: Ctx):
    codes = sorted(store.coupons.values(),
                   key=lambda c: int(c.get("created") or 0), reverse=True)
    m = Msg()
    m.header("coupon", "Coupons")
    if not codes:
        m.italic("None yet.")
    for record in codes[:15]:
        value = (f"{util.fmt_amount(record.get('value'))}%"
                 if record.get("kind") == "percent"
                 else util.fmt_money(record.get("value")))
        m.emoji("ok" if record.get("enabled", True) else "no").space()
        m.code(record["code"]).text(f" · -{value}")
        m.text(f" · {record.get('uses', 0)}/{record.get('max_uses') or '∞'}")
        if record.get("scope_pid"):
            m.text(f" · {record['scope_pid']}")
        m.nl()

    rows = [[btn("New coupon", "ad:coup:add", emoji_name="plus",
                 style="success")]]
    for record in codes[:10]:
        rows.append([
            btn(record["code"], "noop", emoji_name="coupon"),
            btn("Delete", f"ad:coup:d:{record['code']}", style="danger"),
        ])
    rows.append(_back_row())
    await show(ctx, View.of(m, kb(*rows)))


# ─── TOP-UPS ──────────────────────────────────────────────────
async def topup_menu(ctx: Ctx):
    pending = sorted(store.topups_pending(),
                     key=lambda r: int(r.get("created") or 0), reverse=True)
    m = Msg()
    m.header("card", "Pending top-ups")
    if not pending:
        m.italic("Nothing waiting.")
    for record in pending[:10]:
        user_rec = store.user_get(record.get("user_id"))
        m.emoji("clock").space().bold(util.fmt_money(record.get("amount")))
        m.text(f" · {payments.label(record.get('method'))}")
        m.text(f" · {util.user_handle(user_rec)}")
        m.text(f" · {util.ago(record.get('created'))}").nl()
        m.code(record["id"]).nl()

    rows = []
    for record in pending[:8]:
        rows.append([
            btn(f"Credit {util.fmt_money_short(record.get('amount'))}",
                f"ad:top:ok:{record['id']}", emoji_name="ok",
                style="success"),
            btn("Decline", f"ad:top:no:{record['id']}", style="danger"),
        ])
    rows.append(_back_row())
    await show(ctx, View.of(m, kb(*rows)))


# ─── USERS ────────────────────────────────────────────────────
async def user_menu(ctx: Ctx):
    s = store.stats()
    m = Msg()
    m.header("user", "Users")
    m.kvline("user", "Total", s["users"])
    m.kvline("plus", "New today", s["users_today"])
    m.kvline("ban", "Banned", s["banned"])
    m.kvline("card", "In wallets", util.fmt_money(s["wallets"]))
    m.nl().italic("Look one up by id or @username.")
    await show(ctx, View.of(m, kb(
        [btn("Find user", "ad:user:find", emoji_name="search")],
        _back_row(),
    )))


async def user_open(ctx: Ctx, user_id: str):
    record = store.users.get(user_id)
    if not record:
        await toast(ctx, "No such user", alert=True)
        await user_menu(ctx)
        return
    m = Msg()
    m.header("user", util.display_name(record))
    m.emoji("id").space().bold("id: ").code(str(record.get("id"))).nl()
    if record.get("username"):
        m.kvline("link", "Username", f"@{record['username']}",
                 bold_value=False)
    m.kvline("money", "Balance", util.fmt_money(record.get("balance")))
    m.kvline("chart", "Spent", util.fmt_money(record.get("spent")))
    m.kvline("orders", "Orders", int(record.get("orders") or 0))
    m.kvline("clock", "Joined", util.fmt_day(record.get("joined")),
             bold_value=False)
    if record.get("banned"):
        m.kvline("ban", "Banned", record.get("ban_reason") or "—",
                 bold_value=False)

    uid = record.get("id")
    await show(ctx, View.of(m, kb(
        [btn("Credit / debit", f"ad:user:c:{uid}", emoji_name="money",
             style="success")],
        [btn("Unban" if record.get("banned") else "Ban",
             f"ad:user:b:{uid}", emoji_name="ban",
             style=None if record.get("banned") else "danger"),
         btn("Message", f"ad:user:m:{uid}", emoji_name="mail")],
        [btn("Users", "ad:user", emoji_name="back")],
    )))


# ─── BROADCAST ────────────────────────────────────────────────
async def broadcast_menu(ctx: Ctx):
    m = Msg()
    m.header("broadcast", "Broadcast")
    m.kvline("user", "Recipients", store.users.count())
    m.nl().italic("Sends your next message to every user who is not banned.")
    await show(ctx, View.of(m, kb(
        [btn("Write broadcast", "ad:bc:new", emoji_name="edit",
             style="success")],
        _back_row(),
    )))


async def run_broadcast(ctx: Ctx, text: str):
    audience = [
        record.get("id") for record in store.users.values()
        if record.get("id") and not record.get("banned")
    ]
    sent = failed = 0
    for user_id in audience:
        data = await tg.send_message(user_id, text)
        if data.get("ok"):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY)

    m = Msg()
    m.header("ok", "Broadcast done")
    m.kvline("ok", "Delivered", sent)
    m.kvline("no", "Failed", failed)
    await send_new(ctx, View.of(m, kb(_back_row())))


# ─── SETTINGS ─────────────────────────────────────────────────
SETTING_FIELDS = [
    ("store_name", "Store name"),
    ("support_username", "Support username"),
    ("channel_link", "Channel link"),
    ("min_topup", "Min top-up"),
    ("welcome_note", "Welcome note"),
    ("terms", "Terms text"),
    ("manual_pay_note", "Manual pay note"),
    ("api_note", "API note"),
]


async def settings_menu(ctx: Ctx):
    m = Msg()
    m.header("edit", "Settings")
    for key, label in SETTING_FIELDS:
        value = store.setting(key)
        shown = util.clip(str(value), 40) if value else "—"
        m.emoji("dot").space().bold(f"{label}: ").text(shown).nl()
    m.nl()
    m.emoji("bell").space().bold("Force join: ")
    m.text("on" if store.setting("force_join") else "off").nl()
    m.nl().italic("Env vars (token, gateway keys, channel ids) are not "
                  "editable here — set them in the host and redeploy.")

    rows = []
    for index in range(0, len(SETTING_FIELDS), 2):
        rows.append([
            btn(label, f"ad:set:f:{key}", emoji_name="edit")
            for key, label in SETTING_FIELDS[index:index + 2]
        ])
    rows.append([btn("Toggle force join", "ad:set:fj", emoji_name="bell")])
    rows.append(_back_row())
    await show(ctx, View.of(m, kb(*rows)))


# ─── CALLBACK ROUTER ──────────────────────────────────────────
async def handle_callback(ctx: Ctx, rest: str) -> bool:
    """rest = callback_data after the 'ad:' prefix."""
    if not _guard(ctx):
        await toast(ctx, t("err_admin_only", ctx.lang), alert=True)
        return True

    parts = rest.split(":")
    section = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    arg = ":".join(parts[2:]) if len(parts) > 2 else ""

    if section in ("", "home"):
        await panel(ctx)
        return True

    await toast(ctx)

    if section == "cat":
        if action == "":
            await categories(ctx)
        elif action == "add":
            await _prompt(ctx, "ad_cat_add", "New category",
                          "Name | emoji-slot (optional)\n\n"
                          "Example:\nSpotify Premium | star",
                          cancel_to="ad:cat")
        elif action == "o":
            await category_open(ctx, arg)
        elif action == "r":
            await _prompt(ctx, "ad_cat_name", "Rename category",
                          "New name", cancel_to=f"ad:cat:o:{arg}", cat_id=arg)
        elif action == "e":
            await _prompt(ctx, "ad_cat_emoji", "Category emoji",
                          f"One emoji slot name.\nAvailable: "
                          f"{', '.join(sorted(emo.EMOJI)[:24])} …",
                          cancel_to=f"ad:cat:o:{arg}", cat_id=arg)
        elif action == "t":
            cat = store.categories.get(arg)
            if cat:
                store.category_save(arg, enabled=not cat.get("enabled", True))
            await categories(ctx)
        elif action == "d":
            store.category_delete(arg, cascade=True)
            await categories(ctx)
        return True

    if section == "prod":
        if action == "":
            await products(ctx)
        elif action == "add":
            await _prompt(ctx, "ad_prod_add", "New product",
                          "Name | price | description (optional)\n\n"
                          "Example:\nSpotify 3 Months | 1.5 | Full access, "
                          "7 day warranty",
                          cancel_to=f"ad:cat:o:{arg}", cat_id=arg)
        elif action == "o":
            await product_open(ctx, arg)
        elif action == "f":
            field, pid = (parts[2], ":".join(parts[3:])) if len(parts) > 3 \
                else ("", "")
            await _product_field_prompt(ctx, field, pid)
        elif action == "t":
            product = store.product_get(arg)
            if product:
                store.product_save(arg,
                                   enabled=not product.get("enabled", True))
            await product_open(ctx, arg)
        elif action == "d":
            product = store.product_get(arg) or {}
            store.product_delete(arg)
            await category_open(ctx, product.get("cat_id", ""))
        return True

    if section == "stock":
        if action == "":
            await stock_menu(ctx)
        elif action == "a":
            await _prompt(ctx, "ad_stock_add", "Add stock",
                          "One item per line. Each line is delivered to one "
                          "buyer.\n\nExample:\n"
                          "mail@example.com | pass | note\n"
                          "mail2@example.com | pass2 | note",
                          cancel_to=f"ad:prod:o:{arg}", pid=arg)
        elif action == "c":
            store.stock_clear(arg)
            await product_open(ctx, arg)
        return True

    if section == "gift":
        if action == "":
            await gift_menu(ctx)
        elif action == "add":
            await _prompt(ctx, "ad_gift_add", "New gift code",
                          "amount | uses (optional) | code (optional)\n\n"
                          "Example:\n5 | 10\n"
                          "Leave code empty to generate one.",
                          cancel_to="ad:gift")
        elif action == "o":
            await gift_open(ctx, arg)
        elif action == "d":
            store.giftcodes.delete(arg)
            await gift_menu(ctx)
        return True

    if section == "coup":
        if action == "":
            await coupon_menu(ctx)
        elif action == "add":
            await _prompt(ctx, "ad_coup_add", "New coupon",
                          "code | percent|fixed | value | uses (optional) | "
                          "product id (optional)\n\n"
                          "Example:\nWELCOME10 | percent | 10 | 100",
                          cancel_to="ad:coup")
        elif action == "d":
            store.coupons.delete(util.normalize_code(arg))
            await coupon_menu(ctx)
        return True

    if section == "top":
        if action == "":
            await topup_menu(ctx)
        elif action in ("ok", "no"):
            await pay_flow.admin_approve(ctx, arg, action == "ok")
            await topup_menu(ctx)
        return True

    if section == "user":
        if action == "":
            await user_menu(ctx)
        elif action == "find":
            await _prompt(ctx, "ad_user_find", "Find user",
                          "Telegram id or @username", cancel_to="ad:user")
        elif action == "o":
            await user_open(ctx, arg)
        elif action == "c":
            await _prompt(ctx, "ad_user_credit", "Credit / debit",
                          "Amount. Negative takes money away.\n\n"
                          "Example:\n5\n-2.5",
                          cancel_to=f"ad:user:o:{arg}", target=arg)
        elif action == "b":
            record = store.users.get(arg) or {}
            if record.get("banned"):
                store.set_banned(arg, False)
                await user_open(ctx, arg)
            else:
                await _prompt(ctx, "ad_user_ban", "Ban user", "Reason",
                              cancel_to=f"ad:user:o:{arg}", target=arg)
        elif action == "m":
            await _prompt(ctx, "ad_user_msg", "Message user",
                          "The text to send", cancel_to=f"ad:user:o:{arg}",
                          target=arg)
        return True

    if section == "bc":
        if action == "":
            await broadcast_menu(ctx)
        elif action == "new":
            await _prompt(ctx, "ad_bc", "Broadcast",
                          "The message to send to every user",
                          cancel_to="ad:bc")
        return True

    if section == "set":
        if action == "":
            await settings_menu(ctx)
        elif action == "f":
            key = arg
            label = dict(SETTING_FIELDS).get(key, key)
            await _prompt(ctx, "ad_set", f"Set {label}",
                          "The new value. Send - to clear it.",
                          cancel_to="ad:set", key=key)
        elif action == "fj":
            store.set_setting("force_join", not store.setting("force_join"))
            await settings_menu(ctx)
        return True

    if section == "emoji":
        await emoji_status(ctx)
        return True

    if section == "ord" and action == "done":
        order = store.order_get(arg)
        if order:
            store.orders.patch(arg, status="delivered",
                               delivered=util.now_ts())
            lang = store.user_lang(order.get("user_id"))
            await broadcast.dm(
                order["user_id"],
                lambda m: m.header("ok", t("delivered_title", lang))
                .text(t("delivered_keep", lang)),
            )
            await toast(ctx, "Marked delivered")
        return True

    return False


# ─── EMOJI STATUS ─────────────────────────────────────────────
async def emoji_status(ctx: Ctx):
    """What is mapped, whether it animates, and a live sample to look at."""
    report = await emo.audit(tg)
    missing = [slot for slot in emo.EMOJI if slot not in emo.PREMIUM]

    m = Msg()
    m.header("star", "Premium emoji")
    m.kvline("ok", "Slots mapped", f"{len(emo.PREMIUM)} / {len(emo.EMOJI)}")
    if report["animated"] >= 0:
        m.kvline("chart", "Unique ids", report["total"])
        m.kvline("party", "Animated", report["animated"])
        m.kvline("warn", "Static", report["static"])
        if report["dropped"]:
            m.kvline("trash", "Dead ids removed", report["dropped"])
    m.nl()

    m.bold("Live sample — every icon below is a custom emoji:").nl()
    for slot in ("products", "wallet", "money", "stock", "sold", "sku",
                 "delivery", "party", "fire", "rocket", "key", "ok"):
        m.emoji(slot).space()
    m.nl(2)

    if report["sets"]:
        m.bold("Emoji sets in use").nl()
        for name in sorted(report["sets"])[:10]:
            m.text("• ").code(name).nl()
        m.nl()
    if missing:
        m.emoji("warn").space().bold(f"Still plain ({len(missing)})").nl()
        m.text(", ".join(f"{s} {emo.EMOJI[s]}" for s in missing)).nl(2)

    allowed = tg.CUSTOM_EMOJI_ALLOWED
    if allowed is False:
        m.emoji("ban").space().bold("Telegram is stripping them").nl()
        m.text("This bot is not permitted to send custom emoji, so every "
               "one above arrives as plain unicode. The Bot API allows them "
               "only for a bot that either:").nl()
        m.text("• has a username purchased for it on Fragment, or").nl()
        m.text("• is owned by an account with Telegram Premium — the "
               "account that created it in @BotFather.").nl(2)
        m.italic("No code change can work around this. Give the owner "
                 "account Premium, or create the bot from an account that "
                 "already has it, and these start working immediately.")
    elif allowed is True:
        m.emoji("ok").space().italic(
            "Telegram is keeping the custom emoji, so they render. If they "
            "do not visibly move, that is your client's animation setting.")
    else:
        m.italic("Send /start once, then re-check — the bot learns whether "
                 "Telegram accepts custom emoji from the first message it "
                 "sends with them.")

    await show(ctx, View.of(m, kb(
        [btn("Re-check", "ad:emoji", emoji_name="refresh")],
        _back_row(),
    )))


# ─── PREMIUM EMOJI HARVEST ────────────────────────────────────
async def harvest_emoji(ctx: Ctx, message: dict) -> bool:
    """Read custom_emoji ids out of a message an admin forwarded here.

    Forward any message that uses premium emoji and the ids are matched to
    this bot's emoji slots by the emoji each sticker represents, then merged
    into data/emoji.json. That is the whole setup for animated emoji — no
    hunting through @RawDataBot.
    """
    text = message.get("text") or message.get("caption") or ""
    entities = (message.get("entities") or []) + \
               (message.get("caption_entities") or [])
    found = [e for e in entities if e.get("type") == "custom_emoji"]
    if not found:
        return False

    ids = []
    for entity in found:
        eid = str(entity.get("custom_emoji_id") or "")
        if eid.isdigit() and eid not in ids:
            ids.append(eid)

    # Every custom emoji belongs to a set. Pulling the whole set turns one
    # forwarded message into hundreds of usable emoji, which is what makes a
    # single forward enough to style the entire bot.
    pool, set_names, kinds = await _emoji_pool(ids)

    mapping: dict = {}
    for slot, char_text in emo.EMOJI.items():
        eid = pool.get(emo.normalize(char_text))
        if eid:
            mapping[slot] = eid

    total = emo.save_premium(mapping) if mapping else len(emo.PREMIUM)
    report = await emo.audit(tg)
    missing = [slot for slot in emo.EMOJI if slot not in emo.PREMIUM]

    m = Msg()
    m.header("star", "Premium emoji adopted")
    m.kvline("box", "Emoji sets read", len(set_names))
    m.kvline("chart", "Emoji available", len(pool))
    m.kvline("ok", "Slots mapped", f"{total} / {len(emo.EMOJI)}")
    m.kvline("party", "Moving (animated/video)",
             f"{report['animated']} of {report['total']} ids")
    if report["static"]:
        m.kvline("warn", "Still images", report["static"])
    m.kvline("id", "From the message itself",
             f"{len(ids)} emoji pinned exactly")
    if set_names:
        m.nl()
        for name in sorted(set_names)[:12]:
            m.text("• ").code(name).nl()
    if missing:
        m.nl().emoji("warn").space()
        m.bold(f"Still plain ({len(missing)})").nl()
        m.text(", ".join(f"{slot} {emo.EMOJI[slot]}"
                         for slot in missing[:20])).nl()
        m.nl().italic("Forward a message that uses those emoji and they "
                      "will be picked up too.")
    else:
        m.nl().emoji("party").space().italic("Every slot is animated now.")
    m.nl(2).italic("Send /start to see the result.")

    text_out, entities_out = m.build()
    await tg.send_message(ctx.chat_id, text_out, entities_out,
                          kb(_back_row()))
    logger.info("emoji harvest: %d sets, %d emoji, %d/%d slots",
                len(set_names), len(pool), total, len(emo.EMOJI))
    return True


def _rank(sticker: dict, from_message: bool) -> int:
    """How much we want this sticker for its slot. Higher wins.

    An id taken straight out of the forwarded message beats anything merely
    found in the same set — that is what makes "forward the bot you like"
    reproduce its exact emoji. Failing that, a moving emoji beats a still
    one, because a static .webp can never animate however it is sent.
    """
    score = 0
    if from_message:
        score += 100
    if sticker.get("is_animated"):
        score += 10           # .tgs (Lottie)
    elif sticker.get("is_video"):
        score += 9            # .webm
    return score


async def _emoji_pool(ids: list) -> tuple[dict, list, dict]:
    """Pick the best id per emoji character.

    -> ({normalized char: id}, set names, {kind: count} for what was chosen)
    """
    best: dict = {}                      # char -> (score, id, sticker)
    set_names: list = []
    if not ids:
        return {}, set_names, {}

    def offer(sticker: dict, from_message: bool):
        char_text = emo.normalize(sticker.get("emoji") or "")
        eid = str(sticker.get("custom_emoji_id") or "")
        if not (char_text and eid):
            return
        score = _rank(sticker, from_message)
        if char_text not in best or score > best[char_text][0]:
            best[char_text] = (score, eid, sticker)

    data = await tg.api("getCustomEmojiStickers",
                        {"custom_emoji_ids": ids[:200]}, quiet=True)
    if not data.get("ok"):
        return {}, set_names, {}

    for sticker in data.get("result") or []:
        offer(sticker, from_message=True)
        name = sticker.get("set_name")
        if name and name not in set_names:
            set_names.append(name)

    for name in set_names:
        pack = await tg.api("getStickerSet", {"name": name}, quiet=True)
        if not pack.get("ok"):
            continue
        for sticker in (pack.get("result") or {}).get("stickers") or []:
            offer(sticker, from_message=False)

    pool = {char_text: eid for char_text, (_s, eid, _k) in best.items()}
    kinds: dict = {"animated": 0, "video": 0, "static": 0}
    for _score, _eid, sticker in best.values():
        if sticker.get("is_animated"):
            kinds["animated"] += 1
        elif sticker.get("is_video"):
            kinds["video"] += 1
        else:
            kinds["static"] += 1
    return pool, set_names, kinds


async def _product_field_prompt(ctx: Ctx, field: str, pid: str):
    if not store.product_get(pid):
        await toast(ctx, "Gone", alert=True)
        return

    syntax = {
        "name": "The new product name",
        "price": "The new price, for example 1.5",
        "description": "The full description shown on the confirm screen",
        "delivery_note": "The short delivery note",
        "emoji": f"One emoji slot name, e.g. star, box, mail, key\n"
                 f"Available: {', '.join(sorted(emo.EMOJI)[:24])} …",
        "qty": "min | max, for example 1 | 5",
        "bulk": "Volume discounts, one tier per line:\n"
                "qty | amount off each unit\n\n"
                "Example:\n5 | 0.15\n10 | 0.20\n\n"
                "Send - to remove all tiers.",
        "stock_mode": "lines, unlimited or manual\n\n"
                      "lines     = one stock line per buyer\n"
                      "unlimited = same payload for everyone\n"
                      "manual    = support delivers by hand",
    }.get(field)

    if syntax is None:
        await toast(ctx, "Unknown field", alert=True)
        return

    await _prompt(ctx, f"ad_prod_{field}", f"Set {field}", syntax,
                  cancel_to=f"ad:prod:o:{pid}", pid=pid)


# ─── PROMPT REPLIES ───────────────────────────────────────────
async def handle_prompt(ctx: Ctx, mode: str, data: dict, text: str) -> bool:
    """Consume an admin's reply to a prompt. Returns True when handled."""
    if not mode.startswith("ad_"):
        return False
    if not _guard(ctx):
        return True

    from .. import state
    raw = text.strip()

    if mode == "ad_cat_add":
        name, _, emoji_name = (part.strip() for part in
                               (raw.split("|") + ["", ""])[:3])
        if not name:
            await send_new(ctx, screens.simple("warn", "Need a name",
                                               "", ctx.lang, kb(_back_row())))
            return True
        cat_id = util.gen_id("c", 5).lower()
        store.category_save(cat_id, name=name,
                            emoji=emoji_name if emoji_name in emo.EMOJI
                            else "box")
        state.clear_prompt(ctx.user_id)
        await categories(ctx)
        return True

    if mode == "ad_cat_name":
        store.category_save(data["cat_id"], name=raw)
        state.clear_prompt(ctx.user_id)
        await category_open(ctx, data["cat_id"])
        return True

    if mode == "ad_cat_emoji":
        if raw not in emo.EMOJI:
            await send_new(ctx, screens.simple(
                "warn", "Unknown emoji slot",
                ", ".join(sorted(emo.EMOJI)), ctx.lang, kb(_back_row())))
            return True
        store.category_save(data["cat_id"], emoji=raw)
        state.clear_prompt(ctx.user_id)
        await category_open(ctx, data["cat_id"])
        return True

    if mode == "ad_prod_add":
        chunks = [part.strip() for part in raw.split("|")]
        name = chunks[0] if chunks else ""
        price = util.parse_amount(chunks[1]) if len(chunks) > 1 else None
        description = chunks[2] if len(chunks) > 2 else ""
        if not name or price is None:
            await send_new(ctx, screens.simple(
                "warn", "Need name and price",
                "Example: Spotify 3 Months | 1.5 | Full access", ctx.lang,
                kb(_back_row())))
            return True
        pid = util.gen_id("p", 6).lower()
        store.product_save(pid, cat_id=data["cat_id"], name=name, price=price,
                           description=description, delivery_note=description,
                           sku=util.gen_sku(),
                           position=len(store.products_in(data["cat_id"],
                                                          include_hidden=True)))
        state.clear_prompt(ctx.user_id)
        await product_open(ctx, pid)
        return True

    if mode.startswith("ad_prod_"):
        field = mode[len("ad_prod_"):]
        pid = data.get("pid", "")
        if not store.product_get(pid):
            state.clear_prompt(ctx.user_id)
            return True
        await _apply_product_field(ctx, pid, field, raw)
        state.clear_prompt(ctx.user_id)
        await product_open(ctx, pid)
        return True

    if mode == "ad_stock_add":
        pid = data.get("pid", "")
        product = store.product_get(pid)
        if not product:
            state.clear_prompt(ctx.user_id)
            return True
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            await send_new(ctx, screens.simple("warn", "Nothing to add", "",
                                               ctx.lang, kb(_back_row())))
            return True
        store.stock_add(pid, lines)
        store.product_save(pid, gone_posted=False)
        state.clear_prompt(ctx.user_id)
        await product_open(ctx, pid)

        fresh = store.product_get(pid)
        total = store.stock_count(pid)
        try:
            await broadcast.stock_alert(fresh, len(lines), total)
            await broadcast.alert_restock_subscribers(fresh, len(lines))
        except Exception as exc:                 # noqa: BLE001
            logger.warning("restock announce failed: %s", exc)
        return True

    if mode == "ad_gift_add":
        chunks = [part.strip() for part in raw.split("|")]
        amount = util.parse_amount(chunks[0]) if chunks else None
        uses = util.parse_qty(chunks[1]) if len(chunks) > 1 and chunks[1] else 1
        code = util.normalize_code(chunks[2]) if len(chunks) > 2 else ""
        if amount is None or amount <= 0:
            await send_new(ctx, screens.simple("warn", "Need an amount",
                                               "Example: 5 | 10", ctx.lang,
                                               kb(_back_row())))
            return True
        code = code or util.gen_code("GIFT-", 8)
        store.giftcode_save(code, amount=amount, max_uses=uses or 1)
        state.clear_prompt(ctx.user_id)
        await gift_open(ctx, code)
        return True

    if mode == "ad_coup_add":
        chunks = [part.strip() for part in raw.split("|")]
        code = util.normalize_code(chunks[0]) if chunks else ""
        kind = (chunks[1].lower() if len(chunks) > 1 else "percent")
        value = util.parse_amount(chunks[2]) if len(chunks) > 2 else None
        uses = util.parse_qty(chunks[3]) if len(chunks) > 3 and chunks[3] else 0
        scope = chunks[4] if len(chunks) > 4 else ""
        if not code or kind not in ("percent", "fixed") or value is None:
            await send_new(ctx, screens.simple(
                "warn", "Check the syntax",
                "code | percent|fixed | value | uses | product id", ctx.lang,
                kb(_back_row())))
            return True
        store.coupon_save(code, kind=kind, value=value, max_uses=uses or 0,
                          scope_pid=scope)
        state.clear_prompt(ctx.user_id)
        await coupon_menu(ctx)
        return True

    if mode == "ad_user_find":
        needle = raw.lstrip("@").lower()
        found = None
        if needle.isdigit():
            found = store.users.get(needle)
        if not found:
            for record in store.users.values():
                if (record.get("username") or "").lower() == needle:
                    found = record
                    break
        state.clear_prompt(ctx.user_id)
        if not found:
            await send_new(ctx, screens.simple("warn", "No such user", "",
                                               ctx.lang, kb(_back_row())))
            return True
        await user_open(ctx, str(found.get("id")))
        return True

    if mode == "ad_user_credit":
        amount = util.parse_amount(raw)
        target = data.get("target")
        if amount is None or amount == 0:
            await send_new(ctx, screens.simple("warn", "Send a number", "",
                                               ctx.lang, kb(_back_row())))
            return True
        store.credit(target, amount, kind="topup" if amount > 0 else "adjust")
        state.clear_prompt(ctx.user_id)

        lang = store.user_lang(target)
        if amount > 0:
            topup = store.topup_create(
                user_id=int(target), amount=amount, method="admin",
                status="paid", credited=True, paid=util.now_ts(),
            )
            await broadcast.dm(
                target,
                lambda m: m.header("party", t("wallet_title", lang)).text(
                    t("wallet_funded_dm", lang,
                      amount=util.fmt_money(amount),
                      balance=util.fmt_money(store.balance_of(target)))),
            )
            try:
                await broadcast.wallet_funded(topup)
            except Exception as exc:             # noqa: BLE001
                logger.warning("funded post failed: %s", exc)
        await user_open(ctx, str(target))
        return True

    if mode == "ad_user_ban":
        target = data.get("target")
        store.set_banned(target, True, raw or "—")
        state.clear_prompt(ctx.user_id)
        await user_open(ctx, str(target))
        return True

    if mode == "ad_user_msg":
        target = data.get("target")
        await tg.send_message(target, raw)
        state.clear_prompt(ctx.user_id)
        await toast(ctx, "Sent")
        await user_open(ctx, str(target))
        return True

    if mode == "ad_bc":
        state.clear_prompt(ctx.user_id)
        await run_broadcast(ctx, raw)
        return True

    if mode == "ad_set":
        key = data.get("key", "")
        value = "" if raw == "-" else raw
        if key == "min_topup":
            parsed = util.parse_amount(value)
            value = parsed if parsed is not None else config.MIN_TOPUP
        store.set_setting(key, value)
        state.clear_prompt(ctx.user_id)
        await settings_menu(ctx)
        return True

    return False


async def _apply_product_field(ctx: Ctx, pid: str, field: str, raw: str):
    if field == "price":
        price = util.parse_amount(raw)
        if price is None or price < 0:
            return
        old = float((store.product_get(pid) or {}).get("price") or 0.0)
        store.product_save(pid, price=price)
        # A price drop is news; a rise is not something to advertise.
        if price < old:
            try:
                await broadcast.price_update(store.product_get(pid), old)
            except Exception as exc:             # noqa: BLE001
                logger.warning("price update announce failed: %s", exc)
        return
    if field == "bulk":
        store.product_save(pid, bulk=_parse_bulk(raw))
        return
    if field == "qty":
        chunks = [part.strip() for part in raw.split("|")]
        low = util.parse_qty(chunks[0]) if chunks else None
        high = util.parse_qty(chunks[1]) if len(chunks) > 1 else None
        if low and high and high >= low:
            store.product_save(pid, min_qty=low, max_qty=high)
        return
    if field == "stock_mode":
        mode = raw.strip().lower()
        if mode in ("lines", "unlimited", "manual"):
            updates = {"stock_mode": mode}
            if mode == "manual":
                updates["delivery_mode"] = "manual"
            elif mode == "lines":
                updates["delivery_mode"] = "instant"
            store.product_save(pid, **updates)
        return
    if field == "emoji":
        if raw.strip() in emo.EMOJI:
            store.product_save(pid, emoji=raw.strip())
        return
    if field in ("name", "description", "delivery_note"):
        store.product_save(pid, **{field: "" if raw == "-" else raw})
