"""
app/handlers/router.py — one entry point per update type.

Order of business for a message: identify the user, block bans, apply the
force-join gate, then try (in order) a slash command, a persistent-keyboard
label, an open prompt, a pasted gift code, and finally fall back to the start
screen.
"""

import logging

from .. import broadcast, commands, config, screens, state, store, tg, util
from ..lang import t
from .base import Ctx, ctx_from_callback, ctx_from_message, error, send_new, \
    toast
from . import account, admin, pay_flow, shop_flow

logger = logging.getLogger(__name__)

# Commands that work even when the force-join gate is closed.
GATE_FREE_COMMANDS = {"start", "support", "id", "help", "terms", "language"}


async def handle_update(update: dict):
    if "message" in update:
        await on_message(update["message"])
    elif "callback_query" in update:
        await on_callback(update["callback_query"])
    elif "my_chat_member" in update:
        await _on_membership(update["my_chat_member"])


async def _on_membership(event: dict):
    """A user blocking the bot is normal — just note it.

    Being added to a group is worth more: a private group has no username, so
    its numeric id is the only way to check membership or post logs, and there
    is no API that maps an invite link to an id. So when the bot joins a chat
    it reports the id to the admins, ready to paste into FORCE_JOIN_CHATS or
    LOG_CHANNEL_ID.
    """
    status = (event.get("new_chat_member") or {}).get("status")
    chat = event.get("chat") or {}
    chat_id = chat.get("id")

    if status == "kicked" and chat.get("type") == "private":
        logger.info("user %s blocked the bot", chat_id)
        return

    if chat.get("type") in ("group", "supergroup", "channel") \
            and status in ("member", "administrator"):
        title = chat.get("title") or "this chat"
        logger.info("added to %s %s (%s) as %s",
                    chat.get("type"), title, chat_id, status)
        if status != "administrator":
            note = ("Make the bot an ADMIN here — a plain member cannot "
                    "check who has joined, and force-join would let "
                    "everyone through.")
        else:
            note = "Admin rights confirmed — membership checks will work."
        try:
            await broadcast.admin_chat_id(chat_id, title, note)
        except Exception as exc:                 # noqa: BLE001
            logger.warning("could not report chat id: %s", exc)


# ─── GATES ────────────────────────────────────────────────────
async def _blocked(ctx: Ctx) -> bool:
    banned, reason = store.is_banned(ctx.user_id)
    if not banned:
        return False
    await send_new(ctx, screens.banned(ctx.lang, reason))
    return True


async def _gated(ctx: Ctx) -> bool:
    """True when the user must join one or more chats first."""
    if not store.setting("force_join") or not config.FORCE_JOIN_CHATS:
        return False
    if config.is_admin(ctx.user_id):
        return False
    missing = await tg.missing_chats(config.FORCE_JOIN_CHATS, ctx.user_id)
    if not missing:
        return False
    await send_new(ctx, screens.force_join(ctx.lang, missing))
    return True


# ─── MESSAGES ─────────────────────────────────────────────────
async def on_message(message: dict):
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return

    tg_user = message.get("from") or {}
    if not tg_user or tg_user.get("is_bot"):
        return

    store.user_upsert(tg_user)
    ctx = ctx_from_message(message)
    if await _blocked(ctx):
        return

    if ctx.is_admin:
        await commands.ensure_admin_menu(ctx.user_id, tg)
        # A photo from an admin is a poster to install.
        if message.get("photo"):
            if await admin.capture_poster(ctx, message):
                return
        # An admin forwarding a message that uses premium emoji is asking to
        # adopt those emoji — see admin.harvest_emoji.
        if message.get("forward_origin") or message.get("forward_from") \
                or message.get("forward_from_chat"):
            if await admin.harvest_emoji(ctx, message):
                return

    text = (message.get("text") or message.get("caption") or "").strip()

    if text.startswith("/"):
        await _on_command(ctx, text)
        return

    if await _gated(ctx):
        return

    # The persistent keyboard always wins: tapping Products while a prompt is
    # open should navigate, not be read as an answer to the prompt.
    routes = screens.reply_labels(ctx.lang)
    route = routes.get(text)
    if route:
        state.clear_prompt(ctx.user_id)
        await _navigate(ctx, route)
        return

    # Otherwise an open prompt owns the next message.
    prompt = state.get_prompt(ctx.user_id)
    if prompt:
        if await _on_prompt(ctx, prompt, text, message):
            return

    if text and account.looks_like_gift_code(text):
        await account.redeem_gift(ctx, text)
        return

    if text:
        await send_new(ctx, screens.start(ctx.tg_user, ctx.lang,
                                          is_admin=ctx.is_admin))


async def _on_command(ctx: Ctx, text: str):
    head, _, tail = text.partition(" ")
    command = head[1:].split("@")[0].lower()
    payload = tail.strip()

    if command not in GATE_FREE_COMMANDS and await _gated(ctx):
        return

    if command == "start":
        state.clear_prompt(ctx.user_id)
        await account.start(ctx, payload)
    elif command in ("products", "shop", "catalog"):
        await send_new(ctx, screens.categories(ctx.lang))
    elif command == "wallet":
        await send_new(ctx, screens.wallet(ctx.user, ctx.lang))
    elif command in ("topup", "deposit", "add"):
        if payload:
            amount = util.parse_amount(payload)
            if amount is None:
                await error(ctx, "err_bad_number", alert=False)
                return
            await account.topup_with_amount(ctx, amount)
            return
        await send_new(ctx, screens.topup_methods(ctx.lang, ctx.balance))
    elif command in ("orders", "order"):
        await send_new(ctx, screens.orders(ctx.user_id, ctx.lang))
    elif command in ("gift", "giftcode", "redeem"):
        if payload:
            await account.redeem_gift(ctx, payload)
            return
        await account.gift(ctx)
    elif command == "support":
        await send_new(ctx, screens.support(ctx.lang))
    elif command in ("profile", "me", "account"):
        await send_new(ctx, screens.profile(ctx.user, ctx.lang))
    elif command in ("language", "lang"):
        await send_new(ctx, screens.language(ctx.lang))
    elif command == "help":
        await send_new(ctx, screens.help_screen(ctx.lang,
                                                is_admin=ctx.is_admin))
    elif command == "terms":
        await send_new(ctx, screens.terms(ctx.lang))
    elif command in ("id", "myid"):
        await account.whoami(ctx)
    elif command in ("balance", "bal"):
        await send_new(ctx, screens.wallet(ctx.user, ctx.lang))
    elif command == "admin":
        await admin.panel(ctx)
    elif command in ("inventorylist", "inventory", "stocklist"):
        await admin.inventory_list(ctx)
    elif command == "cancel":
        state.clear_prompt(ctx.user_id)
        await send_new(ctx, screens.simple("no", ctx.s("cancelled"), "",
                                           ctx.lang))
    else:
        await send_new(ctx, screens.help_screen(ctx.lang,
                                                is_admin=ctx.is_admin))


async def _on_prompt(ctx: Ctx, prompt: dict, text: str,
                     message: dict) -> bool:
    mode = prompt["mode"]
    data = prompt["data"]

    if mode.startswith("ad_"):
        return await admin.handle_prompt(ctx, mode, data, text)

    if mode == "qty":
        await shop_flow.on_qty_text(ctx, data.get("pid", ""), text)
        return True
    if mode == "coupon":
        await shop_flow.on_coupon_text(ctx, data.get("pid", ""), text)
        return True
    if mode == "topup":
        await account.on_topup_text(ctx, text, data.get("method", ""))
        return True
    if mode == "gift":
        await account.redeem_gift(ctx, text)
        return True
    if mode == "transfer":
        await account.on_transfer_text(ctx, text)
        return True

    state.clear_prompt(ctx.user_id)
    return False


async def _navigate(ctx: Ctx, route: str):
    if route == "products":
        await send_new(ctx, screens.categories(ctx.lang))
    elif route == "wallet":
        await send_new(ctx, screens.wallet(ctx.user, ctx.lang))
    elif route == "orders":
        await send_new(ctx, screens.orders(ctx.user_id, ctx.lang))
    elif route == "gift":
        await account.gift(ctx)
    elif route == "support":
        await send_new(ctx, screens.support(ctx.lang))
    elif route == "profile":
        await send_new(ctx, screens.profile(ctx.user, ctx.lang))
    elif route == "language":
        await send_new(ctx, screens.language(ctx.lang))


# ─── CALLBACKS ────────────────────────────────────────────────
async def on_callback(cq: dict):
    tg_user = cq.get("from") or {}
    if not tg_user:
        return

    store.user_upsert(tg_user)
    ctx = ctx_from_callback(cq)
    data = cq.get("data") or ""

    if await _blocked(ctx):
        await toast(ctx, t("banned_title", ctx.lang), alert=True)
        return

    if data == "noop":
        await toast(ctx)
        return

    if data.startswith("ad:"):
        if await admin.handle_callback(ctx, data[3:]):
            return
        await toast(ctx)
        return

    if data != "nav:joined" and await _gated(ctx):
        await toast(ctx, t("join_not_yet", ctx.lang), alert=True)
        return

    try:
        await _route_callback(ctx, data)
    except Exception:
        logger.exception("callback failed: %s", data)
        await toast(ctx, t("err_generic", ctx.lang), alert=True)


async def _route_callback(ctx: Ctx, data: str):
    head, _, rest = data.partition(":")

    if head == "nav":
        await _nav(ctx, rest)
        return

    if head == "cat":
        await toast(ctx)
        await shop_flow.category(ctx, rest)
        return

    if head == "p":
        await toast(ctx)
        await shop_flow.product(ctx, rest)
        return

    if head == "pq":
        await shop_flow.prompt_qty(ctx, rest)
        return

    if head == "pc":
        await shop_flow.prompt_coupon(ctx, rest)
        return

    if head == "pcx":
        await shop_flow.clear_coupon(ctx, rest)
        return

    if head == "pa":
        await shop_flow.toggle_alerts(ctx, rest)
        return

    if head == "pn":
        await toast(ctx)
        await shop_flow.delivery_note(ctx, rest)
        return

    if head == "buy":
        pid, qty = _pid_qty(rest)
        if not pid:
            await error(ctx, "err_not_found")
            return
        await toast(ctx)
        await shop_flow.confirm(ctx, pid, qty)
        return

    if head == "ok":
        parts = rest.split(":")
        pid = parts[0] if parts else ""
        qty = util.parse_qty(parts[1]) if len(parts) > 1 else 1
        coupon = parts[2] if len(parts) > 2 else ""
        if not pid or not qty:
            await error(ctx, "err_not_found")
            return
        await shop_flow.buy(ctx, pid, qty, coupon)
        return

    if head == "pay":
        pid, qty = _pid_qty(rest)
        if not pid:
            await error(ctx, "err_not_found")
            return
        await toast(ctx)
        await shop_flow.pay_shortfall(ctx, pid, qty)
        return

    if head == "paym":
        parts = rest.split(":")
        if len(parts) < 3:
            await error(ctx, "err_not_found")
            return
        method, pid = parts[0], parts[1]
        qty = util.parse_qty(parts[2]) or 1
        await shop_flow.start_payment(ctx, method, pid, qty)
        return

    if head == "w":
        await _wallet_route(ctx, rest)
        return

    if head == "wm":
        parts = rest.split(":")
        method = parts[0] if parts else ""
        if not method:
            await error(ctx, "err_not_found")
            return
        if len(parts) == 1:                  # method chosen, amount next
            await account.topup_pick_amount(ctx, method)
            return
        amount = util.parse_amount(parts[1])
        if amount is None:
            await error(ctx, "err_bad_number")
            return
        await account.topup_method(ctx, method, amount)
        return

    if head == "paid":
        await pay_flow.confirm_paid(ctx, rest)
        return

    if head == "pcan":
        await pay_flow.cancel(ctx, rest)
        return

    if head == "ord":
        await account.order_detail(ctx, rest)
        return

    if head == "ordr":
        await account.resend(ctx, rest)
        return

    if head == "lang":
        await account.set_language(ctx, rest)
        return

    await toast(ctx)


async def _nav(ctx: Ctx, where: str):
    if where == "home":
        await account.home(ctx)
    elif where == "products":
        await toast(ctx)
        await shop_flow.categories(ctx)
    elif where == "wallet":
        await toast(ctx)
        await account.wallet(ctx)
    elif where == "orders":
        await toast(ctx)
        await account.orders(ctx)
    elif where == "gift":
        await toast(ctx)
        await account.gift(ctx)
    elif where == "support":
        await toast(ctx)
        await account.support(ctx)
    elif where == "profile":
        await toast(ctx)
        await account.profile(ctx)
    elif where == "language":
        await account.language(ctx)
    elif where == "terms":
        await toast(ctx)
        await account.terms(ctx)
    elif where == "help":
        await toast(ctx)
        await account.help_screen(ctx)
    elif where == "api":
        await account.api(ctx)
    elif where == "close":
        await account.close(ctx)
    elif where == "joined":
        await account.joined_check(ctx)
    else:
        await toast(ctx)


async def _wallet_route(ctx: Ctx, rest: str):
    if rest == "top":
        await account.topup_menu(ctx)
        return
    if rest == "topc" or rest.startswith("topc:"):
        await account.topup_custom(ctx, rest[5:] if ":" in rest else "")
        return
    if rest == "hist":
        await account.history(ctx)
        return
    if rest == "tr":
        await account.transfer_prompt(ctx)
        return
    await toast(ctx)


def _pid_qty(rest: str) -> tuple[str, int]:
    parts = rest.split(":")
    pid = parts[0] if parts else ""
    qty = util.parse_qty(parts[1]) if len(parts) > 1 else 1
    return pid, qty or 1
