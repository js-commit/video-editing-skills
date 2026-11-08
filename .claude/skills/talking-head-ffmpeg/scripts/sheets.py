#!/usr/bin/env python3
"""Contact sheets the planner reads: every b-roll clip (source time), and the edited a-roll (record time).

    sheets.py broll <work>/recipe_v0.json [--dirs DIR ...] [--files CLIP[@START-END] ...] [--width 480]
    sheets.py aroll <work>/recipe_vN.json [--every 6]

A contact sheet is a grid of still frames from a clip, each stamped with its time: the cheapest way for Claude to see
what a clip shows without watching it.

broll: every video in the project's footage folder that is not an a-roll take (no `.aroll.tb.json` beside it, not in
the recipe's keeps), or the folders given with --dirs -> <work>/sheets/broll/<folder>__<stem>.jpg, one tile every ~4 s
(4 to 16 tiles, 4 across), each stamped with its SOURCE second (it becomes a brick's in_s), plus
<work>/broll_catalog.json [{file, folder, window, duration_s, fps, hfr, width, height, sheet, tiles}]. `hfr` (>= 47
fps) marks slow-motion candidates: a brick with "speed": 0.4 plays 60p at 24p frame for frame.
--files adds clips from anywhere (another project, a b-roll library hit); `CLIP@START-END` samples only that window of a
long clip at a tile every 2 s. Runs MERGE into the catalog (an entry is replaced only by the same file + window).

aroll: one tile every --every record seconds, stamped with the RECORD time -> <work>/sheets/aroll/aroll_NN.jpg (30
tiles a sheet). This is how the planner sees where the speaker shows something to the camera: talking head the
audience must see, so no brick goes there.

Re-runs skip sheets that already exist (delete a sheet to redo it).
"""
from __future__ import annotations

import argparse
import functools
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402


def stamp(t):
    return f"{int(t // 60)}\\:{t % 60:04.1f}"


@functools.lru_cache(None)
def labels_work():
    """drawtext needs ffmpeg built with freetype + a default font; without it the sheets carry no labels."""
    r = subprocess.run([C.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.04", "-vf",
                        "drawtext=text='1':fontsize=12:fontcolor=white", "-frames:v", "1", "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode:
        print("note: this ffmpeg cannot draw text (no freetype/fontconfig); sheets are unlabelled - "
              "tiles run left to right, top to bottom, at the times listed in the output", file=sys.stderr)
    return r.returncode == 0


def sheet(items, out, width, cols):
    """items: [(file, source_s, label)] - one tile each, in order."""
    rows = -(-len(items) // cols)
    cmd = [C.ffmpeg(), "-v", "error", "-y"]
    for path, t, _ in items:
        cmd += ["-ss", f"{t:.3f}", "-i", path]
    text = labels_work()
    parts = []
    for i, (_, _, lab) in enumerate(items):
        dt = (f",drawtext=text='{lab}':fontsize=24:fontcolor=yellow:box=1:boxcolor=black@0.7:boxborderw=5:x=8:y=8"
              if text else "")
        parts.append(f"[{i}:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale={width}:-2,setsar=1,format=yuv420p{dt}[t{i}]")
    fc = ";".join(parts) + ";" + "".join(f"[t{i}]" for i in range(len(items))) + \
        f"concat=n={len(items)}:v=1:a=0,tile={cols}x{rows}[s]"
    r = C.media.run(cmd + ["-filter_complex", fc, "-map", "[s]", "-frames:v", "1", "-q:v", "4", out],
                    capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"sheet failed for {os.path.basename(items[0][0])}: {r.stderr[-300:]}")


def default_broll(recipe):
    proj = recipe.get("project")
    if not proj:
        return []
    foot = Path(proj) / C.settings.layout("footage")
    takes = {os.path.realpath(k["file"]) for k in recipe["aroll"]}
    out = []
    for p in sorted(foot.rglob("*")) if foot.is_dir() else []:
        if p.suffix.lower() not in C.VIDEO_EXT or p.name.startswith("."):
            continue
        if os.path.realpath(p) in takes or Path(os.path.splitext(str(p))[0] + ".aroll.tb.json").exists():
            continue
        out.append(str(p))
    return out


def cmd_broll(a, r, work):
    jobs = []   # (file, window or None)
    if a.dirs:
        for d in a.dirs:
            for folder in sorted(glob.glob(d)):
                jobs += [(str(p), None) for p in sorted(Path(folder).iterdir()) if p.suffix.lower() in C.VIDEO_EXT]
    elif not a.files:
        jobs = [(f, None) for f in default_broll(r)]
    for spec in a.files or []:
        f, win = spec, None
        if "@" in spec:
            head, tail = spec.rsplit("@", 1)
            if tail.replace(".", "").replace("-", "").isdigit() and "-" in tail:
                f, win = head, tuple(float(x) for x in tail.split("-"))
        f = str(Path(f).resolve())
        if not os.path.exists(f):
            sys.exit(f"no such clip: {f}")
        jobs.append((f, win))
    if not jobs:
        print("no b-roll found: put clips in the project's footage folder, or pass --dirs / --files", file=sys.stderr)
    outdir = work / "sheets" / "broll"
    outdir.mkdir(parents=True, exist_ok=True)
    catp = work / "broll_catalog.json"
    cat = C.read_json(catp) if catp.exists() else []
    for f, win in jobs:
        dur, fps, w, h = R.probe(f)
        lo, hi = win if win else (0.0, dur)
        hi = min(hi, dur)
        span = max(0.1, hi - lo)
        n = max(4, min(16, round(span / (2 if win else 4))))
        times = [min(hi - 0.1, lo + (i + 0.5) * span / n) for i in range(n)]
        folder = os.path.basename(os.path.dirname(f))
        tag = f"__{lo:.0f}-{hi:.0f}" if win else ""
        out = outdir / f"{folder}__{Path(f).stem}{tag}.jpg"
        if not out.exists():
            sheet([(f, t, stamp(t)) for t in times], str(out), a.width, 4)
        entry = {"file": f, "folder": folder, "window": [lo, hi] if win else None, "duration_s": round(dur, 3),
                 "fps": round(float(fps), 3), "hfr": float(fps) >= 47, "width": w, "height": h, "sheet": str(out),
                 "tiles": [round(t, 2) for t in times]}
        cat = [c for c in cat if not (c["file"] == f and c.get("window") == entry["window"])] + [entry]
        print(f"{folder}/{Path(f).name}{tag}: {dur:.1f}s {float(fps):.2f}fps {w}x{h} -> {out}", file=sys.stderr)
    C.write_json(catp, cat)
    print(json.dumps({"clips": len(cat), "added": len(jobs), "catalog": str(catp), "sheets": str(outdir)}))


def cmd_aroll(a, r, work):
    fps, keeps, F = R.fps_of(r), R.aroll_frames(r), R.total_frames(r)
    outdir = work / "sheets" / "aroll"
    outdir.mkdir(parents=True, exist_ok=True)
    samples = []   # (record_s, file, source_s)
    t = a.every / 2
    while t < float(F / fps):
        f = round(t * fps)
        k = next(k for k in keeps if k["rec_f"] <= f < k["rec_f"] + k["n"])
        samples.append((t, k["file"], k["in_s"] + float((f - k["rec_f"]) / fps)))
        t += a.every
    per, made = 30, []
    for s in range(0, len(samples), per):
        chunk = samples[s:s + per]
        out = outdir / f"aroll_{s // per + 1:02d}.jpg"
        made.append(str(out))
        if out.exists():
            continue
        sheet([(x[1], x[2], stamp(x[0])) for x in chunk], str(out), 360, 6)
        print(f"{out}: record {chunk[0][0]:.0f}-{chunk[-1][0]:.0f}s", file=sys.stderr)
    print(json.dumps({"tiles": len(samples), "every_s": a.every, "sheets": made}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["broll", "aroll"])
    ap.add_argument("recipe")
    ap.add_argument("--dirs", action="append", help="folder (glob) of b-roll clips instead of the project's footage")
    ap.add_argument("--files", action="append", help="a clip from anywhere, optionally CLIP@START-END")
    ap.add_argument("--every", type=float, default=6.0, help="aroll: seconds between tiles")
    ap.add_argument("--width", type=int, default=480, help="broll: tile width in px")
    a = ap.parse_args()
    rp = Path(a.recipe).resolve()
    r = C.read_json(rp)
    (cmd_broll if a.cmd == "broll" else cmd_aroll)(a, r, rp.parent)


if __name__ == "__main__":
    main()
