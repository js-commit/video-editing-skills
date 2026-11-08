#!/usr/bin/env python3
"""Harvest the b-roll a finished DaVinci Resolve edit used into the library.

Reads which stretches of which camera files the timeline used, cuts those
stretches (plus a little handle on each side) out of the camera originals into
<library>/clips/<project>/, makes a contact sheet per clip and adds them to the
catalog. The project and the originals are never modified.

Two ways to read the timeline (both read-only):
  PROJECT.drp            a Resolve project export (Project Manager > right-click >
                         Export Project). Works offline, any Resolve version, free
                         or Studio, Resolve need not be running.
  --resolve              the timeline open in DaVinci Resolve Studio right now,
                         through its scripting API. Uses the current project;
                         never loads, saves or changes anything.

Which clips count as b-roll: by default every clip on video track 2 and up
(V1 is the main talking-head / a-roll track), minus any file that also
appears on V1 (a picture-in-picture of the a-roll), stills, titles and
generators. Change it with --broll-tracks.

Usage:
  harvest_project.py PROJECT.drp [--timeline NAME] [--name SLUG] [--dry-run]
  harvest_project.py --resolve [--timeline NAME] [--name SLUG] [--dry-run]
Options:
  --broll-tracks 2-     tracks to harvest: "2-" (2 and up), "2,3", "1-" (all)
  --media-root DIR      relink media whose recorded path is gone by file name under DIR
  --only-under DIR      keep only media under DIR (repeatable)
  --exclude-under DIR   drop media under DIR, e.g. stock or screen recordings (repeatable)
  --handles 0.5         seconds added before and after each used stretch
  --min-length 1.0      drop stretches shorter than this (seconds of source)
  --copy                bit-exact stream copy instead of re-encoding (cuts snap to keyframes)

stdout: a JSON summary. Exit 0 ok, 1 error, 2 usage, 4 a setting is unset.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import drp  # noqa: E402


def parse_tracks(spec: str):
    spec = spec.strip()
    if spec.endswith("-"):
        lo = int(spec[:-1])
        return lambda t: t >= lo
    if "-" in spec:
        lo, hi = (int(x) for x in spec.split("-", 1))
        return lambda t: lo <= t <= hi
    wanted = {int(x) for x in spec.split(",") if x.strip()}
    return lambda t: t in wanted


def cuts_from_resolve(timeline_name: str | None):
    """Read the current project's timeline through the scripting API (Studio).
    Read-only: GetCurrentProject / GetTimelineByIndex / GetItemListInTrack only."""
    from vidkit import resolve as R
    res = R.connect()
    project = res.GetProjectManager().GetCurrentProject()
    if not project:
        sys.exit("No project is open in DaVinci Resolve. Open the finished project and re-run.")
    tl = project.GetCurrentTimeline()
    if timeline_name:
        tl = next((t for t in R.timelines(project) if t.GetName() == timeline_name), None)
        if tl is None:
            sys.exit(f"timeline {timeline_name!r} not found in the open project")
    if not tl:
        sys.exit("No timeline is open in DaVinci Resolve.")
    fps = float(tl.GetSetting("timelineFrameRate") or 24)
    t0 = tl.GetStartFrame()
    cuts = []
    for track in range(1, (tl.GetTrackCount("video") or 0) + 1):
        for it in tl.GetItemListInTrack("video", track) or []:
            mpi = it.GetMediaPoolItem()
            path = mpi.GetClipProperty("File Path") if mpi else ""
            if not path:
                continue
            try:
                declared = float(mpi.GetClipProperty("FPS") or 0) or fps
            except (TypeError, ValueError):
                declared = fps
            # GetLeftOffset counts timeline frames into the source (exact; the
            # source-start-frame getter can read back one frame off).
            src_in = (it.GetLeftOffset() or 0) / fps
            dur = (it.GetEnd() - it.GetStart()) / fps
            cuts.append({"track": track, "timeline_start": (it.GetStart() - t0) / fps,
                         "timeline_end": (it.GetEnd() - t0) / fps, "source_in": src_in,
                         "source_out": src_in + dur, "speed": 1.0, "declared_fps": declared,
                         "file_path": path, "name": it.GetName() or ""})
    return project.GetName(), tl.GetName(), cuts


def relink(path: str | None, media_root: Path | None, cache: dict):
    if not path:
        return None
    if os.path.exists(path):
        return path
    if media_root is None:
        return None
    name = os.path.basename(path.replace("\\", "/"))
    if name not in cache:
        cache[name] = next((str(p) for p in media_root.rglob(name)), None)
    return cache[name]


def under(path: str, dirs: list) -> bool:
    rp = os.path.realpath(path)
    return any(rp == os.path.realpath(d) or rp.startswith(os.path.realpath(d) + os.sep) for d in dirs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("drp", nargs="?", help="a Resolve project export (.drp)")
    ap.add_argument("--resolve", action="store_true", help="read the timeline open in Resolve Studio")
    ap.add_argument("--timeline", help="timeline name (default: the main cut / the open timeline)")
    ap.add_argument("--name", help="library folder name for this project (default: from the project)")
    ap.add_argument("--broll-tracks", default="2-")
    ap.add_argument("--media-root")
    ap.add_argument("--only-under", action="append", default=[])
    ap.add_argument("--exclude-under", action="append", default=[])
    ap.add_argument("--handles", type=float, default=0.5)
    ap.add_argument("--min-length", type=float, default=1.0)
    ap.add_argument("--copy", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="show what would be harvested, change nothing")
    a = ap.parse_args()
    if bool(a.drp) == bool(a.resolve):
        ap.error("give a .drp file or --resolve (one of them)")

    if a.resolve:
        proj_name, tl_name, cuts = cuts_from_resolve(a.timeline)
    else:
        if not a.drp.lower().endswith(".drp") or not os.path.isfile(a.drp):
            sys.exit(f"not a .drp file: {a.drp}")
        p = drp.Project(a.drp)
        tls = p.timelines()
        if a.timeline:
            tl = p.timeline_named(a.timeline)
            if tl is None:
                sys.exit(f"timeline {a.timeline!r} not in the export. Timelines: {[t.name for t in p.timelines(True)]}")
        elif not tls:
            sys.exit("the export holds no timelines with clips")
        else:
            # the main cut: the timeline that covers the most time with clips
            tl = max(tls, key=lambda t: sum(c["timeline_end"] - c["timeline_start"] for c in p.cuts(t)))
            if len(tls) > 1:
                C.log(f"picked timeline {tl.name!r} of {[t.name for t in tls]} (use --timeline to choose)")
        proj_name, tl_name, cuts = Path(a.drp).stem, tl.name, p.cuts(tl)

    slug = C.slugify(a.name or proj_name)
    media_root = Path(a.media_root).expanduser() if a.media_root else None
    cache, missing = {}, set()
    for c in cuts:
        real = relink(c["file_path"], media_root, cache)
        if not real:
            missing.add(c["file_path"] or c["name"])
        c["real_path"] = real
    cuts = [c for c in cuts if c["real_path"]]
    fps_cache = {}

    def real_fps(path):
        rp = next((c["real_path"] for c in cuts if c["file_path"] == path), None)
        if rp not in fps_cache:
            fps_cache[rp] = (C.safe_probe(rp) or {}).get("fps_float") if rp else None
        return fps_cache[rp]

    drp.conform(cuts, real_fps)

    is_broll = parse_tracks(a.broll_tracks)
    aroll_files = {c["real_path"] for c in cuts if c["track"] == 1} if not is_broll(1) else set()
    skipped = {"a-roll file": 0, "not a video": 0, "source filter": 0}
    by_file = {}
    for c in cuts:
        if not is_broll(c["track"]):
            continue
        rp = c["real_path"]
        if not C.is_video(rp):
            skipped["not a video"] += 1
            continue
        if rp in aroll_files:
            skipped["a-roll file"] += 1
            continue
        if (a.only_under and not under(rp, a.only_under)) or (a.exclude_under and under(rp, a.exclude_under)):
            skipped["source filter"] += 1
            continue
        by_file.setdefault((rp, round(c["speed"], 4)), []).append((c["source_in"], c["source_out"]))

    plan = []
    for (rp, speed), ranges in sorted(by_file.items()):
        dur = (C.safe_probe(rp) or {}).get("duration") or 0
        for s, e in C.merge_ranges(ranges, gap=2 * a.handles):
            s, e = max(0.0, s - a.handles), min(dur or e + a.handles, e + a.handles)
            if e - s >= a.min_length:
                plan.append({"source": rp, "in": round(s, 3), "out": round(e, 3), "speed": speed})

    summary = {"project": proj_name, "timeline": tl_name, "name": slug, "clips": len(plan),
               "source_seconds": round(sum(p["out"] - p["in"] for p in plan), 1),
               "skipped": skipped, "missing_media": sorted(missing)[:20], "missing_count": len(missing)}
    if a.dry_run:
        summary["dry_run"] = True
        summary["plan"] = plan
        print(json.dumps(summary, indent=2))
        return 0

    root = C.root_or_exit(create=True)
    out_dir = root / "clips" / slug
    with C.Lock(root, f"harvest_project {slug}"):
        data = C.load_catalog(root)
        added = 0
        for p in plan:
            # named by source file and in-point, so a re-run reuses exactly the same cut
            dst = out_dir / f"{slug}_{C.slugify(Path(p['source']).stem)}_{p['in']:.1f}s.mp4"
            cid = C.clip_id(p["source"], p["in"], p["out"])
            if not dst.exists() and not C.extract(p["source"], dst, p["in"], p["out"], p["speed"], a.copy):
                continue
            info = C.safe_probe(dst) or {}
            rec = C.new_record(root, path=dst, start=0.0, end=info.get("duration") or (p["out"] - p["in"]) / p["speed"],
                               in_place=False, source_project=slug, source_file=p["source"],
                               source_in=p["in"], source_out=p["out"], speed=p["speed"],
                               origin="resolve-live" if a.resolve else "resolve-drp", info=info)
            sheet = C.catalog_dir(root) / "sheets" / f"{cid}.jpg"
            if C.make_sheet(dst, sheet, 0.0, rec["end"]):
                rec["sheet"] = C.to_stored(root, sheet)
            added += C.upsert(data, rec)
            C.log(f"  {dst.name}  {p['in']:.1f}-{p['out']:.1f}s of {Path(p['source']).name}"
                  + (f"  (slow motion {p['speed']:.2f}x)" if p["speed"] != 1.0 else ""))
        C.save_catalog(root, data)
    summary.update({"added": added, "folder": str(out_dir),
                    "next": "describe the new clips: describe.py briefs --only-missing"})
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
