#!/usr/bin/env python3
"""Map the user's review notes on a draft to the shots they are about.

  review_notes.py PROJECT DRAFT.mp4 [--json]

Reads DRAFT.review/notes.json (EditReview, schema edit-review/4: only "notes" counts) and the
cut list the draft was made from (work/cut_vN.json, N from the draft's name), and prints per
note: the time, the text, the cut under the playhead (index, clip, source seconds, picks note,
section) and, because people stamp a note a beat AFTER the moment, the cut before it when the
stamp lands in the first 1.5 s of a shot. Any player works too: give Claude "m:ss what" lines
instead, and it maps them the same way.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402


def load_notes(review: Path) -> list:
    f = review / "notes.json"
    if not f.exists():
        hv.die(f"no notes yet: {f} (open the draft in EditReview, or paste the notes as 'm:ss text' lines)", 2)
    doc = hv.load_json(f)
    notes = doc.get("notes", []) if isinstance(doc, dict) else doc
    return sorted(({"seconds": float(n["seconds"]), "text": n.get("text", "")} for n in notes), key=lambda n: n["seconds"])


def describe(job: dict, i: int) -> dict:
    c = job["cuts"][i]
    st = c.get("stab") or {}
    src_in = st.get("source_in_s", 0.0) + c["in_s"] if st else c["in_s"]
    return {"cut": i, "clip": c["clip"], "source_in_s": round(src_in, 2), "note": c.get("note", ""),
            "section": c.get("section", ""), "record_s": c["record_s"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("draft")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = hv.project_root(a.project)
    draft = Path(a.draft).expanduser().resolve()
    m = re.search(r"-v(\d+)$", draft.stem)
    cutf = hv.work(p) / (f"cut_v{m.group(1)}.json" if m else "cut_final.json")
    if not cutf.exists():
        hv.die(f"no cut list for {draft.name} ({cutf})", 2)
    job = hv.load_json(cutf)
    starts = [c["record_s"] for c in job["cuts"]]
    rows = []
    for n in load_notes(draft.with_suffix(".review")):
        t = n["seconds"]
        i = max((k for k, s in enumerate(starts) if s <= t + 1e-6), default=0)
        row = {"seconds": round(t, 2), "time": hv.tc(t), "text": n["text"], "at": describe(job, i)}
        if i > 0 and t - starts[i] < 1.5:
            row["maybe"] = describe(job, i - 1)
        sec_t = t - starts[i]
        row["into_shot_s"] = round(sec_t, 2)
        rows.append(row)
    if a.json:
        print(json.dumps({"draft": str(draft), "cut_list": str(cutf), "notes": rows}, indent=1))
        return 0
    print(f"{len(rows)} notes on {draft.name} (cut list {cutf.name})")
    for r in rows:
        at = r["at"]
        print(f"{r['time']}  \"{r['text']}\"\n    -> cut {at['cut']} {at['clip']} @ {at['source_in_s']}s "
              f"[{at['section']}] {at['note'][:50]}" + (f"\n    or cut {r['maybe']['cut']} {r['maybe']['clip']} "
                                                       f"(stamped {r['into_shot_s']}s into the next shot) {r['maybe']['note'][:50]}"
                                                       if r.get("maybe") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
