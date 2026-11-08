#!/usr/bin/env python3
"""Check a placement plan against the live inventory, and snap brick edges
onto the a-roll's cuts BEFORE anything touches Resolve.

Errors (exit 3, fix the plan and re-run):
  * a field is missing, or a source range is empty or runs past the clip
  * two placements overlap, or a placement overlaps a brick already on the
    timeline (the user's or an earlier pass's): bricks only fill EMPTY space
  * the same source range is used twice
  * the a-roll or supply timeline is a backup / on the never-touch list
  * a placement runs past the end of the timeline
  * after snapping, the viewer would still see a flash: an a-roll shot, gap
    or brick shorter than --min-run-s next to a planned brick
Warnings (the verifier and the user look at them):
  * a brick shorter than 3 s or longer than 15 s
  * a brick over words that point at the camera ("this one here", "as you
    can see", "look at"): the speaker may be showing something on camera

Snapping (always on; --no-snap to only report): a brick starting less than
--snap-s AFTER an exposed a-roll cut is pulled back onto the cut (its source
in-point moves earlier by the same amount; slid when the clip has no head
room); a brick ending less than --snap-s BEFORE a cut is extended onto it;
two bricks less than --snap-s apart are butted. Bricks are planned in
seconds, cuts are exact frames: this is where one-frame flashes come from.

Plan format: reference/formats.md. record_s = seconds from the timeline
start; use_src_* = seconds in the source file (native, real time).

Usage:
  check_plan.py plan.json --inventory inventory.json [--transcript edited_transcript.json]
                [--min-run-s 0.6] [--snap-s 1.0] [--no-snap] [--no-probe] [-o snapped_plan.json | --write]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402
import flicker_audit as FA  # noqa: E402

DEICTIC = re.compile(r"\b(this one|right here|over here|as you can see|you can see|look at (this|that|it)|"
                     r"take a look|see (this|that|here)|check (this|it) out)\b", re.I)


def aroll_tracks_from_inventory(inv):
    """{track index: merged items (frames from the timeline start)} for the
    a-roll cameras, plus the coverage items on every other non-brick track."""
    ar = inv["aroll"]
    t0 = ar["start_frame"]
    brick_idx = ar.get("brick_track")
    cams = ar.get("aroll_video_tracks") or [1]
    tracks, overlays, bricks = {}, [], []
    for t in ar["video_tracks"]:
        items = [{"name": i["name"], "start": i["record_frame"] - t0, "end": i["record_end_frame"] - t0,
                  "enabled": i.get("enabled", True), "src_in": i["src_start_frame"], "still": False,
                  "media": i["file_path"] or i["name"]} for i in t["items"]]
        if t["index"] == brick_idx:
            bricks = items
        elif t["index"] in cams:
            tracks[t["index"]] = FA.merge_track(items)
        else:
            overlays += items
    return tracks, overlays, bricks, brick_idx, ar["end_frame"] - t0


def clip_duration(p, inv, probe=True):
    if p.get("clip_duration_s"):
        return float(p["clip_duration_s"])
    if p.get("media") and probe and os.path.exists(p["media"]):
        try:
            return B.media.duration(p["media"])
        except SystemExit:
            return None
    if p.get("broll_timeline"):
        for tl in inv.get("broll", []):
            if tl["name"] != p["broll_timeline"]:
                continue
            for t in tl["video_tracks"]:
                for i in t["items"]:
                    key = (i.get("file_path") or "") + " " + i["name"]
                    if p.get("file_hint", "") in key and i.get("src_end_s") is not None \
                            and i["src_start_s"] - 0.4 <= p["use_src_start_s"] and i["src_end_s"] + 0.4 >= p["use_src_end_s"]:
                        return i["src_end_s"]
    return None


def source_key(p):
    return p.get("media") or f"{p.get('broll_timeline')}::{p.get('file_hint')}"


def check(plan, inv, words=None, min_run_s=0.6, snap_s=1.0, snap=True, probe=True):
    """Pure (given a probe-free plan): returns (snapped_plan, report)."""
    fps = float(inv["aroll"]["fps"])
    errors, warnings, snaps = [], [], []
    plan = json.loads(json.dumps(plan))
    pl = plan.get("placements", [])
    extra = plan.get("never_touch", [])
    for name in {plan.get("aroll_timeline")} | {p.get("broll_timeline") for p in pl}:
        if name and B.is_protected(name, extra):
            errors.append(f"timeline {name!r} is a backup / never-touch timeline")
    tracks, overlays, existing, brick_idx, end_f = aroll_tracks_from_inventory(inv)
    min_f, snap_f = int(round(min_run_s * fps)), int(round(snap_s * fps))
    bricks = []
    for n, p in enumerate(pl):
        pid = p.setdefault("id", n + 1)
        miss = [k for k in ("use_src_start_s", "use_src_end_s", "record_s") if k not in p]
        if not p.get("media") and not (p.get("broll_timeline") and p.get("file_hint")):
            miss.append("media (or broll_timeline + file_hint)")
        if miss:
            errors.append(f"placement {pid}: missing {', '.join(miss)}")
            continue
        if p["use_src_end_s"] <= p["use_src_start_s"] or p["use_src_start_s"] < 0:
            errors.append(f"placement {pid}: empty or negative source range")
            continue
        dur = clip_duration(p, inv, probe)
        if dur is not None and p["use_src_end_s"] > dur + 0.05:
            errors.append(f"placement {pid}: source range ends at {p['use_src_end_s']}s, the clip is {dur:.2f}s")
        bricks.append({"p": p, "id": pid, "start": int(round(p["record_s"] * fps)),
                       "dur": int(round((p["use_src_end_s"] - p["use_src_start_s"]) * fps)),
                       "src_in": int(round(p["use_src_start_s"] * fps)),
                       "room": None if dur is None else int(round(dur * fps)) - int(round(p["use_src_end_s"] * fps))})
    bricks.sort(key=lambda b: b["start"])

    def occupied(f, skip=None):
        if any(e["start"] <= f < e["end"] for e in existing):
            return True
        return any(b is not skip and b["start"] <= f < b["start"] + b["dur"] for b in bricks)

    if snap and not errors:
        bounds = sorted({x for items in tracks.values() for it in items for x in (it["start"], it["end"])}
                        | {e["start"] for e in existing} | {e["end"] for e in existing})
        for b in bricks:
            s = b["start"]
            c = [x for x in bounds if 0 < s - x < snap_f and not any(occupied(f, b) for f in range(x, s))]
            if c:
                x = min(c)
                n = s - x
                if b["src_in"] >= n:
                    b["src_in"] -= n
                    b["dur"] += n
                    how = "start pulled back onto the cut"
                else:
                    how = "slid back onto the cut (no head room in the clip; its end moved too)"
                b["start"] = x
                snaps.append({"id": b["id"], "frames": n, "how": how, "at": B.tc(x, fps)})
        for b in bricks:
            e = b["start"] + b["dur"]
            c = [x for x in bounds if 0 < x - e < snap_f and not any(occupied(f, b) for f in range(e, x))]
            if c:
                x = min(c)
                n = x - e
                if b["room"] is None or b["room"] >= n:
                    b["dur"] += n
                    if b["room"] is not None:
                        b["room"] -= n
                    snaps.append({"id": b["id"], "frames": n, "how": "end pushed onto the cut", "at": B.tc(x, fps)})
                elif b["src_in"] >= n - max(0, b["room"]):
                    short = n - max(0, b["room"])
                    b["src_in"] -= short
                    b["dur"] += n
                    b["room"] = 0
                    snaps.append({"id": b["id"], "frames": n, "how": "end pushed onto the cut (source window "
                                  "moved earlier: the clip had no tail left)", "at": B.tc(x, fps)})
                else:
                    warnings.append(f"placement {b['id']}: ends {n} frames before a cut but the clip has no room")
        for b, nx in zip(bricks, bricks[1:]):
            gap = nx["start"] - (b["start"] + b["dur"])
            if 0 < gap < snap_f and not any(occupied(f) for f in range(b["start"] + b["dur"], nx["start"])):
                if b["room"] is None or b["room"] >= gap:
                    b["dur"] += gap
                    if b["room"] is not None:
                        b["room"] -= gap
                    snaps.append({"id": b["id"], "frames": gap, "how": "end pushed onto the next brick"})
                elif nx["src_in"] >= gap:
                    nx["start"] -= gap
                    nx["src_in"] -= gap
                    nx["dur"] += gap
                    snaps.append({"id": nx["id"], "frames": gap, "how": "start pulled onto the previous brick"})
        for b in bricks:  # write back, frame-exact seconds
            p = b["p"]
            p["record_s"] = round(b["start"] / fps, 6)
            p["use_src_start_s"] = round(b["src_in"] / fps, 6)
            p["use_src_end_s"] = round((b["src_in"] + b["dur"]) / fps, 6)

    # overlaps, reuse, length, end of timeline
    for b, nx in zip(bricks, bricks[1:]):
        if nx["start"] < b["start"] + b["dur"]:
            errors.append(f"placements {b['id']} and {nx['id']} overlap on the timeline")
    for b in bricks:
        s, e = b["start"], b["start"] + b["dur"]
        for x in existing:
            if x["start"] < e and x["end"] > s:
                errors.append(f"placement {b['id']} overlaps the brick already at {B.tc(x['start'], fps)} "
                              f"({x['name']}): only fill empty space; re-read the live timeline")
        if e > end_f:
            errors.append(f"placement {b['id']} runs past the end of the timeline")
        secs = b["dur"] / fps
        if secs < 3 or secs > 15:
            warnings.append(f"placement {b['id']}: {secs:.1f}s on the timeline (3-15 s reads best)")
    by_src = {}
    for b in bricks:
        by_src.setdefault(source_key(b["p"]), []).append(b["p"])
    for k, ps in by_src.items():
        ps.sort(key=lambda p: p["use_src_start_s"])
        for p, q in zip(ps, ps[1:]):
            if q["use_src_start_s"] < p["use_src_end_s"] - 0.04:
                errors.append(f"placements {p['id']} and {q['id']} use the same source range of {os.path.basename(k)}")
    if words:
        for b in bricks:
            s, e = b["start"] / fps, (b["start"] + b["dur"]) / fps
            text = " ".join(w["word"].strip() for w in words if s <= w["start"] < e)
            m = DEICTIC.search(text)
            if m:
                warnings.append(f"placement {b['id']}: covers {m.group(0)!r}; check the a-roll frames: is the "
                                f"speaker showing something on camera?")
    # flashes the plan would create
    flashes = []
    if not errors:
        planned = [{"name": f"plan#{b['id']}", "start": b["start"], "end": b["start"] + b["dur"], "enabled": True,
                    "src_in": b["src_in"], "still": False, "media": source_key(b["p"])} for b in bricks]
        top = (max(tracks) if tracks else 1) + 1 if brick_idx is None else brick_idx
        sim = dict(tracks)
        sim[top] = sorted(existing + planned, key=lambda i: i["start"])
        if overlays:  # the user's other overlays count as cover for what the viewer sees
            sim[top + 100] = FA.merge_track(overlays)
        found = FA.find_flicker(sim, end_f, fps, min_f, sorted(tracks), top)
        edges = [(b["start"], b["start"] + b["dur"]) for b in bricks]
        for f in found:
            if f["kind"] == "aroll-gap":
                continue
            near = any(f["start_f"] <= e + min_f and f["end_f"] >= s - min_f for s, e in edges)
            (flashes if near else warnings).append(f if near else f"pre-existing: {f['tc']} {f['msg']}")
    report = {"placements": len(bricks), "errors": errors, "flashes": flashes, "warnings": warnings, "snaps": snaps}
    return plan, report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--inventory", required=True, help="inventory.py output, taken just before planning")
    ap.add_argument("--transcript", default=None, help="edited_transcript.py output (deictic-word warnings)")
    ap.add_argument("--min-run-s", type=float, default=0.6)
    ap.add_argument("--snap-s", type=float, default=1.0)
    ap.add_argument("--no-snap", action="store_true")
    ap.add_argument("--no-probe", action="store_true", help="do not ffprobe clip durations")
    ap.add_argument("-o", "--out", default=None, help="write the snapped plan here")
    ap.add_argument("--write", action="store_true", help="write the snapped plan back over PLAN")
    a = ap.parse_args()
    with open(a.plan) as f:
        plan = json.load(f)
    with open(a.inventory) as f:
        inv = json.load(f)
    words = None
    if a.transcript:
        with open(a.transcript) as f:
            words = [w for s in json.load(f).get("segments", []) for w in s.get("words", [])]
    out_plan, rep = check(plan, inv, words, a.min_run_s, a.snap_s, not a.no_snap, not a.no_probe)
    dest = a.plan if a.write else a.out
    if dest and not rep["errors"]:
        with open(dest, "w") as f:
            json.dump(out_plan, f, indent=1)
        B.log(f"snapped plan -> {dest}")
    print(json.dumps(rep, indent=1))
    sys.exit(3 if rep["errors"] or rep["flashes"] else 0)


if __name__ == "__main__":
    main()
