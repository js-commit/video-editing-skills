"""Shared helpers for the home-video scripts: the project folder, its clip list, and a few
ffmpeg measurements. Not a command; the other scripts import it.

A home-video project is an ordinary project folder (settings project_layout) with a `work/`
folder that holds every decision as a file, so any session can pick up where the last stopped:

  work/project.json      name, privacy mode, who it is about, footage folders, canvas, length
  work/clips.json        clip id -> absolute path (footage is read in place, never copied)
  work/meta/<id>.json    survey numbers per clip (survey.py)
  work/survey.md         one line per clip: what the numbers say (Claude reads this)
  work/sheets/           contact sheets (privacy "frames" and "local"; in "local" only the local model reads them)
  work/descriptions.json what the local vision model saw per clip (describe.py; privacy "local", optional in "frames")
  work/picks.json        the story: sections, music, cuts (Claude or the picker agents write it)
  work/music/            beat analyses of the chosen tracks
  work/cut_vN.json       draft N's frame-exact cut list (make_draft.py)
  work/changes_vN.json   what a notes round changed, for EditReview's "What changed" list
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402

SKILLS = REPO / ".claude" / "skills"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".avi", ".mkv", ".3gp", ".webm"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
PRIVACY = ("frames", "local", "no-frames")
# frames:    Claude (and its agents) may read contact sheets of the footage.
# local:     only the vision model on this computer sees frames (describe.py); Claude works from its text.
# no-frames: nothing looks at a frame; Claude works from survey numbers and the user's notes.
SHEETS_FOR_CLAUDE = ("frames",)
SHEETS_MADE = ("frames", "local")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def die(msg: str, code: int = 1):
    log(msg)
    sys.exit(code)


# ------------------------------------------------------------------ project

def project_root(arg: str) -> Path:
    """A project from a name (under paths.projects_dir) or a path."""
    try:
        p = settings.project_dir(arg)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    if not (p / "work" / "project.json").exists():
        die(f"{p} is not a home-video project yet (no work/project.json): run init_project.py first", 2)
    return p


def work(p: Path) -> Path:
    return p / "work"


def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def save_json(path: Path, data, indent=1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def project_cfg(p: Path) -> dict:
    return load_json(work(p) / "project.json")


def canvas(cfg: dict) -> tuple:
    return int(cfg.get("width", 1920)), int(cfg.get("height", 1080))


def clips(p: Path) -> dict:
    return load_json(work(p) / "clips.json", {})


def clip_path(p: Path, clip_id: str) -> str:
    c = clips(p).get(clip_id)
    if not c:
        die(f"unknown clip id {clip_id!r}: ids are in {work(p) / 'clips.json'} (run survey.py after adding footage)")
    return c["path"]


def meta(p: Path, clip_id: str) -> dict:
    return load_json(work(p) / "meta" / f"{clip_id}.json", {})


def drafts_dir(p: Path) -> Path:
    d = p / settings.layout("drafts")
    d.mkdir(parents=True, exist_ok=True)
    return d


def finals_dir(p: Path) -> Path:
    d = p / settings.layout("finals")
    d.mkdir(parents=True, exist_ok=True)
    return d


def require_frames(p: Path, what: str) -> None:
    """Privacy guard: only in "frames" mode may images be made for Claude to look at."""
    mode = project_cfg(p).get("privacy")
    if mode == "no-frames":
        die(f"privacy mode is \"no-frames\" for this project: {what} would show Claude frames of the footage. "
            "Work from work/survey.md and the user's own notes instead (EditReview). To change the mode, ask the user "
            "and edit work/project.json.", 2)
    if mode == "local":
        die(f"privacy mode is \"local\" for this project: {what} would show Claude frames of the footage; only the "
            "vision model on this computer may look. Work from work/descriptions.md (describe.py), work/survey.md and "
            "the user's notes. To change the mode, ask the user and edit work/project.json.", 2)


# ------------------------------------------------------------------ time

NAME_TIME = [
    re.compile(r"(20\d{2})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})"),          # 20240131_142233, PXL_20240131_142233123
    re.compile(r"(20\d{2})-(\d{2})-(\d{2})[ _T-](\d{2})[.:-]?(\d{2})[.:-]?(\d{2})"),
]


def capture_time(path: Path, creation_tag: str | None) -> tuple:
    """(iso local-ish time, how it was found). The file name wins over the container tag
    (phones write the tag in UTC, the name in local time); the file date is the last resort."""
    for rx in NAME_TIME:
        m = rx.search(path.name)
        if m:
            try:
                return _dt.datetime(*map(int, m.groups())).isoformat(), "name"
            except ValueError:
                pass
    if creation_tag:
        try:
            t = _dt.datetime.fromisoformat(creation_tag.replace("Z", "+00:00"))
            return t.replace(tzinfo=None).isoformat(timespec="seconds"), "tag (UTC)"
        except ValueError:
            pass
    return _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"), "file date"


def tc(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


# ------------------------------------------------------------------ measurements

def ffmpeg_cmd(*args) -> list:
    return [media.ffmpeg(), "-hide_banner", "-nostdin", *args]


def lufs_range(path: str, start: float = 0.0, dur: float | None = None) -> float | None:
    """Integrated loudness of a stretch of a file's audio."""
    r = subprocess.run(ffmpeg_cmd("-nostats", *(["-ss", f"{start:.3f}"] if start else []),
                                  *(["-t", f"{dur:.3f}"] if dur else []), "-i", path, "-map", "0:a:0",
                                  "-af", "ebur128", "-f", "null", "-"), capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    v = float(m[-1]) if m else None
    return v if v is not None and v > -70 else None


def mean_db(path: str, start: float = 0.0, dur: float | None = None) -> float | None:
    """RMS level (dBFS) of a stretch of a file's audio; None when silent or missing."""
    r = subprocess.run(ffmpeg_cmd(*(["-ss", f"{start:.3f}"] if start else []), *(["-t", f"{dur:.3f}"] if dur else []),
                                  "-i", path, "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"),
                       capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    v = float(m.group(1)) if m else None
    return v if v is not None and v > -90 else None


def has_filter(name: str) -> bool:
    out = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return re.search(rf"\s{name}\s", out) is not None


def display_size(info: dict) -> tuple:
    w, h = info.get("width") or 0, info.get("height") or 0
    return (h, w) if (info.get("rotation") or 0) % 180 else (w, h)
