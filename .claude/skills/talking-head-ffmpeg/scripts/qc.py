#!/usr/bin/env python3
"""Measured QC of a render: length, frame count, black frames, loudness, true peak, long silences.

    qc.py VIDEO [--recipe <work>/recipe_vN.json] [--lufs -14] [--allow-black]

Numbers, not impressions: a draft goes to the user only after this passes. render_recipe.py runs it after every render.

  ERROR  frame count differs from the recipe's timeline (a dropped or doubled frame somewhere: sound and picture will
         drift), black frames (>= 0.1 s, unless --allow-black: an intentional fade), integrated loudness more than
         1.5 LU off the target, true peak above -1.0 dBTP (clips on some players after YouTube's re-encode);
  WARN   a silence over 2.5 s (a dead stretch, or a keep whose sound went missing), duration off the recipe by more
         than one frame.

Prints {"qc": {...}, "errors": [...], "warnings": [...]} on stdout; exit 1 on any ERROR. For the release master,
the youtube-release skill does the final loudness check.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402


def count_frames(path):
    out = subprocess.run([C.ffprobe(), "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return int(out.stdout.strip().split(",")[0])
    except ValueError:
        return 0


def measure(path, lufs=-14.0, want_frames=None, fps=None, allow_black=False):
    info = C.media.probe(path)
    got = count_frames(path)
    log = subprocess.run([C.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
                          "-vf", "blackdetect=d=0.1:pix_th=0.10",
                          "-af", "silencedetect=n=-50dB:d=2.5,ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    blacks = [(float(s), float(e)) for s, e in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    sil_s = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    sil_e = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", log)]
    silences = [(round(s, 2), round(e, 2)) for s, e in zip(sil_s, sil_e + [info["duration"] or 0] * (len(sil_s) - len(sil_e)))]
    summ = log[log.rfind("Summary:"):] if "Summary:" in log else ""
    I = re.search(r"I:\s+(-?[\d.]+) LUFS", summ)
    LRA = re.search(r"LRA:\s+(-?[\d.]+) LU", summ)
    TP = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ)
    qc = {"file": str(path), "duration_s": round(info["duration"] or 0, 3), "frames": got,
          "size": f"{info['width']}x{info['height']}", "fps": info["fps"], "video": info["vcodec"],
          "audio": info["acodec"], "lufs": float(I.group(1)) if I else None, "lra": float(LRA.group(1)) if LRA else None,
          "true_peak_dbtp": float(TP.group(1)) if TP else None, "black": blacks, "silences": silences}
    errs, warns = [], []
    if want_frames is not None:
        qc["want_frames"] = want_frames
        if got != want_frames:
            errs.append(f"frame count {got} != timeline {want_frames}")
        if fps and abs((info["duration"] or 0) - want_frames / fps) > 1.5 / fps:
            warns.append(f"duration {info['duration']:.3f}s vs timeline {want_frames / fps:.3f}s")
    if not info["has_audio"]:
        errs.append("no audio stream")
    elif qc["lufs"] is None:
        errs.append("could not measure loudness")
    else:
        if abs(qc["lufs"] - lufs) > 1.5:
            errs.append(f"loudness {qc['lufs']} LUFS, target {lufs}")
        if qc["true_peak_dbtp"] is not None and qc["true_peak_dbtp"] > -1.0:
            errs.append(f"true peak {qc['true_peak_dbtp']} dBTP > -1.0")
    for s, e in blacks:
        (warns if allow_black else errs).append(f"black frames {s:.2f}-{e:.2f}s")
    for s, e in silences:
        warns.append(f"silence {C.tc(s)}-{C.tc(e)} ({e - s:.1f}s)")
    return qc, errs, warns


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--recipe", help="compare the frame count with this recipe's timeline")
    ap.add_argument("--lufs", type=float, help="loudness target (default: the recipe's, else -14)")
    ap.add_argument("--allow-black", action="store_true", help="black frames are intentional (a fade): warn only")
    a = ap.parse_args()
    want = fps = None
    lufs = a.lufs
    if a.recipe:
        import recipe as R
        r = C.read_json(a.recipe)
        want, fps = R.total_frames(r), float(R.fps_of(r))
        lufs = lufs if lufs is not None else float(r.get("lufs", -14))
    qc, errs, warns = measure(a.video, -14.0 if lufs is None else lufs, want, fps, a.allow_black)
    print(json.dumps({"qc": qc, "errors": errs, "warnings": warns}, indent=1))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
