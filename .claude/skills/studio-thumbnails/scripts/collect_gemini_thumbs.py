#!/usr/bin/env python3
"""Pick up the thumbnails Gemini (gemini.google.com) just downloaded and add
them to the video's thumbnail candidate pool as G-ids.

Gemini's "Download full size image" saves each image to ~/Downloads as
Gemini_Generated_Image_<id>.jpeg (2752x1536 for 16:9, about 2.2 MB: over
YouTube's 2 MB cap). This takes the ones that landed since --since, in download
order (= concept order when each download landed before the next was clicked),
adds them to <dest>/thumbnail-candidates/ as gemini-N-<concept>.jpg through
youtube-thumbnails' thumb_pool.py (which centre-crops to 1280x720, or 1080x1920
when vertical, and re-encodes under 2 MB; append-only, INDEX.txt line each),
then moves each full-size original into --work as gemini-N-<concept>-full.jpeg.

  collect_gemini_thumbs.py --since 1793247240 --dest <release dir> \\
      --work <project>/<work>/thumbnails/<round>/gemini --concepts "SIDE BY SIDE" "FIXED IT"
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from collect_studio_thumbs import DOWNLOADS, find_downloads, parse_since, retire_download, thumb_pool


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True,
                    help="only downloads newer than this: ISO time, epoch seconds, or '15m' / '1h' ago")
    ap.add_argument("--dest", required=True, type=Path, help="where the pool lives (thumb_pool.py info <video> -> dest)")
    ap.add_argument("--work", required=True, type=Path,
                    help="where the full-size originals go (<project>/work/thumbnails/<round>/gemini)")
    ap.add_argument("--concepts", nargs="+", required=True, help="one name per download, in download order")
    ap.add_argument("--downloads", type=Path, default=DOWNLOADS)
    a = ap.parse_args()

    found = find_downloads(a.downloads, "Gemini_Generated_Image_*", parse_since(a.since), len(a.concepts),
                           "Gemini", suffixes=(".jpeg", ".jpg", ".png"))
    added = thumb_pool.add(a.dest, "gemini", found, a.concepts, note=f"Gemini download, original in {a.work}")

    a.work.mkdir(parents=True, exist_ok=True)
    for src, dst in zip(found, added):
        full = a.work / f"{dst.stem}-full{src.suffix.lower()}"
        shutil.copy2(src, full)      # the downloads folder and the project may be on different volumes
        retire_download(src, full)
        w, h = thumb_pool.tk.image_size(dst)
        print(f"{dst.name}  {w}x{h}  {dst.stat().st_size / 1e6:.2f} MB  <- {src.name}")


if __name__ == "__main__":
    main()
