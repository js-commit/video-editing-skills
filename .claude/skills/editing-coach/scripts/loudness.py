#!/usr/bin/env python3
"""Measure how loud a video or audio file is, for audio feedback.

    loudness.py <media> [--target -14]

Uses ffmpeg's loudnorm filter in measure-only mode (EBU R128 / ITU BS.1770).
Prints JSON: integrated loudness (LUFS), true peak (dBTP), loudness range
(LU), plus a plain-language verdict against the target (YouTube plays music
and speech at about -14 LUFS and turns louder uploads down) and a -1 dBTP
peak ceiling. Exit 0 ok, 1 ffmpeg failure, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402


def measure(path: Path) -> dict:
    cmd = [media.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-vn",
           "-af", "loudnorm=print_format=json", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if r.returncode != 0 or not m:
        sys.stderr.write(r.stderr[-2000:])
        sys.exit(1)
    return json.loads(m.group(0))


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Integrated loudness, true peak and loudness range.")
    ap.add_argument("media")
    ap.add_argument("--target", type=float, default=-14.0, help="target integrated loudness in LUFS")
    args = ap.parse_args(argv)
    path = Path(args.media).expanduser().resolve()
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    if not media.probe(path)["has_audio"]:
        print(f"{path} has no audio stream", file=sys.stderr)
        return 2
    raw = measure(path)
    i, tp, lra = float(raw["input_i"]), float(raw["input_tp"]), float(raw["input_lra"])
    diff = i - args.target
    if abs(diff) <= 1:
        verdict = f"on target ({i:.1f} LUFS)"
    elif diff < 0:
        verdict = f"{-diff:.1f} dB quieter than {args.target:g} LUFS: it will play quieter than most videos"
    else:
        verdict = f"{diff:.1f} dB louder than {args.target:g} LUFS: YouTube will turn it down; no harm, but no gain"
    peak = ("peaks are safe" if tp <= -1.0
            else f"true peak {tp:.1f} dBTP is above -1 dBTP: risk of distortion after YouTube's encode")
    print(json.dumps({
        "file": str(path), "integrated_lufs": i, "true_peak_dbtp": tp, "loudness_range_lu": lra,
        "target_lufs": args.target, "verdict": verdict, "peaks": peak,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
