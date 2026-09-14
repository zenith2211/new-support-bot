"""
app/shop.py — buying and delivering.

One checkout path, used by both "buy from wallet" and "pay the shortfall then
get the item", so stock accounting and channel posts cannot diverge between
the two. Stock is reserved before the wallet is charged and handed back if the
charge fails, so a failure never silently eats a unit.
"""

import logging
import os
import tempfile

from . import broadcast, config, screens, store, tg, util
from .lang import t
from .msg import Msg
from .view import btn, kb

logger = logging.getLogger(__name__)

# Deliver as a .txt attachment past this many lines, so long batches stay
# readable (and inside Telegram's message limit).
FILE_DELIVERY_THRESHOLD = 6


def quote(pid: str, qty: int, coupon_code: str = "") -> dict:
    """Price a basket without touching anything. -> dict of numbers."""
    product = store.product_get(pid) or {}
    price = float(product.get("price") or 0.0)
    qty = max(int(qty or 1), 1)
    subtotal = round(price * qty, 6)
    discount = 0.0
    coupon = None
    if coupon_code:
        coupon, _err, discount = store.coupon_check(coupon_code, pid, subtotal)
    return {
        "price": price,
        "qty": qty,
        "subtotal": subtotal,
        "discount": round(discount, 6),
        "total": round(subtotal - discount, 6),
        "coupon": coupon["code"] if coupon else "",
    }


def check_qty(product: dict, qty: int) -> tuple[bool, str, dict]:
    """-> (ok, error_key, {min,max,available})"""
    pid = product["id"]
    available = store.stock_count(pid)
    min_qty = max(int(product.get("min_qty") or 1), 1)
    max_qty = max(int(product.get("max_qty") or 1), min_qty)
    limits = {"min": min_qty, "max": max_qty, "available": available}

    if available <= 0:
        return False, "err_no_stock", limits
    if qty < min_qty or qty > max_qty:
        return False, "err_qty_range", limits
    if not store.stock_is_unlimited(pid) and qty > available:
        return False, "err_stock_short", limits
    return True, "", limits


def _payload_lines(product: dict, taken: list) -> list:
    """What the customer actually receives."""
    mode = product.get("stock_mode", "lines")
    if mode == "lines":
        return [line for line in taken if str(line).strip()]
    if mode == "unlimited":
        payload = (product.get("payload") or "").strip()
        return [payload] if payload else []
    return []


async def checkout(user_id, pid: str, qty: int,
                   coupon_code: str = "") -> tuple[dict | None, str]:
    """Charge the wallet and create the order. -> (order, error_key)"""
    product = store.product_get(pid)
    if not product or not product.get("enabled", True):
        return None, "err_not_found"

    ok, error, _limits = check_qty(product, qty)
    if not ok:
        return None, error

    priced = quote(pid, qty, coupon_code)
    if store.balance_of(user_id) + 1e-9 < priced["total"]:
        return None, "low_balance"

    taken = store.stock_take(pid, qty)
    if taken is None:
        return None, "err_no_stock"

    if not store.debit(user_id, priced["total"]):
        store.stock_return(pid, taken)
        return None, "low_balance"

    # Nothing to hand over (manual product, or unlimited with no payload set)
    # means support finishes the order by hand.
    items = _payload_lines(product, taken)
    manual = not items
    user_rec = store.user_get(user_id)

    order = store.order_create(
        user_id=user_id,
        username=user_rec.get("username") or "",
        pid=pid,
        product_name=product.get("name") or "—",
        sku=product.get("sku") or "",
        qty=qty,
        unit_price=priced["price"],
        subtotal=priced["subtotal"],
        discount=priced["discount"],
        total=priced["total"],
        coupon=priced["coupon"],
        status="manual" if manual else "delivered",
        items=items,
        method="wallet",
        delivered=None if manual else util.now_ts(),
    )

    store.record_sale(pid, qty)
    if priced["coupon"]:
        store.coupon_consume(priced["coupon"])

    logger.info("order %s: user=%s product=%s qty=%s total=%s status=%s",
                order["id"], user_id, pid, qty, order["total"], order["status"])
    return order, ""


async def deliver(chat_id, order: dict, lang: str,
                  message: dict | None = None) -> bool:
    """Show the delivery screen, attaching a .txt for large batches."""
    items = [line for line in (order.get("items") or []) if str(line).strip()]
    balance = store.balance_of(order.get("user_id"))

    if len(items) >= FILE_DELIVERY_THRESHOLD:
        slim = dict(order, items=[])
        view = screens.delivered(slim, lang, balance)
        await tg.render(chat_id, view, message)
        await _send_items_file(chat_id, order, lang)
        return True

    view = screens.delivered(order, lang, balance)
    data = await tg.render(chat_id, view, message)
    return bool(data.get("ok"))


async def _send_items_file(chat_id, order: dict, lang: str):
    lines = [
        f"{store.store_name()} — {order.get('product_name')}",
        "=" * 44,
        f"Order:   {order.get('id')}",
        f"Qty:     {order.get('qty')}",
        f"Paid:    {util.fmt_money(order.get('total'))}",
        f"Date:    {util.fmt_date(order.get('created'))}",
        "=" * 44,
        "",
    ]
    for index, line in enumerate(order.get("items") or [], 1):
        lines.append(f"#{index}  {line}")
    lines.extend(["", "Keep this file. Warranty claims need the order id."])

    path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8",
            prefix=f"{order.get('id', 'order')}-",
        ) as fh:
            fh.write("\n".join(lines))
            path = fh.name

        m = Msg()
        m.emoji("key").space().bold(t("delivered_items", lang))
        caption, entities = m.build()
        await tg.send_document(chat_id, path, caption, entities)
    except OSError as exc:
        logger.warning("delivery file failed for %s: %s", order.get("id"), exc)
    finally:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass


async def after_sale(order: dict):
    """Channel post, manual-delivery ping, and the low-stock alert."""
    try:
        await broadcast.new_order(order)
    except Exception as exc:                     # noqa: BLE001
        logger.warning("new_order post failed: %s", exc)

    if order.get("status") == "manual":
        user_rec = store.user_get(order.get("user_id"))
        try:
            await broadcast.admin_manual_delivery(order, user_rec)
        except Exception as exc:                 # noqa: BLE001
            logger.warning("manual delivery ping failed: %s", exc)

    await check_low_stock(order.get("pid"))


async def check_low_stock(pid: str):
    """Post ALMOST GONE once per threshold crossing."""
    product = store.product_get(pid)
    if not product or product.get("stock_mode") == "unlimited":
        return
    count = store.stock_count(pid)
    if count <= 0 or count > config.LOW_STOCK_THRESHOLD:
        if count > config.LOW_STOCK_THRESHOLD and product.get("gone_posted"):
            store.product_save(pid, gone_posted=False)
        return
    if product.get("gone_posted"):
        return

    store.product_save(pid, gone_posted=True)
    try:
        await broadcast.almost_gone(product, count)
        await broadcast.admin_low_stock(product, count)
    except Exception as exc:                     # noqa: BLE001
        logger.warning("low stock post failed: %s", exc)


async def credit_and_continue(topup: dict, lang: str) -> tuple[dict | None, str]:
    """After a top-up is paid: if it was created to buy something, buy it now.
    -> (order, error_key); (None, "") means the wallet was simply funded."""
    pid = topup.get("intent_pid")
    qty = int(topup.get("intent_qty") or 0)
    if not pid or qty <= 0:
        return None, ""
    return await checkout(topup["user_id"], pid, qty,
                          topup.get("intent_coupon") or "")


def sold_out_keyboard(pid: str, lang: str) -> dict:
    return kb(
        [btn(t("btn_products", lang), "nav:products", emoji_name="products")],
        [btn(t("btn_get_alerts", lang), f"pa:{pid}", emoji_name="bell")],
    )
