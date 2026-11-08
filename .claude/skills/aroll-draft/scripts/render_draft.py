#!/usr/bin/env python3
"""Render a TimeBolt-format cut list to a quick preview MP4 of the first cut.

Each keep becomes a trim/atrim pair with 15 ms audio fades (so cuts never
click); everything is concatenated, scaled so the short side is --height
(default settings render.draft_height, 1080) and encoded with the hardware H.264
encoder vidkit picks (VideoToolbox on a Mac, NVENC on NVIDIA, else libx264).
HEVC sources decode on the GPU where that is faster. The filter graph goes
through a script file, so hundreds of clips never hit argv limits. The output
duration is checked against the cut list.

The preview goes to the project's drafts folder (settings.drafts_dir), never
next to the camera originals.

Usage:
  python3 render_draft.py <cuts.tb.json> <media-file> [-o draft.mp4] [--height 1080]

Summary JSON on stdout, ffmpeg logs on stderr.

Exit codes: 0 ok, 2 usage/input error, 4 a setting is missing, 5 render failed
or the duration drifted.
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
from vidkit import media, settings  # noqa: E402

AFADE = 0.015


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def build_filter_script(keeps, height, has_audio=True):
    lines = []
    for i, k in enumerate(keeps):
        s, e = k["start"], k["start"] + k["duration"]
        fade_out = max(0.0, k["duration"] - AFADE)
        lines.append(f"[0:v]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS[v{i}];")
        if has_audio:
            lines.append(
                f"[0:a]atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={AFADE},afade=t=out:st={fade_out:.6f}:d={AFADE}[a{i}];")
    n = len(keeps)
    if has_audio:
        pairs = "".join(f"[v{i}][a{i}]" for i in range(n))
        lines.append(f"{pairs}concat=n={n}:v=1:a=1[vc][aout];")
    else:
        lines.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc];")
    # short side = height (works for landscape and vertical takes), even dimensions
    lines.append(f"[vc]scale='if(gte(iw,ih),-2,{height})':'if(gte(iw,ih),{height},-2)',format=yuv420p[vout]")
    return "\n".join(lines)


def ffmpeg_major():
    try:
        out = subprocess.run([media.ffmpeg(), "-version"], capture_output=True, text=True).stdout
        return int(re.match(r"ffmpeg version n?(\d+)", out).group(1))
    except Exception:
        return 0


def filter_script_args(script_path):
    # ffmpeg 7 added "-/option file" and deprecated -filter_complex_script; 8 removed it
    if ffmpeg_major() >= 7:
        return ["-/filter_complex", script_path]
    return ["-filter_complex_script", script_path]


def default_output(media_path):
    return settings.drafts_dir(media_path) / f"{Path(media_path).stem}.aroll_draft.mp4"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cutlist")
    p.add_argument("media")
    p.add_argument("-o", "--output", help="default: <drafts folder>/<stem>.aroll_draft.mp4")
    p.add_argument("--height", type=int, help="short side in pixels (default settings render.draft_height or 1080)")
    args = p.parse_args()

    with open(args.cutlist, encoding="utf-8") as f:
        ops = json.load(f)
    keeps = [o for o in ops if o["operation"] == "keep"]
    if not keeps:
        die("cut list has no keep ops")
    expected = sum(k["duration"] for k in keeps)
    info = media.probe(args.media)
    if not info["has_video"]:
        die(f"{args.media} has no video stream")
    try:
        height = args.height or int(settings.get("render.draft_height", default=1080))
        out = Path(args.output) if args.output else default_output(args.media)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    out.parent.mkdir(parents=True, exist_ok=True)

    script = build_filter_script(keeps, height, info["has_audio"])
    tmp = tempfile.NamedTemporaryFile("w", suffix=".filter", delete=False, encoding="utf-8")
    tmp.write(script)
    tmp.close()
    vargs = media.h264_args(quality="draft", height=height)
    cmd = [media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(args.media)] + filter_script_args(tmp.name)
    cmd += ["-map", "[vout]"] + (["-map", "[aout]"] if info["has_audio"] else [])
    cmd += vargs
    if info["has_audio"]:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-movflags", "+faststart", str(out)]
    try:
        rc = media.run(cmd, stdout=sys.stderr, stderr=sys.stderr).returncode
    finally:
        os.unlink(tmp.name)
    if rc != 0:
        die("ffmpeg render failed (see the log above)", 5)

    actual = media.duration(out)
    drift = abs(actual - expected)
    tolerance = max(0.5, 0.025 * len(keeps))  # every trim quantizes to frame / AAC-frame boundaries
    if drift > tolerance:
        die(f"output duration {actual:.2f}s drifts {drift:.2f}s from the cut list "
            f"({expected:.2f}s), tolerance {tolerance:.2f}s", 5)
    print(json.dumps({"output": str(out), "encoder": vargs[1], "clips": len(keeps),
                      "expected_duration_s": round(expected, 2), "actual_duration_s": round(actual, 2)}))


if __name__ == "__main__":
    main()
