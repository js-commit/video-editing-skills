#!/usr/bin/env python3
"""Dump a Resolve project's timelines to JSON (read-only).

Classifies timelines:
  aroll    the edited talking-head timeline to lay b-roll on (--aroll NAME;
           default: the project's current timeline)
  broll    the other timelines, as possible b-roll "supply" (clips laid end to
           end that bricks are CUT from; with --supply-prefix, only names
           starting with it). "dedicated_supply" is true when the name says
           b-roll; apply_plan.py cuts from any other one only when the plan
           lists it in "supply_timelines" (ask the user first)
  skipped  backups and never-touch timelines (never read or written)

Every item records its timeline position and source range in frames AND
seconds, because frame rates are mixed and every interface speaks seconds.
Frames are Resolve's absolute frames (a timeline starting at 01:00:00:00 starts
at frame 86400 at 24 fps); record_s is seconds from the timeline START, the
same clock as a render of the whole timeline (and review notes on it).
The a-roll entry also names the brick track (by name) and the first video
track above the a-roll cameras.

The user edits between passes: run this right before planning, every time,
and pass --compare <previous inventory> to list what changed on the brick
track since (moved, trimmed, deleted or added bricks are the user's
decisions: never undo them).

Usage:
  inventory.py --project P [--aroll T] [--supply-prefix "broll"]
               [--track-name "B-roll bricks"] [--compare old.json] [-o inventory.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402


def dump_track(tl, fps, kind, idx):
    t0 = tl.GetStartFrame()
    items = []
    for it in tl.GetItemListInTrack(kind, idx) or []:
        mpi = it.GetMediaPoolItem()
        start, end = it.GetStart(), it.GetEnd()
        sstart, send = it.GetSourceStartFrame(), it.GetSourceEndFrame()
        left = it.GetLeftOffset()
        if left is not None:  # GetLeftOffset is exact where GetSourceStartFrame can be off by one
            sstart, send = int(left), int(left) + (send - sstart)
        clip_fps = nfps = None
        path = None
        if mpi:
            path = mpi.GetClipProperty("File Path") or None
            try:
                clip_fps = float(mpi.GetClipProperty("FPS"))
            except (TypeError, ValueError):
                clip_fps = None
            nfps = B.native_fps(mpi) if path else clip_fps
        items.append({
            "name": it.GetName(), "file_path": path, "enabled": bool(it.GetClipEnabled()),
            "record_frame": start, "record_end_frame": end,
            "record_s": round((start - t0) / fps, 4), "record_end_s": round((end - t0) / fps, 4),
            "duration_frames": end - start,
            "src_start_frame": sstart, "src_end_frame": send, "clip_fps": clip_fps,
            "src_start_s": round(sstart / nfps, 4) if nfps else None,
            "src_end_s": round(send / nfps, 4) if nfps else None,
        })
    return items


def entry_for(tl):
    fps = B.fps_of(tl)
    e = {"name": tl.GetName(), "fps": fps, "start_frame": tl.GetStartFrame(), "end_frame": tl.GetEndFrame(),
         "video_tracks": [], "audio_tracks": []}
    for kind, key in (("video", "video_tracks"), ("audio", "audio_tracks")):
        for idx in range(1, tl.GetTrackCount(kind) + 1):
            e[key].append({"index": idx, "name": tl.GetTrackName(kind, idx), "items": dump_track(tl, fps, kind, idx)})
    return e


def brick_changes(old, new, track_name):
    """Pure: what changed on the brick track between two inventories."""
    def bricks(inv):
        ar = (inv or {}).get("aroll") or {}
        for t in ar.get("video_tracks", []):
            if t["name"] == track_name or t["index"] == ar.get("brick_track"):
                return {(i["file_path"] or i["name"], i["src_start_frame"]): i for i in t["items"]}
        return {}
    a, b = bricks(old), bricks(new)
    out = []
    for k in sorted(set(a) | set(b), key=lambda k: (str(k[0]), k[1])):
        x, y = a.get(k), b.get(k)
        if x and not y:
            out.append({"change": "deleted", "name": x["name"], "was_s": x["record_s"]})
        elif y and not x:
            out.append({"change": "added", "name": y["name"], "at_s": y["record_s"]})
        elif (x["record_frame"], x["record_end_frame"]) != (y["record_frame"], y["record_end_frame"]):
            out.append({"change": "moved/trimmed", "name": y["name"],
                        "was": [x["record_s"], x["record_end_s"]], "now": [y["record_s"], y["record_end_s"]]})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--aroll", default=None, help="the a-roll timeline (default: the current timeline)")
    ap.add_argument("--supply-prefix", default=None, help="only timelines starting with this are b-roll supply")
    ap.add_argument("--track-name", default=B.BRICK_TRACK)
    ap.add_argument("--compare", default=None, help="an earlier inventory.json: list brick-track changes")
    ap.add_argument("-o", "--output", default=None)
    a = ap.parse_args()

    _, proj = B.open_project(a.project)
    aroll_name = a.aroll
    if not aroll_name:
        cur = proj.GetCurrentTimeline()
        if cur is None:
            sys.exit("no current timeline; pass --aroll")
        aroll_name = cur.GetName()
    out = {"project": proj.GetName(), "aroll": None, "broll": [], "skipped": []}
    for tl in B.vr().timelines(proj):
        name = tl.GetName()
        if B.is_protected(name):
            out["skipped"].append({"name": name, "reason": "backup / never-touch"})
            continue
        if name == aroll_name:
            e = entry_for(tl)
            e["brick_track"] = B.find_brick_track(tl, a.track_name, explicit=False)
            ends = [t["index"] for t in e["video_tracks"]
                    if t["index"] != e["brick_track"] and sum(i["duration_frames"] for i in t["items"])
                    >= 0.8 * max(1, e["end_frame"] - e["start_frame"])]
            e["aroll_video_tracks"] = ends
            e["first_overlay_track"] = (max(ends) + 1) if ends else 2
            out["aroll"] = e
        elif a.supply_prefix is not None and not name.lower().startswith(a.supply_prefix.lower()):
            out["skipped"].append({"name": name, "reason": "not a supply timeline (--supply-prefix)"})
        else:
            e = entry_for(tl)
            e["dedicated_supply"] = B.is_dedicated_supply(name)
            out["broll"].append(e)
    if out["aroll"] is None:
        sys.exit(f"a-roll timeline {aroll_name!r} not found (or it is a backup / never-touch timeline)")
    others = [e["name"] for e in out["broll"] if not e["dedicated_supply"]]
    if others:
        B.log(f"not named as b-roll supply: {others}. Bricks are CUT out of a supply timeline: plan from one of "
              f"these only after the user says yes, and list it in the plan's \"supply_timelines\".")
    if a.compare:
        with open(a.compare) as f:
            out["brick_changes_since_compare"] = brick_changes(json.load(f), out, a.track_name)
        for c in out["brick_changes_since_compare"]:
            B.log("user change:", json.dumps(c))
    blob = json.dumps(out, indent=1)
    if a.output:
        with open(a.output, "w") as f:
            f.write(blob)
        B.log(f"wrote {a.output}")
    else:
        print(blob)


if __name__ == "__main__":
    main()
