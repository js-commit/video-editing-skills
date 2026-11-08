#!/usr/bin/env python3
"""Build the first cut as a timeline in DaVinci Resolve Studio (external
scripting; the free version cannot be scripted: import the .xml instead).

  single    one camera: every keep of the cut list on V1/A1.
  multicam  two or more cameras of the SAME take: every keep laid on each
            camera's own tracks (camera N video on V N, audio on A N), offset
            corrected so the angles stay in sync.

The scripting API cannot create real multicam clips, so multicam is the
scriptable equivalent: secondary cameras' video can be disabled per clip (the
timeline plays as camera A) and switching a segment's angle is enabling the clip
above it (or select V1+V2 and use Convert to Multicam in the UI afterwards).
EVERY camera's audio is kept: cameras carry different mics, and dropping one can
lose the good mic. Mute a camera's audio track ("audio_muted") instead of
omitting it.

All clips go in with ONE MediaPool.AppendToTimeline call (each call is a
cross-process round trip); explicit recordFrame values keep placement exact. If
the batch does not land 1:1 the timeline is cleared and filled clip by clip.
After saving, per-track item counts are read back: an errored append can leave
items that vanish on save.

An existing timeline of the same name is never replaced unless you pass
--replace (single) or "replace": true (job); otherwise a new name gets " v2",
" v3"... Names in "never_touch" are refused outright.

Usage:
  resolve_timeline.py single <video> [--cuts <stem>.aroll.tb.json] [--project NAME]
                      [--timeline NAME] [--report <work>/report.json] [--replace]
  resolve_timeline.py multicam job.json [--report <work>/report.json]

Multicam job JSON:
  {
    "project": "my-review",                 # created if missing
    "timeline": "first cut - multicam",
    "never_touch": ["my hand edit"],        # timelines this job must never delete
    "replace": false,
    "fps": "29.97",                         # Resolve timelineFrameRate (default: camera A's rate)
    "width": 3840, "height": 2160,          # optional (default settings editor.timeline_resolution)
    "cuts_json": "/abs/path/<stem>.aroll.tb.json",   # cut list on camera A's clock
    "cameras": [                            # first = camera A, the cut source
      {"path": "/abs/camA.mp4", "offset_s": 0.0, "name": "Camera A", "audio_muted": true},
      {"path": "/abs/camB.mp4", "offset_s": 3.35, "name": "Camera B", "enabled": false}
    ],
    "bins_root": "/abs/project/footage",    # optional: one media-pool bin per subfolder
    "bin_extensions": [".mp4", ".mov"],
    "secondary_rotate180": false            # camera B mounted upside down (copied to angle_job.json)
  }
A multicam build also writes angle_job.json next to the job (project, timeline,
never_touch, primary_path, secondary_path, secondary_rotate180, offset_s, fps):
the hand-off to the multicam-angles skill.
offset_s = how much LATER this camera started rolling than camera A
(camera time = camera A time - offset_s); measure it with sync_offset.py, never
from camera clocks. "enabled": false disables that camera's video clips;
"audio_muted": true disables its audio track (leave unmuted the camera wearing
the good mic).

Resolve must be running with Preferences > System > General > External
scripting using = Local. Exit 3 = Resolve did not answer (restart it).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import settings  # noqa: E402
from vidkit.resolve import (check_never_touch, connect, delete_clips_checked,  # noqa: E402
                            ensure_resolution, job_fps, log, parse_fps, pool_by_path)

def import_bins(mp, root, job):
    """One bin per subfolder of bins_root; import media files not yet in the pool."""
    bins_root = job.get("bins_root")
    if not bins_root:
        return {}
    exts = tuple(e.lower() for e in job.get("bin_extensions", [".mp4", ".mov"]))
    by_path = pool_by_path(root)
    existing = {f.GetName(): f for f in root.GetSubFolderList() or []}
    imported = {}
    for name in sorted(os.listdir(bins_root)):
        sub = os.path.join(bins_root, name)
        if not os.path.isdir(sub) or name.startswith("."):
            continue
        files = sorted(os.path.join(sub, f) for f in os.listdir(sub)
                       if f.lower().endswith(exts) and not f.startswith("."))
        if not files:
            continue
        folder = existing.get(name) or mp.AddSubFolder(root, name)
        if not folder:
            log(f"WARN: could not create bin {name}")
            continue
        need = [p for p in files if p not in by_path]
        if need:
            mp.SetCurrentFolder(folder)
            items = mp.ImportMedia(need) or []
            for it in items:
                p = it.GetClipProperty("File Path")
                if p:
                    by_path[p] = it
            log(f"bin {name}: imported {len(items)}/{len(need)} new ({len(files) - len(need)} already in pool)")
        imported[name] = len(files)
    mp.SetCurrentFolder(root)
    return imported


def free_name(project, mp, job):
    """The timeline name to build: replace the old one only when asked."""
    name = job["timeline"]
    check_never_touch(job, name)
    existing = {}
    for i in range(1, (project.GetTimelineCount() or 0) + 1):
        t = project.GetTimelineByIndex(i)
        if t:
            existing[t.GetName()] = t
    if name not in existing:
        return name
    if job.get("replace"):
        mp.DeleteTimelines([existing[name]])
        log(f"deleted existing timeline {name!r} (replace requested)")
        return name
    n = 2
    while f"{name} v{n}" in existing:
        n += 1
    log(f"timeline {name!r} exists; building {name + ' v' + str(n)!r} instead (pass --replace to rebuild it)")
    return f"{name} v{n}"


def add_markers(timeline, report_path, fps):
    if not report_path or not os.path.exists(report_path):
        return 0
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    colors = {"clipped-word seam": "Red", "short clip": "Yellow", "long pause": "Blue",
              "possible hidden retake": "Purple"}
    added = 0
    used = set()
    for rp in report.get("review_points", []):
        frame = int(float(rp["first_cut_s"]) * float(fps))
        while frame in used:          # one marker per frame
            frame += 1
        used.add(frame)
        if timeline.AddMarker(frame, colors.get(rp["kind"], "Cream"), rp["kind"], rp["note"][:250], 1):
            added += 1
    return added


def write_angle_job(job, job_path, tl_name, fps_s):
    """angle_job.json next to the multicam job: the hand-off to the multicam-angles skill."""
    if not job_path or len(job["cameras"]) < 2:
        return None
    a, b = job["cameras"][0], job["cameras"][1]
    out = Path(job_path).resolve().parent / "angle_job.json"
    data = {}
    if out.exists():
        with open(out, encoding="utf-8") as f:
            data = json.load(f)       # keep what the angle pass already added (angles, pip...)
    data.update({"project": job["project"], "timeline": tl_name,
                 "never_touch": sorted(set(data.get("never_touch", [])) | set(job.get("never_touch", []))),
                 "primary_path": a["path"], "secondary_path": b["path"],
                 "secondary_rotate180": bool(job.get("secondary_rotate180", False)),
                 "offset_s": float(b.get("offset_s", 0.0)), "fps": fps_s})
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return str(out)


def build(job, report=None, job_path=None):
    with open(job["cuts_json"], encoding="utf-8") as f:
        cuts = json.load(f)
    keeps = [c for c in cuts if c.get("operation") != "remove"]
    if not keeps:
        sys.exit("cut list has no keep segments")

    resolve = connect()
    pm = resolve.GetProjectManager()
    project = pm.LoadProject(job["project"]) or pm.CreateProject(job["project"])
    if not project:
        sys.exit(f"could not load or create project {job['project']!r}")

    fps_s = job_fps(job, job["cameras"][0]["path"])
    if not (project.GetTimelineCount() or 0):   # the frame rate locks once a timeline exists
        if not project.SetSetting("timelineFrameRate", fps_s):
            log(f"WARN: SetSetting(timelineFrameRate, {fps_s}) failed")

    mp = project.GetMediaPool()
    root = mp.GetRootFolder()
    import_bins(mp, root, job)

    by_path = pool_by_path(root)
    cams = []
    for cam in job["cameras"]:
        item = by_path.get(cam["path"])
        if item is None:
            mp.SetCurrentFolder(root)
            got = mp.ImportMedia([cam["path"]]) or []
            item = got[0] if got else None
        if item is None:
            sys.exit(f"camera file could not be imported: {cam['path']}")
        cams.append(dict(cam, item=item))

    tl_name = free_name(project, mp, job)
    timeline = mp.CreateEmptyTimeline(tl_name)
    if not timeline:
        sys.exit(f"could not create timeline {tl_name!r}")
    project.SetCurrentTimeline(timeline)
    ensure_resolution(project, timeline, job.get("width"), job.get("height"))
    if not timeline.SetStartTimecode("00:00:00:00"):   # cosmetic: rulers read as elapsed time
        log("WARN: SetStartTimecode 00:00:00:00 failed; ruler starts at " + str(timeline.GetStartTimecode()))
    while (timeline.GetTrackCount("video") or 0) < len(cams):
        if not timeline.AddTrack("video"):
            sys.exit("AddTrack(video) failed")
    while (timeline.GetTrackCount("audio") or 0) < len(cams):
        if not timeline.AddTrack("audio", "stereo"):
            sys.exit("AddTrack(audio) failed")
    for idx, cam in enumerate(cams, start=1):
        if cam.get("name"):
            timeline.SetTrackName("video", idx, cam["name"])
            timeline.SetTrackName("audio", idx, cam["name"])

    fps = parse_fps(fps_s)
    tl_start = timeline.GetStartFrame()
    record = tl_start
    skipped = []
    planned = []  # (clipInfo, seg_i, track, kind, disable_after)
    for seg_i, keep in enumerate(keeps):
        s, e = keep["start"], keep["start"] + keep["duration"]
        src_in, src_out = int(s * fps), int(e * fps)    # floor, as the TimeBolt importer does
        dur = src_out - src_in
        if dur <= 0:
            skipped.append((seg_i, "zero-length"))
            continue
        for track, cam in enumerate(cams, start=1):
            off = int(cam.get("offset_s", 0.0) * fps)
            ci_in, ci_out = src_in - off, src_out - off
            if ci_in < 0:
                skipped.append((seg_i, f"camera {track} not rolling yet"))
                continue
            info = {"mediaPoolItem": cam["item"], "startFrame": ci_in, "endFrame": ci_out,
                    "trackIndex": track, "recordFrame": record}
            if track == 1:
                planned.append((dict(info), seg_i, track, "av", False))   # video V1 + audio A1, linked
            else:
                # separate appends so the video can be disabled while this camera's audio stays live
                planned.append((dict(info, mediaType=1), seg_i, track, "video", cam.get("enabled") is False))
                planned.append((dict(info, mediaType=2), seg_i, track, "audio", False))
        record += dur

    appended = 0
    items = mp.AppendToTimeline([p[0] for p in planned]) or []
    if len(items) == len(planned):
        appended, landed = len(items), planned
    else:
        log(f"batch append landed {len(items)}/{len(planned)} items; clearing and retrying clip by clip")
        leftovers = []
        for tt in ("video", "audio"):
            for ti in range(1, (timeline.GetTrackCount(tt) or 0) + 1):
                leftovers += timeline.GetItemListInTrack(tt, ti) or []
        if not delete_clips_checked(timeline, leftovers):
            sys.exit("could not clear the partial batch append: the timeline is partial, run again")
        landed = []
        for p in planned:
            got = mp.AppendToTimeline([p[0]]) or []
            if not got:
                skipped.append((p[1], f"camera {p[2]} {p[3]} append failed"))
                continue
            appended += len(got)
            landed.append(p)

    # disable by position: recordFrame is absolute, so the item on V(track) starting there is the planned clip
    disables = {}
    for a, _seg, track, kind, dis in planned:
        if dis and kind == "video":
            disables.setdefault(track, set()).add(a["recordFrame"])
    for track, recs in disables.items():
        for it in timeline.GetItemListInTrack("video", track) or []:
            if it.GetStart() in recs and not it.SetClipEnabled(False):
                log(f"WARN: SetClipEnabled(False) failed on V{track} @ {it.GetStart()}")
    for idx, cam in enumerate(cams, start=1):
        if cam.get("audio_muted") and not timeline.SetTrackEnable("audio", idx, False):
            log(f"WARN: could not disable audio track {idx}")

    markers = add_markers(timeline, report, fps)
    pm.SaveProject()
    want = {}
    for _a, _seg, track, kind, _dis in landed:
        if kind in ("av", "video"):
            want[("video", track)] = want.get(("video", track), 0) + 1
        if kind in ("av", "audio"):
            want[("audio", track)] = want.get(("audio", track), 0) + 1
    lost = [f"{tt} {ti}: {len(timeline.GetItemListInTrack(tt, ti) or [])}/{n}"
            for (tt, ti), n in sorted(want.items())
            if len(timeline.GetItemListInTrack(tt, ti) or []) != n]
    if lost:
        sys.exit("LOST AFTER SAVE: " + "; ".join(lost) + " - run the build again")
    angle_job = write_angle_job(job, job_path, tl_name, fps_s)
    print(json.dumps({"project": job["project"], "timeline": tl_name, "fps": fps_s, "angle_job": angle_job,
                      "keep_segments": len(keeps), "items_appended": appended, "markers": markers,
                      "timeline_duration_s": round(float((record - tl_start) / fps), 3),
                      "skipped": skipped}, indent=2))


def single_job(args):
    video = Path(args.video).expanduser().absolute()
    cuts = Path(args.cuts) if args.cuts else video.with_name(video.stem + ".aroll.tb.json")
    if not cuts.exists():
        sys.exit(f"no cut list at {cuts}: run the aroll-draft pipeline first")
    project = args.project
    if not project:
        try:
            root = settings.find_project_root(video)
        except Exception:
            root = None
        project = root.name if root else video.stem
    return {"project": project, "timeline": args.timeline or f"{video.stem} first cut",
            "never_touch": args.never_touch or [], "replace": args.replace,
            "cuts_json": str(cuts), "cameras": [{"path": str(video), "offset_s": 0.0}]}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sub.required = True
    sp = sub.add_parser("single", help="one camera")
    sp.add_argument("video")
    sp.add_argument("--cuts")
    sp.add_argument("--project", help="Resolve project (default: the project folder's name, else the video's stem)")
    sp.add_argument("--timeline", help="timeline name (default '<stem> first cut')")
    sp.add_argument("--never-touch", action="append", help="timeline name that must never be replaced")
    sp.add_argument("--replace", action="store_true", help="rebuild a timeline of the same name")
    sp.add_argument("--report", help="deliver.py's report.json: adds a marker per review point")
    sp = sub.add_parser("multicam", help="two or more cameras, from a job JSON")
    sp.add_argument("job")
    sp.add_argument("--report", help="deliver.py's report.json: adds a marker per review point")
    args = p.parse_args()

    job_path = None
    if args.cmd == "single":
        job = single_job(args)
    else:
        job_path = args.job
        with open(args.job, encoding="utf-8") as f:
            job = json.load(f)
    try:
        build(job, args.report, job_path)
    except settings.SettingMissing as e:
        settings.exit_missing(e)


if __name__ == "__main__":
    main()
