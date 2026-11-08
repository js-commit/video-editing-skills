#!/usr/bin/env python3
"""Build (or rebuild) a single-track DaVinci Resolve timeline from an ordered
SEQUENCE of source slices - any media, any order, pickups interleaved with the
main take - in ONE AppendToTimeline call.

When a review changes many cuts at once (silences trimmed, stumbles restored,
pickups inserted), rebuilding from a sequence beats chaining many ripple edits.
Pair it with seam_plan_apply.py to fold a seam_audit.py plan into the sequence
and rebuild. Needs DaVinci Resolve Studio (external scripting).

job.json:
{
  "project": "my-review", "timeline": "first cut v2",
  "never_touch": ["first cut"],               # timelines this job must never delete
  "replace": false,                           # true: delete and rebuild a timeline of the same name
  "fps": "29.97",                             # optional (default: the first sequence media's rate)
  "track_name": "Camera A",
  "width": 3840, "height": 2160,              # optional (default settings editor.timeline_resolution)
  "sequence": [{"media": "/abs/take.mp4", "src_in_s": 5.77, "src_out_s": 19.14,
                "txt": "...", "marker": {"name": "...", "note": "...", "color": "Sky"}}, ...]
}
If the job's timeline already exists, the new one is built as "<name> v2" (v3...)
beside it; with "replace": true the old one is deleted first instead. Backups,
settings editor.never_touch_timelines and the job's never_touch names are
refused. Every media file must already be in the project's media pool.

Usage: resolve_sequence.py job.json [report.json]
Prints a JSON summary; report.json gets record_s for every sequence item.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit.resolve import (check_never_touch, connect, delete_clips_checked,  # noqa: E402
                            ensure_resolution, job_fps, log, parse_fps, pool_by_path)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) > 1 else 2)
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)
    seq = job["sequence"]
    resolve = connect()
    pm = resolve.GetProjectManager()
    project = pm.LoadProject(job["project"])
    if not project:
        sys.exit(f"could not load project {job['project']!r}")
    mp = project.GetMediaPool()
    by_path = pool_by_path(mp.GetRootFolder())
    for it in seq:
        if it["media"] not in by_path:
            sys.exit(f"not in the media pool: {it['media']}")

    tl_name = job["timeline"]
    check_never_touch(job, tl_name)
    existing = {}
    for i in range(1, (project.GetTimelineCount() or 0) + 1):
        t = project.GetTimelineByIndex(i)
        if t:
            existing[t.GetName()] = t
    if tl_name in existing:
        if job.get("replace"):
            mp.DeleteTimelines([existing[tl_name]])
            log(f"deleted existing timeline {tl_name!r} (replace requested)")
        else:
            n = 2
            while f"{tl_name} v{n}" in existing:
                n += 1
            log(f"timeline {tl_name!r} exists; building {tl_name + ' v' + str(n)!r} beside it "
                f"(set \"replace\": true in the job to rebuild it in place)")
            tl_name = f"{tl_name} v{n}"
    timeline = mp.CreateEmptyTimeline(tl_name)
    if not timeline:
        sys.exit(f"could not create timeline {tl_name!r}")
    project.SetCurrentTimeline(timeline)
    ensure_resolution(project, timeline, job.get("width"), job.get("height"))
    if not timeline.SetStartTimecode("00:00:00:00"):
        log("WARN: SetStartTimecode failed")
    if job.get("track_name"):
        timeline.SetTrackName("video", 1, job["track_name"])
        timeline.SetTrackName("audio", 1, job["track_name"])

    fps = float(parse_fps(job_fps(job)))
    tl_start = timeline.GetStartFrame()
    record = tl_start
    planned, report = [], []
    for i, it in enumerate(seq):
        src_in, src_out = int(it["src_in_s"] * fps), int(it["src_out_s"] * fps)
        dur = src_out - src_in
        if dur <= 0:
            sys.exit(f"zero-length item {i}: {it}")
        planned.append({"mediaPoolItem": by_path[it["media"]], "startFrame": src_in,
                        "endFrame": src_out, "trackIndex": 1, "recordFrame": record})
        report.append({"i": i, "media": Path(it["media"]).name, "record_frame": record - tl_start,
                       "record_s": round((record - tl_start) / fps, 3), "src_in_s": it["src_in_s"],
                       "src_out_s": it["src_out_s"], "dur_s": round(dur / fps, 3), "txt": it.get("txt", "")[:80]})
        record += dur

    items = mp.AppendToTimeline(planned) or []
    if len(items) != len(planned):
        log(f"batch landed {len(items)}/{len(planned)}; clearing and retrying clip by clip")
        leftovers = []
        for tt in ("video", "audio"):
            for ti in range(1, (timeline.GetTrackCount(tt) or 0) + 1):
                leftovers += timeline.GetItemListInTrack(tt, ti) or []
        if not delete_clips_checked(timeline, leftovers):
            sys.exit("could not clear the partial append")
        for p in planned:
            if not (mp.AppendToTimeline([p]) or []):
                sys.exit(f"append failed at record frame {p['recordFrame']}")

    for it, r in zip(seq, report):
        m = it.get("marker")
        if m and not timeline.AddMarker(r["record_frame"], m.get("color", "Sky"), m["name"], m.get("note", ""), 1):
            log(f"WARN: AddMarker failed at {r['record_frame']}")

    pm.SaveProject()
    nv = len(timeline.GetItemListInTrack("video", 1) or [])
    na = len(timeline.GetItemListInTrack("audio", 1) or [])
    if nv != len(planned) or na != len(planned):
        sys.exit(f"LOST AFTER SAVE: video {nv}, audio {na}, planned {len(planned)}")
    out = {"timeline": tl_name, "items": len(planned), "duration_s": round((record - tl_start) / fps, 3),
           "sequence": report}
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in out.items() if k != "sequence"}))


if __name__ == "__main__":
    main()
