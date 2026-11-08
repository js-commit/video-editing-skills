#!/usr/bin/env python3
"""Flicker audit of an edited Resolve timeline (a-roll + b-roll bricks).

Rebuilds, frame by frame, which SHOT the viewer actually sees (the top-most
enabled item across all video tracks) and reports every visible run shorter
than --min-run-s: those play as a flash. Also reports:
  short-item        a sub-minimum shot on any track (silence-cut slivers)
  aroll-gap         empty frames between consecutive items on an a-roll track
  brick-near-cut    a brick that starts a few frames AFTER, or ends a few frames
                    BEFORE, a lower-track cut, so the a-roll flashes in between
  pixel-flicker     (--render) two picture changes closer than --min-run-s in a
                    low-res render, whatever the cause

Shots are merged before judging: neighbouring pieces of the same source that
continue each other (same file, next in-point = previous out-point) are one
shot to the viewer, so invisible seams are not reported.

Required result: 0 findings, absolute (never "no new findings" against an
earlier audit). Fix brick edges with ripple_extend.py --snap-top-track or
close_gaps.py, slivers with seam_audit.py --plan + ripple_extend.py --plan.

Usage:
  flicker_audit.py --project P --timeline T [--min-run-s 0.6]
                   [--aroll-tracks auto|1|1,2] [--track-name "B-roll bricks"]
                   [--render OUT.mp4 --upload-box-off] [-o report.json]

--aroll-tracks auto = every video track (except the brick track) that covers
at least 80 % of the timeline: camera tracks run end to end, overlays do not.
--render uses the Deliver page's current format at 540p. Resolve's "Upload
directly to YouTube" box can stay ticked for a whole session after any
YouTube preset and the API can neither see nor clear it, so --render refuses
unless --upload-box-off says the user has checked that it is unticked. The
Deliver page's settings are saved as a temporary render preset and loaded back
afterwards; only its own render job is added, started and then removed.

Exit codes: 0 audited (the findings count is the gate), 5 Resolve's log shows
the audit render being uploaded (tell the user at once).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402


# ---- pure logic (unit-tested on synthetic tracks) --------------------------

def merge_track(items):
    """items: dicts {name, start, end, enabled, src_in, still, media}, any order.
    Merges source-continuous neighbours (and chained copies of one still)."""
    items = sorted(items, key=lambda i: i["start"])
    merged = []
    for it in items:
        p = merged[-1] if merged else None
        if p and p["media"] == it["media"] and p["end"] == it["start"] and p["enabled"] == it["enabled"] \
                and (p["src_in"] + (p["end"] - p["start"]) == it["src_in"] or it.get("still")):
            p["end"] = it["end"]
            p["pieces"] = p.get("pieces", 1) + 1
        else:
            merged.append(dict(it))
    return merged


def visible_runs(tracks, end_frame):
    """tracks: {index: [merged items]}. Top-most enabled item per frame ->
    runs [{shot: (track, item_index) | None, start, end}]."""
    order = sorted(tracks.keys(), reverse=True)
    idx = {k: 0 for k in order}
    runs, cur = [], None
    for f in range(end_frame):
        shown = None
        for k in order:
            items = tracks[k]
            i = idx[k]
            while i < len(items) and items[i]["end"] <= f:
                i += 1
            idx[k] = i
            if i < len(items) and items[i]["start"] <= f < items[i]["end"] and items[i]["enabled"]:
                shown = (k, i)
                break
        if cur and cur["shot"] == shown:
            cur["end"] = f + 1
        else:
            cur = {"shot": shown, "start": f, "end": f + 1}
            runs.append(cur)
    return runs


def auto_aroll_tracks(tracks, end_frame, brick_idx, min_cover=0.8):
    out = []
    for k, items in sorted(tracks.items()):
        if k == brick_idx or end_frame <= 0:
            continue
        cover = sum(i["end"] - i["start"] for i in items)
        if cover >= min_cover * end_frame:
            out.append(k)
    return out or [min(tracks)] if tracks else []


def find_flicker(tracks, end_frame, fps, min_f, aroll_tracks, brick_idx, names=None):
    """All structural findings. tracks: {index: merged items}. Frames are
    relative to the timeline start. Returns a list of finding dicts."""
    names = names or {}
    found = []

    def add(kind, start, end, msg):
        found.append({"kind": kind, "start_f": start, "end_f": end, "tc": B.tc(start, fps),
                      "dur_s": round((end - start) / fps, 2), "msg": msg})

    # 1. visible micro-runs
    for r in visible_runs(tracks, end_frame):
        d = r["end"] - r["start"]
        if 0 < d < min_f:
            if r["shot"]:
                k, i = r["shot"]
                what = f"V{k} {tracks[k][i]['name']}"
            else:
                what = "EMPTY (black)"
            add("visible-micro-run", r["start"], r["end"], f"viewer sees {what} for only {d} frames")
    # 2. sub-minimum shots on any track
    for k, items in tracks.items():
        for it in items:
            d = it["end"] - it["start"]
            if d < min_f and it["enabled"]:
                add("short-item", it["start"], it["end"],
                    f"V{k} {names.get(k, '')!r} item {it['name']} is {d} frames")
    # 3. gaps on a-roll tracks
    for k in aroll_tracks:
        items = tracks.get(k, [])
        for p, n in zip(items, items[1:]):
            if n["start"] > p["end"]:
                add("aroll-gap", p["end"], n["start"], f"V{k} gap of {n['start'] - p['end']} frames")
    # 4. bricks a flash away from a lower-track cut they do not cover
    if brick_idx is not None and brick_idx in tracks:
        bounds = sorted({b for k in tracks if k != brick_idx for it in tracks[k] for b in (it["start"], it["end"])})
        covered = sorted((it["start"], it["end"]) for it in tracks[brick_idx] if it["enabled"])

        def exposed(a, b):
            return any(not any(s <= f < e for s, e in covered) for f in range(a, b))

        for it in tracks[brick_idx]:
            s, e = it["start"], it["end"]
            for b in bounds:
                if 0 < s - b < min_f and exposed(b, s):
                    add("brick-near-cut", b, s, f"V{brick_idx} brick {it['name']} starts {s - b} frames AFTER "
                                                f"the cut at {B.tc(b, fps)}; the a-roll flashes in between")
                if 0 < b - e < min_f and exposed(e, b):
                    add("brick-near-cut", e, b, f"V{brick_idx} brick {it['name']} ends {b - e} frames BEFORE "
                                                f"the cut at {B.tc(b, fps)}; the a-roll flashes in between")
    found.sort(key=lambda x: x["start_f"])
    return found


def pixel_findings(cuts, fps, min_run_s):
    out = []
    for p, n in zip(cuts, cuts[1:]):
        if n - p < min_run_s:
            out.append({"kind": "pixel-flicker", "start_f": int(round(p * fps)), "end_f": int(round(n * fps)),
                        "tc": B.tc(int(round(p * fps)), fps), "dur_s": round(n - p, 2),
                        "msg": f"two picture changes {n - p:.2f}s apart at {p:.2f}s -> {n:.2f}s (rendered)"})
    return out


# ---- Resolve side ----------------------------------------------------------

def dump_tracks(tl):
    t0 = tl.GetStartFrame()
    tracks, names = {}, {}
    for idx in range(1, tl.GetTrackCount("video") + 1):
        items = []
        for it in tl.GetItemListInTrack("video", idx) or []:
            mpi = it.GetMediaPoolItem()
            items.append({"name": it.GetName(), "start": it.GetStart() - t0, "end": it.GetEnd() - t0,
                          "enabled": bool(it.GetClipEnabled()), "src_in": it.GetLeftOffset(),
                          "still": bool(mpi and mpi.GetClipProperty("Type") == "Still"),
                          "media": (mpi.GetClipProperty("File Path") if mpi else it.GetName())})
        tracks[idx] = merge_track(items)
        names[idx] = tl.GetTrackName("video", idx)
    return tracks, names, tl.GetEndFrame() - t0


def render_and_detect(proj, tl, path, thresh):
    """Render a 540p copy with ONE job of our own and scene-detect it. The
    Deliver page's settings (and the current timeline) are put back afterwards,
    and our job is removed from the queue, whether or not the render worked.
    Returns (file, scene cut times, uploaded per Resolve's log)."""
    out_dir = os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    preset = f"flicker-audit restore {time.strftime('%Y%m%d-%H%M%S')}"
    if not proj.SaveAsNewRenderPreset(preset):
        sys.exit("could not save the Deliver page's settings as a temporary render preset, so they could not be "
                 "put back after the audit render: not rendering. Run the audit without --render.")
    prev_tl = proj.GetCurrentTimeline()
    job = None
    try:
        proj.SetCurrentTimeline(tl)
        if not proj.SetRenderSettings({"SelectAllFrames": True, "TargetDir": out_dir, "CustomName": stem,
                                       "FormatWidth": 960, "FormatHeight": 540,
                                       "ExportVideo": True, "ExportAudio": False}):
            sys.exit("SetRenderSettings was refused (is the output folder writable?)")
        job = proj.AddRenderJob()
        if not job:
            sys.exit("AddRenderJob failed (is the Deliver page set to a video format?)")
        proj.StartRendering([job], isInteractiveMode=False)
        while proj.IsRenderingInProgress():
            time.sleep(3)
        B.log("render:", proj.GetRenderJobStatus(job))
    finally:
        if job and not proj.DeleteRenderJob(job):
            B.log(f"WARN: could not remove the audit render job {job} from the render queue")
        if proj.LoadRenderPreset(preset):
            proj.DeleteRenderPreset(preset)
        else:
            B.log(f"WARN: could not load the Deliver page's settings back; they are saved as render preset "
                  f"{preset!r}: load it on the Deliver page, then delete it")
        if prev_tl:
            proj.SetCurrentTimeline(prev_tl)
    cands = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith(stem)]
    if not cands:
        sys.exit(f"render produced nothing in {out_dir}")
    vid = max(cands, key=os.path.getmtime)
    time.sleep(2)  # give Resolve's log a moment to record an upload
    uploaded = B.vr().youtube_upload_logged(vid)
    r = B.media.run([B.media.ffmpeg(), "-nostdin", "-i", vid, "-vf", f"select='gt(scene,{thresh})',showinfo",
                     "-f", "null", "-"], capture_output=True, text=True)
    cuts = [float(ln.split("pts_time:")[1].split()[0]) for ln in r.stderr.splitlines() if "pts_time:" in ln]
    return vid, cuts, uploaded


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--min-run-s", type=float, default=0.6,
                    help="shortest shot that does not read as a flash (13 frames flickers, 16 does not)")
    ap.add_argument("--aroll-tracks", default="auto", help="'auto' or comma list of a-roll video tracks")
    ap.add_argument("--track-name", default=B.BRICK_TRACK, help="the brick track's name ('' = none)")
    ap.add_argument("--render", default=None, help="also render a 540p copy here and scene-detect it")
    ap.add_argument("--upload-box-off", action="store_true",
                    help="with --render: the user has checked that the Deliver page's 'Upload directly to YouTube' "
                         "box is unticked (the API cannot see it)")
    ap.add_argument("--scene-thresh", type=float, default=0.3)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    if a.render and not a.upload_box_off:
        sys.exit("refusing --render: it goes through the Deliver page, whose 'Upload directly to YouTube' box can "
                 "stay ticked for the whole Resolve session and is invisible to the scripting API, so the audit "
                 "render could be published. Ask the user to open the Deliver page (Shift+8) and untick it, then "
                 "re-run with --render ... --upload-box-off.")
    _, proj = B.open_project(a.project)
    tl = B.timeline_by_name(proj, a.timeline)
    fps = B.fps_of(tl)
    tracks, names, end_frame = dump_tracks(tl)
    explicit = "--track-name" in sys.argv
    brick_idx = B.find_brick_track(tl, a.track_name, explicit=explicit)
    if a.aroll_tracks == "auto":
        aroll = auto_aroll_tracks(tracks, end_frame, brick_idx)
    else:
        aroll = [int(x) for x in a.aroll_tracks.split(",") if x.strip()]
    min_f = int(round(a.min_run_s * fps))
    found = find_flicker(tracks, end_frame, fps, min_f, aroll, brick_idx, names)
    rep = {"timeline": a.timeline, "fps": fps, "min_run_s": a.min_run_s, "aroll_tracks": aroll,
           "brick_track": brick_idx}
    uploaded = False
    if a.render:
        vid, cuts, uploaded = render_and_detect(proj, tl, a.render, a.scene_thresh)
        rep["render"] = {"file": vid, "scene_cuts": cuts, "youtube_upload_logged": uploaded}
        found = sorted(found + pixel_findings(cuts, fps, a.min_run_s), key=lambda x: x["start_f"])
    rep["findings"] = found
    for f in found:
        B.log(f"{f['tc']}  {f['kind']:18} {f['msg']}")
    B.log(f"{len(found)} findings (min run {a.min_run_s}s, a-roll tracks {aroll}, brick track {brick_idx})")
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(rep, fh, indent=1)
    print(json.dumps({"findings": len(found), "kinds": sorted({f["kind"] for f in found}),
                      "youtube_upload_logged": uploaded}))
    if uploaded:
        B.log("WARNING: Resolve's log shows the audit render being UPLOADED to YouTube: the Deliver page's "
              "'Upload directly to YouTube' box was ticked. Tell the user now; they delete it in YouTube Studio "
              "and untick the box.")
        sys.exit(5)


if __name__ == "__main__":
    main()
