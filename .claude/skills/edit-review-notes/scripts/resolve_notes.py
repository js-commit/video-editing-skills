#!/usr/bin/env python3
"""DaVinci Resolve helpers for a notes round (needs DaVinci Resolve Studio
running with the project open and external scripting enabled).

    resolve_notes.py backup       --timeline T [--project P]
    resolve_notes.py fingerprint  --timeline T -o aroll.json [--tracks 1]
    resolve_notes.py verify       --timeline T --against aroll.json [--tracks 1]
    resolve_notes.py ripple-delete --timeline T --start S --end E [--tracks 1] [--apply]
    resolve_notes.py remove-layer --timeline T --track N --at S [--apply]
    resolve_notes.py markers      --timeline T --file markers.json
    resolve_notes.py clear-markers --timeline T [--prefix "NOTE "]

backup        duplicates the timeline inside the project as "<T> backup <date-time>"
              (a restore point; scripts here never edit a timeline with "backup"
              in its name) and leaves T current.
fingerprint   writes the a-roll's item list (video + audio tracks named by
              --tracks, default 1): name, record frames, source frames, plus the
              timeline's end frame. Take it before the first change.
verify        compares the live a-roll with a fingerprint: exits 0 when the
              items are identical (additive notes must not change them), 3 and a
              list of differences otherwise.
ripple-delete removes the a-roll items lying wholly inside [S, E) seconds from
              the timeline start (video and audio on --tracks) with a ripple,
              which in Resolve moves every later item on EVERY track and the
              markers, shortens an upper-track item that straddles the range and
              drops one inside it. Dry run unless --apply. Refuses when an
              item straddles S or E: blade it first (Resolve: playhead on the
              edge, select the clip, Cmd+B / Ctrl+B) or snap S / E to item edges.
remove-layer  removes the item on video track N (above the a-roll) under S
              seconds, without a ripple: the first step of a "replace this
              shot" or "move this shot" note. Dry run unless --apply.
markers       adds markers from a JSON list
              [{"seconds": 12.3, "name": "NOTE 3: ...", "note": "...", "color": "Blue"}]
              (seconds from the timeline start), tagged so clear-markers finds them.
clear-markers removes the markers this script added whose name starts with --prefix.

Prints JSON on stdout. Exit codes: 0 ok, 1 bad input, 3 verify found
differences / Resolve not answering.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))

TAG = "note:"


def log(*a):
    print(*a, file=sys.stderr)


def open_timeline(project_name, timeline_name, write=False):
    from vidkit.resolve import connect, get_project, timelines
    pm = connect().GetProjectManager()
    project = get_project(pm, project_name) if project_name else pm.GetCurrentProject()
    if project is None:
        sys.exit("DaVinci Resolve has no project open")
    tl = next((t for t in timelines(project) if t.GetName() == timeline_name), None)
    if tl is None:
        sys.exit(f"no timeline {timeline_name!r} in {project.GetName()!r}")
    if write:
        from vidkit.resolve import check_never_touch
        check_never_touch({}, timeline_name)   # backups and settings editor.never_touch_timelines
    if project.GetCurrentTimeline() is None or project.GetCurrentTimeline().GetName() != timeline_name:
        project.SetCurrentTimeline(tl)
    return project, tl


def fps_of(tl) -> float:
    from vidkit.resolve import parse_fps
    return float(parse_fps(tl.GetSetting("timelineFrameRate")))


def _src(item, name, default=None):
    fn = getattr(item, name, None)
    try:
        v = fn() if fn else None
    except Exception:
        v = None
    return default if v is None else v


def aroll_items(tl, tracks):
    """[(kind, track, item)] for the a-roll tracks, in record order."""
    out = []
    for kind in ("video", "audio"):
        for t in tracks:
            if t > int(tl.GetTrackCount(kind) or 0):
                continue
            for it in tl.GetItemListInTrack(kind, t) or []:
                out.append((kind, t, it))
    return out


def fingerprint(tl, tracks) -> dict:
    rows = []
    for kind, t, it in aroll_items(tl, tracks):
        rows.append({"track": f"{kind[0].upper()}{t}", "name": it.GetName() or "",
                     "start": int(it.GetStart()), "end": int(it.GetEnd()),
                     "src_start": _src(it, "GetSourceStartFrame", _src(it, "GetLeftOffset")),
                     "src_end": _src(it, "GetSourceEndFrame")})
    return {"timeline": tl.GetName(), "frame_rate": fps_of(tl), "start_frame": int(tl.GetStartFrame()),
            "end_frame": int(tl.GetEndFrame()), "tracks": tracks, "items": rows,
            "taken_at": datetime.now().isoformat(timespec="seconds")}


def diff(old: dict, new: dict) -> list:
    out = []
    if old["end_frame"] != new["end_frame"]:
        out.append(f"end frame {old['end_frame']} -> {new['end_frame']}")
    key = lambda r: (r["track"], r["start"])  # noqa: E731
    a, b = {key(r): r for r in old["items"]}, {key(r): r for r in new["items"]}
    for k in sorted(set(a) | set(b)):
        if k not in b:
            out.append(f"{k[0]} @{k[1]}: {a[k]['name']!r} is gone")
        elif k not in a:
            out.append(f"{k[0]} @{k[1]}: new item {b[k]['name']!r}")
        elif a[k] != b[k]:
            changed = [f for f in ("name", "end", "src_start", "src_end") if a[k].get(f) != b[k].get(f)]
            out.append(f"{k[0]} @{k[1]}: {a[k]['name']!r} changed {', '.join(changed)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["backup", "fingerprint", "verify", "ripple-delete", "remove-layer",
                                        "markers", "clear-markers"])
    ap.add_argument("--project", help="project name (default: the open one)")
    ap.add_argument("--timeline", required=True, help="timeline name")
    ap.add_argument("--tracks", default="1", help="a-roll track numbers, comma-separated (default 1)")
    ap.add_argument("-o", "--out", type=Path, help="fingerprint: where to write it")
    ap.add_argument("--against", type=Path, help="verify: the fingerprint to compare with")
    ap.add_argument("--start", type=float, help="ripple-delete: seconds from the timeline start")
    ap.add_argument("--end", type=float, help="ripple-delete: seconds from the timeline start (exclusive)")
    ap.add_argument("--apply", action="store_true", help="ripple-delete / remove-layer: really delete (default: dry run)")
    ap.add_argument("--track", type=int, help="remove-layer: the video track number")
    ap.add_argument("--at", type=float, help="remove-layer: seconds from the timeline start")
    ap.add_argument("--file", type=Path, help="markers: the JSON list of markers")
    ap.add_argument("--prefix", default="NOTE ", help='clear-markers: name prefix (default "NOTE ")')
    args = ap.parse_args()
    tracks = [int(x) for x in args.tracks.split(",") if x.strip()]
    write = args.command in ("ripple-delete", "remove-layer", "markers", "clear-markers")

    if args.command == "verify" and not args.against:
        sys.exit("verify needs --against <fingerprint.json>")
    if args.command == "fingerprint" and not args.out:
        sys.exit("fingerprint needs -o <file>")
    if args.command == "ripple-delete" and (args.start is None or args.end is None or args.end <= args.start):
        sys.exit("ripple-delete needs --start and a larger --end (seconds from the timeline start)")
    if args.command == "remove-layer" and (args.track is None or args.at is None):
        sys.exit("remove-layer needs --track N and --at SECONDS")
    if args.command == "remove-layer" and args.track in tracks:
        sys.exit(f"V{args.track} is an a-roll track (--tracks): use ripple-delete for the a-roll")
    if args.command == "markers" and not args.file:
        sys.exit("markers needs --file <markers.json>")

    project, tl = open_timeline(args.project, args.timeline, write=write)

    if args.command == "backup":
        from vidkit.resolve import duplicate_timeline
        name = f"{tl.GetName()} backup {datetime.now().strftime('%Y-%m-%d %H%M')}"
        if duplicate_timeline(project, tl, name) is None:
            sys.exit(f"Resolve refused to duplicate {tl.GetName()!r}")
        print(json.dumps({"backup": name}))
        return 0

    if args.command == "fingerprint":
        fp = fingerprint(tl, tracks)
        args.out.write_text(json.dumps(fp, indent=2) + "\n")
        print(json.dumps({"fingerprint": str(args.out), "items": len(fp["items"]), "end_frame": fp["end_frame"]}))
        return 0

    if args.command == "verify":
        old = json.loads(args.against.read_text())
        problems = diff(old, fingerprint(tl, old.get("tracks", tracks)))
        print(json.dumps({"identical": not problems, "differences": problems}, indent=2))
        return 3 if problems else 0

    fps = fps_of(tl)
    t0 = int(tl.GetStartFrame())

    if args.command == "ripple-delete":
        a, b = t0 + round(args.start * fps), t0 + round(args.end * fps)
        inside, straddle = [], []
        for kind, t, it in aroll_items(tl, tracks):
            s, e = int(it.GetStart()), int(it.GetEnd())
            if s >= a and e <= b:
                inside.append((kind, t, it))
            elif s < b and e > a:
                straddle.append(f"{kind[0].upper()}{t} {it.GetName()!r} {(s - t0) / fps:.3f}-{(e - t0) / fps:.3f} s")
        report = {"range_s": [args.start, args.end], "frames": b - a,
                  "delete": [f"{k[0].upper()}{t} {it.GetName()!r} {(int(it.GetStart()) - t0) / fps:.3f}-"
                             f"{(int(it.GetEnd()) - t0) / fps:.3f} s" for k, t, it in inside],
                  "straddling": straddle, "applied": False}
        if straddle:
            report["error"] = "items straddle the range edges: blade them or move S/E onto item edges"
            print(json.dumps(report, indent=2))
            return 1
        if not inside:
            report["error"] = "no a-roll item lies wholly inside the range"
            print(json.dumps(report, indent=2))
            return 1
        if args.apply:
            from vidkit.resolve import delete_clips_checked
            before = int(tl.GetEndFrame())
            if not delete_clips_checked(tl, [it for _, _, it in inside], ripple=True):
                sys.exit("Resolve refused the delete (is the Edit page reachable?)")
            report.update(applied=True, end_frame_before=before, end_frame_after=int(tl.GetEndFrame()))
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "remove-layer":
        f = t0 + round(args.at * fps)
        hit = next((it for it in tl.GetItemListInTrack("video", args.track) or []
                    if int(it.GetStart()) <= f < int(it.GetEnd())), None)
        if hit is None:
            print(json.dumps({"error": f"nothing on V{args.track} at {args.at:.3f} s"}))
            return 1
        report = {"remove": f"V{args.track} {hit.GetName()!r} {(int(hit.GetStart()) - t0) / fps:.3f}-"
                            f"{(int(hit.GetEnd()) - t0) / fps:.3f} s", "applied": False}
        if args.apply:
            from vidkit.resolve import delete_clips_checked
            if not delete_clips_checked(tl, [hit], ripple=False):
                sys.exit("Resolve refused the delete (is the Edit page reachable?)")
            report["applied"] = True
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "markers":
        rows = json.loads(args.file.read_text())
        added, failed = 0, []
        for r in rows:
            frame = round(float(r["seconds"]) * fps)
            ok = any(tl.AddMarker(frame + bump, r.get("color", "Blue"), str(r.get("name", "NOTE"))[:80],
                                  str(r.get("note", "")), 1, TAG + str(r.get("name", ""))[:40])
                     for bump in range(12))       # one marker per frame: nudge on collision
            added += bool(ok)
            if not ok:
                failed.append(r.get("name"))
        print(json.dumps({"added": added, "failed": failed}))
        return 0

    removed = 0
    for frame, info in sorted((tl.GetMarkers() or {}).items()):
        if (info.get("customData") or "").startswith(TAG) and (info.get("name") or "").startswith(args.prefix):
            removed += bool(tl.DeleteMarkerAtFrame(int(frame)))
    print(json.dumps({"removed": removed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
