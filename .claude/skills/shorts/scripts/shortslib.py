"""Shared helpers for the shorts scripts: transcript words, sizes, safe zones,
framing geometry, fonts and small ffmpeg probes. Standard library only.

Imported by the other scripts in this folder:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import shortslib as sl
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402

DEFAULT_SIZE = (1080, 1920)

# YouTube Shorts UI overlays, as fractions of the frame (portrait 9:16).
# Top: search / menu. Bottom: title, channel, description, music ticker.
# Right: like / comment / share / remix rail. Text and the subject stay inside.
SAFE = {"top": 0.08, "bottom": 0.22, "left": 0.04, "right": 0.13}


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def log(*a):
    print(*a, file=sys.stderr)


def parse_size(s) -> tuple:
    if isinstance(s, (list, tuple)):
        w, h = int(s[0]), int(s[1])
    else:
        m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", str(s))
        if not m:
            die(f"size {s!r} is not WIDTHxHEIGHT (e.g. 1080x1920)", 2)
        w, h = int(m.group(1)), int(m.group(2))
    if w % 2 or h % 2:
        die(f"size {w}x{h}: both sides must be even", 2)
    if abs(w / h - 9 / 16) > 0.01:
        die(f"size {w}x{h} is not 9:16 portrait (Shorts are 1080x1920, 1440x2560 or 2160x3840)", 2)
    return w, h


def safe_rect(w: int, h: int) -> tuple:
    """(x0, y0, x1, y1) of the area the Shorts UI leaves uncovered."""
    return (round(w * SAFE["left"]), round(h * SAFE["top"]),
            round(w * (1 - SAFE["right"])), round(h * (1 - SAFE["bottom"])))


# ---- transcript -------------------------------------------------------------

def default_transcript(source: str | Path) -> Path:
    p = Path(source)
    side = p.with_name(p.stem + ".transcript.json")
    if not side.exists():
        found = _find_sidecar(p)
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


def load_transcript(path: str | Path) -> dict:
    try:
        from vidkit.transcript import load_transcript as _lt  # the shared sidecar reader
        return _lt(path)
    except ImportError:
        pass
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_words(path: str | Path) -> list:
    """Every timed word, sorted: [{"word", "start", "end"}]."""
    data = load_transcript(path)
    words = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            text = str(w.get("word", "")).strip()
            if text:
                words.append({"word": text, "start": float(w["start"]), "end": float(w["end"])})
    words.sort(key=lambda w: w["start"])
    return words


def norm(text: str) -> str:
    return re.sub(r"[^\w']+", " ", text.lower()).strip()


def words_between(words: list, start: float, end: float, eps: float = 0.03) -> list:
    return [w for w in words if w["start"] >= start - eps and w["end"] <= end + eps]


def ends_sentence(word: str) -> bool:
    return word.rstrip("\"')]").endswith((".", "!", "?"))


# ---- probes -----------------------------------------------------------------

_PROBES: dict = {}


def probe(path: str | Path) -> dict:
    """media.probe plus the sample aspect ratio, cached per file."""
    key = str(path)
    if key not in _PROBES:
        if not Path(path).exists():
            die(f"file not found: {path}")
        info = media.probe(path)
        r = subprocess.run([media.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=sample_aspect_ratio", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True)
        sar = (r.stdout.strip().split("\n") or [""])[0]
        info["sar"] = sar if re.fullmatch(r"\d+:\d+", sar) and sar not in ("1:1", "0:1") else None
        if info.get("rotation") in (90, -90, 270, -270) and info["width"] and info["height"]:
            info["width"], info["height"] = info["height"], info["width"]  # display size (ffmpeg autorotates)
        _PROBES[key] = info
    return _PROBES[key]


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff")


def has_filter(name: str) -> bool:
    out = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", out, re.M) is not None


# ---- geometry -----------------------------------------------------------------

def window(src_w: int, src_h: int, aspect: float, zoom: float = 1.0,
           cx: float = 0.5, cy: float = 0.5) -> tuple:
    """Source rect (x, y, w, h) of `aspect` (w/h) for a framing.

    zoom 1 = the largest rect of that aspect inside the frame; zoom 2 = half of
    it each way (a 2x punch-in). cx / cy place it: 0 = left / top edge,
    0.5 = centred, 1 = right / bottom edge. Even pixels, clamped inside."""
    zoom = max(1.0, float(zoom))
    if src_w / src_h > aspect:
        h = src_h / zoom
        w = h * aspect
    else:
        w = src_w / zoom
        h = w / aspect
    w = max(2, int(w) // 2 * 2)
    h = max(2, int(h) // 2 * 2)
    x = int(round((src_w - w) * min(1.0, max(0.0, float(cx))))) // 2 * 2
    y = int(round((src_h - h) * min(1.0, max(0.0, float(cy))))) // 2 * 2
    return max(0, min(src_w - w, x)), max(0, min(src_h - h, y)), w, h


def center_for(subject_px: float, src_len: int, win_len: int) -> float:
    """crop_center that puts a subject at `subject_px` in the middle of the window."""
    if src_len <= win_len:
        return 0.5
    return min(1.0, max(0.0, (subject_px - win_len / 2) / (src_len - win_len)))


# ---- fonts (drawtext needs a file; libass finds fonts by name) -------------

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/Library/Fonts/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def find_font(preferred: str | None = None) -> str | None:
    if preferred and Path(preferred).expanduser().is_file():
        return str(Path(preferred).expanduser())
    for c in FONT_CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def ff_escape_path(p: str) -> str:
    """A path inside a filtergraph option value (single-quoted)."""
    return str(p).replace("\\", "/").replace("'", r"'\''").replace(":", r"\:")


# ---- where things go ----------------------------------------------------------

def work_dir(source: str | Path) -> Path:
    """<project>/<work>/shorts/<stem>/ inside a project, else shorts-work/<stem>/ beside the source."""
    src = Path(source).expanduser().resolve()
    proj = settings.find_project_root(src)
    base = (proj / settings.layout("work") / "shorts") if proj else (src.parent / "shorts-work")
    d = base / src.stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def ffmpeg_cmd(*args) -> list:
    return [media.ffmpeg(), "-hide_banner", *args]


def run_ok(cmd: list, what: str) -> subprocess.CompletedProcess:
    r = media.run(cmd, capture_output=True, text=True)
    if r.returncode:
        die(f"{what} failed:\n{(r.stderr or '')[-1500:]}")
    return r
