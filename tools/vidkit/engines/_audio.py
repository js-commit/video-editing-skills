"""Audio extraction shared by the engines: every engine gets audio, never a
whole video file."""
from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path

from vidkit import media
from vidkit.transcript import TranscriptionError


def _ffmpeg_audio(src: Path, dst: Path, codec_args: list, start: float | None = None,
                  length: float | None = None) -> Path:
    cmd = [media.ffmpeg(), "-hide_banner", "-nostdin", "-y", "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-vn", "-sn", "-dn", "-map", "0:a:0", "-ac", "1", "-ar", "16000"] + codec_args + [str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
        raise TranscriptionError(f"ffmpeg could not extract the audio from {src.name}: "
                                 f"{r.stderr.strip()[-600:]}")
    return dst


def wav16k(src: Path, workdir: Path) -> Path:
    """16 kHz mono 16-bit WAV: lossless for timing, the local engine's native rate."""
    return _ffmpeg_audio(src, workdir / "audio16k.wav", ["-c:a", "pcm_s16le"])


@functools.lru_cache(None)
def _has_encoder(name: str) -> bool:
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True)
    return f" {name} " in r.stdout


def compressed16k(src: Path, dst_base: Path, start: float | None = None,
                  length: float | None = None) -> Path:
    """Small upload copy: 16 kHz mono MP3 at 64 kb/s (~29 MB an hour), or FLAC
    when this ffmpeg has no MP3 encoder (lossless, about twice the size)."""
    if _has_encoder("libmp3lame"):
        return _ffmpeg_audio(src, dst_base.with_suffix(".mp3"),
                             ["-c:a", "libmp3lame", "-b:a", "64k"], start, length)
    return _ffmpeg_audio(src, dst_base.with_suffix(".flac"), ["-c:a", "flac"], start, length)


def silences(src: Path, noise_db: int = -35, min_s: float = 0.3) -> list:
    """[(start, end)] of the quiet stretches, from ffmpeg's silencedetect."""
    cmd = [media.ffmpeg(), "-hide_banner", "-nostdin", "-i", str(src), "-vn", "-map", "0:a:0",
           "-ac", "1", "-ar", "16000", "-af", f"silencedetect=noise={noise_db}dB:d={min_s}",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = float(m.group(1))
            continue
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append((max(0.0, start), float(m.group(1))))
            start = None
    return out
