#!/usr/bin/env python3
"""Write changes.json for a NEW render: what this round changed, on the new
render's clock, so EditReview can play just the changes (Option-Up / Down).

    write_changes.py NEW_RENDER.mp4 --list changes.in.json \
        [--round v3 --previous v2 --summary "Your 7 notes on v2, nothing else."]

changes.in.json is a list (or an object with "changes" and optional "round",
"previous", "summary"), one row per change, times in NEW-render seconds:

    [{"start_s": 12.0, "end_s": 15.5, "kind": "added", "title": "B-roll of the unboxing",
      "what": "Laid a 3.5 s shot of the box opening over 'out of the box'.",
      "watch": "Does it start on the word?", "note": "show the unboxing here"}]

Only start_s, end_s and title are required. start_s == end_s marks a point
(something removed at that join). kind: changed, added, removed, audio, music
or answer (display only). Missing ids become c1, c2, ... in time order.

Writes <render-stem>.review/changes.json (schema edit-review-changes/1, see
apps/edit-review/SPEC.md) and prints its path. Problems with the rows are
listed and the script exits 3 without writing: fix the list and re-run.

Exit codes: 0 written, 1 bad input, 3 rows need fixing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))

SCHEMA = "edit-review-changes/1"
KINDS = {"changed", "added", "removed", "audio", "music", "answer"}
TOLERANCE_S = 0.2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("render", type=Path, help="the new render the changes are in")
    ap.add_argument("--list", required=True, type=Path, help="the changes, as JSON")
    ap.add_argument("--round", help='this render\'s name in the review, e.g. "v3"')
    ap.add_argument("--previous", help='the render the notes were on, e.g. "v2"')
    ap.add_argument("--summary", help="one line for the top of the What changed pane")
    args = ap.parse_args()

    render = args.render.expanduser().resolve()
    if not render.is_file():
        sys.exit(f"no such file: {render}")
    try:
        spec = json.loads(args.list.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read {args.list}: {e}")
    meta = spec if isinstance(spec, dict) else {}
    rows = spec.get("changes", []) if isinstance(spec, dict) else spec
    if not isinstance(rows, list) or not rows:
        sys.exit("the change list is empty")

    from vidkit import media
    duration = media.duration(render)
    problems, out = [], []
    for i, r in enumerate(rows):
        try:
            a, b = float(r["start_s"]), float(r["end_s"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"row {i}: start_s and end_s must be numbers")
            continue
        title = str(r.get("title") or "").strip()
        if not title:
            problems.append(f"row {i}: needs a title")
        if b < a:
            problems.append(f"row {i} ({title}): end_s {b} is before start_s {a}")
        if a < 0 or b > duration + TOLERANCE_S:
            problems.append(f"row {i} ({title}): {a:.2f}-{b:.2f} s is outside the render (0-{duration:.2f} s); "
                            "times must be on the NEW render's clock")
        kind = r.get("kind")
        if kind is not None and kind not in KINDS:
            problems.append(f"row {i} ({title}): kind {kind!r} is not one of {sorted(KINDS)}")
        row = {"id": str(r.get("id") or ""), "start_s": round(a, 3), "end_s": round(max(a, b), 3), "title": title}
        for k in ("kind", "what", "watch", "note"):
            if r.get(k):
                row[k] = str(r[k])
        out.append(row)
    if problems:
        print("changes.json not written; fix these rows:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 3

    out.sort(key=lambda r: r["start_s"])
    used = {r["id"] for r in out if r["id"]}
    n = 0
    for r in out:
        if not r["id"]:
            n += 1
            while f"c{n}" in used:
                n += 1
            r["id"] = f"c{n}"
            used.add(r["id"])
    doc = {"schema": SCHEMA, "video": render.name,
           "round": args.round or meta.get("round") or render.stem,
           "previous": args.previous or meta.get("previous"),
           "summary": args.summary or meta.get("summary"),
           "duration_s": round(duration, 3),
           "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "changes": out}
    doc = {k: v for k, v in doc.items() if v is not None}
    path = render.with_suffix(".review") / "changes.json"
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    print(path)
    print(f"{len(out)} change(s), round {doc['round']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
