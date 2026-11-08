#!/usr/bin/env python3
"""Keep the library clean: broll-judge agents look at clips that might be a
talking head (a-roll) or junk, and the user decides what leaves the library.

  judge.py briefs -o DIR [--all] [--per-brief 20]
      clips with no verdict whose description hints at a person talking, a dark /
      blurry / empty frame, or that have no description at all (--all: every
      clip with no verdict). Writes DIR/brief_N.json, prints the paths.
  judge.py collect DIR
      files every DIR/verdicts_N.json in the catalog.
  judge.py prune [--only aroll|junk] [--except ID ...] [--apply]
      lists (default) or removes clips judged aroll / junk. Removing takes the
      entry out of the catalog (kept in catalog/removed.jsonl) and moves a cut
      clip's file to <library>/_trash/. A raw original indexed in place is never
      touched: only its catalog entry goes.
  judge.py keep ID ... [--reason TEXT]
      the user's call: mark clips as b-roll so prune leaves them alone.

stdout: JSON. Exit 0 ok, 1 unanswered briefs, 4 a setting is unset.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

SUSPECT = re.compile(r"\b(talk\w*|speak\w*|face|presenter|person|man|woman|camera-facing|looking at the camera|"
                     r"dark|black|blurr?y|out of focus|empty|floor|ceiling|nothing|lens cap)\b", re.I)
VERDICTS = ("broll", "broll-face", "aroll", "junk")


def cmd_briefs(a):
    root = C.root_or_exit()
    data = C.load_catalog(root)
    out = Path(a.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    todo = [c for c in data["clips"] if c.get("sheet") and not c.get("verdict")
            and (a.all or not c.get("description") or SUSPECT.search(c.get("description", "")))]
    briefs = []
    for i in range(0, len(todo), a.per_brief):
        n = len(briefs) + 1
        brief = {"verdicts_path": str(out / f"verdicts_{n}.json"),
                 "clips": [{"clip_id": c["id"], "sheet": str(C.to_abs(root, c["sheet"])),
                            "description": c.get("description", ""), "source_project": c["source_project"],
                            "length_s": round((c["end"] - c["start"]) / (c.get("speed") or 1.0), 1)}
                           for c in todo[i:i + a.per_brief]]}
        p = out / f"brief_{n}.json"
        C.write_json(p, brief)
        briefs.append(str(p))
    print(json.dumps({"clips": len(todo), "briefs": briefs,
                      "next": "spawn one broll-judge agent per brief (prompt: 'Brief: <path>'), "
                              f"all in one message; then judge.py collect {out}"}, indent=2))
    return 0


def cmd_collect(a):
    root = C.root_or_exit()
    d = Path(a.dir).expanduser().resolve()
    verdicts, unanswered = {}, []
    for bp in sorted(d.glob("brief_*.json")):
        vp = Path(json.loads(bp.read_text())["verdicts_path"])
        if not vp.exists():
            unanswered.append(str(bp))
            continue
        for v in json.loads(vp.read_text()).get("verdicts", []):
            if v.get("verdict") in VERDICTS:
                verdicts[v["clip_id"]] = v
    counts = {}
    with C.Lock(root, "judge collect"):
        data = C.load_catalog(root)
        for c in data["clips"]:
            v = verdicts.get(c["id"])
            if v and c.get("verdict_by") != "user":
                c["verdict"], c["verdict_reason"], c["verdict_by"] = v["verdict"], v.get("reason", ""), "broll-judge"
                counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        C.save_catalog(root, data)
    print(json.dumps({"filed": counts, "unanswered_briefs": unanswered}, indent=2))
    return 1 if unanswered else 0


def cmd_prune(a):
    root = C.root_or_exit()
    kinds = (a.only,) if a.only else ("aroll", "junk")
    data = C.load_catalog(root)
    gone = [c for c in data["clips"] if c.get("verdict") in kinds and c["id"] not in set(a.exclude or [])]
    listing = [{"id": c["id"], "verdict": c["verdict"], "reason": c.get("verdict_reason", ""),
                "sheet": str(C.to_abs(root, c["sheet"])) if c.get("sheet") else "",
                "file": str(C.to_abs(root, c["path"])), "in_place": c["in_place"]} for c in gone]
    if not a.apply:
        print(json.dumps({"dry_run": True, "would_remove": listing,
                          "note": "show the user samples (sheets + reasons); re-run with --apply on their yes"}, indent=2))
        return 0
    with C.Lock(root, "judge prune"):
        data = C.load_catalog(root)
        ids = {c["id"] for c in gone}
        trash = root / "_trash"
        removed_log = C.catalog_dir(root) / "removed.jsonl"
        with open(removed_log, "a", encoding="utf-8") as logf:
            for c in [c for c in data["clips"] if c["id"] in ids]:
                if not c["in_place"]:
                    f = C.to_abs(root, c["path"])
                    if f.exists():
                        dst = C.free_path(trash / f.relative_to(root) if str(f).startswith(str(root)) else trash / f.name)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(f), str(dst))
                        c["trashed_to"] = C.to_stored(root, dst)
                c["removed"] = C.now_iso()
                logf.write(json.dumps(c, ensure_ascii=False) + "\n")
        data["clips"] = [c for c in data["clips"] if c["id"] not in ids]
        C.save_catalog(root, data)
    print(json.dumps({"removed": len(ids), "trash": str(root / "_trash"),
                      "note": "cut clips are in _trash (empty it yourself when happy); originals untouched"}, indent=2))
    return 0


def cmd_keep(a):
    root = C.root_or_exit()
    with C.Lock(root, "judge keep"):
        data = C.load_catalog(root)
        n = 0
        for c in data["clips"]:
            if c["id"] in a.ids:
                c["verdict"], c["verdict_reason"], c["verdict_by"] = "broll", a.reason or "kept by the user", "user"
                n += 1
        C.save_catalog(root, data)
    print(json.dumps({"kept": n}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("briefs")
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--all", action="store_true")
    b.add_argument("--per-brief", type=int, default=20)
    c = sub.add_parser("collect")
    c.add_argument("dir")
    p = sub.add_parser("prune")
    p.add_argument("--only", choices=["aroll", "junk"])
    p.add_argument("--except", dest="exclude", nargs="*")
    p.add_argument("--apply", action="store_true")
    k = sub.add_parser("keep")
    k.add_argument("ids", nargs="+")
    k.add_argument("--reason")
    a = ap.parse_args()
    return {"briefs": cmd_briefs, "collect": cmd_collect, "prune": cmd_prune, "keep": cmd_keep}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
