#!/usr/bin/env python3
"""Put a clean, bold title on a real frame and write a YouTube thumbnail.

Formats (--format):
  landscape  1280x720. Safe zone = frame minus 64 px. The bottom-right corner
             (where YouTube prints the video's duration) is kept clear: the
             script warns if a title or label enters it.
  short      1080x1920. Feeds crop a Short's thumbnail to about 5:4, so the safe
             zone is the centred 1080x1350 band minus a 90 px margin. Titles and
             the subject must sit inside it.

Two engines draw the same layout:
  pillow   soft blurred shadows and smooth retouches (needs Pillow:
           python3 -m pip install Pillow)
  ffmpeg   ffmpeg filters only (drawtext, overlay, geq); works everywhere ffmpeg
           has drawtext. --engine auto (default) uses Pillow when it imports.

The frame is cropped to the target shape around --focus (the subject's x,y in
the source frame, 0-1), given a light colour pop (or --grade), a scrim behind
the text, then the title in the font, white with a black outline and a shadow;
one line may take the accent colour. The output is re-encoded until it is under
2 MB. The fitted font size is printed: to keep a SET uniform, compose the
longest title first and pass its size to the rest as --max-size.

Usage:
  compose_thumbnail.py FRAME --format landscape --title "WORTH|IT?" --accent-line 1 \
      --pos top --focus 0.5,0.45 --guides --out thumb.jpg
  compose_thumbnail.py a.jpg --split b.jpg --format landscape --title VS --pos center \
      --max-size 110 --label "OLD@0.2,0.2" --label "NEW@0.8,0.2" --scrim none --out split.jpg

Options:
  --title        lines separated by "|", drawn as typed (--upper forces capitals)
  --font         a font file path, "condensed", "heavy", or part of an installed
                 font's file name. Default: settings youtube.thumbnail_font, else
                 the first condensed bold font installed
  --text-color   title colour (default #FFFFFF); --accent colours --accent-line
  --pos          top|center|bottom inside the safe zone
  --align        left|center|right. left/right keep the text in a --column-wide
                 strip on that side (put it opposite the face) with a wedge scrim
  --focus x,y    subject position in the source frame (default 0.5,0.5)
  --zoom Z       crop tighter than the frame (>1) so the subject is bigger
  --rotate D     0|90|180|270 counter-clockwise, for cameras mounted upside down
  --blur-box     x0,y0,x1,y1 (0-1, source frame): blur a serial number or label.
                 Repeatable; prefix "2:" to target the --split frame
  --fill-box     same syntax: paint the box with the colours around it. Use it for
                 text on a lit screen (a blur leaves a grey smear there)
  --split B      two-up: FRAME left, B right (stacked on a short), accent divider
  --focus2/--zoom2/--rotate2   the same for the --split frame; --split-at 0.5
  --label        "TEXT@x,y": a word centred at canvas x,y (0-1), e.g. a name
                 beside each product. Repeatable. --label-size (share of canvas
                 height, default 0.22), --label-color (default: --accent)
  --subject      x0,y0,x1,y1 of a subject WIDER than the crop (two products side
                 by side in a 16:9 frame going vertical): the band is scaled to
                 the canvas width over a blurred copy. --subject-y sets its centre
  --scrim        auto|none: darken behind the text (auto) or not
  --max-size     largest font size in px (default 24% of the short side; also pins the size when it fits)
  --grade S      0 = off. 1-1.5 brightens a dim frame: shadow lift, highlight
                 roll-off, vibrance, soft vignette. Use when it warns "dark"
  --no-pop       skip the default small saturation/contrast/sharpen bump
  --guides       also write <out>_guides.jpg (green = safe zone, red = feed crop
                 or duration badge) and <out>_feed200.jpg (what the feed shows,
                 200 px wide). Look at both
  --engine       auto|pillow|ffmpeg

Prints one JSON object (paths, sizes, font, brightness, warnings) on stdout.
Each run is appended to compose-log.txt next to the output, so a restyle is the
same command with different flags.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import thumbkit as tk  # noqa: E402

DARK_LUMA = 90   # centre brightness below this reads dark at feed size


def parse_xy(spec: str, name: str) -> tuple:
    try:
        x, y = (float(v) for v in spec.split(","))
    except ValueError:
        raise SystemExit(f"{name} {spec!r}: expected x,y between 0 and 1")
    return x, y


def rotated_size(path: Path, rotate: int) -> tuple:
    w, h = tk.image_size(path)
    return (h, w) if rotate in (90, 270) else (w, h)


def split_boxes(specs: list, second: bool) -> list:
    return [s[2:] if s.startswith("2:") else s for s in specs if s.startswith("2:") == second]


def source(path: Path, rotate: int, blur: list, fill: list, second: bool = False) -> dict:
    if not path.is_file():
        raise SystemExit(f"{path}: no such file")
    sw, sh = rotated_size(path, rotate)
    return {"path": str(path), "rotate": rotate, "size": (sw, sh),
            "blur": [tk.norm_box(s, sw, sh) for s in split_boxes(blur, second)],
            "fill": [tk.norm_box(s, sw, sh) for s in split_boxes(fill, second)]}


def stroke_for(size: int) -> int:
    return max(3, size // 11)


def line_height(fm, text: str, size: int) -> float:
    h = fm.cap_height(size)
    if any(c in "gjpqy,;" for c in text):
        h += fm.descent(size)
    return h


def block_metrics(fm, lines: list, size: int) -> tuple:
    """(width, height, gap) of the inked block including the outline."""
    st = stroke_for(size)
    gap = round(size * 0.22)
    w = max(fm.width(ln, size) for ln in lines) + 2 * st
    h = sum(line_height(fm, ln, size) for ln in lines) + gap * (len(lines) - 1) + 2 * st
    return w, h, gap


def fit_size(fm, lines: list, max_w: float, max_h: float, max_size: int) -> int:
    size = max_size
    w, _, _ = block_metrics(fm, lines, size)
    if w > max_w:
        size = max(24, int(size * max_w / w))
        while size > 24 and block_metrics(fm, lines, size)[0] > max_w:
            size -= 2
    while size > 24 and block_metrics(fm, lines, size)[1] > max_h:
        size -= 2
    return size


def layout_block(fm, lines: list, size: int, colors: list, x0: float, x1: float, y_top: float,
                 align: str) -> dict:
    st = stroke_for(size)
    _, _, gap = block_metrics(fm, lines, size)
    out, y = [], y_top + st
    for ln, color in zip(lines, colors):
        w = fm.width(ln, size)
        if align == "left":
            x = x0 + st
        elif align == "right":
            x = x1 - st - w
        else:
            x = x0 + ((x1 - x0) - w) / 2
        baseline = y + fm.cap_height(size)
        out.append({"text": ln, "x": round(x), "baseline": round(baseline),
                    "top": round(baseline - fm.cap_height(size)), "color": color})
        y += line_height(fm, ln, size) + gap
    return {"size": size, "stroke": st, "lines": out}


def build_plan(a, font: Path) -> tuple:
    W, H = tk.FORMATS[a.format]
    fx, fy = parse_xy(a.focus, "--focus")
    warnings = []
    if a.split and a.subject:
        raise SystemExit("--split and --subject can't be combined")
    src = source(a.frame, a.rotate, a.blur_box, a.fill_box)
    plan = {"W": W, "H": H, "format": a.format, "font": str(font), "pop": a.pop, "grade": a.grade,
            "sources": [src], "divider": None, "subject": None, "scrim": None, "blocks": []}
    accent = "#" + "%02X%02X%02X" % tk.hex_rgb(a.accent)
    if a.split:
        src2 = source(a.split, a.rotate2, a.blur_box, a.fill_box, second=True)
        stacked = a.format == "short"
        cut = round((H if stacked else W) * a.split_at)
        d1, d2 = ((0, 0, W, cut), (0, cut, W, H - cut)) if stacked else ((0, 0, cut, H), (cut, 0, W - cut, H))
        f2 = parse_xy(a.focus2, "--focus2")
        src["crop"], src["dest"] = tk.crop_box(*src["size"], d1[2], d1[3], fx, fy, a.zoom), d1
        src2["crop"], src2["dest"] = tk.crop_box(*src2["size"], d2[2], d2[3], *f2, a.zoom2), d2
        plan["sources"].append(src2)
        plan["divider"] = {"stacked": stacked, "cut": cut, "thick": max(6, round(W * 0.011)),
                           "thin": max(2, round(W * 0.0035)), "color": accent}
    elif a.subject:
        sw, sh = src["size"]
        band = tk.norm_box(a.subject, sw, sh)
        bh = round((band[3] - band[1]) * W / (band[2] - band[0]))
        if bh > H:
            raise SystemExit("--subject box is taller than the canvas once scaled to its width; widen it")
        top = min(max(0, round(a.subject_y * H) - bh // 2), H - bh)
        plan["subject"] = {"band": band, "top": top, "height": bh,
                           "feather": min(max(24, bh // 18), bh // 2),
                           "bg_crop": tk.crop_box(sw, sh, W, H, fx, fy)}
    else:
        src["crop"], src["dest"] = tk.crop_box(*src["size"], W, H, fx, fy, a.zoom), (0, 0, W, H)

    fm = tk.metrics(str(font))
    lines = [ln.strip() for ln in a.title.split("|") if ln.strip()]
    if a.upper:
        lines = [ln.upper() for ln in lines]
    x0, y0, x1, y1 = tk.safe_zone(a.format, W, H)
    cx0, cx1 = x0, x1
    if a.align != "center":
        col = round((x1 - x0) * a.column)
        cx0, cx1 = (x0, x0 + col) if a.align == "left" else (x1 - col, x1)
    text_rect = None
    title_size = None
    if lines:
        title_size = fit_size(fm, lines, cx1 - cx0, y1 - y0, a.max_size or round(min(W, H) * 0.24))
        bw, bh, _ = block_metrics(fm, lines, title_size)
        y_top = {"top": y0, "center": y0 + ((y1 - y0) - bh) / 2, "bottom": y1 - bh}[a.pos]
        tx0 = {"left": cx0, "center": cx0 + ((cx1 - cx0) - bw) / 2, "right": cx1 - bw}[a.align]
        text_rect = (tx0, y_top, tx0 + bw, y_top + bh)
        colors = [accent if i == a.accent_line else a.text_color for i in range(len(lines))]
        plan["blocks"].append(layout_block(fm, lines, title_size, colors, cx0, cx1, y_top, a.align))
        if plan["subject"]:
            s = plan["subject"]
            if tk.overlaps(text_rect, (0, s["top"], W, s["top"] + s["height"])):
                warnings.append("title overlaps the subject band - change --pos or --subject-y")
        if a.format == "landscape" and tk.overlaps(text_rect, tk.badge_zone(W, H)):
            warnings.append("title enters the duration-badge corner - shorten it or move --pos")
        if a.scrim == "auto":
            if a.align == "center":
                pad = round(title_size * 0.9)
                plan["scrim"] = {"kind": "band", "top": max(0, round(y_top - pad)),
                                 "bot": min(H, round(y_top + bh + pad))}
            else:
                pad = round(title_size * 0.7)
                edge = min(W, cx1 + pad) if a.align == "left" else max(0, cx0 - pad)
                plan["scrim"] = {"kind": a.align, "edge": edge}
    label_rects = []
    lsize = round(H * a.label_size)
    for spec in a.label:
        text, _, at = spec.rpartition("@")
        if not text:
            raise SystemExit(f"--label {spec!r}: expected TEXT@x,y")
        lx, ly = parse_xy(at, "--label")
        lw, lh, _ = block_metrics(fm, [text], lsize)
        want = (lx * W - lw / 2, ly * H - lh / 2)
        bx = min(max(x0, want[0]), x1 - lw)
        by = min(max(y0, want[1]), y1 - lh)
        if (round(bx), round(by)) != (round(want[0]), round(want[1])):
            warnings.append(f"label {text!r} was moved into the safe zone - check it still sits beside its subject")
        rect = (bx, by, bx + lw, by + lh)
        if text_rect and tk.overlaps(rect, text_rect):
            warnings.append(f"label {text!r} overlaps the title")
        if a.format == "landscape" and tk.overlaps(rect, tk.badge_zone(W, H)):
            warnings.append(f"label {text!r} enters the duration-badge corner")
        plan["blocks"].append(layout_block(fm, [text], lsize, [a.label_color or accent], bx, bx + lw, by, "center"))
        label_rects.append(tuple(round(v) for v in rect))
    plan["guides"] = {"safe": (x0, y0, x1, y1), "column": (cx0, y0, cx1, y1) if a.align != "center" else None,
                      "labels": label_rects}
    return plan, title_size, (lsize if a.label else None), warnings


def write_guides(plan: dict, out: Path) -> tuple:
    """<out>_guides.jpg with the zones drawn, and <out>_feed200.jpg: the card as
    the feed shows it (Shorts cropped to 5:4, landscape with a duration badge)."""
    W, H = plan["W"], plan["H"]
    g = plan["guides"]
    boxes = [(g["safe"], "0x00FF00", 4)]
    if g["column"]:
        boxes.append((g["column"], "0xFF00FF", 3))
    if plan["format"] == "short":
        y0, y1 = tk.feed_crop(W, H)
        boxes.append(((0, y0, W, y1), "0xFF3333", 4))
    else:
        boxes.append((tk.badge_zone(W, H), "0xFF3333", 4))
    if plan["subject"]:
        s = plan["subject"]
        boxes.append(((0, s["top"], W, s["top"] + s["height"]), "0x3399FF", 4))
    boxes += [(r, "0xFF00FF", 3) for r in g["labels"]]
    vf = ",".join(f"drawbox=x={round(b[0])}:y={round(b[1])}:w={round(b[2] - b[0])}:h={round(b[3] - b[1])}"
                  f":color={c}:t={t}" for b, c, t in boxes)
    guides = out.with_name(out.stem + "_guides.jpg")
    tk.ffrun(["-i", str(out), "-vf", vf, "-frames:v", "1", "-update", "1", "-q:v", "4", str(guides)], "guides")
    feed = out.with_name(out.stem + "_feed200.jpg")
    if plan["format"] == "short":
        y0, y1 = tk.feed_crop(W, H)
        vf = f"crop={W}:{y1 - y0}:0:{y0},scale=200:-2:flags=area"
    else:
        bw, bh = round(W * 0.085), round(H * 0.075)
        bx, by = W - bw - round(W * 0.012), H - bh - round(H * 0.02)
        vf = f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=black@0.85:t=fill"
        if tk.drawtext_ok():
            txt = out.with_name(out.stem + "_badge.txt")
            txt.write_text("12:34", encoding="utf-8")
            vf += "," + tk.drawtext(txt, Path(plan["font"]), round(bh * 0.62), "white",
                                    f"{bx}+({bw}-tw)/2", f"{by}+({bh}-th)/2")
        vf += ",scale=200:-2:flags=area"
    tk.ffrun(["-i", str(out), "-vf", vf, "-frames:v", "1", "-update", "1", "-q:v", "3", str(feed)], "feed preview")
    badge_txt = out.with_name(out.stem + "_badge.txt")
    if badge_txt.exists():
        badge_txt.unlink()
    return guides, feed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 epilog="Full option notes: see the top of this file.")
    ap.add_argument("frame", type=Path)
    ap.add_argument("--format", choices=tk.FORMATS, required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--font", default=None)
    ap.add_argument("--text-color", default="#FFFFFF")
    ap.add_argument("--accent", default="#FFD400")
    ap.add_argument("--accent-line", type=int, default=None)
    ap.add_argument("--pos", choices=["top", "center", "bottom"], default="top")
    ap.add_argument("--align", choices=["left", "center", "right"], default="center")
    ap.add_argument("--column", type=float, default=0.45)
    ap.add_argument("--focus", default="0.5,0.5")
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0)
    ap.add_argument("--blur-box", action="append", default=[])
    ap.add_argument("--fill-box", action="append", default=[])
    ap.add_argument("--split", type=Path, default=None)
    ap.add_argument("--focus2", default="0.5,0.5")
    ap.add_argument("--zoom2", type=float, default=1.0)
    ap.add_argument("--rotate2", type=int, choices=[0, 90, 180, 270], default=0)
    ap.add_argument("--split-at", type=float, default=0.5)
    ap.add_argument("--label", action="append", default=[])
    ap.add_argument("--label-size", type=float, default=0.22)
    ap.add_argument("--label-color", default=None)
    ap.add_argument("--subject", default=None)
    ap.add_argument("--subject-y", type=float, default=0.58)
    ap.add_argument("--scrim", choices=["auto", "none"], default="auto")
    ap.add_argument("--upper", action="store_true")
    ap.add_argument("--max-size", type=int, default=None)
    ap.add_argument("--no-pop", dest="pop", action="store_false")
    ap.add_argument("--grade", type=float, default=0.0)
    ap.add_argument("--guides", action="store_true")
    ap.add_argument("--engine", choices=["auto", "pillow", "ffmpeg"], default="auto")
    ap.add_argument("--max-bytes", type=int, default=tk.MAX_BYTES)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    font, font_origin = tk.find_font(a.font)
    engine = a.engine
    if engine == "auto":
        engine = "pillow" if tk.pillow_available() else "ffmpeg"
    if engine == "pillow" and not tk.pillow_available():
        raise SystemExit(f"--engine pillow needs Pillow: {tk.PIP_HINT}  (or use --engine ffmpeg)")
    if engine == "ffmpeg" and not tk.drawtext_ok():
        raise SystemExit("This ffmpeg has no drawtext filter (built without libfreetype). Install Pillow "
                         f"({tk.PIP_HINT}) or an ffmpeg build with drawtext.")
    if a.engine == "auto" and engine == "ffmpeg":
        print(f"note: using the ffmpeg engine. Optional, for softer shadows: {tk.PIP_HINT}", file=sys.stderr)

    plan, title_size, label_size, warnings = build_plan(a, font)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.out.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise SystemExit("--out must end in .jpg or .png")
    if engine == "pillow":
        import render_pillow as render
    else:
        import render_ffmpeg as render
    render.render(plan, a.out, a.max_bytes)

    luma = tk.mean_luma(a.out)
    if luma < DARK_LUMA:
        warnings.append(f"reads dark at feed size (centre brightness {luma:.0f} < {DARK_LUMA}): "
                        + ("re-run with --grade 1.5 and compare side by side" if a.grade <= 0
                           else "still dark after --grade; try a brighter frame"))
    result = {"out": str(a.out.resolve()), "bytes": a.out.stat().st_size, "size": [plan["W"], plan["H"]],
              "engine": engine, "font": str(font), "font_from": font_origin, "title_px": title_size,
              "label_px": label_size, "centre_luma": round(luma), "warnings": warnings}
    if a.guides:
        g, f = write_guides(plan, a.out)
        result["guides"], result["feed200"] = str(g.resolve()), str(f.resolve())
    with open(a.out.parent / "compose-log.txt", "a", encoding="utf-8") as log:
        argv = ["python3", str(Path(__file__).resolve())] + sys.argv[1:]
        log.write(f"{_dt.datetime.now():%Y-%m-%d %H:%M}  {a.out.name}\n  {shlex.join(argv)}\n")
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
