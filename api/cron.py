"""
api/cron.py — what housekeeping_forever() does, once per scheduled run.

The polling runner sweeps expired top-ups and stale prompt state every few
minutes. There is no loop here to do that, so Vercel Cron calls this instead
(see the `crons` entry in vercel.json).

Vercel Hobby only runs crons once a day, so an abandoned invoice can sit
"pending" for up to 24 hours rather than the usual few minutes. That is
cosmetic: payment truth comes from check_invoice() asking the gateway, never
from this sweep.
"""

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, state, store, tg, util          # noqa: E402

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("cron")

CRON_SECRET = config._env("CRON_SECRET")


def _expire_topups() -> int:
    cutoff = util.now_ts() - config.ORDER_EXPIRY_MINUTES * 60
    expired = 0
    for record in list(store.topups.values()):
        if record.get("status") != "pending":
            continue
        if int(record.get("created") or 0) > cutoff:
            continue
        store.topups.patch(record["id"], status="expired")
        expired += 1
    return expired


async def _run() -> dict:
    try:
        store.init()
        state.sweep()
        return {"ok": True, "expired_topups": _expire_topups()}
    finally:
        await tg.close_session()


class handler(BaseHTTPRequestHandler):           # noqa: N801 - Vercel's name

    def do_GET(self):                            # noqa: N802 - stdlib name
        # Vercel signs cron invocations with CRON_SECRET when it is set.
        # Without the check this endpoint is a public "expire everything"
        # button.
        if CRON_SECRET:
            auth = self.headers.get("Authorization") or ""
            if auth != f"Bearer {CRON_SECRET}":
                logger.warning("rejected a cron call with a bad secret")
                self._reply(403, {"ok": False, "error": "forbidden"})
                return

        try:
            result = asyncio.run(_run())
        except Exception as exc:                 # noqa: BLE001
            logger.exception("housekeeping failed")
            result = {"ok": False, "error": str(exc)}

        logger.info("housekeeping: %s", result)
        self._reply(200 if result.get("ok") else 500, result)

    def _reply(self, code: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):           # noqa: A003 - stdlib name
        logger.info(fmt, *args)
