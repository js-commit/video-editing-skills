#!/usr/bin/env python3
"""Apply a checked b-roll placement plan to a Resolve timeline (Studio).

Each placement puts a sub-range of a b-roll clip (video only) on the a-roll
timeline's brick track ("B-roll bricks", created on top on first use). Two
kinds of source:

  "media": "/abs/clip.mp4"      a file; imported into a "B-roll (brick layer)"
                                bin when it is not in the media pool yet.
  "broll_timeline" + "file_hint" a clip sitting on a b-roll SUPPLY timeline.
                                The used range is CUT out of the supply (the
                                item is replaced by its unused left/right
                                remainders), so the gap shows what is used
                                and nothing is placed twice.

Times are SECONDS (frame rates are mixed): use_src_start_s / use_src_end_s in
the source file's own real-time seconds; record_s from the timeline start.
Optional per placement: "rotation" (degrees), "zoom" (1.0 = none), "props"
({"Pan": 0, "Tilt": -200, ...} any TimelineItem property).

Safety: refuses backup / never-touch timelines (settings
editor.never_touch_timelines and the plan's "never_touch" list); only cuts
from a supply timeline whose name says b-roll ("B-roll", "broll supply") or
that the plan lists in "supply_timelines" (the user's yes for any other
timeline), and never from the a-roll itself; only fills EMPTY space on the
brick track; exports a .drp backup first (backup.py) and stops if that fails;
after saving, re-reads the track and reports any brick the save dropped. Run
check_plan.py first; run flicker_audit.py after.

Usage:
  apply_plan.py plan.json [--dry-run] [--no-backup] [-o report.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402

MIN_REMAINDER_FRAMES = 8   # supply remainders shorter than this are dropped
EDGE_TOLERANCE_FRAMES = 8  # conform rounding can shave a few frames off an item's range
BIN_NAME = "B-roll (brick layer)"


def append_checked(mp, tl, info, what):
    """Re-add a supply remainder, verified: Resolve can return an item yet drop
    it when rounding makes it overflow into the next item. Retry shorter."""
    for shrink in (0, 4, 8, 16, 32, 64):
        i = dict(info)
        i["endFrame"] = info["endFrame"] - shrink
        if i["endFrame"] - i["startFrame"] < MIN_REMAINDER_FRAMES:
            break
        if mp.AppendToTimeline([i]):
            for it in tl.GetItemListInTrack("video", i["trackIndex"]) or []:
                if it.GetStart() == i["recordFrame"]:
                    if shrink:
                        B.log(f"note: remainder trimmed {shrink} frames to fit ({what})")
                    return it
    B.log(f"WARNING: remainder LOST ({what}): that supply footage is gone from the timeline; "
          f"recover it from the backup timeline or the .drp backup")
    return None


def occupied(tl, track, start_f, end_f):
    for it in tl.GetItemListInTrack("video", track) or []:
        if it.GetStart() < end_f and it.GetEnd() > start_f:
            return it
    return None


def pool_item_for(mp, path, cache):
    if path in cache:
        return cache[path]
    if not cache:
        cache.update(B.vr().pool_by_path(mp.GetRootFolder()))
        if path in cache:
            return cache[path]
    root = mp.GetRootFolder()
    folder = next((f for f in root.GetSubFolderList() or [] if f.GetName() == BIN_NAME), None) \
        or mp.AddSubFolder(root, BIN_NAME)
    prev = mp.GetCurrentFolder()
    if folder:
        mp.SetCurrentFolder(folder)
    got = mp.ImportMedia([path]) or []
    if prev:
        mp.SetCurrentFolder(prev)
    cache[path] = got[0] if got else None
    return cache[path]


def find_supply_item(proj, p):
    broll = B.timeline_by_name(proj, p["broll_timeline"])
    best = None
    for it in broll.GetItemListInTrack("video", p.get("broll_track", 1)) or []:
        mpi = it.GetMediaPoolItem()
        if mpi is None:
            continue
        nfps = B.native_fps(mpi)
        u0, u1 = round(p["use_src_start_s"] * nfps), round(p["use_src_end_s"] * nfps)
        key = (mpi.GetClipProperty("File Path") or "") + " " + it.GetName()
        if p["file_hint"] in key and it.GetSourceStartFrame() <= u0 + EDGE_TOLERANCE_FRAMES \
                and it.GetSourceEndFrame() >= u1 - EDGE_TOLERANCE_FRAMES:
            if best is None or abs(it.GetStart() - p.get("item_record_frame", 0)) < \
                    abs(best.GetStart() - p.get("item_record_frame", 0)):
                best = it
    return broll, best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true", help="skip the automatic .drp backup (not recommended)")
    ap.add_argument("-o", "--report", default=None)
    a = ap.parse_args()

    with open(a.plan) as f:
        plan = json.load(f)
    extra = plan.get("never_touch", [])
    B.refuse_protected(plan["aroll_timeline"], extra)
    for p in plan["placements"]:
        if p.get("broll_timeline"):
            B.refuse_protected(p["broll_timeline"], extra)
    refusals = B.supply_refusals(plan)
    if refusals:
        sys.exit("refusing, nothing was changed:\n  " + "\n  ".join(refusals))

    pm, proj = B.open_project(plan["project"])
    aroll = B.timeline_by_name(proj, plan["aroll_timeline"])
    aroll_fps = B.fps_of(aroll)
    t0 = aroll.GetStartFrame()
    mp = proj.GetMediaPool()
    if not a.dry_run and not a.no_backup:
        import backup
        backup.export_drp(pm, proj, f"before apply_plan {os.path.basename(a.plan)}")

    track_name = plan.get("track_name", B.BRICK_TRACK)
    proj.SetCurrentTimeline(aroll)
    top = None
    for idx in range(1, aroll.GetTrackCount("video") + 1):
        if aroll.GetTrackName("video", idx) == track_name:
            top = idx
    if top is None and not a.dry_run:
        if not aroll.AddTrack("video"):
            sys.exit("could not add a video track to the a-roll timeline")
        top = aroll.GetTrackCount("video")
        aroll.SetTrackName("video", top, track_name)
    B.log(f"brick track: V{top} {track_name!r}" if top else f"brick track {track_name!r} would be created")

    pool_cache, report = {}, []
    for p in plan["placements"]:
        rec = {"id": p.get("id"), "placement": p, "status": None}
        report.append(rec)
        label = p.get("media") or p.get("file_hint")
        broll = item = None
        if p.get("broll_timeline"):
            proj.SetCurrentTimeline(B.timeline_by_name(proj, p["broll_timeline"]))
            broll, item = find_supply_item(proj, p)
            if item is None:
                rec["status"] = "SKIP: source range not found on the supply timeline (already used?)"
                B.log(rec["status"], label)
                continue
            mpi = item.GetMediaPoolItem()
            lo_f, hi_f = item.GetSourceStartFrame(), item.GetSourceEndFrame()
        else:
            if not os.path.exists(p["media"]):
                rec["status"] = "SKIP: media file not found"
                B.log(rec["status"], label)
                continue
            if a.dry_run:  # never import during a dry run: look it up, else judge from the file itself
                if not pool_cache:
                    pool_cache.update(B.vr().pool_by_path(mp.GetRootFolder()))
                mpi = pool_cache.get(p["media"])
                if mpi is None:
                    rec["status"] = (f"DRY: would import {os.path.basename(p['media'])} and place it at "
                                     f"{B.tc(round(p['record_s'] * aroll_fps), aroll_fps)}")
                    B.log(rec["status"])
                    continue
            else:
                mpi = pool_item_for(mp, p["media"], pool_cache)
            if mpi is None:
                rec["status"] = "FAIL: could not import the media into the pool"
                B.log(rec["status"], label)
                continue
            lo_f = 0
            try:
                hi_f = int(float(mpi.GetClipProperty("Frames") or 0)) or 10 ** 9
            except (TypeError, ValueError):
                hi_f = 10 ** 9
        try:
            cfps = float(mpi.GetClipProperty("FPS"))  # conformed rate: frames -> playback duration
        except (TypeError, ValueError):
            cfps = aroll_fps
        nfps = B.native_fps(mpi) or cfps            # native rate: seconds -> frame index
        use0_f = max(lo_f, round(p["use_src_start_s"] * nfps))
        use1_f = min(hi_f, round(p["use_src_end_s"] * nfps))
        if use1_f - use0_f < MIN_REMAINDER_FRAMES:
            rec["status"] = "SKIP: usable range shrank to a sliver after clamping"
            B.log(rec["status"], label)
            continue
        record_f = t0 + round(p["record_s"] * aroll_fps)
        dur_f = round((use1_f - use0_f) / cfps * aroll_fps)
        clash = occupied(aroll, top, record_f, record_f + dur_f) if top else None
        if clash:
            rec["status"] = f"SKIP: brick track occupied at {B.tc(record_f - t0, aroll_fps)} by {clash.GetName()}"
            B.log(rec["status"])
            continue
        if a.dry_run:
            rec["status"] = f"DRY: would place src[{use0_f}-{use1_f}] at {B.tc(record_f - t0, aroll_fps)}"
            B.log(rec["status"], label)
            continue

        proj.SetCurrentTimeline(aroll)
        added = mp.AppendToTimeline([{"mediaPoolItem": mpi, "startFrame": use0_f, "endFrame": use1_f,
                                      "trackIndex": top, "recordFrame": record_f, "mediaType": 1}])
        if not added:
            rec["status"] = "FAIL: AppendToTimeline returned nothing"
            B.log(rec["status"], label)
            continue
        brick = added[0]
        for key, prop in (("rotation", "RotationAngle"), ("zoom", "ZoomX")):
            if p.get(key) is not None:
                ok = brick.SetProperty(prop, float(p[key]))
                if key == "zoom" and ok:
                    brick.SetProperty("ZoomY", float(p[key]))
                if not ok:
                    B.log(f"WARN: SetProperty({prop}) failed on {label}")
        for prop, val in (p.get("props") or {}).items():
            if not brick.SetProperty(prop, val):
                B.log(f"WARN: SetProperty({prop}) failed on {label}")
        got_len = brick.GetEnd() - brick.GetStart()
        if abs(got_len - dur_f) > 1:
            B.log(f"WARN: {label} landed {got_len} frames, planned {dur_f}: flicker_audit.py will show the edge")

        if broll is not None:  # cut the used range out of the supply
            proj.SetCurrentTimeline(broll)
            it_rec, it_src0, it_src1 = item.GetStart(), item.GetSourceStartFrame(), item.GetSourceEndFrame()
            broll_fps = B.fps_of(broll)
            color = item.GetClipColor() or ""
            if not B.delete_clips(broll, [item]):
                rec["status"] = "WARN: placed, but the supply cut failed (source item left in place)"
                B.log(rec["status"], label)
                continue
            rems = []
            if use0_f - it_src0 >= MIN_REMAINDER_FRAMES:
                rems.append({"mediaPoolItem": mpi, "startFrame": it_src0, "endFrame": use0_f,
                             "trackIndex": p.get("broll_track", 1), "recordFrame": it_rec, "mediaType": 1})
            if it_src1 - use1_f >= MIN_REMAINDER_FRAMES:
                rems.append({"mediaPoolItem": mpi, "startFrame": use1_f, "endFrame": it_src1,
                             "trackIndex": p.get("broll_track", 1),
                             "recordFrame": it_rec + round((use1_f - it_src0) / cfps * broll_fps), "mediaType": 1})
            for r in rems:
                landed = append_checked(mp, broll, r, f"{label} src[{r['startFrame']}-{r['endFrame']}]")
                if landed and color and color != "None":
                    landed.SetClipColor(color)
        rec["record_f"] = record_f
        rec["status"] = f"OK: {B.tc(brick.GetStart() - t0, aroll_fps)}-{B.tc(brick.GetEnd() - t0, aroll_fps)}"
        B.log(rec["status"], label)

    if not a.dry_run:
        proj.SetCurrentTimeline(aroll)
        pm.SaveProject()
        # the save is the verification boundary: an append whose response errored
        # can survive in-session reads and still be dropped by the save
        if top:
            on_disk = {it.GetStart() for it in aroll.GetItemListInTrack("video", top) or []}
            for r in report:
                if r["status"] and r["status"].startswith("OK") and r["record_f"] not in on_disk:
                    r["status"] = f"LOST AFTER SAVE: the brick at {B.tc(r['record_f'] - t0, aroll_fps)} vanished; re-run"
                    B.log(r["status"])
    ok = sum(1 for r in report if r["status"] and r["status"].startswith(("OK", "DRY")))
    summary = {"applied" if not a.dry_run else "would_apply": ok, "total": len(report), "results": report}
    if a.report:
        with open(a.report, "w") as f:
            json.dump(summary, f, indent=1, default=str)
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}))


if __name__ == "__main__":
    main()
