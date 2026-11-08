#!/usr/bin/env python3
"""Fold a seam_audit.py report (its per-seam tail_f / head_f plan) into a
resolve_sequence.py job: the outgoing item grows by tail_f frames and the
incoming item starts head_f frames earlier, matched by record frame. Rebuild the
timeline with resolve_sequence.py afterwards.

Usage: seam_plan_apply.py job.json seam_audit.json job_planned.json

Record frames are recomputed from the job exactly as resolve_sequence.py lays
them out (floor(seconds * fps), the same fps: the job's, else the first media's
rate), so the audit must have run on a timeline built from THIS job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit.resolve import job_fps, parse_fps  # noqa: E402


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        audit = json.load(f)
    fps = float(parse_fps(job_fps(job)))
    seq = job["sequence"]
    rec, r = [], 0
    for it in seq:
        rec.append(r)
        r += int(it["src_out_s"] * fps) - int(it["src_in_s"] * fps)
    by_frame = {f: i for i, f in enumerate(rec)}
    applied, unmapped = 0, []
    for s in audit.get("items", []):
        i = by_frame.get(s.get("F"))
        if not i:            # unknown frame, or the first item (no seam before it)
            unmapped.append(s.get("F"))
            continue
        t, h = s.get("tail_f", 0), s.get("head_f", 0)
        if t:
            seq[i - 1]["src_out_s"] = round(seq[i - 1]["src_out_s"] + t / fps, 4)
        if h:
            seq[i]["src_in_s"] = round(seq[i]["src_in_s"] - h / fps, 4)
        if t or h:
            applied += 1
    with open(sys.argv[3], "w", encoding="utf-8") as f:
        json.dump(job, f, indent=1, ensure_ascii=False)
    print(json.dumps({"applied": applied, "unmapped": unmapped[:10], "output": sys.argv[3]}))


if __name__ == "__main__":
    main()
