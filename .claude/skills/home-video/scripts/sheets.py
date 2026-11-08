#!/usr/bin/env python3
"""Contact sheets: a grid of stills, each labelled with its time, for Claude (or you) to read.
Refused unless the project's privacy mode is "frames".

  sheets.py PROJECT                         one sheet per clip that has none yet -> work/sheets/<id>.jpg
  sheets.py PROJECT --clips ID [ID ...]     just these clips (--force to redo)
  sheets.py PROJECT --dense ID [ID ...]     1 still per second (2 under 12 s), 20 per sheet -> work/sheets/<id>_dense_NN.jpg
  sheets.py PROJECT --zoom ID START END [STEP]
                                            one moment at STEP s (default 0.25): the exact head or tail of a shot
  sheets.py PROJECT --render CUT.json VIDEO a rendered draft at 1 still/s, each tile labelled time + cut number
                                            -> <video>.sheets/NN.jpg (for a review)

Each sheet also gets a .json beside it listing the tile times, so a label that the ffmpeg
build cannot draw (no drawtext) is still known. Tiles read left to right, top to bottom.
Prints the written sheet paths on stdout, one per line.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402
from hv import media  # noqa: E402

TILE_W, TILE_H, COLS = 384, 216, 4
_DRAWTEXT = None


def drawtext_ok() -> bool:
    global _DRAWTEXT
    if _DRAWTEXT is None:
        _DRAWTEXT = hv.has_filter("drawtext")
    return _DRAWTEXT


def label(text: str) -> str:
    if not drawtext_ok():
        return ""
    t = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")
    return f",drawtext=text='{t}':x=6:y=6:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6"


def make_sheet(path: str, times: list, out: Path, labels: list | None = None, cols: int = COLS) -> Path:
    """One sheet of stills at `times` (seconds) from `path`."""
    labels = labels or [hv.tc(t) for t in times]
    rows = (len(times) + cols - 1) // cols
    cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-y"]
    for t in times:
        cmd += ["-ss", f"{max(0.0, t):.3f}", "-i", path]
    fc = ""
    for i, lab in enumerate(labels):
        fc += (f"[{i}:v]trim=end_frame=1,scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,"
               f"pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1{label(lab)}[t{i}];")
    pads = cols * rows - len(times)
    for k in range(pads):
        fc += f"color=c=black:s={TILE_W}x{TILE_H}:d=0.04[p{k}];"
    fc += "".join(f"[t{i}]" for i in range(len(times))) + "".join(f"[p{k}]" for k in range(pads))
    fc += f"concat=n={len(times) + pads}:v=1:a=0,tile={cols}x{rows}[out]"
    out.parent.mkdir(parents=True, exist_ok=True)
    r = media.run(cmd + ["-filter_complex", fc, "-map", "[out]", "-frames:v", "1", "-q:v", "4", str(out)],
                  capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"sheet failed for {path}: {r.stderr.strip()[-300:]}")
    out.with_suffix(".json").write_text(json.dumps({"source": path, "tiles": [
        {"t": round(t, 3), "label": lab} for t, lab in zip(times, labels)]}, indent=1))
    return out


def overview_times(dur: float) -> list:
    n = 8 if dur < 20 else 12 if dur < 60 else 16 if dur < 180 else 20
    return [dur * (i + 0.5) / n for i in range(n)]


def chunk(xs: list, n: int) -> list:
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--clips", nargs="+")
    ap.add_argument("--dense", nargs="+", metavar="ID")
    ap.add_argument("--zoom", nargs="+", metavar="ARG", help="ID START END [STEP]")
    ap.add_argument("--render", nargs=2, metavar=("CUT_JSON", "VIDEO"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    p = hv.project_root(a.project)
    hv.require_frames(p, "a contact sheet")
    W = hv.work(p)
    out = []
    if a.zoom:
        if len(a.zoom) not in (3, 4):
            hv.die("--zoom ID START END [STEP]", 2)
        cid, s, e = a.zoom[0], float(a.zoom[1]), float(a.zoom[2])
        step = float(a.zoom[3]) if len(a.zoom) == 4 else 0.25
        times = [round(s + k * step, 3) for k in range(int((e - s) / step) + 1)][:24]
        out.append(make_sheet(hv.clip_path(p, cid), times, W / "sheets" / f"{cid}_zoom_{s:.2f}.jpg",
                              [f"{t:.2f}s" for t in times], cols=6))
    elif a.render:
        job = json.load(open(a.render[0]))
        video = Path(a.render[1]).resolve()
        dur = media.duration(video)
        starts = [c["record_s"] for c in job["cuts"]]
        times = [t + 0.5 for t in range(int(dur))]
        labs = []
        for t in times:
            k = max(i for i, s in enumerate(starts) if s <= t + 1e-6)
            labs.append(f"{hv.tc(t)[:-3]} #{k}")
        d = video.with_suffix(".sheets")
        for n, (tt, ll) in enumerate(zip(chunk(times, 20), chunk(labs, 20)), start=1):
            out.append(make_sheet(str(video), tt, d / f"{n:02d}.jpg", ll, cols=5))
    elif a.dense:
        for cid in a.dense:
            path = hv.clip_path(p, cid)
            dur = media.duration(path)
            step = 0.5 if dur < 12 else 1.0
            times = [round(0.25 + k * step, 3) for k in range(int((dur - 0.3) / step) + 1)]
            for n, tt in enumerate(chunk(times, 20), start=1):
                f = W / "sheets" / f"{cid}_dense_{n:02d}.jpg"
                if f.exists() and not a.force:
                    out.append(f)
                    continue
                out.append(make_sheet(path, tt, f, [f"{t:.1f}s" for t in tt], cols=5))
    else:
        ids = a.clips or sorted(hv.clips(p))
        for cid in ids:
            f = W / "sheets" / f"{cid}.jpg"
            if f.exists() and not a.force:
                out.append(f)
                continue
            path = hv.clip_path(p, cid)
            out.append(make_sheet(path, overview_times(media.duration(path)), f))
    for f in out:
        print(f)
    if not drawtext_ok():
        hv.log("note: this ffmpeg has no drawtext, so tiles carry no printed time; each sheet's .json lists the tile times")
    return 0


if __name__ == "__main__":
    sys.exit(main())
