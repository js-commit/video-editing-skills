"""voz: offline speech-to-text on an Apple silicon Mac (macOS 26+); the audio
stays on the Mac. Desert Ant Labs' Voz model recognises the words and their Align model
sharpens the word edges, both on the Neural Engine, through the small Swift
command tools/bin/voz-engine (source and build script in tools/voz-engine/).

Fast (a 16-minute take in a few seconds) and free. It keeps about half the
"um"s and "uh"s ElevenLabs Scribe keeps, so a-roll cuts need a little more
hand-trimming; for sorting footage, home videos and b-roll context it is the
right engine. The ~470 MB model downloads once, on the first run.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path

from vidkit import media
from vidkit.engines import _audio
from vidkit.transcript import TranscriptionError

NAME = "voz"
KIND = "local"
TOOLS = Path(__file__).resolve().parents[2]
ENGINE_BIN = TOOLS / "bin" / "voz-engine"
MODEL_DIR = Path("~/Library/Caches/desert-ant-models/desert-ant-labs/voz").expanduser()
MIN_MACOS = 26
TIMEOUT_S = 1800


def problem() -> str | None:
    """Why voz cannot run on this computer, or None."""
    if platform.system() != "Darwin":
        return "runs only on a Mac (the models use Apple's Neural Engine)"
    if platform.machine() != "arm64":
        return "needs an Apple silicon Mac (M1 or newer)"
    major = (platform.mac_ver()[0] or "0").split(".")[0]
    try:
        if int(major) < MIN_MACOS:
            return f"needs macOS {MIN_MACOS} or newer (this Mac has {platform.mac_ver()[0]})"
    except ValueError:
        return "could not read the macOS version"
    if not os.access(ENGINE_BIN, os.X_OK):
        return f"engine binary missing or not executable: {ENGINE_BIN} (restore it with git checkout -- tools/bin/voz-engine, or rebuild: tools/voz-engine/build.sh)"
    return None


def model_cached() -> bool:
    return MODEL_DIR.is_dir()


def available():
    why = problem()
    return (False, why) if why else (True, None)


def transcribe(src: Path, workdir: Path, language, duration, log) -> dict:
    why = problem()
    if why:
        raise TranscriptionError(f"voz {why}")
    if not model_cached():
        log("first voz run on this Mac: downloading the speech model (about 470 MB, once)...")
    # With ffmpeg, hand voz-engine the same 16 kHz mono WAV every other tool
    # decodes; without it, voz-engine decodes the media file itself.
    audio = _audio.wav16k(src, workdir) if media.which("ffmpeg") else src
    out = workdir / "voz.json"
    cmd = [str(ENGINE_BIN), str(audio), "-o", str(out), "--language", language or "en"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise TranscriptionError(f"voz-engine did not finish within {TIMEOUT_S}s")
    if r.returncode != 0 or not out.is_file():
        raise TranscriptionError(f"voz-engine failed: {r.stderr.strip()[-800:]}")
    doc = json.loads(out.read_text())
    st = doc.get("stats") or {}
    log(f"voz: {st.get('words', 0)} words in {st.get('voz_s', 0):.1f}s, "
        f"align {st.get('align_s', 0):.1f}s ({st.get('refined', 0)} edges refined)")
    words = [{"start": float(w["start"]), "end": float(w["end"]), "word": (w.get("text") or "").strip()}
             for w in doc.get("words") or [] if (w.get("text") or "").strip()]
    return {"words": words, "language": doc.get("language") or language,
            "model": doc.get("model") or "Voz + Align"}
