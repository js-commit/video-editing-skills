#!/usr/bin/env python3
"""A contact sheet (grid of evenly spaced frames) of a video, so Claude can
look at the user's footage and give feedback.

    contact_sheet.py <video> [-o sheet.jpg] [--frames 12] [--cols 4] [--width 480]
                     [--start S] [--end S]

Each frame is grabbed with a fast seek, then tiled with ffmpeg's tile filter.
Timestamps are burned in when ffmpeg has drawtext and are always listed in the
JSON on stdout (tile number -> seconds), reading left to right, top to bottom.
Default output: the user cache folder (settings paths.cache_dir, else
user/cache) under editing-coach/. Exit 0 ok, 1 ffmpeg failure, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media, settings  # noqa: E402


def has_filter(name: str) -> bool:
    out = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return f" {name} " in out


def fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def grab(video: str, t: float, width: int, out: Path, label: str | None) -> bool:
    vf = f"scale={width}:-2"
    if label:
        safe = label.replace(":", r"\:")
        vf += (f",drawtext=text='{safe}':x=8:y=h-th-8:fontsize={max(14, width // 20)}"
               f":fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=4")
    cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video,
           "-frames:v", "1", "-vf", vf, str(out)]
    r = media.run(cmd, capture_output=True, text=True)
    return r.returncode == 0 and out.is_file()


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Grid of evenly spaced frames from a video.")
    ap.add_argument("video")
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--width", type=int, default=480, help="width of each tile in pixels")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    args = ap.parse_args(argv)

    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        print(f"no such file: {video}", file=sys.stderr)
        return 2
    info = media.probe(video)
    if not info["has_video"] or not info["duration"]:
        print(f"{video} has no video stream or no duration", file=sys.stderr)
        return 2
    n = max(1, args.frames)
    cols = max(1, min(args.cols, n))
    rows = math.ceil(n / cols)
    start = max(0.0, args.start)
    end = min(args.end or info["duration"], info["duration"])
    span = max(0.0, end - start)
    # centre of each of n equal slices, so the first and last frames are not black fades
    times = [start + span * (i + 0.5) / n for i in range(n)]

    out = args.output or settings.cache_dir("editing-coach") / f"{video.stem}.contact.jpg"
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    label_ok = has_filter("drawtext")

    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        last = None
        for i, t in enumerate(times):
            f = tmpd / f"f{i:04d}.png"
            ok = grab(str(video), t, args.width, f, fmt(t) if label_ok else None)
            if not ok and label_ok:  # drawtext present but no usable font: retry plain
                label_ok = False
                ok = grab(str(video), t, args.width, f, None)
            if not ok and last:
                shutil.copy(last, f)  # a seek past the last decodable frame: reuse the previous one
            elif not ok:
                print(f"could not read a frame at {t:.2f}s from {video}", file=sys.stderr)
                return 1
            last = f
        cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-framerate", "1",
               "-i", str(tmpd / "f%04d.png"), "-vf", f"tile={cols}x{rows}:padding=4:margin=4",
               "-frames:v", "1", "-q:v", "3", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ffmpeg could not tile the frames: {r.stderr.strip()}", file=sys.stderr)
            return 1

    print(json.dumps({
        "sheet": str(out), "video": str(video), "cols": cols, "rows": rows,
        "labels_burned_in": label_ok,
        "tiles": [{"tile": i + 1, "seconds": round(t, 2), "timecode": fmt(t)} for i, t in enumerate(times)],
        "video_info": {k: info[k] for k in ("duration", "width", "height", "fps", "vcodec", "has_audio")},
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
