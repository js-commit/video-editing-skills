#!/usr/bin/env python3
"""Write the cuts sidecar for a rendered draft: where every clip starts and
ends in the FILE. EditReview draws these on its timeline, snaps the playhead
to them (mouse and the up / down arrow keys) and names the clip under each note.

    export_cuts.py VIDEO                         # from the open DaVinci Resolve project
    export_cuts.py VIDEO --timeline NAME         # that timeline, no guessing
    export_cuts.py VIDEO --project P             # load project P first
    export_cuts.py VIDEO --segments SEG.json     # no Resolve: from a segment list (ffmpeg renders)

Writes <video-stem>.review/cuts.json (schema edit-review-cuts/1, see
apps/edit-review/SPEC.md) and prints its path on stdout.

From Resolve (needs DaVinci Resolve Studio running, with external scripting
enabled): read-only, nothing on the timeline is touched and the current
timeline is not switched. Without --timeline it takes the current timeline if
its length matches the file; otherwise the one timeline whose length matches;
if several match, the one whose name is in the file name. No match is an
error: a sidecar from the wrong timeline is worse than none.

What counts as a cut: the file is one flat picture, so the cuts are the places
where the TOPMOST full-frame clip changes. Titles, generators, Fusion comps
(no media behind them), picture-in-picture clips (zoom < 0.95) and
semi-transparent clips are overlays: listed under "overlays", never a cut.
Disabled clips and disabled tracks are ignored. Transitions are invisible to
the scripting API; a dissolve's cut sits at the clip boundary under it.

From a segment list (--segments): for files rendered by ffmpeg (a
talking-head-ffmpeg recipe, a montage). The JSON is a list, or an object with
"segments" (and optional "overlays", "project", "timeline"), of
  {"start_s": 0.0, "end_s": 4.2, "name": "take-1", "source": "/abs/take-1.mov",
   "source_start_s": 12.0, "track": 1}
in FILE seconds. Only start_s and end_s are required. Overlapping segments:
the higher track wins, as in an NLE. Holes become gaps.

Exit codes: 0 written, 1 bad input / no matching timeline, 3 Resolve not answering.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools"))

SCHEMA = "edit-review-cuts/1"
# A render's container duration differs from frames / fps by audio priming and
# rounding; a different cut differs by whole shots. 0.2 s separates the two.
DURATION_TOLERANCE_S = 0.2
NTSC = {23.976: 24000 / 1001, 23.98: 24000 / 1001, 29.97: 30000 / 1001,
        47.952: 48000 / 1001, 59.94: 60000 / 1001, 119.88: 120000 / 1001}


def true_fps(value) -> float:
    """Resolve reports 29.97 for 30000/1001; seconds need the exact rate."""
    f = float(value)
    for shown, exact in NTSC.items():
        if abs(f - shown) < 0.011:
            return exact
    return f


def sidecar_path(video) -> Path:
    return Path(video).with_suffix(".review") / "cuts.json"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def flatten(full: list, t0, t1) -> list:
    """Between consecutive boundaries the picture is the highest track's item.
    Items are dicts with start, end, track; returns [{start, end, top}]."""
    edges = sorted({t0, t1} | {e["start"] for e in full} | {e["end"] for e in full})
    edges = [e for e in edges if t0 <= e <= t1]
    segments = []
    for a, b in zip(edges, edges[1:]):
        if b <= a:
            continue
        covering = [e for e in full if e["start"] <= a and e["end"] >= b]
        top = max(covering, key=lambda e: e["track"]) if covering else None
        if segments and segments[-1]["top"] is top:
            segments[-1]["end"] = b
        else:
            segments.append({"start": a, "end": b, "top": top})
    return segments


# ---------------------------------------------------------------- from Resolve

def _call(obj, method, *args, default=None):
    """Resolve API calls missing on this version come back as a None attribute;
    a call that fails returns None or raises. Either way: default."""
    fn = getattr(obj, method, None)
    if fn is None:
        return default
    try:
        out = fn(*args)
    except Exception:
        return default
    return default if out is None else out


def _overlay_reason(item):
    """Why this item is not a full-frame picture, or None if it is one."""
    if _call(item, "GetMediaPoolItem") is None:
        return "no media (title / generator / Fusion / adjustment)"
    try:
        zx = float(_call(item, "GetProperty", "ZoomX", default=1.0))
        zy = float(_call(item, "GetProperty", "ZoomY", default=1.0))
        if min(zx, zy) < 0.95:
            return f"picture-in-picture (zoom {min(zx, zy):.2f})"
        op = float(_call(item, "GetProperty", "Opacity", default=100.0))
        if op < 99:
            return f"semi-transparent (opacity {op:.0f})"
    except (TypeError, ValueError):
        pass
    return None


def cuts_document(tl, project_name="", mark_in=None, mark_out=None, video_name="") -> dict:
    """The sidecar as a dict, from a Resolve timeline. mark_in / mark_out: the
    rendered range in timeline frames, mark_out INCLUSIVE (a render job's
    MarkIn / MarkOut); default the whole timeline. A render script can call
    write_sidecar() right after a successful render."""
    fps = true_fps(tl.GetSetting("timelineFrameRate"))
    t0 = int(tl.GetStartFrame()) if mark_in is None else int(mark_in)
    t1 = int(tl.GetEndFrame()) if mark_out is None else int(mark_out) + 1   # exclusive
    full, overlays = [], []
    tracks = range(1, int(tl.GetTrackCount("video")) + 1)
    # GetIsTrackEnabled can answer False for every track of a timeline that is
    # not the current one, so an all-False reading means "unknown".
    enabled = {t: _call(tl, "GetIsTrackEnabled", "video", t, default=True) is not False for t in tracks}
    if not any(enabled.values()):
        enabled = {t: True for t in tracks}
    for track in tracks:
        if not enabled[track]:
            continue
        for item in tl.GetItemListInTrack("video", track) or []:
            if _call(item, "GetClipEnabled", default=True) is False:
                continue
            start, end = int(item.GetStart()), int(item.GetEnd())
            if end <= t0 or start >= t1:
                continue
            entry = {"track": track, "start": max(start, t0), "end": min(end, t1),
                     "item_start": start, "name": item.GetName() or "", "item": item}
            why = _overlay_reason(item)
            if why:
                entry["why"] = why
                overlays.append(entry)
            else:
                full.append(entry)

    def seconds(frame):
        return round((frame - t0) / fps, 6)

    cuts = []
    for n, seg in enumerate(flatten(full, t0, t1), 1):
        top = seg["top"]
        cut = {"index": n, "start_s": seconds(seg["start"]), "end_s": seconds(seg["end"]),
               "start_frame": seg["start"] - t0, "end_frame": seg["end"] - t0,
               "kind": "clip" if top else "gap", "track": top["track"] if top else 0,
               "name": top["name"] if top else "(gap)"}
        if top:
            item = top["item"]
            mpi = _call(item, "GetMediaPoolItem")
            path = _call(mpi, "GetClipProperty", "File Path", default="") if mpi else ""
            cut["source"] = path or None
            # Source frame on screen at the segment's first frame (the item may start earlier).
            src0 = _call(item, "GetSourceStartFrame")
            if src0 is None:
                src0 = _call(item, "GetLeftOffset")
            cut["source_start_frame"] = (int(src0) + seg["start"] - top["item_start"]
                                         if src0 is not None else None)
        cuts.append(cut)

    return {
        "schema": SCHEMA,
        "video": video_name,
        "project": project_name,
        "timeline": tl.GetName(),
        "frame_rate": round(fps, 6),
        "timeline_start_frame": int(tl.GetStartFrame()),
        "render_in_frame": t0,
        "render_out_frame": t1 - 1,
        "duration_s": round((t1 - t0) / fps, 6),
        "written_at": now_utc(),
        "cuts": cuts,
        "overlays": [{"track": o["track"], "start_s": seconds(o["start"]), "end_s": seconds(o["end"]),
                      "name": o["name"], "why": o["why"]}
                     for o in sorted(overlays, key=lambda o: (o["start"], o["track"]))],
    }


def write_sidecar(video, tl, project_name="", mark_in=None, mark_out=None):
    """Build and write <stem>.review/cuts.json for `video` from a Resolve
    timeline; returns (path, document)."""
    video = Path(video)
    doc = cuts_document(tl, project_name, mark_in, mark_out, video.name)
    out = sidecar_path(video)
    write_json(out, doc)
    return out, doc


def timeline_seconds(tl) -> float:
    return (int(tl.GetEndFrame()) - int(tl.GetStartFrame())) / true_fps(tl.GetSetting("timelineFrameRate"))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def pick_timeline(proj, video: Path, duration, wanted=None):
    """The timeline `video` was rendered from, or exit with the reason."""
    tls = [proj.GetTimelineByIndex(i) for i in range(1, int(proj.GetTimelineCount()) + 1)]
    if wanted:
        tl = next((t for t in tls if t.GetName() == wanted), None)
        if tl is None:
            sys.exit(f"no timeline {wanted!r} in {proj.GetName()!r}: {[t.GetName() for t in tls]}")
        if duration is not None and abs(timeline_seconds(tl) - duration) > DURATION_TOLERANCE_S:
            sys.exit(f"{wanted!r} is {timeline_seconds(tl):.2f} s but {video.name} is {duration:.2f} s: "
                     f"not the timeline this file was rendered from (or it changed since)")
        return tl
    if duration is None:
        sys.exit("could not read the file's duration, so the timeline cannot be checked "
                 "against it; name it with --timeline")

    def fits(t):
        return abs(timeline_seconds(t) - duration) <= DURATION_TOLERANCE_S

    cur = proj.GetCurrentTimeline()
    if cur is not None and fits(cur):
        return cur
    matches = [t for t in tls if fits(t)]
    if len(matches) > 1:
        stem = slug(video.stem)
        named = [t for t in matches if slug(t.GetName()) and slug(t.GetName()) in stem]
        if named:   # the longest name is the most specific ("v4" vs "v4-final")
            matches = [max(named, key=lambda t: len(t.GetName()))]
    if len(matches) == 1:
        return matches[0]
    names = [f"{t.GetName()} ({timeline_seconds(t):.2f} s)" for t in (matches or tls)]
    sys.exit(f"{video.name} is {duration:.2f} s; "
             + ("several timelines match, pass --timeline: " if matches else
                f"no timeline in {proj.GetName()!r} is that long: ") + ", ".join(names))


def from_resolve(video: Path, project: str | None, timeline: str | None):
    from vidkit import media
    from vidkit.resolve import connect
    resolve = connect()
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if project and (proj is None or proj.GetName() != project):
        proj = pm.LoadProject(project)
        if proj is None:
            sys.exit(f"cannot load project {project!r}")
    if proj is None:
        sys.exit("no project open in DaVinci Resolve")
    tl = pick_timeline(proj, video, media.probe(video)["duration"], timeline)
    return write_sidecar(video, tl, proj.GetName())


# ---------------------------------------------------------------- from a segment list

def segments_document(video: Path, spec, fps: float, duration: float) -> dict:
    if isinstance(spec, dict):
        segs, overlays = spec.get("segments") or [], spec.get("overlays") or []
        project, timeline = spec.get("project") or "", spec.get("timeline") or ""
    else:
        segs, overlays, project, timeline = spec, [], "", ""
    if not isinstance(segs, list) or not segs:
        sys.exit("the segment list is empty")
    total = int(round(duration * fps))
    full = []
    for i, s in enumerate(segs):
        try:
            a, b = float(s["start_s"]), float(s["end_s"])
        except (KeyError, TypeError, ValueError):
            sys.exit(f"segment {i}: needs numeric start_s and end_s")
        fa, fb = max(0, int(round(a * fps))), min(total, int(round(b * fps)))
        if fb > fa:
            full.append({"start": fa, "end": fb, "track": int(s.get("track", 1)), "seg": s, "seg_start": a})
    cuts = []
    for n, seg in enumerate(flatten(full, 0, total), 1):
        top = seg["top"]
        cut = {"index": n, "start_s": round(seg["start"] / fps, 6), "end_s": round(seg["end"] / fps, 6),
               "start_frame": seg["start"], "end_frame": seg["end"],
               "kind": "clip" if top else "gap", "track": top["track"] if top else 0,
               "name": str(top["seg"].get("name") or f"segment {n}") if top else "(gap)"}
        if top:
            s = top["seg"]
            cut["source"] = s.get("source")
            if s.get("source_start_s") is not None:
                offset = seg["start"] / fps - top["seg_start"]
                cut["source_start_frame"] = int(round((float(s["source_start_s"]) + max(0.0, offset)) * fps))
            else:
                cut["source_start_frame"] = None
        cuts.append(cut)
    return {
        "schema": SCHEMA,
        "video": video.name,
        "project": project,
        "timeline": timeline,
        "frame_rate": round(fps, 6),
        "timeline_start_frame": 0,
        "render_in_frame": 0,
        "render_out_frame": total - 1,
        "duration_s": round(duration, 6),
        "written_at": now_utc(),
        "cuts": cuts,
        "overlays": [{"track": int(o.get("track", 2)), "start_s": float(o["start_s"]),
                      "end_s": float(o["end_s"]), "name": str(o.get("name", "")),
                      "why": str(o.get("why", "overlay"))} for o in overlays],
    }


def from_segments(video: Path, seg_file: Path):
    from vidkit import media
    try:
        spec = json.loads(seg_file.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read {seg_file}: {e}")
    info = media.probe(video)
    if not info["fps_float"] or not info["duration"]:
        sys.exit(f"{video} has no video stream with a frame rate and duration")
    doc = segments_document(video, spec, info["fps_float"], info["duration"])
    out = sidecar_path(video)
    write_json(out, doc)
    return out, doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path, help="the rendered file")
    ap.add_argument("--project", help="Resolve: load this project first (default: the open one)")
    ap.add_argument("--timeline", help="Resolve: timeline name (default: picked by length)")
    ap.add_argument("--segments", type=Path, metavar="FILE",
                    help="no Resolve: build the sidecar from this segment list (file seconds)")
    args = ap.parse_args()
    video = args.video.expanduser().resolve()
    if not video.is_file():
        sys.exit(f"no such file: {video}")

    if args.segments:
        out, doc = from_segments(video, args.segments.expanduser())
    else:
        out, doc = from_resolve(video, args.project, args.timeline)
    clips = [c for c in doc["cuts"] if c["kind"] == "clip"]
    print(out)
    where = " / ".join(x for x in (doc["project"], doc["timeline"]) if x) or "segment list"
    print(f"  {where}: {len(doc['cuts'])} cuts ({len(clips)} clips, {len(doc['cuts']) - len(clips)} gaps), "
          f"{len(doc['overlays'])} overlays, {doc['duration_s']:.2f} s @ {doc['frame_rate']:g} fps",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
