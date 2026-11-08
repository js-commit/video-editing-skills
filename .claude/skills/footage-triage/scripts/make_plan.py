#!/usr/bin/env python3
"""Step 5: turn the classifier verdicts into a move plan.

  make_plan.py --inventory W/inventory.json [--verdicts W/verdicts]

Every unit becomes one move (all its files to one folder), or several when the
classifier split it with confident per-clip destinations. Low confidence,
"undecided", an unknown destination or a destination whose folder setting is
unset go to `needs_decision` instead: the user decides those on the review page.
Units no verdict covers are listed as `unclassified` (re-spawn that brief).

Writes W/plan.json (the format is in reference/plan-format.md) and checks it:
no file planned twice, no file that would overwrite an existing one.
stdout: JSON summary. Exit 0 ok, 1 error, 3 some briefs have no verdicts yet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def build_move(key, unit, files, dest, project, new_project, folder_name, confidence, reason, input_dir):
    first = min(f["capture_time"] for f in files)[:10]
    folder_name = folder_name or f"{first}-{C.slugify(unit['device'])}"
    dest_dir, problem = C.dest_dir_for(dest, project=project, folder_name=folder_name, input_dir=input_dir,
                                       first_date=first)
    return {"key": key, "unit_id": unit["id"], "destination": dest, "project": project,
            "new_project": bool(new_project), "folder_name": folder_name, "first_date": first,
            "dest_dir": str(dest_dir) if dest_dir else None, "confidence": confidence, "reason": reason,
            "files": [f["path"] for f in files], "bytes": sum(f["bytes"] for f in files)}, problem


def check(plan: dict) -> list:
    problems, seen, landing = [], {}, {}
    for m in plan["moves"]:
        for f in m["files"]:
            if f in seen:
                problems.append(f"{Path(f).name} is planned twice ({seen[f]} and {m['key']})")
            seen[f] = m["key"]
            if m["dest_dir"]:         # two sources with one name (cards restart numbering) would collide
                spot = (str(Path(m["dest_dir"])), Path(f).name.casefold())
                if spot in landing and landing[spot] != f:
                    problems.append(f"{m['key']}: {landing[spot]} and {f} would both land as "
                                    f"{Path(m['dest_dir']) / Path(f).name}: split the unit or give one a "
                                    f"different folder_name")
                landing.setdefault(spot, f)
            if m["dest_dir"] and (Path(m["dest_dir"]) / Path(f).name).exists():
                problems.append(f"{m['key']}: {Path(m['dest_dir']) / Path(f).name} already exists (never overwritten)")
            if not Path(f).exists():
                problems.append(f"{m['key']}: {f} no longer exists")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--verdicts")
    a = ap.parse_args()
    inv = C.load_json(a.inventory)
    work = Path(inv["work_dir"])
    vdir = Path(a.verdicts) if a.verdicts else work / "verdicts"
    input_dir = Path(inv["input_dir"])
    verdicts, missing = {}, []
    for bp in sorted((work / "briefs").glob("brief_*.json")):
        vp = Path(C.load_json(bp)["verdicts_path"])
        if not vp.exists() and (vdir / vp.name).exists():
            vp = vdir / vp.name
        if not vp.exists():
            missing.append(str(bp))
            continue
        try:
            for v in C.load_json(vp).get("units", []):
                verdicts[v.get("unit_id")] = v
        except ValueError as e:
            missing.append(f"{bp} (verdicts not valid JSON: {e})")

    known = {p["name"] for p in inv["projects"]}
    plan = {"input_dir": str(input_dir), "work_dir": str(work), "trash_dir": inv["destinations"]["trash_dir"],
            "moves": [], "needs_decision": [], "unclassified": [], "content": {}}
    for u in inv["units"]:
        v = verdicts.get(u["id"])
        if not v:
            plan["unclassified"].append({"key": u["id"], "unit_id": u["id"], "files": [f["path"] for f in u["files"]],
                                         "first_date": u["first"][:10],
                                         "bytes": u["bytes"], "notes": "no verdict yet"})
            continue
        by_rel = {f["rel"]: f for f in u["files"]}
        for c in v.get("clips") or []:
            if c.get("file") in by_rel and c.get("content"):
                plan["content"][by_rel[c["file"]]["path"]] = c["content"]
        groups = {}
        default = (v.get("destination"), v.get("project"), v.get("new_project", False), v.get("folder_name"))
        for f in u["files"]:
            c = next((c for c in v.get("clips") or [] if c.get("file") == f["rel"]), {})
            if c.get("destination") and c.get("confidence", v.get("confidence")) == "high":
                k = (c["destination"], c.get("project"), c.get("new_project", False), c.get("folder_name"))
            else:
                k = default
            groups.setdefault(k, []).append(f)
        for i, ((dest, project, newp, folder), files) in enumerate(groups.items(), 1):
            key = u["id"] if len(groups) == 1 else f"{u['id']}.{i}"
            conf = v.get("confidence", "low")
            if dest == "project" and project and project not in known and not newp:
                newp = True
            if dest not in C.DESTINATIONS or conf == "low":
                plan["needs_decision"].append({"key": key, "unit_id": u["id"], "files": [f["path"] for f in files],
                                               "first_date": min(f["capture_time"] for f in files)[:10],
                                               "bytes": sum(f["bytes"] for f in files), "suggestion": dest,
                                               "project": project, "folder_name": folder,
                                               "notes": v.get("reason", ""), "confidence": conf})
                continue
            move, problem = build_move(key, u, files, dest, project, newp, folder, conf, v.get("reason", ""), input_dir)
            if problem:
                plan["needs_decision"].append({"key": key, "unit_id": u["id"], "files": move["files"],
                                               "first_date": move["first_date"],
                                               "bytes": move["bytes"], "suggestion": dest, "project": project,
                                               "folder_name": move["folder_name"],
                                               "notes": f"{v.get('reason', '')} [{problem}]", "confidence": conf})
            else:
                plan["moves"].append(move)
    plan["problems"] = check(plan)
    C.write_json(work / "plan.json", plan)
    by_dest = {}
    for m in plan["moves"]:
        d = by_dest.setdefault(m["destination"], {"moves": 0, "files": 0, "bytes": 0})
        d["moves"] += 1
        d["files"] += len(m["files"])
        d["bytes"] += m["bytes"]
    print(json.dumps({"plan": str(work / "plan.json"), "moves": len(plan["moves"]),
                      "needs_decision": len(plan["needs_decision"]), "unclassified": len(plan["unclassified"]),
                      "by_destination": {k: {**d, "bytes": C.human_bytes(d["bytes"])} for k, d in by_dest.items()},
                      "problems": plan["problems"], "briefs_without_verdicts": missing}, indent=2))
    return 3 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
