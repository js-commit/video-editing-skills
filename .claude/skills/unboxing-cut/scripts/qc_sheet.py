#!/usr/bin/env python3
"""QC sheet of a rendered sequence: each beat's first, middle and last frame in one row.

The editorial check before the user sees a draft: a head that opens on a hand
leaving, a tail that cuts mid-move, a hold that is really dead air - all show
up in the first and last tiles of a row.

    qc_sheet.py PREVIEW.mp4 [--plan PREVIEW.plan.json] [-o OUT_DIR] [--rows 8]

Writes OUT_DIR/<stem>_qc_p01.jpg ... (default: next to the preview, in <stem>.review/).
"""
import argparse
import sys, io, json, os, subprocess

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("this script needs pillow: python3 -m pip install pillow")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools"))
from vidkit import media  # noqa: E402


def font(size):
    for f in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Supplemental/Courier New.ttf",
              "C:/Windows/Fonts/consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


FONT = font(16)
W = 480


def grab(path, t):
    out = subprocess.run([media.ffmpeg(), "-v", "error", "-ss", f"{max(0.0, t):.4f}", "-i", path, "-frames:v", "1",
                          "-vf", f"scale={W}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(out)).convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preview")
    ap.add_argument("--plan")
    ap.add_argument("-o", "--out")
    ap.add_argument("--rows", type=int, default=8)
    a = ap.parse_args()
    stem = os.path.splitext(a.preview)[0]
    plan = json.load(open(a.plan or stem + ".plan.json"))
    out = a.out or stem + ".review"
    os.makedirs(out, exist_ok=True)
    fps = None
    rows = []
    for i, b in enumerate(plan["beats"], 1):
        n = b["f_out"] - b["f_in"]
        fps = fps or n / (b["end_s"] - b["start_s"])
        ts = [b["start_s"] + 0.5 / fps, (b["start_s"] + b["end_s"]) / 2, b["end_s"] - 1.5 / fps]
        tiles = []
        for t in ts:
            try:
                tiles.append(grab(a.preview, t))
            except Exception:                          # a frame past the file's end: one frame earlier
                tiles.append(grab(a.preview, t - 1.0 / fps))
        rows.append((f'{i:02d} {b["kind"]} {b["end_s"] - b["start_s"]:.2f}s  {b["label"]}', tiles))
    th = rows[0][1][0].height
    for p in range(0, len(rows), a.rows):
        chunk = rows[p:p + a.rows]
        page = Image.new("RGB", (3 * W + 8, len(chunk) * (th + 26)), (40, 40, 40))
        d = ImageDraw.Draw(page)
        for r, (lab, tiles) in enumerate(chunk):
            y = r * (th + 26)
            d.text((4, y + 4), lab[:150], font=FONT, fill=(255, 255, 0))
            for c, im in enumerate(tiles):
                page.paste(im, (c * (W + 4), y + 24))
        f = os.path.join(out, f"{os.path.basename(stem)}_qc_p{p // a.rows + 1:02d}.jpg")
        page.save(f, quality=80)
        print(f)


if __name__ == "__main__":
    main()
