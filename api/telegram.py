"""
api/telegram.py — the Telegram webhook, for serverless hosts.

Vercel invokes this once per update. There is no polling loop and no
long-lived process: Telegram POSTs an update, we route it, we exit.

Three things this has to get right that the polling runner does not:

  * Authenticity. This URL is public, so without a check anyone could POST a
    forged update — including one whose `from.id` is an admin's, which would
    hand them /admin. Telegram signs every delivery with the secret_token
    given to setWebhook; we reject anything that does not match.
  * Session lifetime. tg.py caches one aiohttp session, and a cached session
    belongs to the event loop that made it. Each invocation gets a fresh loop
    via asyncio.run(), so the session is closed before returning or the next
    invocation would inherit one bound to a dead loop.
  * State. DATABASE_URL is mandatory here. With JSON files every invocation
    would start from an empty, read-only disk, so nothing would persist
    between two messages from the same customer.

Answer Telegram quickly and always with 200: a non-2xx makes it retry the
same update, and an update that crashes us would then crash us repeatedly.
"""

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, emoji as emo, store, tg          # noqa: E402
from app.handlers import router                          # noqa: E402

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("webhook")

WEBHOOK_SECRET = config._env("WEBHOOK_SECRET")

# Survives between invocations on a warm instance, so the catalog is only
# loaded from Postgres on a cold start.
_ready = False


def _boot():
    global _ready
    if _ready:
        return
    store.init()
    emo.load_premium()
    _ready = True


async def _process(update: dict):
    try:
        await router.handle_update(update)
    finally:
        # Never leak a session into the next invocation's event loop.
        await tg.close_session()


class handler(BaseHTTPRequestHandler):           # noqa: N801 - Vercel's name

    def _reply(self, code: int, body: str = "ok"):
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):                            # noqa: N802 - stdlib name
        """A browser hitting the URL, or a health check.

        Reports what this instance actually resolved, not what the repo says.
        Environment changes only reach a new deployment, so being able to read
        back the live gateway list and emoji count is what turns "I changed
        the variable" into something checkable.
        """
        _boot()
        from app import payments                 # noqa: PLC0415 - diagnostic
        self._reply(200, json.dumps({
            "ok": True,
            "store": store.store_name(),
            "storage": store.backend.kind,
            "products": store.products.count(),
            "gateways": [m.key for m in payments.available()],
            "emoji": len(emo.PREMIUM),
            # Exactly what _gated() checks. Reporting the env var alone once
            # hid a wide-open shop behind a healthy-looking "force_join": 1 —
            # and FORCE_JOIN is only the default for the stored setting, so
            # it says nothing at all once that row exists.
            "force_join": {
                "enabled": bool(store.setting("force_join")),
                "env_default": bool(config.FORCE_JOIN),
                "chats": [c["id"] for c in config.FORCE_JOIN_CHATS],
                "gating": bool(store.setting("force_join"))
                          and bool(config.FORCE_JOIN_CHATS),
            },
        }))

    def do_POST(self):                           # noqa: N802 - stdlib name
        if WEBHOOK_SECRET:
            sent = self.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
            if sent != WEBHOOK_SECRET:
                logger.warning("rejected a webhook POST with a bad secret")
                self._reply(403, "forbidden")
                return
        else:
            # Refuse rather than accept unsigned updates: anyone who guesses
            # the URL could otherwise forge an admin's user id.
            logger.error("WEBHOOK_SECRET is not set — refusing updates")
            self._reply(403, "webhook secret not configured")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            update = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError) as exc:
            logger.warning("unreadable update: %s", exc)
            self._reply(200, "ok")               # do not make Telegram retry
            return

        try:
            _boot()
            asyncio.run(_process(update))
        except Exception:                        # noqa: BLE001
            # 200 regardless: a crash-looping update would otherwise be
            # redelivered forever.
            logger.exception("update %s failed", update.get("update_id"))

        self._reply(200, "ok")

    def log_message(self, fmt, *args):           # noqa: A003 - stdlib name
        logger.info(fmt, *args)
