#!/usr/bin/env python3
"""Read and update user/preferences.md, the user's standing preferences.

One `## <heading>` per skill (`## aroll-draft`, `## youtube-release`, ...)
plus `## general`. Bullets are plain Markdown list items.

    prefs.py add <heading> "<text>"       append a bullet (creates file/heading); skips exact duplicates
    prefs.py show [heading]               print the file, or one heading's bullets
    prefs.py sections                     list the headings
    prefs.py remove <heading> "<match>"   remove the bullet containing <match> (--all for several)

Options: --file <path> uses another preferences file (tests, other setups).
Exit codes: 0 ok, 2 usage, 3 ambiguous/not found (nothing changed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FILE = REPO_ROOT / "user" / "preferences.md"

HEADER = """# My preferences

Claude reads this before every editing task; what is here overrides the skills'
defaults. Claude adds a bullet when you correct something or say "from now on...".
Edit freely: one heading per skill, plus `general`.
"""


def norm_heading(h: str) -> str:
    return h.strip().lstrip("#").strip().lower()


def read_lines(path: Path) -> list:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def write_lines(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip("\n") + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def find_section(lines: list, heading: str):
    """(start, end) line indexes of a heading's body: start is the heading line,
    end is the index of the next `## ` heading (or len). None if absent."""
    want = norm_heading(heading)
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if start is not None:
                return start, i
            if norm_heading(line) == want:
                start = i
    return (start, len(lines)) if start is not None else None


def bullets(lines: list, sec) -> list:
    if not sec:
        return []
    return [(i, lines[i]) for i in range(sec[0] + 1, sec[1]) if lines[i].lstrip().startswith(("- ", "* "))]


def clean_text(text: str) -> str:
    t = " ".join(text.split())
    for p in ("- ", "* "):
        if t.startswith(p):
            t = t[len(p):]
    return t.strip()


def cmd_add(path: Path, heading: str, text: str) -> int:
    text = clean_text(text)
    if not text:
        print("nothing to add (empty text)", file=sys.stderr)
        return 2
    lines = read_lines(path) or HEADER.rstrip("\n").splitlines()
    sec = find_section(lines, heading)
    bullet = f"- {text}"
    if sec:
        for _, b in bullets(lines, sec):
            if clean_text(b).lower() == text.lower():
                print(json.dumps({"file": str(path), "heading": norm_heading(heading),
                                  "added": False, "reason": "already there", "bullet": bullet}))
                return 0
        # insert after the last non-blank line of the section
        insert_at = sec[1]
        while insert_at - 1 > sec[0] and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, bullet)
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"## {norm_heading(heading)}", bullet]
    write_lines(path, lines)
    print(json.dumps({"file": str(path), "heading": norm_heading(heading), "added": True, "bullet": bullet}))
    return 0


def cmd_show(path: Path, heading: str | None) -> int:
    lines = read_lines(path)
    if not lines:
        print(f"(no preferences file yet: {path})", file=sys.stderr)
        return 0
    if heading is None:
        print("\n".join(lines))
        return 0
    sec = find_section(lines, heading)
    if not sec:
        print(f"(no '## {norm_heading(heading)}' heading in {path})", file=sys.stderr)
        return 0
    print("\n".join(lines[sec[0]:sec[1]]).rstrip())
    return 0


def cmd_sections(path: Path) -> int:
    for line in read_lines(path):
        if line.startswith("## "):
            print(norm_heading(line))
    return 0


def cmd_remove(path: Path, heading: str, match: str, remove_all: bool) -> int:
    lines = read_lines(path)
    sec = find_section(lines, heading)
    hits = [(i, b) for i, b in bullets(lines, sec) if match.lower() in b.lower()]
    if not hits:
        print(f"no bullet under '## {norm_heading(heading)}' contains: {match}", file=sys.stderr)
        return 3
    if len(hits) > 1 and not remove_all:
        print("several bullets match; be more specific or pass --all:", file=sys.stderr)
        for _, b in hits:
            print(f"  {b}", file=sys.stderr)
        return 3
    for i, _ in reversed(hits):
        del lines[i]
    write_lines(path, lines)
    print(json.dumps({"file": str(path), "heading": norm_heading(heading),
                      "removed": [b for _, b in hits]}))
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Read and update user/preferences.md.")
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE, help="preferences file (default: user/preferences.md)")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("add", help="append a bullet under a heading")
    a.add_argument("heading")
    a.add_argument("text")
    s = sub.add_parser("show", help="print the file or one heading")
    s.add_argument("heading", nargs="?")
    sub.add_parser("sections", help="list headings")
    r = sub.add_parser("remove", help="remove a bullet")
    r.add_argument("heading")
    r.add_argument("match")
    r.add_argument("--all", action="store_true", help="remove every matching bullet")
    args = ap.parse_args(argv)
    path = args.file.expanduser()
    if args.cmd == "add":
        return cmd_add(path, args.heading, args.text)
    if args.cmd == "show":
        return cmd_show(path, args.heading)
    if args.cmd == "sections":
        return cmd_sections(path)
    if args.cmd == "remove":
        return cmd_remove(path, args.heading, args.match, args.all)
    ap.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
