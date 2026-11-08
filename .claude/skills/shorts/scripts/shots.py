#!/usr/bin/env python3
"""Find the shot changes in a stretch of video and lay it out as timestamped
contact sheets, so an agent (or you) can see what is on screen where.

    shots.py VIDEO --start 60 --end 95 --out-dir DIR      # cuts + 1 fps sheets of that range
    shots.py VIDEO --fps 0.2 --out-dir DIR                # sweep the whole file (one tile per 5 s)

A contact sheet is a grid of small frames; each tile is stamped with its source
time. Prints JSON: {"cuts": [source seconds], "sheets": [paths], "tile_every_s", "start", "end"}.
Scene detection uses ffmpeg's scene score (0-1; 0.3 catches hard cuts, lower
also catches big camera moves).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortslib as sl  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--fps", type=float, default=1.0, help="tiles per second of video (default 1)")
    ap.add_argument("--scene", type=float, default=0.3, help="scene-change threshold 0-1 (default 0.3)")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--width", type=int, default=320, help="tile width in px")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--no-sheets", action="store_true", help="only detect the cuts")
    a = ap.parse_args()

    video = Path(a.video).expanduser().resolve()
    dur = sl.probe(video)["duration"] or 0
    start = max(0.0, a.start)
    end = min(dur, a.end) if a.end else dur
    if end <= start:
        sl.die(f"empty range {start}-{end}", 2)
    seek = ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video)]

    r = sl.media.run(sl.ffmpeg_cmd("-nostats", *seek, "-an", "-vf",
                                   f"scale=480:-2,select='gt(scene\\,{a.scene})',showinfo", "-f", "null", "-"),
                     capture_output=True, text=True)
    cuts = [round(start + float(t), 3) for t in re.findall(r"pts_time:([\d.]+)", r.stderr or "")]

    sheets = []
    if not a.no_sheets:
        out = Path(a.out_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        stem = f"{video.stem}_{start:07.1f}-{end:07.1f}".replace(".", "_")
        font = sl.find_font()
        label = ""
        if font and sl.has_filter("drawtext"):
            label = (f",drawtext=fontfile='{sl.ff_escape_path(font)}':text='%{{pts\\:hms\\:{start:.3f}}}':"
                     f"x=4:y=4:fontsize={max(12, a.width // 16)}:fontcolor=yellow:box=1:boxcolor=black@0.7")
        vf = f"fps={a.fps},scale={a.width}:-2{label},tile={a.cols}x{a.rows}:padding=3:color=gray"
        pattern = out / f"{stem}_%02d.jpg"
        sl.run_ok(sl.ffmpeg_cmd("-v", "error", "-y", *seek, "-an", "-vf", vf, "-q:v", "4", str(pattern)),
                  "contact sheets")
        sheets = sorted(str(p) for p in out.glob(f"{stem}_*.jpg"))
    print(json.dumps({"video": str(video), "start": start, "end": round(end, 3), "cuts": cuts,
                      "tile_every_s": round(1 / a.fps, 3), "tiles_per_sheet": a.cols * a.rows,
                      "sheets": sheets}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
