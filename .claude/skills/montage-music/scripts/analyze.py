#!/usr/bin/env python3
"""Beat, tempo and energy analysis of a music track, with or without librosa.

  analyze.py TRACK [--out FILE.json] [--engine auto|basic|librosa]
  analyze.py TRACK --profile [START END STEP]     print a loudness profile (find entries by eye)

Writes a JSON (default: <cache>/music/<track stem>.beats.json, or --out) and prints one
JSON line on stdout: {"out", "tempo", "beats", "interval_cv", "lufs", "duration", "engine"}.

The JSON holds
  tempo         beats per minute (a half or double reading is harmless: cuts are sized in seconds)
  beats         detected beat times (s), tracked so small tempo drift is followed
  grid          a uniform grid at the median beat period, anchored on the detected beats.
                Use it when interval_cv > 0.06 (rubato, quiet intros with no beats)
  interval_cv   how regular the detected beats are (0 = metronome)
  energy_1s     [second, dB] loudness per second (max of 10 ms frames)
  entries       seconds where the level jumps >= 8 dB: a band or vocal coming in = in-point candidates
  loudest_10s   where the loudest 10 s starts (often the chorus / drop)
  ends_at       where the music has died away at the end: an end_at candidate for a natural ending
  lufs          integrated loudness of the whole track

Engines: "librosa" when it is installed (python3 -m pip install librosa), else "basic": ffmpeg
decodes the track and this script finds onsets in three bands (lows, full, highs), the tempo by
autocorrelation and the beat phase by a comb search. Standard library only.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media, settings  # noqa: E402

SR = 11000           # 110 samples = exactly 10 ms per analysis frame
HOP_S = 0.01            # 10 ms analysis frames
FPS = 1 / HOP_S


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ decode

def decode(path: str, af: str = "") -> array.array:
    """Mono int16 samples at SR, through an optional filter chain."""
    chain = f"aformat=channel_layouts=mono,aresample={SR}" + (f",{af}" if af else "")
    r = subprocess.run([media.ffmpeg(), "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0", "-af", chain,
                        "-f", "s16le", "-acodec", "pcm_s16le", "-"], capture_output=True)
    if r.returncode:
        sys.exit(f"ffmpeg could not decode {path}: {r.stderr.decode(errors='replace')[-400:]}")
    a = array.array("h")
    a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    return a


def decode_bands(path: str) -> tuple:
    """Full band, lows (< 200 Hz: kick, bass) and highs (> 3 kHz: hats, snares), one decode each."""
    full = decode(path)
    low = decode(path, "lowpass=f=200,lowpass=f=200")
    high = decode(path, "highpass=f=3000")
    n = min(len(full), len(low), len(high))
    return full[:n], low[:n], high[:n]


def frame_power(x: array.array) -> list:
    """Mean power per 10 ms frame."""
    hop = int(SR * HOP_S)
    out = []
    for i in range(0, len(x) - hop + 1, hop):
        seg = x[i:i + hop]
        out.append(sum(v * v for v in seg) / hop)
    return out


def to_db(p: float) -> float:
    return 10 * math.log10(p / (32768.0 ** 2) + 1e-12)


def onset_env(powers: list) -> list:
    """Half-wave rectified rise of log power, a little smoothed, normalised to max 1."""
    lg = [math.log10(p + 1.0) for p in powers]
    d = [0.0] + [max(0.0, lg[i] - lg[i - 1]) for i in range(1, len(lg))]
    sm = [(d[i - 1] if i else 0) * 0.25 + d[i] * 0.5 + (d[i + 1] if i + 1 < len(d) else 0) * 0.25 for i in range(len(d))]
    nz = sorted(v for v in sm if v > 0)
    m = nz[int(0.99 * (len(nz) - 1))] if nz else 1.0     # 99th percentile: one huge rise (the first sound) must not flatten the rest
    return [min(1.5, v / m) if m else 0.0 for v in sm]


# ------------------------------------------------------------------ tempo + beats

def tempo_autocorr(env: list, lo_bpm=60, hi_bpm=190) -> float:
    """Best beat period in frames: autocorrelation weighted towards ~120 BPM."""
    n = len(env)
    mean = sum(env) / n
    e = [v - mean for v in env]
    best, best_lag = -1e18, None
    scores = {}
    for lag in range(int(FPS * 60 / hi_bpm), int(FPS * 60 / lo_bpm) + 1):
        s = sum(e[i] * e[i + lag] for i in range(0, n - lag)) / (n - lag)
        bpm = 60 * FPS / lag
        w = math.exp(-0.5 * (math.log2(bpm / 120.0) / 0.9) ** 2)    # gentle prior on 120 BPM
        scores[lag] = s * w
        if s * w > best:
            best, best_lag = s * w, lag
    a, b, c = scores.get(best_lag - 1, best), best, scores.get(best_lag + 1, best)
    den = a - 2 * b + c
    return best_lag + (0.5 * (a - c) / den if den else 0.0)


def comb_fit(env: list, period: float) -> tuple:
    """Refine the period (+-2 %) and find the phase with the strongest beats on it."""
    n = len(env)
    best = (-1.0, period, 0.0)
    for k in range(-20, 21):
        p = period * (1 + k * 0.001)
        for ph10 in range(0, int(p * 10)):
            ph = ph10 / 10.0
            idx = ph
            s, cnt = 0.0, 0
            while idx < n:
                s += env[int(idx)]
                cnt += 1
                idx += p
            if cnt and s / cnt > best[0]:
                best = (s / cnt, p, ph)
    return best[1], best[2]


def track_beats(env: list, period: float, phase: float) -> list:
    """Walk beat to beat from the strongest phase, letting each beat move +-8 % of a period
    towards the nearest strong onset (follows small drift, never jumps tempo)."""
    n = len(env)
    win = max(1, int(period * 0.08))
    beats = []
    t = phase
    while t - period >= 0:
        t -= period
    prev = None
    while t < n:
        c = int(round(t))
        lo, hi = max(0, c - win), min(n - 1, c + win)
        if hi <= lo:
            break
        j = max(range(lo, hi + 1), key=lambda i: env[i] * math.exp(-0.5 * ((i - t) / (win + 1e-9)) ** 2))
        pos = j if env[j] > 0.15 else t
        if prev is not None and pos - prev < period * 0.5:
            pos = prev + period
        beats.append(pos)
        prev = pos
        t = pos + period
    return [round(b * HOP_S, 3) for b in beats]


def basic_analysis(path: str) -> tuple:
    full, low, high = decode_bands(path)
    pf, pl, ph = frame_power(full), frame_power(low), frame_power(high)
    ef, el, eh = onset_env(pf), onset_env(pl), onset_env(ph)
    env = [0.5 * el[i] + 0.3 * ef[i] + 0.2 * eh[i] for i in range(len(ef))]
    period = tempo_autocorr(env)
    period, phase = comb_fit(env, period)
    # the comb cannot tell the beat from the off-beat (hi-hats); the kick drum usually sits on the beat
    def low_score(ph):
        vals, t = [], ph
        while t < len(el):
            vals.append(el[int(t)])
            t += period
        return sum(vals) / max(1, len(vals))
    if low_score((phase + period / 2) % period) > 1.2 * low_score(phase):
        phase = (phase + period / 2) % period
    beats = track_beats(env, period, phase)
    dur = len(full) / SR
    return beats, 60 * FPS / period, [to_db(p) for p in pf], dur


def librosa_analysis(path: str) -> tuple:
    import numpy as np  # noqa
    import librosa      # noqa
    y, sr = librosa.load(path, sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    hop = int(sr * HOP_S)
    rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
    db = [float(20 * np.log10(v + 1e-6)) for v in rms]
    return [round(float(b), 3) for b in beats], float(np.atleast_1d(tempo)[0]), db, float(len(y) / sr)


# ------------------------------------------------------------------ structure

def per_second(db_frames: list) -> list:
    n = int(1 / HOP_S)
    return [(i // n, max(db_frames[i:i + n])) for i in range(0, len(db_frames), n)]


def lufs(path: str) -> float | None:
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-nostats", "-nostdin", "-i", path, "-map", "0:a:0",
                        "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(m[-1]) if m else None


def structure(sec: list, beats: list) -> dict:
    vals = [d for _, d in sec]
    peak = max(vals) if vals else -90
    entries = []
    for i in range(1, len(sec)):
        if vals[i] - vals[i - 1] >= 8 and vals[i] > peak - 25:
            t = float(sec[i][0])
            if beats:
                t = min(beats, key=lambda b: abs(b - t)) if abs(min(beats, key=lambda b: abs(b - t)) - t) < 1.0 else t
            entries.append(round(t, 2))
    loud = None
    if len(vals) >= 10:
        best = max(range(len(vals) - 9), key=lambda i: sum(10 ** (v / 10) for v in vals[i:i + 10]))
        loud = float(sec[best][0])
    ends = float(len(vals))
    for i in range(len(vals) - 1, -1, -1):
        if vals[i] > peak - 30:
            ends = float(i + 1)
            break
    return {"entries": entries, "loudest_10s": loud, "ends_at": round(ends, 1), "peak_db": round(peak, 1)}


def uniform_grid(beats: list, dur: float) -> tuple:
    iv = [b - a for a, b in zip(beats, beats[1:])]
    if len(iv) < 4:
        return beats, None, 1.0
    s = sorted(iv)
    per = s[len(s) // 2]
    mean = sum(iv) / len(iv)
    cv = math.sqrt(sum((x - mean) ** 2 for x in iv) / len(iv)) / mean if mean else 1.0
    t0 = beats[0]
    while t0 - per >= 0:
        t0 -= per
    grid, t = [], t0
    while t < dur - 0.05:
        grid.append(round(t, 3))
        t += per
    return grid, per, cv


def default_out(track: Path) -> Path:
    return settings.cache_dir("music") / f"{track.stem}.beats.json"


def analyze(track: str, out: str | None = None, engine: str = "auto") -> dict:
    p = Path(track).expanduser().resolve()
    if not p.is_file():
        sys.exit(f"no such file: {p}")
    used = "basic"
    if engine in ("auto", "librosa"):
        try:
            beats, tempo, db, dur = librosa_analysis(str(p))
            used = "librosa"
        except ImportError:
            if engine == "librosa":
                sys.exit("librosa is not installed. It is optional (the basic engine works without it):\n"
                         "  python3 -m pip install librosa")
    if used == "basic":
        beats, tempo, db, dur = basic_analysis(str(p))
    grid, per, cv = uniform_grid(beats, dur)
    sec = per_second(db)
    doc = {"file": str(p), "engine": used, "duration": round(dur, 2), "tempo": round(tempo, 1),
           "period": round(per, 4) if per else None, "interval_cv": round(cv, 3),
           "beats": beats, "grid": grid, "lufs": lufs(str(p)),
           "energy_1s": [[t, round(d, 1)] for t, d in sec], **structure(sec, beats)}
    o = Path(out).expanduser().resolve() if out else default_out(p)
    o.parent.mkdir(parents=True, exist_ok=True)
    o.write_text(json.dumps(doc))
    doc["out"] = str(o)
    return doc


def print_profile(track: str, start: float, end: float | None, step: float) -> None:
    full, _, _ = decode_bands(track)
    db = [to_db(p) for p in frame_power(full)]
    n = max(1, int(step / HOP_S))
    a = int(start / HOP_S)
    b = len(db) if end is None else min(len(db), int(end / HOP_S))
    prev = None
    for i in range(a, b, n):
        d = max(db[i:i + n])
        line = f"{i * HOP_S:7.2f}s {d:6.1f} dB " + "#" * max(0, int((d + 60) / 2))
        if prev is not None and d - prev >= 8:
            line += f"   <- ENTRY (+{d - prev:.0f} dB)"
        print(line)
        prev = d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("track")
    ap.add_argument("--out", help="where to write the analysis JSON")
    ap.add_argument("--engine", choices=("auto", "basic", "librosa"), default="auto")
    ap.add_argument("--profile", nargs="*", type=float, metavar="START END STEP",
                    help="print a loudness profile instead (default whole track at 1 s)")
    a = ap.parse_args()
    media.require("ffmpeg")
    if a.profile is not None:
        st = a.profile + [None] * (3 - len(a.profile))
        print_profile(a.track, st[0] or 0.0, st[1], st[2] or 1.0)
        return 0
    try:
        doc = analyze(a.track, a.out, a.engine)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    log(f"{Path(a.track).name}: {doc['duration']} s, {doc['tempo']} BPM ({doc['engine']}), {len(doc['beats'])} beats, "
        f"interval CV {doc['interval_cv']} ({'use beats' if doc['interval_cv'] <= 0.06 else 'irregular: use grid'}), "
        f"{doc['lufs']} LUFS, entries {doc['entries'][:6]}, loudest 10 s at {doc['loudest_10s']}, ends at {doc['ends_at']} s")
    print(json.dumps({k: doc[k] for k in ("out", "tempo", "interval_cv", "lufs", "duration", "engine", "entries", "ends_at")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
