#!/usr/bin/env python3
"""Frames and contact sheets of one clip, for Claude to look at.

One frame every --interval seconds. Handheld footage is full of motion blur,
so each sample point tries --candidates frames spread across its interval
and keeps the SHARPEST (largest JPEG at fixed quality: blur compresses
small). Blurred frames get products and on-screen text misread. Frames are
named by their true timestamp: f000012.50.jpg = 12.5 s into the file.

A dedup pass drops frames that look the same as the previous KEPT frame
(locked-off shots, a camera left running), with a heartbeat frame kept every
--dedup-max-gap seconds; the first and last frames always survive.

--sheet also tiles the kept frames into contact sheets (a grid of small
frames with their timestamps burned in) plus sheets.json mapping every tile
to its timestamp. Annotators skim sheets and open single frames to settle a
detail; a sheet costs one image instead of twelve.

Usage:
  frames.py FILE OUT_DIR [--interval 2.5] [--width 768] [--candidates 5]
            [--start S] [--end S] [--keep-dupes] [--sheet [--cols 4 --rows 3]]

Prints OUT_DIR (stdout). For a placement check, sample the exact source range
densely: --start 31 --end 37 --interval 0.5.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402

FF = None


def ff():
    global FF
    if FF is None:
        FF = B.media.ffmpeg()
    return FF


def grab(file, t, width, out):
    # accurate seek (the default): the frame really is at t, so its file name tells the truth
    B.media.run([ff(), "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", file,
                 "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", "-y", out], check=True)
    return os.path.getsize(out) if os.path.exists(out) else 0


def sharpest_at(file, t0, span, width, n, out_dir):
    """n candidates in [t0, t0+span); keep the largest JPEG."""
    best_t, best_size, best_tmp = None, -1, None
    with tempfile.TemporaryDirectory(dir=out_dir) as td:  # same filesystem for os.replace
        for i in range(n):
            t = t0 + span * i / n
            tmp = os.path.join(td, f"c{i}.jpg")
            try:
                size = grab(file, t, width, tmp)
            except subprocess.CalledProcessError:
                continue
            if size > best_size:
                best_t, best_size, best_tmp = t, size, tmp
        if best_tmp is None:
            return None
        out = os.path.join(out_dir, f"f{best_t:09.2f}.jpg")
        os.replace(best_tmp, out)
    return out


def gray_sig(jpg):
    """16x16 grayscale signature for near-duplicate detection."""
    p = subprocess.run([ff(), "-nostdin", "-v", "error", "-i", jpg, "-vf", "scale=16:16", "-pix_fmt", "gray",
                        "-f", "rawvideo", "-"], capture_output=True, check=True)
    return p.stdout


def sig_diff(a, b):
    """Mean absolute pixel difference, 0-255."""
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def t_of(path):
    return float(os.path.basename(path)[1:-4])


def dedup_sigs(frames, sigs, thresh, max_gap):
    """Pure: drop frames ~identical to the previous KEPT one (slow drift still
    accumulates into a kept frame). Returns (kept, dropped)."""
    if len(frames) <= 2:
        return list(frames), []
    kept, dropped = [frames[0]], []
    last_sig, last_t = sigs[0], t_of(frames[0])
    for f, sig in zip(frames[1:-1], sigs[1:-1]):
        t = t_of(f)
        if sig_diff(sig, last_sig) < thresh and t - last_t < max_gap:
            dropped.append(f)
        else:
            kept.append(f)
            last_sig, last_t = sig, t
    kept.append(frames[-1])
    return kept, dropped


def has_drawtext():
    r = subprocess.run([ff(), "-hide_banner", "-filters"], capture_output=True, text=True)
    return " drawtext " in r.stdout


def make_sheet(frames, out, cols, tile_w, labels=True):
    """One contact sheet from up to cols*rows frames (xstack, one ffmpeg call)."""
    n = len(frames)
    rows = (n + cols - 1) // cols
    args = [ff(), "-nostdin", "-v", "error", "-y"]
    for f in frames:
        args += ["-i", f]
    chains = []
    for i, f in enumerate(frames):
        c = f"[{i}:v]scale={tile_w}:-2,setsar=1"
        if labels:
            c += (f",drawtext=text='{t_of(f):.1f} s':x=6:y=6:fontsize=22:fontcolor=white:"
                  f"box=1:boxcolor=black@0.6:boxborderw=4")
        chains.append(c + f"[t{i}]")
    # pad the last row with copies of black so xstack gets a full grid
    pads = cols * rows - n
    for j in range(pads):
        chains.append(f"[0:v]scale={tile_w}:-2,setsar=1,drawbox=c=black:t=fill[p{j}]")
    names = [f"[t{i}]" for i in range(n)] + [f"[p{j}]" for j in range(pads)]
    if len(names) == 1:
        graph = ";".join(chains) + f";{names[0]}null[out]"
    else:
        layout = "|".join(f"{'+'.join(['w0'] * (k % cols)) or '0'}_{'+'.join(['h0'] * (k // cols)) or '0'}"
                          for k in range(len(names)))
        graph = ";".join(chains) + f";{''.join(names)}xstack=inputs={len(names)}:layout={layout}[out]"
    r = subprocess.run(args + ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-q:v", "4", out],
                       capture_output=True, text=True)
    return r.returncode == 0


def build_sheets(frames, out_dir, cols, rows, tile_w=384):
    labels = has_drawtext()
    per = cols * rows
    sheets = []
    for k in range(0, len(frames), per):
        chunk = frames[k:k + per]
        out = os.path.join(out_dir, f"sheet_{k // per:03d}.jpg")
        ok = make_sheet(chunk, out, cols, tile_w, labels)
        if not ok and labels:  # an ffmpeg without a usable font: unlabeled tiles, sheets.json still maps them
            labels = False
            ok = make_sheet(chunk, out, cols, tile_w, False)
        if ok:
            sheets.append({"sheet": out, "cols": cols, "labels_burned_in": labels,
                           "tiles": [{"index": i, "t": t_of(f), "frame": f} for i, f in enumerate(chunk)]})
    with open(os.path.join(out_dir, "sheets.json"), "w") as f:
        json.dump(sheets, f, indent=1)
    return sheets


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("out_dir")
    ap.add_argument("--interval", type=float, default=2.5)
    ap.add_argument("--width", type=int, default=768)
    ap.add_argument("--candidates", type=int, default=5, help="frames tried per interval; the sharpest wins")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--keep-dupes", action="store_true", help="skip the static-shot dedup pass")
    ap.add_argument("--dedup-thresh", type=float, default=6.0, help="mean pixel difference (0-255) of a dupe")
    ap.add_argument("--dedup-max-gap", type=float, default=30.0, help="keep a heartbeat frame this often (s)")
    ap.add_argument("--sheet", action="store_true", help="also build contact sheets + sheets.json")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=3)
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    duration = B.media.duration(a.file)
    end = min(a.end, duration) if a.end else duration
    windows, t = [], a.start
    while t < end:
        windows.append((t, min(a.interval, end - t)))
        t += a.interval
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        outs = list(ex.map(lambda w: sharpest_at(a.file, w[0], w[1], a.width, a.candidates, a.out_dir), windows))
    frames = sorted(o for o in outs if o)
    n_dropped = 0
    if not a.keep_dupes and len(frames) > 2:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            sigs = list(ex.map(gray_sig, frames))
        frames, dropped = dedup_sigs(frames, sigs, a.dedup_thresh, a.dedup_max_gap)
        for f in dropped:
            os.remove(f)
        n_dropped = len(dropped)
    msg = (f"{len(frames)} frames -> {a.out_dir} (duration {duration:.1f}s, {a.candidates} candidates each, "
           f"{n_dropped} static duplicates dropped)")
    if a.sheet:
        sheets = build_sheets(frames, a.out_dir, a.cols, a.rows)
        msg += f", {len(sheets)} contact sheets"
    B.log(msg)
    print(a.out_dir)


if __name__ == "__main__":
    main()
