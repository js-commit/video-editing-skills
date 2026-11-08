#!/usr/bin/env python3
"""Shared helpers for the broll-library scripts: where the library lives, the
one-writer lock, the catalog file, contact sheets and clip extraction.

Library layout (root = settings paths.broll_library_dir):

    <library>/
      clips/<source>/<source>_<camera file>_<in-point>s.mp4
                                        clips cut out of finished projects / salvage
      footage/<name>/...                raw b-roll folders moved in whole (indexed in place)
      catalog/catalog.json              every clip: path, range, description, tags...
      catalog/sheets/<clip id>.jpg      one contact sheet per clip
      catalog/.lock/                    held by whichever script is writing
      _trash/                           clips removed from the library (you empty it)

Paths inside the library are stored relative to it, so the same library works
when a NAS is mounted at a different place on another computer. Footage indexed
in place outside the library keeps its absolute path.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".mxf", ".webm", ".3gp", ".insv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".dng", ".webp", ".gif", ".bmp"}
SCHEMA = 1
LOCK_STALE_S = 6 * 3600


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s or "untitled"


def is_video(p) -> bool:
    return Path(p).suffix.lower() in VIDEO_EXT


# ---- where the library is --------------------------------------------------

class LibraryUnavailable(Exception):
    pass


def library_root(required: bool = True, create: bool = False) -> Path | None:
    """The library folder. Unset -> SettingMissing when required (exit 4), else
    None. Set but unreachable -> LibraryUnavailable with what to do."""
    raw = settings.get("paths.broll_library_dir", required=required,
                       hint="a folder for your b-roll library, e.g. ~/Movies/B-roll Library on a Mac")
    if not raw or not str(raw).strip():
        if required:
            raise settings.SettingMissing("paths.broll_library_dir", "a folder for your b-roll library")
        return None
    root = Path(os.path.expandvars(str(raw))).expanduser()
    if root.is_dir():
        return root
    on_nas = bool(settings.get("nas.enabled", default=False))
    mount = settings.get_path("nas.mount_path")
    if on_nas and (mount is None or str(root).startswith(str(mount))):
        raise LibraryUnavailable(
            f"The b-roll library {root} is not reachable. It is on your NAS: mount the NAS "
            f"(macOS Finder: Go > Connect to Server, Cmd+K) and run this again.")
    if create and root.parent.is_dir():
        root.mkdir()
        log(f"created the b-roll library folder {root}")
        return root
    raise LibraryUnavailable(
        f"The b-roll library {root} does not exist (unplugged drive?). Connect it, or change "
        f"the location with: python3 {REPO / 'tools/vidkit/settings.py'} set paths.broll_library_dir <folder>")


def root_or_exit(create: bool = False) -> Path:
    try:
        return library_root(required=True, create=create)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    except LibraryUnavailable as e:
        sys.exit(str(e))


def catalog_dir(root: Path) -> Path:
    d = root / "catalog"
    (d / "sheets").mkdir(parents=True, exist_ok=True)
    return d


def to_stored(root: Path, path) -> str:
    """Relative to the library when inside it, else absolute."""
    p = Path(path).expanduser().resolve()
    try:
        return p.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def to_abs(root: Path, stored: str) -> Path:
    p = Path(stored)
    return p if p.is_absolute() else root / p


def free_path(p: Path) -> Path:
    """p, or p with -2, -3 ... before the extension when a file is already there: a move
    into _trash/ never replaces an earlier trashed clip."""
    q, n = p, 2
    while q.exists():
        q, n = p.with_name(f"{p.stem}-{n}{p.suffix}"), n + 1
    return q


# ---- one writer at a time --------------------------------------------------

class Lock:
    """A lock folder inside the catalog (mkdir is atomic, also on network shares).
    A second writer exits naming the holder. A lock older than six hours, or one
    left by a dead process on this computer, is taken over."""

    def __init__(self, root: Path, what: str):
        self.dir = catalog_dir(root) / ".lock"
        self.what = what

    def _stale(self) -> bool:
        info_p = self.dir / "holder.json"
        try:
            info = json.loads(info_p.read_text())
        except Exception:
            return time.time() - self.dir.stat().st_mtime > 60
        if time.time() - info.get("t", 0) > LOCK_STALE_S:
            return True
        if info.get("host") == socket.gethostname():
            try:
                os.kill(int(info.get("pid", 0)), 0)
            except (ProcessLookupError, ValueError):
                return True
            except PermissionError:
                return False
        return False

    def __enter__(self):
        for _ in range(2):
            try:
                self.dir.mkdir()
                (self.dir / "holder.json").write_text(json.dumps(
                    {"host": socket.gethostname(), "pid": os.getpid(), "t": time.time(), "what": self.what}))
                return self
            except FileExistsError:
                if self._stale():
                    shutil.rmtree(self.dir, ignore_errors=True)
                    continue
                try:
                    holder = json.loads((self.dir / "holder.json").read_text())
                except Exception:
                    holder = {}
                sys.exit(f"The library is busy: {holder.get('what', 'another run')} (pid {holder.get('pid', '?')}) "
                         f"holds {self.dir}. Wait for it to finish. If you are sure it died, delete that folder.")
        sys.exit(f"could not take the library lock {self.dir}")

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


# ---- the catalog -----------------------------------------------------------

def catalog_path(root: Path) -> Path:
    return catalog_dir(root) / "catalog.json"


def load_catalog(root: Path) -> dict:
    p = catalog_path(root)
    if not p.exists():
        return {"schema": SCHEMA, "clips": []}
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("clips", [])
    return data


def save_catalog(root: Path, data: dict) -> None:
    """Atomic write (call it while holding the Lock)."""
    p = catalog_path(root)
    data["schema"] = SCHEMA
    data["updated"] = now_iso()
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".catalog.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def clip_id(source_file, start: float, end: float) -> str:
    key = f"{Path(source_file).name}|{Path(source_file).stat().st_size if Path(source_file).exists() else 0}|{start:.1f}|{end:.1f}"
    return "c" + hashlib.sha1(key.encode()).hexdigest()[:10]


def upsert(data: dict, rec: dict) -> bool:
    """Insert or update by id; keeps an existing description/tags/verdict. True if new."""
    for i, old in enumerate(data["clips"]):
        if old["id"] == rec["id"]:
            merged = dict(rec)
            for k in ("description", "tags", "described_by", "verdict", "verdict_reason"):
                if old.get(k) and not rec.get(k):
                    merged[k] = old[k]
            data["clips"][i] = merged
            return False
    data["clips"].append(rec)
    return True


def new_record(root: Path, *, path, start, end, in_place, source_project, source_file,
               source_in, source_out, origin, info=None, description="", tags=None,
               described_by="", speed=1.0) -> dict:
    info = info or {}
    return {
        "id": clip_id(source_file, source_in, source_out),
        "path": to_stored(root, path),
        "start": round(float(start), 3),
        "end": round(float(end), 3),
        "in_place": bool(in_place),
        "source_project": source_project,
        "source_file": to_stored(root, source_file),
        "source_in": round(float(source_in), 3),
        "source_out": round(float(source_out), 3),
        "speed": round(float(speed), 4),
        "origin": origin,
        "width": info.get("width"),
        "height": info.get("height"),
        "fps": info.get("fps_float"),
        "description": description,
        "tags": list(tags or []),
        "described_by": described_by,
        "verdict": None,
        "verdict_reason": "",
        "sheet": "",
        "added": now_iso(),
    }


# ---- probing without exiting ----------------------------------------------

def safe_probe(path) -> dict | None:
    """media.probe, but None instead of exiting on an unreadable file."""
    try:
        return media.probe(path)
    except SystemExit:
        return None


# ---- contact sheets --------------------------------------------------------

def _has_drawtext() -> bool:
    if not hasattr(_has_drawtext, "v"):
        out = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        _has_drawtext.v = " drawtext " in out
    return _has_drawtext.v


def sheet_layout(duration: float) -> tuple:
    """(frames, columns): 4 for short clips up to 12 for long ones."""
    if duration <= 4:
        return 4, 4
    if duration <= 12:
        return 8, 4
    return 12, 4


def make_sheet(video, out_path, start: float = 0.0, end: float | None = None,
               frames: int | None = None, cols: int = 4, tile_w: int = 480,
               stamps: bool = True, force: bool = False) -> list | None:
    """One JPEG grid of evenly spaced frames from start..end (seconds). Tiles
    read left to right, top to bottom. Returns the tile times (seconds into the
    source file), or None on failure. Timestamps are burned in when this ffmpeg
    has drawtext; the times are returned either way."""
    out_path = Path(out_path)
    if end is None:
        info = safe_probe(video)
        end = (info or {}).get("duration") or 0
    dur = max(0.0, float(end) - float(start))
    if dur <= 0:
        return None
    if frames is None:
        frames, cols = sheet_layout(dur)
    cols = min(cols, frames)
    rows = -(-frames // cols)
    step = dur / frames
    times = [round(start + step * i, 2) for i in range(frames)]   # what the fps filter samples
    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        return times
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vf = f"fps={frames}/{dur:.4f},scale={tile_w}:-2"
    if stamps and _has_drawtext():
        vf_s = vf + (f",drawtext=text='%{{pts\\:hms\\:{start:.3f}}}':x=6:y=6:fontsize=20:"
                     f"fontcolor=white:box=1:boxcolor=black@0.55")
    else:
        vf_s = None
    for filt in [f for f in (vf_s, vf) if f]:
        cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
               "-i", str(video), "-an", "-vf", f"{filt},tile={cols}x{rows}", "-frames:v", "1", "-q:v", "4",
               str(out_path)]
        r = media.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return times
    return None


# ---- cutting a clip out of a camera original ------------------------------

def extract(src, dst, start: float, end: float, speed: float = 1.0, copy: bool = False) -> bool:
    """Cut src[start:end] into dst. Re-encodes (exact cut, H.264) unless copy=True
    (bit-exact, cut snaps to keyframes). speed < 1 bakes slow motion (no audio)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dur = end - start
    cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
           "-i", str(src)]
    if copy and abs(speed - 1.0) < 1e-3:
        cmd += ["-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-avoid_negative_ts", "make_zero"]
    else:
        info = safe_probe(src) or {}
        h = info.get("height") or 1080
        vf = ["format=yuv420p"]
        if abs(speed - 1.0) >= 1e-3:
            vf.insert(0, f"setpts=PTS/{speed:.6f}")
        cmd += ["-map", "0:v:0", "-vf", ",".join(vf)] + media.h264_args("final", height=h)
        if abs(speed - 1.0) < 1e-3:
            cmd += ["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]
        cmd += ["-movflags", "+faststart"]
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    r = media.run(cmd + [str(tmp)], capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists():
        log(f"  ffmpeg failed on {src}: {(r.stderr or '').strip()[-300:]}")
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, dst)
    return True


def merge_ranges(ranges: list, gap: float = 0.5) -> list:
    """Union of (start, end) pairs, joining ones closer than `gap` seconds."""
    out = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def subtract_ranges(span: tuple, used: list, pad: float = 0.5) -> list:
    """Parts of span (start, end) not covered by `used` (each padded by `pad`)."""
    s0, e0 = span
    free, cur = [], s0
    for s, e in merge_ranges([(max(s0, s - pad), min(e0, e + pad)) for s, e in used], 0):
        if s > cur:
            free.append((cur, s))
        cur = max(cur, e)
    if cur < e0:
        free.append((cur, e0))
    return free


def write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
