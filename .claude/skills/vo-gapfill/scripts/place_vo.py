#!/usr/bin/env python3
"""Insert a voiceover audio clip into a timeline gap, resizing the gap to fit.

Usage: place_vo.py job.json

The gap is located by a timeline marker at its start. The Resolve API has no clip-move operation,
so resizing the gap means delete + re-append of every item at/after the
gap end, shifted by the delta — clip-enabled state and non-default
transform properties are preserved, and markers past the gap ride along.
A zero-width gap (marker at a cut boundary) opens a new gap by rippling;
a marker at/past the last item appends at the end with no ripple.
Refuses never_touch timelines and duplicates the working timeline to
"<name> pre-vo backup" before any mutation.

job.json: project, timeline, never_touch, fps (optional: default the timeline's own rate), audio_path, bin,
marker_name (substring match), tail_pad_s (default 0.5), slack_s
(default 1.0 — if the VO already fits and the leftover gap is within
this, skip the ripple entirely; a whole-tail delete/re-append is not
worth a few frames).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit.resolve import (delete_clips_checked, duplicate_timeline,  # noqa: E402
                            get_timeline, log, media_seconds, parse_fps,
                            pool_by_path, tc, timelines)

TRANSFORM_KEYS = (
    "ZoomX", "ZoomY", "ZoomGang", "Pan", "Tilt", "RotationAngle",
    "CropLeft", "CropRight", "CropTop", "CropBottom", "CropSoftness",
    "AnchorPointX", "AnchorPointY", "Pitch", "Yaw", "FlipX", "FlipY",
    "Opacity")


def all_items(timeline):
    for kind in ("video", "audio"):
        for ti in range(1, (timeline.GetTrackCount(kind) or 0) + 1):
            for it in timeline.GetItemListInTrack(kind, ti) or []:
                yield kind, ti, it


def backup(project, timeline):
    base = timeline.GetName() + " pre-vo backup"
    existing = {t.GetName() for t in timelines(project)}
    name, n = base, 2
    while name in existing:
        name, n = f"{base} {n}", n + 1
    if not duplicate_timeline(project, timeline, name):
        sys.exit("DuplicateTimeline failed — refusing to mutate without a backup")
    log(f"backup: {name!r}")
    return name


def find_gap(timeline, marker_name):
    """Locate the gap and cache one pass over the whole timeline.

    Returns (gap_start, gap_end, items, markers, tl_start) where items is
    [(kind, track, item, start, end)] — every Resolve call is a
    cross-process RPC, so later stages reuse this instead of re-walking.
    """
    tl_start = int(timeline.GetStartFrame())
    markers = timeline.GetMarkers() or {}
    hits = [f for f, m in markers.items()
            if marker_name.lower() in (m.get("name") or "").lower()]
    if len(hits) != 1:
        sys.exit(f"marker matching {marker_name!r}: found {len(hits)}, need exactly 1 "
                 f"(markers: {[m.get('name') for m in markers.values()]})")
    gap_start = tl_start + int(hits[0])
    items, after = [], []
    for kind, ti, it in all_items(timeline):
        s, e = int(it.GetStart()), int(it.GetEnd())
        items.append((kind, ti, it, s, e))
        if s < gap_start < e:
            sys.exit(f"{kind} track {ti} item {it.GetName()!r} overlaps the "
                     f"marker at {gap_start} ({s}..{e}) — not a gap")
        if s >= gap_start:
            after.append(s)
    if not after:
        # marker at/past the last item: end-of-timeline append, no ripple
        log("no items after the marker — appending at the end of the timeline")
        after.append(gap_start)
    return gap_start, min(after), items, markers, tl_start


def snapshot_tail(items, gap_end):
    tail = []
    for kind, ti, it, s, e in items:
        if s < gap_end:
            continue
        rec = {"kind": kind, "track": ti, "item": it, "start": s, "end": e,
               "left": int(it.GetLeftOffset() or 0),
               "enabled": bool(it.GetClipEnabled()),
               "mpi": it.GetMediaPoolItem(), "name": it.GetName()}
        if kind == "video":
            props = it.GetProperty()  # argless = full dict in one RPC
            if not isinstance(props, dict):
                props = {k: it.GetProperty(k) for k in TRANSFORM_KEYS}
            rec["props"] = {k: v for k, v in props.items()
                            if k in TRANSFORM_KEYS and v is not None}
        tail.append(rec)
    return tail


def ripple(timeline, mp, tail, delta, fps):
    """Delete every tail item and re-append shifted by delta frames."""
    for t in tail:
        if t["mpi"] is None:
            sys.exit(f"tail item {t['name']!r} at {tc(t['start'], fps)} has no "
                     f"media pool item (compound/generator?) — can't re-append, aborting "
                     f"BEFORE any deletion; move it by hand or extend the script")
    # pair video+audio items that came in as one linked append (same track
    # index, same record range) so they go back linked
    audios = {(t["track"], t["start"], t["end"]): t
              for t in tail if t["kind"] == "audio"}
    paired = set()
    for v in (t for t in tail if t["kind"] == "video"):
        a = audios.get((v["track"], v["start"], v["end"]))
        if a is not None and id(a) not in paired:
            paired.add(id(a))
            v["with_audio"] = a
    if not delete_clips_checked(timeline, [t["item"] for t in tail]):
        # nothing was deleted (the page-gated failure mode deletes nothing),
        # so the timeline is intact — abort cleanly before any mutation
        sys.exit("DeleteClips failed mid-ripple even on the edit page — "
                 "timeline left as-is; check the pre-vo backup and retry")
    moved = 0
    for t in sorted(tail, key=lambda t: t["start"]):
        if id(t) in paired:
            continue  # re-appended with its video half
        clip = {"mediaPoolItem": t["mpi"], "startFrame": t["left"],
                "endFrame": t["left"] + (t["end"] - t["start"]),
                "trackIndex": t["track"], "recordFrame": t["start"] + delta}
        if t["kind"] == "video" and "with_audio" not in t:
            clip["mediaType"] = 1
        elif t["kind"] == "audio":
            clip["mediaType"] = 2
        new = mp.AppendToTimeline([clip]) or []
        if not new:
            sys.exit(f"re-append FAILED for {t['name']!r} at "
                     f"{tc(t['start'] + delta, fps)} — restore from the pre-vo backup")
        moved += 1
        it = new[0]
        if t["kind"] == "video":
            if not t["enabled"]:
                it.SetClipEnabled(False)
            if t["props"]:
                cur = it.GetProperty()
                if not isinstance(cur, dict):
                    cur = {}
                for k, v in t["props"].items():
                    if cur.get(k) != v and not it.SetProperty(k, v):
                        log(f"WARN: SetProperty({k}) failed on {t['name']!r}")
        a = t.get("with_audio")
        if a and not a["enabled"]:
            log(f"WARN: linked audio of {t['name']!r} was disabled — "
                f"re-appended enabled, disable by hand")
    return moved


def ripple_markers(timeline, markers, tl_start, gap_end, gap_start, delta):
    moved = 0
    for f, m in markers.items():
        pos = tl_start + int(f)
        if pos < gap_end or pos == gap_start:
            continue  # before the gap, or the gap marker itself (zero-width gap)
        timeline.DeleteMarkerAtFrame(f)
        if timeline.AddMarker(int(f) + delta, m.get("color", "Blue"),
                              m.get("name", ""), m.get("note", ""),
                              int(m.get("duration", 1)) or 1,
                              m.get("customData", "")):
            moved += 1
        else:
            log(f"WARN: marker {m.get('name')!r} did not re-add at "
                f"{int(f) + delta} — re-place by hand")
    return moved


def stamp_marker(timeline, markers, gap_start, tl_start, stamp):
    """Prepend the placement record to the gap marker's note."""
    f = gap_start - tl_start
    m = markers.get(f)
    if not m:
        return False
    timeline.DeleteMarkerAtFrame(f)
    return bool(timeline.AddMarker(f, m.get("color", "Blue"),
                                   m.get("name", ""),
                                   stamp + (m.get("note") or ""),
                                   int(m.get("duration", 1)) or 1,
                                   m.get("customData", "")))


def free_audio_track(timeline, lo, hi):
    # fresh reads on purpose: runs post-ripple, when cached positions are stale
    n = timeline.GetTrackCount("audio") or 0
    for ti in range(1, n + 1):
        if not timeline.GetIsTrackEnabled("audio", ti):
            continue  # muted camera track (multicam convention) — VO would be silent
        items = timeline.GetItemListInTrack("audio", ti) or []
        if not any(int(it.GetStart()) < hi and int(it.GetEnd()) > lo
                   for it in items):
            return ti
    if not timeline.AddTrack("audio", "stereo"):
        sys.exit("AddTrack(audio) failed")
    return n + 1


def get_bin(mp, name):
    root = mp.GetRootFolder()
    f = next((f for f in root.GetSubFolderList() or []
              if f.GetName() == name), None) or mp.AddSubFolder(root, name)
    if not f:
        sys.exit(f"could not create bin {name!r}")
    return f


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    job = json.load(open(sys.argv[1]))
    pm, project, timeline = get_timeline(job)
    fps = parse_fps(job.get("fps") or timeline.GetSetting("timelineFrameRate"))
    audio_path = job["audio_path"]
    pad = float(job.get("tail_pad_s", 0.5))

    dur_s = media_seconds(audio_path)
    audio_frames = round(dur_s * fps)

    gap_start, gap_end, items, markers, tl_start = find_gap(
        timeline, job["marker_name"])

    # everything fallible happens before the backup and the ripple, so an
    # abort leaves neither a stray backup nor a half-mutated timeline
    mp = project.GetMediaPool()
    vo = pool_by_path(mp.GetRootFolder()).get(audio_path)
    if vo is None:
        mp.SetCurrentFolder(get_bin(mp, job.get("bin", "audio")))
        got = mp.ImportMedia([audio_path]) or []
        if not got:
            sys.exit(f"ImportMedia failed for {audio_path}")
        vo = got[0]
    else:
        log("audio already in the media pool — not re-importing")

    needed = audio_frames + round(pad * fps)
    delta = needed - (gap_end - gap_start)
    slack = round(float(job.get("slack_s", 1.0)) * fps)
    if -slack <= delta <= 0:
        log(f"gap already fits (leftover {-delta} frames <= slack) — no ripple")
        delta = 0

    backup_name = backup(project, timeline)
    moved = markers_moved = 0
    if delta:
        tail = snapshot_tail(items, gap_end)
        if tail:  # empty at end-of-timeline — nothing to shift
            moved = ripple(timeline, mp, tail, delta, fps)
        markers_moved = ripple_markers(timeline, markers, tl_start,
                                       gap_end, gap_start, delta)

    track = free_audio_track(timeline, gap_start, gap_start + audio_frames)
    ok = mp.AppendToTimeline([{
        "mediaPoolItem": vo, "trackIndex": track,
        "recordFrame": gap_start, "mediaType": 2}]) or []
    if not ok:
        sys.exit("AppendToTimeline failed for the VO clip")

    stamp = (f"VO PLACED: {Path(audio_path).name}, {dur_s:.1f} s, "
             f"audio track {track}. ")
    if not stamp_marker(timeline, markers, gap_start, tl_start, stamp):
        log("WARN: could not stamp the gap marker's note")

    pm.SaveProject()
    # Post-save readback: the save can discard items placed by an errored
    # append while every in-session read shows them present (measured
    # upstream). The ripple must preserve the item count (delete N,
    # re-append N — linked pairs come back as two items) and add the VO.
    total_after = sum(1 for _ in all_items(timeline))
    vo_ok = any(int(it.GetStart()) == gap_start
                for it in timeline.GetItemListInTrack("audio", track) or [])
    if not vo_ok or total_after != len(items) + 1:
        sys.exit(f"POST-SAVE VERIFY FAILED: items {total_after}/{len(items) + 1}, "
                 f"VO at gap {'present' if vo_ok else 'MISSING'} — restore "
                 f"from backup {backup_name!r}")
    print(json.dumps({
        "timeline": timeline.GetName(), "backup": backup_name,
        "vo_seconds": round(dur_s, 2),
        "vo_tc": f"{tc(gap_start, fps)} .. {tc(gap_start + audio_frames, fps)}",
        "audio_track": track,
        "gap_before_s": round(float((gap_end - gap_start) / fps), 2),
        "gap_after_s": round(float(needed / fps), 2),
        "ripple_delta_s": round(float(delta / fps), 2),
        "items_rippled": moved,
        "markers_rippled": markers_moved}, indent=2))


if __name__ == "__main__":
    main()
