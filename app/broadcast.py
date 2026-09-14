"""
app/broadcast.py — posts that leave the customer's chat.

Three public posts (wallet funded, new order, almost gone), restock alerts to
subscribed customers, and plain notifications to admins. Everything here is
best-effort: a missing LOG_CHANNEL_ID or a bot that is not an admin in the
channel must never break a purchase, so failures are logged and swallowed.
"""

import asyncio
import logging

from . import config, emoji as emo, store, tg, util
from .lang import t
from .msg import Msg, u16
from .payments import label as method_label
from .view import btn, kb

logger = logging.getLogger(__name__)

# Delay between DMs in a fan-out, to stay under Telegram's ~30 msg/s limit.
FANOUT_DELAY = 0.06


async def _deep_link(payload: str = "") -> str:
    link = await tg.bot_link()
    if not link:
        return ""
    return f"{link}?start={payload}" if payload else link


async def _post(view_text: str, entities: list, keyboard: dict | None,
                poster: str | None) -> bool:
    if not config.LOG_CHANNEL_ID:
        return False
    if poster and u16(view_text) <= tg.CAPTION_LIMIT:
        data = await tg.send_photo(config.LOG_CHANNEL_ID, poster, view_text,
                                   entities, keyboard)
        if data.get("ok"):
            return True
    data = await tg.send_message(config.LOG_CHANNEL_ID, view_text, entities,
                                 keyboard)
    if not data.get("ok"):
        logger.warning("channel post failed: %s", data.get("description"))
    return bool(data.get("ok"))


# ─── WALLET FUNDED ────────────────────────────────────────────
def build_wallet_funded(topup: dict, lang: str = "en") -> tuple[str, list]:
    m = Msg()
    m.emoji("money").space().bold(t("bc_funded_title", lang))
    m.space().emoji("party").nl()
    m.rule()
    m.kvline("money", t("bc_funded_amount", lang),
             util.fmt_money(topup.get("amount")))
    m.kvline("id", t("bc_funded_customer", lang),
             util.mask_user_id(topup.get("user_id")))
    m.kvline("bank", t("bc_funded_method", lang),
             method_label(topup.get("method")))
    m.nl()
    m.emoji("spark").space().italic(t("bc_funded_line1", lang)).nl()
    m.emoji("clock").space().italic(t("bc_funded_line2", lang))
    return m.build()


async def wallet_funded(topup: dict):
    lang = "en"          # public posts stay in one language
    text, entities = build_wallet_funded(topup, lang)
    link = await _deep_link()
    keyboard = kb([btn(t("btn_visit_bot", lang), url=link,
                       emoji_name="rocket")]) if link else None
    await _post(text, entities, keyboard, config.POSTER_WALLET_FUNDED)


# ─── NEW ORDER ────────────────────────────────────────────────
def build_new_order(order: dict, lang: str = "en") -> tuple[str, list]:
    m = Msg()
    m.bar_header(t("bc_order_title", lang), trailing_emoji="fire")
    m.emoji("clipboard").space().bold(f"{t('bc_order_product', lang)}: ")
    m.text(emo.BAR).bold(order.get("product_name") or "—").nl()
    m.kvline("money", t("bc_order_qty", lang), order.get("qty") or 1)
    m.kvline("money", t("bc_order_paid", lang),
             util.fmt_money(order.get("total")))
    m.kvline("id", t("bc_order_customer", lang),
             util.mask_user_id(order.get("user_id")))
    m.nl()
    m.emoji("spark").space().italic(t("bc_order_line1", lang)).nl()
    m.emoji("party").space().italic(t("bc_order_line2", lang))
    return m.build()


async def new_order(order: dict):
    lang = "en"
    text, entities = build_new_order(order, lang)
    link = await _deep_link(f"p_{order.get('pid')}")
    keyboard = kb([btn(t("btn_buy_now", lang), url=link,
                       emoji_name="products")]) if link else None

    product = store.product_get(order.get("pid")) or {}
    poster = product.get("image") or config.POSTER_NEW_ORDER
    await _post(text, entities, keyboard, poster)


# ─── ALMOST GONE ──────────────────────────────────────────────
def build_almost_gone(product: dict, count: int,
                      lang: str = "en") -> tuple[str, list]:
    m = Msg()
    m.rule()
    m.emoji("fire").space().bold(t("bc_gone_title", lang)).nl()
    m.rule()
    m.emoji(product.get("emoji") or "box").space()
    m.bold(product.get("name") or "—").nl()
    m.emoji("low").space().text(t("bc_gone_left", lang, n=count)).nl()
    m.emoji("price").space().bold(t("bc_gone_price", lang)).space()
    m.bold(util.fmt_money_short(product.get("price"))).nl()
    m.nl()
    m.italic(t("bc_gone_final", lang))
    return m.build()


async def almost_gone(product: dict, count: int):
    lang = "en"
    text, entities = build_almost_gone(product, count, lang)
    link = await _deep_link(f"p_{product.get('id')}")
    keyboard = kb([btn(util.clip(product.get("name") or "—", 40), url=link,
                       emoji_name=product.get("emoji") or "box",
                       style="success")]) if link else None
    poster = product.get("image") or config.POSTER_ALMOST_GONE
    await _post(text, entities, keyboard, poster)


# ─── RESTOCK ──────────────────────────────────────────────────
def build_restocked(product: dict, added: int,
                    lang: str = "en") -> tuple[str, list]:
    m = Msg()
    m.emoji("party").space().bold(t("bc_restock_title", lang)).nl()
    m.rule()
    m.emoji(product.get("emoji") or "box").space()
    m.bold(product.get("name") or "—").nl()
    m.emoji("stock").space().text(t("bc_restock_line", lang, n=added)).nl()
    m.kvline("price", t("bc_gone_price", lang),
             util.fmt_money_short(product.get("price")))
    m.nl()
    m.italic(t("bc_restock_hurry", lang))
    return m.build()


async def restocked(product: dict, added: int):
    lang = "en"
    text, entities = build_restocked(product, added, lang)
    link = await _deep_link(f"p_{product.get('id')}")
    keyboard = kb([btn(t("btn_buy_now", lang), url=link,
                       emoji_name="products")]) if link else None
    poster = product.get("image") or config.POSTER_NEW_ORDER
    await _post(text, entities, keyboard, poster)


async def alert_restock_subscribers(product: dict, added: int):
    """DM everyone who did not press Stop Alerts for this product."""
    pid = product.get("id")
    audience = store.alert_audience(pid)
    if not audience:
        return 0

    sent = 0
    for user_id in audience:
        lang = store.user_lang(user_id)
        m = Msg()
        m.header("bell", t("bc_restock_title", lang))
        m.emoji(product.get("emoji") or "box").space()
        m.bold(product.get("name") or "—").nl()
        m.emoji("stock").space().text(t("bc_restock_line", lang, n=added)).nl()
        m.kvline("price", t("pd_unit_price", lang),
                 util.fmt_money(product.get("price")))
        text, entities = m.build()
        keyboard = kb(
            [btn(t("btn_buy_now", lang), f"p:{pid}", emoji_name="products",
                 style="success")],
            [btn(t("btn_stop_alerts", lang), f"pa:{pid}", emoji_name="bell")],
        )
        data = await tg.send_message(user_id, text, entities, keyboard)
        if data.get("ok"):
            sent += 1
        await asyncio.sleep(FANOUT_DELAY)
    logger.info("restock alert sent to %d/%d users", sent, len(audience))
    return sent


# ─── ADMIN NOTIFICATIONS ──────────────────────────────────────
async def to_admins(builder, keyboard: dict | None = None):
    """builder(Msg) fills a message; it is sent to every admin."""
    for admin_id in config.ADMINS:
        m = Msg()
        builder(m)
        text, entities = m.build()
        await tg.send_message(admin_id, text, entities, keyboard)


async def admin_manual_topup(topup: dict, user_rec: dict):
    def build(m: Msg):
        m.header("warn", "Manual payment claimed")
        m.emoji("user").space().bold("User: ")
        m.text(f"{util.user_handle(user_rec)} ({user_rec.get('id')})").nl()
        m.kvline("money", "Amount", util.fmt_money(topup.get("amount")))
        m.kvline("bank", "Method", method_label(topup.get("method")))
        m.emoji("sku").space().bold("Top-up: ").code(topup.get("id")).nl(2)
        m.italic("Approve to credit the wallet, or decline it.")

    keyboard = kb(
        [btn("Approve", f"ad:top:ok:{topup['id']}", emoji_name="ok",
             style="success")],
        [btn("Decline", f"ad:top:no:{topup['id']}", emoji_name="no",
             style="danger")],
    )
    await to_admins(build, keyboard)


async def admin_manual_delivery(order: dict, user_rec: dict):
    def build(m: Msg):
        m.header("clock", "Manual delivery needed")
        m.emoji("box").space().bold("Product: ")
        m.text(order.get("product_name") or "—").nl()
        m.kvline("qty", "Qty", order.get("qty") or 1)
        m.kvline("money", "Paid", util.fmt_money(order.get("total")))
        m.emoji("user").space().bold("User: ")
        m.text(f"{util.user_handle(user_rec)} ({user_rec.get('id')})").nl()
        m.emoji("sku").space().bold("Order: ").code(order.get("id")).nl(2)
        m.italic("Send the item to the user, then mark it delivered.")

    keyboard = kb(
        [btn("Mark delivered", f"ad:ord:done:{order['id']}", emoji_name="ok",
             style="success")],
    )
    await to_admins(build, keyboard)


async def admin_low_stock(product: dict, count: int):
    def build(m: Msg):
        m.header("low", "Low stock")
        m.emoji(product.get("emoji") or "box").space()
        m.bold(product.get("name") or "—").nl()
        m.kvline("stock", "Left", count)
        m.kvline("sku", "SKU", product.get("sku") or "—")

    await to_admins(build)


async def dm(user_id, builder, keyboard: dict | None = None) -> bool:
    m = Msg()
    builder(m)
    text, entities = m.build()
    data = await tg.send_message(user_id, text, entities, keyboard)
    return bool(data.get("ok"))
