#!/usr/bin/env python3
"""Pillow renderer for compose_thumbnail.py (Pillow only, no numpy).

Same layout plan as render_ffmpeg.py; softer shadows and smoother retouches.
Imported lazily by compose_thumbnail.py when Pillow is installed
(python3 -m pip install Pillow). Not meant to be run directly.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat


def _load(src: dict) -> Image.Image:
    im = Image.open(src["path"]).convert("RGB")
    if src["rotate"]:
        im = im.rotate(src["rotate"], expand=True)
    for box in src["blur"]:
        im.paste(im.crop(box).filter(ImageFilter.GaussianBlur(24)), box[:2])
    for box in src["fill"]:
        _fill_box(im, box)
    return im


def _vgradient(size: tuple, start: int, span: int) -> Image.Image:
    """L image: 0 above row `start`, ramping to 255 over `span` rows, 255 below."""
    w, h = size
    col = Image.new("L", (1, h))
    col.putdata([max(0, min(255, round(255 * (y - start) / max(1, span)))) for y in range(h)])
    return col.resize((w, h))


def _fill_box(im: Image.Image, box: tuple) -> None:
    """Paint `box` with the colours just above and below it, blended top to
    bottom, edges feathered: hides text on a screen without a grey smear."""
    sw, sh = im.size
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    ring = max(4, round(0.08 * min(w, h)))
    f = max(2, round(0.10 * min(w, h)))

    def med(region):
        rx0, ry0, rx1, ry1 = max(0, region[0]), max(0, region[1]), min(sw, region[2]), min(sh, region[3])
        if rx1 <= rx0 or ry1 <= ry0:
            return None
        return tuple(int(v) for v in ImageStat.Stat(im.crop((rx0, ry0, rx1, ry1))).median)

    sides = med((x0 - ring, y0 - ring, x1 + ring, y1 + ring)) or (0, 0, 0)
    top = med((x0, y0 - ring, x1, y0)) or sides
    bot = med((x0, y1, x1, y1 + ring)) or sides
    wx0, wy0 = max(0, x0 - 2 * f), max(0, y0 - 2 * f)
    wx1, wy1 = min(sw, x1 + 2 * f), min(sh, y1 + 2 * f)
    size = (wx1 - wx0, wy1 - wy0)
    patch = Image.composite(Image.new("RGB", size, bot), Image.new("RGB", size, top),
                            _vgradient(size, y0 - wy0, h))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle((x0 - f - wx0, y0 - f - wy0, x1 + f - wx0, y1 + f - wy0), fill=255)
    im.paste(patch, (wx0, wy0), mask.filter(ImageFilter.GaussianBlur(max(1, f / 2))))


def _crop_resize(im: Image.Image, crop: tuple, dw: int, dh: int) -> Image.Image:
    x, y, w, h = crop
    return im.crop((x, y, x + w, y + h)).resize((dw, dh), Image.LANCZOS)


def _grade(im: Image.Image, s: float, pop: bool) -> Image.Image:
    lut = []
    for i in range(256):
        y = (i / 255) ** (1.0 / (1.0 + 0.22 * s))
        if y > 0.72:
            y = 0.72 + (y - 0.72) * (1 - 0.30 * s)
        lut.append(round(min(1.0, y * (1 + 0.02 * s)) * 255))
    im = im.point(lut * 3)
    im = ImageEnhance.Color(im).enhance(1 + 0.15 * s)
    W, H = im.size
    radial = Image.radial_gradient("L").resize((W, H))   # 0 at the centre, 255 at the edge midpoints
    vig = radial.point(lambda v: round(255 * (1 - 0.13 * s * max(0.0, v / 255 - 0.55) ** 1.6)))
    im = ImageChops.multiply(im, Image.merge("RGB", (vig, vig, vig)))
    if pop:
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))
    return im


def _scrim(sc: dict, W: int, H: int) -> Image.Image:
    if sc["kind"] == "band":
        top, bot = sc["top"], sc["bot"]
        span = max(1, bot - top)
        col = [0] * H
        for y in range(top, bot):
            col[y] = round(120 * (1 - abs(2 * (y - top) / span - 1)) ** 0.7)
        a = Image.new("L", (1, H))
        a.putdata(col)
        a = a.resize((W, H))
    else:
        e = sc["edge"]
        row = []
        for x in range(W):
            if sc["kind"] == "left":
                row.append(round(150 * (1 - x / max(1, e)) ** 1.2) if x < e else 0)
            else:
                row.append(round(150 * ((x - e) / max(1, W - e)) ** 1.2) if x >= e else 0)
        a = Image.new("L", (W, 1))
        a.putdata(row)
        a = a.resize((W, H))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.putalpha(a)
    return layer


def _text(im: Image.Image, block: dict, font_path: str) -> None:
    size, st = block["size"], block["stroke"]
    font = ImageFont.truetype(font_path, size)
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    off = max(1, size // 14)
    for ln in block["lines"]:
        sd.text((ln["x"] + off, ln["baseline"] + off), ln["text"], font=font, anchor="ls",
                fill=(0, 0, 0, 190), stroke_width=st, stroke_fill=(0, 0, 0, 190))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, size // 16))))
    d = ImageDraw.Draw(im)
    for ln in block["lines"]:
        d.text((ln["x"], ln["baseline"]), ln["text"], font=font, anchor="ls", fill=ln["color"],
               stroke_width=st, stroke_fill="#000000")


def render(plan: dict, out: Path, max_bytes: int) -> None:
    W, H = plan["W"], plan["H"]
    srcs = plan["sources"]
    if plan["subject"]:
        s = plan["subject"]
        im = _load(srcs[0])
        canvas = _crop_resize(im, s["bg_crop"], W, H).filter(ImageFilter.GaussianBlur(28))
        canvas = ImageEnhance.Brightness(canvas).enhance(0.5)
        band = im.crop(s["band"]).resize((W, s["height"]), Image.LANCZOS)
        bh, fe = s["height"], s["feather"]
        col = Image.new("L", (1, bh))
        col.putdata([round(255 * max(0.0, min(1.0, min(y, bh - 1 - y) / fe))) for y in range(bh)])
        canvas.paste(band, (0, s["top"]), col.resize((W, bh)))
    else:
        canvas = Image.new("RGB", (W, H))
        for src in srcs:
            dx, dy, dw, dh = src["dest"]
            canvas.paste(_crop_resize(_load(src), src["crop"], dw, dh), (dx, dy))
        d = plan["divider"]
        if d:
            draw = ImageDraw.Draw(canvas)
            for w, c in ((d["thick"], "#000000"), (d["thin"], d["color"])):
                if d["stacked"]:
                    draw.rectangle((0, d["cut"] - w // 2, W, d["cut"] - w // 2 + w - 1), fill=c)
                else:
                    draw.rectangle((d["cut"] - w // 2, 0, d["cut"] - w // 2 + w - 1, H), fill=c)
    if plan["grade"] > 0:
        canvas = _grade(canvas, plan["grade"], plan["pop"])
    elif plan["pop"]:
        canvas = ImageEnhance.Color(canvas).enhance(1.15)
        canvas = ImageEnhance.Contrast(canvas).enhance(1.06)
        canvas = canvas.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))
    im = canvas.convert("RGBA")
    if plan["scrim"]:
        im.alpha_composite(_scrim(plan["scrim"], W, H))
    for block in plan["blocks"]:
        _text(im, block, plan["font"])
    final = im.convert("RGB")
    if out.suffix.lower() == ".png":
        final.save(out, optimize=True)
        if out.stat().st_size > max_bytes:
            out.unlink()
            raise SystemExit("the PNG is over 2 MB; write a .jpg instead")
        return
    for q in range(95, 55, -5):
        final.save(out, quality=q, optimize=True, subsampling=0)
        if out.stat().st_size <= max_bytes:
            return
    raise SystemExit(f"{out}: could not get it under {max_bytes} bytes")
