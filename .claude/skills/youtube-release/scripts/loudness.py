#!/usr/bin/env python3
"""Loudness check for a finished video before it goes to YouTube: measure, and
fix only when needed with a two-pass ffmpeg loudnorm. The picture is never
re-encoded (the video stream is copied bit for bit).

    loudness.py VIDEO...                      # measure: exit 0 = fine, 1 = needs a fix
    loudness.py VIDEO --fix                   # writes <stem>-loudnorm.<ext> beside it
    loudness.py VIDEO --fix --in-place        # replaces VIDEO (only after the user's yes)
    loudness.py VIDEO --fix --out OUT.mp4
    options: --target -14 (LUFS)  --tol 1.0  --force (normalize a loud file too)  --json

Why: YouTube plays everything at about -14 LUFS (integrated loudness, the
average perceived level). It turns louder uploads DOWN, but never turns a quiet
one up, so a quiet video sounds weak next to the one before it. Peaks above
-1 dBTP (true peak, the real top of the waveform) distort after YouTube's
re-encode.

Verdicts:  pass   target +/- tol, true peak <= -1 dBTP     -> nothing to do
           loud   louder than target + tol, peaks fine     -> nothing to do (YouTube turns it down)
           quiet  quieter than target - tol                -> fix
           peaks  true peak above -1 dBTP                  -> fix

The fix: pass 1 measures with loudnorm. When a plain gain change reaches the
target with the peaks still under the ceiling, that is all it does (linear: like
pushing one fader, the mix keeps its dynamics). Otherwise pass 2 runs loudnorm
with the measured values, which reaches the target with gentle dynamic
compression and a true-peak limiter. The ceiling is -1.5 dBTP because AAC
encoding overshoots a little. Audio becomes AAC 256 kb/s 48 kHz; metadata and
chapters are kept. The result is measured again; exit 1 if it still fails.

Machine-readable results: --json (stdout). Exit 0 every file passes (after any
fix), 1 otherwise, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402

TP_MAX, TP_FIX = -1.0, -1.5


def measure(path: str) -> dict:
    """Integrated loudness, loudness range and true peak of the first audio stream (ebur128)."""
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-nostats", "-i", path, "-vn", "-map", "0:a:0",
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):] if "Summary:" in r.stderr else ""
    if r.returncode or not tail:
        sys.exit(f"{path}: could not measure the audio (no audio stream?)\n{r.stderr[-300:]}")

    def num(key):
        m = re.search(key + r":\s+(-?[\d.]+|-inf)", tail)
        return float(m.group(1).replace("-inf", "-120")) if m else -120.0
    return {"lufs": num("I"), "lra": num("LRA"), "true_peak": num("Peak")}


def verdict(m: dict, target: float, tol: float) -> str:
    if m["lufs"] < target - tol:
        return "quiet"
    if m["true_peak"] > TP_MAX:
        return "peaks"
    return "loud" if m["lufs"] > target + tol else "pass"


def _loudnorm_json(stderr: str) -> dict:
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end < start:
        sys.exit("loudnorm printed no measurement:\n" + stderr[-400:])
    return json.loads(stderr[start:end + 1])


def normalized_wav(src: str, target: float, td: str) -> tuple:
    """Two-pass loudnorm of src's first audio stream -> (48 kHz 24-bit WAV path, pass-2 report)."""
    ff = media.ffmpeg()
    first = subprocess.run([ff, "-hide_banner", "-nostats", "-i", src, "-vn", "-map", "0:a:0", "-af",
                            f"loudnorm=I={target}:TP={TP_FIX}:LRA=11:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True)
    if first.returncode:
        sys.exit("loudnorm pass 1 failed:\n" + first.stderr[-400:])
    m = _loudnorm_json(first.stderr)
    out = os.path.join(td, "norm.wav")
    gain = target - float(m["input_i"])
    if float(m["input_tp"]) + gain <= TP_FIX:
        # Enough headroom: one plain gain change is exact and keeps every dynamic of the mix.
        r = subprocess.run([ff, "-hide_banner", "-nostats", "-y", "-i", src, "-vn", "-map", "0:a:0",
                            "-af", f"volume={gain:.2f}dB", "-ar", "48000", "-c:a", "pcm_s24le", out],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit("gain pass failed:\n" + r.stderr[-400:])
        return out, {"normalization_type": f"linear, {gain:+.1f} dB"}
    # Not enough headroom: second loudnorm pass with the measured values (true-peak limited).
    # Its linear mode needs a target range at least as wide as the input's; older ffmpeg caps LRA at 20.
    lra = min(20.0, max(11.0, float(m["input_lra"]) + 1.0))
    chain = (f"loudnorm=I={target}:TP={TP_FIX}:LRA={lra:.1f}"
             f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
             f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    second = subprocess.run([ff, "-hide_banner", "-nostats", "-y", "-i", src, "-vn", "-map", "0:a:0",
                             "-af", chain, "-ar", "48000", "-c:a", "pcm_s24le", out], capture_output=True, text=True)
    if second.returncode:
        sys.exit("loudnorm pass 2 failed:\n" + second.stderr[-400:])
    return out, _loudnorm_json(second.stderr)


def fix(src: str, dest: str, target: float) -> dict:
    """Normalize src's audio into dest with the video stream copied. Returns the pass-2 report."""
    ext = os.path.splitext(dest)[1] or ".mp4"
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(dest)), prefix=".loudness-") as td:
        wav, report = normalized_wav(src, target, td)
        tmp = os.path.join(td, "out" + ext)
        info = media.probe(src)
        tag = ["-tag:v", "hvc1"] if info.get("vcodec") == "hevc" and ext.lower() in (".mp4", ".mov") else []
        r = subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-i", src, "-i", wav,
                            "-map", "0:v?", "-map", "1:a", "-map_metadata", "0", "-map_chapters", "0",
                            "-c:v", "copy", *tag, "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
                            "-movflags", "+faststart", tmp], capture_output=True, text=True)
        if r.returncode:
            sys.exit("mux failed:\n" + r.stderr[-400:])
        os.replace(tmp, dest)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--fix", action="store_true", help="normalize files that fail (or all, with --force)")
    ap.add_argument("--in-place", action="store_true", help="replace the original file (ask the user first)")
    ap.add_argument("--out", help="output path (one video only)")
    ap.add_argument("--target", type=float, default=-14.0, help="integrated loudness target in LUFS (default -14)")
    ap.add_argument("--tol", type=float, default=1.0)
    ap.add_argument("--force", action="store_true", help="with --fix: normalize even a passing/loud file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.out and len(a.videos) > 1:
        ap.error("--out takes one video")
    results, ok = [], True
    for v in a.videos:
        if not os.path.isfile(v):
            sys.exit(f"not a file: {v}")
        m = measure(v)
        vd = verdict(m, a.target, a.tol)
        res = {"file": os.path.abspath(v), **m, "verdict": vd}
        if a.fix and (vd in ("quiet", "peaks") or a.force):
            stem, ext = os.path.splitext(v)
            dest = a.out or (v if a.in_place else f"{stem}-loudnorm{ext}")
            report = fix(v, dest, a.target)
            after = measure(dest)
            res.update(fixed=os.path.abspath(dest), mode=report.get("normalization_type"), after=after,
                       verdict_after=verdict(after, a.target, a.tol))
        good = res.get("verdict_after", vd) in ("pass", "loud")
        ok &= good
        results.append(res)
        if not a.json:
            line = f"{vd:5s}  {m['lufs']:6.1f} LUFS  TP {m['true_peak']:5.1f} dBTP  LRA {m['lra']:4.1f}  {v}"
            if "after" in res:
                line += (f"\n  fixed ({res['mode']}) -> {res['after']['lufs']:.1f} LUFS, "
                         f"TP {res['after']['true_peak']:.1f} dBTP ({res['verdict_after']})  {res['fixed']}")
            elif vd in ("quiet", "peaks"):
                line += "\n  needs a fix: run again with --fix"
            elif vd == "loud":
                line += "\n  louder than YouTube's reference: YouTube turns it down, nothing to do"
            print(line)
    if a.json:
        print(json.dumps(results, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
