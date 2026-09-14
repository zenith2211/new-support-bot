"""
app/screens.py — every customer-facing screen.

Each function returns a View (text + entities + keyboard + poster). Handlers
decide *when* a screen is shown; this module decides what it looks like, so
the wording and layout of the storefront all live in one place.
"""

from . import commands, config, emoji as emo, payments, store, util
from .lang import LANGS, lang_flag, lang_name, t
from .msg import Msg
from .view import View, btn, kb, reply_kb

TOPUP_PRESETS = (1, 3, 5, 10, 25, 50)


# ─── SHARED PIECES ────────────────────────────────────────────
def main_reply_kb(lang: str) -> dict:
    return reply_kb(
        [
            [f"{emo.char('products')} {t('btn_products', lang)}",
             f"{emo.char('wallet')} {t('btn_wallet', lang)}"],
            [f"{emo.char('orders')} {t('btn_orders', lang)}",
             f"{emo.char('gift')} {t('btn_gift', lang)}"],
            [f"{emo.char('support')} {t('btn_support', lang)}"],
            [f"{emo.char('profile')} {t('btn_profile', lang)}",
             f"{emo.char('language')} {t('btn_language', lang)}"],
        ],
        placeholder=t("products_tap", lang),
    )


def reply_labels(lang: str) -> dict:
    """{reply-keyboard label: route} for every supported language, so the
    persistent buttons keep working after a language switch."""
    routes = {}
    for code in LANGS:
        routes[f"{emo.char('products')} {t('btn_products', code)}"] = "products"
        routes[f"{emo.char('wallet')} {t('btn_wallet', code)}"] = "wallet"
        routes[f"{emo.char('orders')} {t('btn_orders', code)}"] = "orders"
        routes[f"{emo.char('gift')} {t('btn_gift', code)}"] = "gift"
        routes[f"{emo.char('support')} {t('btn_support', code)}"] = "support"
        routes[f"{emo.char('profile')} {t('btn_profile', code)}"] = "profile"
        routes[f"{emo.char('language')} {t('btn_language', code)}"] = "language"
    return routes


def home_row(lang: str) -> list:
    return [btn(t("btn_home", lang), "nav:home", emoji_name="home")]


def _delivery_words(product: dict, lang: str) -> str:
    mode = product.get("delivery_mode", "instant")
    word = t("pd_delivery_instant" if mode == "instant" else
             "pd_delivery_manual", lang)
    channel = product.get("delivery_channel") or "chat"
    return f"{word} · {channel}"


def _stock_words(pid: str, lang: str) -> str:
    if store.stock_is_unlimited(pid):
        return "∞"
    return str(store.stock_count(pid))


# ─── START ────────────────────────────────────────────────────
def start(tg_user: dict, lang: str, is_admin: bool = False) -> View:
    m = Msg()
    m.header("products", store.store_name())
    m.emoji("spark").space()
    m.bold(t("start_hello", lang, name=util.display_name(tg_user))).nl(2)
    m.text(t("start_tagline", lang)).nl(2)

    m.bullet("products", t("menu_products", lang), t("menu_products_desc", lang))
    m.bullet("wallet", t("menu_wallet", lang), payments.methods_summary())
    m.bullet("orders", t("menu_orders", lang), t("menu_orders_desc", lang))
    m.bullet("gift", t("menu_gift", lang), t("menu_gift_desc", lang))
    m.bullet("support", t("menu_support", lang), t("menu_support_desc", lang))
    m.nl()

    m.bold(t("start_commands", lang)).nl()
    for command, emoji_name, description in commands.listing(
            lang, include_admin=is_admin):
        m.emoji(emoji_name).space().code(command).text(f" — {description}").nl()

    note = store.setting("welcome_note") or ""
    m.nl()
    if note:
        m.italic(note).nl(2)
    m.emoji("tip").space().italic(t("start_tip", lang))

    return View.of(m, keyboard=main_reply_kb(lang), poster=config.BANNER_START)


# ─── CATEGORIES ───────────────────────────────────────────────
def categories(lang: str) -> View:
    cats = store.category_list()
    counts = store.stock_counts_by_category()

    m = Msg()
    m.header("products", t("products_title", lang))
    m.emoji("spark").space().text(t("products_intro", lang)).nl(2)

    if not cats:
        m.emoji("warn").space().italic(t("products_empty", lang))
        return View.of(
            m,
            kb([btn(t("btn_refresh", lang), "nav:products", emoji_name="refresh")],
               home_row(lang)),
            poster=config.BANNER_PRODUCTS,
        )

    m.kvline("bank", t("products_categories", lang), len(cats))
    m.nl()
    for cat in cats:
        m.emoji(cat.get("emoji") or "box").space()
        m.bold(cat.get("name") or "—")
        m.text(f" — {counts.get(str(cat['id']), 0)}").nl()
    m.nl()
    m.emoji("rocket").space().italic(t("products_tap", lang))

    rows = [
        [btn(f"{cat.get('name') or '—'} ({counts.get(str(cat['id']), 0)})",
             f"cat:{cat['id']}", emoji_name=cat.get("emoji") or "box")]
        for cat in cats
    ]
    rows.append([
        btn(t("btn_api_key", lang), "nav:api", emoji_name="lock"),
        btn(t("btn_refresh", lang), "nav:products", emoji_name="refresh"),
        btn(t("btn_close", lang), "nav:close", emoji_name="close", style="danger"),
    ])
    return View.of(m, kb(*rows), poster=config.BANNER_PRODUCTS)


# ─── ONE CATEGORY ─────────────────────────────────────────────
def category(cat: dict, lang: str) -> View:
    items = store.products_in(cat["id"])

    m = Msg()
    m.header(cat.get("emoji") or "box", (cat.get("name") or "—").upper())
    if not items:
        m.italic(t("category_empty", lang))
        return View.of(
            m,
            kb([btn(t("btn_catalog", lang), "nav:products",
                    emoji_name="catalog")]),
            poster=config.BANNER_PRODUCTS,
        )

    m.text(t("category_intro", lang, n=len(items))).nl(2)

    for product in items:
        pid = product["id"]
        count = store.stock_count(pid)
        m.emoji(product.get("emoji") or "box").space()
        m.bold(product.get("name") or "—").nl()
        m.emoji("money").space().bold(util.fmt_money(product.get("price")))
        m.text(" · ")
        if store.stock_is_unlimited(pid):
            m.text(t("unlimited_stock", lang))
        elif count > 0:
            m.text(t("in_stock", lang, n=count))
        else:
            m.text(t("out_of_stock", lang))
        bulk = store.bulk_label(product)
        if bulk:
            m.text(" · ").emoji("chart").space().text(bulk)
        m.nl(2)

    rows = []
    for product in items:
        pid = product["id"]
        bits = [util.clip(product.get("name") or "—", 30),
                util.fmt_money(product.get("price")),
                store.stock_display(pid)]
        bulk = store.bulk_label(product)
        if bulk:
            bits.append(bulk)
        rows.append([btn(" · ".join(bits), f"p:{pid}",
                         emoji_name=product.get("emoji") or "box")])
    rows.append([btn(t("btn_catalog", lang), "nav:products",
                     emoji_name="catalog")])
    return View.of(m, kb(*rows), poster=config.BANNER_PRODUCTS)


# ─── PRODUCT DETAIL ───────────────────────────────────────────
def product(product_rec: dict, lang: str, balance: float,
            qty: int = 1, coupon: dict | None = None,
            alerts_on: bool = True) -> View:
    pid = product_rec["id"]
    count = store.stock_count(pid)
    price = float(product_rec.get("price") or 0.0)
    min_qty = max(int(product_rec.get("min_qty") or 1), 1)
    max_qty = max(int(product_rec.get("max_qty") or 1), min_qty)
    if not store.stock_is_unlimited(pid):
        max_qty = min(max_qty, max(count, min_qty))
    qty = min(max(qty, min_qty), max_qty)
    total = price * qty

    m = Msg()
    m.header(product_rec.get("emoji") or "box", product_rec.get("name") or "—")
    m.kvline("money", t("pd_unit_price", lang), util.fmt_money(price))

    m.emoji("stock").space().bold(f"{t('pd_stock', lang)}: ")
    m.bold(_stock_words(pid, lang))
    m.text(" · ").text(emo.BAR)
    m.bold(f"{t('pd_wallet', lang)}: ").bold(util.fmt_money(balance)).nl()

    m.kvline("sold", t("pd_sold", lang), int(product_rec.get("sold") or 0))
    m.kvline("sku", t("pd_sku", lang), product_rec.get("sku") or "—")
    m.kvline("delivery", t("pd_delivery", lang),
             _delivery_words(product_rec, lang), bold_value=False)
    if product_rec.get("warranty"):
        m.kvline("ok", t("pd_warranty", lang), product_rec["warranty"],
                 bold_value=False)

    tiers = store.bulk_tiers(product_rec)
    if tiers:
        m.emoji("chart").space().bold(f"{t('pd_bulk', lang)}:").nl()
        for tier in tiers:
            per_unit = max(round(price - tier["off"], 6), 0.0)
            m.text(f"  x{tier['qty']}+ · {util.fmt_money(tier['off'])} "
                   f"{t('pd_bulk_off', lang)} · ")
            m.bold(util.fmt_money(per_unit)).nl()

    unit_now, tier_now = store.unit_price_for(product_rec, qty)
    m.emoji("products").space()
    m.bold(t("pd_qty_line", lang, min=min_qty, max=max_qty, qty=qty,
             total=util.fmt_money(unit_now * qty)))
    if tier_now:
        m.nl().emoji("party").space()
        m.italic(t("pd_bulk_active", lang,
                   saved=util.fmt_money((price - unit_now) * qty)))

    if coupon:
        _record, _err, discount = store.coupon_check(
            coupon.get("code", ""), pid, total
        )
        if discount:
            m.nl().emoji("coupon").space()
            m.italic(t("pd_coupon_applied", lang, code=coupon["code"],
                       amount=util.fmt_money(discount)))

    if count <= 0 and not store.stock_is_unlimited(pid):
        m.nl(2).emoji("low").space().italic(t("pd_sold_out_note", lang))

    # buttons
    rows = []
    sellable = count > 0 or store.stock_is_unlimited(pid)
    if sellable:
        presets = store.qty_presets(product_rec, count)
        quick = [
            btn(f"x{value}", f"buy:{pid}:{value}",
                style="primary" if value == qty else None)
            for value in presets
        ]
        # Three per row, with Custom filling the last slot.
        for index in range(0, len(quick), 3):
            rows.append(quick[index:index + 3])
        custom = btn(t("btn_custom", lang), f"pq:{pid}", emoji_name="star")
        if rows and len(rows[-1]) < 3:
            rows[-1].append(custom)
        else:
            rows.append([custom])

    if coupon:
        rows.append([btn(t("btn_remove_coupon", lang), f"pcx:{pid}",
                         emoji_name="close")])
    else:
        rows.append([btn(t("btn_apply_coupon", lang), f"pc:{pid}",
                         emoji_name="coupon", style="primary")])

    rows.append([
        btn(t("btn_stop_alerts" if alerts_on else "btn_get_alerts", lang),
            f"pa:{pid}",
            emoji_name="bell" if alerts_on else "bell_off",
            style="danger" if alerts_on else None)
    ])
    if product_rec.get("delivery_note") or product_rec.get("description"):
        rows.append([btn(t("btn_delivery_note", lang), f"pn:{pid}",
                         emoji_name="delivery")])
    rows.append([btn(t("btn_back", lang), f"cat:{product_rec.get('cat_id')}",
                     emoji_name="back")])

    poster = product_rec.get("image") or config.BANNER_PRODUCTS
    return View.of(m, kb(*rows), poster=poster)


def delivery_note(product_rec: dict, lang: str) -> View:
    m = Msg()
    m.header("note", t("confirm_delivery_note", lang))
    m.emoji(product_rec.get("emoji") or "box").space()
    m.bold(product_rec.get("name") or "—").nl(2)
    body = (product_rec.get("delivery_note")
            or product_rec.get("description") or "—")
    m.text(body)
    return View.of(m, kb([btn(t("btn_product", lang), f"p:{product_rec['id']}",
                              emoji_name="back")]))


# ─── CONFIRM ──────────────────────────────────────────────────
def confirm(product_rec: dict, lang: str, qty: int, balance: float,
            coupon: dict | None = None) -> View:
    pid = product_rec["id"]
    priced = store.quote(pid, qty, (coupon or {}).get("code", ""))

    m = Msg()
    m.header("clipboard", t("confirm_title", lang))
    m.emoji(product_rec.get("emoji") or "box").space()
    m.bold(product_rec.get("name") or "—").nl(2)

    m.kvline("qty", t("confirm_qty", lang), qty)
    m.kvline("money", t("pd_unit_price", lang),
             util.fmt_money(priced["price"]))
    if priced["bulk_saved"] > 0:
        m.kvline("chart", t("pd_bulk", lang),
                 f"-{util.fmt_money(priced['bulk_saved'])}")
    if priced["discount"]:
        m.kvline("coupon", t("confirm_discount", lang),
                 f"-{util.fmt_money(priced['discount'])}")
    m.kvline("money", t("confirm_total", lang),
             util.fmt_money(priced["total"]))
    m.kvline("card", t("pd_wallet", lang), util.fmt_money(balance))

    description = (product_rec.get("description") or "").strip()
    if description:
        m.nl().bold(t("confirm_details", lang)).nl()
        m.text(util.clip(description, 700)).nl()

    note = (product_rec.get("delivery_note") or "").strip()
    if note and note != description:
        m.nl().emoji("delivery").space().bold(t("confirm_delivery_note", lang))
        m.nl().text(util.clip(note, 400)).nl()

    m.nl().text(t("confirm_question", lang))

    coupon_code = (coupon or {}).get("code", "")
    suffix = f":{coupon_code}" if coupon_code else ""
    return View.of(m, kb(
        [btn(t("btn_yes_buy", lang), f"ok:{pid}:{qty}{suffix}",
             emoji_name="ok", style="success")],
        [btn(t("btn_no_cancel", lang), f"p:{pid}",
             emoji_name="no", style="danger")],
    ))


# ─── LOW BALANCE ──────────────────────────────────────────────
def low_balance(product_rec: dict, lang: str, qty: int, balance: float,
                total: float) -> View:
    pid = product_rec["id"]
    price = float(product_rec.get("price") or 0.0)
    short = max(round(total - balance, 6), 0.0)
    charge = max(short, store.min_topup())

    m = Msg()
    m.header("low", t("low_title", lang))
    m.kvline("money", t("pd_unit_price", lang), util.fmt_money(price))
    m.kvline("qty", t("confirm_qty", lang), qty)
    m.kvline("money", t("confirm_total", lang), util.fmt_money(total))
    m.nl()
    m.kvline("card", t("pd_wallet", lang), util.fmt_money(balance))
    m.nl()
    m.text(t("low_help", lang)).nl(2)
    m.text(t("low_need", lang,
             short=util.fmt_money(short),
             min=util.fmt_money(store.min_topup())))

    return View.of(m, kb(
        [btn(t("btn_pay_and_get", lang, amount=util.fmt_money_short(charge)),
             f"pay:{pid}:{qty}", emoji_name="card", style="success")],
        [btn(t("btn_open_wallet", lang), "nav:wallet", emoji_name="wallet")],
        [btn(t("btn_product", lang), f"p:{pid}", emoji_name="back")],
    ))


# ─── PAY AND GET ITEM ─────────────────────────────────────────
def pay_methods(product_rec: dict, lang: str, qty: int, balance: float,
                total: float) -> View:
    pid = product_rec["id"]
    short = max(round(total - balance, 6), 0.0)
    charge = max(short, store.min_topup())
    methods = payments.available()

    m = Msg()
    m.header("card", t("pay_title", lang))
    m.kvline("coupon", t("pay_product", lang), product_rec.get("name") or "—")
    m.kvline("qty", t("confirm_qty", lang), qty)
    m.kvline("money", t("pay_order_total", lang), util.fmt_money(total))
    m.kvline("card", t("pd_wallet", lang), util.fmt_money(balance))
    m.kvline("money", t("pay_now", lang), util.fmt_money(charge))
    m.nl()
    m.text(t("low_need", lang,
             short=util.fmt_money(short),
             min=util.fmt_money(store.min_topup()))).nl(2)

    if methods:
        m.emoji("rocket").space().italic(t("pay_pick", lang))
    else:
        m.emoji("warn").space().italic(t("pay_none", lang))

    rows = [
        [btn(method.label, f"paym:{method.key}:{pid}:{qty}",
             emoji_name=method.emoji, style="success")]
        for method in methods
    ]
    rows.append([btn(t("btn_gift", lang), "nav:gift", emoji_name="gift")])
    rows.append([btn(t("btn_open_wallet", lang), "nav:wallet",
                     emoji_name="wallet")])
    rows.append([btn(t("btn_product", lang), f"p:{pid}", emoji_name="back")])
    return View.of(m, kb(*rows))


# ─── INVOICE ──────────────────────────────────────────────────
def invoice(topup: dict, lang: str, method_label: str,
            checkout_url: str = "", manual_note: str = "") -> View:
    m = Msg()
    m.header("card", t("invoice_title", lang))
    m.kvline("money", t("invoice_amount", lang),
             util.fmt_money(topup.get("amount")))
    m.kvline("bank", t("invoice_method", lang), method_label)
    m.emoji("sku").space().bold(f"{t('invoice_ref', lang)}: ")
    m.code(topup.get("id") or "—").nl(2)

    if manual_note:
        m.text(manual_note).nl(2)
        m.italic(t("invoice_manual", lang))
    else:
        m.italic(t("invoice_open", lang))

    rows = []
    if checkout_url:
        rows.append([btn(t("btn_open_invoice", lang), url=checkout_url,
                         emoji_name="card", style="success")])
    rows.append([btn(t("btn_i_paid", lang), f"paid:{topup['id']}",
                     emoji_name="ok")])
    rows.append([btn(t("btn_cancel", lang), f"pcan:{topup['id']}",
                     emoji_name="no", style="danger")])
    rows.append([btn(t("btn_open_wallet", lang), "nav:wallet",
                     emoji_name="wallet")])
    return View.of(m, kb(*rows))


# ─── DELIVERY ─────────────────────────────────────────────────
def delivered(order: dict, lang: str, balance: float) -> View:
    m = Msg()
    m.header("party", t("delivered_title", lang))
    m.kvline("box", t("pay_product", lang), order.get("product_name") or "—")
    m.kvline("qty", t("confirm_qty", lang), order.get("qty") or 1)
    m.kvline("money", t("confirm_total", lang),
             util.fmt_money(order.get("total")))
    m.kvline("card", t("pd_wallet", lang), util.fmt_money(balance))
    m.emoji("sku").space().bold(f"{t('order_title', lang)}: ")
    m.code(order.get("id") or "—").nl()

    items = [line for line in (order.get("items") or []) if str(line).strip()]
    if items:
        m.nl().emoji("key").space().bold(t("delivered_items", lang)).nl()
        for line in items:
            m.code(str(line)).nl()
    elif order.get("status") == "manual":
        m.nl().emoji("clock").space().italic(t("delivered_manual", lang))

    m.nl().emoji("tip").space().italic(t("delivered_keep", lang))

    rows = [
        [btn(t("btn_products", lang), "nav:products", emoji_name="products"),
         btn(t("btn_orders", lang), "nav:orders", emoji_name="orders")],
    ]
    if store.support_url():
        rows.append([btn(t("btn_contact_support", lang),
                         url=store.support_url(), emoji_name="support")])
    return View.of(m, kb(*rows), poster=config.POSTER_DELIVERED)


# ─── WALLET ───────────────────────────────────────────────────
def wallet(user_rec: dict, lang: str) -> View:
    user_id = user_rec.get("id")
    m = Msg()
    m.header("wallet", t("wallet_title", lang))
    m.kvline("money", t("wallet_balance", lang),
             util.fmt_money(user_rec.get("balance")))
    m.emoji("id").space().bold(f"{t('wallet_customer_id', lang)}: ")
    m.code(store.customer_id(user_id) or "—").nl()
    m.kvline("coin", t("wallet_topped_up", lang),
             util.fmt_money(user_rec.get("topped_up")))
    m.kvline("chart", t("wallet_spent", lang),
             util.fmt_money(user_rec.get("spent")))
    m.nl()
    m.emoji("rocket").space().text(t("wallet_hint_topup", lang)).nl()
    m.emoji("plus").space().text(t("wallet_hint_transfer", lang)).nl()
    m.emoji("ok").space().text(f"{t('wallet_accepted', lang)}: "
                               f"{payments.methods_summary()}").nl(2)

    recent = store.topups_of(user_id, limit=3)
    m.emoji("orders").space().bold(t("wallet_recent", lang)).nl()
    if not recent:
        m.text(f"• {t('wallet_history_empty', lang)}").nl()
    else:
        for record in recent:
            icon = {"paid": "ok", "pending": "clock"}.get(
                record.get("status") or "pending", "no")
            m.text("• ").emoji(icon).space()
            m.text(f"{util.fmt_money(record.get('amount'))} · "
                   f"{payments.label(record.get('method'))} · "
                   f"{util.ago(record.get('created'))}").nl()

    return View.of(m, kb(
        [btn(t("btn_topup", lang), "w:top", emoji_name="card",
             style="success"),
         btn(t("btn_transfer", lang), "w:tr", emoji_name="plus",
             style="primary")],
        [btn(t("btn_gift", lang), "nav:gift", emoji_name="gift"),
         btn(t("btn_history", lang), "w:hist", emoji_name="orders")],
        [btn(t("btn_home", lang), "nav:home", emoji_name="back",
             style="primary")],
    ), poster=config.BANNER_WALLET)


def topup_amounts(lang: str, balance: float) -> View:
    m = Msg()
    m.header("plus", t("topup_title", lang))
    m.kvline("money", t("wallet_balance", lang), util.fmt_money(balance))
    m.nl()
    m.text(t("topup_pick", lang)).nl(2)
    m.italic(t("wallet_min", lang, min=util.fmt_money(store.min_topup())))

    presets = [amount for amount in TOPUP_PRESETS
               if amount >= store.min_topup()]
    rows = []
    for index in range(0, len(presets), 3):
        rows.append([
            btn(util.fmt_money_short(amount), f"w:top:{amount}",
                emoji_name="money")
            for amount in presets[index:index + 3]
        ])
    rows.append([btn(t("btn_custom", lang), "w:topc", emoji_name="star")])
    rows.append([btn(t("btn_wallet", lang), "nav:wallet", emoji_name="back")])
    return View.of(m, kb(*rows), poster=config.BANNER_WALLET)


def topup_methods(lang: str, amount: float) -> View:
    methods = payments.available()
    m = Msg()
    m.header("card", t("topup_title", lang))
    m.kvline("money", t("invoice_amount", lang), util.fmt_money(amount))
    m.nl()
    if methods:
        m.emoji("rocket").space().italic(t("pay_pick", lang))
    else:
        m.emoji("warn").space().italic(t("pay_none", lang))

    rows = [
        [btn(method.label, f"wm:{method.key}:{util.fmt_amount(amount)}",
             emoji_name=method.emoji, style="success")]
        for method in methods
    ]
    rows.append([btn(t("btn_gift", lang), "nav:gift", emoji_name="gift")])
    rows.append([btn(t("btn_back", lang), "w:top", emoji_name="back")])
    return View.of(m, kb(*rows))


def wallet_history(user_id, lang: str) -> View:
    rows_data = store.topups_of(user_id, limit=10)
    m = Msg()
    m.header("orders", t("wallet_history_title", lang))
    if not rows_data:
        m.italic(t("wallet_history_empty", lang))
    else:
        for record in rows_data:
            status = record.get("status") or "pending"
            icon = {"paid": "ok", "pending": "clock"}.get(status, "no")
            m.emoji(icon).space()
            m.bold(util.fmt_money(record.get("amount")))
            m.text(f" · {payments.label(record.get('method'))}")
            m.text(f" · {util.ago(record.get('created'))}").nl()
    return View.of(m, kb(
        [btn(t("btn_topup", lang), "w:top", emoji_name="plus")],
        [btn(t("btn_wallet", lang), "nav:wallet", emoji_name="back")],
    ))


# ─── ORDERS ───────────────────────────────────────────────────
def orders(user_id, lang: str) -> View:
    mine = store.orders_of(user_id, limit=10)
    m = Msg()
    m.header("orders", t("orders_title", lang))
    if not mine:
        m.italic(t("orders_empty", lang))
        return View.of(m, kb(
            [btn(t("btn_products", lang), "nav:products",
                 emoji_name="products")],
            home_row(lang),
        ), poster=config.BANNER_ORDERS)

    m.text(t("orders_intro", lang, n=len(mine))).nl(2)
    for order in mine:
        m.emoji("box").space().bold(util.clip(order.get("product_name"), 46))
        m.nl()
        m.emoji("money").space().text(util.fmt_money(order.get("total")))
        m.text(f" · x{order.get('qty', 1)}")
        m.text(f" · {util.ago(order.get('created'))}").nl()
        m.emoji("sku").space().code(order.get("id") or "—").nl(2)

    rows = [[btn(f"{util.clip(order.get('product_name'), 30)} · "
                 f"{util.fmt_money(order.get('total'))}",
                 f"ord:{order['id']}", emoji_name="box")]
            for order in mine]
    rows.append(home_row(lang))
    return View.of(m, kb(*rows), poster=config.BANNER_ORDERS)


def order_detail(order: dict, lang: str) -> View:
    status_key = {
        "delivered": "status_delivered",
        "pending": "status_pending",
        "manual": "status_manual",
        "cancelled": "status_cancelled",
    }.get(order.get("status") or "pending", "status_pending")

    m = Msg()
    m.header("orders", t("order_title", lang))
    m.emoji("sku").space().bold(f"{t('order_title', lang)}: ")
    m.code(order.get("id") or "—").nl()
    m.kvline("box", t("pay_product", lang), order.get("product_name") or "—")
    m.kvline("qty", t("confirm_qty", lang), order.get("qty") or 1)
    m.kvline("money", t("pd_unit_price", lang),
             util.fmt_money(order.get("unit_price")))
    if float(order.get("discount") or 0):
        m.kvline("coupon", t("confirm_discount", lang),
                 f"-{util.fmt_money(order.get('discount'))}")
    m.kvline("money", t("confirm_total", lang),
             util.fmt_money(order.get("total")))
    m.kvline("ok", t("order_status", lang), t(status_key, lang))
    m.kvline("clock", t("order_date", lang),
             util.fmt_date(order.get("created")), bold_value=False)

    items = [line for line in (order.get("items") or []) if str(line).strip()]
    if items:
        m.nl().emoji("key").space().bold(t("delivered_items", lang)).nl()
        for line in items:
            m.code(str(line)).nl()

    rows = []
    if items:
        rows.append([btn(t("btn_resend", lang), f"ordr:{order['id']}",
                         emoji_name="refresh")])
    if store.support_url():
        rows.append([btn(t("btn_contact_support", lang),
                         url=store.support_url(), emoji_name="support")])
    rows.append([btn(t("btn_orders", lang), "nav:orders", emoji_name="back")])
    return View.of(m, kb(*rows))


# ─── GIFT CODE ────────────────────────────────────────────────
def gift(lang: str, balance: float) -> View:
    m = Msg()
    m.header("gift", t("gift_title", lang))
    m.kvline("money", t("wallet_balance", lang), util.fmt_money(balance))
    m.nl()
    m.text(t("gift_intro", lang)).nl(2)
    m.emoji("rocket").space().italic(t("gift_send_now", lang))
    return View.of(m, kb(
        [btn(t("btn_wallet", lang), "nav:wallet", emoji_name="wallet")],
        home_row(lang),
    ), poster=config.BANNER_GIFT)


# ─── SUPPORT ──────────────────────────────────────────────────
def support(lang: str) -> View:
    m = Msg()
    m.header("support", t("support_title", lang))
    m.text(t("support_intro", lang)).nl(2)
    m.emoji("clock").space().italic(t("support_hours", lang))

    rows = []
    url = store.support_url()
    if url:
        rows.append([btn(t("btn_contact_support", lang), url=url,
                         emoji_name="support", style="success")])
    channel = store.setting("channel_link")
    if channel:
        rows.append([btn(store.store_name(), url=channel, emoji_name="link")])
    rows.append([btn(t("btn_orders", lang), "nav:orders", emoji_name="orders"),
                 btn(t("terms_title", lang), "nav:terms", emoji_name="terms")])
    rows.append(home_row(lang))
    return View.of(m, kb(*rows), poster=config.BANNER_SUPPORT)


# ─── PROFILE ──────────────────────────────────────────────────
def profile(user_rec: dict, lang: str) -> View:
    m = Msg()
    m.header("profile", t("profile_title", lang))
    m.kvline("user", t("profile_name", lang),
             util.display_name(user_rec))
    m.emoji("id").space().bold(f"{t('profile_id', lang)}: ")
    m.code(str(user_rec.get("id") or "—")).nl()
    m.kvline("money", t("wallet_balance", lang),
             util.fmt_money(user_rec.get("balance")))
    m.kvline("chart", t("wallet_spent", lang),
             util.fmt_money(user_rec.get("spent")))
    m.kvline("orders", t("profile_orders", lang),
             int(user_rec.get("orders") or 0))
    m.kvline("clock", t("profile_joined", lang),
             util.fmt_day(user_rec.get("joined")), bold_value=False)
    m.kvline("language", t("profile_language", lang),
             f"{lang_flag(lang)} {lang_name(lang)}", bold_value=False)

    return View.of(m, kb(
        [btn(t("btn_wallet", lang), "nav:wallet", emoji_name="wallet"),
         btn(t("btn_orders", lang), "nav:orders", emoji_name="orders")],
        [btn(t("btn_language", lang), "nav:language", emoji_name="language")],
        home_row(lang),
    ), poster=config.BANNER_PROFILE)


# ─── LANGUAGE ─────────────────────────────────────────────────
def language(lang: str) -> View:
    m = Msg()
    m.header("language", t("lang_title", lang))
    m.text(t("lang_intro", lang)).nl(2)
    for code, name in LANGS.items():
        marker = "ok" if code == lang else "dot"
        m.emoji(marker).space().text(f"{lang_flag(code)} {name}").nl()

    codes = list(LANGS.keys())
    rows = []
    for index in range(0, len(codes), 2):
        rows.append([
            btn(f"{lang_flag(code)} {LANGS[code]}", f"lang:{code}")
            for code in codes[index:index + 2]
        ])
    rows.append(home_row(lang))
    return View.of(m, kb(*rows))


# ─── HELP / TERMS / API ───────────────────────────────────────
def help_screen(lang: str, is_admin: bool = False) -> View:
    m = Msg()
    m.header("help", t("help_title", lang))
    m.text(t("help_steps", lang)).nl(2)
    m.bold(t("start_commands", lang)).nl()
    for command, emoji_name, description in commands.listing(
            lang, include_admin=is_admin):
        m.emoji(emoji_name).space().code(command).text(f" — {description}").nl()
    return View.of(m, kb(
        [btn(t("btn_products", lang), "nav:products", emoji_name="products"),
         btn(t("terms_title", lang), "nav:terms", emoji_name="terms")],
        home_row(lang),
    ))


def terms(lang: str) -> View:
    m = Msg()
    m.header("terms", t("terms_title", lang))
    m.text(store.setting("terms") or t("terms_default", lang))
    return View.of(m, kb(
        [btn(t("btn_support", lang), "nav:support", emoji_name="support")],
        home_row(lang),
    ))


def api_screen(lang: str) -> View:
    m = Msg()
    m.header("lock", t("api_title", lang))
    if config.STORE_API_KEY:
        m.text(t("api_on", lang)).nl(2)
        m.emoji("link").space().code("GET /api/catalog").nl()
        m.emoji("key").space().code("X-API-Key: <your key>").nl()
        note = store.setting("api_note")
        if note:
            m.nl().italic(note)
    else:
        m.text(t("api_off", lang))
    rows = []
    if store.support_url():
        rows.append([btn(t("btn_contact_support", lang),
                         url=store.support_url(), emoji_name="support")])
    rows.append([btn(t("btn_products", lang), "nav:products",
                     emoji_name="catalog")])
    return View.of(m, kb(*rows))


# ─── GATES ────────────────────────────────────────────────────
def force_join(lang: str) -> View:
    channel = config.FORCE_JOIN_NAME or "our channel"
    m = Msg()
    m.header("bell", t("join_title", lang))
    m.text(t("join_intro", lang, channel=channel))
    rows = []
    if config.FORCE_JOIN_LINK:
        rows.append([btn(t("btn_join_channel", lang),
                         url=config.FORCE_JOIN_LINK, emoji_name="link",
                         style="success")])
    rows.append([btn(t("btn_joined", lang), "nav:joined", emoji_name="ok")])
    return View.of(m, kb(*rows), poster=config.BANNER_START)


def banned(lang: str, reason: str) -> View:
    m = Msg()
    m.header("ban", t("banned_title", lang))
    m.text(t("banned_body", lang, reason=reason or "—"))
    rows = []
    if store.support_url():
        rows.append([btn(t("btn_contact_support", lang),
                         url=store.support_url(), emoji_name="support")])
    return View.of(m, kb(*rows))


def simple(emoji_name: str, title: str, body: str = "",
           lang: str = "en", buttons: dict | None = None) -> View:
    m = Msg()
    m.header(emoji_name, title)
    if body:
        m.text(body)
    return View.of(m, buttons if buttons is not None
                   else kb(home_row(lang)))
