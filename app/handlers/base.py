"""
app/handlers/base.py — the per-update context object.

Every handler takes a Ctx. It carries who is asking, in what language, and
which message (if any) should be edited rather than replaced — which is what
lets one handler serve both a slash command and a button press.
"""

from dataclasses import dataclass, field

from .. import config, screens, store, tg
from ..lang import t
from ..view import View


@dataclass
class Ctx:
    chat_id: int
    user_id: int
    tg_user: dict = field(default_factory=dict)
    lang: str = "en"
    message: dict | None = None       # message to edit (callback queries)
    cq_id: str | None = None
    is_admin: bool = False

    @property
    def user(self) -> dict:
        return store.user_get(self.user_id)

    @property
    def balance(self) -> float:
        return store.balance_of(self.user_id)

    def s(self, key: str, **kwargs) -> str:
        return t(key, self.lang, **kwargs)


def ctx_from_message(message: dict) -> Ctx:
    tg_user = message.get("from") or {}
    user_id = tg_user.get("id")
    return Ctx(
        chat_id=(message.get("chat") or {}).get("id"),
        user_id=user_id,
        tg_user=tg_user,
        lang=store.user_lang(user_id),
        message=None,
        is_admin=config.is_admin(user_id),
    )


def ctx_from_callback(cq: dict) -> Ctx:
    tg_user = cq.get("from") or {}
    message = cq.get("message") or {}
    user_id = tg_user.get("id")
    return Ctx(
        chat_id=(message.get("chat") or {}).get("id"),
        user_id=user_id,
        tg_user=tg_user,
        lang=store.user_lang(user_id),
        message=message or None,
        cq_id=cq.get("id"),
        is_admin=config.is_admin(user_id),
    )


async def show(ctx: Ctx, view: View) -> dict:
    """Render a view, editing ctx.message when there is one."""
    return await tg.render(ctx.chat_id, view, ctx.message)


async def send_new(ctx: Ctx, view: View) -> dict:
    """Render a view as a brand new message, never editing."""
    return await tg.render(ctx.chat_id, view, None)


async def toast(ctx: Ctx, text: str = "", alert: bool = False):
    if ctx.cq_id:
        await tg.answer_callback(ctx.cq_id, text, alert)


async def error(ctx: Ctx, key: str, alert: bool = True, **kwargs):
    """Report a problem: a toast on a button press, a message otherwise."""
    text = ctx.s(key, **kwargs)
    if ctx.cq_id:
        await toast(ctx, text, alert)
        return
    await send_new(ctx, screens.simple("warn", ctx.s("err_generic"), text,
                                       ctx.lang))
