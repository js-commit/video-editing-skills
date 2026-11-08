#!/usr/bin/env python3
"""The spoken words on a recipe's record clock: what every state change of a clip is timed to.

    cues.py <work>/recipe_vN.json                     # sentence lines, jump cuts '|', bricks and overlays marked
    cues.py <recipe> --from 32 --to 44                # a window
    cues.py <recipe> --in 32.40 [--to 42.3]           # one word per line, clip-local (record - in): a clip's cues
    cues.py <recipe> --json                           # the words as JSON

Words come from each take's transcript sidecar (<take>.transcript.json), mapped through THIS recipe's keeps, so they
are right after a notes round moved the a-roll. A keep with no sidecar (a chart insert) shows as "[no words: file]".
Transcript times are measured: put a change on a word's start (first column), a landing on its end (second).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "talking-head-ffmpeg" / "scripts"))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402

record_words = R.record_words


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe")
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float)
    ap.add_argument("--in", dest="clip_in", type=float, help="one word per line, clip-local (record - IN)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = C.read_json(a.recipe)
    fps = R.fps_of(r)
    words, bare = record_words(r)
    t0 = a.clip_in if a.clip_in is not None and a.t0 == 0 else a.t0
    t1 = a.t1 if a.t1 is not None else (t0 + 20 if a.clip_in is not None else float(R.total_frames(r) / fps))
    win = [w for w in words if w["e"] > t0 and w["s"] < t1]
    if a.json:
        print(json.dumps(win))
        return 0
    if a.clip_in is not None:
        print("  start     end  word   (clip-local seconds)")
        for w in win:
            print(f"{w['s'] - a.clip_in:7.2f} {w['e'] - a.clip_in:7.2f}  {w['w']}")
        return 0
    marks = [(float(k["rec_f"] / fps), "|") for k in R.aroll_frames(r)[1:]]
    for b in R.brick_frames(r):
        e = float((b["rec_f"] + b["n"]) / fps)
        marks.append((float(b["rec_f"] / fps), f"{{brick {b['i']} until {C.tc(e)}: "
                                                f"{(b.get('why') or os.path.basename(b['file']))[:60]}}}"))
    for o in R.overlay_frames(r):
        marks.append((float(o["rec_f"] / fps), f"{{overlay {o['i']} {float(o['n'] / fps):.1f}s: "
                                                f"{(o.get('why') or os.path.basename(o['file']))[:50]}}}"))
    marks += [(s, f"[no words: {os.path.basename(f)}]") for s, f in bare]
    marks = sorted(m for m in marks if t0 <= m[0] < t1)
    line, start, mi = [], None, 0
    for w in win:
        while mi < len(marks) and marks[mi][0] <= w["s"]:
            line.append(marks[mi][1])
            mi += 1
        start = w["s"] if start is None else start
        line.append(w["w"])
        if w["w"].endswith((".", "?", "!")) and len(line) >= 6:
            print(f"[{C.tc(start)}-{C.tc(w['e'])}] " + " ".join(line))
            line, start = [], None
    line += [m[1] for m in marks[mi:]]
    if line:
        print(f"[{C.tc(start if start is not None else t0)}] " + " ".join(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
