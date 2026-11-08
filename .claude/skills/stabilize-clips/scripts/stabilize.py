#!/usr/bin/env python3
"""Stabilize shaky clips with ffmpeg's vid.stab (two passes), inside a fixed crop budget.

  stabilize.py IN -o OUT                         whole clip
  stabilize.py IN -o OUT --range 12.0 17.5       one stretch (+0.5 s handles each side)
  stabilize.py --analyze IN [IN ...]             measure shake only, render nothing
  stabilize.py --check                           does this ffmpeg have vid.stab?

How it works
  1. vidstabdetect measures how the camera moved between frames (on a copy no wider than
     --detect-width, so 4K stays fast; the motion file is scaled back up for pass 2).
  2. The shake score is the frame-to-frame jitter that is left after removing the slow
     camera path (pans and walks are kept), in pixels per frame at 960 px wide.
     Below --min-shake the clip is already smooth: skipped (the phone did the job).
  3. vidstabtransform smooths the path over --smooth-s seconds, zooms in by --max-zoom
     percent and never shifts or rotates more than that zoom can hide, so no black edges.
  4. The result is measured again. If the jitter did not drop by at least --min-gain
     (default 15 %), the render is deleted and the source stays ("reverted"): a subject that
     fills the frame, water or darkness fool the estimator, and then the honest answer is
     the original.

Output: OUT (H.264 + the source's audio) and OUT.stab.json with every number. One JSON line
per item on stdout: status (kept | reverted | skip | error), reason, shake before/after,
gain, zoom, source and source_in_s (where OUT starts in the source, for cut lists).

Flags worth knowing: --force stabilizes a clip the score calls smooth (the user saw shake);
--keep-all keeps a render the gate would revert (for a side-by-side look);
--engine deshake uses ffmpeg's built-in deshake when vid.stab is missing (weaker, unmeasured);
--replace overwrites an existing OUT (without it an existing OUT is an error; the source never is).

Exit codes: 0 ok (including skip/reverted), 1 failure, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402

ANALYSIS_W = 960          # shake numbers are reported in pixels at this width
HANDLE_S = 0.5

VIDSTAB_HELP = """This ffmpeg was built without vid.stab (the vidstabdetect / vidstabtransform filters).
Builds that include it:
  macOS:   Homebrew's full build:   brew install ffmpeg-full
           (the plain `ffmpeg` formula may leave vid.stab out; ffmpeg-full is keg-only,
           so put $(brew --prefix ffmpeg-full)/bin first on PATH, or call it by full path)
  Windows: a "full" GPL build, e.g. the gyan.dev full build:  winget install --id Gyan.FFmpeg
  Linux:   most distro packages are built with --enable-libvidstab (apt install ffmpeg);
           or a static GPL build.
Check any ffmpeg with:  ffmpeg -hide_banner -filters | grep vidstab
Ask the user before installing anything. Meanwhile --engine deshake works with any ffmpeg
(weaker, no before/after measurement)."""


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def has_filter(name: str) -> bool:
    out = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return re.search(rf"\s{name}\s", out) is not None


def has_vidstab() -> bool:
    return has_filter("vidstabdetect") and has_filter("vidstabtransform")


def run(cmd: list) -> subprocess.CompletedProcess:
    r = media.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-600:]}")
    return r


def seek_args(ss: float, dur: float | None) -> list:
    a = ["-ss", f"{ss:.3f}"] if ss > 0 else []
    return a + (["-t", f"{dur:.3f}"] if dur else [])


def ff_escape(path: str) -> str:
    """A path as a filter option value (vidstab's result= / input=)."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ---------------------------------------------------------------- motion file (.trf)

LM = re.compile(r"\(LM (-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) ([-\d.e]+) ([-\d.e]+)\)")


def parse_trf(path: str) -> list:
    """Per frame: list of local motions (vx, vy, fx, fy, size, contrast, match)."""
    frames = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("Frame"):
                frames.append([tuple(float(x) for x in m.groups()) for m in LM.finditer(line)])
    return frames


def scale_trf(src: str, dst: str, s: float) -> None:
    """Scale a vid.stab ASCII motion file measured on a smaller copy up to full size: the
    motion vector, field position and field size are pixels, contrast/match are not."""
    def fix(m):
        v = [int(round(int(m.group(i)) * s)) for i in range(1, 6)]
        return f"(LM {v[0]} {v[1]} {v[2]} {v[3]} {v[4]} {m.group(6)} {m.group(7)})"
    with open(src, encoding="utf-8", errors="replace") as f, open(dst, "w", encoding="utf-8") as g:
        for line in f:
            g.write(LM.sub(fix, line) if line.startswith("Frame") else line)


def global_motion(frames: list) -> list:
    """Camera translation per frame (median of the local motions), None where nothing tracked."""
    out = []
    for lm in frames:
        if len(lm) < 3:
            out.append(None)
            continue
        out.append((statistics.median(x[0] for x in lm), statistics.median(x[1] for x in lm)))
    return out


def shake_metrics(motion: list, fps: float, to_960: float) -> dict:
    """Jitter = per-frame motion minus its moving average (fps/6 frames), so a pan or a walk
    is not shake. 'worst_s' = 90th percentile of 1 s windows, so one bad stretch counts."""
    n = len(motion)
    tracked = [m for m in motion if m is not None]
    if n < 4 or len(tracked) < 0.6 * n:
        return {"tracked": round(len(tracked) / max(1, n), 2), "mean": None, "worst_s": None, "pan": None}
    filled, last = [], (0.0, 0.0)
    for m in motion:
        last = m if m is not None else last
        filled.append(last)
    half = max(1, int(round(fps / 12)))
    jit = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        ax = sum(p[0] for p in filled[lo:hi]) / (hi - lo)
        ay = sum(p[1] for p in filled[lo:hi]) / (hi - lo)
        jit.append(math.hypot(filled[i][0] - ax, filled[i][1] - ay) * to_960)
    win = max(1, int(round(fps)))
    secs = sorted(sum(jit[i:i + win]) / len(jit[i:i + win]) for i in range(0, n, win))
    pan = sum(math.hypot(*p) for p in filled) / n * to_960
    return {"tracked": round(len(tracked) / n, 2), "mean": round(sum(jit) / n, 3),
            "worst_s": round(secs[min(len(secs) - 1, int(0.9 * len(secs)))], 3), "pan": round(pan, 2)}


def detect(path: str, ss: float, dur: float | None, width: int, src_w: int, trf: str, shakiness: int) -> float:
    """Pass 1 on a copy at most `width` wide. Returns the scale factor full-size / detect-size."""
    dw = min(width, src_w) // 2 * 2
    vf = (f"scale={dw}:-2," if dw < src_w else "") + \
        f"vidstabdetect=shakiness={shakiness}:accuracy=15:stepsize=6:mincontrast=0.2:fileformat=ascii:result='{ff_escape(trf)}'"
    run([media.ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-y", *seek_args(ss, None), "-i", path,
         *(["-t", f"{dur:.3f}"] if dur else []), "-an", "-vf", vf, "-fps_mode", "passthrough", "-f", "null", "-"])
    return src_w / dw


def measure(path: str, ss: float, dur: float | None, info: dict, args, keep_trf: str | None = None) -> tuple:
    w = info["width"]
    fps = info["fps_float"] or 30.0
    with tempfile.TemporaryDirectory() as td:
        trf = os.path.join(td, "m.trf")
        scale = detect(path, ss, dur, args.detect_width, w, trf, args.shakiness)
        frames = parse_trf(trf)
        dw = w / scale
        m = shake_metrics(global_motion(frames), fps, ANALYSIS_W / dw)
        if keep_trf:
            if abs(scale - 1) > 1e-3:
                scale_trf(trf, keep_trf, scale)
            else:
                os.replace(trf, keep_trf)
    return m, scale


# ---------------------------------------------------------------- one item

def display_size(info: dict) -> tuple:
    w, h = info["width"], info["height"]
    return (h, w) if info.get("rotation", 0) % 180 else (w, h)


def stabilize_one(src: str, out: str | None, rng: tuple | None, args) -> dict:
    t0 = time.time()
    info = media.probe(src)
    if not info["has_video"]:
        return {"status": "error", "reason": "no video stream", "source": src}
    W, H = display_size(info)
    info = dict(info, width=W, height=H)          # ffmpeg auto-rotates on decode
    total = info["duration"] or 0.0
    if rng:
        a, b = rng
        if not (0 <= a < b):
            return {"status": "error", "reason": f"bad range {a}-{b}", "source": src}
        ss = max(0.0, a - args.handles)
        dur = min(total, b + args.handles) - ss if total else (b - a + 2 * args.handles)
    else:
        ss, dur = 0.0, None
    res = {"source": src, "source_in_s": round(ss, 3), "range": list(rng) if rng else None,
           "engine": args.engine, "zoom_pct": args.max_zoom}

    if args.engine == "deshake":
        if args.analyze:
            return dict(res, status="error", reason="--analyze needs vid.stab (ffmpeg -filters | grep vidstab)")
        return render_deshake(src, out, ss, dur, info, args, res, t0)

    with tempfile.TemporaryDirectory() as td:
        trf = os.path.join(td, "full.trf")
        before, scale = measure(src, ss, dur, info, args, keep_trf=trf)
        res.update(shake_before=before["worst_s"], shake_mean_before=before["mean"], tracked=before["tracked"],
                   pan=before["pan"], detect_scale=round(scale, 3))
        if before["worst_s"] is None:
            return dict(res, status="skip", reason=f"untrackable (only {int(before['tracked'] * 100)} % of frames tracked: "
                                                   "water, fog, dark or a subject filling the frame)", seconds=round(time.time() - t0, 1))
        if args.analyze:
            verdict = "shaky" if before["worst_s"] >= args.min_shake else "already smooth"
            return dict(res, status="analyze", reason=verdict, seconds=round(time.time() - t0, 1))
        if before["worst_s"] < args.min_shake and not args.force:
            return dict(res, status="skip", reason=f"already smooth (worst second {before['worst_s']} px/frame < {args.min_shake})",
                        seconds=round(time.time() - t0, 1))

        fps = info["fps_float"] or 30.0
        z = float(args.max_zoom)
        margin = min(W, H) * z / 100.0 / 2.0                      # pixels the zoom hides on the short side
        maxshift = max(1, int(0.75 * margin))
        maxangle = 0.25 * margin / (math.hypot(W, H) / 2.0)       # corner travel of a rotation stays inside the rest
        smoothing = max(1, int(round(fps * args.smooth_s)))
        vf = (f"vidstabtransform=input='{ff_escape(trf)}':smoothing={smoothing}:optalgo=gauss:optzoom=0:zoom={z:g}"
              f":maxshift={maxshift}:maxangle={maxangle:.5f}:crop=black:interpol=bicubic,unsharp=5:5:0.5:3:3:0,format=yuv420p")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        tmp = str(Path(out).with_name(Path(out).stem + ".part" + Path(out).suffix))
        cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-y", *seek_args(ss, None), "-i", src,
               *(["-t", f"{dur:.3f}"] if dur else []), "-map", "0:v:0", *(["-map", "0:a:0"] if info["has_audio"] else []),
               "-vf", vf, "-fps_mode", "passthrough", *media.h264_args("final", height=H),
               *(["-c:a", "aac", "-b:a", "192k"] if info["has_audio"] else []), "-movflags", "+faststart", tmp]
        run(cmd)
        res.update(smoothing_frames=smoothing, smooth_s=args.smooth_s, maxshift_px=maxshift, maxangle_rad=round(maxangle, 5))

    oinfo = media.probe(tmp)
    oinfo = dict(oinfo, width=oinfo["width"], height=oinfo["height"])
    after, _ = measure(tmp, 0.0, None, oinfo, args)
    a_worst = after["worst_s"]
    if a_worst is not None:
        a_worst = round(a_worst / (1 + z / 100.0), 3)            # the zoom magnifies whatever motion is left
    gain = None if a_worst is None or not before["worst_s"] else round(1 - a_worst / before["worst_s"], 3)
    res.update(shake_after=a_worst, gain=gain)
    keep = args.keep_all or (gain is not None and gain >= args.min_gain)
    if keep:
        os.replace(tmp, out)
        res.update(status="kept", out=out,
                   reason=f"jitter {before['worst_s']} -> {a_worst} px/frame ({int(round((gain or 0) * 100))} % less), zoom {z:g} %")
    else:
        os.remove(tmp)
        res.update(status="reverted", out=None,
                   reason=f"gain {gain if gain is None else int(round(gain * 100))} % < {int(args.min_gain * 100)} %: "
                          "the measurements disagree about what the camera did - keep the original, or trim to a calmer stretch")
    res["seconds"] = round(time.time() - t0, 1)
    if res.get("out"):
        res["size_x"] = round(os.path.getsize(out) / max(1, os.path.getsize(src)) * (total / (dur or total or 1)), 2)
        Path(out + ".stab.json").write_text(json.dumps(res, indent=1))
    return res


def render_deshake(src, out, ss, dur, info, args, res, t0) -> dict:
    W, H = info["width"], info["height"]
    z = 1 + float(args.max_zoom) / 100.0
    zw, zh = int(W * z) // 2 * 2, int(H * z) // 2 * 2
    vf = f"deshake=rx=32:ry=32:edge=clamp,scale={zw}:{zh}:flags=bicubic,crop={W}:{H},format=yuv420p"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    run([media.ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-y", *seek_args(ss, None), "-i", src,
         *(["-t", f"{dur:.3f}"] if dur else []), "-map", "0:v:0", *(["-map", "0:a:0"] if info["has_audio"] else []),
         "-vf", vf, "-fps_mode", "passthrough", *media.h264_args("final", height=H),
         *(["-c:a", "aac", "-b:a", "192k"] if info["has_audio"] else []), "-movflags", "+faststart", out])
    res.update(status="kept", out=out, reason="deshake (unmeasured: watch it before keeping it)", seconds=round(time.time() - t0, 1))
    Path(out + ".stab.json").write_text(json.dumps(res, indent=1))
    return res


def default_out(src: str, rng, out_dir: str | None) -> str:
    p = Path(src)
    d = Path(out_dir) if out_dir else p.parent / "stabilized"
    tag = f"_{rng[0]:.2f}" if rng else "_stab"
    return str(d / f"{p.stem}{tag}.mp4")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="clip(s)")
    ap.add_argument("-o", "--out", help="output file (one input); default <clip dir>/stabilized/<stem>_stab.mp4")
    ap.add_argument("--out-dir", help="output folder when several inputs are given")
    ap.add_argument("--range", nargs=2, type=float, metavar=("IN", "OUT"), help="stabilize only this stretch (source seconds)")
    ap.add_argument("--handles", type=float, default=HANDLE_S, help="extra seconds kept each side of --range (default 0.5)")
    ap.add_argument("--analyze", action="store_true", help="measure only, render nothing")
    ap.add_argument("--check", action="store_true", help="say whether this ffmpeg has vid.stab, then exit")
    ap.add_argument("--max-zoom", type=float, default=8.0, help="crop budget in percent (default 8; 12 is a sane ceiling)")
    ap.add_argument("--smooth-s", type=float, default=0.5, help="smoothing window each side, seconds (default 0.5: longer = calmer, more crop needed)")
    ap.add_argument("--min-shake", type=float, default=0.8, help="worst-second jitter (px/frame at 960 px) below which a clip counts as smooth")
    ap.add_argument("--min-gain", type=float, default=0.15, help="keep a render only if jitter drops at least this much (default 0.15)")
    ap.add_argument("--shakiness", type=int, default=6, help="vidstabdetect shakiness 1-10 (default 6)")
    ap.add_argument("--detect-width", type=int, default=1920, help="analysis copy width (default 1920; motion is scaled back up)")
    ap.add_argument("--force", action="store_true", help="stabilize even when the clip measures smooth")
    ap.add_argument("--keep-all", action="store_true", help="keep the render even when the gate would revert it")
    ap.add_argument("--replace", action="store_true", help="overwrite an existing output file (never the source)")
    ap.add_argument("--engine", choices=("vidstab", "deshake"), default="vidstab")
    args = ap.parse_args()

    media.require("ffmpeg")
    if args.check:
        ok = has_vidstab()
        print(json.dumps({"vidstab": ok, "deshake": has_filter("deshake")}))
        if not ok:
            log(VIDSTAB_HELP)
        return 0 if ok else 1
    if not args.inputs:
        ap.print_usage(sys.stderr)
        return 2
    if args.engine == "vidstab" and not has_vidstab():
        log(VIDSTAB_HELP)
        return 1
    if args.out and len(args.inputs) > 1:
        log("-o takes one input; use --out-dir for several")
        return 2
    if not (0 < args.max_zoom <= 20):
        log("--max-zoom must be in (0, 20]: a bigger crop loses more of the shot than smoothing gives back")
        return 2

    rng = tuple(args.range) if args.range else None
    bad = 0
    for src in args.inputs:
        if not Path(src).is_file():
            print(json.dumps({"status": "error", "source": src, "reason": "file not found"}))
            bad += 1
            continue
        out = None if args.analyze else str(Path(args.out).expanduser().resolve()) if args.out else default_out(src, rng, args.out_dir)
        if out and Path(out).resolve() == Path(src).resolve():
            res = {"status": "error", "source": src, "reason": "the output is the source file: refusing to overwrite the original"}
        elif out and Path(out).exists() and not args.replace:
            res = {"status": "error", "source": src, "reason": f"{out} already exists: pass --replace to overwrite it, or pick another -o"}
        else:
            try:
                res = stabilize_one(str(Path(src).resolve()), out, rng, args)
            except RuntimeError as e:
                res = {"status": "error", "source": src, "reason": str(e)}
        bad += res["status"] == "error"
        print(json.dumps(res), flush=True)
        log(f"{Path(src).name}: {res['status']} - {res.get('reason', '')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
