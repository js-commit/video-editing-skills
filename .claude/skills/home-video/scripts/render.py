#!/usr/bin/env python3
"""Render a cut list to an mp4 with ffmpeg: straight cuts on the beat, zooms, portrait
blur-fill, photo push-ins, and the mixed soundtrack.

  render.py CUT.json MIX.wav OUT.mp4 [--final] [--size WxH]

Draft (default): settings render.draft_height (1080) tall, fast hardware/libx264 encode.
--final: the cut list's own canvas size, high quality (the version you keep or share).

Each cut becomes its own segment in work/segments/, named by a hash of everything that
shapes it, so a notes round re-encodes only the shots that changed; the segments are then
joined without re-encoding. A cut runs from its record_s to the next cut's, counted in frames,
so nothing drifts off the music. A source that ends a frame early holds its last frame.
Every segment leaves as limited-range BT.709 (camera clips mix full and limited range, and a
joined file keeps only the first segment's flags: mixed ranges look washed out or crushed).
The finished file's true peak is measured and the audio trimmed once if it is above -1 dBTP.
Prints the output path on stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402
from hv import media, settings  # noqa: E402

TP_MAX, TP_TARGET = -1.0, -1.4


def even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def fit_filter(c: dict, src_w: int, src_h: int, W: int, H: int) -> str:
    """Scale/crop chain for one cut onto a W x H frame."""
    fit = c.get("fit")
    same_aspect = src_w and src_h and abs(src_w / src_h - W / H) < 0.02 * (W / H)
    if not fit:
        fit = "cover" if same_aspect or c.get("zoom") else "blur"
    if c.get("photo") and not c.get("fit"):
        fit = "blur"
    z = c.get("zoom") or {}
    zf = float(z.get("z", 1.0))
    if fit == "pad":
        return f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos:out_range=tv,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"
    if fit == "blur":
        return (f"split[bg0][fg0];[bg0]scale={W}:{H}:force_original_aspect_ratio=increase:flags=bilinear:out_range=tv,"
                f"crop={W}:{H},gblur=sigma=40,eq=brightness=-0.06[bg];"
                f"[fg0]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos:out_range=tv[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    # cover (+ zoom about cx, cy, clamped so no edge shows)
    zf = max(1.0, zf)
    lim = (zf - 1) / (2 * zf)
    cx = min(max(float(z.get("cx", 0.5)), 0.5 - lim), 0.5 + lim)
    cy = min(max(float(z.get("cy", 0.5)), 0.5 - lim), 0.5 + lim)
    zw, zh = even(W * zf), even(H * zf)
    return (f"scale={zw}:{zh}:force_original_aspect_ratio=increase:flags=lanczos:out_range=tv,"
            f"crop={W}:{H}:'max(0,min(iw-{W},iw*{cx:.4f}-{W}/2))':'max(0,min(ih-{H},ih*{cy:.4f}-{H}/2))'")


def segment(c: dict, n: int, fps: int, W: int, H: int, enc: list, seg_dir: Path) -> tuple:
    src = c["file"]
    if c.get("photo"):
        info = {"width": 0, "height": 0}
    else:
        info = media.probe(src)
    sw, sh = hv.display_size(info)
    fit = fit_filter(c, sw, sh, W, H)
    if c.get("photo"):
        # slow push-in: 100 % -> 108 % over the shot, on a frame twice the size so the move is smooth
        head = f"[0:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
        head += f"zoompan=z='1+0.08*on/{max(1, n)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={fps},"
        fit = f"scale={W}:{H}:out_range=tv"
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", src]
        seek = []
    else:
        head = f"[0:v]setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop_duration=2,"
        inputs = ["-i", src]
        seek = ["-ss", f"{c['in_s']:.3f}"]
    fc = head + fit + ",format=yuv420p,setsar=1[v]"
    st = os.stat(src)
    key = f"{os.path.realpath(src)}|{st.st_size}|{int(st.st_mtime)}|{c['in_s']:.3f}|{n}|{fc}|{' '.join(enc)}"
    seg = seg_dir / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".mp4")
    if seg.exists():
        return seg, False
    tmp = seg.with_suffix(".part.mp4")
    cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-y", *seek, *inputs, "-an", "-filter_complex", fc,
           "-map", "[v]", "-frames:v", str(n), *enc, str(tmp)]
    r = media.run(cmd, capture_output=True, text=True)
    if r.returncode:
        hv.die(f"cut {c.get('i')}: ffmpeg failed: {r.stderr.strip()[-400:]}")
    got = subprocess.run([media.ffprobe(), "-v", "error", "-count_packets", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(tmp)], capture_output=True, text=True).stdout
    got = int((got.strip().split(",")[0] or "0"))
    if got != n:
        tmp.unlink(missing_ok=True)
        hv.die(f"cut {c.get('i')}: {got} frames, wanted {n} ({Path(src).name} from {c['in_s']}s)")
    tmp.replace(seg)
    return seg, True


def true_peak(path: Path) -> float | None:
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-map", "0:a:0",
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    s = r.stderr[r.stderr.rfind("Summary:"):]
    m = re.search(r"Peak:\s+(-?[\d.]+) dBFS", s)
    return float(m.group(1)) if m else None


def render(job: dict, mix: str, out: Path, final: bool = False, size: str | None = None, work_dir: Path | None = None) -> dict:
    t0 = time.time()
    cuts, fps = job["cuts"], int(job.get("fps", 30))
    W, H = int(job["width"]), int(job["height"])
    if size:
        W, H = (int(x) for x in size.lower().split("x"))
    elif not final:
        dh = int(settings.get("render.draft_height", default=1080) or 1080)
        if H > dh:
            W, H = even(W * dh / H), dh
    enc = media.h264_args("final" if final else "draft", height=H) + [
        "-g", str(fps), "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    seg_dir = (work_dir or out.parent) / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    end = float(job["end_s"])
    edges = [round(c["record_s"] * fps) for c in cuts] + [round(end * fps)]
    lst, made = [], 0
    for i, c in enumerate(cuts):
        n = edges[i + 1] - edges[i]
        if n < 1:
            hv.die(f"cut {i} has no frames (record_s {c['record_s']})")
        seg, new = segment(c, n, fps, W, H, enc, seg_dir)
        made += new
        lst.append(f"file '{seg.as_posix()}'")
    lfile = seg_dir / f"list-{out.stem}.txt"
    lfile.write_text("\n".join(lst) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)

    def mux(trim_db: float) -> float | None:
        r = subprocess.run([media.ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0",
                            "-i", str(lfile), "-i", mix, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                            "-af", f"volume={trim_db:.2f}dB", "-c:a", "aac", "-b:a", "256k", "-t", f"{end:.3f}",
                            "-movflags", "+faststart", str(out)], capture_output=True, text=True)
        if r.returncode:
            hv.die(f"mux failed: {r.stderr.strip()[-400:]}")
        return true_peak(out)
    trim = 0.0
    tp = mux(trim)
    if tp is not None and tp > TP_MAX:
        trim += TP_TARGET - tp
        tp = mux(trim)
    return {"out": str(out), "size": f"{W}x{H}", "segments": len(cuts), "encoded": made,
            "audio_trim_db": round(trim, 2), "true_peak": tp, "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cut")
    ap.add_argument("mix")
    ap.add_argument("out")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--size")
    a = ap.parse_args()
    job = json.load(open(a.cut))
    res = render(job, a.mix, Path(a.out).expanduser().resolve(), a.final, a.size, Path(a.cut).resolve().parent)
    hv.log(f"rendered {res['out']}: {res['size']}, {res['encoded']} of {res['segments']} segments encoded, "
           f"true peak {res['true_peak']} dBTP, {res['seconds']} s")
    print(res["out"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
