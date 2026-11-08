#!/usr/bin/env python3
"""Index a folder of raw b-roll IN PLACE: nothing is copied, cut or moved.

Each video is split into shots (where the picture changes a lot, and long
takes every --max-length seconds); each shot becomes a catalog entry that
points at a time range of the original file, with a contact sheet. Then
describe.py gives every shot a description so search can find it.

The folder can be anywhere (a local drive, the NAS, inside the library's
footage/ folder). If it later moves, run this again on the new location and
`catalog.py check --apply` to drop the old entries.

Usage:
  index_folder.py FOLDER [--name LABEL] [--max-length 30] [--min-length 1.5] [--dry-run]
Options:
  --name LABEL          what search shows as source_project (default: the folder name)
  --scene 0.35          scene-change sensitivity (0-1, lower = more cuts)
  --include-aroll       also index sub-folders named a-roll / aroll (skipped by default:
                        talking-head takes do not belong in a b-roll library)
  --force               re-index files that are already in the catalog

stdout: a JSON summary. Exit 0 ok, 1 error, 4 a setting is unset.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from vidkit import media  # noqa: E402

AROLL_DIR = re.compile(r"a[-_ ]?roll", re.I)


def scene_cuts(path: Path, threshold: float) -> list:
    """Times (s) where the picture changes, from one low-resolution decode."""
    cmd = [media.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-an",
           "-vf", f"fps=4,scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    r = media.run(cmd, capture_output=True, text=True)
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr or "")]


def shots(duration: float, cuts: list, min_len: float, max_len: float) -> list:
    bounds = [0.0] + [t for t in cuts if 0 < t < duration] + [duration]
    segs = [[a, b] for a, b in zip(bounds, bounds[1:]) if b > a]
    merged = []
    for s in segs:                        # fold slivers into the previous shot
        if merged and (s[1] - s[0] < min_len or merged[-1][1] - merged[-1][0] < min_len):
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    out = []
    for a, b in merged:                   # split long takes evenly
        n = max(1, int(-(-(b - a) // max_len)))
        step = (b - a) / n
        out += [(round(a + i * step, 2), round(a + (i + 1) * step, 2)) for i in range(n)]
    return [s for s in out if s[1] - s[0] >= min(min_len, duration)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--name")
    ap.add_argument("--max-length", type=float, default=30.0)
    ap.add_argument("--min-length", type=float, default=1.5)
    ap.add_argument("--scene", type=float, default=0.35)
    ap.add_argument("--include-aroll", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    folder = Path(a.folder).expanduser().resolve()
    if not folder.is_dir():
        sys.exit(f"not a folder: {folder}")
    label = C.slugify(a.name or folder.name)
    files, skipped_aroll = [], 0
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or not C.is_video(p) or any(part.startswith((".", "_")) for part in p.relative_to(folder).parts):
            continue
        if not a.include_aroll and any(AROLL_DIR.search(part) for part in p.relative_to(folder).parts[:-1]):
            skipped_aroll += 1
            continue
        files.append(p)

    root = None if a.dry_run else C.root_or_exit(create=True)
    known = set()
    if root and not a.force:
        known = {str(C.to_abs(root, c["source_file"])) for c in C.load_catalog(root)["clips"]}

    plan = []
    for f in files:
        if str(f) in known:
            continue
        info = C.safe_probe(f)
        if not info or not info.get("has_video") or not info.get("duration"):
            C.log(f"  skipped (unreadable): {f.name}")
            continue
        cuts = scene_cuts(f, a.scene) if info["duration"] > a.min_length * 2 else []
        for s, e in shots(info["duration"], cuts, a.min_length, a.max_length):
            plan.append((f, s, e, info))
        C.log(f"  {f.name}: {info['duration']:.1f}s -> {sum(1 for p in plan if p[0] == f)} shots")

    summary = {"folder": str(folder), "name": label, "files": len(files), "already_indexed": len(
        [f for f in files if str(f) in known]), "skipped_aroll_files": skipped_aroll, "shots": len(plan)}
    if a.dry_run:
        summary["dry_run"] = True
        summary["plan"] = [{"file": str(f), "start": s, "end": e} for f, s, e, _ in plan]
        print(json.dumps(summary, indent=2))
        return 0

    removed = set()
    rlog = C.catalog_dir(root) / "removed.jsonl"
    if rlog.exists():                      # shots taken out of the library stay out (even with --force)
        removed = {json.loads(line).get("id") for line in rlog.read_text(encoding="utf-8").splitlines() if line.strip()}
    with C.Lock(root, f"index_folder {label}"):
        data = C.load_catalog(root)
        added = 0
        for f, s, e, info in plan:
            rec = C.new_record(root, path=f, start=s, end=e, in_place=True, source_project=label,
                               source_file=f, source_in=s, source_out=e, origin="folder", info=info)
            if rec["id"] in removed:
                continue
            sheet = C.catalog_dir(root) / "sheets" / f"{rec['id']}.jpg"
            if C.make_sheet(f, sheet, s, e):
                rec["sheet"] = C.to_stored(root, sheet)
            added += C.upsert(data, rec)
        C.save_catalog(root, data)
    summary.update({"added": added, "next": "describe the new shots: describe.py briefs --only-missing"})
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
