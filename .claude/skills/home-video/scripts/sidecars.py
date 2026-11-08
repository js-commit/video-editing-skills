#!/usr/bin/env python3
"""EditReview sidecars for a rendered draft (formats: apps/edit-review/SPEC.md).

  sidecars.py cuts    CUT.json VIDEO                      -> VIDEO.review/cuts.json (clip strip, cut-to-cut jumps)
  sidecars.py changes CUT.json VIDEO CHANGES_SPEC.json [--previous PREV_CUT.json]
                                                          -> VIDEO.review/changes.json ("What changed" list)

CHANGES_SPEC (work/changes_vN.json, written by Claude for a notes round, one entry per thing
to look at - normally one per note):
  {"summary": "your 5 notes on v1", "changes": [
     {"cut": 7 | "<unique part of a cut note>", "title": "...", "what": "...", "watch": "...",
      "note": "<the user's note, verbatim>", "kind": "changed|added|removed|audio|music|answer"},
     {"cuts": [3, 5], ...},           a run of cuts
     {"after": 9, ...},               a removed shot: the join after cut 9
     {"start_s": 41.0, "end_s": 44.0, ...}]}
Cut numbers are indices into THIS round's cut list (0-based, as lint and QC print them).
With --previous, every cut that differs from the last round and is not covered by an entry is
listed as UNCOVERED and the exit code is 1: the user reviews only the changes, so every change
must be announced (cover it, or undo it).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def edges(job: dict) -> list:
    fps = int(job.get("fps", 30))
    return [round(c["record_s"] * fps) for c in job["cuts"]] + [round(float(job["end_s"]) * fps)]


def write_cuts(job: dict, video: Path) -> Path:
    fps = int(job.get("fps", 30))
    e = edges(job)
    rows = []
    for i, c in enumerate(job["cuts"]):
        st = c.get("stab") or {}
        src = st.get("source") or c["file"]
        src_in = float(st.get("source_in_s", 0.0)) + float(c["in_s"]) if st else float(c["in_s"])
        rows.append({"index": i + 1, "start_s": round(e[i] / fps, 6), "end_s": round(e[i + 1] / fps, 6),
                     "start_frame": e[i], "end_frame": e[i + 1], "kind": "clip", "track": 1,
                     "name": f"{i} {Path(src).name} {c.get('note', '')[:40]}".strip(), "source": src,
                     "source_start_frame": round(src_in * fps)})
    doc = {"schema": "edit-review-cuts/1", "video": video.name, "project": job.get("project", ""),
           "timeline": f"v{job.get('version', '')}", "frame_rate": float(fps), "timeline_start_frame": 0,
           "render_in_frame": 0, "render_out_frame": e[-1] - 1, "duration_s": round(e[-1] / fps, 6),
           "written_at": now(), "cuts": rows, "overlays": []}
    out = video.with_suffix(".review") / "cuts.json"
    hv.save_json(out, doc)
    return out


def write_changes(job: dict, video: Path, spec: dict, previous: dict | None) -> tuple:
    fps = int(job.get("fps", 30))
    e = [x / fps for x in edges(job)]
    cuts = job["cuts"]

    def idx(ref):
        if isinstance(ref, int):
            if not 0 <= ref < len(cuts):
                hv.die(f"changes: cut {ref} does not exist (0-{len(cuts) - 1})")
            return ref
        hit = [i for i, c in enumerate(cuts) if str(ref).lower() in c.get("note", "").lower()]
        if len(hit) != 1:
            hv.die(f"changes: {ref!r} matches {len(hit)} cut notes; use the cut number")
        return hit[0]
    rows = []
    for k, ch in enumerate(spec.get("changes", []), start=1):
        if "cut" in ch:
            i = idx(ch["cut"])
            s, t = e[i], e[i + 1]
        elif "cuts" in ch:
            i, j = sorted((idx(ch["cuts"][0]), idx(ch["cuts"][-1])))
            s, t = e[i], e[j + 1]
        elif "after" in ch:
            i = idx(ch["after"])
            s = t = e[i + 1]
        elif "start_s" in ch:
            s, t = float(ch["start_s"]), float(ch.get("end_s", ch["start_s"]))
        else:
            hv.die(f"changes: entry {k} ({ch.get('title', '?')}) needs cut / cuts / after / start_s")
        row = {"id": ch.get("id", f"c{k}"), "start_s": round(s, 6), "end_s": round(max(s, t), 6),
               "title": ch.get("title") or hv.die(f"changes: entry {k} has no title")}
        row.update({f: ch[f] for f in ("what", "watch", "note", "kind") if ch.get(f)})
        rows.append(row)
    if not rows:
        hv.die("changes: the spec lists no changes (a notes round always has at least one; a question gets kind 'answer')")
    rows.sort(key=lambda r: (r["start_s"], r["end_s"]))
    doc = {"schema": "edit-review-changes/1", "video": video.name, "round": f"v{job.get('version', '')}",
           "previous": spec.get("previous") or (f"v{previous.get('version')}" if previous else None),
           "summary": spec.get("summary"), "duration_s": round(e[-1], 6), "written_at": now(), "changes": rows}
    out = video.with_suffix(".review") / "changes.json"
    hv.save_json(out, doc)

    uncovered = []
    if previous:
        def sig(c):
            return (Path(c["file"]).name if not c.get("stab") else Path(c["stab"]["source"]).name,
                    json.dumps({k: c.get(k) for k in ("zoom", "fit", "bed", "bed_db", "stabilize")}, sort_keys=True))

        def covered(s, t, slack=0.05):
            return any(r["start_s"] - (0.75 if r["start_s"] == r["end_s"] else 0) - slack <= t and
                       s <= r["end_s"] + (0.75 if r["start_s"] == r["end_s"] else 0) + slack for r in rows)
        prev_cuts = previous["cuts"]
        free = list(range(len(prev_cuts)))
        match = {}
        for i, c in enumerate(cuts):
            src_in = c.get("src_in_s", c["in_s"])
            for j in free:
                pc = prev_cuts[j]
                if sig(pc) == sig(c) and abs(pc.get("src_in_s", pc["in_s"]) - src_in) <= 0.06 and \
                        abs((pc["out_s"] - pc["in_s"]) - (c["out_s"] - c["in_s"])) <= 0.3:
                    match[i] = j
                    free.remove(j)
                    break
        for i, c in enumerate(cuts):
            if i not in match and not covered(e[i], e[i + 1]):
                uncovered.append(f"cut {i} {c.get('note', '')[:50]!r} is new or changed")
        kept = {j: i for i, j in match.items()}
        for j in free:
            k = next((k for k in range(j - 1, -1, -1) if k in kept), None)
            at = e[kept[k] + 1] if k is not None else 0.0
            if not covered(at, at, 0.5):
                uncovered.append(f"previous cut {j} {prev_cuts[j].get('note', '')[:50]!r} is gone (near {at:.2f}s)")
    return out, uncovered


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cuts")
    c.add_argument("cut")
    c.add_argument("video")
    g = sub.add_parser("changes")
    g.add_argument("cut")
    g.add_argument("video")
    g.add_argument("spec")
    g.add_argument("--previous")
    a = ap.parse_args()
    job = json.load(open(a.cut))
    video = Path(a.video).expanduser().resolve()
    if a.cmd == "cuts":
        print(write_cuts(job, video))
        return 0
    out, unc = write_changes(job, video, json.load(open(a.spec)), json.load(open(a.previous)) if a.previous else None)
    for u in unc:
        hv.log("UNCOVERED " + u)
    print(out)
    return 1 if unc else 0


if __name__ == "__main__":
    sys.exit(main())
