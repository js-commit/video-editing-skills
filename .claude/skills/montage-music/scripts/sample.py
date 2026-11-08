#!/usr/bin/env python3
"""Level-matched listening samples, so the user picks a cue by ear before anything is built.

  sample.py TRACK --in 12.0 --len 40 --out DIR [--label "Part 2 - A"]
  sample.py TRACK --end-at 118.0 --len 30 --out DIR       the last 30 s before a natural ending

Writes "<label> - <track stem>.mp3": exactly the stretch that would play under that part,
loudness-matched (-16 LUFS) so a louder master does not win by volume, with a 2 s fade-out.
Prints the sample path. Make two candidates per part and say, for each, the time range,
what is on screen there and the mood it sells.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("track")
    ap.add_argument("--in", dest="in_s", type=float)
    ap.add_argument("--end-at", type=float)
    ap.add_argument("--len", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="sample")
    a = ap.parse_args()
    if (a.in_s is None) == (a.end_at is None):
        sys.exit("give exactly one of --in or --end-at")
    start = a.in_s if a.in_s is not None else max(0.0, a.end_at - a.len)
    out = Path(a.out).expanduser() / f"{a.label} - {Path(a.track).stem}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    fo = 2.0 if a.in_s is not None else 0.3
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-t", f"{a.len:.3f}",
                        "-i", a.track, "-vn", "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={max(0.0, a.len - fo):.3f}:d={fo}",
                        "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "2", str(out)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-500:])
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
