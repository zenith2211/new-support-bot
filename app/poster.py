"""
app/poster.py — generate product banners locally.

A storefront looks half-finished without art, but the artwork has to be
*yours*: reusing a competitor's banner puts their logo in your shop. So this
draws banners from your own store name and product data.

The layout follows what makes a storefront banner read well: a dark base with
a coloured glow, one large hero graphic on a glossy podium, a short headline
with an accent word, a row of feature cards, and a price badge. The hero is
the product's own emoji rendered in full colour, which is why these look like
art rather than a text dump.

Pillow only. If Pillow is missing the module degrades to disabled rather than
breaking the bot.
"""

import logging
import os
import re
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

# (base, accent, light, deep) — deep is used for shadows and the podium.
PALETTES = [
    ((8, 14, 12),  (0, 214, 129), (176, 255, 219), (0, 96, 60)),    # emerald
    ((8, 12, 22),  (56, 138, 255), (180, 214, 255), (20, 56, 130)),  # azure
    ((16, 10, 24), (168, 92, 255), (222, 195, 255), (72, 32, 128)),  # violet
    ((22, 14, 8),  (255, 158, 44), (255, 222, 176), (128, 70, 10)),  # amber
    ((6, 18, 20),  (0, 209, 214), (170, 246, 249), (0, 92, 96)),    # teal
    ((20, 8, 14),  (255, 74, 122), (255, 190, 208), (128, 22, 50)),  # rose
]

_BOLD = ("C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/segoeuib.ttf",
         "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/impact.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
_SEMI = ("C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/segoeuib.ttf",
         "C:/Windows/Fonts/arialbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
_BOOK = ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf")
_EMOJI = ("C:/Windows/Fonts/seguiemj.ttf",
          "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
          "/System/Library/Fonts/Apple Color Emoji.ttc")


def _pick(paths, size: int):
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _font(size: int, weight: str = "bold"):
    return _pick({"bold": _BOLD, "semi": _SEMI}.get(weight, _BOOK), size)


def _emoji_font(size: int):
    """Segoe UI Emoji only has bitmap strikes at certain sizes; 109 is the
    one that scales cleanly, so render there and resize."""
    for path in _EMOJI:
        if os.path.exists(path):
            for trial in (size, 109, 96, 64):
                try:
                    return ImageFont.truetype(path, trial), trial
                except OSError:
                    continue
    return None, 0


def _palette(seed: str) -> tuple:
    return PALETTES[sum(ord(c) for c in str(seed)) % len(PALETTES)]


def _mix(a, b, ratio: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * ratio) for i in range(3))


def _overlay():
    """A transparent layer to draw translucent things on.

    ImageDraw.Draw(img, "RGBA") *overwrites* the target pixel including its
    alpha — it does not blend — so a fill like (255,255,255,16) lands as a
    near-invisible-alpha white pixel that turns solid white on RGB export.
    Everything translucent is therefore drawn on its own layer and merged
    with alpha_composite, which does blend.
    """
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)


# ─── TEXT HELPERS ─────────────────────────────────────────────
def _tracked(draw, xy, text: str, font, fill, tracking: int = 0):
    """Draw text with extra letter spacing (small-caps labels need it)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


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
                current = ""
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        lines = [str(text)[:18]]
    # ellipsis if we dropped anything
    if len(" ".join(lines)) < len(text.strip()):
        while (draw.textlength(lines[-1] + "…", font=font) > max_width
               and " " in lines[-1]):
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def split_name(name: str) -> tuple[str, str, str]:
    """A long product name into (headline, subtitle, badge).

    'Spotify Premium Account – 3 Months Access (7 Day Warranty)'
      -> ('Spotify Premium Account', '3 Months Access', '7 Day Warranty')
    """
    name = str(name or "Product").strip()
    badge = ""
    match = re.search(r"\(([^)]{2,28})\)\s*$", name)
    if match:
        badge = match.group(1).strip()
        name = name[:match.start()].strip()

    subtitle = ""
    for sep in ("–", "—", " - ", "|", ":"):
        if sep in name:
            head, _, tail = name.partition(sep)
            if len(head.strip()) >= 4 and tail.strip():
                name, subtitle = head.strip(), tail.strip()
                break
    return name, subtitle, badge


# ─── PAINTING BLOCKS ──────────────────────────────────────────
def _background(base, accent, deep) -> "Image.Image":
    img = Image.new("RGB", (WIDTH, HEIGHT), base)
    draw = ImageDraw.Draw(img)

    top = _mix(base, (255, 255, 255), 0.04)
    bottom = _mix(base, (0, 0, 0), 0.35)
    for y in range(HEIGHT):
        draw.line([(0, y), (WIDTH, y)], fill=_mix(top, bottom, y / HEIGHT))

    # faint diagonal mesh, blurred so it reads as texture
    mesh = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    mdraw = ImageDraw.Draw(mesh)
    for offset in range(-HEIGHT, WIDTH, 46):
        mdraw.line([(offset, 0), (offset + HEIGHT, HEIGHT)],
                   fill=(*accent, 16), width=1)
    img = Image.alpha_composite(img.convert("RGBA"),
                                mesh.filter(ImageFilter.GaussianBlur(0.6)))

    # two soft accent blooms
    glow = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([760, -220, 1460, 440], fill=accent)
    gdraw.ellipse([-260, 470, 360, 980], fill=deep)
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    img = Image.blend(img.convert("RGB"), glow, 0.38).convert("RGBA")

    # vignette
    vign = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(vign).ellipse([-280, -240, WIDTH + 280, HEIGHT + 240],
                                 fill=255)
    vign = vign.filter(ImageFilter.GaussianBlur(190))
    shade = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    shade.putalpha(Image.eval(vign, lambda v: 255 - v))
    img = Image.alpha_composite(img, shade)

    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, 4], fill=accent)
    draw.rectangle([0, HEIGHT - 4, WIDTH, HEIGHT], fill=deep)
    return img


def _hero(img, emoji_char: str, accent, light, deep,
          cx: int = 985, cy: int = 300, tile: int = 286):
    """Glossy tile carrying the product emoji, on a glowing podium."""
    # radial glow behind everything
    glow = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [cx - tile, cy - tile, cx + tile, cy + tile], fill=accent)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img.alpha_composite(Image.merge("RGBA", (*glow.split(),
                                             glow.convert("L").point(
                                                 lambda v: int(v * 0.75)))))

    half = tile // 2
    box = [cx - half, cy - half, cx + half, cy + half]

    # drop shadow
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [box[0] + 10, box[1] + 26, box[2] + 10, box[3] + 34],
        radius=62, fill=(0, 0, 0, 170))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)))

    # the tile itself: light at the top, dark at the bottom
    face = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(face)
    for y in range(tile):
        fdraw.line([(0, y), (tile, y)],
                   fill=(*_mix((250, 252, 255), (196, 206, 220),
                               y / tile), 255))
    mask = Image.new("L", (tile, tile), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile - 1, tile - 1],
                                           radius=58, fill=255)
    face.putalpha(mask)

    # inner top highlight
    gloss = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).rounded_rectangle(
        [12, 8, tile - 12, tile // 2], radius=48, fill=(255, 255, 255, 90))
    face.alpha_composite(gloss.filter(ImageFilter.GaussianBlur(16)))
    img.paste(face, (box[0], box[1]), face)

    rim, rdraw = _overlay()
    rdraw.rounded_rectangle(box, radius=58, outline=(*light, 130), width=3)
    img.alpha_composite(rim)

    # the emoji, rendered in colour and fitted to the tile
    target = int(tile * 0.56)
    _glyph(img, emoji_char, cx - target // 2, cy - target // 2, target)

    # podium: sits directly under the tile so the two read as one object
    pod_y = cy + half + 16
    podium, pdraw = _overlay()
    pod_box = [cx - half - 40, pod_y - 26, cx + half + 40, pod_y + 26]
    pdraw.ellipse(pod_box, fill=(*deep, 210))
    pdraw.ellipse(pod_box, outline=(*accent, 255), width=5)
    img.alpha_composite(podium.filter(ImageFilter.GaussianBlur(1.5)))

    # Light spill below the podium. A mirrored copy of the tile was the
    # obvious choice but a flipped square reads as a pale block rather than a
    # reflection, so this is a blurred ellipse of the tile's own colour.
    spill, sdraw = _overlay()
    sdraw.ellipse([cx - half + 18, pod_y + 12, cx + half - 18, pod_y + 78],
                  fill=(*light, 46))
    img.alpha_composite(spill.filter(ImageFilter.GaussianBlur(26)))
    return img


def _fit(draw, text: str, font, max_width: int) -> str:
    """Shorten text with an ellipsis so it cannot escape its card."""
    text = str(text)
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def _glyph(img, char: str, x: int, y: int, size: int):
    """Paste one colour emoji, scaled to `size`."""
    efont, rendered = _emoji_font(size)
    if not efont or not char:
        return
    pad = 10
    layer = Image.new("RGBA", (rendered * 2 + pad,) * 2, (0, 0, 0, 0))
    try:
        ImageDraw.Draw(layer).text((pad, pad), char, font=efont,
                                   embedded_color=True)
    except TypeError:                            # very old Pillow
        ImageDraw.Draw(layer).text((pad, pad), char, font=efont)
    bbox = layer.getbbox()
    if not bbox:
        return
    glyph = layer.crop(bbox)
    scale = size / max(glyph.size)
    glyph = glyph.resize((max(int(glyph.width * scale), 1),
                          max(int(glyph.height * scale), 1)), Image.LANCZOS)
    img.alpha_composite(glyph, (x, y))


def _cards(img, items: list, accent, light, top: int = 492):
    """Row of feature cards: small colour glyph, then a two-line label."""
    f_title = _font(20, "semi")
    f_sub = _font(16, "book")
    card_w, card_h, gap = 150, 108, 15
    inner = card_w - 34

    plate, pdraw = _overlay()
    x = 72
    for _glyph_char, _title, _sub in items[:4]:
        box = [x, top, x + card_w, top + card_h]
        pdraw.rounded_rectangle(box, radius=18, fill=(255, 255, 255, 20),
                                outline=(*light, 55), width=2)
        pdraw.rounded_rectangle([x + 16, top, x + card_w - 16, top + 4],
                                radius=2, fill=(*accent, 230))
        x += card_w + gap
    img.alpha_composite(plate)

    text_layer, tdraw = _overlay()
    x = 72
    for glyph_char, title, sub in items[:4]:
        _glyph(img, glyph_char, x + 17, top + 18, 32)
        tdraw.text((x + 17, top + 58),
                   _fit(tdraw, title, f_title, inner),
                   font=f_title, fill=(255, 255, 255, 255))
        if sub:
            tdraw.text((x + 17, top + 81),
                       _fit(tdraw, sub, f_sub, inner),
                       font=f_sub, fill=(*light, 220))
        x += card_w + gap
    img.alpha_composite(text_layer)
    return img


def _badge_strip(img, entries: list, accent, light, y: int = 640):
    layer, draw = _overlay()
    font = _font(18, "book")
    draw.line([(72, y - 16), (WIDTH - 72, y - 16)], fill=(*light, 45), width=1)
    x = 72
    for index, text in enumerate(entries[:4]):
        if index:
            draw.text((x, y), "|", font=font, fill=(*light, 85))
            x += 24
        draw.ellipse([x, y + 7, x + 9, y + 16], fill=(*accent, 255))
        x += 17
        draw.text((x, y), text, font=font, fill=(*light, 235))
        x += int(draw.textlength(text, font=font)) + 20
    img.alpha_composite(layer)
    return img


# ─── PUBLIC API ───────────────────────────────────────────────
def _features(product: dict) -> list:
    from . import store as store_mod
    headline, _sub, _badge = split_name(product.get("name") or "")
    instant = product.get("delivery_mode", "instant") == "instant"

    items = [
        ("⚡", "Instant" if instant else "Manual",
         "Delivery" if instant else "By support"),
        ("💳", "Wallet", "Payment"),
    ]
    if product.get("warranty"):
        # "7 Day Warranty" -> title "7 Day", sub "Warranty": the word would
        # otherwise be repeated and overflow the card.
        span = re.sub(r"\s*warrant\w*\s*", " ", str(product["warranty"]),
                      flags=re.I).strip()
        items.insert(1, ("🛡", util.clip(span or "Covered", 12), "Warranty"))
    tiers = store_mod.bulk_tiers(product)
    if tiers:
        items.append(("🌊", f"Bulk x{tiers[0]['qty']}+", "Cheaper per unit"))
    elif product.get("sku"):
        items.append(("🏷", "Verified", str(product["sku"])[:14]))
    items.append(("🎧", "Support", "In this chat"))
    return items


def generate(product: dict, store_name: str = "", out_dir: str = "") -> str:
    """Draw a banner for one product. Returns the file path, or "" on failure."""
    if not AVAILABLE:
        return ""

    from . import emoji as emo
    raw_name = str(product.get("name") or "Product")
    headline, subtitle, badge = split_name(raw_name)
    base, accent, light, deep = _palette(product.get("id") or raw_name)
    hero_char = emo.char(product.get("emoji") or "box")

    try:
        img = _background(base, accent, deep)
        img = _hero(img, hero_char, accent, light, deep)
        draw = ImageDraw.Draw(img)

        # brand line
        f_brand = _font(23, "semi")
        label = (store_name or config.STORE_NAME or "Store").upper()
        end = _tracked(draw, (74, 62), label, f_brand, light,
                       tracking=2)
        draw.rectangle([74, 96, end - 2, 99], fill=accent)

        # headline, wrapped, with the last word accented
        f_title = _font(74)
        lines = _wrap(draw, headline, f_title, 620, max_lines=2)
        y = 160 if len(lines) > 1 else 196
        for index, line in enumerate(lines):
            last = index == len(lines) - 1
            if last and len(lines) > 1 and len(line.split()) <= 2:
                draw.text((72, y), line, font=f_title, fill=accent)
            elif last and " " in line:
                head, _, tail = line.rpartition(" ")
                draw.text((72, y), head + " ", font=f_title,
                          fill=(255, 255, 255))
                draw.text((72 + draw.textlength(head + " ", font=f_title), y),
                          tail, font=f_title, fill=accent)
            else:
                draw.text((72, y), line, font=f_title, fill=(255, 255, 255))
            y += f_title.size + 6

        # badge pill taken out of the product name
        if badge:
            f_badge = _font(20, "semi")
            bw = int(draw.textlength(badge.upper(), font=f_badge)) + 34
            draw.rounded_rectangle([72, y + 10, 72 + bw, y + 50], radius=20,
                                   fill=accent)
            draw.text((72 + 17, y + 19), badge.upper(), font=f_badge,
                      fill=_mix(base, (0, 0, 0), 0.2))
            y += 58
        else:
            y += 8

        # subtitle
        f_sub = _font(29, "book")
        tail_text = subtitle or "Pay from your wallet — delivered in this chat."
        for line in _wrap(draw, tail_text, f_sub, 600, max_lines=2):
            draw.text((72, y), line, font=f_sub, fill=light)
            y += f_sub.size + 6

        img = _cards(img, _features(product), accent, light)

        # price badge, top right — clear of the hero tile and its podium
        price = util.fmt_money(product.get("price"))
        f_price = _font(46)
        pw = int(draw.textlength(price, font=f_price)) + 56
        x0, y0, y1 = WIDTH - 72 - pw, 50, 128

        shadow, sdraw = _overlay()
        sdraw.rounded_rectangle([x0, y0 + 8, WIDTH - 72, y1 + 10], radius=22,
                                fill=(0, 0, 0, 160))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))

        pill, pdraw = _overlay()
        pdraw.rounded_rectangle([x0, y0, WIDTH - 72, y1], radius=22,
                                fill=(*accent, 255))
        pdraw.text((x0 + 28, y0 + 14), price, font=f_price,
                   fill=(*_mix(base, (0, 0, 0), 0.25), 255))
        img.alpha_composite(pill)
        draw = ImageDraw.Draw(img)

        img = _badge_strip(img, [
            "Instant top-up",
            "Delivered in chat",
            "Order id on every sale",
        ], accent, light)

        target = out_dir or tempfile.gettempdir()
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target,
                            f"poster-{product.get('id', 'product')}.png")
        img.convert("RGB").save(path, "PNG", optimize=True)
        return path
    except Exception as exc:                     # noqa: BLE001
        logger.warning("poster generation failed for %s: %s",
                       product.get("id"), exc)
        return ""


def generate_banner(title: str, subtitle: str, seed: str = "",
                    emoji_char: str = "", out_dir: str = "") -> str:
    """A generic screen banner (start, wallet, orders …)."""
    if not AVAILABLE:
        return ""
    base, accent, light, deep = _palette(seed or title)
    try:
        img = _background(base, accent, deep)
        if emoji_char:
            img = _hero(img, emoji_char, accent, light, deep,
                        cx=1000, cy=330, tile=248)
        draw = ImageDraw.Draw(img)

        f_brand = _font(23, "semi")
        label = (config.STORE_NAME or "Store").upper()
        end = _tracked(draw, (74, 62), label, f_brand, light,
                       tracking=2)
        draw.rectangle([74, 96, end - 2, 99], fill=accent)

        f_title = _font(88)
        lines = _wrap(draw, title, f_title, 640, max_lines=2)
        y = 250 if len(lines) == 1 else 208
        for line in lines:
            draw.text((72, y), line, font=f_title, fill=(255, 255, 255))
            y += f_title.size + 6

        draw.rectangle([72, y + 16, 268, y + 22], fill=accent)
        f_sub = _font(31, "book")
        for line in _wrap(draw, subtitle, f_sub, 620, max_lines=2):
            draw.text((72, y + 54), line, font=f_sub, fill=light)
            y += f_sub.size + 4

        img = _badge_strip(img, [
            "Instant delivery",
            "Wallet payments",
            "Support in this chat",
        ], accent, light)

        target = out_dir or tempfile.gettempdir()
        os.makedirs(target, exist_ok=True)
        slug = "".join(c if c.isalnum() else "-"
                       for c in (seed or title).lower())[:40]
        path = os.path.join(target, f"banner-{slug}.png")
        img.convert("RGB").save(path, "PNG", optimize=True)
        return path
    except Exception as exc:                     # noqa: BLE001
        logger.warning("banner generation failed: %s", exc)
        return ""
