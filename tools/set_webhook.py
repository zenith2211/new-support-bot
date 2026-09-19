"""
tools/set_webhook.py — point Telegram at the serverless endpoint, or back.

    python -m tools.set_webhook https://your-app.vercel.app
    python -m tools.set_webhook --show
    python -m tools.set_webhook --delete        # back to long polling

Generates WEBHOOK_SECRET if it is missing and prints it, because Telegram
signs every delivery with it and api/telegram.py refuses updates that are not
signed. Set the same value in the host's environment.

A bot cannot poll and receive a webhook at the same time: setWebhook stops
getUpdates working, and --delete restores it. Deleting is how you move back
to a long-polling host.
"""

import json
import secrets
import sys
import urllib.error
import urllib.request

from app import config


def call(method: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}",
        data=json.dumps(body or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as exc:
        return json.load(exc)
    except OSError as exc:
        return {"ok": False, "description": str(exc)}


def show() -> int:
    data = call("getWebhookInfo")
    if not data.get("ok"):
        print(f"failed: {data.get('description')}")
        return 1
    info = data["result"]
    url = info.get("url") or ""
    print(f"  url                  {url or '(none — long polling)'}")
    print(f"  pending updates      {info.get('pending_update_count')}")
    print(f"  custom certificate   {info.get('has_custom_certificate')}")
    if info.get("last_error_message"):
        print(f"  last error           {info['last_error_message']}")
        print(f"  last error date      {info.get('last_error_date')}")
    else:
        print("  last error           none")
    return 0


def main(argv: list) -> int:
    if not config.BOT_TOKEN:
        print("BOT_TOKEN is not set.")
        return 2

    if "--show" in argv or not argv:
        return show()

    if "--delete" in argv:
        data = call("deleteWebhook", {"drop_pending_updates": False})
        if not data.get("ok"):
            print(f"failed: {data.get('description')}")
            return 1
        print("Webhook removed. getUpdates (long polling) works again.")
        return 0

    base = argv[0].rstrip("/")
    if not base.startswith("https://"):
        print("Telegram only accepts an https:// webhook URL.")
        return 2

    secret = config._env("WEBHOOK_SECRET") or secrets.token_urlsafe(32)
    url = f"{base}/api/telegram"

    data = call("setWebhook", {
        "url": url,
        "secret_token": secret,
        "allowed_updates": ["message", "callback_query", "my_chat_member"],
        "drop_pending_updates": False,
        "max_connections": 40,
    })
    if not data.get("ok"):
        print(f"failed: {data.get('description')}")
        return 1

    print(f"Webhook set to {url}\n")
    if not config._env("WEBHOOK_SECRET"):
        print("Generated a WEBHOOK_SECRET. Set this on the host AND in .env,")
        print("or every update will be rejected as unsigned:\n")
        print(f"  WEBHOOK_SECRET={secret}\n")
    print("Long polling is now disabled for this bot. Undo with --delete.")
    return show()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
