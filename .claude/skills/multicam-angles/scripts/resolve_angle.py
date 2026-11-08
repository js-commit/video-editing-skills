#!/usr/bin/env python3
"""Resolve side of the multicam angle pass (needs DaVinci Resolve Studio
running with the project open; the free version blocks external scripts).

Timeline layout (built by aroll-draft's multicam variant): V1/A1 = camera A,
the cut source; V2/A2 = camera B on the same cuts, every V2 clip disabled so
the timeline plays camera A. Switching a segment to camera B = enabling the
V2 clip above it. A PiP segment = V2 enabled plus a V3 clip of camera A
shrunk into a corner. Whole clips only: cut boundaries are trusted, clips
are never split.

Subcommands:
  backup    job.json "<suffix>"     duplicate the working timeline as
                                    "<timeline> <suffix>", add the copy to
                                    never_touch, keep the working one current
  dump      job.json out.json       V1/V2/V3 items of the LIVE timeline
                                    (record in/out, source offset, enabled,
                                    media path)
  frames    job.json dump.json outdir [only.json]
                                    side-by-side samples of both cameras
                                    (A left, B right) per V2 clip, tiled into
                                    contact sheets psheet_NN.jpg + index.json
  apply     job.json decisions.json set exactly the V2 clips in
                                    {"enable_v2": [record starts]} enabled
  pip       job.json pip.json       camera-A insets on V3 for
                                    {"pip_v3": [record starts]} (idempotent)
  restyle   job.json [pip.json]     rebuild the Fusion look on existing V3
                                    insets in place (keeps the user's moves)
  smooth    job.json out.json [--min-run-s 2]
                                    live anti-flicker safety net: absorb any
                                    camera A/B run under the minimum
  transform job.json <track> props.json [record_lt]
                                    static Inspector properties on every clip
                                    of one video track (rotate/zoom camera B)
  verify    job.json outdir start [start ...]
                                    export the RENDERED frame at the middle of
                                    each given segment (the only trustworthy
                                    check)

job.json (aroll-draft writes angle_job.json):
  {"project": "...", "timeline": "...", "never_touch": ["... backup"],
   "primary_path": "/abs/cameraA.mov", "secondary_path": "/abs/cameraB.mov",
   "secondary_rotate180": false,
   "offset_s": 1.25,     # camera B started this much LATER than camera A,
                         # measured from the audio (never from file clocks)
   "fps": "24",
   # optional, added by this skill:
   "angles": {"a": {"name": "face", "describe": "..."}, "b": {...}, "pip": {...}},
   "allowed_angles": ["a", "b", "pip"], "min_run_s": 2.0, "target_run_s": 4.0,
   "pip": {"corner": "top-right", "face_box": [x0, y0, x1, y1], "inset_width": 0.23}}

Camera-A time for a V2 sample = (left_offset + t) / fps + offset_s, derived
from the V2 clip itself so it survives hand edits on V1.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3] / "tools"))
import angles as A  # noqa: E402
from vidkit import media  # noqa: E402
from vidkit.resolve import (check_never_touch, connect, delete_clips_checked,  # noqa: E402
                            get_timeline, log, parse_fps, pool_by_path,
                            resolve_window_id, tc, timelines)

PIP_TRACK_NAME = "camera A PiP"


# ---- live timeline helpers ----------------------------------------------------

def track_items(timeline, idx, with_path=False):
    out = []
    for it in timeline.GetItemListInTrack("video", idx) or []:
        start, dur = it.GetStart(), it.GetDuration()
        c = {"record_in": start, "record_out": start + dur, "duration": dur,
             "left_offset": it.GetLeftOffset(), "enabled": it.GetClipEnabled(),
             "name": it.GetName()}
        if with_path:
            mpi = it.GetMediaPoolItem()
            c["path"] = mpi.GetClipProperty("File Path") if mpi else None
        out.append(c)
    return out


def v3_starts(timeline):
    if (timeline.GetTrackCount("video") or 0) < 3:
        return set()
    return {c["record_in"] for c in track_items(timeline, 3)}


def ab_segments(v2, pip_starts):
    """Live V2 clips as smoothing segments: 'b' when camera B shows (V2
    enabled, or a PiP sits on it), else 'a'."""
    segs = [{"start": c["record_in"], "dur": c["duration"],
             "angle": "b" if (c["enabled"] or c["record_in"] in pip_starts) else "a"}
            for c in v2]
    return sorted(segs, key=lambda s: s["start"])


def shortest_run_s(timeline, fps):
    rs = A.runs(ab_segments(track_items(timeline, 2), v3_starts(timeline)))
    return (min(r["dur"] for r in rs) / float(fps)) if rs else 0.0, len(rs)


def toggle_v2(timeline, enable):
    """Make the live V2 enabled set exactly `enable`.
    Returns (changed, enabled_n, requested_but_not_found)."""
    changed, enabled_n, seen = 0, 0, set()
    for it in timeline.GetItemListInTrack("video", 2) or []:
        start = it.GetStart()
        want = start in enable
        seen.add(start)
        if it.GetClipEnabled() != want:
            if not it.SetClipEnabled(want):
                log(f"WARN: SetClipEnabled failed at {start}")
                continue
            changed += 1
        enabled_n += want
    return changed, enabled_n, sorted(set(enable) - seen)


def timeline_size(timeline):
    try:
        return (int(timeline.GetSetting("timelineResolutionWidth")),
                int(timeline.GetSetting("timelineResolutionHeight")))
    except (TypeError, ValueError):
        return 3840, 2160


# ---- backup / dump --------------------------------------------------------------

def cmd_backup(a):
    job = A.load_job(a.job, need_offset=False)
    new_name = f"{job['timeline']} {a.suffix}"
    pm, project, timeline = get_timeline(job)
    if any(t.GetName() == new_name for t in timelines(project)):
        sys.exit(f"refusing: timeline {new_name!r} already exists")
    dup = timeline.DuplicateTimeline(new_name)
    if not dup:
        sys.exit("DuplicateTimeline failed")
    project.SetCurrentTimeline(timeline)   # the duplicate became current
    if new_name not in job["never_touch"]:
        job["never_touch"].append(new_name)
        Path(a.job).write_text(json.dumps(job, indent=2) + "\n")
    pm.SaveProject()
    print(json.dumps({"backup": dup.GetName(),
                      "v2_items": len(dup.GetItemListInTrack("video", 2) or []),
                      "never_touch": job["never_touch"]}))


def cmd_dump(a):
    job = A.load_job(a.job, need_offset=False)
    _, _, timeline = get_timeline(job)
    data = {"timeline": timeline.GetName(), "fps": str(job.get("fps", "24")),
            "start_frame": timeline.GetStartFrame(),
            "v1": track_items(timeline, 1, with_path=True),
            "v2": track_items(timeline, 2, with_path=True)}
    if (timeline.GetTrackCount("video") or 0) >= 3:
        data["v3"] = track_items(timeline, 3, with_path=True)
    Path(a.out).write_text(json.dumps(data, indent=1) + "\n")
    v1_starts = {c["record_in"] for c in data["v1"]}
    foreign_v3 = [c["record_in"] for c in data.get("v3", []) if c["record_in"] not in v1_starts]
    print(json.dumps({"timeline": data["timeline"], "v1_items": len(data["v1"]),
                      "v2_items": len(data["v2"]),
                      "v2_enabled": sum(1 for c in data["v2"] if c["enabled"]),
                      "v3_items": len(data.get("v3", [])),
                      "v3_not_ours": foreign_v3,
                      "counts_match": len(data["v1"]) == len(data["v2"]),
                      "out": os.path.abspath(a.out)}))


# ---- frames (contact sheets) ------------------------------------------------------

def _font_arg():
    """drawtext fontfile=... for this OS, '' to let fontconfig pick, None
    when drawtext is not compiled in (labels are then skipped: the brief
    still names every tile by sheet/row/column)."""
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"],
                       capture_output=True, text=True)
    if " drawtext " not in r.stdout:
        return None
    for f in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f):
            return "fontfile='" + f.replace(":", "\\:") + "':"
    return ""


def cmd_frames(a):
    from concurrent.futures import ThreadPoolExecutor
    job = A.load_job(a.job)
    data = json.loads(Path(a.dump).read_text())
    clips = data["v2"]
    if a.only:
        keep = set(json.loads(Path(a.only).read_text())["record_in"])
        clips = [c for c in clips if c["record_in"] in keep]
    fps = parse_fps(job.get("fps", data.get("fps", "24")))
    off = float(job["offset_s"])
    pri, sec = job.get("primary_path"), job.get("secondary_path")
    if not pri or not sec:
        sys.exit("job.json needs primary_path and secondary_path: the sampler "
                 "shows both cameras side by side (one camera alone cannot tell "
                 "'holding it up to camera A' from 'looking down at it').")
    rot = "hflip,vflip," if job.get("secondary_rotate180") else ""
    font = _font_arg()
    os.makedirs(a.outdir, exist_ok=True)
    for old in Path(a.outdir).glob("pair_*.jpg"):
        old.unlink()
    for old in Path(a.outdir).glob("psheet_*.jpg"):
        old.unlink()
    cols, rows = 2, 8
    per_sheet = cols * rows
    jobs, index, n = [], [], 0
    for i, c in enumerate(clips):
        dur_s = float(c["duration"] / fps)
        # never fewer than 2 samples: one instant can land on a glance up
        k_total = max(2, min(8, round(dur_s / 2.5)))
        for k in range(k_total):
            frac = (k + 0.5) / k_total
            sec_t = float((c["left_offset"] + frac * c["duration"]) / fps)
            pri_t = sec_t + off
            out = os.path.join(a.outdir, f"pair_{n:04d}.jpg")
            label = f"{i:03d}.{k}  {tc(c['record_in'], fps)}  {dur_s:.1f}s"
            fc = f"[0:v]scale=-2:240[a];[1:v]{rot}scale=-2:240[b];[a][b]hstack"
            if font is not None:
                fc += (",drawtext=" + font + "text='" + label.replace(":", "\\:")
                       + "':x=6:y=6:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.7")
            jobs.append((i, k, [media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                                "-ss", f"{max(pri_t, 0):.3f}", "-i", pri,
                                "-ss", f"{max(sec_t, 0):.3f}", "-i", sec,
                                "-frames:v", "1", "-filter_complex", fc, out]))
            sheet_no, pos = divmod(n, per_sheet)
            index.append({"i": i, "k": k, "record_in": c["record_in"],
                          "record_tc": tc(c["record_in"], fps),
                          "duration_s": round(dur_s, 2), "enabled": c["enabled"],
                          "pair": os.path.basename(out),
                          "sheet": f"psheet_{sheet_no + 1:02d}.jpg",
                          "row": pos // cols + 1, "col": pos % cols + 1,
                          "cols": cols})
            n += 1

    failed = []

    def run_one(j):
        i, k, cmd = j
        if media.run(cmd, capture_output=True).returncode:
            failed.append(f"{i}.{k}")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run_one, jobs))
    if failed:
        log(f"WARN: {len(failed)} sample(s) failed to extract: {failed[:20]} "
            "(past the end of a file? check offset_s)")
    Path(a.outdir, "index.json").write_text(json.dumps(index, indent=1) + "\n")
    if index and not failed:
        subprocess.run([media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-framerate", "1", "-i", os.path.join(a.outdir, "pair_%04d.jpg"),
                        "-vf", f"tile={cols}x{rows}", "-fps_mode", "passthrough",
                        os.path.join(a.outdir, "psheet_%02d.jpg")])
    elif failed:
        log("contact sheets skipped: a missing pair would shift every tile after "
            "it. Fix the failed samples and re-run.")
    sheets = sorted(p.name for p in Path(a.outdir).glob("psheet_*.jpg"))
    print(json.dumps({"segments": len(clips), "samples": len(index),
                      "failed": failed, "sheets": sheets,
                      "outdir": os.path.abspath(a.outdir)}))
    if failed:
        sys.exit(1)


# ---- apply / smooth ------------------------------------------------------------------

def cmd_apply(a):
    job = A.load_job(a.job, need_offset=False)
    enable = set(json.loads(Path(a.decisions).read_text())["enable_v2"])
    pm, _, timeline = get_timeline(job)
    fps = parse_fps(job.get("fps", "24"))
    # a live PiP inset needs camera B under it: keep those enabled even if
    # the decisions forgot them, so the two files cannot drift apart
    live_pip = v3_starts(timeline)
    kept = sorted(live_pip - enable)
    changed, enabled_n, missing = toggle_v2(timeline, enable | live_pip)
    pm.SaveProject()
    shortest, n_runs = shortest_run_s(timeline, fps)
    report = {"v2_enabled": enabled_n, "changed": changed,
              "requested_not_found": missing, "pip_bases_kept": kept,
              "runs": n_runs, "shortest_run_s": round(shortest, 2)}
    if missing:
        report["note"] = "record starts not on the timeline: re-dump and re-map, it was edited"
    if shortest < A.min_run_s(job) and n_runs > 1:
        report["WARNING"] = f"an angle run of {shortest:.2f}s flickers: run `smooth`"
    print(json.dumps(report))


def cmd_smooth(a):
    job = A.load_job(a.job, need_offset=False)
    min_s = a.min_run_s if a.min_run_s is not None else A.min_run_s(job)
    pm, _, timeline = get_timeline(job)
    fps = parse_fps(job.get("fps", "24"))
    pip_starts = v3_starts(timeline)
    segs = ab_segments(track_items(timeline, 2), pip_starts)
    flips = A.smooth(segs, min_s * float(fps))
    # disabling camera B under a live PiP would leave a floating inset over
    # camera A: keep those on and report them (re-run `pip` without them)
    conflicts = sorted(s["start"] for s in segs if s["start"] in pip_starts and s["angle"] == "a")
    enable = {s["start"] for s in segs if s["angle"] == "b"} | set(conflicts)
    Path(a.out).write_text(json.dumps({"enable_v2": sorted(enable)}, indent=1) + "\n")
    changed = 0
    if flips:
        changed, _, _ = toggle_v2(timeline, enable)
        pm.SaveProject()
    shortest, n_runs = shortest_run_s(timeline, fps)   # re-read, not bookkeeping
    report = {"min_run_s": min_s, "segments": len(segs), "flipped": flips,
              "applied": changed, "pip_conflicts": conflicts, "runs": n_runs,
              "shortest_run_s": round(shortest, 2), "out": os.path.abspath(a.out)}
    if shortest < min_s and n_runs > 1:
        report["WARNING"] = "short runs remain (pip conflicts or gaps): investigate"
    print(json.dumps(report, indent=1))


# ---- PiP ------------------------------------------------------------------------------

def set_shadow(tool, p):
    """Fusion Shadow: ShadowOffset is an ABSOLUTE screen point, (0.5, 0.5) =
    straight under the input, so the relative offset gets 0.5 added."""
    dx, dy = p["shadow_offset"]
    tool.SetInput("ShadowOffset", {1: 0.5 + float(dx), 2: 0.5 + float(dy), 3: 0.0})
    tool.SetInput("Softness", float(p["shadow_softness"]))
    tool.SetInput("Alpha", float(p["shadow_alpha"]))


def build_pip_comp(item, p, tl_w, tl_h):
    """Give a V3 clip the rounded, shadowed inset look as a Fusion comp.

    Graph: MediaIn -> Merge over a transparent Background with a rounded
    RectangleMask as effect mask (optional outline underneath) -> Transform
    (scale about the centre, slide into the corner) -> Shadow -> MediaOut.

    Comp lifecycle: DeleteFusionCompByName refuses the comp currently LOADED
    on the clip and AddFusionComp loads the new one, so add + load the new
    comp first and delete the old ones after (the other order piles comps up).
    """
    g = A.pip_geometry(p, tl_w=tl_w, tl_h=tl_h)["fusion"]
    old = list(item.GetFusionCompNameList() or [])
    comp = item.AddFusionComp()
    if not comp:
        return False
    new_name = next((n for n in item.GetFusionCompNameList() or [] if n not in old), None)
    if new_name:
        item.LoadFusionCompByName(new_name)
    for name in old:
        if not item.DeleteFusionCompByName(name):
            log(f"WARN: could not delete old comp {name!r} at {item.GetStart()}")
    mi, mo = comp.FindTool("MediaIn1"), comp.FindTool("MediaOut1")
    if not mi or not mo:
        return False

    def add(tool_id):
        t = comp.AddTool(tool_id, -32768, -32768)
        if not t:
            raise RuntimeError(f"AddTool({tool_id}) failed")
        return t

    def xy(v):
        return {1: float(v[0]), 2: float(v[1]), 3: 0.0}

    (cx, cy), (w, h) = g["mask_center"], g["mask_size"]
    clear = add("Background")
    clear.SetInput("TopLeftAlpha", 0.0)
    mask = add("RectangleMask")
    mask.SetInput("Center", xy((cx, cy)))
    mask.SetInput("Width", w)
    mask.SetInput("Height", h)
    mask.SetInput("CornerRadius", float(p["corner_radius"]))
    vid = add("Merge")
    vid.ConnectInput("Background", clear)
    vid.ConnectInput("Foreground", mi)
    vid.ConnectInput("EffectMask", mask)
    framed = vid
    oa = float(p.get("outline_alpha") or 0.0)
    if oa > 0 and float(p.get("outline_px") or 0) > 0:
        ox, oy = p["outline_px"] * 2 / tl_w, p["outline_px"] * 2 / tl_h
        paint = add("Background")
        r, gg, b = p["outline_rgb"]
        for ch, v in (("Red", r), ("Green", gg), ("Blue", b), ("Alpha", oa)):
            paint.SetInput(f"TopLeft{ch}", float(v))
        omask = add("RectangleMask")
        omask.SetInput("Center", xy((cx, cy)))
        omask.SetInput("Width", w + ox)
        omask.SetInput("Height", h + oy)
        omask.SetInput("CornerRadius", float(p["corner_radius"]) + ox / 2)
        clear2 = add("Background")
        clear2.SetInput("TopLeftAlpha", 0.0)
        outline = add("Merge")
        outline.ConnectInput("Background", clear2)
        outline.ConnectInput("Foreground", paint)
        outline.ConnectInput("EffectMask", omask)
        framed = add("Merge")
        framed.ConnectInput("Background", outline)
        framed.ConnectInput("Foreground", vid)
    xf = add("Transform")
    xf.ConnectInput("Input", framed)
    xf.SetInput("Size", g["transform_size"])
    xf.SetInput("Center", xy(g["transform_center"]))
    sh = add("Shadow")
    sh.ConnectInput("Input", xf)
    set_shadow(sh, p)
    mo.ConnectInput("Input", sh)
    return True


def cmd_pip(a):
    job = A.load_job(a.job, need_offset=False)
    pip = json.loads(Path(a.pip).read_text())
    targets = set(pip["pip_v3"])
    p = A.pip_params(job.get("pip"), {k: v for k, v in pip.items() if k != "pip_v3"})
    pm, project, timeline = get_timeline(job)
    mp = project.GetMediaPool()
    tl_w, tl_h = timeline_size(timeline)

    v1_items = timeline.GetItemListInTrack("video", 1) or []
    v1_by_start = {c["record_in"]: c for c in track_items(timeline, 1)}
    missing = sorted(t for t in targets if t not in v1_by_start)
    if missing:
        log(f"WARN: no V1 segment at record starts {missing} (timeline edited? re-dump)")
        targets -= set(missing)

    primary = job.get("primary_path")
    item = v1_items[0].GetMediaPoolItem() if v1_items else None
    if primary and (not item or item.GetClipProperty("File Path") != primary):
        item = pool_by_path(mp.GetRootFolder()).get(primary)
    if item is None:
        sys.exit(f"camera A is not in the media pool: {primary}")

    inspector = None
    if p["style"] == "inspector":
        info = media.probe(item.GetClipProperty("File Path") or primary)
        geo = A.pip_geometry(p, src_w=info["width"] or tl_w, src_h=info["height"] or tl_h,
                             tl_w=tl_w, tl_h=tl_h)
        inspector = {**geo["inspector"], **(pip.get("inspector") or {})}

    while (timeline.GetTrackCount("video") or 0) < 3:
        if not timeline.AddTrack("video"):
            sys.exit("AddTrack(video) failed")
    timeline.SetTrackName("video", 3, PIP_TRACK_NAME)

    # idempotent: clear earlier insets, but ONLY clips that start at a V1
    # segment start (ours by construction). Anything else on V3 is the
    # user's own parked work and stays.
    old = timeline.GetItemListInTrack("video", 3) or []
    ours = [it for it in old if it.GetStart() in v1_by_start]
    if ours and not delete_clips_checked(timeline, ours):
        sys.exit("could not clear the existing V3 insets (DeleteClips failed even "
                 "on the Edit page): aborting before any append")
    if len(old) > len(ours):
        log(f"left {len(old) - len(ours)} V3 clip(s) alone (not at a V1 segment start)")

    v2_items = {it.GetStart(): it for it in timeline.GetItemListInTrack("video", 2) or []}
    infos = []
    for start in sorted(targets):
        seg = v1_by_start[start]
        infos.append({"mediaPoolItem": item, "trackIndex": 3,
                      "startFrame": seg["left_offset"],
                      "endFrame": seg["left_offset"] + seg["duration"],
                      "recordFrame": start, "mediaType": 1})
    # one call: every scripting call is a cross-process round trip
    added = list((mp.AppendToTimeline(infos) or []) if infos else [])
    if len(added) != len(infos):
        got = {it.GetStart() for it in added}
        for info in infos:   # per-item retry for whatever the batch dropped
            if info["recordFrame"] not in got:
                added += list(mp.AppendToTimeline([info]) or [])
        if len(added) != len(infos):
            log(f"WARN: appended {len(added)} of {len(infos)} insets")
    failed, enabled_v2 = [], 0
    for it in added:
        start = it.GetStart()
        if p["style"] == "fusion":
            try:
                ok = build_pip_comp(it, p, tl_w, tl_h)
            except RuntimeError as e:
                ok = False
                log(f"WARN: {e} at {start}")
            if not ok:
                failed.append(start)
        else:
            for k, v in inspector.items():
                if not it.SetProperty(k, v):
                    failed.append(start)
                    log(f"WARN: SetProperty({k}) failed at {start}")
        v2 = v2_items.get(start)
        if v2 and not v2.GetClipEnabled():
            v2.SetClipEnabled(True)
            enabled_v2 += 1
    pm.SaveProject()
    print(json.dumps({"v3_added": len(added), "v2_also_enabled": enabled_v2,
                      "style": p["style"], "corner": p["corner"],
                      "failed": sorted(set(failed)), "requested_not_found": missing}))


def cmd_restyle(a):
    job = A.load_job(a.job, need_offset=False)
    pip = json.loads(Path(a.pip).read_text()) if a.pip else {}
    p = A.pip_params(job.get("pip"), {k: v for k, v in pip.items() if k != "pip_v3"})
    pm, _, timeline = get_timeline(job)
    tl_w, tl_h = timeline_size(timeline)
    rebuilt, skipped, failed = 0, 0, 0
    for it in timeline.GetItemListInTrack("video", 3) or []:
        ours = False
        for k in range(1, (it.GetFusionCompCount() or 0) + 1):
            comp = it.GetFusionCompByIndex(k)
            tools = (comp.GetToolList() or {}).values() if comp else []
            if any(t.GetAttrs().get("TOOLS_RegID") == "Shadow" for t in tools):
                ours = True   # our comps carry a Shadow tool; user clips don't
                break
        if not ours:
            skipped += 1
            continue
        try:
            ok = build_pip_comp(it, p, tl_w, tl_h)
        except RuntimeError as e:
            ok = False
            log(f"WARN: {e} at {it.GetStart()}")
        rebuilt += ok
        failed += not ok
    pm.SaveProject()
    multi = [it.GetStart() for it in timeline.GetItemListInTrack("video", 3) or []
             if (it.GetFusionCompCount() or 0) > 1]
    print(json.dumps({"rebuilt": rebuilt, "skipped": skipped, "failed": failed,
                      "clips_with_multiple_comps": len(multi)}))


# ---- transform ---------------------------------------------------------------------------

def cmd_transform(a):
    """Static Inspector properties for every clip on one track, e.g. camera B
    mounted facing the speaker films upside down: {"RotationAngle": 180.0,
    "ZoomX": 1.15, "ZoomY": 1.15}. Positive Tilt moves the image UP,
    positive Pan moves it right. record_lt: only clips starting before that
    frame (a single-camera section appended later must stay as it is)."""
    props = json.loads(Path(a.props).read_text())
    job = A.load_job(a.job, need_offset=False)
    pm, _, timeline = get_timeline(job)
    items = timeline.GetItemListInTrack("video", int(a.track)) or []
    if a.record_lt is not None:
        items = [it for it in items if it.GetStart() < int(a.record_lt)]
    failed = []
    for it in items:
        for k, v in props.items():
            if not it.SetProperty(k, v):
                failed.append([it.GetStart(), k])
    pm.SaveProject()
    print(json.dumps({"track": int(a.track), "clips": len(items), "props": props,
                      "failed": failed}))


# ---- verify -----------------------------------------------------------------------------

def cmd_verify(a):
    """Export the rendered composite at each segment's midpoint.

    project.ExportCurrentFrameAsStill writes the exact rendered frame (no
    UI, full resolution) but only from the Edit page, and it exports what
    the viewer currently SHOWS: wait for the playhead read-back, then let
    Fusion render (a fresh comp needs ~4 s; sooner returns the unmasked
    source). Property read-backs are not verification."""
    job = A.load_job(a.job, need_offset=False)
    fps = parse_fps(job.get("fps", "24"))
    resolve = connect()
    _, project, timeline = get_timeline(job)
    check_never_touch(job, timeline.GetName())
    prev = resolve.GetCurrentPage()
    if prev != "edit":
        resolve.OpenPage("edit")
    v1 = {c["record_in"]: c for c in track_items(timeline, 1)}
    os.makedirs(a.outdir, exist_ok=True)
    shots, fallbacks = [], 0
    try:
        for start in a.starts:
            c = v1.get(start)
            if not c:
                log(f"WARN: no segment starts at record frame {start}")
                continue
            target = tc(c["record_in"] + c["duration"] // 2, fps)
            timeline.SetCurrentTimecode(target)
            for _ in range(20):
                if timeline.GetCurrentTimecode() == target:
                    break
                time.sleep(0.25)
            else:
                log(f"WARN: the playhead never reached {target}")
                continue
            time.sleep(a.settle_s)
            out = os.path.abspath(os.path.join(a.outdir, f"verify_{start}_{target.replace(':', '')}.png"))
            if project.ExportCurrentFrameAsStill(out) and os.path.exists(out) \
                    and os.path.getsize(out) > 0:
                shots.append(out)
                continue
            if not media.is_macos():
                log(f"WARN: frame export failed at {target}; no screenshot fallback on this OS")
                continue
            log(f"WARN: frame export failed at {target}; window screenshot instead")
            wid = resolve_window_id()
            cmd = ["screencapture", "-x", out] if wid is None else \
                  ["screencapture", "-x", "-l", str(wid), out]
            subprocess.run(cmd)
            shots.append(out)
            fallbacks += 1
    finally:
        if prev and prev != "edit":
            resolve.OpenPage(prev)
    print(json.dumps({"shots": shots, "window_screenshots": fallbacks,
                      "note": "read every capture: is the right camera on, is the "
                              "inset clear of the action, any frame edge showing?"}))


def main():
    ap = argparse.ArgumentParser(
        description="Apply multicam angle decisions to a DaVinci Resolve timeline "
                    "(needs Resolve Studio running).",
        epilog="The module docstring (this file's header) documents job.json.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, func, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        p.add_argument("job", help="angle_job.json")
        p.set_defaults(func=func)
        return p

    p = add("backup", cmd_backup, "duplicate the working timeline as a safety copy")
    p.add_argument("suffix")
    p = add("dump", cmd_dump, "write the live V1/V2/V3 items to JSON")
    p.add_argument("out")
    p = add("frames", cmd_frames, "side-by-side contact sheets of both cameras")
    p.add_argument("dump")
    p.add_argument("outdir")
    p.add_argument("only", nargs="?", help='{"record_in": [...]}: sample only these')
    p = add("apply", cmd_apply, "set exactly the V2 clips in enable_v2 enabled")
    p.add_argument("decisions")
    p = add("pip", cmd_pip, "camera-A insets on V3 (idempotent)")
    p.add_argument("pip")
    p = add("restyle", cmd_restyle, "rebuild the Fusion PiP look in place")
    p.add_argument("pip", nargs="?")
    p = add("smooth", cmd_smooth, "live anti-flicker pass on camera A/B runs")
    p.add_argument("out")
    p.add_argument("--min-run-s", type=float)
    p = add("transform", cmd_transform, "static Inspector properties on one track")
    p.add_argument("track", type=int)
    p.add_argument("props", help='JSON file, e.g. {"RotationAngle": 180.0, "ZoomX": 1.15, "ZoomY": 1.15}')
    p.add_argument("record_lt", nargs="?", type=int)
    p = add("verify", cmd_verify, "export rendered frames at segment midpoints")
    p.add_argument("outdir")
    p.add_argument("starts", nargs="+", type=int, help="segment record start frames")
    p.add_argument("--settle-s", type=float, default=4.0)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
