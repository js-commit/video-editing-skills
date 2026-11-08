#!/usr/bin/env python3
"""Review broll-library salvage picks in BulkCut before they are cut into the
library (optional, macOS). Fits between the broll-salvage-picker agents and
`salvage.py apply`:

  salvage_review.py stage WORK [-o DIR]
      Makes a BulkCut review folder (default WORK/bulkcut) from the salvage
      work folder: a link per camera file, each pick as a purple range with its
      description, and what the edit or the library already used in orange.
      Files with no picks start "not kept". Prints the folder; open it with
      `bulkcut.py open DIR`.
  salvage_review.py collect WORK [-o DIR]
      Writes the reviewed ranges back as WORK/picks/<batch>.json (the agents'
      originals are kept once in WORK/picks-agent/). A kept pick keeps its
      description (or the one the user typed), tags and privacy note; a range
      the user drew gets their typed description, or none (listed under
      "need_description": describe it from its frames before `apply`). BulkCut's
      Send button runs this too.

Then run `salvage.py apply WORK --dry-run` as usual: it checks every pick.
stdout: JSON. Exit 0 ok, 2 usage, 3 not reviewed yet.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bulkcut  # noqa: E402

PICKER = "salvage picker"


def load_work(work: Path):
    """batches.json, every info.json by camera file, and the picks by camera file."""
    b = bulkcut.load_json(work / "batches.json")
    infos, batch_of = {}, {}
    for x in b["batches"]:
        for ip in x["info_files"]:
            rec = bulkcut.load_json(Path(ip))
            infos[rec["file"]] = rec
            batch_of[rec["file"]] = x
    picks: dict = {}
    for x in b["batches"]:
        pp = Path(x["picks"])
        if pp.exists():
            for p in bulkcut.load_json(pp).get("picks", []):
                rec = infos.get(p.get("file")) or next((r for r in infos.values() if r["stem"] == p.get("stem")), None)
                if rec:
                    picks.setdefault(rec["file"], []).append(p)
    return b, infos, batch_of, picks


def cmd_stage(a) -> int:
    work = Path(a.work).expanduser().resolve()
    b, infos, _, picks = load_work(work)
    out = Path(a.out).expanduser().resolve() if a.out else work / "bulkcut"
    files = []
    for path, rec in infos.items():
        mine = picks.get(path, [])
        privacy = "; ".join(p["privacy_note"] for p in mine if p.get("privacy_note"))
        files.append({
            "source": path,
            "kept": bool(mine),
            "why": "a-roll angle: only clear visual moments" if rec.get("aroll") else None,
            "privacy": privacy or None,
            "proposals": [{"start": float(p["source_in"]), "end": float(p["source_out"]), "kind": "pick",
                           "text": p.get("description", ""), "by": PICKER} for p in mine],
            "library": [{"start": s, "end": e, "text": "", "by": "", "clip": "used by the edit or the library"}
                        for s, e in rec.get("used_ranges", [])],
        })
    files = [{k: v for k, v in f.items() if v is not None} for f in files]
    spec = {
        "title": f"Salvage picks: {b.get('name', work.name)}",
        "legend": {"pick": "salvage pick", "library": "already used"},
        "send": {"label": "Save picks", "command": [sys.executable, str(Path(__file__).resolve()), "collect", str(work),
                                                    "-o", str(out)],
                 "steps": ["Writes your ranges back as the salvage picks (picks/<batch>.json); the agents' "
                           "originals stay in picks-agent/.",
                           "Then tell Claude the review is done: it checks the picks and cuts them into the "
                           "library (salvage.py apply)."]},
        "files": files,
    }
    print(json.dumps(bulkcut.stage(spec, out), indent=2, ensure_ascii=False))
    return 0


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def cmd_collect(a) -> int:
    work = Path(a.work).expanduser().resolve()
    out = Path(a.out).expanduser().resolve() if a.out else work / "bulkcut"
    review = bulkcut.read_review(out)
    if review is None:
        bulkcut.die(f"{out} has not been opened in BulkCut yet", 3)
    b, infos, batch_of, picks = load_work(work)

    backup = work / "picks-agent"
    if not backup.exists():
        backup.mkdir()
        for x in b["batches"]:
            if Path(x["picks"]).exists():
                shutil.copy2(x["picks"], backup / Path(x["picks"]).name)

    new: dict = {x["batch"]: [] for x in b["batches"]}
    kept = added = 0
    need, ignored = [], []
    for row in review["files"]:
        src = row.get("source")
        if src not in infos or row["deleted"]:
            continue
        rec, batch = infos[src], batch_of[src]["batch"]
        if row.get("turns") or row.get("zoom"):
            ignored.append(src)    # apply cuts from the originals as they are
        originals = picks.get(src, [])
        for r in row["ranges"]:
            s, e = float(r["start"]), float(r["end"])
            match = max(originals, key=lambda p: overlap(s, e, float(p["source_in"]), float(p["source_out"])),
                        default=None)
            if match is not None:
                o = overlap(s, e, float(match["source_in"]), float(match["source_out"]))
                if o < 0.5 * min(e - s, float(match["source_out"]) - float(match["source_in"])):
                    match = None
            p = {"file": src, "source_in": round(s, 2), "source_out": round(e, 2)}
            if match is not None:
                p.update({k: match[k] for k in ("tags", "quality", "privacy_note") if k in match})
                p["description"] = r.get("note") or match.get("description", "")
                kept += 1
            else:
                p["description"] = r.get("note") or ""
                p["tags"] = []
                added += 1
            if r.get("note"):
                p["described_by"] = "user"
            if not p["description"]:
                need.append({"file": src, "source_in": p["source_in"], "source_out": p["source_out"],
                             "batch": batch})
            new[batch].append(p)

    removed = sum(len(v) for v in picks.values()) - kept
    for x in b["batches"]:
        pp = Path(x["picks"])
        doc = bulkcut.load_json(pp) if pp.exists() else {"batch": x["batch"]}
        doc["picks"] = new[x["batch"]]
        doc["reviewed_in"] = "bulkcut"
        bulkcut.write_json(pp, doc)
    print(json.dumps({"picks": sum(len(v) for v in new.values()), "kept_from_agents": kept, "removed": removed,
                      "added_by_user": added, "need_description": need,
                      "rotation_or_zoom_ignored": ignored, "agent_originals": str(backup),
                      "stale_review": review["stale"],
                      "next": f"salvage.py apply {work} --dry-run"}, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("stage", "collect"):
        p = sub.add_parser(name)
        p.add_argument("work", help="the salvage work folder (salvage.py prep -o)")
        p.add_argument("-o", "--out", help="the review folder (default WORK/bulkcut)")
    a = ap.parse_args()
    return {"stage": cmd_stage, "collect": cmd_collect}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
