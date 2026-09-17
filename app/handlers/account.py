"""
app/handlers/account.py — everything that is not the catalog.

Start screen, wallet and top-ups, orders, gift codes, support, profile,
language, help and terms.
"""

import logging

from .. import broadcast, config, payments, screens, shop, state, store, tg, \
    util
from ..lang import LANGS, lang_name, t
from ..view import btn, kb
from .base import Ctx, error, send_new, show, toast
from . import pay_flow, shop_flow

logger = logging.getLogger(__name__)


# ─── START ────────────────────────────────────────────────────
async def start(ctx: Ctx, payload: str = ""):
    if payload:
        if await shop_flow.open_from_payload(ctx, payload):
            return
        if payload.startswith("gift_"):
            await redeem_gift(ctx, payload[5:])
            return
        _apply_referral(ctx, payload)

    view = screens.start(ctx.tg_user, ctx.lang, is_admin=ctx.is_admin)
    await send_new(ctx, view)


def _apply_referral(ctx: Ctx, payload: str):
    if not payload.startswith("ref_"):
        return
    referrer = payload[4:]
    if not referrer.isdigit() or str(referrer) == str(ctx.user_id):
        return
    me = ctx.user
    if me.get("referrer") or not store.users.get(referrer):
        return
    store.users.patch(ctx.user_id, referrer=int(referrer))
    inviter = store.users.get(referrer) or {}
    store.users.patch(referrer, referrals=int(inviter.get("referrals") or 0) + 1)
    if config.REFERRAL_BONUS > 0:
        store.credit(referrer, config.REFERRAL_BONUS, kind="topup")


async def home(ctx: Ctx):
    await toast(ctx)
    view = screens.start(ctx.tg_user, ctx.lang, is_admin=ctx.is_admin)
    await show(ctx, view)


async def close(ctx: Ctx):
    await toast(ctx)
    if ctx.message:
        await tg.delete_message(ctx.chat_id, ctx.message["message_id"])


# ─── WALLET ───────────────────────────────────────────────────
async def wallet(ctx: Ctx):
    await show(ctx, screens.wallet(ctx.user, ctx.lang))


async def topup_menu(ctx: Ctx):
    """Add funds, step 1: pick the payment method (matching the reference
    flow, where the method is chosen before the amount)."""
    await toast(ctx)
    await show(ctx, screens.topup_methods(ctx.lang, ctx.balance))


async def topup_pick_amount(ctx: Ctx, method_key: str):
    """Add funds, step 2: pick the amount for the chosen method."""
    if not payments.get(method_key):
        await error(ctx, "pay_none")
        return
    await toast(ctx)
    await show(ctx, screens.topup_amounts(ctx.lang, ctx.balance, method_key))


async def topup_custom(ctx: Ctx, method_key: str = ""):
    state.set_prompt(ctx.user_id, "topup", method=method_key)
    await toast(ctx)
    await show(ctx, screens.simple(
        "plus", ctx.s("topup_title"), ctx.s("topup_custom_prompt"), ctx.lang,
        kb([btn(ctx.s("btn_no_cancel"), "nav:wallet", emoji_name="no")]),
    ))


def _amount_error(ctx: Ctx, amount: float | None) -> str:
    if amount is None or amount <= 0:
        return "err_bad_number"
    if amount < store.min_topup():
        return "topup_too_small"
    if amount > config.MAX_TOPUP:
        return "topup_too_big"
    return ""


async def on_topup_text(ctx: Ctx, text: str, method_key: str = ""):
    amount = util.parse_amount(text)
    problem = _amount_error(ctx, amount)
    if problem:
        await error(ctx, problem, alert=False,
                    min=util.fmt_money(store.min_topup()),
                    max=util.fmt_money(config.MAX_TOPUP))
        return
    state.clear_prompt(ctx.user_id)
    if method_key and payments.get(method_key):
        await pay_flow.start_topup(ctx, method_key, amount)
        return
    await send_new(ctx, screens.topup_methods(ctx.lang, ctx.balance))


async def topup_method(ctx: Ctx, method_key: str, amount: float):
    problem = _amount_error(ctx, amount)
    if problem:
        await error(ctx, problem,
                    min=util.fmt_money(store.min_topup()),
                    max=util.fmt_money(config.MAX_TOPUP))
        return
    await pay_flow.start_topup(ctx, method_key, amount)


async def topup_with_amount(ctx: Ctx, amount: float):
    """`/topup 5` — amount known, method still to pick."""
    problem = _amount_error(ctx, amount)
    if problem:
        await error(ctx, problem, alert=False,
                    min=util.fmt_money(store.min_topup()),
                    max=util.fmt_money(config.MAX_TOPUP))
        return
    await send_new(ctx, screens.topup_methods(ctx.lang, ctx.balance, amount))


async def history(ctx: Ctx):
    await toast(ctx)
    await show(ctx, screens.wallet_history(ctx.user_id, ctx.lang))


# ─── WALLET TRANSFER ──────────────────────────────────────────
async def transfer_prompt(ctx: Ctx):
    state.set_prompt(ctx.user_id, "transfer")
    await toast(ctx)
    m_view = screens.simple(
        "plus", ctx.s("transfer_title"),
        f"{ctx.s('wallet_balance')}: {util.fmt_money(ctx.balance)}\n"
        f"{ctx.s('wallet_customer_id')}: "
        f"{store.customer_id(ctx.user_id)}\n\n"
        f"{ctx.s('transfer_prompt')}",
        ctx.lang,
        kb([btn(ctx.s("btn_no_cancel"), "nav:wallet", emoji_name="no")]),
    )
    await show(ctx, m_view)


async def on_transfer_text(ctx: Ctx, text: str):
    parts = str(text).split()
    if len(parts) < 2:
        await error(ctx, "transfer_bad_format", alert=False)
        return
    amount = util.parse_amount(parts[-1])
    code = " ".join(parts[:-1])
    if amount is None or amount <= 0:
        await error(ctx, "transfer_bad_format", alert=False)
        return

    target = store.find_by_customer_id(code)
    if not target:
        await error(ctx, "transfer_no_user", alert=False)
        return

    ok, err = store.transfer(ctx.user_id, target["id"], amount)
    if not ok:
        await error(ctx, err or "err_generic", alert=False)
        return

    state.clear_prompt(ctx.user_id)
    sender_name = store.customer_id(ctx.user_id)
    await send_new(ctx, screens.simple(
        "party", ctx.s("transfer_title"),
        ctx.s("transfer_ok",
              amount=util.fmt_money(amount),
              who=store.customer_id(target["id"]),
              balance=util.fmt_money(ctx.balance)),
        ctx.lang,
        kb([btn(ctx.s("btn_wallet"), "nav:wallet", emoji_name="wallet")]),
    ))

    their_lang = store.user_lang(target["id"])
    await broadcast.dm(
        target["id"],
        lambda m: m.header("party", t("wallet_title", their_lang)).text(
            t("transfer_got", their_lang,
              amount=util.fmt_money(amount),
              who=sender_name,
              balance=util.fmt_money(store.balance_of(target["id"])))),
    )


# ─── ORDERS ───────────────────────────────────────────────────
async def orders(ctx: Ctx):
    await show(ctx, screens.orders(ctx.user_id, ctx.lang))


async def order_detail(ctx: Ctx, order_id: str):
    order = store.order_get(order_id)
    if not order or str(order.get("user_id")) != str(ctx.user_id):
        await error(ctx, "err_not_found")
        return
    await toast(ctx)
    await show(ctx, screens.order_detail(order, ctx.lang))


async def resend(ctx: Ctx, order_id: str):
    order = store.order_get(order_id)
    if not order or str(order.get("user_id")) != str(ctx.user_id):
        await error(ctx, "err_not_found")
        return
    await toast(ctx, ctx.s("delivered_title"))
    await shop.deliver(ctx.chat_id, order, ctx.lang, None)


# ─── GIFT CODES ───────────────────────────────────────────────
async def gift(ctx: Ctx):
    state.set_prompt(ctx.user_id, "gift")
    await show(ctx, screens.gift(ctx.lang, ctx.balance))


async def redeem_gift(ctx: Ctx, raw_code: str):
    code = util.normalize_code(raw_code)
    if not code:
        await error(ctx, "gift_unknown", alert=False)
        return

    amount, err = store.giftcode_redeem(code, ctx.user_id)
    if not amount:
        await error(ctx, err or "gift_unknown", alert=False)
        return

    state.clear_prompt(ctx.user_id)
    balance = ctx.balance

    topup = store.topup_create(
        user_id=ctx.user_id, amount=amount, method="gift",
        status="paid", credited=True, paid=util.now_ts(),
        provider_ref=code,
    )

    await send_new(ctx, screens.simple(
        "party", ctx.s("gift_title"),
        ctx.s("gift_ok", amount=util.fmt_money(amount),
              balance=util.fmt_money(balance)),
        ctx.lang,
        kb([btn(ctx.s("btn_products"), "nav:products", emoji_name="products")],
           [btn(ctx.s("btn_wallet"), "nav:wallet", emoji_name="wallet")]),
    ))

    try:
        await broadcast.wallet_funded(topup)
    except Exception as exc:                     # noqa: BLE001
        logger.warning("gift funded post failed: %s", exc)


def looks_like_gift_code(text: str) -> bool:
    """True when a plain message is an existing gift code, so users can paste
    one without opening the Gift screen first."""
    code = util.normalize_code(text)
    if len(code) < 4:
        return False
    return store.giftcodes.get(code) is not None


# ─── SUPPORT / PROFILE / LANGUAGE ─────────────────────────────
async def support(ctx: Ctx):
    await show(ctx, screens.support(ctx.lang))


async def profile(ctx: Ctx):
    await show(ctx, screens.profile(ctx.user, ctx.lang))


async def language(ctx: Ctx):
    await toast(ctx)
    await show(ctx, screens.language(ctx.lang))


async def set_language(ctx: Ctx, code: str):
    code = code[:2]
    if code not in LANGS:
        await error(ctx, "err_not_found")
        return
    store.user_set_lang(ctx.user_id, code)
    ctx.lang = code
    await toast(ctx, t("lang_set", code, name=lang_name(code)))
    await show(ctx, screens.language(code))
    await send_new(ctx, screens.start(ctx.tg_user, code, is_admin=ctx.is_admin))


async def help_screen(ctx: Ctx):
    await show(ctx, screens.help_screen(ctx.lang, is_admin=ctx.is_admin))


async def terms(ctx: Ctx):
    await show(ctx, screens.terms(ctx.lang))


async def api(ctx: Ctx):
    await toast(ctx)
    await show(ctx, screens.api_screen(ctx.lang))


async def whoami(ctx: Ctx):
    m_view = screens.simple(
        "id", ctx.s("profile_id"), str(ctx.user_id), ctx.lang,
        kb([btn(ctx.s("btn_profile"), "nav:profile", emoji_name="profile")]),
    )
    await send_new(ctx, m_view)


# ─── FORCE JOIN ───────────────────────────────────────────────
async def joined_check(ctx: Ctx):
    if not store.setting("force_join") or not config.FORCE_JOIN_CHATS:
        await home(ctx)
        return
    missing = await tg.missing_chats(config.FORCE_JOIN_CHATS, ctx.user_id)
    if not missing:
        await toast(ctx, ctx.s("btn_joined"))
        await home(ctx)
        return
    # Say which one is still outstanding, so "I have joined" is not a
    # dead end for someone who joined only the first of two.
    await toast(ctx, f"{ctx.s('join_not_yet')} "
                     f"({', '.join(str(c.get('name')) for c in missing)})",
                alert=True)
    await show(ctx, screens.force_join(ctx.lang, missing))
