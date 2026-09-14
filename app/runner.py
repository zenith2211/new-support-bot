"""
app/runner.py — process lifecycle.

Long-polling loop, a small HTTP server (health check for free hosting tiers
plus an optional read-only catalog feed), and a housekeeping task that expires
abandoned invoices and sweeps stale conversation state.
"""

import asyncio
import logging
import sys

from aiohttp import web

from . import commands, config, emoji as emo, payments, state, store, tg, util
from .handlers import router

logger = logging.getLogger(__name__)

HOUSEKEEPING_INTERVAL = 300


def setup_logging():
    logging.basicConfig(
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


# ─── POLLING ──────────────────────────────────────────────────
ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]


async def _safe_handle(update: dict):
    try:
        await router.handle_update(update)
    except Exception:
        logger.exception("update %s failed", update.get("update_id"))


async def poll_forever():
    offset = 0
    backoff = 1

    while True:
        data = await tg.api("getUpdates", {
            "offset": offset,
            "timeout": config.POLL_TIMEOUT,
            "allowed_updates": ALLOWED_UPDATES,
        })

        if not data.get("ok"):
            logger.warning("getUpdates failed: %s", data.get("description"))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        backoff = 1
        updates = data.get("result") or []
        for update in updates:
            offset = update["update_id"] + 1
            asyncio.create_task(_safe_handle(update))


# ─── HOUSEKEEPING ─────────────────────────────────────────────
async def housekeeping_forever():
    while True:
        await asyncio.sleep(HOUSEKEEPING_INTERVAL)
        try:
            state.sweep()
            _expire_topups()
        except Exception:
            logger.exception("housekeeping failed")


def _expire_topups():
    cutoff = util.now_ts() - config.ORDER_EXPIRY_MINUTES * 60
    expired = 0
    for record in store.topups_pending():
        if int(record.get("created") or 0) < cutoff:
            store.topups.patch(record["id"], status="expired")
            expired += 1
    if expired:
        logger.info("expired %d stale top-up(s)", expired)


# ─── HTTP ─────────────────────────────────────────────────────
async def _health(request: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "store": store.store_name(),
        "products": store.product_count(),
        "gateways": [method.key for method in payments.available()],
    })


async def _root(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _catalog(request: web.Request) -> web.Response:
    if not config.STORE_API_KEY:
        return web.json_response({"error": "disabled"}, status=404)
    supplied = (request.headers.get("X-API-Key")
                or request.query.get("key") or "")
    if supplied != config.STORE_API_KEY:
        return web.json_response({"error": "unauthorized"}, status=401)

    payload = []
    for cat in store.category_list():
        payload.append({
            "id": cat["id"],
            "name": cat.get("name"),
            "products": [
                {
                    "id": product["id"],
                    "name": product.get("name"),
                    "sku": product.get("sku"),
                    "price": float(product.get("price") or 0.0),
                    "currency": config.CURRENCY,
                    "stock": store.stock_count(product["id"]),
                    "unlimited": store.stock_is_unlimited(product["id"]),
                    "sold": int(product.get("sold") or 0),
                    "min_qty": int(product.get("min_qty") or 1),
                    "max_qty": int(product.get("max_qty") or 1),
                }
                for product in store.products_in(cat["id"])
            ],
        })
    return web.json_response({"store": store.store_name(),
                              "categories": payload})


async def start_http() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", _root)
    app.router.add_get("/health", _health)
    app.router.add_get("/api/catalog", _catalog)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    logger.info("http listening on :%s", config.PORT)
    return runner


# ─── STARTUP ──────────────────────────────────────────────────
async def publish_commands():
    """Register the hamburger menu, in every language plus an admin scope."""
    await tg.set_my_commands(commands.public_commands("en"))
    for code in commands.all_langs():
        if code == "en":
            continue
        await tg.api("setMyCommands", {
            "commands": commands.public_commands(code),
            "language_code": code,
        })
    # Chat-scoped menus only work for admins who have opened the bot; the
    # rest get theirs on first contact (see commands.ensure_admin_menu).
    for admin_id in config.ADMINS:
        if not await commands.ensure_admin_menu(admin_id, tg):
            logger.info("admin menu for %s deferred until they open the bot",
                        admin_id)


async def announce_start():
    me = await tg.get_me()
    logger.info("running as @%s (%s)", me.get("username"), me.get("id"))
    logger.info("admins: %s", config.ADMINS or "none configured")
    logger.info("gateways: %s", [m.key for m in payments.available()] or "none")
    logger.info("premium emoji slots loaded: %d", len(emo.PREMIUM))
    if not config.LOG_CHANNEL_ID:
        logger.info("LOG_CHANNEL_ID unset — channel posts are off")


async def main():
    setup_logging()

    problems = config.missing_required()
    if problems:
        for problem in problems:
            logger.error("config: %s", problem)
        logger.error("Set the variables above (see .env.example) and restart.")
        return 1

    store.init()
    emo.load_premium()

    http_runner = await start_http()
    try:
        await announce_start()
        await publish_commands()
        logger.info("polling for updates")
        await asyncio.gather(poll_forever(), housekeeping_forever())
    except asyncio.CancelledError:
        logger.info("shutting down")
    finally:
        await tg.close_session()
        await http_runner.cleanup()
    return 0


def run():
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 0
    sys.exit(code or 0)
