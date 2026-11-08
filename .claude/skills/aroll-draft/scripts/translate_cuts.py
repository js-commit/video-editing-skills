#!/usr/bin/env python3
"""Shift a TimeBolt cut list from one camera's clock to another's (multicam:
the cut was made on camera B's file but the timeline is built on camera A).

Usage: translate_cuts.py IN.tb.json OUT.tb.json SHIFT_S [MAX_DUR_S]

Every op moves by +SHIFT_S (use the sync_offset.py offset_s measured with the
target camera as primary); a leading remove op absorbs the shift so the list
stays gapless from 0. Ops are clamped to MAX_DUR_S (the target file's length).
"""
from __future__ import annotations

import json
import sys


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) not in (4, 5):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    src, dst, shift = sys.argv[1], sys.argv[2], float(sys.argv[3])
    max_dur = float(sys.argv[4]) if len(sys.argv) > 4 else None
    with open(src, encoding="utf-8") as f:
        ops = json.load(f)
    out = []
    for op in ops:
        o = dict(op)
        s = op["start"] + shift
        e = op["start"] + op["duration"] + shift
        if max_dur is not None:
            e = min(e, max_dur)
        if e <= 0 or e <= s:
            continue
        s = max(s, 0.0)
        o["start"], o["duration"] = round(s, 6), round(e - s, 6)
        out.append(o)
    if out and out[0]["start"] > 0:
        out.insert(0, {"start": 0.0, "duration": out[0]["start"], "type": "original",
                       "punched": 1, "punchedPosition": "center", "operation": "remove", "id": -1})
    for i, o in enumerate(out):
        o["id"] = i
    for a, b in zip(out, out[1:]):
        if abs(a["start"] + a["duration"] - b["start"]) > 1e-5:
            sys.exit(f"gap in translated cut list between {a} and {b}")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    keeps = [o for o in out if o["operation"] == "keep"]
    print(json.dumps({"ops": len(out), "keeps": len(keeps),
                      "keep_s": round(sum(o["duration"] for o in keeps), 3), "shift_s": shift}))


if __name__ == "__main__":
    main()
