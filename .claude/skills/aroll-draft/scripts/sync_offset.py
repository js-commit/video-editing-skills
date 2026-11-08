#!/usr/bin/env python3
"""Measure how far apart two cameras started rolling on the same take, by
cross-correlating their audio. Camera clocks and creation times are not to be
trusted for this (they drift, sit in other time zones, or are simply wrong);
the audio is ground truth.

Usage: sync_offset.py PRIMARY SECONDARY

Each input is a video/audio file or a 16 kHz mono wav (aroll-draft's
audio_16k.wav); other files are converted with ffmpeg first. Prints JSON:

  offset_s      how much LATER the secondary camera started than the primary
                (secondary time = primary time - offset_s; negative = earlier)
  peak_to_rms   confidence: the same take scores in the hundreds; under ~20,
                distrust the result (different takes, or one camera had no mic)

Needs numpy (FFT). Install with: python3 -m pip install numpy
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

RATE = 16000


def need_numpy():
    try:
        import numpy as np  # noqa: F401
        return np
    except ImportError:
        sys.exit("sync_offset.py needs numpy for the audio cross-correlation. Install it with:\n"
                 "  python3 -m pip install numpy\n(ask the user first)")


def as_wav(path):
    """(wav path, is_temp): reuse a 16 kHz mono 16-bit wav, else extract one."""
    if path.lower().endswith(".wav"):
        with wave.open(path, "rb") as w:
            if w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == RATE:
                return path, False
    from vidkit import media
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    r = media.run([media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-vn",
                   "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", tmp.name])
    if r.returncode != 0:
        sys.exit(f"ffmpeg could not read the audio of {path}")
    return tmp.name, True


def load(np, path):
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)


def xcorr(np, a, b):
    """Full cross-correlation of a with b (lag L such that a[i] ~ b[i - L] peaks at index L + len(b) - 1)."""
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    fa = np.fft.rfft(a, size)
    fb = np.fft.rfft(b[::-1], size)
    return np.fft.irfft(fa * fb, size)[:n]


def decimate(np, x, q):
    """Box-filter decimation: plenty for the coarse pass, which only has to land within a second."""
    n = len(x) - len(x) % q
    return x[:n].reshape(-1, q).mean(axis=1)


def main(primary_path, secondary_path):
    np = need_numpy()
    temps = []
    try:
        pw, t1 = as_wav(primary_path)
        sw, t2 = as_wav(secondary_path)
        temps = [p for p, t in ((pw, t1), (sw, t2)) if t]
        prim, sec = load(np, pw), load(np, sw)
    finally:
        for p in temps:
            os.unlink(p)
    sr = RATE
    if len(prim) < sr or len(sec) < sr:
        sys.exit("both recordings need at least a second of audio")

    # coarse pass over the whole files at 4 kHz
    q = 4
    pd, sd = decimate(np, prim, q), decimate(np, sec, q)
    corr = xcorr(np, pd - pd.mean(), sd - sd.mean())
    lag_coarse = int(corr.argmax() - (len(sd) - 1)) * q

    # refine at full rate on a 120 s slice of the primary from a quarter in
    win = sr
    start = max(0, len(prim) // 4)
    seg = prim[start:start + 120 * sr]
    s0 = max(0, start - lag_coarse - win)
    sec_seg = sec[s0:s0 + len(seg) + 2 * win]
    if len(sec_seg) < sr:
        sys.exit("the recordings barely overlap: check that both are the same take")
    corr2 = xcorr(np, seg, sec_seg)
    fine = int(corr2.argmax() - (len(sec_seg) - 1))
    lag = start - (s0 - fine)   # prim[i] ~ sec[i - lag]

    peak = float(np.abs(corr2).max())
    rms = float(np.sqrt(np.mean(corr2 ** 2)))
    print(json.dumps({"offset_s": lag / sr, "lag_samples": int(lag), "sample_rate": sr,
                      "peak_to_rms": round(peak / rms, 1) if rms else 0.0}))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 else 2)
    main(sys.argv[1], sys.argv[2])
