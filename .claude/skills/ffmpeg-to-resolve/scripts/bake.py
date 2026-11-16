#!/usr/bin/env python3
"""Render the few things a job could not express as Resolve items: job["bakes"] -> clips in <job folder>/baked/.

    bake.py <job folder>/job.json

  clip            a push-in (zoom "to"), a blur fit, or (plan.py --exact-rates) a clip at another frame rate: the
                  renderer's own filter chain at the canvas size, H.264 at final quality
  still-overlay   a PNG overlay as a ProRes 4444 clip of the overlay's length with its alpha fades
  webm-overlay    a VP9 overlay with alpha as a ProRes 4444 clip (Resolve does not read VP9 alpha)
  fade            the fade-out: a black ProRes 4444 clip whose alpha ramps like the renderer's fade

Each output is named by a hash of what shapes it (plan.py), so a clip that exists is right and is kept; clips in
baked/ the job no longer lists are deleted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "talking-head-ffmpeg" / "scripts"))
import _common as C  # noqa: E402
import qc as Q  # noqa: E402

TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
PRORES = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", *TAGS]


def main():
    job = C.read_json(sys.argv[1])
    fps_s = job["fps"]
    fps = Fraction(fps_s)
    ffmpeg = C.ffmpeg()
    made = 0
    for b in job["bakes"]:
        out = Path(b["out"])
        if out.exists() and Q.count_frames(out) == b["n"]:
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".part" + out.suffix)
        W, H = b["size"]
        run = subprocess.run
        if b["kind"] == "clip":
            enc = C.media.h264_args("final", height=H, width=W) + ["-g", str(round(float(fps)))] + TAGS
            cmd = [ffmpeg, "-v", "error", "-y", "-ss", b["ss"], "-i", b["src"], "-an", "-vf", b["vf"], "-frames:v", str(b["n"]),
                   *enc, "-write_tmcd", "0", str(tmp)]
            run = C.media.run
        elif b["kind"] == "still-overlay":
            fd = float(b["fade_s"])
            n_s = float(b["n"] / fps)
            fades = f"fade=t=in:st=0:d={fd}:alpha=1,fade=t=out:st={n_s - fd:.4f}:d={fd}:alpha=1," if fd > 0 else ""
            cmd = [ffmpeg, "-v", "error", "-y", "-framerate", fps_s, "-loop", "1", "-i", b["src"], "-vf",
                   f"format=rgba,{fades}scale={W}:{H}:out_color_matrix=bt709:out_range=tv,format=yuva444p10le",
                   "-frames:v", str(b["n"]), *PRORES, str(tmp)]
        elif b["kind"] == "webm-overlay":
            cmd = [ffmpeg, "-v", "error", "-y", "-c:v", "libvpx-vp9", "-i", b["src"], "-vf",
                   f"format=rgba,scale={W}:{H}:out_color_matrix=bt709:out_range=tv,format=yuva444p10le",
                   "-frames:v", str(b["n"]), *PRORES, str(tmp)]
        elif b["kind"] == "fade":       # black with alpha i/n on frame i: render_recipe's fade=t=out, as a layer
            cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={fps_s},format=rgba",
                   "-vf", f"fade=t=in:st=0:d={float(b['n'] / fps):.6f}:alpha=1,format=yuva444p10le", "-frames:v", str(b["n"]),
                   *PRORES, str(tmp)]
        else:
            sys.exit(f"unknown bake kind {b['kind']!r}")
        res = run(cmd, capture_output=True, text=True)
        if res.returncode:
            sys.exit(f"bake {b['id']} ({b['kind']}): exit {res.returncode} {res.stderr[-400:]}")
        got = Q.count_frames(tmp)
        if got != b["n"]:
            os.remove(tmp)
            sys.exit(f"bake {b['id']}: {got} frames, wanted {b['n']}")
        os.replace(tmp, out)
        made += 1
    keep = {b["out"] for b in job["bakes"]}
    gone = [f for f in (Path(job["out_dir"]) / "baked").glob("*") if f.suffix in (".mov", ".mp4") and str(f) not in keep]
    for f in gone:                      # clips an earlier plan of this recipe baked and this one does not use
        f.unlink()
    print(json.dumps({"bakes": len(job["bakes"]), "made": made, "reused": len(job["bakes"]) - made, "pruned": len(gone)}))


if __name__ == "__main__":
    main()
