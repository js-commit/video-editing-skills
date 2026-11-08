#!/usr/bin/env python3
"""A still (screenshot, chart PNG, photo) -> a short clip a recipe can use as a b-roll brick, with a slow push-in.

    still_clip.py IMAGE --recipe <work>/recipe_vN.json [--dur 6] [--push 1.08] [--focus 0.5,0.5] [--fit blur|cover]
                  [--out FILE]

The renderer seeks inside clips, so a picture becomes a clip first: the recipe's fps and canvas size, H.264 final
quality. --fit blur (default) shows the whole picture over a blurred, darkened copy of itself (a tall phone screenshot
without black bars); cover fills the frame and crops. --push is the zoom at the end (1.0 = static); --focus is the point
it pushes toward (0-1, x,y). The push is computed on a 2x-size frame, so it glides instead of stepping a pixel at a
time. Output defaults to <work>/stills/<image stem>.mp4.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--dur", type=float, default=6.0)
    ap.add_argument("--push", type=float, default=1.08)
    ap.add_argument("--focus", default="0.5,0.5")
    ap.add_argument("--fit", choices=["blur", "cover"], default="blur")
    ap.add_argument("--out")
    a = ap.parse_args()
    rp = Path(a.recipe).resolve()
    r = C.read_json(rp)
    fps = R.fps_of(r)
    W, H = R.size_of(r)
    W2, H2 = W * 2, H * 2
    cx, cy = (float(v) for v in a.focus.split(","))
    N = max(1, round(a.dur * fps))
    out = Path(a.out) if a.out else rp.parent / "stills" / (Path(a.image).stem + ".mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    if a.fit == "blur":
        base = (f"split[a][b];[a]scale={W2 // 8}:{H2 // 8}:force_original_aspect_ratio=increase,crop={W2 // 8}:{H2 // 8},"
                f"boxblur=10:2,scale={W2}:{H2},eq=brightness=-0.1[bg];"
                f"[b]scale={W2}:{H2}:force_original_aspect_ratio=decrease:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    else:
        base = f"scale={W2}:{H2}:force_original_aspect_ratio=increase:flags=lanczos,crop={W2}:{H2}"
    z = f"1+({a.push}-1)*on/{max(1, N - 1)}"
    vf = (f"{base},format=yuv420p,zoompan=z='{z}':x='(iw-iw/zoom)*{cx}':y='(ih-ih/zoom)*{cy}':d={N}:s={W}x{H}:"
          f"fps={fps.numerator}/{fps.denominator},setsar=1,"
          f"setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709")
    cmd = [C.ffmpeg(), "-v", "error", "-y", "-i", a.image, "-filter_complex", vf, "-frames:v", str(N),
           *C.media.h264_args("final", height=H), "-color_range", "tv", "-colorspace", "bt709",
           "-color_primaries", "bt709", "-color_trc", "bt709", str(out)]
    res = C.media.run(cmd, capture_output=True, text=True)
    if res.returncode:
        sys.exit(res.stderr[-400:])
    print(json.dumps({"out": str(out), "frames": N, "seconds": round(N / float(fps), 3), "size": f"{W}x{H}"}))


if __name__ == "__main__":
    main()
