"""
app/handlers/shop_flow.py — browsing and buying.

Categories -> category -> product -> confirm -> delivered, with the
low-balance detour that funds the wallet and then finishes the purchase.
"""

import logging

from .. import screens, shop, state, store, util
from ..view import btn, kb
from .base import Ctx, error, show, toast
from . import pay_flow

logger = logging.getLogger(__name__)


# ─── BROWSING ─────────────────────────────────────────────────
async def categories(ctx: Ctx):
    await show(ctx, screens.categories(ctx.lang))


async def category(ctx: Ctx, cat_id: str):
    cat = store.categories.get(cat_id)
    if not cat or not cat.get("enabled", True):
        await error(ctx, "err_not_found")
        await categories(ctx)
        return
    await show(ctx, screens.category(cat, ctx.lang))


async def product(ctx: Ctx, pid: str, qty: int = 1):
    record = store.product_get(pid)
    if not record or not record.get("enabled", True):
        await error(ctx, "err_not_found")
        await categories(ctx)
        return

    coupon_code = state.get_coupon(ctx.user_id, pid)
    coupon = {"code": coupon_code} if coupon_code else None
    await show(ctx, screens.product(
        record, ctx.lang, ctx.balance, qty=qty, coupon=coupon,
        alerts_on=store.alerts_enabled(ctx.user_id, pid),
    ))


async def delivery_note(ctx: Ctx, pid: str):
    record = store.product_get(pid)
    if not record:
        await error(ctx, "err_not_found")
        return
    await show(ctx, screens.delivery_note(record, ctx.lang))


async def toggle_alerts(ctx: Ctx, pid: str):
    record = store.product_get(pid)
    if not record:
        await error(ctx, "err_not_found")
        return
    enabled = store.toggle_alerts(ctx.user_id, pid)
    await toast(ctx, ctx.s("alerts_on" if enabled else "alerts_off"))
    await product(ctx, pid)


# ─── QUANTITY ─────────────────────────────────────────────────
async def prompt_qty(ctx: Ctx, pid: str):
    record = store.product_get(pid)
    if not record:
        await error(ctx, "err_not_found")
        return

    ok, _err, limits = shop.check_qty(record, int(record.get("min_qty") or 1))
    state.set_prompt(ctx.user_id, "qty", pid=pid)
    await toast(ctx)

    body = ctx.s("err_qty_range", min=limits["min"],
                 max=min(limits["max"], max(limits["available"], limits["min"])))
    await show(ctx, screens.simple(
        "star", ctx.s("btn_custom"), body, ctx.lang,
        kb([btn(ctx.s("btn_no_cancel"), f"p:{pid}", emoji_name="no")]),
    ))


async def on_qty_text(ctx: Ctx, pid: str, text: str):
    qty = util.parse_qty(text)
    if qty is None:
        await error(ctx, "err_bad_number", alert=False)
        return
    state.clear_prompt(ctx.user_id)
    await confirm(ctx, pid, qty)


# ─── COUPON ───────────────────────────────────────────────────
async def prompt_coupon(ctx: Ctx, pid: str):
    if not store.product_get(pid):
        await error(ctx, "err_not_found")
        return
    state.set_prompt(ctx.user_id, "coupon", pid=pid)
    await toast(ctx)
    await show(ctx, screens.simple(
        "coupon", ctx.s("coupon_title"), ctx.s("coupon_prompt"), ctx.lang,
        kb([btn(ctx.s("btn_no_cancel"), f"p:{pid}", emoji_name="no")]),
    ))


async def on_coupon_text(ctx: Ctx, pid: str, text: str):
    record = store.product_get(pid)
    if not record:
        state.clear_prompt(ctx.user_id)
        await error(ctx, "err_not_found", alert=False)
        return

    code = util.normalize_code(text)
    subtotal = float(record.get("price") or 0.0) * max(
        int(record.get("min_qty") or 1), 1)
    coupon, err, _discount = store.coupon_check(code, pid, subtotal)
    if not coupon:
        await error(ctx, err or "coupon_unknown", alert=False)
        return

    state.clear_prompt(ctx.user_id)
    state.set_coupon(ctx.user_id, pid, coupon["code"])
    await product(ctx, pid)


async def clear_coupon(ctx: Ctx, pid: str):
    state.clear_coupon(ctx.user_id, pid)
    await toast(ctx, ctx.s("coupon_cleared"))
    await product(ctx, pid)


# ─── CONFIRM & BUY ────────────────────────────────────────────
async def confirm(ctx: Ctx, pid: str, qty: int):
    record = store.product_get(pid)
    if not record or not record.get("enabled", True):
        await error(ctx, "err_not_found")
        return

    ok, err, limits = shop.check_qty(record, qty)
    if not ok:
        if err == "err_no_stock":
            await toast(ctx, ctx.s("err_no_stock"), alert=True)
            await product(ctx, pid)
            return
        if err == "err_stock_short":
            await error(ctx, err, n=limits["available"])
        else:
            await error(ctx, err, min=limits["min"], max=limits["max"])
        return

    coupon_code = state.get_coupon(ctx.user_id, pid)
    coupon = {"code": coupon_code} if coupon_code else None
    await show(ctx, screens.confirm(record, ctx.lang, qty, ctx.balance, coupon))


async def buy(ctx: Ctx, pid: str, qty: int, coupon_code: str = ""):
    record = store.product_get(pid)
    if not record:
        await error(ctx, "err_not_found")
        return

    coupon_code = coupon_code or state.get_coupon(ctx.user_id, pid)
    priced = shop.quote(pid, qty, coupon_code)

    if ctx.balance + 1e-9 < priced["total"]:
        await toast(ctx)
        await show(ctx, screens.low_balance(
            record, ctx.lang, qty, ctx.balance, priced["total"]))
        return

    order, err = await shop.checkout(ctx.user_id, pid, qty, coupon_code)
    if not order:
        if err == "low_balance":
            await show(ctx, screens.low_balance(
                record, ctx.lang, qty, ctx.balance, priced["total"]))
            return
        if err == "err_no_stock":
            await toast(ctx, ctx.s("err_no_stock"), alert=True)
            await product(ctx, pid)
            return
        await error(ctx, err or "err_generic")
        return

    state.clear_coupon(ctx.user_id, pid)
    await toast(ctx, ctx.s("delivered_title"))
    await shop.deliver(ctx.chat_id, order, ctx.lang, ctx.message)
    await shop.after_sale(order)


# ─── PAY THE SHORTFALL ────────────────────────────────────────
async def pay_shortfall(ctx: Ctx, pid: str, qty: int):
    record = store.product_get(pid)
    if not record:
        await error(ctx, "err_not_found")
        return
    coupon_code = state.get_coupon(ctx.user_id, pid)
    priced = shop.quote(pid, qty, coupon_code)
    await show(ctx, screens.pay_methods(
        record, ctx.lang, qty, ctx.balance, priced["total"]))


async def start_payment(ctx: Ctx, method_key: str, pid: str, qty: int):
    record = store.product_get(pid)
    if not record:
        await error(ctx, "err_not_found")
        return

    coupon_code = state.get_coupon(ctx.user_id, pid)
    priced = shop.quote(pid, qty, coupon_code)
    shortfall = max(round(priced["total"] - ctx.balance, 6), 0.0)
    amount = max(shortfall, store.min_topup())

    await pay_flow.start_topup(
        ctx, method_key, amount,
        intent_pid=pid, intent_qty=qty, intent_coupon=coupon_code,
    )


# ─── DEEP LINK ────────────────────────────────────────────────
async def open_from_payload(ctx: Ctx, payload: str) -> bool:
    """Handle /start p_<pid>. Returns True when the payload was consumed."""
    if not payload.startswith("p_"):
        return False
    pid = payload[2:]
    if not store.product_get(pid):
        return False
    await product(ctx, pid)
    return True
