#!/usr/bin/env python3
"""Pick up the thumbnails Ask Studio just downloaded and add them to the video's
thumbnail candidate pool.

Ask Studio's Download button saves each generated concept to ~/Downloads as
IM<image-id>.png (1365x768 long-form, 768x1365 Short). This finds the ones
that landed since --since, in download order (= concept order when they were
downloaded top to bottom), checks each is a 16:9 / 9:16 PNG under YouTube's
2 MB cap, and adds them to <dest>/thumbnail-candidates/ as studio-N-<concept>.png
via youtube-thumbnails' thumb_pool.py: N continues after any earlier round, the
pool is append-only, and each file gets an INDEX.txt line. The user picks the
final three from the pool (thumb_pool.py sheet / pick).

  collect_studio_thumbs.py --since 15m --dest <release dir> \\
      --concepts "split screen" "3 elements" "size comparison"
"""
from __future__ import annotations

import argparse
import filecmp
import re
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "youtube-thumbnails" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
import thumb_pool  # noqa: E402

DOWNLOADS = Path.home() / "Downloads"


def parse_since(s):
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"(\d+)([mh])", s)
    if m:
        return time.time() - int(m[1]) * (60 if m[2] == "m" else 3600)
    return datetime.fromisoformat(s).timestamp()


def find_downloads(folder, pattern, since, n, label, suffixes=None):
    """The n downloads matching pattern that landed since `since`, oldest first
    (= concept order when they were downloaded in order); exits listing what is
    there otherwise."""
    found = sorted((p.stat().st_mtime, p) for p in folder.glob(pattern)
                   if not suffixes or p.suffix.lower() in suffixes)
    found = [(t, p) for t, p in found if t >= since]
    if len(found) != n:
        listing = "\n".join(f"  {datetime.fromtimestamp(t):%H:%M:%S}  {p.name}" for t, p in found)
        sys.exit(f"expected {n} {label} downloads ({pattern}) since "
                 f"{datetime.fromtimestamp(since):%Y-%m-%d %H:%M:%S}, found {len(found)}:\n{listing or '  (none)'}")
    return [p for _, p in found]


def retire_download(src, copy):
    """Delete a download once its copy verifies byte for byte: a move, not a copy,
    so nothing strays in the downloads folder."""
    if filecmp.cmp(src, copy, shallow=False):
        src.unlink()
    else:
        print(f"  WARN {copy.name} differs from {src.name}; download left in place")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True,
                    help="only downloads newer than this: ISO time, epoch seconds, or '15m' / '1h' ago")
    ap.add_argument("--dest", required=True, type=Path, help="where the pool lives (thumb_pool.py info <video> -> dest)")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--concepts", nargs="*", default=[], help="Ask Studio's concept names, in order")
    ap.add_argument("--downloads", type=Path, default=DOWNLOADS)
    a = ap.parse_args()

    found = find_downloads(a.downloads, "IM*.png", parse_since(a.since), a.count, "Ask Studio")

    shapes = set()
    for p in found:
        wh = png_size(p)
        if not wh:
            sys.exit(f"{p.name}: not a PNG")
        w, h = wh
        if abs(w / h - 16 / 9) > 0.01 and abs(w / h - 9 / 16) > 0.01:
            sys.exit(f"{p.name}: {w}x{h} is neither 16:9 nor 9:16")
        shapes.add("landscape" if w > h else "short")
    if len(shapes) > 1:
        sys.exit("mixed landscape and vertical downloads - two videos' concepts got mixed up")

    concepts = [a.concepts[i] if i < len(a.concepts) else "concept" for i in range(len(found))]
    added = thumb_pool.add(a.dest, "studio", found, concepts, note="Ask Studio download")
    for src, dst in zip(found, added):
        wh = png_size(dst) if dst.suffix.lower() == ".png" else None
        size = f"{wh[0]}x{wh[1]}" if wh else "fitted"
        print(f"{dst.name}  {size}  {dst.stat().st_size / 1e6:.2f} MB  <- {src.name}")
        if wh:   # an untouched copy: the download can go
            retire_download(src, dst)
        else:    # thumb_pool had to fit it (re-encoded): keep the original beside the pool
            keep = thumb_pool.pool_dir(a.dest) / "originals" / src.name
            keep.parent.mkdir(parents=True, exist_ok=True)
            src.replace(keep) if src.stat().st_dev == keep.parent.stat().st_dev else (keep.write_bytes(src.read_bytes()), src.unlink())


if __name__ == "__main__":
    main()
