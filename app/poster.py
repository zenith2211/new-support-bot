"""
app/poster.py — generate product banners locally.

A storefront looks half-finished without art, but the artwork has to be
*yours*: reusing a competitor's banner puts their logo in your shop. So this
draws clean banners from your own store name and product data — dark
background, accent glow, product title, feature chips, price badge — and the
result installs like any other poster.

Pillow only. If Pillow is missing the module degrades to disabled rather
than breaking the bot.
"""

import logging
import os
import tempfile

from . import config, util

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    AVAILABLE = True
except ImportError:                              # pragma: no cover
    AVAILABLE = False
    logger.info("Pillow not installed — poster generation disabled")

WIDTH, HEIGHT = 1280, 720

# Accent palettes, picked per product so a catalog does not look monotonous.
PALETTES = [
    ((16, 24, 22), (0, 200, 120), (140, 255, 200)),     # green
    ((14, 18, 32), (60, 130, 255), (150, 200, 255)),    # blue
    ((26, 16, 32), (180, 90, 255), (220, 180, 255)),    # violet
    ((30, 20, 14), (255, 150, 40), (255, 210, 150)),    # amber
    ((10, 26, 28), (0, 200, 210), (150, 240, 245)),     # teal
    ((30, 14, 20), (255, 80, 120), (255, 180, 200)),    # rose
]

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
_FONT_REGULAR = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _font(size: int, bold: bool = True):
    for path in (_FONT_CANDIDATES if bold else _FONT_REGULAR):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _palette(seed: str) -> tuple:
    return PALETTES[sum(ord(c) for c in str(seed)) % len(PALETTES)]


def _wrap(draw, text: str, font, max_width: int, max_lines: int = 2) -> list:
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        # add an ellipsis if anything was dropped
        joined = " ".join(lines)
        if len(joined) < len(text):
            while (draw.textlength(lines[-1] + "…", font=font) > max_width
                   and " " in lines[-1]):
                lines[-1] = lines[-1].rsplit(" ", 1)[0]
            lines[-1] += "…"
    return lines


def _background(base, accent, light) -> "Image.Image":
    img = Image.new("RGB", (WIDTH, HEIGHT), base)
    draw = ImageDraw.Draw(img)

    # vertical gradient
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        draw.line(
            [(0, y), (WIDTH, y)],
            fill=(
                int(base[0] + (base[0] + 14) * ratio),
                int(base[1] + (base[1] + 14) * ratio),
                int(base[2] + (base[2] + 18) * ratio),
            ),
        )

    # accent glow, blurred so it reads as light rather than a shape
    glow = Image.new("RGB", (WIDTH, HEIGHT), base)
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([WIDTH - 520, -260, WIDTH + 190, 450], fill=accent)
    gdraw.ellipse([-240, HEIGHT - 300, 320, HEIGHT + 190],
                  fill=tuple(c // 3 for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    img = Image.blend(img, glow, 0.55)

    draw = ImageDraw.Draw(img)
    # thin accent rules top and bottom
    draw.rectangle([0, 0, WIDTH, 5], fill=accent)
    draw.rectangle([0, HEIGHT - 5, WIDTH, HEIGHT], fill=tuple(
        int(c * 0.6) for c in accent))
    return img


def _chip(draw, x: int, y: int, text: str, font, accent, light) -> int:
    pad_x, pad_y = 20, 12
    width = int(draw.textlength(text, font=font)) + pad_x * 2
    height = font.size + pad_y * 2
    draw.rounded_rectangle([x, y, x + width, y + height], radius=height // 2,
                           fill=(255, 255, 255, 18),
                           outline=accent, width=2)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=light)
    return x + width + 14


def generate(product: dict, store_name: str = "",
             out_dir: str = "") -> str:
    """Draw a banner for one product. Returns the file path, or "" on failure."""
    if not AVAILABLE:
        return ""

    name = str(product.get("name") or "Product")
    base, accent, light = _palette(product.get("id") or name)

    try:
        img = _background(base, accent, light)
        draw = ImageDraw.Draw(img, "RGBA")

        f_store = _font(34)
        f_title = _font(78)
        f_chip = _font(26, bold=False)
        f_price = _font(64)
        f_small = _font(26, bold=False)

        # store name, top left
        label = (store_name or config.STORE_NAME or "Store").upper()
        draw.text((72, 64), label, font=f_store, fill=light)
        draw.rectangle([72, 108, 72 + int(draw.textlength(label, f_store)), 112],
                       fill=accent)

        # product title
        lines = _wrap(draw, name, f_title, WIDTH - 420, max_lines=2)
        y = 210 if len(lines) > 1 else 250
        for line in lines:
            draw.text((72, y), line, font=f_title, fill=(255, 255, 255))
            y += f_title.size + 12

        # feature chips from the product's own fields
        chips = []
        if product.get("warranty"):
            chips.append(str(product["warranty"]))
        mode = product.get("delivery_mode", "instant")
        chips.append("Instant delivery" if mode == "instant"
                     else "Manual delivery")
        from . import store as store_mod
        if store_mod.bulk_tiers(product):
            chips.append(store_mod.bulk_label(product))
        if product.get("sku"):
            chips.append(str(product["sku"]))

        x = 72
        chip_y = min(y + 26, HEIGHT - 210)
        for chip in chips[:4]:
            x = _chip(draw, x, chip_y, chip, f_chip, accent, light)

        # price badge, bottom right
        price = util.fmt_money(product.get("price"))
        pw = int(draw.textlength(price, font=f_price)) + 68
        draw.rounded_rectangle(
            [WIDTH - 72 - pw, HEIGHT - 190, WIDTH - 72, HEIGHT - 76],
            radius=26, fill=accent)
        draw.text((WIDTH - 72 - pw + 34, HEIGHT - 175), price,
                  font=f_price, fill=(10, 14, 16))

        draw.text((72, HEIGHT - 120),
                  "Pay from wallet · delivered in chat",
                  font=f_small, fill=light)

        target = out_dir or tempfile.gettempdir()
        os.makedirs(target, exist_ok=True)
        path = os.path.join(
            target, f"poster-{product.get('id', 'product')}.png")
        img.save(path, "PNG", optimize=True)
        return path
    except Exception as exc:                     # noqa: BLE001
        logger.warning("poster generation failed for %s: %s",
                       product.get("id"), exc)
        return ""


def generate_banner(title: str, subtitle: str, seed: str = "",
                    out_dir: str = "") -> str:
    """A generic screen banner (start, wallet, orders …)."""
    if not AVAILABLE:
        return ""
    base, accent, light = _palette(seed or title)
    try:
        img = _background(base, accent, light)
        draw = ImageDraw.Draw(img, "RGBA")
        f_title = _font(88)
        f_sub = _font(34, bold=False)

        lines = _wrap(draw, title, f_title, WIDTH - 300, max_lines=2)
        y = 250 if len(lines) == 1 else 200
        for line in lines:
            draw.text((72, y), line, font=f_title, fill=(255, 255, 255))
            y += f_title.size + 10
        draw.rectangle([72, y + 18, 320, y + 24], fill=accent)
        draw.text((72, y + 56), subtitle, font=f_sub, fill=light)

        target = out_dir or tempfile.gettempdir()
        os.makedirs(target, exist_ok=True)
        slug = "".join(c if c.isalnum() else "-"
                       for c in (seed or title).lower())[:40]
        path = os.path.join(target, f"banner-{slug}.png")
        img.save(path, "PNG", optimize=True)
        return path
    except Exception as exc:                     # noqa: BLE001
        logger.warning("banner generation failed: %s", exc)
        return ""
