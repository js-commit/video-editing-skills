#!/usr/bin/env python3
"""Export a review: turn notes.json into the plain files other tools read.

    export_review.py VIDEO            # or the <video-stem>.review/ folder itself

Writes into <video-stem>.review/:

  review.jsonl   one object per live note, in time order:
                 {"timecode": "00:04:37:12", "seconds": 277.5, "frame_rate": 29.97,
                  "text": "jump cut"}
  markers.edl    one marker per note in the EDL format DaVinci Resolve writes
                 for timeline markers (Timeline > Import > Timeline Markers
                 from EDL). Experimental: --to-resolve is the dependable
                 way to get the markers into Resolve.

With --to-resolve the same markers are added straight onto the current
timeline of the open Resolve project through the scripting API (needs
DaVinci Resolve Studio running). Each carries customData
"edit-review:<seconds>", so --clear-resolve removes exactly those again.

`seconds` is file-relative; `timecode` adds the file's start timecode
(notes.json start_timecode) so it matches the Resolve timeline ruler.

Exit codes: 0 ok, 1 bad input, 3 Resolve not answering.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools"))

RESOLVE_COLORS = {
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
    "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream",
}
MARKER_TAG = "edit-review:"


# ---------------------------------------------------------------- timecode

def tc_base(fps: float) -> int:
    """Non-drop timecode counts 24 / 30 / 60 frames per second for 23.976 / 29.97 / 59.94."""
    return max(1, int(round(fps)))


def tc_parse(text, fps):
    """HH:MM:SS:FF -> frame count (non-drop), or None."""
    m = re.fullmatch(r"\s*(\d+)[:;](\d\d?)[:;](\d\d?)[:;](\d\d?)\s*", text or "")
    if not m:
        return None
    h, mi, s, f = (int(x) for x in m.groups())
    b = tc_base(fps)
    if mi >= 60 or s >= 60 or f >= b:
        return None
    return ((h * 60 + mi) * 60 + s) * b + f


def tc_string(frames: int, fps: float) -> str:
    b = tc_base(fps)
    f = max(0, frames)
    return "%02d:%02d:%02d:%02d" % (f // (b * 3600), (f // (b * 60)) % 60, (f // b) % 60, f % b)


def seconds_to_frames(seconds: float, fps: float) -> int:
    return max(0, int(seconds * fps + 1e-6))


def true_fps(value) -> float:
    f = float(value)
    for shown, exact in ((23.976, 24000 / 1001), (29.97, 30000 / 1001), (59.94, 60000 / 1001)):
        if abs(f - shown) < 0.011:
            return exact
    return f


# ---------------------------------------------------------------- inputs

def review_dir_for(arg: str) -> Path:
    p = Path(arg).expanduser().resolve()
    if p.is_dir() and p.suffix == ".review":
        return p
    if p.is_file():
        d = p.with_suffix(".review")
        if d.is_dir():
            return d
        sys.exit(f"no review folder next to {p.name} (expected {d})")
    sys.exit(f"not a video file or .review folder: {p}")


def probe_fps(video: Path) -> float:
    from vidkit import media
    fps = media.probe(video)["fps_float"]
    if not fps:
        sys.exit(f"could not read the frame rate of {video}")
    return round(fps, 3)


def review_rows(review_dir: Path, log=lambda m: print(m, file=sys.stderr)):
    """The live notes of a review folder as review.jsonl rows, in time order,
    and the file's frame rate: (rows, fps)."""
    notes_path = review_dir / "notes.json"
    if not notes_path.exists():
        sys.exit(f"no notes.json in {review_dir}")
    doc = json.loads(notes_path.read_text())
    notes = sorted(doc.get("notes", []), key=lambda n: float(n["seconds"]))
    video_name = doc.get("video") or ""
    video = review_dir.parent / video_name if video_name else None
    fps = doc.get("frame_rate")
    if not fps:
        if not (video and video.exists()):
            sys.exit("notes.json has no frame_rate and the video is not next to the .review folder")
        fps = probe_fps(video)
    start_frames = tc_parse(doc.get("start_timecode", "00:00:00:00"), fps)
    if start_frames is None:
        log(f"start_timecode {doc.get('start_timecode')!r} is not valid at {fps} fps; using 00:00:00:00")
        start_frames = 0
    return [{
        "timecode": tc_string(seconds_to_frames(float(n["seconds"]), fps) + start_frames, fps),
        "seconds": round(float(n["seconds"]), 3),
        "frame_rate": fps,
        "text": (n.get("text") or "").strip(),
    } for n in notes], fps


# ---------------------------------------------------------------- outputs

def marker_name(row: dict, limit: int = 80) -> str:
    name = " ".join((row["text"] or "review note").split())
    return name if len(name) <= limit else name[: limit - 1] + "…"


def write_edl(path: Path, title: str, rows: list, fps: float, color: str) -> None:
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for i, n in enumerate(rows, 1):
        start = tc_parse(n["timecode"], fps)
        end = tc_string(start + 1, fps)
        lines.append(f"{i:03d}  001      V     C        {n['timecode']} {end} {n['timecode']} {end}  ")
        lines.append(f" |C:ResolveColor{color} |M:{marker_name(n)} |D:1")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- Resolve

def resolve_timeline(name):
    from vidkit.resolve import connect
    project = connect().GetProjectManager().GetCurrentProject()
    if project is None:
        sys.exit("DaVinci Resolve has no project open")
    tl = project.GetCurrentTimeline()
    if name:
        tl = next((project.GetTimelineByIndex(i + 1) for i in range(project.GetTimelineCount())
                   if project.GetTimelineByIndex(i + 1).GetName() == name), None)
        if tl is None:
            sys.exit(f"no timeline named {name!r} in project {project.GetName()!r}")
    if tl is None:
        sys.exit("no timeline is open in DaVinci Resolve")
    return project, tl, true_fps(tl.GetSetting("timelineFrameRate"))


def clear_resolve_markers(tl) -> int:
    removed = 0
    for frame, info in sorted((tl.GetMarkers() or {}).items()):
        if (info.get("customData") or "").startswith(MARKER_TAG):
            removed += bool(tl.DeleteMarkerAtFrame(int(frame)))
    return removed


def push_resolve_markers(tl, tl_fps, rows, color, log) -> int:
    """One marker per note at its timeline frame. Frames come from `timecode`
    (which carries the file's start offset) against the timeline's own start,
    so a timeline that starts at 01:00:00:00 lands correctly too."""
    start = tl.GetStartFrame()
    added = 0
    by_seconds = False
    for n in rows:
        frame = tc_parse(n["timecode"], tl_fps) - start
        if frame < 0 or by_seconds:
            # The render carried no start timecode (00:00:00:00) but the
            # timeline starts later (often 01:00:00:00): place by seconds
            # from the timeline start, which is what a whole-timeline render plays.
            if not by_seconds:
                log("  the notes' timecodes are before the timeline start; placing by seconds from its start")
                by_seconds = True
            frame = int(round(n["seconds"] * tl_fps))
        tag = MARKER_TAG + f"{n['seconds']:.3f}"
        ok = False
        for bump in range(12):                      # one marker per frame: nudge on collision
            if tl.AddMarker(frame + bump, color, marker_name(n), "", 1, tag):
                ok = True
                break
        added += ok
        if not ok:
            log(f"  could not add a marker at {n['timecode']}")
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="the reviewed video, or its <stem>.review folder")
    ap.add_argument("--color", default="Red", choices=sorted(RESOLVE_COLORS), help="marker colour (default Red)")
    ap.add_argument("--title", default=None, help="EDL TITLE line (default: the video's name)")
    ap.add_argument("--to-resolve", action="store_true",
                    help="also add the markers to the open Resolve project's current timeline")
    ap.add_argument("--timeline", default=None, metavar="NAME",
                    help="with --to-resolve: this timeline instead of the current one")
    ap.add_argument("--clear-resolve", action="store_true",
                    help="with --to-resolve: first delete the markers this script added earlier; "
                         "alone: only delete them, export nothing")
    args = ap.parse_args()
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731

    if args.clear_resolve and not args.to_resolve:
        _, tl, _ = resolve_timeline(args.timeline)
        log(f"removed {clear_resolve_markers(tl)} edit-review marker(s) from {tl.GetName()!r}")
        return 0

    review_dir = review_dir_for(args.target)
    rows, fps = review_rows(review_dir, log)
    jsonl = review_dir / "review.jsonl"
    with jsonl.open("w") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    edl = review_dir / "markers.edl"
    write_edl(edl, args.title or review_dir.stem, rows, fps, args.color)
    log(f"wrote {jsonl} ({len(rows)} notes) and {edl}")
    print(json.dumps({"review_jsonl": str(jsonl), "markers_edl": str(edl), "notes": len(rows)}))

    if args.to_resolve:
        project, tl, tl_fps = resolve_timeline(args.timeline)
        if abs(tl_fps - fps) > 0.01:
            log(f"warning: timeline {tl.GetName()!r} runs at {tl_fps:.3f} fps, the file at {fps} fps; "
                "markers are placed by timecode")
        if args.clear_resolve:
            log(f"removed {clear_resolve_markers(tl)} earlier edit-review marker(s)")
        added = push_resolve_markers(tl, tl_fps, rows, args.color, log)
        log(f"added {added}/{len(rows)} {args.color} marker(s) to {project.GetName()!r} > {tl.GetName()!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
