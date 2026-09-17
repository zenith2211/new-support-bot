"""
app/tg.py — thin async Telegram Bot API client.

Raw aiohttp on purpose: no python-telegram-bot, so the bot runs on any
Python 3.11+ (including 3.13/3.14) with two dependencies.

The important piece here is render(): one function that puts a "view"
(text + entities + keyboard + optional poster) on screen, whether that means
sending a new message, editing text in place, or swapping a photo's media.
"""

import asyncio
import logging
import os

import aiohttp

from . import config
from .msg import strip_entities, u16

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

_session: aiohttp.ClientSession | None = None
_me: dict = {}


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
            timeout=aiohttp.ClientTimeout(total=60, connect=10),
        )
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


# ─── RAW CALL ─────────────────────────────────────────────────
async def api(method: str, payload: dict | None = None,
              files: dict | None = None, quiet: bool = False) -> dict:
    """Call a Bot API method. Returns the full response envelope.

    Retries once on 429 using Telegram's retry_after, and on transient
    network errors, so a hiccup never kills the polling loop. `quiet`
    suppresses the failure log for calls whose failure is expected and
    handled by the caller.
    """
    url = f"{config.API}/{method}"
    payload = {k: v for k, v in (payload or {}).items() if v is not None}

    for attempt in (1, 2):
        try:
            session = await get_session()
            if files:
                # Read the bytes up front and close the handles. Handing an
                # open file to FormData leaks the descriptor, which on Windows
                # means the caller cannot delete its own temp file afterwards.
                form = aiohttp.FormData()
                for key, value in payload.items():
                    form.add_field(
                        key,
                        value if isinstance(value, str) else _json(value),
                    )
                for key, path in files.items():
                    with open(path, "rb") as fh:
                        blob = fh.read()
                    form.add_field(key, blob,
                                   filename=os.path.basename(path))
                async with session.post(url, data=form) as resp:
                    data = await resp.json(content_type=None)
            else:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json(content_type=None)
        except OSError as exc:
            logger.warning("%s could not read upload: %s", method, exc)
            return {"ok": False, "description": str(exc)}
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if attempt == 2:
                logger.warning("%s network error: %s", method, exc)
                return {"ok": False, "description": str(exc)}
            await asyncio.sleep(1)
            continue

        if data.get("ok"):
            return data

        desc = str(data.get("description", ""))
        if data.get("error_code") == 429 and attempt == 1:
            wait = float(data.get("parameters", {}).get("retry_after", 1))
            logger.info("rate limited on %s, sleeping %ss", method, wait)
            await asyncio.sleep(min(wait, 30) + 0.5)
            continue

        # "message is not modified" is normal when a refresh changes nothing.
        if not quiet and "not modified" not in desc:
            logger.warning("%s failed: %s", method, desc)
        return data

    return {"ok": False, "description": "unreachable"}


def _json(value) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


#: Set once we learn whether Telegram lets this bot use custom emoji.
#: None = not yet observed, True/False = confirmed by a real send.
CUSTOM_EMOJI_ALLOWED: bool | None = None
_custom_emoji_warned = False


def note_custom_emoji_result(sent: list, result: dict):
    """Detect Telegram silently dropping our custom emoji.

    Per the Bot API docs, custom emoji entities "can only be used by bots
    that purchased additional usernames on Fragment or in the messages
    directly sent by the bot ... if the owner of the bot has a Telegram
    Premium subscription". A bot without that privilege gets no error: the
    message is accepted and the entities are quietly stripped, so the only
    way to notice is to compare what came back.
    """
    global CUSTOM_EMOJI_ALLOWED, _custom_emoji_warned
    asked = [e for e in (sent or []) if e.get("type") == "custom_emoji"]
    if not asked:
        return
    echoed = (result.get("entities") or result.get("caption_entities") or [])
    kept = [e for e in echoed if e.get("type") == "custom_emoji"]

    CUSTOM_EMOJI_ALLOWED = bool(kept)
    if not kept and not _custom_emoji_warned:
        _custom_emoji_warned = True
        logger.warning(
            "Telegram stripped all %d custom emoji from a message: this bot "
            "is not allowed to use them, so every emoji arrives as plain "
            "unicode. Per the Bot API, custom emoji need either a username "
            "purchased for the bot on Fragment, or the bot's OWNER (the "
            "account that created it in @BotFather) to have Telegram "
            "Premium. Nothing in this code can work around it.",
            len(asked))


def _is_entity_error(data: dict) -> bool:
    desc = str(data.get("description", "")).upper()
    return any(
        token in desc
        for token in ("ENTITY", "CUSTOM_EMOJI", "EMOJI_INVALID",
                      "ENTITIES_TOO_LONG")
    )


def _is_photo_source_error(data: dict) -> bool:
    desc = str(data.get("description", "")).upper()
    return any(
        token in desc
        for token in ("WEBPAGE_CURL_FAILED", "WEBPAGE_MEDIA_EMPTY",
                      "IMAGE_PROCESS_FAILED", "WRONG_FILE_IDENTIFIER",
                      "FILE_REFERENCE", "PHOTO_INVALID")
    )


def _poster_kind(poster: str) -> str:
    """'local' for a file on disk, 'remote' for a URL or file_id."""
    if not poster:
        return ""
    if poster.startswith(("http://", "https://")):
        return "remote"
    candidate = poster
    if not os.path.isabs(candidate):
        candidate = os.path.join(config.BASE_DIR, poster)
    return "local" if os.path.exists(candidate) else "remote"


def _poster_path(poster: str) -> str:
    if os.path.isabs(poster):
        return poster
    return os.path.join(config.BASE_DIR, poster)


# ─── SENDING ──────────────────────────────────────────────────
async def send_message(chat_id, text: str, entities: list | None = None,
                       keyboard: dict | None = None,
                       reply_to: int | None = None,
                       disable_preview: bool = True) -> dict:
    payload = {
        "chat_id": chat_id,
        "text": text[:TEXT_LIMIT],
        "entities": entities or None,
        "reply_markup": keyboard,
        "link_preview_options": {"is_disabled": True} if disable_preview else None,
        "reply_parameters": (
            {"message_id": reply_to, "allow_sending_without_reply": True}
            if reply_to else None
        ),
    }
    data = await api("sendMessage", payload)
    if not data.get("ok") and _is_entity_error(data) and entities:
        payload["entities"] = strip_entities(entities) or None
        data = await api("sendMessage", payload)
    if data.get("ok"):
        note_custom_emoji_result(entities, data.get("result") or {})
    return data


async def send_photo(chat_id, poster: str, caption: str = "",
                     entities: list | None = None,
                     keyboard: dict | None = None) -> dict:
    payload = {
        "chat_id": chat_id,
        "caption": caption[:CAPTION_LIMIT] or None,
        "caption_entities": entities or None,
        "reply_markup": keyboard,
    }
    kind = _poster_kind(poster)
    if kind == "local":
        data = await api("sendPhoto", payload, files={"photo": _poster_path(poster)})
    else:
        data = await api("sendPhoto", {**payload, "photo": poster})

    if not data.get("ok") and _is_entity_error(data) and entities:
        payload["caption_entities"] = strip_entities(entities) or None
        if kind == "local":
            data = await api("sendPhoto", payload,
                             files={"photo": _poster_path(poster)})
        else:
            data = await api("sendPhoto", {**payload, "photo": poster})
    if data.get("ok"):
        note_custom_emoji_result(entities, data.get("result") or {})
    return data


async def send_document(chat_id, path: str, caption: str = "",
                        entities: list | None = None,
                        keyboard: dict | None = None) -> dict:
    return await api(
        "sendDocument",
        {
            "chat_id": chat_id,
            "caption": caption[:CAPTION_LIMIT] or None,
            "caption_entities": entities or None,
            "reply_markup": keyboard,
        },
        files={"document": path},
    )


async def edit_text(chat_id, message_id: int, text: str,
                    entities: list | None = None,
                    keyboard: dict | None = None) -> dict:
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:TEXT_LIMIT],
        "entities": entities or None,
        "reply_markup": keyboard,
        "link_preview_options": {"is_disabled": True},
    }
    data = await api("editMessageText", payload)
    if not data.get("ok") and _is_entity_error(data) and entities:
        payload["entities"] = strip_entities(entities) or None
        data = await api("editMessageText", payload)
    return data


async def edit_media(chat_id, message_id: int, poster: str, caption: str,
                     entities: list | None = None,
                     keyboard: dict | None = None) -> dict:
    """Swap a photo message's image AND caption in one call."""
    media = {
        "type": "photo",
        "media": poster,
        "caption": caption[:CAPTION_LIMIT],
        "caption_entities": entities or [],
    }
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "media": media,
        "reply_markup": keyboard,
    }
    data = await api("editMessageMedia", payload)
    if not data.get("ok") and _is_entity_error(data) and entities:
        media["caption_entities"] = strip_entities(entities)
        data = await api("editMessageMedia", payload)
    return data


async def edit_caption(chat_id, message_id: int, caption: str,
                       entities: list | None = None,
                       keyboard: dict | None = None) -> dict:
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "caption": caption[:CAPTION_LIMIT],
        "caption_entities": entities or None,
        "reply_markup": keyboard,
    }
    data = await api("editMessageCaption", payload)
    if not data.get("ok") and _is_entity_error(data) and entities:
        payload["caption_entities"] = strip_entities(entities) or None
        data = await api("editMessageCaption", payload)
    return data


async def edit_markup(chat_id, message_id: int,
                      keyboard: dict | None = None) -> dict:
    return await api("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": keyboard,
    })


async def delete_message(chat_id, message_id: int) -> dict:
    return await api("deleteMessage", {
        "chat_id": chat_id, "message_id": message_id,
    })


async def answer_callback(cq_id: str, text: str = "",
                          alert: bool = False) -> dict:
    return await api("answerCallbackQuery", {
        "callback_query_id": cq_id,
        "text": text[:200] or None,
        "show_alert": alert or None,
    })


# ─── VIEW RENDERING ───────────────────────────────────────────
async def render(chat_id, view, message: dict | None = None) -> dict:
    """Put a View on screen.

    message = the message being replaced (from a callback query) or None to
    send fresh. Photo<->text transitions are handled by deleting and resending,
    photo->photo by editMessageMedia, text->text by editMessageText.
    """
    text, entities, keyboard, poster = (
        view.text, view.entities, view.keyboard, view.poster
    )

    # A caption caps at 1024 UTF-16 units (an emoji costs two), so a long
    # screen drops its poster rather than being rejected by Telegram.
    if poster and u16(text) > CAPTION_LIMIT:
        poster = None

    if message is None:
        if poster:
            data = await send_photo(chat_id, poster, text, entities, keyboard)
            if data.get("ok") or not _is_photo_source_error(data):
                return data
            logger.info("poster rejected (%s), sending as text",
                        data.get("description"))
        return await send_message(chat_id, text, entities, keyboard)

    message_id = message.get("message_id")
    was_photo = bool(message.get("photo"))

    if poster and was_photo and _poster_kind(poster) == "remote":
        data = await edit_media(chat_id, message_id, poster, text,
                                entities, keyboard)
        if data.get("ok"):
            return data
        if "not modified" in str(data.get("description", "")):
            return data

    elif poster and was_photo:
        # Local file: caption-only edit keeps the existing image, which is
        # correct when the poster did not change between the two views.
        data = await edit_caption(chat_id, message_id, text, entities, keyboard)
        if data.get("ok") or "not modified" in str(data.get("description", "")):
            return data

    elif not poster and not was_photo:
        data = await edit_text(chat_id, message_id, text, entities, keyboard)
        if data.get("ok") or "not modified" in str(data.get("description", "")):
            return data

    # Type changed (or the edit failed) — replace the message.
    await delete_message(chat_id, message_id)
    if poster:
        data = await send_photo(chat_id, poster, text, entities, keyboard)
        if data.get("ok") or not _is_photo_source_error(data):
            return data
    return await send_message(chat_id, text, entities, keyboard)


# ─── MISC ─────────────────────────────────────────────────────
async def get_me() -> dict:
    global _me
    if not _me:
        data = await api("getMe")
        _me = data.get("result", {}) if data.get("ok") else {}
    return _me


async def bot_username() -> str:
    me = await get_me()
    return me.get("username", "")


async def bot_link() -> str:
    if config.BOT_LINK:
        return config.BOT_LINK
    username = await bot_username()
    return f"https://t.me/{username}" if username else ""


async def is_member(chat_id: int, user_id) -> bool:
    """True when the user is in the channel (or the check cannot be made).

    Fails open on purpose: a config mistake must never lock the shop. Note the
    most common mistake is the bot not being an admin in the chat, which makes
    every check fail and so waves everyone through — hence the warning.
    """
    if not chat_id:
        return True
    data = await api("getChatMember", {"chat_id": chat_id, "user_id": user_id})
    if not data.get("ok"):
        logger.warning("membership check failed for chat %s: %s — is the bot "
                       "an admin there?", chat_id, data.get("description"))
        return True  # never lock users out because of a config mistake
    status = data.get("result", {}).get("status", "")
    return status in ("creator", "administrator", "member", "restricted")


async def missing_chats(chats: list, user_id) -> list:
    """Which of `chats` the user has not joined. Empty list = let them in."""
    missing = []
    for chat in chats or []:
        if not await is_member(chat.get("id"), user_id):
            missing.append(chat)
    return missing


async def set_my_commands(commands: list, scope: dict | None = None,
                          quiet: bool = False) -> dict:
    return await api("setMyCommands", {
        "commands": commands,
        "scope": scope,
    }, quiet=quiet)
