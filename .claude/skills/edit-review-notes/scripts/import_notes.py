#!/usr/bin/env python3
"""Turn review notes taken WITHOUT EditReview into the notes.json it writes,
so the rest of the edit-review-notes skill reads one format.

    import_notes.py DRAFT.mp4 --text notes.txt          # any player + a text file
    import_notes.py DRAFT.mp4 --resolve-markers [--timeline T] [--color Blue]
                                                        # markers dropped in DaVinci Resolve (M key)
    import_notes.py DRAFT.mp4 --edl markers.edl [--color Blue]
                                                        # Resolve markers exported to an EDL (free version)

Writes <draft-stem>.review/notes.json (schema edit-review/4, see
apps/edit-review/SPEC.md) and prints its path. An existing notes.json is
never overwritten: the imported notes are appended to its live list, skipping
any note with the same time and text (pass --replace to start fresh; the old
file is kept as notes.before-import-<stamp>.json).

Text file: one note per line, a time first, then the note:
    1:23 cut the long pause
    01:02:03 show the product here
    00:04:37:12 jump cut          (HH:MM:SS:FF timecode, at the draft's frame rate)
    83.5 too loud                 (plain seconds)
Separators after the time may be a space, " - ", ":" or a tab. Lines without
a leading time are added to the previous note (so a note can wrap).

Resolve markers (needs DaVinci Resolve Studio running, the project open):
reads the timeline's markers; the note is the marker's name plus its notes
field. Marker times are timeline-relative, which equals the draft's seconds
when the draft is a render of the whole timeline. --color keeps only markers
of that colour (e.g. the colour you review with). Markers this skill or
export_review.py added (customData starting "edit-review" / "note:") are skipped.

Marker EDL (File > Export > Timeline Markers to EDL... in Resolve): the
timecodes include the timeline's start. --edl-start gives it (default: the
whole hours below the first marker when the draft is shorter than that, so
a timeline starting at 01:00:00:00 just works).

Exit codes: 0 written, 1 bad input, 3 Resolve not answering.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))

SCHEMA = "edit-review/4"
TIME_RE = re.compile(
    r"^\s*[\[(]?(?P<t>\d+(?::\d{1,2}){1,3}(?:\.\d+)?|\d+(?:\.\d+)?)[\])]?\s*(?:[-–—:|]\s*|\t|\s)\s*(?P<text>.*)$")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(t: str, fps: float) -> float:
    """'83.5' / '1:23' / '1:02:03' / '00:04:37:12' (timecode at fps) -> seconds."""
    parts = t.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 4:
        h, m, s, f = (int(float(x)) for x in parts)
        base = max(1, round(fps))
        frames = ((h * 60 + m) * 60 + s) * base + f
        return frames / fps
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


def notes_from_text(path: Path, fps: float) -> list:
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = TIME_RE.match(line)
        if m and m.group("text").strip():
            out.append({"seconds": parse_time(m.group("t"), fps), "text": m.group("text").strip()})
        elif out:
            out[-1]["text"] += " " + line
        else:
            print(f"skipped (no time in front): {line}", file=sys.stderr)
    return out


def notes_from_resolve(timeline_name, color) -> list:
    from vidkit.resolve import connect, parse_fps
    project = connect().GetProjectManager().GetCurrentProject()
    if project is None:
        sys.exit("DaVinci Resolve has no project open")
    tl = project.GetCurrentTimeline()
    if timeline_name:
        tl = next((project.GetTimelineByIndex(i + 1) for i in range(project.GetTimelineCount())
                   if project.GetTimelineByIndex(i + 1).GetName() == timeline_name), None)
    if tl is None:
        sys.exit(f"no timeline {timeline_name!r}" if timeline_name else "no timeline is open")
    fps = float(parse_fps(tl.GetSetting("timelineFrameRate")))
    out = []
    for frame, info in sorted((tl.GetMarkers() or {}).items()):
        custom = info.get("customData") or ""
        if custom.startswith(("edit-review", "note:")):
            continue
        if color and (info.get("color") or "").lower() != color.lower():
            continue
        text = " ".join(x for x in ((info.get("name") or "").strip(), (info.get("note") or "").strip()) if x)
        out.append({"seconds": float(frame) / fps, "text": text or "(marker without text)"})
    return out


EDL_EVENT = re.compile(r"^\d+\s+\S+\s+\S+\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)")


def notes_from_edl(path: Path, fps: float, color, start_tc, duration) -> list:
    """Resolve's marker EDL: an event line (record in = 3rd timecode) followed by
    ' |C:ResolveColorBlue |M:name |D:1'."""
    events, cur = [], None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = EDL_EVENT.match(line.strip())
        if m:
            cur = {"tc": m.group(3), "text": "", "color": ""}
            events.append(cur)
        elif cur is not None and "|M:" in line:
            cm = re.search(r"\|C:ResolveColor(\w+)", line)
            mm = re.search(r"\|M:(.*?)(?:\s\|D:\d+)?\s*$", line)
            cur["color"] = cm.group(1) if cm else ""
            cur["text"] = (mm.group(1).strip() if mm else "")
    if not events:
        return []
    tcs = [e["tc"].replace(";", ":") for e in events]
    secs = [parse_time(t, fps) for t in tcs]
    offset = parse_time(start_tc, fps) if start_tc else 0.0
    hours = min(int(t.split(":")[0]) for t in tcs)
    if start_tc is None and hours >= 1 and duration and duration < 3600 * hours:
        # Timecode hours are counted in timecode frames, not wall-clock seconds.
        offset = parse_time(f"{hours:02d}:00:00:00", fps)
    out = []
    for e, t in zip(events, secs):
        if color and e["color"].lower() != color.lower():
            continue
        out.append({"seconds": max(0.0, t - offset), "text": e["text"] or "(marker without text)"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft", type=Path, help="the reviewed render")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", type=Path, metavar="FILE", help="a text file of timed notes")
    src.add_argument("--resolve-markers", action="store_true", help="read the markers of a Resolve timeline")
    src.add_argument("--edl", type=Path, metavar="FILE", help="a marker EDL exported from Resolve")
    ap.add_argument("--edl-start", metavar="TC", help="with --edl: the timeline's start timecode (e.g. 01:00:00:00)")
    ap.add_argument("--timeline", help="with --resolve-markers: this timeline (default: the current one)")
    ap.add_argument("--color", help="with --resolve-markers / --edl: only markers of this colour")
    ap.add_argument("--fps", type=float, help="frame rate for HH:MM:SS:FF times (default: the draft's)")
    ap.add_argument("--replace", action="store_true", help="start a fresh notes.json (the old one is kept aside)")
    args = ap.parse_args()

    draft = args.draft.expanduser().resolve()
    if not draft.is_file():
        sys.exit(f"no such file: {draft}")
    from vidkit import media
    info = media.probe(draft)
    fps = args.fps or info["fps_float"] or 24.0

    if args.text:
        if not args.text.is_file():
            sys.exit(f"no such file: {args.text}")
        new = notes_from_text(args.text, fps)
    elif args.edl:
        if not args.edl.is_file():
            sys.exit(f"no such file: {args.edl}")
        new = notes_from_edl(args.edl, fps, args.color, args.edl_start, info["duration"])
    else:
        new = notes_from_resolve(args.timeline, args.color)
    if not new:
        sys.exit("no notes found")

    review = draft.with_suffix(".review")
    review.mkdir(exist_ok=True)
    path = review / "notes.json"
    doc = None
    if path.exists():
        if args.replace:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(path, review / f"notes.before-import-{stamp}.json")
        else:
            doc = json.loads(path.read_text())
    if doc is None:
        doc = {"schema": SCHEMA, "video": draft.name, "frame_rate": round(fps, 3),
               "start_timecode": "00:00:00:00", "video_duration": info["duration"],
               "video_bytes": draft.stat().st_size, "notes": [], "archived": [], "versions": []}
    have = {(round(float(n["seconds"]), 2), n.get("text", "")) for n in doc.get("notes", [])}
    added = 0
    for n in new:
        key = (round(n["seconds"], 2), n["text"])
        if key in have:
            continue
        doc.setdefault("notes", []).append({"id": str(uuid.uuid4()).upper(), "seconds": round(n["seconds"], 3),
                                            "text": n["text"], "created_at": now_utc()})
        added += 1
    doc["notes"].sort(key=lambda n: float(n["seconds"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    print(path)
    print(f"added {added} note(s), {len(doc['notes'])} live in total", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
