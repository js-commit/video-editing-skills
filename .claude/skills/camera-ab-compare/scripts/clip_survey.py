#!/usr/bin/env python3
"""Survey source clips: contact sheets + the best usable window in each.

Two jobs that always come up before pairing, and are tedious by hand:

1. `sheets` - one 4x3 contact sheet per clip with timestamps burned in. This
   is how lens order gets settled (a wide/ultra-wide/tele run is obvious at a
   glance) and how hands, walk-ins and walk-outs get spotted.

2. `windows` - pick the best N seconds of each clip, for two shot kinds:

   --mode talking-head : subject seated, still, and NOT talking. Scored on
       audio RMS (speech) + deviation from the clip's median frame (walking
       in/out). Both normalised per clip, so it does not matter how loud or
       how contrasty the take is.

   --mode static-scene : a locked-off or handheld product/flat-lay shot that
       must be free of hands. Scored on deviation from the median frame only.

       Do NOT reach for skin-tone detection here. A wood tabletop sits
       squarely inside every standard YCbCr skin gate - on a real
       studio shoot the "skin" fraction of a hands-free flat lay was 59%,
       so the hand was invisible against it.

       Frame motion alone is also not enough if the shot is HANDHELD: the
       camera drifts constantly, so an absolute threshold marks everything
       dirty. What separates a hand event from drift is magnitude - drift
       sits near 0.1-0.2 of the clip's peak deviation, a hand crossing the
       frame spikes to 0.8-1.0. `--runs` lists the contiguous runs under
       --thresh so a short clean stretch can be found even when no window of
       the requested length exists.

Windows are a starting point, not a verdict: always extract the chosen
start/mid/end frames and look before building anything on them.

Usage:
  clip_survey.py sheets  OUTDIR CLIP [CLIP ...]
  clip_survey.py windows --mode talking-head [--length 7] CLIP [CLIP ...]
  clip_survey.py windows --mode static-scene --runs [--thresh 0.3] CLIP ...
"""
import argparse
import functools
import json
import os
import subprocess
import sys

try:
    import numpy as np
except ImportError:
    sys.exit("this script needs numpy: python3 -m pip install numpy")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools"))
from vidkit import media   # media.run: hardware decode for HEVC inputs where it is faster

FPS = 4          # analysis sampling rate
THUMB_W = 96     # tiny frames carry plenty of motion energy


@functools.lru_cache(maxsize=None)
def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    st = j["streams"][0]
    return st["width"], st["height"], float(j["format"]["duration"])


def gray_samples(path):
    """Whole clip at FPS as tiny grayscale frames -> (n, h, w) float32."""
    w, h, _ = probe(path)
    th = max(2, round(THUMB_W * h / w / 2) * 2)
    out = media.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf",
         f"fps={FPS},scale={THUMB_W}:{th},format=gray",
         "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    n = len(out) // (THUMB_W * th)
    return np.frombuffer(out[:n * THUMB_W * th],
                         dtype=np.uint8).reshape(n, th, THUMB_W).astype(np.float32)


def audio_rms(path, n):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1",
         "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    if not out:
        return np.zeros(n, dtype=np.float32)
    a = np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0
    per = max(1, len(a) // n)
    a = a[:per * n].reshape(n, per)
    return np.sqrt((a ** 2).mean(axis=1))


def motion(frames):
    return np.abs(frames - np.median(frames, axis=0)).mean(axis=(1, 2))


def norm(x):
    return x / (x.max() or 1.0)


def score_clip(path, mode):
    f = gray_samples(path)
    mot = norm(motion(f))
    if mode == "talking-head":
        return norm(audio_rms(path, len(f))) + mot
    return mot


def best_window(score, want_s, pad_s=0.3):
    """Lowest-scoring window, penalising the in-window PEAK: one bad frame
    (a hand, a walk-out) has to disqualify a window, not be averaged away."""
    k = int(round(want_s * FPS))
    pad = int(round(pad_s * FPS))
    if len(score) - 2 * pad < k:
        return None, None
    s = score[pad:len(score) - pad]
    win = np.lib.stride_tricks.sliding_window_view(s, k)
    i = int(np.argmin(win.mean(axis=1) + 2.0 * win.max(axis=1)))
    return (pad + i) / FPS, float(win[i].mean())


def clean_runs(score, thresh, min_s=1.0):
    ok = score < thresh
    out, i = [], 0
    while i < len(ok):
        if ok[i]:
            j = i
            while j < len(ok) and ok[j]:
                j += 1
            if (j - i) / FPS >= min_s:
                out.append((i / FPS, j / FPS, (j - i) / FPS))
            i = j
        else:
            i += 1
    return out


def cmd_sheets(args):
    os.makedirs(args.outdir, exist_ok=True)
    for path in args.clips:
        b = os.path.splitext(os.path.basename(path))[0]
        _w, _h, dur = probe(path)
        n = 12
        times = [round(0.3 + i * (dur - 0.9) / (n - 1), 2) for i in range(n)]
        # One ffmpeg per clip: 12 input-seeks into the same file, each frame
        # stamped then tiled - no temp PNGs, no 13 sequential spawns.
        cmd = ["ffmpeg", "-v", "error"]
        for t in times:
            cmd += ["-ss", str(t), "-i", path]
        # trim to ONE frame per branch: concat would otherwise drain every
        # frame of input 0 (from its seek point to EOF) before touching
        # input 1, and the tile ends up 12 consecutive frames of one moment
        fc = ";".join(
            f"[{i}:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale=480:-2,"
            f"drawtext=font=Helvetica Neue:text='{t:g}s':"
            "fontsize=30:fontcolor=yellow:box=1:boxcolor=black@0.7:"
            f"boxborderw=8:x=10:y=10[t{i}]" for i, t in enumerate(times))
        fc += (";" + "".join(f"[t{i}]" for i in range(n))
               + f"concat=n={n}:v=1:a=0,tile=4x3[sheet]")
        media.run(cmd + ["-filter_complex", fc, "-map", "[sheet]",
                              "-frames:v", "1", "-q:v", "3",
                              "-y", f"{args.outdir}/{b}.jpg"], check=True)
        print(f"{args.outdir}/{b}.jpg   ({dur:.1f}s)")
    return 0


def cmd_windows(args):
    result = {}
    for path in args.clips:
        s = score_clip(path, args.mode)
        _w, _h, dur = probe(path)
        name = os.path.basename(path)
        start, val = best_window(s, args.length)
        result[name] = {"duration": round(dur, 2), "start": start,
                        "score": round(val, 4) if val is not None else None}
        print(f"{name}  dur={dur:6.1f}  best {args.length}s @ {start}  "
              f"score={val if val is None else round(val, 4)}")
        prof = " ".join(f"{i // FPS}:{v:.2f}"
                        for i, v in list(enumerate(s))[::FPS * 2])
        print(f"    profile  {prof}")
        if args.runs:
            runs = clean_runs(s, args.thresh)
            result[name]["clean_runs"] = [[round(a, 2), round(b, 2), round(d, 2)]
                                          for a, b, d in runs]
            for a, b, d in sorted(runs, key=lambda r: -r[2]):
                print(f"    clean {a:6.2f} -> {b:6.2f}  ({d:.2f}s)")
            if not runs:
                print(f"    no run under thresh={args.thresh}; raise it or "
                      f"accept that this take is dirty throughout")
    if args.json:
        json.dump(result, open(args.json, "w"), indent=2)
        print(f"\n-> {args.json}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheets")
    s.add_argument("outdir")
    s.add_argument("clips", nargs="+")
    w = sub.add_parser("windows")
    w.add_argument("clips", nargs="+")
    w.add_argument("--mode", choices=("talking-head", "static-scene"),
                   required=True)
    w.add_argument("--length", type=float, default=7.0)
    w.add_argument("--runs", action="store_true",
                   help="also list contiguous runs under --thresh")
    w.add_argument("--thresh", type=float, default=0.3,
                   help="clean-run cutoff, fraction of the clip's peak "
                        "deviation (0.3 separates handheld drift from hands)")
    w.add_argument("--json", help="write results here")
    args = ap.parse_args()
    return {"sheets": cmd_sheets, "windows": cmd_windows}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
