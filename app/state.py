"""
app/state.py — short-lived, in-memory conversation state.

Two kinds of memory:
  * a prompt the bot is waiting on ("send me a quantity", "send me a code")
  * the coupon a user picked for a product, until they buy or clear it

Both are deliberately not persisted: after a restart the user simply taps the
button again, which is better than reviving a half-finished admin form.
"""

import time

TTL_SECONDS = 15 * 60
COUPON_TTL_SECONDS = 60 * 60

_prompts: dict = {}     # user_id -> {"mode": str, "data": dict, "ts": int}
_coupons: dict = {}     # user_id -> {pid: {"code": str, "ts": int}}


# ─── PROMPTS ──────────────────────────────────────────────────
def set_prompt(user_id, mode: str, **data):
    _prompts[str(user_id)] = {
        "mode": mode,
        "data": data,
        "ts": int(time.time()),
    }


def get_prompt(user_id) -> dict | None:
    record = _prompts.get(str(user_id))
    if not record:
        return None
    if int(time.time()) - record["ts"] > TTL_SECONDS:
        _prompts.pop(str(user_id), None)
        return None
    return record


def prompt_mode(user_id) -> str:
    record = get_prompt(user_id)
    return record["mode"] if record else ""


def clear_prompt(user_id):
    _prompts.pop(str(user_id), None)


# ─── COUPONS ──────────────────────────────────────────────────
def set_coupon(user_id, pid: str, code: str):
    bucket = _coupons.setdefault(str(user_id), {})
    bucket[pid] = {"code": code, "ts": int(time.time())}


def get_coupon(user_id, pid: str) -> str:
    bucket = _coupons.get(str(user_id)) or {}
    record = bucket.get(pid)
    if not record:
        return ""
    if int(time.time()) - record["ts"] > COUPON_TTL_SECONDS:
        bucket.pop(pid, None)
        return ""
    return record["code"]


def clear_coupon(user_id, pid: str):
    bucket = _coupons.get(str(user_id))
    if bucket:
        bucket.pop(pid, None)


def sweep():
    """Drop expired entries. Called by the background housekeeping task."""
    now = int(time.time())
    for user_id, record in list(_prompts.items()):
        if now - record["ts"] > TTL_SECONDS:
            _prompts.pop(user_id, None)
    for user_id, bucket in list(_coupons.items()):
        for pid, record in list(bucket.items()):
            if now - record["ts"] > COUPON_TTL_SECONDS:
                bucket.pop(pid, None)
        if not bucket:
            _coupons.pop(user_id, None)
