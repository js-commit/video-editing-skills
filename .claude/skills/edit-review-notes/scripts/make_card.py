#!/usr/bin/env python3
"""Make the two cards review notes ask for most, with ffmpeg only.

    make_card.py shot IMAGE -o card.mp4 [--size 1920x1080] [--fps 30] [--dur 5]
    make_card.py text "Big line" "smaller line" ... -o card.png|card.mov
                 [--size 1920x1080] [--fps 30] [--dur 5] [--align left|right|center]
                 [--fontfile F] [--scale 1.0]

shot  a screenshot or photo as a full-frame clip: the whole picture, enlarged
      to fit, over a blurred and darkened copy of itself (a tall phone
      screenshot gets no black bars and is never stretched). H.264.
text  a text panel on a transparent background, stacked lines (the first
      one big, the rest smaller) on a dark translucent box. .png = one
      frame-sized RGBA image (a talking-head-ffmpeg recipe overlay); .mov =
      ProRes 4444 with alpha for a DaVinci Resolve track above the b-roll.
      --align puts the panel on the side away from the face: read the frame
      under the slot first.

--size / --fps should match the timeline (Resolve) or recipe canvas. Prints
the output path. Exit codes: 0 ok, 1 bad input or ffmpeg failed.
"""
from __future__ import annotations

import argparse
import platform
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))

from vidkit import media  # noqa: E402

MAC_FONTS = ["/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc",
             "/System/Library/Fonts/SFNS.ttf"]
WIN_FONTS = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
LINUX_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"]


def font_file(explicit):
    if explicit:
        return explicit
    cands = {"Darwin": MAC_FONTS, "Windows": WIN_FONTS}.get(platform.system(), LINUX_FONTS)
    return next((f for f in cands if Path(f).exists()), None)


def ff_path(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:")


def run(cmd):
    r = media.run(cmd)
    if getattr(r, "returncode", 0) != 0:
        sys.exit("ffmpeg failed: " + " ".join(cmd[:6]) + " ...")


def shot(args, w, h):
    img = Path(args.image).expanduser()
    if not img.is_file():
        sys.exit(f"no such image: {img}")
    fg_w, fg_h = int(w * 0.86), int(h * 0.86)
    graph = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=40,"
             f"eq=brightness=-0.18[bg];"
             f"[0:v]scale={fg_w}:{fg_h}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p,fps={args.fps}[v]")
    run([media.ffmpeg(), "-v", "error", "-y", "-loop", "1", "-i", str(img), "-filter_complex", graph,
         "-map", "[v]", "-t", str(args.dur), *media.h264_args("final"), "-an", str(args.out)])


def text(args, w, h):
    lines = [l for l in args.lines if l.strip()]
    if not lines:
        sys.exit("give at least one line of text")
    font = font_file(args.fontfile)
    if not font:
        sys.exit("no font found: pass --fontfile /path/to/font.ttf")
    big, small = int(h * 0.075 * args.scale), int(h * 0.045 * args.scale)
    sizes = [big] + [small] * (len(lines) - 1)
    pad = int(h * 0.035)
    box_h = sum(int(s * 1.35) for s in sizes) + 2 * pad
    longest = max(len(l) * s * 0.55 for l, s in zip(lines, sizes))
    box_w = min(int(longest) + 2 * pad, int(w * 0.6))
    margin = int(w * 0.06)
    box_x = {"left": margin, "right": w - margin - box_w, "center": (w - box_w) // 2}[args.align]
    box_y = int(h * 0.62) - box_h // 2
    filters = [f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.62:t=fill:replace=1"]
    y = box_y + pad
    tmp = Path(tempfile.mkdtemp(prefix="card-"))
    for i, (line, size) in enumerate(zip(lines, sizes)):
        # Each line from a file with expansion off: no escaping of : , % ' in the text.
        tf = tmp / f"line{i}.txt"
        tf.write_text(line, encoding="utf-8")
        filters.append(f"drawtext=fontfile='{ff_path(font)}':textfile='{ff_path(str(tf))}':expansion=none:"
                       f"fontsize={size}:fontcolor=white:x={box_x + pad}:y={y}")
        y += int(size * 1.35)
    src = f"color=c=black@0.0:s={w}x{h}:r={args.fps},format=rgba"
    vf = ",".join(filters)
    out = Path(args.out)
    if out.suffix.lower() == ".png":
        run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", src, "-vf", vf,
             "-frames:v", "1", "-pix_fmt", "rgba", str(out)])
    elif out.suffix.lower() == ".mov":
        run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", src, "-vf", vf + ",format=yuva444p10le",
             "-t", str(args.dur), "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
             "-alpha_bits", "16", str(out)])
    else:
        sys.exit("text cards are .png (recipe overlay) or .mov (Resolve, with alpha)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["shot", "text"])
    ap.add_argument("items", nargs="+", help="shot: the image; text: the lines")
    ap.add_argument("-o", "--out", required=True, type=Path)
    ap.add_argument("--size", default="1920x1080", help="WxH (default 1920x1080)")
    ap.add_argument("--fps", default="30", help="frame rate, e.g. 30, 29.97, 24000/1001 (default 30)")
    ap.add_argument("--dur", type=float, default=5.0, help="seconds (default 5)")
    ap.add_argument("--align", default="left", choices=["left", "right", "center"], help="text: panel side")
    ap.add_argument("--fontfile", help="text: a .ttf/.ttc/.otf font file")
    ap.add_argument("--scale", type=float, default=1.0, help="text: font size multiplier")
    args = ap.parse_args()
    try:
        w, h = (int(x) for x in args.size.lower().split("x"))
    except ValueError:
        sys.exit(f"--size must be WxH, not {args.size!r}")
    args.out = args.out.expanduser().resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.kind == "shot":
        args.image = args.items[0]
        shot(args, w, h)
    else:
        args.lines = args.items
        text(args, w, h)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
