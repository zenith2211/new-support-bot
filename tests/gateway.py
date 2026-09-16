"""
tests/gateway.py — Cryptomus gateway logic, with no network.

    python -m tests.gateway

app.tg.get_session is replaced by a fake that records the exact bytes and
headers we would have sent and replays a canned reply. That makes two things
testable that a live call cannot check safely:

  * the signature covers precisely the body we transmit (the one mistake that
    silently breaks Cryptomus auth), and
  * every documented payment status maps to the right verdict — most
    importantly, that nothing we fail to recognise can ever read as "paid".

Exit code is non-zero if any check fails.
"""

import asyncio
import base64
import hashlib
import json
import os
import sys

os.environ.setdefault("BOT_TOKEN", "123456:test-token-not-real")
os.environ.setdefault("ADMIN_IDS", "424242")
os.environ["CRYPTOMUS_MERCHANT_ID"] = "8b03432e-385b-4670-8d06-064591096795"
os.environ["CRYPTOMUS_API_KEY"] = "test-payment-key"
os.environ["CRYPTOMUS_CURRENCY"] = "USD"
os.environ["CRYPTOMUS_SUBTRACT"] = "100"
os.environ["BOT_LINK"] = "https://t.me/examplestorebot"

from app import config, payments, tg                           # noqa: E402

FAILURES: list = []
SENT: list = []
REPLY: dict = {}


def check(name: str, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def ok(name: str, condition: bool, detail: str = ""):
    if not condition:
        FAILURES.append(f"{name}{': ' + detail if detail else ''}")


# ─── FAKE TRANSPORT ───────────────────────────────────────────
class _FakeResponse:
    async def json(self, content_type=None):
        if isinstance(REPLY, Exception):
            raise REPLY
        return REPLY


class _FakePost:
    async def __aenter__(self):
        return _FakeResponse()

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def post(self, url, data=None, headers=None):
        if isinstance(REPLY, Exception):
            raise REPLY
        SENT.append({"url": url, "body": data, "headers": headers or {}})
        return _FakePost()


async def _fake_session():
    return _FakeSession()


def last() -> dict:
    return SENT[-1] if SENT else {}


def last_body() -> dict:
    raw = last().get("body") or b"{}"
    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


def invoice_reply(status: str = "check", **extra) -> dict:
    result = {
        "uuid": "26109ba0-b05b-4ee0-93d1-fd62c822ce95",
        "order_id": "TOP-A1B2C3D4",
        "amount": "15.00",
        "payment_status": status,
        "status": status,
        "url": "https://pay.cryptomus.com/pay/26109ba0",
        "is_final": status not in ("check", "process", "confirm_check",
                                   "wrong_amount_waiting"),
    }
    result.update(extra)
    return {"state": 0, "result": result}


TOPUP = {"id": "TOP-A1B2C3D4", "amount": 15.0}


# ─── CHECKS ───────────────────────────────────────────────────
def check_signature_scheme():
    """md5(base64(body) + api_key), per the documented PHP snippet."""
    for body in ({}, {"amount": "15", "currency": "USD", "order_id": "1"}):
        raw = json.dumps(body, separators=(",", ":"))
        want = hashlib.md5(
            (base64.b64encode(raw.encode()).decode("ascii")
             + "test-payment-key").encode()
        ).hexdigest()
        check(f"sign {raw}", payments._cryptomus_sign(raw), want)


async def check_create_request():
    global REPLY
    REPLY = invoice_reply()
    SENT.clear()

    created = await payments._cryptomus_create(
        payments.CRYPTOMUS, TOPUP, "Spotify Premium")

    check("create ok", created.get("ok"), True)
    check("checkout url", created.get("checkout_url"),
          "https://pay.cryptomus.com/pay/26109ba0")
    check("provider_ref is the uuid", created.get("provider_ref"),
          "26109ba0-b05b-4ee0-93d1-fd62c822ce95")

    request = last()
    check("endpoint", request.get("url"),
          "https://api.cryptomus.com/v1/payment")
    check("merchant header", request["headers"].get("merchant"),
          "8b03432e-385b-4670-8d06-064591096795")

    # The signature must match the bytes actually transmitted. Re-serialising
    # the dict between signing and sending is the classic way to break this,
    # and the API answers with a bare "Merchant unknown." when it happens.
    raw = request["body"]
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    check("signature covers the sent bytes", request["headers"].get("sign"),
          payments._cryptomus_sign(text))

    body = last_body()
    check("amount is a trimmed string", body.get("amount"), "15")
    check("currency", body.get("currency"), "USD")
    check("order_id", body.get("order_id"), "TOP-A1B2C3D4")
    check("subtract", body.get("subtract"), 100)
    check("lifetime", body.get("lifetime"), config.CRYPTOMUS_LIFETIME)
    ok("lifetime within Cryptomus' 300-43200 range",
       300 <= body.get("lifetime", 0) <= 43200, str(body.get("lifetime")))
    check("url_return", body.get("url_return"),
          "https://t.me/examplestorebot")
    # Unset options must be absent, not sent empty — Cryptomus validates them.
    for field in ("to_currency", "network", "url_callback"):
        ok(f"{field} omitted when unset", field not in body,
           f"{field}={body.get(field)!r}")


async def check_status_mapping():
    """Every status in the Cryptomus reference, plus one it does not define."""
    global REPLY
    cases = {
        "paid": payments.PAID,
        "paid_over": payments.PAID,
        "check": payments.PENDING,
        "process": payments.PENDING,
        "confirm_check": payments.PENDING,
        "wrong_amount_waiting": payments.PENDING,
        "wrong_amount": payments.FAILED,
        "fail": payments.FAILED,
        "cancel": payments.FAILED,
        "system_fail": payments.FAILED,
        "refund_process": payments.FAILED,
        "refund_fail": payments.FAILED,
        "refund_paid": payments.FAILED,
        "locked": payments.FAILED,
        # Not in the docs. A gateway that invents a status must never be
        # read as paid.
        "some_new_status": payments.PENDING,
    }
    for status, want in cases.items():
        REPLY = invoice_reply(status)
        got = await payments._cryptomus_check(
            dict(TOPUP, provider_ref="26109ba0-b05b-4ee0-93d1-fd62c822ce95"))
        check(f"status {status}", got, want)


async def check_failures_never_credit():
    """No reachable error may produce PAID."""
    global REPLY
    bad_replies = [
        ({"state": 1, "message": "Merchant unknown."}, "unknown merchant"),
        ({"message": "Merchant unknown."}, "reply with no state"),
        ({"state": 0, "result": {}}, "empty result"),
        ({"state": 0}, "no result"),
        ("<html>502</html>", "non-dict reply"),
        (None, "null reply"),
        (OSError("connection reset"), "network error"),
    ]
    for reply, label in bad_replies:
        REPLY = reply
        got = await payments._cryptomus_check(TOPUP)
        check(f"error is pending, not paid ({label})", got, payments.PENDING)

        REPLY = reply
        created = await payments._cryptomus_create(payments.CRYPTOMUS, TOPUP)
        check(f"create fails cleanly ({label})", created.get("ok"), False)
        ok(f"create explains itself ({label})",
           bool(created.get("error")), "empty error string")


async def check_check_uses_order_id_as_fallback():
    """A top-up whose uuid was never stored is still checkable by order_id."""
    global REPLY
    REPLY = invoice_reply("paid")

    SENT.clear()
    await payments._cryptomus_check(dict(TOPUP, provider_ref=""))
    check("no uuid -> query by order_id", last_body(),
          {"order_id": "TOP-A1B2C3D4"})

    SENT.clear()
    await payments._cryptomus_check(dict(TOPUP, provider_ref="a-uuid-here"))
    check("uuid present -> query by uuid", last_body(),
          {"uuid": "a-uuid-here"})


def check_error_flattening():
    check("message error", payments._cryptomus_error(
        {"state": 1, "message": "Merchant unknown."}), "Merchant unknown.")
    check("field errors", payments._cryptomus_error(
        {"state": 1, "errors": {"amount": ["The amount is too small."]}}),
        "amount: The amount is too small.")
    ok("empty error still says something",
       bool(payments._cryptomus_error({"state": 1})))


def check_order_id_rules():
    # Our own ids pass through untouched — that is what makes a repeat
    # create_invoice return the same invoice instead of a second one.
    check("our id survives", payments.cryptomus_order_id("TOP-A1B2C3D4"),
          "TOP-A1B2C3D4")
    check("illegal chars stripped", payments.cryptomus_order_id("TOP/x y!"),
          "TOPxy")
    check("length capped", len(payments.cryptomus_order_id("A" * 400)), 128)
    ok("blank id still yields something",
       bool(payments.cryptomus_order_id("")))


def check_amount_formatting():
    for value, want in ((15, "15"), (15.0, "15"), (0.1, "0.1"),
                        (2.5, "2.5"), (12.345, "12.345"), (0, "0")):
        check(f"amount {value}", payments._cryptomus_amount(value), want)


def check_availability_gating():
    ok("configured with both credentials", payments.cryptomus_configured())
    ok("cryptomus is offered",
       "cryptomus" in [m.key for m in payments.available()])
    check("get() finds it", payments.get("cryptomus").key, "cryptomus")
    check("label is resolvable", payments.label("cryptomus"),
          payments.CRYPTOMUS.label)

    saved = config.CRYPTOMUS_API_KEY
    config.CRYPTOMUS_API_KEY = ""
    try:
        ok("hidden without an api key", not payments.cryptomus_configured())
        ok("button gone without an api key",
           "cryptomus" not in [m.key for m in payments.available()])
    finally:
        config.CRYPTOMUS_API_KEY = saved


async def check_public_dispatch():
    """create_invoice / check_invoice must route a Method to the right gateway.

    The private helpers above are what the checks exercise; this is the seam
    the rest of the bot actually calls.
    """
    global REPLY
    REPLY = invoice_reply("paid")

    SENT.clear()
    created = await payments.create_invoice(payments.CRYPTOMUS, TOPUP, "item")
    check("create_invoice routes to cryptomus", created.get("ok"), True)
    check("create_invoice hit the right endpoint", last().get("url"),
          "https://api.cryptomus.com/v1/payment")

    status = await payments.check_invoice(
        payments.CRYPTOMUS, dict(TOPUP, provider_ref="a-uuid"))
    check("check_invoice routes to cryptomus", status, payments.PAID)
    check("check_invoice hit the right endpoint", last().get("url"),
          "https://api.cryptomus.com/v1/payment/info")

    # A manual top-up must stay manual: no gateway call, and never auto-paid.
    SENT.clear()
    manual = await payments.create_invoice(payments.MANUAL, TOPUP)
    check("manual create needs no gateway", len(SENT), 0)
    check("manual create succeeds", manual.get("ok"), True)
    check("manual check stays pending",
          await payments.check_invoice(payments.MANUAL, TOPUP),
          payments.PENDING)
    check("manual sent nothing", len(SENT), 0)


async def check_close_is_a_noop():
    """Cryptomus has no cancel-invoice call; closing must not pretend to."""
    SENT.clear()
    result = await payments.close_invoice(payments.CRYPTOMUS, TOPUP)
    check("close reports success", result, True)
    check("close sends nothing", len(SENT), 0)


# ─── RUNNER ───────────────────────────────────────────────────
async def main() -> int:
    tg.get_session = _fake_session

    checks = [
        ("signature scheme", check_signature_scheme),
        ("create request", check_create_request),
        ("status mapping", check_status_mapping),
        ("errors never credit", check_failures_never_credit),
        ("order_id fallback", check_check_uses_order_id_as_fallback),
        ("error flattening", check_error_flattening),
        ("order_id rules", check_order_id_rules),
        ("amount formatting", check_amount_formatting),
        ("availability gating", check_availability_gating),
        ("public dispatch", check_public_dispatch),
        ("close is a no-op", check_close_is_a_noop),
    ]

    for name, runner in checks:
        before = len(FAILURES)
        try:
            result = runner()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:                 # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILURES.append(f"{name}: raised {type(exc).__name__}: {exc}")
        broke = len(FAILURES) - before
        print(f"  [{('FAIL x' + str(broke)) if broke else 'ok':>7}] {name}")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for problem in FAILURES:
            print(f"  - {problem}")
        return 1
    print(f"all {len(checks)} gateway checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
