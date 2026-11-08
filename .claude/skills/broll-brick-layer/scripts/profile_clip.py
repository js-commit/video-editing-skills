#!/usr/bin/env python3
"""Scene cuts and a motion profile of one b-roll clip -> JSON.

scenes  ffmpeg's scene score: where the picture changes completely. A long
        take that wanders across subjects must be broken at these cuts before
        it is annotated, and a placement stays inside one scene.
motion  mean frame-to-frame luma difference per --bucket seconds. Spikes are
        whip pans, shake and the grab-the-camera moments at a clip's head and
        tail. Placement in/out points belong in calm buckets: motion above
        both ~2x the clip's median and its 90th percentile is shaky ("calm"
        lists the spans under that line).

Output: {"file", "duration_s", "scene_threshold", "cuts": [s...],
         "scenes": [{"start_s", "end_s"}], "bucket_s", "p50", "p90",
         "motion": [{"t", "motion"}], "calm": [{"start_s", "end_s"}]}

Usage:
  profile_clip.py FILE -o profile.json [--threshold 0.3] [--bucket 0.5] [--no-motion]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402


def parse_scene_cuts(text, min_gap=0.5):
    cuts = []
    for m in re.finditer(r"pts_time:([0-9.]+)", text):
        t = float(m.group(1))
        if not cuts or t - cuts[-1] > min_gap:  # collapse flash doubles
            cuts.append(round(t, 2))
    return cuts


def scenes_from_cuts(cuts, duration, min_len=0.25):
    bounds = [0.0] + cuts + [round(duration, 2)]
    return [{"start_s": a, "end_s": b} for a, b in zip(bounds, bounds[1:]) if b - a > min_len]


def parse_motion(text, bucket):
    buckets, t = {}, None
    for line in text.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"YAVG=([0-9.]+)", line)
        if m and t is not None:
            buckets.setdefault(int(t / bucket), []).append(float(m.group(1)))
    return [{"t": round(b * bucket, 2), "motion": round(statistics.fmean(v), 2)} for b, v in sorted(buckets.items())]


def calm_spans(rows, bucket, limit):
    """Runs of buckets at or under `limit` (where in/out points may go)."""
    spans, cur = [], None
    for r in rows:
        if r["motion"] <= limit:
            if cur and abs(cur["end_s"] - r["t"]) < 1e-6:
                cur["end_s"] = round(r["t"] + bucket, 2)
            else:
                cur = {"start_s": r["t"], "end_s": round(r["t"] + bucket, 2)}
                spans.append(cur)
        else:
            cur = None
    return spans


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.3, help="scene score for a cut (0-1)")
    ap.add_argument("--bucket", type=float, default=0.5)
    ap.add_argument("--no-motion", action="store_true")
    a = ap.parse_args()
    ff = B.media.ffmpeg()
    duration = B.media.duration(a.file)
    r = B.media.run([ff, "-nostdin", "-v", "error", "-i", a.file, "-vf",
                     f"select='gt(scene,{a.threshold})',metadata=print:file=-", "-an", "-f", "null", "-"],
                    capture_output=True, text=True)
    cuts = parse_scene_cuts(r.stdout)
    doc = {"file": os.path.abspath(a.file), "duration_s": round(duration, 2), "scene_threshold": a.threshold,
           "cuts": cuts, "scenes": scenes_from_cuts(cuts, duration)}
    if not a.no_motion:
        r = B.media.run([ff, "-nostdin", "-v", "error", "-i", a.file, "-vf",
                         "scale=160:-2,tblend=all_mode=difference,signalstats,"
                         "metadata=print:key=lavfi.signalstats.YAVG:file=-", "-an", "-f", "null", "-"],
                        capture_output=True, text=True)
        rows = parse_motion(r.stdout, a.bucket)
        vals = sorted(x["motion"] for x in rows)
        p50 = vals[len(vals) // 2] if vals else 0
        p90 = vals[int(len(vals) * 0.9)] if vals else 0
        limit = max(2 * p50, p90)
        doc.update(bucket_s=a.bucket, p50=p50, p90=p90, motion=rows, calm=calm_spans(rows, a.bucket, limit))
    with open(a.out, "w") as f:
        json.dump(doc, f, indent=1)
    B.log(f"{len(doc['scenes'])} scenes"
          + ("" if a.no_motion else f", {len(doc['calm'])} calm spans") + f" -> {a.out}")
    print(a.out)


if __name__ == "__main__":
    main()
