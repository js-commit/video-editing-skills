#!/usr/bin/env python3
"""Step 1 of a triage: list every media file in a folder, read when and on what
device each was shot, and group them into units (one shooting session on one
device) that are routed together.

  inventory.py [FOLDER] [--work DIR] [--gap-hours 3]

FOLDER defaults to settings paths.inbox_dir. Nothing next to the media is
written: the inventory, sheets, briefs, plan and review page go in the work
folder (default: <cache>/footage-triage/<folder>-<time>), printed as work_dir.

Capture time comes from the file name (20250314_153012 style) first, then the
photo/video metadata (exiftool when installed, else ffprobe), then the file's
modified date (marked time_source "file-date": copies can reset it). Device
comes from the metadata make/model, else the file-name prefix (IMG_, DJI_ ...).
A unit is one device in one top-level sub-folder, split where more than
--gap-hours pass between files.

stdout: one JSON line {inventory, work_dir, units, files, bytes}. Exit 0 ok,
1 error, 4 a setting is unset.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from vidkit import settings  # noqa: E402


def device_from(meta: dict, probe: dict, name: str) -> str:
    make = (meta.get("Make") or meta.get("AndroidManufacturer") or "").strip()
    model = (meta.get("Model") or meta.get("AndroidModel") or "").strip()
    if not (make or model):
        tags = {k.lower(): v for k, v in (probe.get("format", {}).get("tags") or {}).items()}
        make = tags.get("com.apple.quicktime.make") or tags.get("make") or ""
        model = tags.get("com.apple.quicktime.model") or tags.get("model") or tags.get("com.android.model") or ""
    if model and make and model.lower().startswith(make.lower()):
        make = ""
    label = f"{make} {model}".strip()
    if label:
        return label
    m = re.match(r"([A-Za-z]+)[_\-]?\d", name)
    return f"{m.group(1).upper()}* files" if m else "unknown device"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--work")
    ap.add_argument("--gap-hours", type=float, default=None)
    a = ap.parse_args()

    if a.folder:
        folder = Path(a.folder).expanduser().resolve()
    else:
        try:
            folder = settings.get_path("paths.inbox_dir", required=True,
                                       hint="the folder where you copy footage off your cards and phone")
        except settings.SettingMissing as e:
            settings.exit_missing(e)
    if not folder.is_dir():
        sys.exit(f"not a folder (unplugged drive or unmounted share?): {folder}")
    gap_h = a.gap_hours if a.gap_hours is not None else float(settings.get("triage.session_gap_hours", default=3))
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = Path(a.work).expanduser().resolve() if a.work else settings.cache_dir("footage-triage") / f"{C.slugify(folder.name)}-{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    files, others = [], []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "_")))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if fn.startswith("."):
                continue
            k = C.kind_of(p)
            (files.append((p, k)) if k else others.append(p))
    meta_all = C.exiftool_batch([p for p, _ in files])
    sidecars, attached = {}, set()
    for d in {p.parent for p, _ in files}:
        names = [p.name for p, _ in files if p.parent == d]
        for m, side in C.sidecars_of(d, names).items():
            sidecars[str(d / m)] = side
            attached.update(str(d / s) for s in side)
    skipped = [{"path": str(p), "reason": "not a media file (left in place)"} for p in others if str(p) not in attached]

    recs = []
    for i, (p, k) in enumerate(files, 1):
        meta = meta_all.get(str(p), {})
        probe = C.ffprobe_json(p) if k in ("video", "audio") else {}
        streams = probe.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
        aud = next((s for s in streams if s.get("codec_type") == "audio"), None)
        dur = probe.get("format", {}).get("duration") or meta.get("Duration")
        t, src = C.time_from_name(p.name), "file-name"
        if t is None:
            t, src = (C.parse_exif_time(meta.get("DateTimeOriginal")) or C.parse_exif_time(meta.get("CreateDate"))
                      or C.parse_exif_time(meta.get("MediaCreateDate"))), "metadata"
        if t is None:
            t, src = C.parse_iso_utc((probe.get("format", {}).get("tags") or {}).get("creation_time")), "metadata"
        if t is None:
            t, src = _dt.datetime.fromtimestamp(p.stat().st_mtime), "file-date"
        fps = None
        if v and v.get("avg_frame_rate") not in (None, "0/0"):
            try:
                n, d_ = v["avg_frame_rate"].split("/")
                fps = round(int(n) / int(d_), 3) if int(d_) else None
            except (ValueError, ZeroDivisionError):
                fps = None
        recs.append({
            "id": f"f{i:04d}", "path": str(p), "rel": p.relative_to(folder).as_posix(), "kind": k,
            "bytes": p.stat().st_size, "duration": round(float(dur), 2) if dur else None,
            "width": (v or {}).get("width") or meta.get("ImageWidth"),
            "height": (v or {}).get("height") or meta.get("ImageHeight"),
            "fps": fps, "has_audio": aud is not None,
            "capture_time": t.isoformat(timespec="seconds"), "time_source": src,
            "device": device_from(meta, probe, p.name), "sidecars": sidecars.get(str(p), []),
            "top_folder": p.relative_to(folder).parts[0] if len(p.relative_to(folder).parts) > 1 else "",
        })
        if i % 50 == 0:
            C.log(f"  {i}/{len(files)} files read")

    groups = {}
    for r in recs:
        groups.setdefault((r["top_folder"], r["device"]), []).append(r)
    units = []
    for (top, dev), rs in sorted(groups.items()):
        rs.sort(key=lambda r: r["capture_time"])
        cur = []
        for r in rs:
            if cur and (_dt.datetime.fromisoformat(r["capture_time"]) -
                        _dt.datetime.fromisoformat(cur[-1]["capture_time"])).total_seconds() > gap_h * 3600:
                units.append((top, dev, cur))
                cur = []
            cur.append(r)
        if cur:
            units.append((top, dev, cur))
    units.sort(key=lambda u: u[2][0]["capture_time"])
    out_units = []
    for n, (top, dev, rs) in enumerate(units, 1):
        first, last = rs[0]["capture_time"], rs[-1]["capture_time"]
        out_units.append({
            "id": f"U{n:02d}", "name": "_".join(x for x in (first[:10], C.slugify(dev), C.slugify(top) if top else "") if x),
            "folder": top, "device": dev, "first": first, "last": last,
            "counts": {k: sum(1 for r in rs if r["kind"] == k) for k in ("video", "photo", "audio")},
            "bytes": sum(r["bytes"] for r in rs),
            "minutes": round(sum(r["duration"] or 0 for r in rs if r["kind"] != "photo") / 60, 1),
            "time_sources": sorted({r["time_source"] for r in rs}), "files": rs})

    projects = []
    pdir = settings.get_path("paths.projects_dir")
    if pdir and pdir.is_dir():
        for d in sorted((d for d in pdir.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))),
                        key=lambda d: -d.stat().st_mtime)[:40]:
            foot = d / settings.layout("footage")
            projects.append({"name": d.name, "modified": _dt.datetime.fromtimestamp(d.stat().st_mtime).date().isoformat(),
                             "footage_folders": sorted(x.name for x in foot.iterdir() if x.is_dir())[:20] if foot.is_dir() else []})
    roots = C.dest_roots()
    inv = {"input_dir": str(folder), "work_dir": str(work), "created": _dt.datetime.now().isoformat(timespec="seconds"),
           "gap_hours": gap_h, "exiftool": bool(meta_all),
           "destinations": {k: (str(v) if v else None) for k, v in roots.items()} | {"trash_dir": str(C.trash_dir(folder))},
           "projects": projects, "units": out_units, "skipped": skipped,
           "totals": {"files": len(recs), "bytes": sum(r["bytes"] for r in recs),
                      **{k: sum(1 for r in recs if r["kind"] == k) for k in ("video", "photo", "audio")}}}
    C.write_json(work / "inventory.json", inv)
    print(json.dumps({"inventory": str(work / "inventory.json"), "work_dir": str(work), "units": len(out_units),
                      "files": len(recs), "bytes": C.human_bytes(inv["totals"]["bytes"]),
                      "unset_destinations": [k for k, v in roots.items() if not v]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
