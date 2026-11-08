#!/usr/bin/env python3
"""Render a DaVinci Resolve timeline to a draft H.264 MP4 through the
scripting API (DaVinci Resolve Studio, running). No Deliver page clicking.

  render_draft.py --list [--project P]          projects, current timeline, all timelines
  render_draft.py [--project P] [--timeline T]  render -> <project>/<drafts>/<project>-draft-N.mp4
        [--out-dir DIR] [--name NAME] [--height 1080] [--preset NAME]
        [--wait 120] [--preflight-only]

Defaults: the open project and its current timeline (what the user last had
open). Output folder: the drafts folder (settings project_layout.drafts) of the
project folder most of the timeline's clips live in; else
<paths.projects_dir>/<Resolve project name>/<drafts>. N = the first unused
number. Size: the short side is --height (settings render.draft_height,
1080), the timeline's aspect ratio kept (1920x1080, or 1080x1920 vertical).

Format: MP4 / H.264 / AAC set directly through the API, so no preset is
needed. --preset NAME loads one of the user's own render presets instead
(settings editor.draft_render_preset); TargetDir, name and size still apply.

Job-scoped: adds ONE render job, starts only that job, and deletes only that
job once the file is verified. The user's other queued jobs are never touched
(never DeleteAllRenderJobs). Before rendering, every clip's media is checked:
Resolve aborts a render at the first offline clip, so those are listed and
nothing is rendered (exit 2).

Exit codes: 0 rendered (or preflight clean), 2 offline media, 3 render
failed, 4 a setting is missing (ask the user, set it, re-run).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---- pure helpers -----------------------------------------------------------

def slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-").lower() or "timeline"


def draft_name(out_dir, project):
    """<project-slug>-draft-N, N = the first number with no existing file."""
    s, n = slug(project), 1
    while any((Path(out_dir) / f"{s}-draft-{n}{ext}").exists() for ext in (".mp4", ".mov", ".mxf")):
        n += 1
    return f"{s}-draft-{n}"


def scaled_size(tl_w, tl_h, short_side):
    """Output size: the SHORT side becomes `short_side` (1080 -> 1920x1080 for
    a landscape timeline, 1080x1920 for a vertical one), never upscaled, the
    timeline's aspect kept, even numbers only."""
    try:
        tl_w, tl_h = int(tl_w), int(tl_h)
    except (TypeError, ValueError):
        tl_w, tl_h = 1920, 1080
    if tl_w <= 0 or tl_h <= 0:
        tl_w, tl_h = 1920, 1080
    s = min(int(short_side), tl_w, tl_h)
    if tl_w >= tl_h:
        h, w = s, s * tl_w / tl_h
    else:
        w, h = s, s * tl_h / tl_w
    even = lambda v: int(round(v / 2.0)) * 2  # noqa: E731
    return even(w), even(h)


def pick_h264(codecs):
    """codecs: {description: codec name} from GetRenderCodecs('mp4')."""
    items = list((codecs or {}).items())
    for desc, name in items:
        if str(name).upper() in ("H264", "H.264"):
            return name
    for desc, name in items:
        if "264" in str(desc) or "264" in str(name):
            return name
    return None


def vote_project_dir(paths):
    """The project folder most of the clip paths sit in (settings.find_project_root)."""
    votes = Counter()
    for p in paths:
        if not p:
            continue
        try:
            root = settings.find_project_root(p)
        except Exception:
            root = None
        if root:
            votes[str(root)] += 1
    return Path(votes.most_common(1)[0][0]) if votes else None


# ---- Resolve side ------------------------------------------------------------

def connect(wait_s):
    from vidkit import resolve as vr
    deadline = time.time() + wait_s
    while True:
        try:
            return vr.connect()
        except SystemExit:
            if time.time() >= deadline:
                raise
            log("  waiting for DaVinci Resolve's scripting server...")
            time.sleep(5)


def timelines(proj):
    return [proj.GetTimelineByIndex(i) for i in range(1, (proj.GetTimelineCount() or 0) + 1)]


def all_items(tl):
    for kind in ("video", "audio"):
        for i in range(1, tl.GetTrackCount(kind) + 1):
            for it in tl.GetItemListInTrack(kind, i) or []:
                yield kind, i, it


def preflight(tl):
    fps = float(tl.GetSetting("timelineFrameRate"))
    t0 = tl.GetStartFrame()
    bad = []
    for kind, idx, it in all_items(tl):
        mpi = it.GetMediaPoolItem()
        if not mpi:
            continue  # titles, generators
        status = mpi.GetClipProperty("Online Status")
        path = mpi.GetClipProperty("File Path") or ""
        missing = bool(path) and not os.path.exists(path)
        if status == "Offline" or missing:
            s = (it.GetStart() - t0) / fps
            bad.append({"track": f"{kind[0].upper()}{idx}", "name": it.GetName(),
                        "at": "%02d:%02d:%05.2f" % (s // 3600, s % 3600 // 60, s % 60), "path": path,
                        "reason": "file missing from disk" if missing else "flagged offline"})
    return bad


def resolve_logs():
    home = Path.home()
    sysname = platform.system()
    if sysname == "Darwin":
        return [home / "Library/Application Support/Blackmagic Design/DaVinci Resolve/logs/davinci_resolve.log"]
    if sysname == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        return [appdata / "Blackmagic Design/DaVinci Resolve/Support/logs/davinci_resolve.log"]
    return [home / ".local/share/DaVinciResolve/logs/davinci_resolve.log"]


def upload_seen(path, since):
    """Did Resolve's own log record an upload of this file (the Deliver page's
    'Upload directly to ...' box is invisible to the API)? 'started' /
    'finished' / None. Best effort."""
    base = os.path.basename(path)
    state = None
    for lp in resolve_logs():
        try:
            with open(lp, errors="replace") as fh:
                for ln in fh:
                    if "Upload" not in ln or base not in ln:
                        continue
                    m = re.search(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", ln)
                    if m and time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) < since - 60:
                        continue
                    state = "finished" if "finished" in ln.lower() else (state or "started")
        except OSError:
            continue
    return state


def write_cuts_sidecar(path, tl, proj, info):
    """If EditReview's cuts exporter is installed, write <stem>.review/cuts.json
    (where every clip sits in the file). Never fails the render."""
    for cand in (REPO / "apps/edit-review/scripts/export_cuts.py",):
        if not cand.is_file():
            continue
        try:
            sys.path.insert(0, str(cand.parent))
            import export_cuts  # noqa
            mark_in, mark_out = int(info["MarkIn"]), int(info["MarkOut"])
            if mark_in < int(tl.GetStartFrame()):
                mark_in, mark_out = mark_in + int(tl.GetStartFrame()), mark_out + int(tl.GetStartFrame())
            out = export_cuts.write_sidecar(path, tl, proj.GetName(), mark_in, mark_out)
            return str(out[0] if isinstance(out, tuple) else out)
        except Exception as e:  # noqa: BLE001
            log(f"cuts sidecar not written ({e})")
            return None
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list projects and timelines, then exit")
    ap.add_argument("--project", help="Resolve project name (default: the open project)")
    ap.add_argument("--timeline", help="timeline name (default: the current timeline)")
    ap.add_argument("--out-dir", help="output folder (default: the project's drafts folder)")
    ap.add_argument("--name", help="output file name without extension (default: <project>-draft-N)")
    ap.add_argument("--height", type=int, default=None,
                    help="short side in pixels (default: settings render.draft_height, 1080)")
    ap.add_argument("--preset", default=None, help="load this render preset first (default: settings "
                                                   "editor.draft_render_preset, else plain MP4/H.264)")
    ap.add_argument("--wait", type=int, default=0, metavar="SECS", help="retry connecting this long (Resolve just launched)")
    ap.add_argument("--preflight-only", action="store_true")
    a = ap.parse_args()

    resolve = connect(a.wait)
    pm = resolve.GetProjectManager()
    if a.list:
        proj = pm.LoadProject(a.project) if a.project else pm.GetCurrentProject()
        out = {"projects": pm.GetProjectListInCurrentFolder(), "current_project": proj.GetName() if proj else None}
        if proj:
            cur = proj.GetCurrentTimeline()
            out["current_timeline"] = cur.GetName() if cur else None
            out["timelines"] = [{"name": t.GetName(), "frames": t.GetEndFrame() - t.GetStartFrame(),
                                 "fps": t.GetSetting("timelineFrameRate"),
                                 "size": f"{t.GetSetting('timelineResolutionWidth')}x{t.GetSetting('timelineResolutionHeight')}"}
                                for t in timelines(proj)]
        print(json.dumps(out, indent=1))
        return 0

    proj = pm.GetCurrentProject()
    if a.project and (proj is None or proj.GetName() != a.project):
        proj = pm.LoadProject(a.project)
    if proj is None:
        sys.exit(f"project {a.project!r} not found. Available: {pm.GetProjectListInCurrentFolder()}")
    if a.timeline:
        tl = next((t for t in timelines(proj) if t.GetName() == a.timeline), None)
        if tl is None:
            sys.exit(f"timeline {a.timeline!r} not found. Available: {[t.GetName() for t in timelines(proj)]}")
    else:
        tl = proj.GetCurrentTimeline()
        if tl is None:
            sys.exit("the project has no current timeline: pass --timeline")
    proj.SetCurrentTimeline(tl)
    fps = float(tl.GetSetting("timelineFrameRate"))
    log(f"project : {proj.GetName()}")
    log(f"timeline: {tl.GetName()} ({(tl.GetEndFrame() - tl.GetStartFrame()) / fps:.1f}s @ {fps}fps)")

    bad = preflight(tl)
    if bad:
        log("\nOFFLINE MEDIA (Resolve would stop the render at the first one; relink it in the Media page):")
        for e in bad:
            log(f"  {e['track']} @ {e['at']}  {e['name']!r}  ({e['reason']})  {e['path']}")
        print(json.dumps({"offline": bad}, indent=1))
        return 2
    log("preflight: all media online")
    if a.preflight_only:
        return 0

    try:
        if a.out_dir:
            out_dir = Path(a.out_dir).expanduser().resolve()
        else:
            clips = [it.GetMediaPoolItem().GetClipProperty("File Path") for _, _, it in all_items(tl)
                     if it.GetMediaPoolItem()]
            proj_dir = vote_project_dir(clips)
            if proj_dir is None:
                root = settings.get_path("paths.projects_dir", required=True,
                                         hint="the folder where your video projects live")
                proj_dir = root / proj.GetName()
            out_dir = proj_dir / settings.layout("drafts")
        height = a.height or int(settings.get("render.draft_height", default=1080))
        preset = a.preset or settings.get("editor.draft_render_preset", default=None)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = a.name or draft_name(out_dir, proj.GetName())
    w, h = scaled_size(tl.GetSetting("timelineResolutionWidth"), tl.GetSetting("timelineResolutionHeight"), height)

    if preset:
        if not proj.LoadRenderPreset(preset):
            sys.exit(f"render preset {preset!r} not found. Available: {proj.GetRenderPresetList()}")
    else:
        codec = pick_h264(proj.GetRenderCodecs("mp4"))
        if not codec or not proj.SetCurrentRenderFormatAndCodec("mp4", codec):
            sys.exit("could not select MP4 / H.264 on the Deliver page (pass --preset with one of: "
                     f"{proj.GetRenderPresetList()})")
    if hasattr(proj, "SetCurrentRenderMode"):
        proj.SetCurrentRenderMode(1)  # single clip: one file for the whole timeline
    ok = proj.SetRenderSettings({"SelectAllFrames": True, "TargetDir": str(out_dir), "CustomName": name,
                                 "ExportVideo": True, "ExportAudio": True, "FormatWidth": w, "FormatHeight": h})
    if not ok:
        sys.exit("SetRenderSettings was refused (is the output folder writable?)")
    if not preset:
        proj.SetRenderSettings({"AudioCodec": "aac"})  # best effort: older versions ignore it
    started = time.time()
    job = proj.AddRenderJob()
    if not job:
        sys.exit("AddRenderJob returned nothing")
    info = next((j for j in proj.GetRenderJobList() or [] if j.get("JobId") == job), None)
    if info is None:
        sys.exit(f"queued job {job} is missing from the render queue")
    log(f"render  : {info.get('VideoFormat')}/{info.get('VideoCodec')} {info.get('FormatWidth')}x"
        f"{info.get('FormatHeight')} frames {info.get('MarkIn')}-{info.get('MarkOut')} -> {info.get('OutputFilename')}")
    proj.StartRendering([job], isInteractiveMode=False)
    last = None
    while proj.IsRenderingInProgress():
        st = proj.GetRenderJobStatus(job) or {}
        pct = st.get("CompletionPercentage")
        if pct != last and pct is not None:
            log(f"  {pct}%")
            last = pct
        time.sleep(5)
    # the job record can vanish once the queue drains: the file is the verdict
    st = proj.GetRenderJobStatus(job) or {}
    path = out_dir / info["OutputFilename"]
    expected = (int(info["MarkOut"]) - int(info["MarkIn"]) + 1) / fps
    if st and st.get("JobStatus") not in ("Complete", None):
        log(f"RENDER FAILED: {st}")
        return 3
    if not path.exists():
        log(f"RENDER FAILED: no file at {path}")
        return 3
    pr = media.probe(path)
    if not pr["has_video"]:
        log("RENDER FAILED: the file has no video stream (the Deliver page was set to audio only); "
            "re-run, or pass --preset with a video preset")
        return 3
    if abs((pr["duration"] or 0) - expected) > 1.0:
        log(f"RENDER INCOMPLETE: {pr['duration']:.1f}s on disk, {expected:.1f}s expected")
        return 3
    if hasattr(proj, "DeleteRenderJob"):
        proj.DeleteRenderJob(job)  # only our own job, after the file checked out
    cuts = write_cuts_sidecar(str(path), tl, proj, info)
    time.sleep(2)
    up = upload_seen(str(path), started)
    result = {"file": str(path), "duration_s": round(pr["duration"], 2), "expected_s": round(expected, 2),
              "size_mb": round(path.stat().st_size / 1e6, 1), "width": pr["width"], "height": pr["height"],
              "project": proj.GetName(), "timeline": tl.GetName(), "cuts_sidecar": cuts, "upload_seen": up}
    if up:
        log("NOTE: Resolve's log shows this file being UPLOADED (the Deliver page's 'Upload directly to' box is "
            "ticked; the API cannot see it). Tell the user; untick it on the Deliver page for local drafts.")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
