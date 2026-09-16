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
os.environ["NOWPAYMENTS_API_KEY"] = "test-nowpayments-key"
os.environ["NOWPAYMENTS_CURRENCY"] = "usd"
os.environ["NOWPAYMENTS_PAY_CURRENCY"] = "usdttrc20"
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
        return self.request("POST", url, data=data, headers=headers)

    def request(self, method, url, data=None, headers=None):
        if isinstance(REPLY, Exception):
            raise REPLY
        SENT.append({"method": method, "url": url, "body": data,
                     "headers": headers or {}})
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


# ─── NOWPAYMENTS ──────────────────────────────────────────────
def nowpay_reply(status: str = "waiting", **extra) -> dict:
    result = {
        "payment_id": 5077125051,
        "payment_status": status,
        "pay_address": "TXxDgSHT3nMLLEnbFEd3fTqyiBvyNNMYcp",
        "price_amount": 15.0,
        "price_currency": "usd",
        "pay_amount": 15.02,
        "actually_paid": 0,
        "pay_currency": "usdttrc20",
        "order_id": "TOP-A1B2C3D4",
        "network": "trx",
    }
    result.update(extra)
    return result


async def check_nowpay_create():
    global REPLY
    REPLY = nowpay_reply()
    SENT.clear()

    created = await payments._nowpay_create(
        payments.NOWPAYMENTS, TOPUP, "Spotify Premium")

    check("create ok", created.get("ok"), True)
    check("provider_ref is the payment id", created.get("provider_ref"),
          "5077125051")
    check("no checkout url to open", created.get("checkout_url"), "")

    request = last()
    check("method", request.get("method"), "POST")
    check("endpoint", request.get("url"),
          "https://api.nowpayments.io/v1/payment")
    check("api key header", request["headers"].get("x-api-key"),
          "test-nowpayments-key")

    body = last_body()
    check("price_amount", body.get("price_amount"), 15.0)
    check("price_currency", body.get("price_currency"), "usd")
    check("pay_currency", body.get("pay_currency"), "usdttrc20")
    check("order_id ties the payment to our top-up", body.get("order_id"),
          "TOP-A1B2C3D4")
    ok("ipn_callback_url omitted when unset",
       "ipn_callback_url" not in body)

    # The instructions are the whole customer-facing payload here, and they
    # must survive rendering: `label|value`, one pair per line.
    text = created.get("instructions") or ""
    pairs = dict(line.split("|", 1) for line in text.split("\n") if "|" in line)
    ok("instructions carry the amount and coin",
       pairs.get("Send exactly") == "15.02 USDTTRC20", text)
    ok("instructions carry the address",
       "TXxDgSHT3nMLLEnbFEd3fTqyiBvyNNMYcp" in pairs.values(), text)
    ok("every instruction line has a value",
       all("|" in line and line.split("|", 1)[1].strip()
           for line in text.split("\n") if line.strip()), text)


async def check_nowpay_memo_is_shown():
    """Coins that route by memo lose the funds if the memo is omitted, so it
    must never be silently dropped."""
    global REPLY
    REPLY = nowpay_reply(pay_currency="ton", network="ton",
                         payin_extra_id="9876543")
    created = await payments._nowpay_create(payments.NOWPAYMENTS, TOPUP)
    text = created.get("instructions") or ""
    ok("memo is shown when present", "9876543" in text, text)
    ok("memo is marked required", "required" in text.lower(), text)

    REPLY = nowpay_reply()                       # no memo for this coin
    created = await payments._nowpay_create(payments.NOWPAYMENTS, TOPUP)
    ok("no memo line when there is no memo",
       "memo" not in (created.get("instructions") or "").lower())


async def check_nowpay_status_mapping():
    global REPLY
    cases = {
        # Verified in NOWPayments' own documentation.
        "finished": payments.PAID,
        "waiting": payments.PENDING,
        "partially_paid": payments.FAILED,
        # Standard statuses, spelling not verified in-session. Listing them is
        # safe either way: an absent name simply never matches.
        "confirming": payments.PENDING,
        "confirmed": payments.PAID,
        "sending": payments.PAID,
        "failed": payments.FAILED,
        "refunded": payments.FAILED,
        "expired": payments.FAILED,
        # Anything unrecognised must read as pending, never as paid.
        "some_new_status": payments.PENDING,
        "": payments.PENDING,
    }
    for status, want in cases.items():
        REPLY = nowpay_reply(status)
        got = await payments._nowpay_check(dict(TOPUP, provider_ref="5077125051"))
        check(f"status {status or '(empty)'}", got, want)


async def check_nowpay_check_request():
    global REPLY
    REPLY = nowpay_reply("finished")
    SENT.clear()
    await payments._nowpay_check(dict(TOPUP, provider_ref="5077125051"))
    check("status method", last().get("method"), "GET")
    check("status endpoint", last().get("url"),
          "https://api.nowpayments.io/v1/payment/5077125051")
    check("GET sends no body", last().get("body"), None)

    # No payment id means nothing to ask: GET /v1/payment/ needs JWT auth, so
    # we cannot fall back to order_id the way Cryptomus can.
    SENT.clear()
    got = await payments._nowpay_check(dict(TOPUP, provider_ref=""))
    check("missing payment id stays pending", got, payments.PENDING)
    check("missing payment id sends nothing", len(SENT), 0)


async def check_nowpay_failures_never_credit():
    global REPLY
    bad = [
        ({"status": False, "statusCode": 403, "code": "INVALID_API_KEY",
          "message": "Invalid api key"}, "invalid key"),
        ({"status": False, "statusCode": 404,
          "message": "Endpoint not found"}, "404"),
        ({}, "empty reply"),
        ("<html>502</html>", "non-dict reply"),
        (None, "null reply"),
        (OSError("connection reset"), "network error"),
    ]
    for reply, labelled in bad:
        REPLY = reply
        check(f"error is pending, not paid ({labelled})",
              await payments._nowpay_check(dict(TOPUP, provider_ref="1")),
              payments.PENDING)

        REPLY = reply
        created = await payments._nowpay_create(payments.NOWPAYMENTS, TOPUP)
        check(f"create fails cleanly ({labelled})", created.get("ok"), False)
        ok(f"create explains itself ({labelled})", bool(created.get("error")))

    # A success-shaped reply that is missing the address must not be treated
    # as usable — there would be nowhere for the customer to send money.
    REPLY = nowpay_reply(pay_address="")
    created = await payments._nowpay_create(payments.NOWPAYMENTS, TOPUP)
    check("no address -> not ok", created.get("ok"), False)


def check_nowpay_gating():
    ok("configured with a key", payments.nowpay_configured())
    ok("nowpay is offered",
       "nowpay" in [m.key for m in payments.available()])
    check("label is resolvable", payments.label("nowpay"),
          payments.NOWPAYMENTS.label)

    saved = config.NOWPAYMENTS_API_KEY
    config.NOWPAYMENTS_API_KEY = ""
    try:
        ok("hidden without a key", not payments.nowpay_configured())
        ok("button gone without a key",
           "nowpay" not in [m.key for m in payments.available()])
    finally:
        config.NOWPAYMENTS_API_KEY = saved


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

    # Same seam, other gateway — the two must not be able to cross over.
    REPLY = nowpay_reply("finished")
    SENT.clear()
    created = await payments.create_invoice(payments.NOWPAYMENTS, TOPUP, "x")
    check("create_invoice routes to nowpayments", created.get("ok"), True)
    check("nowpayments create endpoint", last().get("url"),
          "https://api.nowpayments.io/v1/payment")

    status = await payments.check_invoice(
        payments.NOWPAYMENTS, dict(TOPUP, provider_ref="5077125051"))
    check("check_invoice routes to nowpayments", status, payments.PAID)
    check("nowpayments status endpoint", last().get("url"),
          "https://api.nowpayments.io/v1/payment/5077125051")

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
    """Neither gateway has a cancel call; closing must not pretend to."""
    for method in (payments.CRYPTOMUS, payments.NOWPAYMENTS):
        SENT.clear()
        result = await payments.close_invoice(method, TOPUP)
        check(f"close reports success ({method.key})", result, True)
        check(f"close sends nothing ({method.key})", len(SENT), 0)


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
        ("nowpay create request", check_nowpay_create),
        ("nowpay memo handling", check_nowpay_memo_is_shown),
        ("nowpay status mapping", check_nowpay_status_mapping),
        ("nowpay status request", check_nowpay_check_request),
        ("nowpay errors never credit", check_nowpay_failures_never_credit),
        ("nowpay gating", check_nowpay_gating),
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
