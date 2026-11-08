#!/usr/bin/env python3
"""Backups of repo files before the customize skill edits them, and undo.

    backup.py save <path>... [--label L]   copy files/folders into user/backups/<id>/ (paths that
                                           do not exist yet are recorded, so undo removes them)
    backup.py list                         backups, newest first
    backup.py diff <id|latest>             what changed since the backup (unified diff)
    backup.py restore <id|latest> [--yes]  dry run by default; --yes restores (and first backs up
                                           the current state, so an undo can itself be undone)

Options: --repo <dir> (default: this repo), --root <dir> (default: <repo>/user/backups).
Prints JSON on stdout. Exit codes: 0 ok, 2 usage, 3 nothing to do / not found.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import filecmp
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def rel_inside(repo: Path, p: Path) -> str:
    p = p.expanduser().resolve()
    try:
        return p.relative_to(repo).as_posix()
    except ValueError:
        sys.exit(f"{p} is outside the repo ({repo}); only files in the repo are backed up.")


def new_id(root: Path, label: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label).strip("-")[:40]
    base = f"{stamp}-{safe}" if safe else stamp
    bid, n = base, 1
    while (root / bid).exists():
        n += 1
        bid = f"{base}-{n}"
    return bid


def save(repo: Path, root: Path, paths: list, label: str) -> dict:
    bid = new_id(root, label)
    dest = root / bid
    files = dest / "files"
    entries = []
    for raw in paths:
        rel = rel_inside(repo, Path(raw) if Path(raw).is_absolute() else repo / raw)
        src = repo / rel
        entry = {"path": rel, "existed": src.exists(), "kind": "dir" if src.is_dir() else "file"}
        if src.is_dir():
            shutil.copytree(src, files / rel, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif src.is_file():
            (files / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, files / rel)
        entries.append(entry)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"id": bid, "label": label, "created": dt.datetime.now().isoformat(timespec="seconds"),
                "entries": entries}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(root: Path, bid: str) -> dict:
    if bid == "latest":
        ids = sorted(p.name for p in root.iterdir() if (p / "manifest.json").is_file()) if root.is_dir() else []
        if not ids:
            print(json.dumps({"error": "no backups yet", "root": str(root)}))
            sys.exit(3)
        bid = ids[-1]
    mf = root / bid / "manifest.json"
    if not mf.is_file():
        print(json.dumps({"error": f"no backup named {bid}", "root": str(root)}))
        sys.exit(3)
    return json.loads(mf.read_text(encoding="utf-8"))


def walk_files(base: Path) -> set:
    return {p.relative_to(base).as_posix() for p in base.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


def plan(repo: Path, root: Path, m: dict) -> list:
    """What restoring would do, one action per file."""
    actions = []
    files = root / m["id"] / "files"
    for e in m["entries"]:
        cur = repo / e["path"]
        if not e["existed"]:
            if cur.exists():
                actions.append({"action": "delete", "path": e["path"], "why": "did not exist before"})
            continue
        if e["kind"] == "dir":
            saved, now = walk_files(files / e["path"]), walk_files(cur) if cur.is_dir() else set()
            for f in sorted(saved):
                p = f"{e['path']}/{f}"
                if f not in now:
                    actions.append({"action": "restore", "path": p, "why": "missing now"})
                elif not filecmp.cmp(files / p, repo / p, shallow=False):
                    actions.append({"action": "restore", "path": p, "why": "changed"})
            for f in sorted(now - saved):
                actions.append({"action": "delete", "path": f"{e['path']}/{f}", "why": "added since the backup"})
        else:
            if not cur.exists():
                actions.append({"action": "restore", "path": e["path"], "why": "missing now"})
            elif not filecmp.cmp(files / e["path"], cur, shallow=False):
                actions.append({"action": "restore", "path": e["path"], "why": "changed"})
    return actions


def diff(repo: Path, root: Path, m: dict) -> str:
    out = []
    files = root / m["id"] / "files"
    for a in plan(repo, root, m):
        old = files / a["path"]
        new = repo / a["path"]
        if new.is_dir():
            out.append(f"Only now: {a['path']}/ (a folder; undo removes it)\n")
            continue
        try:
            ol = old.read_text(encoding="utf-8").splitlines(True) if old.is_file() else []
            nl = new.read_text(encoding="utf-8").splitlines(True) if new.is_file() else []
        except UnicodeDecodeError:
            out.append(f"Binary file {a['path']} differs\n")
            continue
        out += difflib.unified_diff(ol, nl, f"backup/{a['path']}", f"now/{a['path']}")
    return "".join(out)


def restore(repo: Path, root: Path, m: dict, actions: list) -> None:
    files = root / m["id"] / "files"
    for a in actions:
        target = repo / a["path"]
        if a["action"] == "restore":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(files / a["path"], target)
        elif a["action"] == "delete":
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
    # tidy folders the restore emptied that did not exist before
    for e in m["entries"]:
        p = repo / e["path"]
        if not e["existed"] and p.is_dir() and not any(p.rglob("*")):
            p.rmdir()


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Back up repo files before editing them; undo.")
    ap.add_argument("--repo", type=Path, default=REPO_ROOT)
    ap.add_argument("--root", type=Path, default=None, help="backup folder (default <repo>/user/backups)")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("save")
    s.add_argument("paths", nargs="+")
    s.add_argument("--label", default="")
    sub.add_parser("list")
    d = sub.add_parser("diff")
    d.add_argument("id")
    r = sub.add_parser("restore")
    r.add_argument("id")
    r.add_argument("--yes", action="store_true", help="really restore (default: dry run)")
    args = ap.parse_args(argv)
    repo = args.repo.expanduser().resolve()
    root = (args.root or repo / "user" / "backups").expanduser().resolve()

    if args.cmd == "save":
        m = save(repo, root, args.paths, args.label)
        print(json.dumps({"saved": m["id"], "folder": str(root / m["id"]), "entries": m["entries"]}, indent=2))
        return 0
    if args.cmd == "list":
        out = []
        if root.is_dir():
            for p in sorted(root.iterdir(), reverse=True):
                mf = p / "manifest.json"
                if mf.is_file():
                    m = json.loads(mf.read_text(encoding="utf-8"))
                    out.append({"id": m["id"], "label": m.get("label", ""), "created": m.get("created"),
                                "paths": [e["path"] for e in m["entries"]]})
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "diff":
        m = load_manifest(root, args.id)
        text = diff(repo, root, m)
        print(text if text else f"(no changes since backup {m['id']})")
        return 0
    if args.cmd == "restore":
        m = load_manifest(root, args.id)
        actions = plan(repo, root, m)
        if not actions:
            print(json.dumps({"backup": m["id"], "actions": [], "note": "nothing to restore: files match the backup"}))
            return 3
        if not args.yes:
            print(json.dumps({"backup": m["id"], "dry_run": True, "actions": actions}, indent=2))
            return 0
        safety = save(repo, root, [e["path"] for e in m["entries"]], f"before-undo-{m['id']}"[:60])
        restore(repo, root, m, actions)
        print(json.dumps({"backup": m["id"], "restored": True, "actions": actions,
                          "undo_of_undo": safety["id"]}, indent=2))
        return 0
    ap.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
