#!/usr/bin/env python3
"""Drop red NEED BROLL markers where b-roll should go but nothing matched.

The only markers this skill places. A wrong brick is worse than a gap, so a
transcript stretch with no honest match becomes a need in needs.json, and
this puts a red marker on it for the user (or a broll-hunt agent) to fill.
Rationale for placed bricks stays in plan.json ("why"), never on the timeline:
dozens of explanation markers are noise.

needs.json: {"project": "...", "timeline": "...",
             "needs": [{"record_s": 88.5, "end_s": 96.0, "note": "what the words are about"}]}
record_s / end_s are seconds from the timeline start.

A need only gets a marker where the picture is still bare: spans already
covered on video tracks >= --skip-covered-from-track (bricks, stills, the
user's own overlays) are subtracted first, so a need the user has filled
by hand goes quiet on the next run. Default: the first track above the
a-roll cameras.

In Resolve, jump between markers with Shift+Up / Shift+Down arrow on the Edit
page; double-click a marker to read its note.

Usage:
  add_markers.py --needs needs.json [--clear-first] [--skip-covered-from-track N|auto] [--min-need-s 1.5]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402

NEED_COLOR = "Red"
MARKER_TAG = "broll-brick-layer:need"   # customData on our markers: --clear-first removes only these


def subtract(s0, s1, spans):
    """Pure: the parts of [s0, s1] not covered by any (start, end) span."""
    out = [(s0, s1)]
    for c0, c1 in spans:
        nxt = []
        for a, b in out:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
            else:
                if a < c0:
                    nxt.append((a, c0))
                if c1 < b:
                    nxt.append((c1, b))
        out = nxt
    return out


def covered_spans(tl, fps, from_track):
    t0 = tl.GetStartFrame()
    spans = []
    for idx in range(from_track, tl.GetTrackCount("video") + 1):
        for it in tl.GetItemListInTrack("video", idx) or []:
            spans.append(((it.GetStart() - t0) / fps, (it.GetEnd() - t0) / fps))
    return sorted(spans)


def add(tl, frame, color, name, note, dur_frames):
    for bump in range(12):  # two markers cannot share a frame: nudge until it takes
        if tl.AddMarker(frame + bump, color, name, note, max(1, dur_frames), MARKER_TAG):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--needs", required=True)
    ap.add_argument("--clear-first", action="store_true", help="delete the NEED BROLL markers an earlier run added first (never the user's own markers)")
    ap.add_argument("--skip-covered-from-track", default="auto", metavar="N|auto")
    ap.add_argument("--min-need-s", type=float, default=1.5, help="drop leftover bare slivers shorter than this")
    a = ap.parse_args()
    with open(a.needs) as f:
        doc = json.load(f)
    B.refuse_protected(doc["timeline"], doc.get("never_touch", []))
    pm, proj = B.open_project(doc["project"])
    tl = B.timeline_by_name(proj, doc["timeline"])
    fps = B.fps_of(tl)
    if a.skip_covered_from_track == "auto":
        import flicker_audit as FA
        tracks, _, end_f = FA.dump_tracks(tl)
        cams = FA.auto_aroll_tracks(tracks, end_f, B.find_brick_track(tl, B.BRICK_TRACK))
        from_track = (max(cams) + 1) if cams else 2
    else:
        from_track = int(a.skip_covered_from_track)
    if a.clear_first:   # only ours: tagged, or (older runs) red and named exactly "NEED BROLL"
        for frame, m in (tl.GetMarkers() or {}).items():
            if m.get("customData") == MARKER_TAG or (m.get("color") == NEED_COLOR and m.get("name") == "NEED BROLL"
                                                     and not m.get("customData")):
                tl.DeleteMarkerAtFrame(frame)
    spans = covered_spans(tl, fps, from_track)
    n_ok = n_fail = 0
    for nd in doc.get("needs", []):
        s0, s1 = nd["record_s"], nd.get("end_s", nd["record_s"] + 1)
        pieces = [(x, y) for x, y in subtract(s0, s1, spans) if y - x >= a.min_need_s]
        if not pieces:
            B.log(f"  need {s0:.1f}-{s1:.1f}s already covered: no marker ({nd.get('note', '')[:50]})")
            continue
        for x, y in pieces:
            ok = add(tl, round(x * fps), NEED_COLOR, "NEED BROLL", nd.get("note", ""), round((y - x) * fps))
            n_ok += ok
            n_fail += not ok
    pm.SaveProject()
    print(json.dumps({"markers_added": n_ok, "failed": n_fail, "covered_from_track": from_track}))
    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
