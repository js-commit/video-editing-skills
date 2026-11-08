#!/usr/bin/env python3
"""Measure a rendered draft before anyone watches it.

  qc_render.py RENDER.mp4 CUT.json [--mix MIX.wav] [--json]

One decode of the render finds: black frames, frozen pictures, bars (a portrait or odd-shaped
shot that reached the frame unfitted), loudness per music cue and the steps between cues,
integrated loudness, true peak, silence, and a length that does not match the cut list.
With --mix (and its -bed.wav twin from mixdown.py) it also checks that the clips' own sound
sits under the music where it should: audible, not competing.

ERROR = broken (fix before showing anyone). WARN = probably wrong, look at it. Exit 1 on any ERROR.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402
from hv import media  # noqa: E402


def qc(render: str, job: dict, mix: str | None = None) -> dict:
    cuts, end, fps = job["cuts"], float(job["end_s"]), int(job.get("fps", 30))
    cues = sorted(job.get("cues", []), key=lambda c: c["record_s"])
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-nostats", "-nostdin", "-i", render,
                        "-vf", "blackdetect=d=0.03:pix_th=0.10,freezedetect=n=0.002:d=0.15,cropdetect=limit=24:round=2:reset=1",
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    log = r.stderr
    if r.returncode:
        return {"errors": [f"could not decode the render: {log[-300:]}"], "warnings": [], "info": []}
    err, warn, info = [], [], []
    info_v = media.probe(render)
    dur, W, H = info_v["duration"] or 0, info_v["width"], info_v["height"]

    def cut_at(t):
        return max((i for i, c in enumerate(cuts) if c["record_s"] <= t + 1e-3), default=0)

    def where(t):
        i = cut_at(t)
        return f"{hv.tc(t)} (cut {i}: {cuts[i].get('note', '')[:40]})"

    if abs(dur - end) > 0.5:
        err.append(f"render is {dur:.2f}s but the cut list is {end:.2f}s: stale segments or a wrong mix")
    if not info_v["has_audio"]:
        err.append("the render has no audio track")

    for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", log):
        s, e, d = map(float, m.groups())
        if s > end - 2.5:
            continue          # a fade to black at the very end is fine
        err.append(f"BLACK {d * fps:.0f} frame(s) at {where(s)}: an in-point before the clip's first frame, or a dark shot")

    boxes = {}
    for m in re.finditer(r"t:([\d.]+) .*?crop=(\d+):(\d+):(\d+):(\d+)", log):
        t = float(m.group(1))
        if t < end - 2.5:
            boxes.setdefault(cut_at(t), []).append(tuple(map(int, m.groups()[1:])))

    def bars(lo, size, full):
        return size < 0.9 * full and min(lo, full - size - lo) >= (full - size) / 4

    for i, b in sorted(boxes.items()):
        w, h, x, y = (sorted(c[k] for c in b)[len(b) // 2] for k in range(4))
        if len(b) >= 10 and (bars(x, w, W) or bars(y, h, H)):
            warn.append(f"BARS cut {i} at {hv.tc(cuts[i]['record_s'])}: picture {w}x{h} inside {W}x{H} - "
                        "an unfitted portrait / odd-aspect shot (or very dark edges); fit: blur")

    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
    for s, d in zip(starts, durs):
        if s > end - 3.0:
            continue
        i = cut_at(s)
        if cuts[i].get("photo"):
            continue
        head = abs(s - cuts[i]["record_s"]) < 0.07
        if head and d < 0.5:
            warn.append(f"FROZEN {d:.2f}s at the head of {where(s)}: the clip starts late - move its in_s later (>= 0.3 s)")
        elif d >= 0.5:
            warn.append(f"FREEZE {d:.2f}s at {where(s)}: a still picture inside a shot (locked-off view, or a stalled clip)")

    series = [(float(t), float(s)) for t, s in re.findall(r"t:\s*([\d.]+)\s+TARGET.*?S:\s*(-?[\d.]+)", log)]
    summ = log[log.rfind("Summary:"):]
    I = re.search(r"I:\s+(-?[\d.]+) LUFS", summ)
    P = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ)
    integ = float(I.group(1)) if I else None
    tp = float(P.group(1)) if P else None
    if tp is not None and tp > -1.0:
        warn.append(f"true peak {tp} dBTP: over -1 dBTP can distort on phones and TVs")
    if integ is not None and (integ < -26 or integ > -10):
        warn.append(f"integrated loudness {integ} LUFS: far from the -14..-18 most players expect")
    if integ is not None and integ < -60:
        err.append("the render is silent")

    def st_mean(t0, t1):
        v = [s for t, s in series if t0 + 3.0 <= t < t1 and s > -70]
        return 10 * math.log10(sum(10 ** (x / 10) for x in v) / len(v)) if v else None
    prev = None
    for k, c in enumerate(cues):
        t0 = c["record_s"]
        t1 = cues[k + 1]["record_s"] if k + 1 < len(cues) else end
        L = st_mean(t0, t1)
        name = Path(c["file"]).stem
        info.append(f"{hv.tc(t0)} {name[:34]:34s} {t1 - t0:5.1f}s " + (f"{L:6.1f} LUFS" if L is not None else "(too short to measure)"))
        if L is not None and prev is not None and abs(L - prev[1]) > 3.0:
            warn.append(f"loudness step {L - prev[1]:+.1f} LU into {name!r} at {hv.tc(t0)}: over ~3 LU needs a reason")
        if L is not None:
            prev = (name, L)

    if mix and Path(mix).exists():
        bed = Path(mix).with_name(Path(mix).stem + "-bed.wav")
        if bed.exists():
            for k, c in enumerate(cues):
                t0 = c["record_s"]
                t1 = cues[k + 1]["record_s"] if k + 1 < len(cues) else end
                if t1 - t0 < 4:
                    continue
                b = hv.mean_db(str(bed), t0, t1 - t0)
                m = hv.mean_db(mix, t0, t1 - t0)
                if b is None or m is None:
                    continue
                gap = b - m
                info.append(f"clips' own sound under {Path(c['file']).stem[:30]}: {gap:+.1f} dB vs the mix")
                if gap > -5:
                    warn.append(f"BED LOUD under {Path(c['file']).stem!r}: {gap:+.1f} dB vs the mix - it competes with the music "
                                "(bed_db down on the loud cuts)")
                elif gap < -20:
                    warn.append(f"BED LOST under {Path(c['file']).stem!r}: {gap:+.1f} dB vs the mix - the clips sound silent")
    return {"errors": err, "warnings": warn, "info": info, "lufs": integ, "true_peak": tp,
            "duration": round(dur, 3), "size": f"{W}x{H}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("render")
    ap.add_argument("cut")
    ap.add_argument("--mix")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = qc(a.render, json.load(open(a.cut)), a.mix)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"{Path(a.render).name}: {res.get('duration')} s, {res.get('size')}, {res.get('lufs')} LUFS, true peak {res.get('true_peak')}")
        for x in res["info"]:
            print("  " + x)
        for x in res["errors"]:
            print("ERROR", x)
        for x in res["warnings"]:
            print("WARN ", x)
        print(f"{len(res['errors'])} errors, {len(res['warnings'])} warnings")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
