#!/usr/bin/env python3
"""Look after the library catalog.

  catalog.py status                  where the library is, clip counts, what still needs describing
  catalog.py list [--source NAME]    every clip (id, file, range, description)
  catalog.py check [--apply]         find entries whose media file is gone (moved or deleted);
                                     --apply drops them (logged in catalog/removed.jsonl)
  catalog.py remove ID ... [--apply] take clips out of the library: the entry goes, a cut clip's
                                     file moves to <library>/_trash/, a raw original is never touched

Dry run by default for everything that changes the catalog.
stdout: JSON. Exit 0 ok, 1 library unreachable, 4 a setting is unset.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def cmd_status(a):
    root = C.root_or_exit()
    clips = C.load_catalog(root)["clips"]
    by_src = {}
    for c in clips:
        by_src[c["source_project"]] = by_src.get(c["source_project"], 0) + 1
    print(json.dumps({
        "library": str(root), "clips": len(clips),
        "seconds": round(sum((c["end"] - c["start"]) for c in clips), 1),
        "described": sum(1 for c in clips if c.get("description")),
        "judged": sum(1 for c in clips if c.get("verdict")),
        "in_place": sum(1 for c in clips if c["in_place"]),
        "by_source": by_src}, indent=2))
    return 0


def cmd_list(a):
    root = C.root_or_exit()
    rows = [{"id": c["id"], "path": str(C.to_abs(root, c["path"])), "start": c["start"], "end": c["end"],
             "source_project": c["source_project"], "description": c.get("description", ""),
             "verdict": c.get("verdict")}
            for c in C.load_catalog(root)["clips"] if not a.source or c["source_project"] == C.slugify(a.source)]
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def _drop(root, ids, reason):
    data = C.load_catalog(root)
    with open(C.catalog_dir(root) / "removed.jsonl", "a", encoding="utf-8") as logf:
        for c in [c for c in data["clips"] if c["id"] in ids]:
            f = C.to_abs(root, c["path"])
            if not c["in_place"] and f.exists():
                dst = C.free_path(root / "_trash" / f.name)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dst))
                c["trashed_to"] = C.to_stored(root, dst)
            c["removed"], c["removed_why"] = C.now_iso(), reason
            logf.write(json.dumps(c, ensure_ascii=False) + "\n")
    data["clips"] = [c for c in data["clips"] if c["id"] not in ids]
    C.save_catalog(root, data)


def cmd_check(a):
    root = C.root_or_exit()
    clips = C.load_catalog(root)["clips"]
    gone = [c for c in clips if not C.to_abs(root, c["path"]).exists()]
    if gone and len(gone) > 0.5 * len(clips) and len(clips) > 10:
        sys.exit(f"{len(gone)} of {len(clips)} clips are missing: that looks like an unplugged drive or "
                 f"unmounted share, not deleted files. Connect it and check again. Nothing changed.")
    if a.apply and gone:
        with C.Lock(root, "catalog check"):
            _drop(root, {c["id"] for c in gone}, "media file missing")
    print(json.dumps({"missing": [str(C.to_abs(root, c["path"])) for c in gone], "dropped": bool(a.apply and gone)},
                     indent=2))
    return 0


def cmd_remove(a):
    root = C.root_or_exit()
    clips = {c["id"]: c for c in C.load_catalog(root)["clips"]}
    unknown = [i for i in a.ids if i not in clips]
    if unknown:
        sys.exit(f"not in the catalog: {unknown}")
    if not a.apply:
        print(json.dumps({"dry_run": True, "would_remove": [
            {"id": i, "file": str(C.to_abs(root, clips[i]["path"])), "in_place": clips[i]["in_place"]} for i in a.ids]},
            indent=2))
        return 0
    with C.Lock(root, "catalog remove"):
        _drop(root, set(a.ids), a.reason or "removed by the user")
    print(json.dumps({"removed": len(a.ids), "trash": str(root / "_trash")}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    l = sub.add_parser("list")
    l.add_argument("--source")
    c = sub.add_parser("check")
    c.add_argument("--apply", action="store_true")
    r = sub.add_parser("remove")
    r.add_argument("ids", nargs="+")
    r.add_argument("--reason")
    r.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    return {"status": cmd_status, "list": cmd_list, "check": cmd_check, "remove": cmd_remove}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
