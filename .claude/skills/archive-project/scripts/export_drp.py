#!/usr/bin/env python3
"""Export a DaVinci Resolve project as a .drp file (read-only: nothing in Resolve changes).

A .drp is the whole Resolve project (timelines, media pool, grades) in one file.
Saved inside the project folder, it travels with an archive, lets the archive's
reference gate see which files Resolve uses, and can be imported again later
(Project Manager > right-click > Import Project).

    export_drp.py --list                                   # project names in the Project Manager's current folder
    export_drp.py --project "My Review" --out <project>/resolve
    export_drp.py --project "My Review" --out <dir> --no-stills   # skip gallery stills and LUTs

Needs DaVinci Resolve Studio running with external scripting enabled
(Preferences > System > General > External scripting using: Local). The free
version blocks external scripts: the script prints the manual steps instead.
It never opens, saves, switches or deletes a project; it only calls
ProjectManager.ExportProject, which writes the project's last SAVED state, so
save in Resolve first (Cmd+S / Ctrl+S).

Output: JSON on stdout. Exit 0 ok, 1 export failed, 2 usage, 4 editor.nle unset.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import settings  # noqa: E402

MANUAL = ("In DaVinci Resolve: save the project (Cmd+S / Ctrl+S), open the Project Manager "
          "(Shift+1, or the house icon bottom right), right-click the project > Export Project..., "
          "and save it as {out}.")


def safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "project"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="list project names (read-only)")
    p.add_argument("--project", help="the Resolve project name, exactly as in the Project Manager")
    p.add_argument("--out", help="folder to write <project>.drp into (usually <project folder>/resolve)")
    p.add_argument("--no-stills", action="store_true", help="leave gallery stills and LUTs out")
    a = p.parse_args(argv)
    if not a.list and not (a.project and a.out):
        p.print_help()
        return 2
    try:
        editor = settings.get("editor.nle", required=True,
                              hint="resolve-studio, resolve-free or none")
    except settings.SettingMissing as e:
        settings.exit_missing(e)
        return 4
    out_file = (Path(a.out).expanduser() / f"{safe_name(a.project)}.drp") if a.out else None
    if editor != "resolve-studio":
        print(json.dumps({"exported": False, "reason": f"editor.nle is {editor}: no external scripting",
                          "manual": MANUAL.format(out=out_file or "<project folder>/resolve/<name>.drp")}))
        return 0

    from vidkit.resolve import connect
    resolve = connect()
    pm = resolve.GetProjectManager()
    names = list(pm.GetProjectListInCurrentFolder() or [])
    if a.list:
        cur = pm.GetCurrentProject()
        print(json.dumps({"folder": pm.GetCurrentFolder(), "projects": names,
                          "open": cur.GetName() if cur else None}, indent=2))
        return 0
    if a.project not in names:
        print(json.dumps({"exported": False, "reason": "no such project in the Project Manager's current folder",
                          "projects": names}, indent=2))
        return 1
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        out_file = out_file.with_name(f"{out_file.stem}-{time.strftime('%Y%m%d-%H%M%S')}.drp")
    ok = bool(pm.ExportProject(a.project, str(out_file), not a.no_stills))
    size = out_file.stat().st_size if out_file.exists() else 0
    print(json.dumps({"exported": ok and size > 0, "project": a.project, "drp": str(out_file),
                      "bytes": size}, indent=2))
    return 0 if ok and size > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
