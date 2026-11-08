"""Shared helpers for the talking-head-ffmpeg scripts: vidkit import, transcript words, project folders.

Not a command. Every script here does `import _common as C` first.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "tools"))

from vidkit import media, settings  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".m4v", ".mkv", ".avi", ".webm"}


def ffmpeg() -> str:
    return media.ffmpeg()


def ffprobe() -> str:
    return media.ffprobe()


def transcript_path(src: str | Path) -> Path:
    side = Path(os.path.splitext(str(src))[0] + ".transcript.json")
    if not side.exists():
        found = _find_sidecar(src)
        if found:
            return Path(found)
    return side


def _find_sidecar(media):
    """Next to the media, else the cache copy tools/transcribe.py makes for read-only folders."""
    try:
        from vidkit.transcript import find_sidecar
        return find_sidecar(media)
    except Exception:
        return None


def load_transcript(src: str | Path):
    """The `<stem>.transcript.json` sidecar of a media file (dict), or None when there is none."""
    side = transcript_path(src)
    if not side.exists():
        return None
    try:
        from vidkit.transcript import load_transcript as _load  # the shared sidecar reader
        return _load(side)
    except ImportError:
        with open(side, encoding="utf-8") as f:
            return json.load(f)


def words_of(src: str | Path):
    """[{start, end, word}] of a media file's transcript sidecar, or None."""
    t = load_transcript(src)
    if t is None:
        return None
    return [w for s in t.get("segments", []) for w in s.get("words", []) if "start" in w and "end" in w]


def project_root(path: str | Path) -> Path:
    """The project folder holding `path` (settings.find_project_root), else the file's own folder."""
    p = Path(path).expanduser().resolve()
    root = settings.find_project_root(p)
    return root if root else (p if p.is_dir() else p.parent)


def work_dir(project: Path) -> Path:
    """<project>/<work>/talking-head: recipes, sheets, segment cache."""
    d = project / settings.layout("work") / "talking-head"
    d.mkdir(parents=True, exist_ok=True)
    return d


def finals_dir(project: Path) -> Path:
    d = project / settings.layout("finals")
    d.mkdir(parents=True, exist_ok=True)
    return d


def tc(t: float) -> str:
    """m:ss.ss"""
    return f"{int(t // 60)}:{t % 60:05.2f}"


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data, indent=1):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
