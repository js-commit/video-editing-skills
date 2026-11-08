#!/usr/bin/env python3
"""Step 8: move the files of an approved plan. Dry run unless --execute.

  move.py --plan W/plan.json                 show every move (dry run, the default)
  move.py --plan W/plan.json --approve       record the user's yes for THIS exact plan
  move.py --plan W/plan.json --execute       move (refused unless the plan is approved
                                             and unchanged since)
  move.py --undo W/moves.log.jsonl [--execute]   put everything back

Safety, enforced here:
- MOVE only: same drive = rename; across drives (a NAS) = copy, check the size,
  then remove the source. A copy that does not match is removed and the source kept.
- Never overwrite: an existing file at the destination stops that move.
- Never delete: "trash" is a folder (default <inbox>/_trash) the user empties.
- Sidecars travel: every non-media file next to a clip whose name starts with the
  clip's name (transcripts, .xml, .lrf, .thm, .srt) moves with it.
- --approve stores a fingerprint of the moves; editing the plan afterwards
  needs a new approval. Claude runs --approve only after the user's explicit yes
  to the dry-run list.
- Every move is logged to W/moves.log.jsonl; re-running resumes, --undo reverses.

stdout: JSON summary. Exit 0 ok, 1 error, 3 refused or some moves stopped.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from vidkit import settings  # noqa: E402


FORCE_COPY = False   # tests: take the copy-verify-remove path even on one drive


def fingerprint(plan: dict) -> str:
    core = [(m["key"], m["dest_dir"], sorted(m["files"])) for m in plan["moves"]]
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def move_file(src: Path, dst: Path) -> str:
    if dst.exists():
        raise FileExistsError(str(dst))
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        same = src.stat().st_dev == dst.parent.stat().st_dev and not FORCE_COPY
    except OSError:
        same = False
    if same:
        os.rename(src, dst)
        return "rename"
    size = src.stat().st_size
    shutil.copy2(src, dst)
    if dst.stat().st_size != size:
        dst.unlink()
        raise IOError(f"copy of {src} did not verify; source kept")
    src.unlink()
    return "copy-verify-remove"


def unreachable_roots(plan: dict) -> list:
    """Destination roots that do not exist (unmounted NAS, unplugged drive)."""
    out = []
    roots = [p for p in C.dest_roots().values() if p]
    for m in plan["moves"]:
        d = Path(m["dest_dir"])
        root = next((r for r in roots if str(d).startswith(str(r))), None)
        if root is not None and not root.exists() and str(root) not in out:
            out.append(str(root))
    return out


def run_plan(a) -> int:
    plan_p = Path(a.plan)
    plan = C.load_json(plan_p)
    work = Path(plan["work_dir"])
    log_p = work / "moves.log.jsonl"
    rows, problems = [], []
    total = 0
    for m in plan["moves"]:
        if not m.get("dest_dir"):
            problems.append(f"{m['key']}: no destination folder")
            continue
        for f in m["files"]:
            src = Path(f)
            dst = Path(m["dest_dir"]) / src.name
            side = C.sidecars_of(src.parent, [src.name]).get(src.name, []) if src.exists() else []
            if not src.exists():
                if dst.exists():
                    rows.append({"key": m["key"], "src": f, "dst": str(dst), "status": "already moved"})
                else:
                    problems.append(f"{m['key']}: {f} is missing")
                continue
            if dst.exists():
                problems.append(f"{m['key']}: {dst} already exists")
            total += src.stat().st_size
            rows.append({"key": m["key"], "src": f, "dst": str(dst), "sidecars": side})
    roots = unreachable_roots(plan)
    if roots:
        hint = " It is on your NAS: mount it." if settings.get("nas.enabled", default=False) else ""
        problems.append(f"destination folder not reachable: {', '.join(roots)}.{hint} "
                        "(Connect the drive / mount the share, then run again.)")
    fp = fingerprint(plan)
    appr_p = plan_p.with_name(plan_p.name + ".approved")
    approved = appr_p.exists() and appr_p.read_text().strip() == fp
    summary = {"moves": len(plan["moves"]), "files": sum(1 for r in rows if "status" not in r),
               "sidecars": sum(len(r.get("sidecars", [])) for r in rows), "bytes": C.human_bytes(total),
               "approved": approved, "problems": problems,
               "left_in_place": [x["key"] for x in plan.get("needs_decision", []) + plan.get("unclassified", [])]}
    if a.approve:
        if problems:
            summary["refused"] = "fix the problems first"
            print(json.dumps(summary, indent=2))
            return 3
        appr_p.write_text(fp + "\n")
        summary["approved"] = True
        print(json.dumps(summary, indent=2))
        return 0
    if not a.execute:
        for r in rows:
            C.log(f"  {r['key']:6s} {r.get('status', 'move')}: {r['src']}\n         -> {r['dst']}"
                  + (f"  (+ {', '.join(r['sidecars'])})" if r.get("sidecars") else ""))
        summary["dry_run"] = True
        print(json.dumps(summary, indent=2))
        return 0
    if not approved:
        summary["refused"] = ("this plan is not approved (or changed after approval): show the user the dry run, "
                              "and after their explicit yes run --approve, then --execute")
        print(json.dumps(summary, indent=2))
        return 3
    if problems:
        summary["refused"] = "fix the problems first"
        print(json.dumps(summary, indent=2))
        return 3
    moved, failed = 0, []
    with open(log_p, "a", encoding="utf-8") as logf:
        for r in rows:
            if r.get("status"):
                continue
            src, dst = Path(r["src"]), Path(r["dst"])
            try:
                mode = move_file(src, dst)
                logf.write(json.dumps({"t": now(), "key": r["key"], "src": str(src), "dst": str(dst), "mode": mode}) + "\n")
                for s in r["sidecars"]:
                    s_src, s_dst = src.parent / s, dst.parent / s
                    if s_src.exists():
                        m2 = move_file(s_src, s_dst)
                        logf.write(json.dumps({"t": now(), "key": r["key"], "src": str(s_src), "dst": str(s_dst),
                                               "mode": m2, "sidecar": True}) + "\n")
                logf.flush()
                moved += 1
            except (OSError, IOError) as e:
                failed.append(f"{r['key']}: {e}")
    summary.update({"moved": moved, "failed": failed, "log": str(log_p)})
    lib = [m["dest_dir"] for m in plan["moves"] if m["destination"] == "broll-library"]
    if lib:
        summary["next_index_library"] = [f"python3 .claude/skills/broll-library/scripts/index_folder.py \"{d}\"" for d in lib]
    newp = sorted({m["project"] for m in plan["moves"] if m.get("new_project")})
    if newp:
        summary["new_projects"] = newp
    print(json.dumps(summary, indent=2))
    return 3 if failed else 0


def run_undo(a) -> int:
    log_p = Path(a.undo)
    live = {}                                  # dst -> move entry, in log order
    for line in log_p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if "undo_of" in e:
            live.pop(e["undo_of"], None)
        elif "src" in e:
            live[e["dst"]] = e
    entries = list(live.values())
    rows, problems = [], []
    for e in reversed(entries):
        src, dst = Path(e["dst"]), Path(e["src"])
        if not src.exists():
            problems.append(f"{src} is not there any more")
        elif dst.exists():
            problems.append(f"{dst} already exists")
        else:
            rows.append((src, dst))
    if not a.execute:
        for s, d in rows:
            C.log(f"  back: {s}\n     -> {d}")
        print(json.dumps({"dry_run": True, "would_move_back": len(rows), "problems": problems}, indent=2))
        return 0
    done = 0
    with open(log_p, "a", encoding="utf-8") as logf:
        for s, d in rows:
            move_file(s, d)
            logf.write(json.dumps({"t": now(), "undo_of": str(s), "back_to": str(d)}) + "\n")
            done += 1
    print(json.dumps({"moved_back": done, "problems": problems,
                      "note": "folders the move created are left in place (empty)"}, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--undo", metavar="LOG")
    a = ap.parse_args()
    if a.undo:
        return run_undo(a)
    if not a.plan:
        ap.error("--plan is required")
    return run_plan(a)


if __name__ == "__main__":
    sys.exit(main())
