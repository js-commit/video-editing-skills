#!/usr/bin/env python3
"""Timestamped contact sheets with the sound drawn under every frame.

An unboxing is cut on what you SEE (a product coming out, a hold) and what you
HEAR (the knife on the tape, the shrink wrap, the lid sliding off). So each
tile is one frame plus the waveform of the seconds it stands for: grey is the
full-band level, orange the 3-10 kHz band where crinkles, peels and the knife
live (speech sits mostly below it), both scaled from the file's own quiet floor
to its loudest moment. Pages are COLS x ROWS tiles in reading order; the tile
label is the source time of the frame.

    overview.py VIDEO --step 4 [--start S] [--end E] -o OUT_DIR [--cols 5 --rows 4 --width 384] [--flip]

--flip rotates the frames 180 degrees (a rig mounted upside down). Writes
OUT_DIR/<stem>_p01.jpg ... and OUT_DIR/<stem>.audio.npz (the 20 ms envelopes).
One ffmpeg at a time.
"""
import argparse, os, subprocess, sys

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("this script needs numpy scipy pillow: python3 -m pip install numpy scipy pillow")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools"))
from vidkit import media  # noqa: E402

SR = 24000
HOP = 0.02           # envelope resolution, seconds


def font(size):
    for f in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Supplemental/Courier New.ttf",
              "C:/Windows/Fonts/consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


FONT = font(18)


def duration(path):
    out = subprocess.run([media.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def envelopes(path, start, end):
    """(full, high) RMS per HOP from start to end, in dBFS."""
    from scipy.signal import butter, sosfilt
    cmd = [media.ffmpeg(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", path, "-vn",
           "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    pcm = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32)
    hi = sosfilt(butter(4, [3000, 10000], btype="band", fs=SR, output="sos"), pcm)
    n = int(HOP * SR)
    k = len(pcm) // n

    def rms_db(x):
        r = np.sqrt(np.mean(x[:k * n].reshape(k, n) ** 2, axis=1) + 1e-12)
        return 20 * np.log10(r + 1e-9)
    return rms_db(pcm), rms_db(hi)


def frame(path, t, width, flip=False):
    cmd = [media.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
           "-vf", ("hflip,vflip," if flip else "") + f"scale={width}:-2,format=rgb24", "-f", "image2pipe", "-vcodec", "png", "-"]
    import io
    out = media.run(cmd, capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(out)).convert("RGB")


def strip(full, high, w, h, floor, top):
    img = Image.new("RGB", (w, h), (18, 18, 18))
    d = ImageDraw.Draw(img)
    if len(full) == 0:
        return img
    xs = np.linspace(0, len(full), w + 1).astype(int)
    for x in range(w):
        a, b = xs[x], max(xs[x + 1], xs[x] + 1)
        for env, col in ((full, (150, 150, 150)), (high, (255, 140, 0))):
            v = float(np.max(env[a:b])) if b <= len(env) else floor
            y = int(h * min(1.0, max(0.0, (v - floor) / (top - floor))))
            if y > 0:
                d.line([(x, h - 1), (x, h - y)], fill=col)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--step", type=float, default=4.0)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--width", type=int, default=384)
    ap.add_argument("--flip", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    end = a.end or duration(a.video)
    stem = os.path.splitext(os.path.basename(a.video))[0]

    full, high = envelopes(a.video, a.start, end)
    np.savez(os.path.join(a.out, f"{stem}.audio.npz"), full=full, high=high, start=a.start, hop=HOP)

    floor, top = float(np.percentile(full, 5)), float(np.max(full))   # the file's own range: quiet room -> loudest hit
    times = list(np.arange(a.start, end - 0.05, a.step))
    per = a.cols * a.rows
    sh = 44
    for p in range(0, len(times), per):
        tiles = []
        for t in times[p:p + per]:
            im = frame(a.video, t, a.width, a.flip)
            d = ImageDraw.Draw(im)
            lab = f"{int(t // 60)}:{t % 60:05.2f}"
            d.rectangle([0, 0, 12 * len(lab) + 8, 24], fill=(0, 0, 0))
            d.text((4, 2), lab, font=FONT, fill=(255, 255, 0))
            i0, i1 = int((t - a.start) / HOP), int((t + a.step - a.start) / HOP)
            tiles.append((im, strip(full[i0:i1], high[i0:i1], a.width, sh, floor, top)))
        th = tiles[0][0].height + sh
        page = Image.new("RGB", (a.cols * a.width + (a.cols - 1) * 4, a.rows * th + (a.rows - 1) * 6), (60, 60, 60))
        for i, (im, st) in enumerate(tiles):
            x, y = (i % a.cols) * (a.width + 4), (i // a.cols) * (th + 6)
            page.paste(im, (x, y))
            page.paste(st, (x, y + im.height))
        out = os.path.join(a.out, f"{stem}_p{p // per + 1:02d}.jpg")
        page.save(out, quality=82)
        print(out)


if __name__ == "__main__":
    main()
