#!/usr/bin/env python3
"""Download a track you have the rights to with yt-dlp (optional), and log where it came from.

  pull.py URL --name "Track title" --rights "why you may use it" [--out DIR] [--license CC-BY-4.0]

Only for music you are allowed to use: your own uploads, tracks whose licence allows it
(Creative Commons, a royalty-free library that offers downloads), or music you bought with a
download right. Downloading other people's songs from YouTube breaks YouTube's terms and,
for anything you publish, copyright. If the source has a download button (YouTube Audio
Library, Free Music Archive, Pixabay Music, incompetech, Bandcamp), use that instead: it is
simpler and the file is better.

--rights is required: one honest line ("my own song", "CC BY 4.0, credit: Name",
"YouTube Audio Library, no attribution needed"). It is written to SOURCES.tsv beside the
track with the URL and date, so a later release can check what it may use.
--out defaults to settings paths.music_dir. The track is saved as <name>.mp3 (characters a file
name cannot hold, and %, become spaces); an existing file is never overwritten.

yt-dlp is not installed by this repo. If it is missing this prints how to install it; ask the
user first.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media, settings  # noqa: E402

COLS = ("name", "url", "rights", "license", "seconds", "pulled")


def ytdlp_cmd() -> list | None:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, text=True)
    return [sys.executable, "-m", "yt_dlp"] if r.returncode == 0 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--name", required=True)
    ap.add_argument("--rights", required=True, help="why you may use this track (logged)")
    ap.add_argument("--license", default="", help="licence id if any, e.g. CC-BY-4.0")
    ap.add_argument("--out")
    a = ap.parse_args()
    if len(a.rights.strip()) < 4:
        sys.exit("--rights needs a real reason (e.g. 'CC BY 4.0, credit: Name'); without one, do not download")
    y = ytdlp_cmd()
    if not y:
        sys.exit("yt-dlp is not installed. It is optional; to install it (ask the user first):\n"
                 "  python3 -m pip install yt-dlp      (or: brew install yt-dlp)")
    try:
        out = Path(a.out).expanduser() if a.out else settings.get_path("paths.music_dir", required=True,
                                                                       hint="the folder with music you have the rights to use")
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    # a file name, not a path: no folder separators, and no % (yt-dlp reads it as a template field)
    fname = re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|%\x00-\x1f]', " ", a.name)).strip(" .-")
    if not fname:
        sys.exit("--name is empty once the characters a file name cannot hold are removed")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{fname}.mp3"
    if dest.exists():
        sys.exit(f"{dest} exists: pick another --name")
    ff = Path(media.ffmpeg()).parent
    r = subprocess.run([*y, a.url, "--no-playlist", "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "0",
                        "--ffmpeg-location", str(ff), "-o", str(out / f"{fname}.%(ext)s")], capture_output=True, text=True)
    if r.returncode or not dest.exists():
        sys.exit(f"download failed:\n{r.stderr[-800:]}")
    secs = media.duration(dest)
    tsv = out / "SOURCES.tsv"
    new = not tsv.exists()
    with open(tsv, "a", encoding="utf-8") as f:
        if new:
            f.write("\t".join(COLS) + "\n")
        row = {"name": a.name, "url": a.url, "rights": a.rights.replace("\t", " "), "license": a.license,
               "seconds": f"{secs:.1f}", "pulled": _dt.date.today().isoformat()}
        f.write("\t".join(row[c] for c in COLS) + "\n")
    print(dest)
    print(f"{dest.name}: {secs:.1f} s, logged in {tsv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
