#!/usr/bin/env python3
"""ffmpeg / ffprobe helpers shared by every skill: finding the binaries,
probing files, picking a hardware encoder, and hardware decode for HEVC.

    from vidkit import media
    info = media.probe("/path/clip.mov")      # duration, fps, width, height, has_video, has_audio, vcodec
    vargs = media.h264_args(quality="draft")   # ["-c:v", "h264_videotoolbox", "-b:v", "12M"] or libx264 ...
    media.run(["ffmpeg", "-i", clip, ...])     # subprocess.run with HEVC decoded on the GPU where that is faster

Encoder choice (settings render.video_encoder, default "auto"):
  auto -> h264_videotoolbox on macOS, h264_nvenc when an NVIDIA encoder works,
          else libx264 (always available, slower). "libx264", "h264_videotoolbox",
          "h264_nvenc", "h264_qsv", "h264_amf" force one.

Shell: `media.py probe FILE`, `media.py encoder`, `media.py check` (prints
what is installed, exit 1 if ffmpeg/ffprobe are missing).
"""
from __future__ import annotations

import functools
import json
import platform
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

INSTALL_HINT = {
    "Darwin": "brew install ffmpeg   (Homebrew: https://brew.sh)",
    "Windows": "winget install --id Gyan.FFmpeg   (then open a new terminal)",
    "Linux": "sudo apt install ffmpeg   (or your distro's package manager)",
}


def system() -> str:
    return platform.system()


def is_macos() -> bool:
    return system() == "Darwin"


def which(name: str) -> str | None:
    return shutil.which(name)


def require(name: str = "ffmpeg") -> str:
    path = which(name)
    if not path:
        sys.exit(f"{name} is not installed (or not on PATH). Install it with:\n  "
                 f"{INSTALL_HINT.get(system(), INSTALL_HINT['Linux'])}\n"
                 f"Ask the user before installing anything.")
    return path


def ffmpeg() -> str:
    return require("ffmpeg")


def ffprobe() -> str:
    return require("ffprobe")


def _fps(rate: str | None) -> Fraction | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        f = Fraction(rate)
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: str | Path) -> dict:
    """Basic facts about a media file. fps is a string like '30000/1001'."""
    out = subprocess.run(
        [ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"ffprobe failed on {path}: {out.stderr.strip()}")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = _fps(v.get("avg_frame_rate")) or _fps(v.get("r_frame_rate")) if v else None
    dur = data.get("format", {}).get("duration") or (v or a or {}).get("duration")
    rot = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int(v.get("tags", {}).get("rotate", rot) or rot)
    return {
        "path": str(path),
        "duration": float(dur) if dur else None,
        "has_video": v is not None,
        "has_audio": a is not None,
        "vcodec": v.get("codec_name") if v else None,
        "acodec": a.get("codec_name") if a else None,
        "width": int(v["width"]) if v and v.get("width") else None,
        "height": int(v["height"]) if v and v.get("height") else None,
        "rotation": rot,
        "fps": str(fps) if fps else None,
        "fps_float": float(fps) if fps else None,
        "pix_fmt": v.get("pix_fmt") if v else None,
        "creation_time": data.get("format", {}).get("tags", {}).get("creation_time"),
        "audio_channels": int(a.get("channels", 0)) if a else 0,
        "sample_rate": int(a.get("sample_rate", 0)) if a else 0,
    }


def duration(path: str | Path) -> float:
    d = probe(path)["duration"]
    if d is None:
        sys.exit(f"could not read the duration of {path}")
    return d


@functools.lru_cache(None)
def _encoders() -> str:
    out = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True)
    return out.stdout


@functools.lru_cache(None)
def _encoder_works(name: str) -> bool:
    """A 0.1 s test encode: listed is not the same as usable (no GPU, no driver)."""
    if name not in _encoders():
        return False
    r = subprocess.run([ffmpeg(), "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=black:s=256x144:d=0.1", "-c:v", name, "-f", "null", "-"],
                       capture_output=True, text=True)
    return r.returncode == 0


@functools.lru_cache(None)
def h264_encoder() -> str:
    try:
        from vidkit import settings  # noqa
        forced = settings.get("render.video_encoder", default="auto")
    except Exception:
        forced = "auto"
    if forced and forced != "auto":
        return forced
    candidates = (["h264_videotoolbox"] if is_macos() else []) + ["h264_nvenc", "h264_qsv", "h264_amf"]
    for name in candidates:
        if _encoder_works(name):
            return name
    return "libx264"


def h264_args(quality: str = "draft", height: int | None = None, width: int | None = None) -> list:
    """Video codec args. quality: 'draft' (fast, review copies) or 'final' (high bitrate).
    The bitrate scales with the frame's SHORT side, so a 1080x1920 vertical gets the 1080p rate."""
    enc = h264_encoder()
    sides = [x for x in (height, width) if x]
    tall = min(sides) if sides else 1080
    draft_mbps = 8 if tall <= 1080 else 24
    final_mbps = 16 if tall <= 1080 else 45
    mbps = draft_mbps if quality == "draft" else final_mbps
    if enc == "libx264":
        crf = "23" if quality == "draft" else "17"
        preset = "veryfast" if quality == "draft" else "slow"
        return ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p"]
    args = ["-c:v", enc, "-b:v", f"{mbps}M", "-maxrate", f"{int(mbps * 1.5)}M", "-bufsize", f"{mbps * 2}M"]
    if enc == "h264_videotoolbox":
        args += ["-allow_sw", "1"]
    return args + ["-pix_fmt", "yuv420p"]


# ---- hardware decode (HEVC only; H.264 decodes faster on the CPU) ----------

HW_DECODE = ["-hwaccel", "videotoolbox"]


@functools.lru_cache(None)
def is_hevc(path: str) -> bool:
    """First sample description is hvc1/hev1 (MP4/MOV), read from the moov box, ~1 ms."""
    try:
        with open(path, "rb") as f:
            while True:
                h = f.read(8)
                if len(h) != 8:
                    break
                size, kind = int.from_bytes(h[:4], "big"), h[4:]
                if size == 1:
                    size = int.from_bytes(f.read(8), "big") - 16
                elif size >= 8:
                    size -= 8
                else:
                    return False
                if kind == b"moov":
                    m = f.read(size)
                    i = m.find(b"stsd")
                    while i >= 0:
                        if m[i + 16:i + 20] in (b"hvc1", b"hev1"):
                            return True
                        i = m.find(b"stsd", i + 4)
                    return False
                f.seek(size, 1)
    except (OSError, ValueError):
        pass
    return False


def hw(cmd: list) -> list:
    """`cmd` with -hwaccel videotoolbox before each HEVC input (macOS only)."""
    if not is_macos() or not any(str(a).endswith(("ffmpeg", "ffmpeg.exe")) for a in cmd[:5]):
        return list(cmd)
    out = []
    for i, a in enumerate(cmd):
        if a == "-i" and i + 1 < len(cmd) and is_hevc(str(cmd[i + 1])):
            out += HW_DECODE
        out.append(a)
    return out


def run(cmd: list, **kw):
    """subprocess.run with HEVC inputs hardware-decoded; a failure re-runs on the CPU."""
    check = kw.pop("check", False)
    fast = hw(cmd)
    r = subprocess.run(fast, **kw)
    if r.returncode and fast != list(cmd):
        r = subprocess.run(cmd, **kw)
    if check and r.returncode:
        raise subprocess.CalledProcessError(r.returncode, cmd, getattr(r, "stdout", None), getattr(r, "stderr", None))
    return r


def check() -> dict:
    tools = {t: which(t) for t in ("ffmpeg", "ffprobe", "exiftool", "yt-dlp", "swiftc")}
    info = {"os": system(), "python": sys.version.split()[0], "tools": tools}
    if tools["ffmpeg"]:
        info["h264_encoder"] = h264_encoder()
        filters = subprocess.run([tools["ffmpeg"], "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        info["ffmpeg_filters"] = {f: (f" {f} " in filters) for f in ("vidstabdetect", "drawtext", "subtitles", "loudnorm", "zscale")}
    for mod in ("numpy", "scipy", "PIL", "cv2", "librosa"):
        try:
            __import__(mod)
            info.setdefault("python_modules", {})[mod] = True
        except Exception:
            info.setdefault("python_modules", {})[mod] = False
    return info


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if len(sys.argv) >= 3 and sys.argv[1] == "probe":
        print(json.dumps(probe(sys.argv[2]), indent=2))
    elif len(sys.argv) == 2 and sys.argv[1] == "encoder":
        print(h264_encoder())
    elif len(sys.argv) == 2 and sys.argv[1] == "check":
        info = check()
        print(json.dumps(info, indent=2))
        sys.exit(0 if info["tools"]["ffmpeg"] and info["tools"]["ffprobe"] else 1)
    else:
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help") else 2)
