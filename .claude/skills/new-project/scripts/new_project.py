#!/usr/bin/env python3
"""Create a video project folder from the user's project layout.

    new_project.py "<name>" [--resolve-project NAME] [--dry-run]

<name> becomes a folder under settings paths.projects_dir (or pass an absolute
path to put the project somewhere else). Inside it, one folder per entry of
settings project_layout (footage, audio, graphics, drafts, finals, work...).
Safe to re-run: existing folders are left alone and only missing ones are
added. A small project.json notes the name, the creation date and, optionally,
the DaVinci Resolve project that goes with it.

Prints JSON on stdout. Exit codes: 0 ok, 1 projects folder unreachable,
2 usage, 4 paths.projects_dir is not set.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import settings  # noqa: E402

BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_name(name: str) -> str:
    n = BAD_CHARS.sub(" ", name.strip())
    return re.sub(r"\s+", " ", n).strip(" .-")


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Create a project folder from settings project_layout.")
    ap.add_argument("name", help='project name, e.g. "phone case review", or an absolute path')
    ap.add_argument("--resolve-project", default=None, help="name of the DaVinci Resolve project to note")
    ap.add_argument("--dry-run", action="store_true", help="show what would be created; create nothing")
    args = ap.parse_args(argv)

    given = Path(args.name).expanduser()
    if given.is_absolute():
        project = Path(given.parent, clean_name(given.name))
        root = project.parent
    else:
        name = clean_name(args.name)
        if not name:
            print("the project name is empty after removing characters folders cannot hold", file=sys.stderr)
            return 2
        try:
            root = settings.get_path("paths.projects_dir", required=True,
                                     hint="the folder where your video projects live")
        except settings.SettingMissing as e:
            settings.exit_missing(e)
        project = root / name

    # A projects folder on a drive that is not plugged in must not be
    # recreated as an empty local folder: require its parent to exist.
    if not root.exists() and not root.parent.exists():
        print(f"{root} is not reachable (unplugged drive or unmounted network share?). "
              f"Connect it, or change paths.projects_dir.", file=sys.stderr)
        return 1

    layout = settings.get("project_layout", default={}) or {}
    parts = []
    for key, rel in layout.items():
        if isinstance(rel, str) and rel.strip():
            relp = Path(rel.strip())
            if relp.is_absolute() or ".." in relp.parts:
                print(f"skipping project_layout.{key} = {rel!r}: must be a folder inside the project", file=sys.stderr)
                continue
            parts.append((key, relp))

    wanted = [project] + [project / rel for _, rel in parts]
    created = [str(p) for p in wanted if not p.exists()]
    existing = [str(p) for p in wanted if p.exists()]

    meta_path = project / "project.json"
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    new_meta = dict(meta)
    new_meta.setdefault("name", project.name)
    new_meta.setdefault("created", dt.date.today().isoformat())
    if args.resolve_project:
        new_meta["resolve_project"] = args.resolve_project
    else:
        new_meta.setdefault("resolve_project", None)

    if not args.dry_run:
        if not root.exists():
            root.mkdir(parents=True)
            print(f"created {root}", file=sys.stderr)
        for p in wanted:
            p.mkdir(parents=True, exist_ok=True)
        if new_meta != meta:
            meta_path.write_text(json.dumps(new_meta, indent=2) + "\n", encoding="utf-8")

    result = {
        "project": str(project),
        "dry_run": args.dry_run,
        "created": created,
        "already_there": len(existing),
        "folders": {key: str(project / rel) for key, rel in parts},
        "resolve_project": new_meta.get("resolve_project"),
        "project_json": str(meta_path),
    }
    print(json.dumps(result, indent=2))
    verb = "would create" if args.dry_run else "created"
    print(f"{verb} {len(created)} folder(s) in {project}" if created
          else f"{project} already has every folder in the layout", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
