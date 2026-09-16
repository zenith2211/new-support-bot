"""
tools/check_nowpayments.py — verify the NOWPayments key and the minimums.

    python -m tools.check_nowpayments

The minimum is the thing to check. Every coin has its own floor, and for a
store selling items at a dollar or two that floor — not the fee — is what
decides whether the gateway is usable at all. This prints it in both the coin
and your own currency, and compares it with MIN_TOPUP and your cheapest
product.

Read-only. It creates no payment and moves no money.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from app import config, payments, store, util


def call(path: str, auth: bool = True) -> dict:
    headers = {"x-api-key": config.NOWPAYMENTS_API_KEY} if auth else {}
    req = urllib.request.Request(
        f"{config.NOWPAYMENTS_BASE.rstrip('/')}{path}", headers=headers)
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc)
        except ValueError:
            return {"_error": f"HTTP {exc.code}"}
    except OSError as exc:
        return {"_error": str(exc)}


def failed(data: dict) -> str:
    if data.get("_error"):
        return str(data["_error"])
    if data.get("status") is False or data.get("statusCode"):
        return str(data.get("message") or "rejected")
    return ""


def main() -> int:
    coin = config.NOWPAYMENTS_PAY_CURRENCY
    fiat = config.NOWPAYMENTS_CURRENCY

    # 1. Is the API up? This endpoint needs no key, so it separates "their
    #    outage" from "your key is wrong" before we blame the key.
    status = call("/v1/status", auth=False)
    if failed(status):
        print(f"NOWPayments API is not reachable: {failed(status)}")
        return 1
    print(f"api status      {status.get('message')}")

    if not payments.nowpay_configured():
        print("\nNOWPAYMENTS_API_KEY is not set.")
        print(f"Add it to {config.ENV_FILE_PATH}")
        return 2

    # 2. Any authenticated call proves the key. currencies is the cheapest.
    currencies = call("/v1/currencies")
    if failed(currencies):
        print(f"\nKEY REJECTED: {failed(currencies)}")
        print("\nGenerate the key at account.nowpayments.io -> Settings -> "
              "Payments -> API keys,\nand make sure an outcome wallet is set.")
        return 1

    coins = [str(c).lower() for c in (currencies.get("currencies") or [])]
    print(f"key             valid ({len(coins)} currencies enabled)")

    if coins and coin not in coins:
        print(f"\nNOWPAYMENTS_PAY_CURRENCY={coin!r} is not in your enabled "
              f"list.\nEnable it in the dashboard or pick another coin.")
        near = [c for c in coins if c.startswith(coin[:4])][:8]
        if near:
            print(f"Similar enabled coins: {', '.join(near)}")
        return 1
    print(f"pay currency    {coin}  (customers send this)")
    print(f"price currency  {fiat}  (your prices are quoted in this)")

    # 3. The minimum, which is the number that actually matters.
    query = urllib.parse.urlencode({"currency_from": coin,
                                    "currency_to": coin})
    minimum = call(f"/v1/min-amount?{query}")
    if failed(minimum):
        print(f"\nCould not read the minimum: {failed(minimum)}")
        return 1

    min_coin = _as_float(minimum.get("min_amount"))
    print(f"\nminimum payment {_trim(min_coin)} {coin.upper()}")

    min_fiat = _estimate(min_coin, coin, fiat)
    if min_fiat:
        print(f"                ~{_trim(min_fiat)} {fiat.upper()}")

    _compare_with_catalog(min_fiat or min_coin, fiat)
    return 0


def _estimate(amount: float, coin: str, fiat: str) -> float:
    """Convert the coin minimum into your own currency, for comparison."""
    if not amount:
        return 0.0
    query = urllib.parse.urlencode({"amount": amount,
                                    "currency_from": coin,
                                    "currency_to": fiat})
    data = call(f"/v1/estimate?{query}")
    if failed(data):
        return 0.0
    return _as_float(data.get("estimated_amount"))


def _compare_with_catalog(minimum: float, fiat: str):
    """The check that matters: can a customer actually buy your cheapest
    item in one payment?"""
    if not minimum:
        return

    print()
    if config.MIN_TOPUP < minimum:
        print(f"MIN_TOPUP is {_trim(config.MIN_TOPUP)} but the gateway floor "
              f"is ~{_trim(minimum)} {fiat.upper()}.")
        print(f"Raise MIN_TOPUP to at least {_trim(minimum)} or customers "
              f"will hit a gateway error.")
    else:
        print(f"MIN_TOPUP ({_trim(config.MIN_TOPUP)}) clears the gateway "
              f"floor. Good.")

    try:
        store.init()
        priced = [(p.get("name"), _as_float(p.get("price")))
                  for p in store.products.values()
                  if _as_float(p.get("price")) > 0]
    except Exception:                            # noqa: BLE001 - tool, not bot
        return
    if not priced:
        return

    name, cheapest = min(priced, key=lambda row: row[1])
    if cheapest < minimum:
        print(f"\nHeads up: your cheapest product is {util.fmt_money(cheapest)}"
              f" ({name}),\nbelow the ~{_trim(minimum)} {fiat.upper()} "
              f"minimum. Buyers cannot pay for it in a single\npayment — they "
              f"must top up {_trim(minimum)}+ and spend from the wallet.")
    else:
        print(f"Cheapest product ({util.fmt_money(cheapest)}) is above the "
              f"minimum too.")


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _trim(value) -> str:
    text = f"{_as_float(value):.8f}".rstrip("0").rstrip(".")
    return text or "0"


if __name__ == "__main__":
    sys.exit(main())
