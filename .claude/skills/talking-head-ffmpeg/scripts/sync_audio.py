#!/usr/bin/env python3
"""Sync a separately recorded voice track (a lav or desk-mic recorder) to a talking-head take, clock drift included.

    sync_audio.py TAKE.mp4 RECORDER.wav [--wav SYNCED_16k.wav]

Measures audio_s = offset_s + rate * take_s by cross-correlating the two recordings: one coarse pass (a minute of the
take against the whole recorder file at 4 kHz), then a 15 s window every 30 s (closer on a short take), fitted to a line. Two devices' clocks
drift apart (tens of parts per million: several frames over a long take), so one offset is not enough.

Writes <take stem>.audio_sync.json next to the take: {"audio", "offset_s", "rate", "residual_ms", "windows"}.
timeline.py copies it into the recipe's "take_audio" and the renderer then cuts every keep's sound from the recorder
instead of the camera. --wav writes the recorder on the take's clock as 16 kHz mono (silence where it was not running):
transcribe that and run aroll-draft on it, so the cut is made on the sound that will play.

Needs numpy (python3 -m pip install numpy). Run it BEFORE aroll-draft, so the cut is made on the better sound.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

SR = 16000


def need_numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        sys.exit("sync_audio.py needs numpy for the cross-correlation. Install it with:\n"
                 "  python3 -m pip install numpy\n(ask the user first)")


def pcm(np, path):
    raw = subprocess.run([C.ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True)
    if raw.returncode:
        sys.exit(f"could not decode audio from {path}: {raw.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(raw.stdout, dtype=np.int16).astype(np.float32)


def xcorr(np, a, b):
    """Full cross-correlation of b inside a via FFT: index i means b starts at a[i]."""
    n = 1 << (len(a) + len(b)).bit_length()
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    return c[: len(a) - len(b) + 1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take")
    ap.add_argument("audio")
    ap.add_argument("--wav", help="write the recorder on the take's clock (16 kHz mono) here")
    a = ap.parse_args()
    np = need_numpy()
    take, audio = str(Path(a.take).resolve()), str(Path(a.audio).resolve())
    cam, st = pcm(np, take), pcm(np, audio)
    if len(cam) < SR * 20 or len(st) < SR * 20:
        sys.exit("both recordings must be at least 20 s long")

    def pool(x, k=4):           # 16 kHz -> 4 kHz, enough for a coarse match
        x = x[: len(x) // k * k]
        return x.reshape(-1, k).mean(axis=1)
    c0 = 5.0
    chunk = pool(cam[int(c0 * SR): int(min(len(cam) / SR, c0 + 60) * SR)])
    c = np.abs(xcorr(np, pool(st), chunk))
    if not len(c):
        sys.exit("the recorder file is shorter than the stretch of the take used to find it")
    off0 = np.argmax(c) / (SR / 4) - c0                     # audio_s ~= take_s + off0
    peak = float(c.max() / (np.sqrt(np.mean(c ** 2)) + 1e-9))
    pts = []
    step = min(30.0, max(8.0, (len(cam) / SR - 25) / 6))     # every 30 s on a long take, at least ~6 windows on a short one
    for t in np.arange(5.0, len(cam) / SR - 20, step):
        x = cam[int(t * SR): int((t + 15) * SR)]
        s0 = int((t + off0 - 0.25) * SR)
        if s0 < 0 or s0 + len(x) + SR // 2 > len(st) or np.std(x) < 1:
            continue
        cc = np.abs(xcorr(np, st[s0: s0 + len(x) + SR // 2], x))
        if cc.max() / (np.sqrt(np.mean(cc ** 2)) + 1e-9) >= 8:   # silence or noise has no clear peak
            pts.append((t, (s0 + int(np.argmax(cc))) / SR))
    if len(pts) < 2:
        sys.exit(f"only {len(pts)} windows correlated (coarse peak/rms {peak:.1f}) - is {os.path.basename(audio)} "
                 "the same take?")
    t, s = np.array(pts).T
    rate, off = np.polyfit(t, s, 1) if len(pts) >= 3 else (1.0, float(np.mean(s - t)))
    resid = float(np.abs(s - (off + rate * t)).max() * 1000)
    if resid > 20:
        sys.exit(f"windows disagree by {resid:.0f} ms after the fit - a gap or an edit in one recording?")
    res = {"audio": audio, "offset_s": round(float(off), 6), "rate": round(float(rate), 9),
           "residual_ms": round(resid, 1), "windows": len(pts)}
    side = os.path.splitext(take)[0] + ".audio_sync.json"
    Path(side).write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    if a.wav:
        n = np.arange(len(cam), dtype=np.float64)
        y = np.interp((off + rate * n / SR) * SR, np.arange(len(st)), st, left=0, right=0)
        with wave.open(a.wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(np.clip(y, -32768, 32767).astype(np.int16).tobytes())
    print(json.dumps({**res, "sidecar": side, **({"wav": a.wav} if a.wav else {}),
                      "drift_ms_over_take": round((rate - 1) * len(cam) / SR * 1000, 1)}))


if __name__ == "__main__":
    main()
