#!/usr/bin/env python3
"""Step 7: apply the decisions the user copied from the review page.

  apply_decisions.py --plan W/plan.json --decisions FILE   (or - for stdin)

Decisions JSON: {"<card key>": {"choice": "...", "feedback": "...",
"folder_name": "...", "project": "..."}}. Choices:
  keep                 leave the card as planned (with folder_name: same place, new folder name)
  project:<name>       an existing project; project:new with "project": "<new name>"
  home-videos | broll-library | trash
  skip                 leave these files where they are (dropped from the plan)
Undecided cards given a choice become moves; undecided cards left on "keep"
stay where they are.

The page writes choice + feedback. Mechanical changes are applied (plan.json is
backed up to plan.prev.json); feedback text and a new project with no name are
printed under `needs_claude`. Claude acts on them by running this again with a
small decisions JSON of its own (folder_name / project fields), or by
re-classifying, then re-runs build_review.py if anything changed.
stdout: JSON summary.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import make_plan  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--decisions", required=True)
    a = ap.parse_args()
    plan_p = Path(a.plan)
    plan = C.load_json(plan_p)
    raw = sys.stdin.read() if a.decisions == "-" else Path(a.decisions).read_text(encoding="utf-8")
    raw = raw.strip()
    decisions = {} if raw.lower() in ("", "approved", '"approved"') else json.loads(raw)
    input_dir = Path(plan["input_dir"])
    items = {m["key"]: ("move", m) for m in plan["moves"]}
    items.update({x["key"]: ("undecided", x) for x in plan["needs_decision"] + plan.get("unclassified", [])})
    changed, skipped, needs, unknown = [], [], [], []
    new_moves = list(plan["moves"])
    still_undecided = []
    taken_undecided = set()
    for key, d in decisions.items():
        if key not in items:
            unknown.append(key)
            continue
        kind, item = items[key]
        choice = (d.get("choice") or "keep").strip()
        fb = (d.get("feedback") or "").strip()
        if fb:
            needs.append({"key": key, "choice": choice, "feedback": fb})
        if choice == "keep" and not (kind == "move" and d.get("folder_name")):
            continue
        if choice == "skip":
            skipped.append(key)
            if kind == "move":
                new_moves = [m for m in new_moves if m["key"] != key]
            taken_undecided.add(key)
            continue
        if choice == "keep":                      # same destination, new folder name
            dest, project = item["destination"], item.get("project")
        else:
            dest, project = choice, None
        if choice.startswith("project:"):
            dest, project = "project", d.get("project") or choice.split(":", 1)[1]
            if project == "new":
                needs.append({"key": key, "choice": choice, "feedback": fb or "(no name given)",
                              "todo": 'ask for the new project\'s name, then re-run with {"choice": "project:new", '
                                      '"project": "<name>"} for this key'})
                continue
        if dest not in C.DESTINATIONS:
            unknown.append(f"{key}: choice {choice!r}")
            continue
        first = item.get("first_date")
        folder = d.get("folder_name") or item.get("folder_name") or f"{item['unit_id'].lower()}-footage"
        dest_dir, problem = C.dest_dir_for(dest, project=project, folder_name=folder, input_dir=input_dir,
                                           first_date=first)
        if problem:
            needs.append({"key": key, "choice": choice, "problem": problem})
            continue
        move = dict(item) if kind == "move" else {
            "key": key, "unit_id": item["unit_id"], "files": item["files"], "bytes": item["bytes"],
            "reason": item.get("notes", ""), "first_date": first}
        pdir = C.dest_roots()["projects_dir"]
        move.update({"destination": dest, "project": project, "folder_name": folder, "dest_dir": str(dest_dir),
                     "new_project": bool(project) and not (pdir / project).is_dir(),
                     "confidence": "user", "reason": (move.get("reason") or "") + " [changed by the user]"})
        new_moves = [m for m in new_moves if m["key"] != key] + [move]
        taken_undecided.add(key)
        changed.append(key)
    for x in plan["needs_decision"] + plan.get("unclassified", []):
        if x["key"] not in taken_undecided:
            still_undecided.append(x)
    shutil.copy2(plan_p, plan_p.with_name("plan.prev.json"))
    plan["moves"] = new_moves
    plan["needs_decision"] = [x for x in still_undecided if x in plan["needs_decision"]]
    plan["unclassified"] = [x for x in still_undecided if x in plan.get("unclassified", [])]
    plan["skipped_by_user"] = sorted(set(plan.get("skipped_by_user", []) + skipped))
    plan["problems"] = make_plan.check(plan)
    C.write_json(plan_p, plan)
    print(json.dumps({"changed": changed, "skipped": skipped, "unknown": unknown, "needs_claude": needs,
                      "still_undecided": [x["key"] for x in still_undecided], "problems": plan["problems"],
                      "moves": len(plan["moves"])}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
