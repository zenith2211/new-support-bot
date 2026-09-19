"""
app/state.py — short-lived conversation state.

Two kinds of memory:
  * a prompt the bot is waiting on ("send me a quantity", "send me a code")
  * the coupon a user picked for a product, until they buy or clear it

Both used to live in a module-level dict, on the reasoning that losing a
half-finished admin form to a restart was harmless. That reasoning holds for
one long-lived process and is wrong for anything serverless: each webhook
invocation is its own process, so the invocation that stores the prompt is
never the one that reads the reply. Tapping "Add stock" and then sending the
lines would silently do nothing.

So state goes through store.Table like everything else. On Postgres that
means both halves of a prompt see the same row; on JSON it is one small file.
Entries still expire — see TTL_SECONDS — they are just no longer lost between
two consecutive messages.
"""

import logging
import time

from . import store

logger = logging.getLogger(__name__)

TTL_SECONDS = 15 * 60
COUPON_TTL_SECONDS = 60 * 60


def _now() -> int:
    return int(time.time())


# ─── PROMPTS ──────────────────────────────────────────────────
def set_prompt(user_id, mode: str, **data):
    store.prompts.put(str(user_id), {
        "mode": mode,
        "data": data,
        "ts": _now(),
    })


def get_prompt(user_id) -> dict | None:
    record = store.prompts.get(str(user_id))
    if not record:
        return None
    if _now() - int(record.get("ts") or 0) > TTL_SECONDS:
        clear_prompt(user_id)
        return None
    # Callers read record["data"]; keep the shape they already expect.
    record.setdefault("data", {})
    return record


def prompt_mode(user_id) -> str:
    record = get_prompt(user_id)
    return record["mode"] if record else ""


def clear_prompt(user_id):
    store.prompts.delete(str(user_id))


# ─── COUPONS ──────────────────────────────────────────────────
# Keyed by user, holding one entry per product, so picking a coupon for one
# product does not disturb another.
def set_coupon(user_id, pid: str, code: str):
    bucket = dict(store.coupon_picks.get(str(user_id)) or {})
    bucket[str(pid)] = {"code": code, "ts": _now()}
    store.coupon_picks.put(str(user_id), bucket)


def get_coupon(user_id, pid: str) -> str:
    bucket = store.coupon_picks.get(str(user_id)) or {}
    record = bucket.get(str(pid))
    if not record:
        return ""
    if _now() - int(record.get("ts") or 0) > COUPON_TTL_SECONDS:
        clear_coupon(user_id, pid)
        return ""
    return record.get("code") or ""


def clear_coupon(user_id, pid: str):
    bucket = dict(store.coupon_picks.get(str(user_id)) or {})
    if bucket.pop(str(pid), None) is None:
        return
    if bucket:
        store.coupon_picks.put(str(user_id), bucket)
    else:
        store.coupon_picks.delete(str(user_id))


def sweep() -> dict:
    """Drop expired entries. Run by housekeeping (api/cron.py on serverless).

    Nothing depends on this for correctness — get_prompt and get_coupon both
    check the age themselves. It only stops the tables growing.
    """
    now = _now()
    dropped_prompts = 0
    for user_id, record in list(store.prompts.all().items()):
        if now - int(record.get("ts") or 0) > TTL_SECONDS:
            store.prompts.delete(user_id)
            dropped_prompts += 1

    dropped_coupons = 0
    for user_id, bucket in list(store.coupon_picks.all().items()):
        kept = {pid: rec for pid, rec in (bucket or {}).items()
                if now - int(rec.get("ts") or 0) <= COUPON_TTL_SECONDS}
        if len(kept) == len(bucket or {}):
            continue
        dropped_coupons += len(bucket or {}) - len(kept)
        if kept:
            store.coupon_picks.put(user_id, kept)
        else:
            store.coupon_picks.delete(user_id)

    return {"prompts": dropped_prompts, "coupons": dropped_coupons}
