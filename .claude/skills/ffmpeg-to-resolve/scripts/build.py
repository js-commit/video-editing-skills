#!/usr/bin/env python3
"""Job -> a DaVinci Resolve timeline. Executes plan.py's job.json and reads everything back.

    build.py <job folder>/job.json [--replace] [--keep-going]

Makes (or loads) the job's project, files the media in bins (used clips, and an "unused" bin beside them), creates ONE
new timeline and fills it: V1 keeps, A1 their sound, V2 bricks, V3+ overlays, the fade-out clip, the NEED BROLL markers.
Then it saves, re-reads every item from the saved timeline and writes <job folder>/build_report.json with one row per
job item (ok / wrong, and what Resolve holds). Exit 1 if any row is wrong.

Needs DaVinci Resolve Studio 21.2 or later, running (the sub-frame audio setters arrived in 21.1.2).

Never touches anything it did not make:
  * the timeline name must end in "(ffmpeg)" and must not exist - or pass --replace, which deletes and rebuilds only
    that timeline. No other timeline, bin or clip in the project is changed or removed.
  * a project that already holds timelines is exported to <job folder>/snapshots/ first; if that export fails, it
    stops (API edits are not in Resolve's undo: the .drp is the way back).
  * the recipe and the source media are only read.

Measured on Resolve 21.2:
  * AppendToTimeline rounds an audio item's source start to a whole frame. A separately recorded mic's offset is not
    on the frame grid, so the item goes in one frame short, is slid by the fraction (SetPosition, sub-frame), and its
    edges are pulled back onto the keep's frames (SetLeftOffset / SetRightOffset, sub-frame). Read back to 1e-3 frame.
  * a clip at another rate than the timeline's gets a source range in ITS frames; the item's length is then read back
    and its tail trimmed or re-appended until it is the brick's frames.
  * ImportMedia with a list drops a file now and then; each one imports alone, so the dropped ones are retried singly.
  * SetLUT only takes a LUT that lives in Resolve's own LUT folder.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import time
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import settings  # noqa: E402
from vidkit.resolve import connect, launch_hint, log, pool_by_path, timelines  # noqa: E402

TAG = "(ffmpeg)"


def lut_dir():
    """Resolve's own LUT folder: SetLUT refuses a path anywhere else. (macOS measured; Windows and Linux are the
    documented locations.)"""
    system = platform.system()
    if system == "Darwin":
        return "/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT"
    if system == "Windows":
        return os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Blackmagic Design", "DaVinci Resolve", "Support", "LUT")
    return next((d for d in ("/opt/resolve/LUT", "/home/resolve/LUT") if os.path.isdir(d)), "/opt/resolve/LUT")
SUB = 1e-3          # frames: how close a sub-frame audio edge must read back


def bin_at(mp, root, parts):
    f = root
    for name in parts:
        nxt = next((s for s in f.GetSubFolderList() or [] if s.GetName() == name), None)
        f = nxt or mp.AddSubFolder(f, name)
        if f is None:
            sys.exit(f"could not create bin {'/'.join(parts)}")
    return f


def file_media(mp, root, job):
    """Every job media file in its bin; clips already in the pool are moved, not re-imported. -> {path: MediaPoolItem}"""
    by = pool_by_path(root)
    groups = {}
    for m in job["media"]:
        groups.setdefault(tuple(m["bin"]), []).append(m)
    for parts, ms in groups.items():
        folder = bin_at(mp, root, parts)
        need = [m["file"] for m in ms if m["file"] not in by]
        missing = [f for f in need if not os.path.exists(f)]
        if missing:
            sys.exit(f"missing media (bake.py first?): {missing[:3]}")
        if need:
            mp.SetCurrentFolder(folder)
            for i in range(0, len(need), 25):
                for c in mp.ImportMedia(need[i:i + 25]) or []:
                    p = c.GetClipProperty("File Path")
                    if p:
                        by[p] = c
            # a batch import drops files now and then (measured: 2 of 86, both on a network share; each imported
            # alone in 0.3 s): once more, one at a time
            for f in [f for f in need if f not in by]:
                for _ in range(2):
                    got = mp.ImportMedia([f]) or []
                    if got:
                        by[f] = got[0]
                        log(f"imported on a retry: {f}")
                        break
                    time.sleep(1)
        have = {c.GetClipProperty("File Path") for c in folder.GetClipList() or []}
        move = [by[m["file"]] for m in ms if m["file"] in by and m["file"] not in have]
        if move:
            mp.MoveClips(move, folder)
    mp.SetCurrentFolder(root)
    dropped = [m["file"] for m in job["media"] if m["file"] not in by]
    used_dropped = [f for f in dropped if any(m["file"] == f and m["used"] for m in job["media"])]
    if used_dropped:
        sys.exit(f"ImportMedia dropped {len(used_dropped)} used file(s): {used_dropped[:3]}")
    for m in job["media"]:
        c = by.get(m["file"])
        if c is not None and m.get("conform_fps") and str(c.GetClipProperty("FPS")) != m["conform_fps"]:
            if not c.SetClipProperty("FPS", m["conform_fps"]):
                sys.exit(f"could not conform {m['file']} to {m['conform_fps']} fps")
    return by, dropped


def item_at(tl, kind, track, start):
    for it in tl.GetItemListInTrack(kind, track) or []:
        if abs(it.GetStart(True) - start) < 0.5:
            return it
    return None


def append(mp, infos):
    out = mp.AppendToTimeline(infos) or []
    return [o for o in out if o]


def place_video(mp, tl, by, it, base, fps):
    """One video item whose clip may run at another rate: append, read the length back, fix the tail."""
    mpi = by[it["file"]]
    n, rec = it["n"], base + it["rec_f"]
    step = 1.0 if it.get("conformed") else float(it.get("src_step", 1.0))
    if it.get("speed"):
        step = step / (it["speed"] / 100.0)         # the range is appended at real time, then SetSpeed shortens it
    want = n * step
    for extra in (0, 1, -1, 2):
        end = it["src_f"] + max(math.ceil(want - 1e-6) + extra, 1)
        got = append(mp, [{"mediaPoolItem": mpi, "startFrame": it["src_f"], "endFrame": end, "mediaType": 1,
                           "trackIndex": it["track"][1], "recordFrame": rec}])
        item = item_at(tl, "video", it["track"][1], rec)
        if item is None:
            continue
        if it.get("speed"):
            if not item.SetSpeed({"Percentage": it["speed"], "RippleTimeline": False}):
                return item, f"SetSpeed {it['speed']} refused"
        d = item.GetDuration()
        if d == n:
            return item, None
        if d > n and item.SetRightOffset(item.GetRightOffset() + (d - n)) and item.GetDuration() == n:
            return item, None
        if item.GetDuration() == n:
            return item, None
        tl.DeleteClips([item], False)
    return None, f"could not land {n} frames"


def place_audio(mp, tl, by, it, base):
    """One audio-only item. A fractional source start is appended a frame short, slid by the fraction, then both edges
    are pulled back onto the keep's frames."""
    mpi = by[it["file"]]
    n, rec, src = it["n"], base + it["rec_f"], it["src_f"]
    tr = it["track"][1]
    if abs(src - round(src)) < 1e-6:
        src = round(src)
        append(mp, [{"mediaPoolItem": mpi, "startFrame": src, "endFrame": src + n, "mediaType": 2, "trackIndex": tr, "recordFrame": rec}])
        item = item_at(tl, "audio", tr, rec)
        return item, None if item is not None else "append dropped"
    c = math.ceil(src)
    short = n - 1 if n > 1 else n
    append(mp, [{"mediaPoolItem": mpi, "startFrame": c, "endFrame": c + short, "mediaType": 2, "trackIndex": tr, "recordFrame": rec}])
    item = item_at(tl, "audio", tr, rec)
    if item is None:
        return None, "append dropped"
    ok = item.SetPosition({"startFrame": rec + (c - src)}, False, True)
    ok = item.SetLeftOffset(src, True, False) and ok
    ro = item.GetRightOffset(True) - (rec + n - item.GetEnd(True))
    ok = item.SetRightOffset(ro, True, False) and ok
    return item, None if ok else ("a sub-frame setter was refused: needs Resolve 21.2 or later, and Preferences > User > Editing > "
                                  "'Align audio edits to frame boundaries' off")


def tc_frames(tc, fps):
    """A clip's Start TC as a frame count at its own rate (a camera file starts at the time of day, not at zero)."""
    drop = ";" in tc
    h, m, sec, f = (int(x) for x in tc.replace(";", ":").split(":"))
    base = round(fps)
    n = ((h * 60 + m) * 60 + sec) * base + f
    if drop:
        d = round(base / 15)                       # 2 at 29.97, 4 at 59.94
        mins = h * 60 + m
        n -= d * (mins - mins // 10)
    return n


def source_frame(item, mpi, tl_fps):
    """The clip frame (0 = its first) a video item starts on. At the timeline's rate GetLeftOffset is exact. At another
    rate GetLeftOffset counts timeline frames and GetSourceStartFrame reads one low on some items (measured: 2761 for
    2762), so it is the source TIME x the clip's rate, less the clip's start timecode, which that time includes."""
    cf = float(mpi.GetClipProperty("FPS"))
    if abs(cf - tl_fps) < 0.01:
        return item.GetLeftOffset()
    exact = next((n / 1001 for n in (24000, 30000, 48000, 60000, 120000) if abs(cf - n / 1001) < 0.01), cf)   # "59.94" is 60000/1001:
    # at a time-of-day timecode the rounded rate is two frames out
    return round(item.GetSourceStartTime() * exact - tc_frames(mpi.GetClipProperty("Start TC") or "00:00:00:00", cf), 3)


def readback(tl, job, base):
    """One row per job item from the timeline as it is now."""
    rows, bad = [], 0
    by_track = {}
    tl_fps = float(tl.GetSetting("timelineFrameRate"))
    for it in job["items"]:
        kind, tr = it["track"]
        if (kind, tr) not in by_track:
            by_track[(kind, tr)] = tl.GetItemListInTrack(kind, tr) or []
        rec = base + it["rec_f"]
        item = next((x for x in by_track[(kind, tr)] if abs(x.GetStart(True) - rec) < 0.5), None)
        row = {"id": it["id"], "track": f"{kind[0].upper()}{tr}", "rec_f": it["rec_f"], "n": it["n"], "ok": True, "why": []}
        if item is None:
            row.update(ok=False, why=["missing"])
        else:
            sub = it["media"] == "audio"
            start, dur, left = item.GetStart(sub), item.GetDuration(sub), item.GetLeftOffset(sub)
            row.update(got_start=round(start - base, 4), got_n=round(dur, 4), got_src=round(left, 4), clip=item.GetName())
            if abs(start - rec) > SUB:
                row["why"].append(f"starts at {start - base}")
            if abs(dur - it["n"]) > SUB:
                row["why"].append(f"{dur} frames")
            mpi = item.GetMediaPoolItem()
            path = mpi.GetClipProperty("File Path") if mpi else None
            if not sub and mpi:
                left = source_frame(item, mpi, tl_fps)
                row["got_src"] = left
            if not it.get("speed") and abs(left - it["src_f"]) > (SUB if sub else 0.01):
                row["why"].append(f"source frame {left}, wanted {it['src_f']}")
            if it.get("lut") and not (item.GetNodeGraph() and item.GetNodeGraph().GetLUT(1)):
                row["why"].append("no LUT on node 1")
            if path != it["file"]:
                row["why"].append(f"plays {path}")
            props = item.GetProperties() or {}
            for k, v in it.get("props", {}).items():
                if abs(float(props.get(k, 1e9)) - v) > 0.01:
                    row["why"].append(f"{k} {props.get(k)}, wanted {v}")
            fades = item.GetFades() or {}
            for k, v in (it.get("fades") or {}).items():
                if fades.get(k) != v:
                    row["why"].append(f"{k} {fades.get(k)}, wanted {v}")
            row["ok"] = not row["why"]
        bad += not row["ok"]
        rows.append(row)
    stray = []
    wanted = {(it["track"][0], it["track"][1], it["rec_f"]) for it in job["items"]}
    for kind, n_tr in (("video", tl.GetTrackCount("video")), ("audio", tl.GetTrackCount("audio"))):
        for tr in range(1, n_tr + 1):
            for x in tl.GetItemListInTrack(kind, tr) or []:
                if (kind, tr, round(x.GetStart(True) - base)) not in wanted:
                    stray.append(f"{kind[0].upper()}{tr} @ {x.GetStart(True) - base}: {x.GetName()}")
    return rows, bad, stray


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job")
    ap.add_argument("--replace", action="store_true", help="delete and rebuild the job's own timeline if it exists")
    ap.add_argument("--keep-going", action="store_true", help="on an item that will not land, record it and go on")
    a = ap.parse_args()
    jp = Path(a.job).resolve()
    with open(jp, encoding="utf-8") as f:
        job = json.load(f)
    if settings.get("editor.nle") in ("resolve-free", "none"):
        sys.exit("building a timeline needs DaVinci Resolve Studio (external scripting): settings editor.nle says "
                 f"{settings.get('editor.nle')!r}")
    name = job["timeline"]
    if not name.endswith(TAG):
        sys.exit(f"refusing: the timeline name {name!r} does not end in {TAG!r}")
    fps = Fraction(job["fps"])
    t0 = time.time()
    resolve = connect()
    pm = resolve.GetProjectManager()

    # ---- project
    cur = pm.GetCurrentProject()
    created = False
    if cur and cur.GetName() == job["project"]:
        proj = cur
    elif job["project"] in (pm.GetProjectListInCurrentFolder() or []):
        proj = pm.LoadProject(job["project"])
    else:
        if cur and cur.GetName() != "Untitled Project":
            pm.SaveProject()
        proj = pm.CreateProject(job["project"])
        created = True
    if proj is None:
        sys.exit(f"could not open or create project {job['project']!r} (a project of that name in another folder? a locked screen?). "
                 f"If Resolve is not running: {launch_hint()}")
    if created or not (proj.GetTimelineCount() or 0):
        for k, v in (("timelineFrameRate", job["fps_name"]), ("timelineResolutionWidth", str(job["width"])),
                     ("timelineResolutionHeight", str(job["height"]))):
            if not proj.SetSetting(k, v) and str(proj.GetSetting(k)) != v:
                sys.exit(f"project setting {k}={v} refused")
    if abs(float(proj.GetSetting("timelineFrameRate")) - float(fps)) > 0.01:
        sys.exit(f"project {job['project']!r} runs at {proj.GetSetting('timelineFrameRate')} fps, the recipe at {job['fps_name']}: "
                 "convert into a new project (--project on plan.py)")
    existing = [t for t in timelines(proj) if t.GetName() == name]
    if existing and not a.replace:
        sys.exit(f"timeline {name!r} already exists - pass --replace to rebuild it (only that timeline is deleted)")
    if (proj.GetTimelineCount() or 0) and not created:
        snap = jp.parent / "snapshots" / f"{job['project']}-{time.strftime('%Y%m%d-%H%M%S')}.drp"
        snap.parent.mkdir(parents=True, exist_ok=True)
        pm.SaveProject()
        if not pm.ExportProject(job["project"], str(snap), False) or not snap.exists() or snap.stat().st_size == 0:
            sys.exit(f"snapshot export failed ({snap}) - nothing was changed; relaunch Resolve and re-run")
        log(f"snapshot {snap}")
    mp = proj.GetMediaPool()
    root = mp.GetRootFolder()
    if existing:
        mp.DeleteTimelines(existing)

    # ---- media + timeline
    by, dropped = file_media(mp, root, job)
    log(f"media filed: {len(by)} clips in the pool ({time.time() - t0:.0f}s)")
    mp.SetCurrentFolder(root)
    # graphics/baked is this script's own bin: clips an earlier build baked and this job no longer lists go
    ours = {m["file"] for m in job["media"]}
    baked_bin = bin_at(mp, root, ["graphics", "baked"]) if job["bakes"] else None
    stale = [c for c in (baked_bin.GetClipList() or []) if c.GetClipProperty("File Path") not in ours] if baked_bin else []
    if stale:
        mp.DeleteClips(stale)
    tl = mp.CreateEmptyTimeline(name)
    if tl is None:
        sys.exit(f"could not create timeline {name!r}")
    proj.SetCurrentTimeline(tl)
    tl.SetStartTimecode("00:00:00:00")
    base = tl.GetStartFrame()
    if (tl.GetSetting("timelineResolutionWidth"), tl.GetSetting("timelineResolutionHeight")) != (str(job["width"]), str(job["height"])):
        for k, v in (("useCustomSettings", "1"), ("timelineResolutionWidth", str(job["width"])), ("timelineResolutionHeight", str(job["height"]))):
            tl.SetSetting(k, v)
    for kind in ("video", "audio"):
        while tl.GetTrackCount(kind) < len(job["tracks"][kind]):
            tl.AddTrack(kind, "stereo") if kind == "audio" else tl.AddTrack(kind)
        for i, nm in enumerate(job["tracks"][kind]):
            tl.SetTrackName(kind, i + 1, nm)
    if resolve.GetCurrentPage() != "edit":
        resolve.OpenPage("edit")

    problems = []
    handle = {}
    luts = {}       # job LUT file -> its name inside Resolve's LUT folder (an absolute path elsewhere is refused)
    if job["luts"]:
        import shutil
        sub = os.path.join("ffmpeg-to-resolve", "".join(c if c.isalnum() or c in "-_" else "-" for c in job["project"]))
        try:
            os.makedirs(os.path.join(lut_dir(), sub), exist_ok=True)
        except OSError as e:
            sys.exit(f"cannot write to Resolve's LUT folder ({lut_dir()}): {e}. Grades need it: SetLUT refuses a LUT elsewhere")
        for l in job["luts"]:
            shutil.copy(l["file"], os.path.join(lut_dir(), sub))
            luts[l["file"]] = os.path.join(sub, os.path.basename(l["file"]))
        proj.RefreshLUTList()

    def problem(it, msg):
        problems.append({"id": it["id"], "what": msg})
        log(f"PROBLEM {it['id']}: {msg}")
        if not a.keep_going:
            with open(jp.parent / "build_report.json", "w", encoding="utf-8") as fh:
                json.dump({"ok": False, "problems": problems}, fh, indent=1)
            sys.exit(1)

    # V1 keeps in one call (same rate as the timeline, whole frames)
    v1 = [it for it in job["items"] if it["role"] == "aroll"]
    append(mp, [{"mediaPoolItem": by[it["file"]], "startFrame": it["src_f"], "endFrame": it["src_f"] + it["n"], "mediaType": 1,
                 "trackIndex": 1, "recordFrame": base + it["rec_f"]} for it in v1])
    on_v1 = {round(x.GetStart()): x for x in tl.GetItemListInTrack("video", 1) or []}
    for it in v1:
        x = on_v1.get(base + it["rec_f"])
        if x is None or x.GetDuration() != it["n"]:      # a ghost or a dropped item right after launch: once more, alone
            if x is not None:
                tl.DeleteClips([x], False)
            x, err = place_video(mp, tl, by, it, base, fps)
            if x is None:
                problem(it, err); continue
        handle[it["id"]] = x
    for it in job["items"]:
        if it["id"] in handle:
            continue
        if it["media"] == "audio":
            x, err = place_audio(mp, tl, by, it, base)
        else:
            x, err = place_video(mp, tl, by, it, base, fps)
        if x is None or err:
            problem(it, err or "did not land")
        if x is not None:
            handle[it["id"]] = x

    log(f"items placed: {len(handle)} of {len(job['items'])} ({time.time() - t0:.0f}s)")
    # properties, fades, grades, links
    for it in job["items"]:
        x = handle.get(it["id"])
        if x is None:
            continue
        if it.get("props") and not x.SetProperties(it["props"]):
            problem(it, f"SetProperties {it['props']} refused")
        if it.get("fades") and not x.SetFades(it["fades"]):
            problem(it, f"SetFades {it['fades']} refused")
        if it.get("lut"):
            g = x.GetNodeGraph()
            if not g or not g.SetLUT(1, luts[it["lut"]]):
                problem(it, f"SetLUT {luts[it['lut']]} refused")
        if it.get("link") and handle.get(it["link"]) is not None:
            tl.SetClipsLinked([handle[it["link"]], x], True)
    for m in job["markers"]:
        tl.AddMarker(m["rec_f"], m["color"], m["name"], m["note"], m["n"])

    # the save is the verification boundary: read back from the saved timeline
    if not pm.SaveProject():
        problems.append({"id": "-", "what": "SaveProject returned False"})
    tl = next(t for t in timelines(proj) if t.GetName() == name)
    rows, bad, stray = readback(tl, job, base)
    markers = tl.GetMarkers() or {}
    report = {"ok": not bad and not problems and not stray and len(markers) >= len(job["markers"]), "project": job["project"], "timeline": name,
              "resolve": resolve.GetVersionString(), "items": len(rows), "wrong": bad, "problems": problems, "stray_items": stray,
              "markers": len(markers), "unused_not_imported": dropped, "seconds": round(time.time() - t0, 1),
              "rows": rows}
    with open(jp.parent / "build_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
    for r in rows:
        if not r["ok"]:
            print("WRONG", r["id"], r["track"], r["rec_f"], "; ".join(r["why"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
