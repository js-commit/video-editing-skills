#!/usr/bin/env python3
"""Shorten a text-to-speech service's artificial pauses in a generated VO clip.

TTS output paces like an audiobook; YouTube VO wants tighter gaps. Every
silence longer than --max-pause is cut down to --keep seconds (cut point
sits inside the silence, so it's inaudible — no jump-cut feel as long as
--keep stays a natural breath). Output is PCM WAV next to the input
(<stem>.tight.wav): decode once, cut, no second lossy encode — and the
raw download stays untouched for reference.

Usage: tighten_vo.py input.mp3 [-o out.wav] [--max-pause 0.35]
                     [--keep 0.25] [--db -35]

Prints JSON: pauses found/shortened, seconds removed, before/after
duration, output path. Defaults: -35 dB catches the breathy TTS gaps that
-40 misses; ~0.4 s pauses read as too long for YouTube pacing, and 0.25 s
is a natural breath.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402  (finds ffmpeg/ffprobe, or says how to install them)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"{cmd[0]} failed: {p.stderr.strip()[-500:]}")
    return p


def probe_duration(path):
    p = run([media.ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)])
    return float(p.stdout.strip())


def detect_silences(path, db, min_d):
    p = subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", str(path),
         "-af", f"silencedetect=n={db}dB:d={min_d}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(m) for m in
              re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    return list(zip(starts, ends))  # trailing silence may lack an end line


def main():
    args = sys.argv[1:]
    opts = {"--max-pause": 0.35, "--keep": 0.25, "--db": -35.0}
    out = None
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            opts[flag] = float(args[i + 1])
            del args[i:i + 2]
    if "-o" in args:
        i = args.index("-o")
        out = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    src = Path(args[0])
    max_pause, keep, db = opts["--max-pause"], opts["--keep"], opts["--db"]
    if out is None:
        out = src.with_suffix(".tight.wav")

    total = probe_duration(src)
    silences = detect_silences(src, db, keep)
    long_pauses = [(s, e) for s, e in silences if e - s > max_pause]

    if not long_pauses:
        run([media.ffmpeg(), "-y", "-hide_banner", "-i", str(src),
             "-c:a", "pcm_s16le", str(out)])
        print(json.dumps({"output": str(out), "pauses_found": len(silences),
                          "pauses_shortened": 0, "removed_s": 0.0,
                          "duration_s": round(total, 2)}))
        return

    # keep [cursor .. silence_start + keep], then jump to silence_end
    keeps, cursor = [], 0.0
    for s, e in long_pauses:
        keeps.append((cursor, min(s + keep, e)))
        cursor = e
    if cursor < total:
        keeps.append((cursor, total))

    parts = "".join(
        f"[0:a]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS[a{i}];"
        for i, (a, b) in enumerate(keeps))
    labels = "".join(f"[a{i}]" for i in range(len(keeps)))
    fc = f"{parts}{labels}concat=n={len(keeps)}:v=0:a=1[out]"
    run([media.ffmpeg(), "-y", "-hide_banner", "-i", str(src),
         "-filter_complex", fc, "-map", "[out]", "-c:a", "pcm_s16le",
         str(out)])

    new_total = probe_duration(out)
    print(json.dumps({
        "output": str(out),
        "pauses_found": len(silences),
        "pauses_shortened": len(long_pauses),
        "shortened": [{"at_s": round(s, 2), "was_s": round(e - s, 2),
                       "now_s": round(min(keep, e - s), 2)}
                      for s, e in long_pauses],
        "removed_s": round(total - new_total, 2),
        "duration_before_s": round(total, 2),
        "duration_s": round(new_total, 2)}, indent=2))


if __name__ == "__main__":
    main()
