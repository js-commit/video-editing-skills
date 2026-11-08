#!/usr/bin/env python3
"""Ripple-insert source frames into an edited a-roll timeline, and snap b-roll
bricks onto the cuts they were meant to start or end on.

Why: the Resolve scripting API has no trim or insert. A silence-cut sliver (a
6-frame clip carrying one word) plays as a double jump cut; the honest fix is
to restore the removed pause on one side so the seam becomes continuous. This
tool re-creates the tail of the timeline shifted right by the restored frames:
every item on every track after the insertion point is collected (source
range, enabled flag, transform properties, clip colour, Fusion comps exported
to disk), deleted, and re-appended at start + shift; Fusion comps are
re-imported and timeline markers after the point move with it.

  --bridge F        F = record start (timeline frame, counted from the timeline
                    start) of a sliver whose PREVIOUS a-roll item is extended
                    through the removed pause up to the sliver's source
                    in-point (gap measured on --aroll-track). Repeatable.
  --plan FILE       seam_audit.py --plan output: [{"F", "tail_f", "head_f"}].
                    At the seam whose incoming a-roll item starts at F, the
                    outgoing item gets tail_f frames of restored source and the
                    incoming item's head is pulled earlier by head_f frames (on
                    every non-brick track; bricks straddling the seam grow).
  --snap-top-track  afterwards, a brick that starts 1..N frames after an
                    exposed lower-track cut (N < --min-run-s) is extended back
                    onto that cut; one that ENDS 1..N frames before a cut is
                    extended onto it; two bricks 1..N frames apart are butted.
                    Bricks are planned in fuzzy seconds, cuts are exact frames:
                    this is where flashes come from.
  --track-name      the brick track, by name (default "B-roll bricks"; a single
                    track named like "b-roll" is accepted; none = no bricks).
                    Bricks are never extended through a bridge.

Safety: refuses backup / never-touch timelines; aborts BEFORE any mutation on
an item it cannot re-create (titles, generators, solids, adjustment clips:
AppendToTimeline only places media-pool clips) or a Fusion comp it cannot
export; writes a restore point JSON (every item and marker it is about to
delete) before deleting anything. Back the project up first (backup.py).

Prints a summary JSON, including {old_start: new_start} for brick-track items
(patch your plan with it). --dry-run only reports.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402

PROPS = ["RotationAngle", "ZoomX", "ZoomY", "Pan", "Tilt", "CropLeft", "CropRight", "CropTop", "CropBottom", "Opacity"]
DEFAULTS = {"RotationAngle": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Pan": 0.0, "Tilt": 0.0, "CropLeft": 0.0,
            "CropRight": 0.0, "CropTop": 0.0, "CropBottom": 0.0, "Opacity": 100.0}


def snap_item(it, t0, kind, idx, comp_dir):
    """Everything needed to re-create one timeline item, read BEFORE any mutation."""
    mpi = it.GetMediaPoolItem()
    if mpi is None:
        raise SystemExit(f"{'V' if kind == 'video' else 'A'}{idx}@{it.GetStart() - t0} {it.GetName()!r} has no media "
                         f"pool item (a title, solid, generator or adjustment clip). AppendToTimeline cannot "
                         f"re-create it, so a ripple would delete it for good. Aborting BEFORE any mutation: "
                         f"move it out of the rippled range and re-run.")
    d = {"kind": kind, "track": idx, "name": it.GetName(), "mpi": mpi, "start": it.GetStart() - t0,
         "dur": it.GetEnd() - it.GetStart(), "src_in": it.GetLeftOffset(), "enabled": bool(it.GetClipEnabled()),
         "color": it.GetClipColor() or "", "props": {}, "comps": [],
         "uid": mpi.GetUniqueId() if hasattr(mpi, "GetUniqueId") else str(id(mpi)),
         "ctype": mpi.GetClipProperty("Type") or ""}
    try:
        d["cfps"] = float(mpi.GetClipProperty("FPS") or 0)
    except (TypeError, ValueError):
        d["cfps"] = 0.0
    try:
        d["cframes"] = int(float(mpi.GetClipProperty("Frames") or 0))  # clip length in ITS fps; 0 = unknown
    except (TypeError, ValueError):
        d["cframes"] = 0
    if kind == "video":
        for p in PROPS:
            v = it.GetProperty(p)
            try:
                if v is not None and abs(float(v) - DEFAULTS[p]) > 1e-6:
                    d["props"][p] = float(v)
            except (TypeError, ValueError):
                pass
        for name in it.GetFusionCompNameList() or []:
            path = os.path.join(comp_dir, f"V{idx}_{d['start']}_{name.replace(' ', '_')}.comp")
            if it.ExportFusionComp(path) and os.path.exists(path):
                d["comps"].append(path)
            else:
                raise SystemExit(f"ExportFusionComp failed V{idx}@{d['start']} {name}: aborting BEFORE any mutation "
                                 f"(a picture-in-picture re-appended without its comp plays full-frame)")
    return d


def append_snapshot(mp, tl, d, t0, tl_fps, media_type=None):
    """Re-append one snap_item() dict at d["new_start"]. Two Resolve quirks:
    * startFrame/endFrame are in the CLIP's own fps, while GetLeftOffset() and
      item lengths are timeline frames: scale, then read back and nudge
      endFrame until the length matches.
    * a still ignores endFrame and gets the default still duration, but an
      append only fills FREE frames, so a still is clipped by whatever follows.
      To hold exactly [s, e): make sure something sits at e (a temporary copy
      if nothing does), then chain copies from s.
    Returns the appended items (empty on failure)."""
    mpi = d["mpi"]
    rec = d["new_start"] + t0
    dur = d["dur"]
    trk = d["track"]
    kind = "video" if media_type != 2 else "audio"

    def occupied_at(f):
        return any(x.GetStart() <= f < x.GetEnd() for x in tl.GetItemListInTrack(kind, trk) or [])

    if d["ctype"] == "Still":
        temp = None
        if not occupied_at(rec + dur):
            got = mp.AppendToTimeline([{"mediaPoolItem": mpi, "startFrame": 0, "endFrame": 119, "trackIndex": trk,
                                        "recordFrame": rec + dur, "mediaType": 1}]) or []  # endFrame 0 is rejected
            if not got:
                return []
            temp = got[0]
        cur, out = rec, []
        while cur < rec + dur:
            got = mp.AppendToTimeline([{"mediaPoolItem": mpi, "startFrame": 0, "endFrame": max(1, rec + dur - cur - 1),
                                        "trackIndex": trk, "recordFrame": cur, "mediaType": 1}]) or []
            if not got:
                break
            it = got[0]
            n = it.GetEnd() - it.GetStart()
            if n <= 0 or it.GetStart() != cur:
                break
            out.append(it)
            cur += n
        if temp is not None:
            B.delete_clips(tl, [temp])
        if cur != rec + dur:
            B.delete_clips(tl, out)
            return []
        return out
    cfps = d["cfps"]
    scaled = bool(cfps) and abs(cfps - tl_fps) > 0.01
    if scaled:  # Resolve floors clip frames -> timeline frames: ceil both edges, then verify by readback
        sf = int(-(-d["src_in"] * cfps // tl_fps))
        ef = sf + int(-(-dur * cfps // tl_fps))
    else:
        sf, ef = d["src_in"], d["src_in"] + dur
    for _ in range(6):
        info = {"mediaPoolItem": mpi, "startFrame": sf, "endFrame": ef, "trackIndex": trk, "recordFrame": rec}
        if media_type:
            info["mediaType"] = media_type
        got = mp.AppendToTimeline([info]) or []
        if not got:
            return []
        it = got[0]
        n = it.GetEnd() - it.GetStart()
        lo = it.GetLeftOffset()
        if not scaled or (n == dur and lo == d["src_in"]):
            return got
        B.delete_clips(tl, got)
        if lo != d["src_in"]:
            step = 1 if lo < d["src_in"] else -1
            sf += step
            ef += step
        else:
            ef += 1 if n < dur else -1
    return []


def write_restore(comp_dir, tag, meta, snaps, markers):
    """Park everything a failed run needs to be undone by hand, BEFORE anything
    is deleted. The name carries a timestamp so a retry never overwrites it."""
    stem = os.path.join(comp_dir, f"restore_{tag}_{time.strftime('%Y%m%d-%H%M%S')}")
    path, n = stem + ".json", 1
    while os.path.exists(path):
        n += 1
        path = f"{stem}-{n}.json"

    def plain(d):
        o = {k: v for k, v in d.items() if k != "mpi"}
        o["media_path"] = d["mpi"].GetClipProperty("File Path") or ""
        return o

    with open(path, "w") as f:
        json.dump({"meta": meta, "items": [plain(d) for d in snaps],
                   "markers": {str(fr): m for fr, m in markers.items()}}, f, indent=1)
    B.log(f"restore point: {path}")
    return path


def pair_key(d):
    """What a video item and its linked audio item have in common."""
    return (d["track"], d["new_start"], d["dur"], d["uid"])


def reappend_snapshots(mp, tl, snaps, t0, tl_fps):
    """Re-append every snapshot at its new_start and put back what an append
    does not carry (transform, enabled state, colour, Fusion comps). A video
    item whose audio twin (same track, position, length, clip) is in the batch
    is appended without mediaType so Resolve re-links the pair. Returns
    failures [(kind, track, new_start, name)]."""
    audio_by_key = {pair_key(d): d for d in snaps if d["kind"] == "audio"}
    done_audio, fails = set(), []
    # stills go LAST: a still is clipped by the item that follows it, so that item must exist first
    for d in sorted(snaps, key=lambda d: (d["ctype"] == "Still", d["new_start"], d["kind"] != "video", d["track"])):
        if d["kind"] == "audio" and id(d) in done_audio:
            continue
        media_type = 2 if d["kind"] == "audio" else None
        if d["kind"] == "video":
            partner = audio_by_key.get(pair_key(d))
            if partner is None:
                media_type = 1
            else:
                done_audio.add(id(partner))
        got = append_snapshot(mp, tl, d, t0, tl_fps, media_type)
        if not got:
            fails.append((d["kind"], d["track"], d["new_start"], d["name"]))
            continue
        if d["kind"] != "video":
            continue
        for it in got:  # a still hold may be several butt-cut copies
            for p, v in d["props"].items():
                if not it.SetProperty(p, v):
                    B.log(f"WARN SetProperty {p} V{d['track']}@{d['new_start']}")
            if not d["enabled"]:
                it.SetClipEnabled(False)
            if d["color"]:
                it.SetClipColor(d["color"])
            for path in d["comps"]:
                if not it.ImportFusionComp(path) or not it.GetFusionCompCount():
                    B.log(f"WARN ImportFusionComp failed V{d['track']}@{d['new_start']}")
    return fails


# ---- pure brick snapping (unit-tested) -------------------------------------

def tail_room(d, fps):
    """Timeline frames the item can still grow at its end (None = unknown)."""
    if d["ctype"] == "Still":
        return 10 ** 9
    if not d.get("cframes"):
        return None
    cf = d.get("cfps") or fps
    total_tl = int(d["cframes"] * fps / cf)
    return total_tl - (d["src_in"] + d["dur"])


def grow_tail(d, n, fps):
    """Lengthen a brick by n frames at its end. If the media has no tail left,
    slide its source window earlier by the shortfall instead."""
    room = tail_room(d, fps)
    if room is None or room < 0:
        return False
    short = max(0, n - room)
    if short and d["src_in"] < short:
        return False
    d["src_in"] -= short
    d["dur"] += n
    return True


def merged_bounds(runs):
    """runs: (start, end, uid, src_in, enabled) per item of one track. Returns the
    boundaries of SOURCE-CONTINUOUS runs (a continuation piece is not a cut)."""
    bounds = set()
    merged = []
    for r in sorted(runs):
        p = merged[-1] if merged else None
        if p and p[2] == r[2] and p[1] == r[0] and p[4] == r[4] and p[3] + (p[1] - p[0]) == r[3]:
            merged[-1] = (p[0], r[1], p[2], p[3], p[4])
        else:
            merged.append(r)
    for r in merged:
        bounds.add(r[0])
        bounds.add(r[1])
    return bounds


def snap_bricks(bricks, bounds, min_f, fps):
    """Pull/push brick dicts (new_start, dur, src_in, ...) onto nearby exposed
    cuts and butt bricks a flash apart. Mutates; returns [(name, how, frames)]."""
    bricks.sort(key=lambda d: d["new_start"])
    snaps = []

    def covered(f):
        return any(d["new_start"] <= f < d["new_start"] + d["dur"] for d in bricks)

    def changed(d, n, how):
        d["snapped"] = d.get("snapped", 0) + n
        d.pop("keep_in_place", None)
        snaps.append((d["name"], how, n))
        B.log(f"snap brick {d['name']}: {how} {n} frames")

    for d in bricks:
        s = d["new_start"]
        cands = [b for b in bounds if 0 < s - b < min_f and not any(covered(f) for f in range(b, s))]
        if cands:
            b = min(cands)
            n = s - b
            if d["src_in"] >= n:
                d["new_start"] = b
                d["src_in"] -= n
                d["dur"] += n
                changed(d, n, f"start pulled onto the cut at {b}")
            else:  # no head room: slide the whole brick (the end pass re-checks it)
                d["new_start"] = b
                changed(d, n, f"slid onto the cut at {b} (no head room)")
    for d in bricks:
        e = d["new_start"] + d["dur"]
        cands = [b for b in bounds if 0 < b - e < min_f and not any(covered(f) for f in range(e, b))]
        if cands:
            b = min(cands)
            n = b - e
            if grow_tail(d, n, fps):
                changed(d, n, f"end pushed onto the cut at {b}")
            else:
                B.log(f"WARN brick {d['name']} ends {n} frames before the cut at {b} but has no room")
    for d, nx in zip(bricks, bricks[1:]):
        gap = nx["new_start"] - (d["new_start"] + d["dur"])
        if 0 < gap < min_f:
            if grow_tail(d, gap, fps):
                changed(d, gap, f"end pushed onto the next brick at {nx['new_start']}")
            elif nx["src_in"] >= gap:
                nx["new_start"] -= gap
                nx["src_in"] -= gap
                nx["dur"] += gap
                changed(nx, gap, "start pulled onto the previous brick")
            else:
                B.log(f"WARN {gap}-frame gap between bricks {d['name']} and {nx['name']} could not be closed")
    return snaps


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--bridge", type=int, action="append", default=[], help="sliver record start frame (repeatable)")
    ap.add_argument("--plan", default=None, help="seam_audit.py --plan JSON: per-seam tail/head frames to restore")
    ap.add_argument("--aroll-track", type=int, default=1, help="video track whose source gaps define a bridge")
    ap.add_argument("--snap-top-track", action="store_true", help="snap bricks onto nearby exposed cuts")
    ap.add_argument("--track-name", default=B.BRICK_TRACK, help="brick track name ('' if there is none)")
    ap.add_argument("--min-run-s", type=float, default=1.0)
    ap.add_argument("--comp-dir", default=None, help="restore points + exported Fusion comps "
                                                     "(default: the project's work folder)")
    ap.add_argument("--keep-restores", type=int, default=14, metavar="DAYS",
                    help="age old restore points out of the comp dir (newest always kept; 0 = never)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true", help="skip the automatic .drp backup (not recommended)")
    ap.add_argument("-o", "--out", default=None, help="write the summary JSON here")
    a = ap.parse_args()

    B.refuse_protected(a.timeline)
    pm, proj = B.open_project(a.project)
    tl = B.timeline_by_name(proj, a.timeline)
    fps = B.fps_of(tl)
    t0 = tl.GetStartFrame()
    min_f = int(round(a.min_run_s * fps))
    comp_dir = os.path.abspath(a.comp_dir) if a.comp_dir else B.work_dir(proj.GetName(), "ripple_comps")
    os.makedirs(comp_dir, exist_ok=True)
    nv, na = tl.GetTrackCount("video"), tl.GetTrackCount("audio")
    bt = B.find_brick_track(tl, a.track_name, explicit="--track-name" in sys.argv)

    def items(kind, idx):
        return sorted(tl.GetItemListInTrack(kind, idx) or [], key=lambda i: i.GetStart())

    # plan the bridges: (F, tail, head); --bridge is tail = whole gap
    bridges = []
    v_ref = items("video", a.aroll_track)
    wanted = {F: None for F in a.bridge}
    if a.plan:
        with open(a.plan) as f:
            for e in json.load(f):
                if int(e.get("tail_f", 0)) or int(e.get("head_f", 0)):
                    wanted[int(e["F"])] = (int(e.get("tail_f", 0)), int(e.get("head_f", 0)))
    for F in sorted(wanted):
        S = next((i for i in v_ref if i.GetStart() - t0 == F), None)
        P = next((i for i in v_ref if i.GetEnd() - t0 == F), None)
        if not S or not P:
            sys.exit(f"seam {F}: no a-roll item starting/ending there on V{a.aroll_track} "
                     f"(the timeline changed since the audit? re-run seam_audit.py)")
        g = S.GetLeftOffset() - (P.GetLeftOffset() + (P.GetEnd() - P.GetStart()))
        if g <= 0:
            sys.exit(f"seam {F}: sources already continuous (gap {g})")
        tail, head = wanted[F] if wanted[F] else (g, 0)
        if tail < 0 or head < 0 or tail + head > g:
            sys.exit(f"seam {F}: tail {tail} + head {head} exceeds the source gap {g}")
        bridges.append((F, tail, head))
        B.log(f"seam @{F}: +{tail} tail, +{head} head of {g} removed frames ({(tail + head) / fps:.2f}s)")
    if not bridges and not a.snap_top_track:
        sys.exit("nothing to do (no --bridge, no plan entries, no --snap-top-track)")
    F0 = min([b[0] for b in bridges], default=10 ** 9)

    def shift_at(s):  # cumulative shift for an original position s
        return sum(tail + head for F, tail, head in bridges if F <= s)

    # collect everything at/after F0
    coll = []
    for idx in range(1, nv + 1):
        for it in items("video", idx):
            if it.GetStart() - t0 >= F0:
                coll.append(snap_item(it, t0, "video", idx, comp_dir))
    for idx in range(1, na + 1):
        for it in items("audio", idx):
            if it.GetStart() - t0 >= F0:
                coll.append(snap_item(it, t0, "audio", idx, comp_dir))
    # extension pieces: a copy of the previous item's tail on every track with an item ending at F
    ext = []
    for F, tail, head in bridges:
        if not tail:
            continue
        for kind, n in (("video", nv), ("audio", na)):
            for idx in range(1, n + 1):
                P = next((i for i in items(kind, idx) if i.GetEnd() - t0 == F), None)
                if not P or (kind == "video" and idx == bt):
                    continue  # never extend b-roll bricks
                d = snap_item(P, t0, kind, idx, comp_dir)
                d.update({"start": F, "dur": tail, "src_in": P.GetLeftOffset() + (P.GetEnd() - P.GetStart()),
                          "ext": True})
                ext.append(d)
    # head extension: every non-brick item starting at F grows backwards by head frames
    heads = {F: head for F, tail, head in bridges if head}
    for d in coll:
        h = heads.get(d["start"])
        if not h or (d["kind"] == "video" and d["track"] == bt):
            continue
        if d["src_in"] < h:
            B.log(f"WARN head {h} > available source on {d['kind']} {d['track']}@{d['start']}: not extended")
            continue
        d["src_in"] -= h
        d["dur"] += h
        d["head_ext"] = h
    for d in coll:
        d["new_start"] = d["start"] + shift_at(d["start"]) - d.get("head_ext", 0)
    for d in ext:
        d["new_start"] = d["start"] + shift_at(d["start"] - 1)  # shifts from EARLIER bridges only
    allitems = coll + ext

    # bricks straddling a seam keep covering the same speech: grow by the restored frames
    if bt:
        live_bricks = [(it.GetStart() - t0, it.GetEnd() - t0, it) for it in items("video", bt)]
        for F, tail, head in bridges:
            g = tail + head
            for s_, e_, it in live_bricks:
                if not (s_ < F < e_):
                    continue
                d = next((x for x in coll if x["kind"] == "video" and x["track"] == bt and x["start"] == s_), None)
                if d is None:
                    d = snap_item(it, t0, "video", bt, comp_dir)
                    d["new_start"] = s_
                    d["keep_in_place"] = True
                    coll.append(d)
                    allitems.append(d)
                if grow_tail(d, g, fps):
                    d["snapped"] = True
                    d.pop("keep_in_place", None)
                    B.log(f"brick {d['name']} straddles seam {F}: +{g} frames")
                else:
                    B.log(f"WARN brick {d['name']} straddles seam {F} but has no {g} frames of source")

    # snap bricks onto exposed cuts (in NEW coordinates)
    snaps = []
    if a.snap_top_track and bt:
        bounds = set()
        for idx in [i for i in range(1, nv + 1) if i != bt]:
            runs = []
            for it in items("video", idx):
                s, e = it.GetStart() - t0, it.GetEnd() - t0
                if s >= F0:
                    d = next((x for x in coll if x["kind"] == "video" and x["track"] == idx and x["start"] == s), None)
                    if d:
                        runs.append((d["new_start"], d["new_start"] + d["dur"], d["uid"], d["src_in"], d["enabled"]))
                else:
                    mpi = it.GetMediaPoolItem()
                    uid = mpi.GetUniqueId() if mpi and hasattr(mpi, "GetUniqueId") else it.GetName()
                    runs.append((s, e, uid, it.GetLeftOffset(), bool(it.GetClipEnabled())))
            for d in ext:
                if d["kind"] == "video" and d["track"] == idx:
                    runs.append((d["new_start"], d["new_start"] + d["dur"], d["uid"], d["src_in"], d["enabled"]))
            bounds |= merged_bounds(runs)
        bricks = [d for d in allitems if d["kind"] == "video" and d["track"] == bt]
        for s, e, it in [(it.GetStart() - t0, it.GetEnd() - t0, it) for it in items("video", bt) if it.GetStart() - t0 < F0]:
            if any(d["start"] == s for d in bricks):
                continue
            d = snap_item(it, t0, "video", bt, comp_dir)
            d["new_start"] = s
            d["keep_in_place"] = True
            bricks.append(d)
            allitems.append(d)
        snaps = snap_bricks(bricks, bounds, min_f, fps)
    elif a.snap_top_track:
        B.log("--snap-top-track: no brick track, nothing to snap")

    markers = {f: m for f, m in (tl.GetMarkers() or {}).items() if f >= F0}
    summary = {"bridges": bridges, "shift_total": shift_at(10 ** 9), "snaps": snaps, "items_moved": len(coll),
               "ext_pieces": len(ext), "markers_moved": len(markers),
               "top_track_map": {str(d["start"]): d["new_start"] for d in allitems
                                 if d["kind"] == "video" and d["track"] == bt}}
    if a.out:
        with open(a.out, "w") as f:
            json.dump(summary, f, indent=1)
    if a.dry_run:
        print(json.dumps({k: v for k, v in summary.items() if k != "top_track_map"}, indent=1))
        return
    if not bridges and not any(d.get("snapped") for d in allitems):
        print(json.dumps({k: v for k, v in summary.items() if k != "top_track_map"}, indent=1))
        return

    # project backup, restore point, then delete, then re-append
    if not a.no_backup:
        import backup
        backup.export_drp(pm, proj, f"before ripple_extend on {a.timeline}")
    for p_ in B.prune_scratch(comp_dir, a.keep_restores):
        B.log(f"pruned old restore point: {os.path.basename(p_)}")
    restore = write_restore(comp_dir, f"bridge{F0}" if bridges else "snap",
                            {"project": proj.GetName(), "timeline": a.timeline, "start_frame": t0, "fps": fps,
                             "bridges": bridges, "from_frame": F0}, allitems, markers)
    todel = []
    for idx in range(1, nv + 1):
        todel += [it for it in items("video", idx)
                  if it.GetStart() - t0 >= F0 or any(d.get("snapped") and d.get("start") == it.GetStart() - t0
                                                      and d["track"] == idx and d["kind"] == "video"
                                                      for d in allitems)]
    for idx in range(1, na + 1):
        todel += [it for it in items("audio", idx) if it.GetStart() - t0 >= F0]
    # clips FIRST: a failed delete must leave the markers where they are
    if not B.delete_clips(tl, todel):
        sys.exit(f"DeleteClips failed; the timeline should be untouched, check it. Restore point: {restore}")
    for f in markers:
        tl.DeleteMarkerAtFrame(f)
    mp = proj.GetMediaPool()
    fails = reappend_snapshots(mp, tl, [d for d in allitems if not d.get("keep_in_place")], t0, fps)
    for f, m in markers.items():  # marker frames are relative to the timeline start, like --bridge
        tl.AddMarker(f + shift_at(f), m.get("color", "Blue"), m.get("name", ""), m.get("note", ""),
                     m.get("duration", 1), m.get("customData", ""))
    pm.SaveProject()
    summary["append_failures"] = fails
    summary["restore_point"] = restore
    if a.out:
        with open(a.out, "w") as f:
            json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "top_track_map"}, indent=1))
    if fails:
        sys.exit(f"{len(fails)} appends failed: inspect the timeline; restore point {restore}")


if __name__ == "__main__":
    main()
