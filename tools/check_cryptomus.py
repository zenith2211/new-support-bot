"""
tools/check_cryptomus.py — verify Cryptomus credentials and report the fees.

    python -m tools.check_cryptomus

Reads CRYPTOMUS_MERCHANT_ID and CRYPTOMUS_API_KEY from .env, then calls
/v1/payment/services. That endpoint is the authoritative answer to "what does
Cryptomus charge me?" — the public tariffs page renders its tables from an API
that returns nothing, so the dashboard and this tool are the only honest
sources. It also prints each coin's minimum, which matters: some coins have a
minimum far above the store's own MIN_TOPUP.

Read-only. It creates no invoice and moves no money.
"""

import json
import sys
import urllib.error
import urllib.request

from app import config, payments


def call(path: str, body: dict) -> dict:
    raw = json.dumps(body, separators=(",", ":"))
    req = urllib.request.Request(
        f"{config.CRYPTOMUS_BASE.rstrip('/')}{path}",
        data=raw.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "merchant": config.CRYPTOMUS_MERCHANT_ID,
            "sign": payments._cryptomus_sign(raw),
        },
    )
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc)
        except ValueError:
            return {"state": -1, "message": f"HTTP {exc.code}"}
    except OSError as exc:
        return {"state": -1, "message": str(exc)}


def main() -> int:
    if not payments.cryptomus_configured():
        print("CRYPTOMUS_MERCHANT_ID / CRYPTOMUS_API_KEY are not set.")
        print(f"Add them to {config.ENV_FILE_PATH}")
        return 2

    print(f"merchant {config.CRYPTOMUS_MERCHANT_ID}")
    print(f"endpoint {config.CRYPTOMUS_BASE}")

    data = call("/v1/payment/services", {})
    if payments._cm_state(data) != 0:
        print(f"\nREJECTED: {payments._cryptomus_error(data)}")
        print("\nCheck that you used the *payment* API key, not the payout one.")
        return 1

    services = [s for s in (data.get("result") or [])
                if isinstance(s, dict) and s.get("is_available")]
    if not services:
        print("\nAuthenticated, but no payment method is enabled on the "
              "account. Enable some in the Cryptomus dashboard.")
        return 1

    print(f"\n{len(services)} payment methods enabled\n")
    print(f"{'COIN':<10} {'NETWORK':<10} {'FEE %':>7} {'FIXED':>9} "
          f"{'MIN':>14} {'MAX':>16}")
    print("-" * 70)

    percents = []
    for service in sorted(services, key=lambda s: (str(s.get("currency")),
                                                   str(s.get("network")))):
        commission = service.get("commission") or {}
        limit = service.get("limit") or {}
        percent = str(commission.get("percent") or "0")
        percents.append(percent)
        print(f"{str(service.get('currency'))[:10]:<10} "
              f"{str(service.get('network'))[:10]:<10} "
              f"{percent:>7} {str(commission.get('fee_amount') or '0'):>9} "
              f"{_trim(limit.get('min_amount')):>14} "
              f"{_trim(limit.get('max_amount')):>16}")

    spread = sorted(set(percents), key=_as_float)
    print(f"\nCommission: {', '.join(p + '%' for p in spread)}")
    if config.CRYPTOMUS_SUBTRACT >= 100:
        print("CRYPTOMUS_SUBTRACT=100 — the customer pays that fee, so the "
              "full invoice amount reaches your balance.")
    else:
        print(f"CRYPTOMUS_SUBTRACT={config.CRYPTOMUS_SUBTRACT} — you absorb "
              f"{100 - config.CRYPTOMUS_SUBTRACT}% of that fee.")

    _warn_about_minimums(services)
    return 0


def _as_float(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _trim(value) -> str:
    text = str(value or "0")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _warn_about_minimums(services: list):
    """MIN_TOPUP is in fiat and these minimums are per coin, so this is a
    rough comparison — enough to catch an obviously unreachable setting."""
    lowest = min((_as_float((s.get("limit") or {}).get("min_amount"))
                  for s in services), default=0.0)
    if lowest and config.MIN_TOPUP < lowest:
        print(f"\nNote: MIN_TOPUP is {config.MIN_TOPUP} but the cheapest coin "
              f"minimum here is {_trim(lowest)}. Small top-ups will be "
              f"rejected by the gateway for most coins.")


if __name__ == "__main__":
    sys.exit(main())
