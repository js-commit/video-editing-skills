#!/usr/bin/env python3
"""List the music you can use: every track in your music folder with its length, tags and
(once analysed) tempo, so Claude can propose cues by mood.

  find_music.py [--dir DIR] [--json] [--analyze]

--dir      default settings paths.music_dir (ask the user for it once, then save it)
--analyze  also run analyze.py on tracks that have no analysis yet (tempo, entries, ending)

A track's mood comes from its tags (genre, comment, mood), its folder and file name: YouTube
Audio Library downloads are named "Title - Artist.mp3" and you can sort them into folders by
mood (calm/, upbeat/, epic/ ...), which this listing shows. Licence notes: a LICENSE.txt,
CREDITS.txt or SOURCES.tsv beside the tracks is listed too, so you can check what a published
video may use.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media, settings  # noqa: E402

AUDIO = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".aif", ".aiff"}
HERE = Path(__file__).resolve().parent


def tags(path: Path) -> dict:
    r = subprocess.run([media.ffprobe(), "-v", "error", "-show_entries", "format=duration:format_tags", "-of", "json", str(path)],
                       capture_output=True, text=True)
    try:
        f = json.loads(r.stdout or "{}").get("format", {})
    except json.JSONDecodeError:
        return {}
    t = {k.lower(): v for k, v in (f.get("tags") or {}).items()}
    return {"duration": round(float(f.get("duration") or 0), 1),
            **{k: t[k] for k in ("title", "artist", "genre", "mood", "comment", "copyright", "license") if t.get(k)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    a = ap.parse_args()
    try:
        d = Path(a.dir).expanduser() if a.dir else settings.get_path("paths.music_dir", required=True,
                                                                       hint="the folder with music you have the rights to use")
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    if not d.is_dir():
        sys.exit(f"music folder not found: {d}")
    rows = []
    for f in sorted(d.rglob("*")):
        if f.suffix.lower() not in AUDIO or f.name.startswith("."):
            continue
        row = {"path": str(f), "folder": str(f.parent.relative_to(d)), **tags(f)}
        cache = settings.cache_dir("music") / f"{f.stem}.beats.json"
        if a.analyze and not cache.exists():
            subprocess.run([sys.executable, "-B", str(HERE / "analyze.py"), str(f), "--out", str(cache)], capture_output=True)
        if cache.exists():
            try:
                an = json.loads(cache.read_text())
                row.update(tempo=an.get("tempo"), entries=an.get("entries", [])[:3], ends_at=an.get("ends_at"), lufs=an.get("lufs"))
            except (OSError, json.JSONDecodeError):
                pass
        rows.append(row)
    notes = [str(p) for p in d.rglob("*") if p.name.lower() in ("license.txt", "licence.txt", "credits.txt", "sources.tsv", "readme.txt")]
    if a.json:
        print(json.dumps({"dir": str(d), "tracks": rows, "licence_files": notes}, indent=1))
        return 0
    print(f"{len(rows)} tracks in {d}")
    for r in rows:
        m, s = divmod(int(r.get("duration", 0)), 60)
        extra = " ".join(f"{k}={r[k]}" for k in ("genre", "mood", "tempo") if r.get(k))
        print(f"  {m}:{s:02d}  {r['folder'] + '/' if r['folder'] != '.' else ''}{Path(r['path']).name}  {extra}")
    for n in notes:
        print(f"  licence / credits file: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
