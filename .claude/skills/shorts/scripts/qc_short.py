#!/usr/bin/env python3
"""Measured QC for a rendered Short, plus a contact sheet to look at.

    qc_short.py SHORT.mp4                          # reads SHORT.mp4.plan.json when it exists
    qc_short.py SHORT.mp4 --sheet SHEET.jpg        # also: frames with the Shorts UI zones shaded red
    qc_short.py SHORT.mp4 --render-transcript SHORT.transcript.json   # check the first words survived the cut

Measures, never assumes:
  file      9:16, the planned size and frame count, <= 3 min (else it is not a Short), audio present
  length    15-60 s is the target (warning outside)
  hook      speech within the first 0.6 s, a caption on screen before 2 s
  audio     integrated loudness near the target (default -14 LUFS), true peak <= -1 dBTP, no long dead air
  picture   no black frames, no location tags left in the file
  captions  rendered alone on black and their bounding box measured: it must sit inside the
            area the Shorts UI leaves free (top 8 %, bottom 22 %, right 13 %, left 4 % are covered)
  framing   face-only time <= the face budget (default 20 %), no shot over 8 s, none under 1 s
Prints a JSON report. Exit 0 = pass (warnings allowed), 3 = fix and re-render.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortslib as sl  # noqa: E402


def ff_log(args: list) -> str:
    """ffmpeg's info-level log (the analysis filters report there; -v error would hide it)."""
    r = sl.media.run(sl.ffmpeg_cmd("-nostats", *args), capture_output=True, text=True)
    return r.stderr or ""


def count_frames(path: Path) -> int:
    out = subprocess.run([sl.media.ffprobe(), "-v", "error", "-count_packets", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout
    try:
        return int(out.strip().split(",")[0])
    except ValueError:
        return 0


def tags(path: Path) -> list:
    out = subprocess.run([sl.media.ffprobe(), "-v", "error", "-show_entries", "format_tags:stream_tags",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    j = json.loads(out or "{}")
    keys = list((j.get("format") or {}).get("tags", {}) or {})
    for s in j.get("streams", []) or []:
        keys += list(s.get("tags", {}) or {})
    return sorted(set(keys))


def caption_boxes(plan: dict, w: int, h: int, dur: float) -> list:
    """Render the plan's captions on black and return the per-frame bounding boxes of the text."""
    cap = (plan.get("captions") or {}).get("filter")
    if not cap:
        return []
    log = ff_log(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=5:d={dur:.3f}",
                  "-vf", f"{cap},bbox=min_val=100", "-f", "null", "-"])
    boxes = []
    for m in re.finditer(r"pts_time:([\d.]+).*?x1:(\d+)\s+x2:(\d+)\s+y1:(\d+)\s+y2:(\d+)", log):
        t, x1, x2, y1, y2 = float(m.group(1)), *(int(g) for g in m.groups()[1:])
        if x2 > x1 and y2 > y1:
            boxes.append({"t": round(t, 2), "x1": x1, "x2": x2, "y1": y1, "y2": y2})
    return boxes


def sheet(video: Path, out: Path, times: list, fps: float):
    """Frames at `times`, 270 px wide, the UI-covered zones shaded red, time stamped."""
    times = sorted({round(t, 2) for t in times})
    frames = sorted({max(0, int(round(t * fps))) for t in times})
    sel = "+".join(f"eq(n\\,{f})" for f in frames)
    s = sl.SAFE
    shade = (f"drawbox=x=0:y=0:w=iw:h=ih*{s['top']}:color=red@0.35:t=fill,"
             f"drawbox=x=0:y=ih*{1 - s['bottom']}:w=iw:h=ih*{s['bottom']}:color=red@0.35:t=fill,"
             f"drawbox=x=iw*{1 - s['right']}:y=ih*{s['top']}:w=iw*{s['right']}:h=ih*{1 - s['top'] - s['bottom']}:"
             f"color=red@0.35:t=fill,"
             f"drawbox=x=0:y=ih*{s['top']}:w=iw*{s['left']}:h=ih*{1 - s['top'] - s['bottom']}:color=red@0.35:t=fill")
    font = sl.find_font()
    label = ""
    if font and sl.has_filter("drawtext"):
        label = (f",drawtext=fontfile='{sl.ff_escape_path(font)}':text='%{{pts\\:hms}}':x=6:y=6:fontsize=20:"
                 f"fontcolor=yellow:box=1:boxcolor=black@0.7")
    cols = min(6, len(frames))
    rows = math.ceil(len(frames) / cols)
    vf = f"select='{sel}',scale=270:-2,{shade}{label},tile={cols}x{rows}:padding=4:color=gray"
    sl.run_ok(sl.ffmpeg_cmd("-v", "error", "-y", "-i", str(video), "-vf", vf, "-fps_mode", "passthrough",
                            "-frames:v", "1", "-update", "1", str(out)), "contact sheet")
    return str(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--plan", help="the render's plan (default: VIDEO.plan.json)")
    ap.add_argument("--sheet", help="write a contact sheet here (jpg/png)")
    ap.add_argument("--lufs", type=float, default=-14.0, help="loudness target (default -14)")
    ap.add_argument("--face-budget", type=float, default=0.20, help="max share of face-only time (default 0.20)")
    ap.add_argument("--render-transcript", help="a transcript of the RENDER: its first words must match the plan's")
    a = ap.parse_args()

    video = Path(a.video).expanduser().resolve()
    plan_path = Path(a.plan) if a.plan else video.with_name(video.name + ".plan.json")
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else {}
    errors, warnings, m = [], [], {}
    info = sl.media.probe(video)
    w, h, dur = info["width"], info["height"], info["duration"] or 0.0
    fps = info["fps_float"] or 30.0
    m.update({"size": f"{w}x{h}", "duration_s": round(dur, 3), "fps": info["fps"]})

    # file
    if not w or not h or abs(w / h - 9 / 16) > 0.01:
        errors.append(f"{w}x{h} is not 9:16 portrait")
    if plan.get("size") and [w, h] != plan["size"]:
        errors.append(f"size {w}x{h}, planned {plan['size'][0]}x{plan['size'][1]}")
    if not info["has_audio"]:
        errors.append("no audio track")
    if dur > 180:
        errors.append(f"{dur:.1f} s: over 3 minutes is a regular video, not a Short")
    elif not (15 <= dur <= 60):
        warnings.append(f"{dur:.1f} s: Shorts work best at 15-60 s")
    if plan.get("frames"):
        n = count_frames(video)
        m["frames"] = n
        if abs(n - plan["frames"]) > 1:
            errors.append(f"{n} frames, planned {plan['frames']}")
    bad_tags = [t for t in tags(video) if "location" in t.lower() or t.lower().startswith("com.apple.quicktime.gps")]
    if bad_tags:
        errors.append(f"location metadata survived: {bad_tags}")

    # one decode for picture + audio analysis
    log = ff_log(["-i", str(video), "-vf", "blackdetect=d=0.1:pix_th=0.10",
                  "-af", "ebur128=peak=true,silencedetect=n=-45dB:d=0.35", "-f", "null", "-"])
    summ = log[log.rfind("Summary:"):]
    I = re.search(r"I:\s+(-?[\d.]+) LUFS", summ)
    TP = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ)
    m["lufs"] = float(I.group(1)) if I else None
    m["true_peak_dbtp"] = float(TP.group(1)) if TP else None
    if m["lufs"] is None:
        errors.append("could not measure loudness")
    elif abs(m["lufs"] - a.lufs) > 2:
        errors.append(f"loudness {m['lufs']} LUFS, target {a.lufs} (set \"lufs\" in the spec and re-render)")
    elif abs(m["lufs"] - a.lufs) > 1:
        warnings.append(f"loudness {m['lufs']} LUFS, target {a.lufs}")
    if m["true_peak_dbtp"] is not None and m["true_peak_dbtp"] > -0.5:
        warnings.append(f"true peak {m['true_peak_dbtp']} dBTP; keep it at or below -1")
    blacks = [(float(x), float(y)) for x, y in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    m["black"] = blacks
    for x, y in blacks:
        errors.append(f"black frames {x:.2f}-{y:.2f} s")
    sil = re.findall(r"silence_start:\s*(-?[\d.]+)[\s\S]*?silence_end:\s*([\d.]+)", log)
    sil = [(max(0.0, float(x)), float(y)) for x, y in sil]
    m["silences"] = [(round(x, 2), round(y, 2)) for x, y in sil]
    if sil and sil[0][0] <= 0.05 and sil[0][1] > 0.6:
        errors.append(f"the first {sil[0][1]:.2f} s are silent: the hook has to start talking at once")
    for x, y in sil:
        if y - x > 1.5 and y < dur - 0.3:
            warnings.append(f"{y - x:.1f} s of dead air at {x:.1f} s")

    # captions
    caps = (plan.get("captions") or {})
    evs = caps.get("events") or []
    if plan and caps.get("engine") not in (None, "off"):
        if not evs or evs[0]["start"] > 2.0:
            warnings.append("no caption before 2 s: the hook should be spoken and shown in the first 2 seconds")
        boxes = caption_boxes(plan, w, h, dur)
        x0, y0, x1, y1 = sl.safe_rect(w, h)
        out = [b for b in boxes if b["x1"] < x0 or b["x2"] > x1 or b["y1"] < y0 or b["y2"] > y1]
        if boxes:
            m["caption_box"] = {"x1": min(b["x1"] for b in boxes), "x2": max(b["x2"] for b in boxes),
                                "y1": min(b["y1"] for b in boxes), "y2": max(b["y2"] for b in boxes)}
        m["safe_rect"] = {"x1": x0, "y1": y0, "x2": x1, "y2": y1}
        if out:
            worst = out[0]
            errors.append(f"{len(out)} sampled caption frames leave the safe area (first at {worst['t']} s: "
                          f"x {worst['x1']}-{worst['x2']}, y {worst['y1']}-{worst['y2']}; safe x {x0}-{x1}, y {y0}-{y1})")
        elif evs and not boxes:
            warnings.append("captions planned but none measured (font missing?) - look at the sheet")
    elif plan:
        warnings.append("no burned-in captions; most Shorts are watched muted")

    # framing
    pieces = plan.get("pieces") or []
    if pieces:
        total = plan.get("duration_s") or dur
        face = sum(p["out_end"] - p["out_start"] for p in pieces if p.get("face_only"))
        m["face_only_frac"] = round(face / total, 3) if total else 0
        if total and face / total > a.face_budget:
            errors.append(f"face-only shots fill {face / total:.0%} of the short (budget {a.face_budget:.0%}): "
                          f"swap in b-roll, stack the face over the subject, or reframe")
        if pieces[0].get("face_only"):
            warnings.append("the short opens on a face-only shot; open on the subject when the footage allows")
        for p in pieces:
            d = p["out_end"] - p["out_start"]
            if d > 8.0:
                warnings.append(f"shot at {p['out_start']:.1f} s holds {d:.1f} s; vary the framing every few seconds")
            if d < 1.0:
                warnings.append(f"shot at {p['out_start']:.1f} s lasts {d:.2f} s; under 1 s reads as a flicker")
        m["shots"] = len(pieces)

    # bled words: the render's own transcript must start with the planned first words
    if a.render_transcript and evs:
        got = sl.load_words(a.render_transcript)[:3]
        want = [x["word"] for x in evs[0]["words"]][:3]
        g, wnt = sl.norm(" ".join(x["word"] for x in got)), sl.norm(" ".join(want))
        m["first_words"] = {"render": g, "planned": wnt}
        if g.split()[:1] != wnt.split()[:1]:
            errors.append(f"the render opens with {g!r}, planned {wnt!r}: a neighbouring word bled in or the hook was clipped")

    if a.sheet:
        times = [0.5, 1.5] + [(p["out_start"] + p["out_end"]) / 2 for p in pieces] + [max(0.0, dur - 0.5)]
        m["sheet"] = sheet(video, Path(a.sheet).expanduser().resolve(), [t for t in times if t < dur], fps)

    rep = {"ok": not errors, "video": str(video), "errors": errors, "warnings": warnings, "measured": m}
    print(json.dumps(rep, indent=2))
    return 0 if not errors else 3


if __name__ == "__main__":
    sys.exit(main())
