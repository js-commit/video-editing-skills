#!/usr/bin/env python3
"""Hand a set of clips to BulkCut for the user to review, and read back what
they decided. BulkCut is the optional macOS triage app in apps/bulk-cut
(ready to use in apps/bulk-cut/prebuilt/). Formats: apps/bulk-cut/SPEC.md.

  bulkcut.py stage SPEC.json -o DIR [--copy] [--id ID]
      Makes the review folder DIR: one link per clip to its original (or a
      copy with --copy; links are fine, BulkCut never trims or trashes
      anything in a review folder) and DIR/bulkcut.json with the proposals.
      SPEC.json is a manifest whose "files" is a LIST of entries, each with
      "source" (absolute path) and optional "name". DIR must be new, empty,
      or a folder this command staged before (it is restaged).
  bulkcut.py read DIR
      What the user did: DIR/bulkcut-review.json (BulkCut writes it after
      every change) joined with the manifest. Exit 3 if the folder was never
      opened in BulkCut.
  bulkcut.py open DIR
      Opens DIR in BulkCut (macOS). Exit 2 with what to do if the app
      is missing. A running BulkCut saves the folder it has open first.
  bulkcut.py where
      Prints the app's path (exit 2 if it is missing).

stdout: JSON. Exit 0 ok, 2 usage / app missing, 3 not reviewed yet.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent
MANIFEST = "bulkcut.json"
STAGED_BY = "bulkcut.py stage"   # only folders carrying this mark are ever restaged (files removed)
REVIEW = "bulkcut-review.json"
VIDEO_EXT = {".mov", ".mp4", ".m4v"}
PHOTO_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".gif", ".bmp", ".webp", ".avif"}
BUILD_HINT = "BulkCut not found: apps/bulk-cut/prebuilt/BulkCut.app is missing; restore it or run apps/bulk-cut/build.sh"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    log(msg)
    sys.exit(code)


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- stage

def stage(spec: dict, out: Path, copy: bool = False, manifest_id: str | None = None) -> dict:
    """Make the review folder `out` from `spec` (see the module doc). Returns
    the summary printed by `stage`."""
    out = out.expanduser().resolve()
    if out.exists():
        leftovers = [p for p in out.iterdir() if not p.name.startswith(".")]
        old_manifest = load_json(out / MANIFEST) if (out / MANIFEST).exists() else {}
        staged_before = old_manifest.get("staged_by") == STAGED_BY
        if leftovers and not staged_before:
            die(f"{out} is not empty and was not staged by bulkcut.py: pick a new folder")
        if staged_before:          # restage: drop only the links and copies stage made, never anything else
            for name, entry in (old_manifest.get("files") or {}).items():
                p = out / Path(name).name
                if p.is_symlink() or (p.is_file() and entry.get("copied") is True):
                    p.unlink()
    out.mkdir(parents=True, exist_ok=True)

    files: dict = {}
    by_source: dict = {}
    taken: set = set()
    skipped = []
    for entry in spec.get("files", []):
        src = Path(str(entry.get("source", ""))).expanduser()
        if not src.is_absolute() or not src.is_file():
            die(f"not a file (sources must be absolute paths): {src}")
        if src.suffix.lower() not in VIDEO_EXT | PHOTO_EXT:
            skipped.append({"source": str(src), "why": "BulkCut plays .mov / .mp4 / .m4v and common photo formats only"})
            continue
        name = Path(entry.get("name") or src.name).name
        stem, ext = Path(name).stem, Path(name).suffix
        n = 2
        while name.lower() in taken:
            name = f"{stem}-{n}{ext}"
            n += 1
        taken.add(name.lower())
        dst = out / name
        if dst.is_symlink():
            dst.unlink()
        elif dst.exists():
            die(f"{dst} already exists and is not one of stage's links or copies: pick a new folder")
        if copy:
            shutil.copy2(src, dst)
        else:
            os.symlink(src, dst)
        e = {k: v for k, v in entry.items() if k not in ("name", "copied")}
        e["source"] = str(src)
        if copy:
            e["copied"] = True
        files[name] = e
        by_source[str(src)] = name
        by_source[src.name] = by_source.get(src.name, name)

    sequences = []
    for seq in spec.get("sequences", []):
        beats = []
        for b in seq.get("beats", []):
            f = str(b.get("file", ""))
            beats.append({**b, "file": by_source.get(f, by_source.get(Path(f).name, Path(f).name))})
        sequences.append({**seq, "beats": beats})

    manifest = {k: v for k, v in spec.items() if k not in ("files", "sequences")}
    manifest["schema"] = "bulkcut/1"
    manifest["staged_by"] = STAGED_BY
    manifest.setdefault("mode", "review")
    manifest["id"] = manifest_id or str(spec.get("id") or time.strftime("%Y%m%d-%H%M%S-") + f"{int(time.time() * 1000) % 1000:03d}")
    manifest["files"] = files
    if sequences:
        manifest["sequences"] = sequences
    write_json(out / MANIFEST, manifest)
    stale = out / REVIEW
    if stale.exists():
        stale.unlink()             # it described the previous staging
    return {"folder": str(out), "manifest": str(out / MANIFEST), "files": len(files), "id": manifest["id"],
            "linked": not copy, "skipped": skipped, "open": f"python3 {HERE / 'bulkcut.py'} open \"{out}\""}


# ---------------------------------------------------------------- read

def read_review(folder: Path) -> dict | None:
    """The user's review of `folder` joined with its manifest; None if BulkCut
    never opened it."""
    folder = folder.expanduser().resolve()
    mp, rp = folder / MANIFEST, folder / REVIEW
    if not mp.exists():
        die(f"no {MANIFEST} in {folder}: not a review folder")
    manifest = load_json(mp)
    if not rp.exists():
        return None
    review = load_json(rp)
    mfiles = manifest.get("files", {})
    rows = []
    for name in sorted(set(mfiles) | set(review.get("files", {}))):
        m = mfiles.get(name, {})
        r = review.get("files", {}).get(name)
        if r is None:              # not in the folder any more
            continue
        ranges = r.get("ranges", [])
        rows.append({
            "name": name,
            "source": r.get("source") or m.get("source"),
            "kind": r.get("kind"),
            "deleted": bool(r.get("deleted")),
            "kept": bool(ranges) and not r.get("deleted"),
            "ranges": ranges,
            "turns": r.get("turns", 0),
            "zoom": r.get("zoom"),
            "proposed": m.get("proposals", []),
        })
    return {"folder": str(folder), "manifest_id": manifest.get("id"), "reviewed_id": review.get("manifest_id"),
            "stale": review.get("manifest_id") != manifest.get("id"), "saved": review.get("saved"),
            "files": rows}


# ---------------------------------------------------------------- app

def find_app() -> Path | None:
    env = os.environ.get("BULKCUT_APP")
    candidates = [Path(env).expanduser()] if env else []
    candidates += [Path.home() / "Applications" / "BulkCut.app", Path("/Applications/BulkCut.app"),
                   APP_DIR / "build" / "BulkCut.app", APP_DIR / "prebuilt" / "BulkCut.app"]
    for c in candidates:
        if (c / "Contents" / "MacOS" / "BulkCut").exists():
            return c
    return None


def open_folder(folder: Path) -> dict:
    if sys.platform != "darwin":
        die("BulkCut is a macOS app; on this computer review the clips another way")
    app = find_app()
    if not app:
        die(BUILD_HINT)
    folder = folder.expanduser().resolve()
    subprocess.run(["open", "-a", str(app), str(folder)], check=True)
    return {"opened": str(folder), "app": str(app)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage", help="make a review folder")
    s.add_argument("spec", help="SPEC.json (a manifest with a list of files)")
    s.add_argument("-o", "--out", required=True, help="the review folder to make")
    s.add_argument("--copy", action="store_true", help="copy the clips instead of linking them")
    s.add_argument("--id", help="manifest id (default: a timestamp, so the proposals are staged afresh)")
    r = sub.add_parser("read", help="what the user did")
    r.add_argument("folder")
    o = sub.add_parser("open", help="open a folder in BulkCut")
    o.add_argument("folder")
    sub.add_parser("where", help="where the app is")
    a = ap.parse_args()

    if a.cmd == "stage":
        print(json.dumps(stage(load_json(Path(a.spec)), Path(a.out), a.copy, a.id), indent=2, ensure_ascii=False))
    elif a.cmd == "read":
        got = read_review(Path(a.folder))
        if got is None:
            die(f"{a.folder} has not been opened in BulkCut yet (no {REVIEW})", 3)
        print(json.dumps(got, indent=2, ensure_ascii=False))
    elif a.cmd == "open":
        print(json.dumps(open_folder(Path(a.folder))))
    elif a.cmd == "where":
        app = find_app()
        if not app:
            die(BUILD_HINT)
        print(json.dumps({"app": str(app)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
