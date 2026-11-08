#!/usr/bin/env python3
"""Close flicker gaps between bricks on the brick track.

A sub-second empty space between two bricks plays as a flash of the talking
head. This EXTENDS the earlier brick's tail through the gap (more of the same
shot, so the seam is invisible); when that clip has no more footage, the
later brick's head is extended backwards instead; only when neither can grow
is the later brick slid back (which can open a hole at ITS tail, so check the
flicker audit afterwards). Only the brick track is touched.

Exports a .drp backup first (backup.py) and checks after saving that the
track still holds exactly as many bricks as before.

Usage:
  close_gaps.py --project P --timeline T [--track-name "B-roll bricks"] [--max-gap-s 1.1] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402


def gap_action(a_src_end, a_total, b_src_start, gap):
    """Pure: how to close a `gap`-frame hole between brick a and brick b.
    a_total = a's clip length in timeline frames (0 = unknown)."""
    if a_total and a_src_end + gap <= a_total:
        return "extend-tail"
    if b_src_start - gap >= 0:
        return "extend-head"
    return "slide"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--track-name", default=B.BRICK_TRACK)
    ap.add_argument("--max-gap-s", type=float, default=1.1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args()
    from ripple_extend import append_snapshot

    B.refuse_protected(a.timeline)
    pm, proj = B.open_project(a.project)
    tl = B.timeline_by_name(proj, a.timeline)
    fps = B.fps_of(tl)
    t0 = tl.GetStartFrame()
    proj.SetCurrentTimeline(tl)
    track = B.find_brick_track(tl, a.track_name, explicit=True)
    mp = proj.GetMediaPool()
    max_gap = round(a.max_gap_s * fps)

    def sorted_items():
        return sorted(tl.GetItemListInTrack("video", track) or [], key=lambda i: i.GetStart())

    gaps = [(x, y, y.GetStart() - x.GetEnd()) for x, y in zip(sorted_items(), sorted_items()[1:])]
    gaps = [g for g in gaps if 0 < g[2] <= max_gap]
    if a.dry_run or not gaps:
        print(json.dumps({"gaps": [{"at": B.tc(x.GetEnd() - t0, fps), "frames": n} for x, _, n in gaps],
                          "dry_run": a.dry_run}))
        return
    if not a.no_backup:
        import backup
        backup.export_drp(pm, proj, "before close_gaps")
    baseline = len(sorted_items())

    def props(it):
        return {k: it.GetProperty(k) for k in ("RotationAngle", "ZoomX", "ZoomY", "Pan", "Tilt")}

    def readd(it_mpi, name, s0, s1, rec, pr):
        d = {"kind": "video", "track": track, "name": name, "mpi": it_mpi, "new_start": rec - t0, "dur": s1 - s0,
             "src_in": s0, "enabled": True, "color": "", "props": {}, "comps": [],
             "ctype": it_mpi.GetClipProperty("Type") or "", "uid": ""}
        try:
            d["cfps"] = float(it_mpi.GetClipProperty("FPS") or 0)
        except (TypeError, ValueError):
            d["cfps"] = 0.0
        got = append_snapshot(mp, tl, d, t0, fps, media_type=1)
        for k, v in pr.items():
            try:
                if got and v is not None and abs(float(v) - (1.0 if k.startswith("Zoom") else 0.0)) > 1e-6:
                    got[0].SetProperty(k, float(v))
            except (TypeError, ValueError):
                pass
        return got

    closed, failed = 0, set()
    for _ in range(500):
        items = sorted_items()
        moved = False
        for x, y in zip(items, items[1:]):
            gap = y.GetStart() - x.GetEnd()
            if not 0 < gap <= max_gap or x.GetEnd() in failed:
                continue
            x_mpi = x.GetMediaPoolItem()
            try:
                x_cfps = float(x_mpi.GetClipProperty("FPS") or 0) or fps
                x_total = int(int(float(x_mpi.GetClipProperty("Frames") or 0)) * fps / x_cfps)
            except (TypeError, ValueError):
                x_total = 0
            x_s0, x_s1 = x.GetLeftOffset(), x.GetLeftOffset() + (x.GetEnd() - x.GetStart())
            y_s0, y_s1 = y.GetLeftOffset(), y.GetLeftOffset() + (y.GetEnd() - y.GetStart())
            how = gap_action(x_s1, x_total, y_s0, gap)
            if how == "extend-tail":
                it, s0, s1, rec = x, x_s0, x_s1 + gap, x.GetStart()
            elif how == "extend-head":
                it, s0, s1, rec = y, y_s0 - gap, y_s1, y.GetStart() - gap
            else:
                it, s0, s1, rec = y, y_s0, y_s1, x.GetEnd()
            it_mpi, name, pr, orig_rec = it.GetMediaPoolItem(), it.GetName(), props(it), it.GetStart()
            orig = (it.GetLeftOffset(), it.GetLeftOffset() + (it.GetEnd() - it.GetStart()))
            gap_at = x.GetEnd()
            if not B.delete_clips(tl, [it]):
                B.log(f"could not delete {name} to close its gap: skipped")
                failed.add(gap_at)
                continue
            if readd(it_mpi, name, s0, s1, rec, pr):
                closed += 1
                B.log(f"closed a {gap}-frame gap at {B.tc(gap_at - t0, fps)} ({how} {name})")
            else:  # put it back where it was rather than lose the brick
                readd(it_mpi, name, orig[0], orig[1], orig_rec, pr)
                failed.add(gap_at)
                B.log(f"could not close the gap at {B.tc(gap_at - t0, fps)}")
            moved = True
            break
        if not moved:
            break
    pm.SaveProject()
    after = len(sorted_items())
    if after != baseline:
        sys.exit(f"BRICK COUNT CHANGED after save: {baseline} -> {after}. A brick was lost: restore it from the "
                 f"backup (backup.py list / restore).")
    print(json.dumps({"gaps_closed": closed}))


if __name__ == "__main__":
    main()
