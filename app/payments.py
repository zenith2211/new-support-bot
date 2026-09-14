"""
app/payments.py — payment methods.

Binance Pay is the one built-in gateway. It only appears in the UI when both
BINANCE_PAY_KEY and BINANCE_PAY_SECRET are set, so a fresh clone with no
credentials still runs — the wallet is then funded by gift codes or by an
admin, and the "pick a payment method" screen says so.

Adding another gateway = one Method entry plus a create/check pair, wired
into METHODS below. Nothing else in the bot needs to change.
"""

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


def manual_enabled() -> bool:
    return config._env_bool("MANUAL_PAY", False)


def available() -> list:
    methods = []
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
    return {"binance": "Binance Pay", "manual": MANUAL.label,
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
