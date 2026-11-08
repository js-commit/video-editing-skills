#!/usr/bin/env python3
"""Shared helpers for the footage-triage scripts: media types, sidecars,
capture times, contact sheets and where each destination lives."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".mxf", ".webm", ".3gp", ".insv", ".360"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".dng", ".webp", ".gif",
             ".cr2", ".cr3", ".arw", ".nef", ".raf", ".orf", ".rw2"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".ogg"}
DESTINATIONS = ("project", "home-videos", "broll-library", "trash")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def kind_of(p) -> str | None:
    ext = Path(p).suffix.lower()
    return "video" if ext in VIDEO_EXT else "photo" if ext in PHOTO_EXT else "audio" if ext in AUDIO_EXT else None


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s or "untitled"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1000.0
    return f"{n:.1f} TB"


# ---- sidecars travel with their clip --------------------------------------

def sidecars_of(src_dir: Path, media_names: list) -> dict:
    """{media name: [sidecar names]}: every non-media file in the same folder
    whose name starts with the clip's stem followed by anything but a digit
    (CLIP_0012.transcript.json, CLIP_0012_audio.wav, C0012M01.XML, C0012.LRF).
    Longest stem first, so CLIP_0012's sidecars never attach to CLIP_001."""
    try:
        others = [f.name for f in Path(src_dir).iterdir() if f.is_file() and not kind_of(f)]
    except OSError:
        others = []
    out = {m: [] for m in media_names}
    taken = set()
    for m in sorted(media_names, key=lambda n: -len(Path(n).stem)):
        stem = Path(m).stem
        for o in others:
            if o not in taken and o.startswith(stem) and len(o) > len(stem) and not o[len(stem)].isdigit():
                out[m].append(o)
                taken.add(o)
    return out


# ---- capture time ----------------------------------------------------------

_NAME_TIME = [
    re.compile(r"(20\d{2})(\d{2})(\d{2})[_\-T ]?(\d{2})(\d{2})(\d{2})"),          # 20250314_153012
    re.compile(r"(20\d{2})-(\d{2})-(\d{2})[ _T](\d{2})[.\-:](\d{2})[.\-:](\d{2})"),  # 2025-03-14 15.30.12
]


def time_from_name(name: str) -> _dt.datetime | None:
    for rx in _NAME_TIME:
        m = rx.search(name)
        if m:
            try:
                return _dt.datetime(*(int(x) for x in m.groups()))
            except ValueError:
                pass
    return None


def parse_exif_time(v) -> _dt.datetime | None:
    if not v or not isinstance(v, str) or v.startswith("0000"):
        return None
    m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", v)
    if not m:
        return None
    try:
        return _dt.datetime(*(int(x) for x in m.groups()))
    except ValueError:
        return None


def parse_iso_utc(v) -> _dt.datetime | None:
    """ffprobe creation_time (UTC) -> local naive time."""
    if not v:
        return None
    try:
        t = _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return t
    if t.year < 2000:
        return None
    return t.astimezone().replace(tzinfo=None)


# ---- probing ---------------------------------------------------------------

def ffprobe_json(path) -> dict:
    r = subprocess.run([media.ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                        str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def exiftool_batch(paths: list) -> dict:
    """{path: tags} from one exiftool run, or {} when exiftool is not installed."""
    exe = media.which("exiftool")
    if not exe or not paths:
        return {}
    out = {}
    for i in range(0, len(paths), 200):
        chunk = [str(p) for p in paths[i:i + 200]]
        r = subprocess.run([exe, "-json", "-api", "QuickTimeUTC=1", "-api", "largefilesupport=1",
                            "-DateTimeOriginal", "-CreateDate", "-MediaCreateDate", "-Make", "-Model",
                            "-AndroidModel", "-AndroidManufacturer", "-Duration#", "-ImageWidth", "-ImageHeight"]
                           + chunk, capture_output=True, text=True)
        try:
            for rec in json.loads(r.stdout or "[]"):
                out[rec.get("SourceFile")] = rec
        except json.JSONDecodeError:
            pass
    return out


# ---- contact sheets --------------------------------------------------------

def _has_drawtext() -> bool:
    if not hasattr(_has_drawtext, "v"):
        out = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        _has_drawtext.v = " drawtext " in out
    return _has_drawtext.v


def triage_layout(duration: float) -> tuple:
    """(frames, columns) by clip length: 4 tiles for a few seconds, up to 12."""
    if duration < 10:
        return 4, 4
    if duration < 60:
        return 6, 3
    if duration < 300:
        return 9, 3
    return 12, 4


def make_sheet(video, out_path, duration: float, tile_w: int = 400) -> list | None:
    """A JPEG grid of evenly spaced frames with the time burned in when this
    ffmpeg has drawtext. Returns the tile times, or None on failure."""
    out_path = Path(out_path)
    if not duration or duration <= 0:
        return None
    frames, cols = triage_layout(duration)
    rows = -(-frames // cols)
    step = duration / frames
    times = [round(step * i, 2) for i in range(frames)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vf = f"fps={frames}/{duration:.4f},scale={tile_w}:-2"
    tries = []
    if _has_drawtext():
        tries.append(vf + ",drawtext=text='%{pts\\:hms}':x=5:y=5:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.55")
    tries.append(vf)
    for filt in tries:
        cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", str(video), "-an",
               "-vf", f"{filt},tile={cols}x{rows}", "-frames:v", "1", "-q:v", "5", str(out_path)]
        r = media.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return times
    return None


def make_photo_thumb(photo, out_path, width: int = 800) -> bool:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", str(photo),
                        "-vf", f"scale='min({width},iw)':-2", "-frames:v", "1", "-q:v", "5", str(out_path)],
                       capture_output=True, text=True)
    if r.returncode == 0 and out_path.exists():
        return True
    if media.which("sips"):        # macOS: HEIC and camera raw files ffmpeg cannot read
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(width), str(photo), "--out", str(out_path)],
                           capture_output=True, text=True)
        return r.returncode == 0 and out_path.exists()
    return False


# ---- destinations ----------------------------------------------------------

def trash_dir(input_dir: Path) -> Path:
    t = settings.get_path("triage.trash_dir")
    return t if t else Path(input_dir) / "_trash"


def dest_roots() -> dict:
    return {"projects_dir": settings.get_path("paths.projects_dir"),
            "home_videos_dir": settings.get_path("paths.home_videos_dir"),
            "broll_library_dir": settings.get_path("paths.broll_library_dir")}


SETTING_FOR = {"project": "paths.projects_dir", "home-videos": "paths.home_videos_dir",
               "broll-library": "paths.broll_library_dir"}


def dest_dir_for(destination: str, *, project: str | None, folder_name: str, input_dir: Path,
                 first_date: str | None) -> tuple:
    """(dest folder, problem) for a destination kind. problem is a short text
    when the destination cannot be resolved (setting unset, no project name)."""
    folder = slugify(folder_name) if folder_name else "footage"
    roots = dest_roots()
    if destination == "trash":
        return trash_dir(input_dir) / folder, None
    if destination == "project":
        if not roots["projects_dir"]:
            return None, "settings paths.projects_dir is unset (ask the user where projects live)"
        if not project:
            return None, "no project named"
        return roots["projects_dir"] / project / settings.layout("footage") / folder, None
    if destination == "home-videos":
        if not roots["home_videos_dir"]:
            return None, "settings paths.home_videos_dir is unset (ask the user where home videos go)"
        name = folder if not first_date or folder.startswith(first_date) else f"{first_date}-{folder}"
        return roots["home_videos_dir"] / name, None
    if destination == "broll-library":
        if not roots["broll_library_dir"]:
            return None, "settings paths.broll_library_dir is unset (ask the user, or use the broll-library skill)"
        return roots["broll_library_dir"] / "footage" / folder, None
    return None, f"unknown destination {destination!r}"
