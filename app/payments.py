"""
app/payments.py — payment methods.

Two built-in gateways: Binance Pay and Cryptomus. Each only appears in the UI
when its own credentials are set, so a fresh clone with no credentials still
runs — the wallet is then funded by gift codes or by an admin, and the "pick a
payment method" screen says so.

Both are *polled* rather than webhooked: the bot asks the gateway whether an
invoice is paid when the customer presses "I have paid". That is what lets the
whole thing run on localhost with no public URL, no port forward and no tunnel.

Adding another gateway = one Method entry plus a create/check pair, wired into
available() and the dispatch in create_invoice / check_invoice. Nothing else in
the bot needs to change.
"""

import base64
import hashlib
import hmac
import json
import logging
import random
import re
import string
import time
from dataclasses import dataclass

from . import config, tg

logger = logging.getLogger(__name__)

PAID = "paid"
PENDING = "pending"
FAILED = "failed"


@dataclass(frozen=True)
class Method:
    key: str
    label: str
    emoji: str
    kind: str          # "api" = the bot can verify; "manual" = admin confirms
    currency: str = "USDT"


BINANCE_PAY = Method(
    key="binance",
    label="Binance Pay",
    emoji="coin",
    kind="api",
    currency=config._env("BINANCE_PAY_CURRENCY", "USDT"),
)

# Pays from any wallet, not just Cryptomus accounts — so it reaches customers
# Binance Pay and the Telegram-native wallets cannot.
CRYPTOMUS = Method(
    key="cryptomus",
    label=config.CRYPTOMUS_LABEL,
    emoji="gem",
    kind="api",
    currency=config.CRYPTOMUS_CURRENCY,
)

# Fallback used when a gateway is configured but the API call fails, and for
# deployments that take payment off-Telegram. Enable with MANUAL_PAY=1.
MANUAL = Method(
    key="manual",
    label=config._env("MANUAL_PAY_LABEL", "Pay manually"),
    emoji="bank",
    kind="manual",
)


def binance_configured() -> bool:
    return bool(config.BINANCE_PAY_KEY and config.BINANCE_PAY_SECRET)


def cryptomus_configured() -> bool:
    return bool(config.CRYPTOMUS_MERCHANT_ID and config.CRYPTOMUS_API_KEY)


def manual_enabled() -> bool:
    return config._env_bool("MANUAL_PAY", False)


def available() -> list:
    methods = []
    if cryptomus_configured():
        methods.append(CRYPTOMUS)
    if binance_configured():
        methods.append(BINANCE_PAY)
    if manual_enabled():
        methods.append(MANUAL)
    return methods


def get(key: str) -> Method | None:
    for method in available():
        if method.key == key:
            return method
    return None


def label(key: str) -> str:
    method = get(key)
    if method:
        return method.label
    return {"binance": "Binance Pay", "cryptomus": CRYPTOMUS.label,
            "manual": MANUAL.label,
            "gift": "Gift code", "admin": "Admin credit",
            "wallet": "Wallet"}.get(key, key or "—")


# ─── BINANCE PAY ──────────────────────────────────────────────
_NONCE_CHARS = string.ascii_letters + string.digits


def _nonce() -> str:
    return "".join(random.choices(_NONCE_CHARS, k=32))


def _sign(timestamp: str, nonce: str, body: str) -> str:
    payload = f"{timestamp}\n{nonce}\n{body}\n"
    digest = hmac.new(
        config.BINANCE_PAY_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()
    return digest.upper()


async def _binance_call(path: str, body: dict) -> dict:
    """POST to Binance Pay with the required signature headers."""
    raw = json.dumps(body, separators=(",", ":"))
    timestamp = str(int(time.time() * 1000))
    nonce = _nonce()
    headers = {
        "Content-Type": "application/json",
        "BinancePay-Timestamp": timestamp,
        "BinancePay-Nonce": nonce,
        "BinancePay-Certificate-SN": config.BINANCE_PAY_KEY,
        "BinancePay-Signature": _sign(timestamp, nonce, raw),
    }
    url = f"{config.BINANCE_PAY_BASE.rstrip('/')}{path}"

    try:
        session = await tg.get_session()
        async with session.post(url, data=raw, headers=headers) as resp:
            data = await resp.json(content_type=None)
    except Exception as exc:                     # noqa: BLE001 - never crash a handler
        logger.warning("binance pay %s failed: %s", path, exc)
        return {"status": "FAIL", "errorMessage": str(exc)}

    if str(data.get("status")) != "SUCCESS":
        logger.warning("binance pay %s rejected: %s", path,
                       data.get("errorMessage") or data)
    return data


def merchant_trade_no(topup_id: str) -> str:
    """Binance requires letters and digits only, 32 chars max."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", topup_id or "")
    return (cleaned or f"TOP{int(time.time())}")[:32]


# ─── CRYPTOMUS ────────────────────────────────────────────────
# Status names from the Cryptomus "Payment statuses" reference. Anything not
# listed below is treated as still pending, so an unfamiliar status can never
# credit a wallet by accident.
_CM_PAID = ("paid", "paid_over")
_CM_FAILED = ("fail", "cancel", "system_fail", "wrong_amount",
              "refund_process", "refund_fail", "refund_paid", "locked")
# Real money arrived but not the right amount, or it is frozen. The top-up is
# still failed (we must not credit the full amount), but it needs a human.
_CM_NEEDS_ATTENTION = ("wrong_amount", "locked")


def cryptomus_order_id(topup_id: str) -> str:
    """Cryptomus order_id: letters, digits, _ and - only, 1-128 chars.

    Our own ids ("TOP-A1B2C3D4") already qualify. Worth keeping deterministic:
    reusing an order_id makes Cryptomus return the *existing* invoice instead
    of creating a second one, so a double-tapped Pay button is harmless.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", topup_id or "")
    return (cleaned or f"TOP-{int(time.time())}")[:128]


def _cryptomus_sign(raw: str) -> str:
    """md5(base64(body) + api_key) — Cryptomus' documented scheme.

    MD5 is their choice, not ours; it is a request signature, not a password
    hash. Do not "upgrade" it to sha256 or auth silently starts failing.
    """
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return hashlib.md5(
        (encoded + config.CRYPTOMUS_API_KEY).encode("utf-8")
    ).hexdigest()


def _cm_state(data: dict) -> int:
    """Cryptomus' state field: 0 = success, anything else = error.

    Beware `data.get("state", -1) or -1` — 0 is falsy, so that idiom turns
    every success into an error. Hence the explicit helper.
    """
    if not isinstance(data, dict):
        return -1
    try:
        return int(data.get("state", -1))
    except (TypeError, ValueError):
        return -1


async def _cryptomus_call(path: str, body: dict) -> dict:
    """POST to Cryptomus. -> the parsed reply, or a synthetic error state."""
    # The signature covers the exact bytes we send, so serialise once and send
    # that same string. Re-encoding the dict here would break authentication.
    raw = json.dumps(body, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "merchant": config.CRYPTOMUS_MERCHANT_ID,
        "sign": _cryptomus_sign(raw),
    }
    url = f"{config.CRYPTOMUS_BASE.rstrip('/')}{path}"

    try:
        session = await tg.get_session()
        async with session.post(url, data=raw.encode("utf-8"),
                                headers=headers) as resp:
            data = await resp.json(content_type=None)
    except Exception as exc:                     # noqa: BLE001 - never crash a handler
        logger.warning("cryptomus %s failed: %s", path, exc)
        return {"state": -1, "message": str(exc)}

    if not isinstance(data, dict):
        logger.warning("cryptomus %s returned %r", path, data)
        return {"state": -1, "message": "unexpected reply"}

    if _cm_state(data) != 0:
        logger.warning("cryptomus %s rejected: %s", path,
                       data.get("message") or data.get("errors") or data)
    return data


def _cryptomus_error(data: dict) -> str:
    """Flatten Cryptomus' two error shapes into one line."""
    errors = data.get("errors")
    if isinstance(errors, dict):
        parts = []
        for field, value in errors.items():
            detail = "; ".join(value) if isinstance(value, list) else str(value)
            parts.append(f"{field}: {detail}")
        if parts:
            return " / ".join(parts)
    return str(data.get("message") or "gateway rejected the invoice")


def _cryptomus_amount(amount: float) -> str:
    """Cryptomus wants the amount as a string, '.' separated."""
    text = f"{float(amount):.8f}".rstrip("0").rstrip(".")
    return text or "0"


async def _cryptomus_create(method: Method, topup: dict,
                            description: str = "") -> dict:
    order_id = cryptomus_order_id(topup["id"])
    body = {
        "amount": _cryptomus_amount(topup["amount"]),
        "currency": method.currency,
        "order_id": order_id,
        "lifetime": config.CRYPTOMUS_LIFETIME,
        "subtract": config.CRYPTOMUS_SUBTRACT,
        # Let a customer who underpaid top the invoice up rather than losing it.
        "is_payment_multiple": True,
    }
    if config.CRYPTOMUS_TO_CURRENCY:
        body["to_currency"] = config.CRYPTOMUS_TO_CURRENCY
    if config.CRYPTOMUS_NETWORK:
        body["network"] = config.CRYPTOMUS_NETWORK
    if config.CRYPTOMUS_CALLBACK_URL:
        body["url_callback"] = config.CRYPTOMUS_CALLBACK_URL
    if config.BOT_LINK:
        # "Back to the bot" button on the Cryptomus payment page.
        body["url_return"] = config.BOT_LINK
        body["url_success"] = config.BOT_LINK
    if description:
        body["additional_data"] = description[:255]

    data = await _cryptomus_call("/v1/payment", body)
    if _cm_state(data) != 0:
        return {"ok": False, "error": _cryptomus_error(data)}

    result = data.get("result") or {}
    checkout = str(result.get("url") or "")
    if not checkout:
        return {"ok": False, "error": "gateway returned no payment link"}

    return {
        "ok": True,
        "checkout_url": checkout,
        # uuid is what payment/info prefers; order_id is our fallback.
        "provider_ref": str(result.get("uuid") or order_id),
        "qr": "",
        "error": "",
    }


async def _cryptomus_check(topup: dict) -> str:
    ref = str(topup.get("provider_ref") or "")
    order_id = cryptomus_order_id(topup["id"])
    # A uuid is a uuid; anything else stored here is our own order id.
    if ref and ref != order_id:
        body = {"uuid": ref}
    else:
        body = {"order_id": order_id}

    data = await _cryptomus_call("/v1/payment/info", body)
    if _cm_state(data) != 0:
        # Could not ask. Never guess "paid" — leave it pending and let the
        # customer press again.
        return PENDING

    result = data.get("result") or {}
    status = str(result.get("payment_status")
                 or result.get("status") or "").lower()

    if status in _CM_PAID:
        return PAID
    if status in _CM_FAILED:
        if status in _CM_NEEDS_ATTENTION:
            logger.warning(
                "cryptomus top-up %s needs a human: status=%s paid=%s of %s %s",
                topup.get("id"), status, result.get("payment_amount"),
                result.get("amount"), result.get("payer_currency") or "",
            )
        return FAILED
    if status:
        logger.info("cryptomus top-up %s still pending: status=%s",
                    topup.get("id"), status)
    return PENDING


async def create_invoice(method: Method, topup: dict,
                         description: str = "") -> dict:
    """Create a payment. -> {ok, checkout_url, provider_ref, qr, error}"""
    if method.kind == "manual":
        return {
            "ok": True,
            "checkout_url": "",
            "provider_ref": merchant_trade_no(topup["id"]),
            "qr": "",
            "error": "",
        }

    if method.key == CRYPTOMUS.key:
        return await _cryptomus_create(method, topup, description)

    if method.key != BINANCE_PAY.key:
        return {"ok": False, "error": "unsupported method"}

    trade_no = merchant_trade_no(topup["id"])
    amount = round(float(topup["amount"]), 8)
    goods_name = (description or f"{config.STORE_NAME} wallet top-up")[:256]

    body = {
        "env": {"terminalType": "APP"},
        "merchantTradeNo": trade_no,
        "orderAmount": amount,
        "currency": method.currency,
        "description": goods_name[:128],
        "goods": {
            "goodsType": "02",              # virtual goods
            "goodsCategory": "Z000",        # others
            "referenceGoodsId": str(topup.get("intent_pid") or topup["id"])[:64],
            "goodsName": goods_name[:256],
        },
    }

    data = await _binance_call("/binancepay/openapi/v3/order", body)
    if str(data.get("status")) != "SUCCESS":
        return {
            "ok": False,
            "error": str(data.get("errorMessage") or "gateway rejected the order"),
        }

    result = data.get("data") or {}
    return {
        "ok": True,
        "checkout_url": result.get("checkoutUrl") or result.get("universalUrl") or "",
        "provider_ref": trade_no,
        "qr": result.get("qrcodeLink") or "",
        "prepay_id": result.get("prepayId") or "",
        "error": "",
    }


async def check_invoice(method: Method, topup: dict) -> str:
    """Ask the gateway whether a top-up is paid. -> PAID / PENDING / FAILED"""
    if method.kind == "manual":
        return PENDING

    if method.key == CRYPTOMUS.key:
        return await _cryptomus_check(topup)

    if method.key != BINANCE_PAY.key:
        return PENDING

    trade_no = topup.get("provider_ref") or merchant_trade_no(topup["id"])
    data = await _binance_call(
        "/binancepay/openapi/v2/order/query",
        {"merchantTradeNo": trade_no},
    )
    if str(data.get("status")) != "SUCCESS":
        return PENDING

    status = str((data.get("data") or {}).get("status") or "").upper()
    if status == "PAID":
        return PAID
    if status in ("CANCELED", "CANCELLED", "ERROR", "EXPIRED", "REFUNDED"):
        return FAILED
    return PENDING


async def close_invoice(method: Method, topup: dict) -> bool:
    """Best-effort cancel so an abandoned invoice cannot be paid later."""
    if method.key == CRYPTOMUS.key:
        # Cryptomus has no cancel-invoice method: an invoice dies when its
        # lifetime runs out (CRYPTOMUS_LIFETIME). Cancelling locally is enough
        # because a late payment arrives with our order_id still attached, so
        # "I have paid" keeps working until the invoice expires.
        return True
    if method.kind == "manual" or method.key != BINANCE_PAY.key:
        return True
    trade_no = topup.get("provider_ref") or merchant_trade_no(topup["id"])
    data = await _binance_call(
        "/binancepay/openapi/order/close",
        {"merchantTradeNo": trade_no},
    )
    return str(data.get("status")) == "SUCCESS"


def methods_summary() -> str:
    """'Binance Pay / Gift code' — used on the /start and Wallet screens."""
    names = [method.label for method in available()]
    names.append("Gift code")
    return " / ".join(names)
