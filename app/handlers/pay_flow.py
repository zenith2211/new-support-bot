"""
app/handlers/pay_flow.py — top-ups and invoices.

Shared by the Wallet screen ("just add funds") and by the low-balance path
("pay the shortfall and get the item"). The only difference between the two is
the intent stored on the top-up: when it names a product, the item is bought
automatically the moment the payment confirms.
"""

import logging

from .. import broadcast, config, payments, screens, shop, store, util
from ..lang import t
from ..msg import Msg
from ..view import View, btn, kb
from .base import Ctx, error, send_new, show, toast

logger = logging.getLogger(__name__)


async def start_topup(ctx: Ctx, method_key: str, amount: float,
                      intent_pid: str = "", intent_qty: int = 0,
                      intent_coupon: str = "") -> bool:
    """Create the invoice and show it. Returns False when it could not start."""
    method = payments.get(method_key)
    if not method:
        await error(ctx, "pay_none")
        return False

    amount = round(max(float(amount), store.min_topup()), 6)
    if amount > config.MAX_TOPUP:
        await error(ctx, "topup_too_big", max=util.fmt_money(config.MAX_TOPUP))
        return False

    topup = store.topup_create(
        user_id=ctx.user_id,
        amount=amount,
        method=method.key,
        intent_pid=intent_pid,
        intent_qty=intent_qty,
        intent_coupon=intent_coupon,
    )

    description = f"{store.store_name()} top-up"
    if intent_pid:
        product = store.product_get(intent_pid) or {}
        description = product.get("name") or description

    await toast(ctx, ctx.s("invoice_checking"))
    created = await payments.create_invoice(method, topup, description)

    if not created.get("ok"):
        store.topups.patch(topup["id"], status="cancelled")
        logger.warning("invoice failed for %s: %s", topup["id"],
                       created.get("error"))
        await show(ctx, _gateway_error(ctx, created.get("error", "")))
        return False

    store.topups.patch(
        topup["id"],
        provider_ref=created.get("provider_ref") or "",
        checkout_url=created.get("checkout_url") or "",
    )
    topup = store.topup_get(topup["id"])

    manual_note = ""
    if method.kind == "manual":
        manual_note = store.setting("manual_pay_note") or _manual_default(amount)

    view = screens.invoice(topup, ctx.lang, method.label,
                           created.get("checkout_url") or "", manual_note)
    await show(ctx, view)
    return True


def _manual_default(amount: float) -> str:
    target = config.BINANCE_PAY_ID or store.setting("manual_pay_target") or ""
    if target:
        return f"Send {util.fmt_money(amount)} to {target}."
    return f"Send {util.fmt_money(amount)} using the details support gives you."


def _gateway_error(ctx: Ctx, detail: str) -> View:
    m = Msg()
    m.header("warn", ctx.s("err_generic"))
    m.text(ctx.s("pay_none")).nl()
    if detail:
        m.nl().italic(util.clip(detail, 200))
    rows = [[btn(ctx.s("btn_gift"), "nav:gift", emoji_name="gift")]]
    if store.support_url():
        rows.append([btn(ctx.s("btn_contact_support"), url=store.support_url(),
                         emoji_name="support")])
    rows.append([btn(ctx.s("btn_wallet"), "nav:wallet", emoji_name="wallet")])
    return View.of(m, kb(*rows))


# ─── "I HAVE PAID" ────────────────────────────────────────────
async def confirm_paid(ctx: Ctx, topup_id: str):
    topup = store.topup_get(topup_id)
    if not topup or str(topup.get("user_id")) != str(ctx.user_id):
        await error(ctx, "err_not_found")
        return

    if topup.get("status") == "paid":
        await toast(ctx, ctx.s("wallet_funded_dm",
                               amount=util.fmt_money(topup["amount"]),
                               balance=util.fmt_money(ctx.balance)))
        await show(ctx, screens.wallet(ctx.user, ctx.lang))
        return

    method = payments.get(topup.get("method"))
    if not method:
        await error(ctx, "err_not_found")
        return

    await toast(ctx, ctx.s("invoice_checking"))

    if method.kind == "manual":
        store.topups.patch(topup_id, status="pending")
        await broadcast.admin_manual_topup(topup, ctx.user)
        await show(ctx, screens.simple(
            "clock", ctx.s("invoice_title"),
            ctx.s("invoice_sent_to_support"), ctx.lang,
            kb([btn(ctx.s("btn_wallet"), "nav:wallet", emoji_name="wallet")]),
        ))
        return

    status = await payments.check_invoice(method, topup)
    if status == payments.PENDING:
        await toast(ctx, ctx.s("invoice_not_paid"), alert=True)
        return
    if status == payments.FAILED:
        store.topups.patch(topup_id, status="cancelled")
        await show(ctx, screens.simple(
            "no", ctx.s("cancelled"), "", ctx.lang,
            kb([btn(ctx.s("btn_topup"), "w:top", emoji_name="plus")],
               [btn(ctx.s("btn_wallet"), "nav:wallet", emoji_name="wallet")]),
        ))
        return

    await settle(ctx, topup_id)


async def settle(ctx: Ctx | None, topup_id: str):
    """Credit a paid top-up, then run its intent (buy the pending item)."""
    topup = store.topup_mark_paid(topup_id)
    if not topup:
        return

    user_id = topup["user_id"]
    lang = store.user_lang(user_id)
    balance = store.balance_of(user_id)

    try:
        await broadcast.wallet_funded(topup)
    except Exception as exc:                     # noqa: BLE001
        logger.warning("wallet funded post failed: %s", exc)

    order, err = await shop.credit_and_continue(topup, lang)

    if order:
        target = ctx.chat_id if ctx else user_id
        message = ctx.message if ctx else None
        await shop.deliver(target, order, lang, message)
        await shop.after_sale(order)
        return

    # Plain top-up, or the item slipped away between paying and delivering.
    view = screens.simple(
        "party", t("wallet_title", lang),
        t("wallet_funded_dm", lang,
          amount=util.fmt_money(topup["amount"]),
          balance=util.fmt_money(balance)),
        lang,
        kb([btn(t("btn_products", lang), "nav:products",
                emoji_name="products")],
           [btn(t("btn_wallet", lang), "nav:wallet", emoji_name="wallet")]),
    )
    if ctx:
        await show(ctx, view)
    else:
        await send_new(Ctx(chat_id=user_id, user_id=user_id, lang=lang), view)

    if err:
        # The money is safely in the wallet; only the follow-on buy failed
        # (usually the last unit sold while the invoice was open).
        logger.info("top-up %s credited but its intent failed: %s",
                    topup_id, err)


async def cancel(ctx: Ctx, topup_id: str):
    topup = store.topup_get(topup_id)
    if not topup or str(topup.get("user_id")) != str(ctx.user_id):
        await error(ctx, "err_not_found")
        return
    if topup.get("status") == "pending":
        method = payments.get(topup.get("method"))
        if method:
            await payments.close_invoice(method, topup)
        store.topups.patch(topup_id, status="cancelled")
    await toast(ctx, ctx.s("cancelled"))
    await show(ctx, screens.wallet(ctx.user, ctx.lang))


# ─── ADMIN APPROVAL OF MANUAL TOP-UPS ─────────────────────────
async def admin_approve(ctx: Ctx, topup_id: str, approve: bool):
    topup = store.topup_get(topup_id)
    if not topup:
        await toast(ctx, "Top-up not found", alert=True)
        return

    if not approve:
        store.topups.patch(topup_id, status="cancelled")
        await toast(ctx, "Declined")
        lang = store.user_lang(topup["user_id"])
        await broadcast.dm(
            topup["user_id"],
            lambda m: m.header("no", t("cancelled", lang)).text(
                t("invoice_not_paid", lang)),
        )
        return

    if topup.get("credited"):
        await toast(ctx, "Already credited", alert=True)
        return

    await settle(None, topup_id)
    await toast(ctx, "Credited")
