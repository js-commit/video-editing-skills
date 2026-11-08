#!/usr/bin/env python3
"""Back up a Resolve project before scripts edit it, and restore it.

Edits made through the scripting API do NOT land in Resolve's undo history
(Cmd/Ctrl+Z will not take them back). The backups are the undo:

  create   export the whole project to a .drp file (Resolve's project archive
           format, without media) and, with --timeline, duplicate that timeline
           as "<name> backup <time>". Every script here refuses to touch a
           timeline with "backup" in its name, so the copy stays pristine.
  list     the .drp backups of a project, newest first.
  restore  import a .drp as a NEW project ("<project> restored <time>"); the
           current project is never overwritten. Open it from the Project
           Manager (Shift+1, or File > Project Manager).

apply_plan.py, close_gaps.py and ripple_extend.py call export_drp() on their
own before every mutating run and stop if it fails. When ExportProject fails
(Resolve's scripting half-wedged after a long session), save your work,
relaunch Resolve and re-run.

Backups go to <project>/<work>/broll-brick-layer/resolve-backups/ (or the cache
folder when the Resolve project has no project folder).

Usage:
  backup.py create --project P [--timeline T] [-m "before b-roll pass 2"]
  backup.py list --project P
  backup.py restore FILE.drp [--name "new project name"]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402


def backup_dir(project_name):
    return B.work_dir(project_name, "resolve-backups")


def export_drp(pm, proj, note=""):
    """Export the project to a timestamped .drp; exits if Resolve refuses."""
    name = proj.GetName()
    pm.SaveProject()
    dest = os.path.join(backup_dir(name), f"{B.slugify(name)}-{time.strftime('%Y%m%d-%H%M%S')}.drp")
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = dest[:-4] + f"-{n}.drp"
    if not pm.ExportProject(name, dest) or not os.path.exists(dest):
        sys.exit("ExportProject failed, so there is no undo point: stopping before any change. Save your work, "
                 "relaunch DaVinci Resolve and re-run.")
    if not zipfile.is_zipfile(dest):
        sys.exit(f"the exported {dest} is not a readable .drp: stopping before any change")
    if note:
        with open(dest[:-4] + ".txt", "w") as f:
            f.write(note + "\n")
    B.log(f"backup: {dest}")
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--project", required=True)
    c.add_argument("--timeline", default=None, help="also duplicate this timeline as a backup timeline")
    c.add_argument("-m", "--message", default="")
    ls = sub.add_parser("list")
    ls.add_argument("--project", required=True)
    r = sub.add_parser("restore")
    r.add_argument("drp")
    r.add_argument("--name", default=None)
    a = ap.parse_args()

    if a.cmd == "list":
        files = sorted(glob.glob(os.path.join(backup_dir(a.project), "*.drp")), key=os.path.getmtime, reverse=True)
        out = []
        for f in files:
            note = f[:-4] + ".txt"
            out.append({"file": f, "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(f))),
                        "note": open(note).read().strip() if os.path.exists(note) else ""})
        print(json.dumps(out, indent=1))
        return
    if a.cmd == "restore":
        if not zipfile.is_zipfile(a.drp):
            sys.exit(f"{a.drp} is not a readable .drp")
        pm = B.vr().connect().GetProjectManager()
        base = os.path.splitext(os.path.basename(a.drp))[0]
        name = a.name or f"{base} restored {time.strftime('%H%M%S')}"
        if not pm.ImportProject(os.path.abspath(a.drp), name):
            sys.exit(f"ImportProject failed (a project named {name!r} may already exist; pass --name)")
        print(json.dumps({"restored_as": name}))
        return
    pm, proj = B.open_project(a.project)
    dup = None
    if a.timeline:
        tl = B.timeline_by_name(proj, a.timeline)
        dup_name = f"{a.timeline} backup {time.strftime('%Y%m%d-%H%M%S')}"
        d = B.vr().duplicate_timeline(proj, tl, dup_name)
        if not d:
            sys.exit("DuplicateTimeline failed: no backup timeline made")
        dup = d.GetName()
        B.log(f"backup timeline: {dup}")
    drp = export_drp(pm, proj, a.message)
    print(json.dumps({"drp": drp, "backup_timeline": dup}))


if __name__ == "__main__":
    main()
