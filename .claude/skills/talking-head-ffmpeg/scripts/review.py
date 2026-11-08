#!/usr/bin/env python3
"""EditReview round trip for a recipe render: read the user's notes, write the cuts and changes sidecars.

    review.py notes   RENDER.mp4 --recipe <work>/recipe_vN.json [--json]
    review.py cuts    RENDER.mp4 --recipe <work>/recipe_vN.json
    review.py changes RENDER.mp4 --list changes.in.json [--round v2 --previous v1 --summary "..."]

The review data lives next to the render in `<render stem>.review/` (EditReview's folder; format in
apps/edit-review/SPEC.md). The render plays the recipe's record clock 1:1, so a note's `seconds` IS a record time.

notes:   reads notes.json and prints a worksheet: per note, the piece under it (a brick and its `why`, or the a-roll keep
         with its take and source second), the words spoken around it (+-4 s) and the bricks/overlays nearby. Notes are
         stamped a beat late by design: look a few seconds either side. --json for the raw rows.
cuts:    writes cuts.json (schema edit-review-cuts/1) from recipe.flatten(): every picture piece with its source, so the
         review app can show the edit points. render_recipe.py writes it after every render.
changes: writes changes.json (schema edit-review-changes/1) from a list Claude authors after a notes round: one row
         per note of the previous round, on the NEW render's clock:
           [{"id": "c1", "start_s": 12.0, "end_s": 15.5, "kind": "changed", "title": "short label",
             "what": "what was done", "watch": "what to check", "note": "the user's original note"}]
         Only id, start_s, end_s and title are required; start_s == end_s marks a point (something removed there).
         kind: changed | added | removed | audio | music | answer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def review_dir(render):
    p = Path(render).resolve()
    if p.suffix == ".review" and p.is_dir():
        return p
    d = p.with_name(p.stem + ".review")
    d.mkdir(exist_ok=True)
    return d


def load_notes(render):
    d = review_dir(render)
    f = d / "notes.json"
    if not f.exists():
        sys.exit(f"no notes yet: {f} (open the render in EditReview and press Return after each note)")
    data = C.read_json(f)
    notes = data.get("notes", data if isinstance(data, list) else [])
    return sorted((n for n in notes if "seconds" in n), key=lambda n: n["seconds"])


def cmd_notes(a):
    r = C.read_json(a.recipe)
    fps = R.fps_of(r)
    pieces = R.flatten(r)
    words, _ = R.record_words(r)
    rows = []
    for n in load_notes(a.render):
        t = float(n["seconds"])
        f = round(t * fps)
        p = next((p for p in pieces if p["rec_f"] <= f < p["rec_f"] + p["n"]), pieces[-1])
        if p["kind"] == "broll":
            b = r["broll"][p["brick"]]
            under = f"brick {p['brick']} ({os.path.basename(b['file'])} @{b['in_s']:.2f}): {b.get('why', '')}"
        else:
            src = p["in_s"] + float((f - p["rec_f"]) / fps)
            under = f"a-roll {os.path.basename(p['file'])} @ source {src:.2f}s"
        near_b = [f"brick {b['i']} {C.tc(b['record_s'])}+{b['dur']:.1f}s" for b in R.brick_frames(r)
                  if b["record_s"] - 6 < t < b["record_s"] + b["dur"] + 6]
        near_o = [f"overlay {o['i']} {C.tc(o['record_s'])}+{o['dur']:.1f}s" for o in R.overlay_frames(r)
                  if o["record_s"] - 6 < t < o["record_s"] + o["dur"] + 6]
        said = " ".join(w["w"] for w in words if t - 4 <= w["s"] <= t + 4)
        rows.append({"seconds": t, "text": n.get("text", ""), "under": under, "words": said,
                     "nearby": near_b + near_o})
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    for i, x in enumerate(rows, 1):
        print(f"## {i}. {C.tc(x['seconds'])}  \"{x['text']}\"")
        print(f"   under: {x['under']}")
        print(f"   said:  {x['words']}")
        if x["nearby"]:
            print(f"   near:  {', '.join(x['nearby'])}")
        print()
    print(json.dumps({"notes": len(rows)}))
    return 0


def write_cuts(render, r):
    """cuts.json for a render of recipe r. Returns its path."""
    fps = R.fps_of(r)
    ff = float(fps)
    cuts = []
    for i, p in enumerate(R.flatten(r), 1):
        _, sfps, _, _ = R.probe(p["file"])
        cuts.append({"index": i, "start_s": round(p["rec_f"] / ff, 6), "end_s": round((p["rec_f"] + p["n"]) / ff, 6),
                     "start_frame": p["rec_f"], "end_frame": p["rec_f"] + p["n"], "kind": "clip",
                     "track": 2 if p["kind"] == "broll" else 1, "name": os.path.basename(p["file"]),
                     "source": p["file"], "source_start_frame": round(p["in_s"] * float(sfps)),
                     **({"why": r["broll"][p["brick"]].get("why", "")} if p["kind"] == "broll" else {})})
    ovs = [{"track": 3, "start_s": round(o["rec_f"] / ff, 6), "end_s": round((o["rec_f"] + o["n"]) / ff, 6),
            "name": os.path.basename(o["file"]), "why": o.get("why", "overlay")} for o in R.overlay_frames(r)]
    F = R.total_frames(r)
    data = {"schema": "edit-review-cuts/1", "video": Path(render).name, "project": r.get("name") or "",
            "timeline": r.get("_recipe_file", ""), "frame_rate": round(ff, 6), "timeline_start_frame": 0,
            "render_in_frame": 0, "render_out_frame": F - 1, "duration_s": round(F / ff, 6),
            "written_at": _now(), "cuts": cuts, "overlays": ovs}
    out = review_dir(render) / "cuts.json"
    C.write_json(out, data)
    return out


def cmd_cuts(a):
    r = C.read_json(a.recipe)
    r["_recipe_file"] = Path(a.recipe).name
    print(json.dumps({"cuts": str(write_cuts(a.render, r))}))
    return 0


def cmd_changes(a):
    src = C.read_json(a.list)
    rows = src.get("changes", []) if isinstance(src, dict) else src
    if not rows:
        print("the change list is empty (a notes round always has at least one row)", file=sys.stderr)
        return 3
    bad = [i for i, c in enumerate(rows) if not all(k in c for k in ("id", "start_s", "end_s", "title"))]
    if bad:
        print(f"rows {bad} need id, start_s, end_s and title", file=sys.stderr)
        return 3
    dur = C.media.duration(a.render)
    late = [c["id"] for c in rows if not (0 <= float(c["start_s"]) <= float(c["end_s"]) <= dur + 0.05)]
    if late:
        print(f"rows {late}: times must satisfy 0 <= start_s <= end_s <= {dur:.2f} (the new render's clock)", file=sys.stderr)
        return 3
    data = {"schema": "edit-review-changes/1", "video": Path(a.render).name,
            "round": a.round or (src.get("round") if isinstance(src, dict) else None) or "",
            "previous": a.previous or (src.get("previous") if isinstance(src, dict) else None) or "",
            "summary": a.summary or (src.get("summary") if isinstance(src, dict) else None) or "",
            "duration_s": round(dur, 3), "written_at": _now(),
            "changes": sorted(rows, key=lambda c: float(c["start_s"]))}
    out = review_dir(a.render) / "changes.json"
    C.write_json(out, data)
    print(json.dumps({"changes": str(out), "rows": len(rows)}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["notes", "cuts", "changes"])
    ap.add_argument("render")
    ap.add_argument("--recipe")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", help="changes: the authored rows (JSON list, or {changes: [...]})")
    ap.add_argument("--round")
    ap.add_argument("--previous")
    ap.add_argument("--summary")
    a = ap.parse_args()
    if a.cmd in ("notes", "cuts") and not a.recipe:
        ap.error(f"{a.cmd} needs --recipe")
    if a.cmd == "changes" and not a.list:
        ap.error("changes needs --list")
    return {"notes": cmd_notes, "cuts": cmd_cuts, "changes": cmd_changes}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
