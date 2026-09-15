"""
tools/switch_bot.py — point this project at a different bot token.

    python -m tools.switch_bot <token>            # check only
    python -m tools.switch_bot <token> --write    # check, then update .env

The useful part is the custom-emoji check. Telegram does not report an error
when a bot is not allowed to send custom emoji — it accepts the message and
silently drops the entities, so the only way to know is to send one and
compare what comes back. This does that before you commit to the token.

The new bot must have been started (press Start / send /start) by at least
one of ADMIN_IDS first, because a bot cannot message anyone who has not.
"""

import json
import re
import sys
import urllib.error
import urllib.request

from app import config


def call(token: str, method: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(body or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as exc:
        return json.load(exc)
    except OSError as exc:
        return {"ok": False, "description": str(exc)}


def identify(token: str) -> dict | None:
    data = call(token, "getMe")
    if not data.get("ok"):
        print(f"  token rejected: {data.get('description')}")
        return None
    me = data["result"]
    print(f"  bot: @{me.get('username')}  (id {me.get('id')}, "
          f"name {me.get('first_name')!r})")
    return me


def custom_emoji_works(token: str, chat_id: int) -> bool | None:
    """-> True allowed, False stripped, None could not test."""
    emoji_id = ""
    try:
        with open("data/emoji.json", encoding="utf-8") as fh:
            emoji_id = next(iter(json.load(fh).values()))
    except (OSError, ValueError, StopIteration):
        pass
    if not emoji_id:
        print("  no data/emoji.json to test with")
        return None

    data = call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": "🎁 custom emoji check",
        "entities": [{"type": "custom_emoji", "offset": 0, "length": 2,
                      "custom_emoji_id": emoji_id}],
    })
    if not data.get("ok"):
        desc = str(data.get("description"))
        if "chat not found" in desc.lower():
            print(f"  cannot reach {chat_id} yet — press Start on the new "
                  f"bot from that account first, then re-run")
        else:
            print(f"  send failed: {desc}")
        return None

    kept = [e for e in (data["result"].get("entities") or [])
            if e.get("type") == "custom_emoji"]
    if kept:
        print("  ALLOWED — the custom emoji survived. Animated emoji will "
              "render for your customers.")
        return True
    print("  STRIPPED — Telegram removed the custom emoji.\n"
          "     This bot's owner still needs Telegram Premium, or the bot\n"
          "     needs a username purchased on Fragment. Create the bot from\n"
          "     the Premium account, not just while logged into it.")
    return False


def write_env(token: str, username: str) -> bool:
    path = config.ENV_FILE_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"  could not read {path}: {exc}")
        return False

    seen = {"BOT_TOKEN": False, "BOT_LINK": False}
    out = []
    for line in lines:
        if re.match(r"\s*BOT_TOKEN\s*=", line):
            out.append(f"BOT_TOKEN={token}\n")
            seen["BOT_TOKEN"] = True
        elif re.match(r"\s*BOT_LINK\s*=", line) and username:
            out.append(f"BOT_LINK=https://t.me/{username}\n")
            seen["BOT_LINK"] = True
        else:
            out.append(line)
    for key, found in seen.items():
        if not found:
            value = (token if key == "BOT_TOKEN"
                     else f"https://t.me/{username}")
            out.append(f"{key}={value}\n")

    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(out)
    print(f"  wrote BOT_TOKEN and BOT_LINK to {path}")
    return True


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2
    token = argv[0].strip()
    write = "--write" in argv

    print("1. identifying the token")
    me = identify(token)
    if not me:
        return 1

    print("\n2. can this bot send custom emoji?")
    verdict = None
    for admin_id in config.ADMINS:
        verdict = custom_emoji_works(token, admin_id)
        if verdict is not None:
            break
    if verdict is None:
        print("     (untested — press Start on the new bot, then re-run)")

    if not write:
        print("\nNothing changed. Re-run with --write to update .env.")
        return 0

    print("\n3. updating .env")
    if not write_env(token, me.get("username", "")):
        return 1
    print("\nDone. Restart the bot (start.bat, or python bot.py).")
    print("Your catalog, posters, users and orders live in data/ and are "
          "untouched — the new bot picks them all up.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
