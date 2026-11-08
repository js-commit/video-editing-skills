#!/usr/bin/env python3
"""Render the final master of a DaVinci Resolve timeline at full resolution,
from the command line (needs DaVinci Resolve Studio running: the free version
does not allow external scripting).

    render_master.py --list [--project NAME]
    render_master.py [--project NAME] [--timeline NAME] [--out-dir DIR] [--name NAME]
                     [--preset "My YouTube 4K"] [--codec H265|H264] [--width W --height H]
                     [--preflight-only]

Defaults: the open project and its current timeline, the whole timeline (in/out
marks ignored), MP4 at the timeline's own resolution, into the project's finals
folder (settings project_layout.finals) as <name>.mp4.

How it renders: it adds ONE render job of its own and starts only that job. It
never clears the render queue (clearing it can cancel someone's queued job or a
running YouTube upload). After the render it checks the file: it exists, its
duration matches the timeline within a second, and it has a video stream.

Things the scripting API cannot do (set them on the Deliver page, or save a
render preset with them and pass --preset):
  * bitrate / quality (the API accepts a quality key but ignores it),
  * Normalize Audio (loudness is fixed afterwards with loudness.py anyway),
  * the "Upload directly to YouTube" box of Resolve's YouTube presets.
Loading a preset resets those click-only fields, so load it first (this script
does) and never reload a preset after clicking them.

Exit codes: 0 rendered | 2 offline media or bad arguments, nothing rendered |
3 the render failed or the file is wrong | 4 a setting is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media, settings  # noqa: E402
from vidkit.resolve import connect, log, timelines, youtube_upload_logged  # noqa: E402


def all_items(tl):
    for kind in ("video", "audio"):
        for i in range(1, (tl.GetTrackCount(kind) or 0) + 1):
            for it in tl.GetItemListInTrack(kind, i) or []:
                yield kind, i, it


def clip_paths(tl) -> list:
    out = []
    for _, _, it in all_items(tl):
        mpi = it.GetMediaPoolItem()
        p = mpi.GetClipProperty("File Path") if mpi else ""
        if p:
            out.append(p)
    return out


def preflight(tl) -> list:
    """Clips Resolve cannot render: it aborts the whole job at the first offline clip."""
    fps = float(tl.GetSetting("timelineFrameRate"))
    bad = []
    for kind, idx, it in all_items(tl):
        mpi = it.GetMediaPoolItem()
        if not mpi:
            continue                         # titles, generators
        status = mpi.GetClipProperty("Online Status")
        path = mpi.GetClipProperty("File Path") or ""
        if status == "Offline" or (path and not os.path.exists(path)):
            s = it.GetStart() / fps
            bad.append(f"{kind[0].upper()}{idx} @ {int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}  "
                       f"{it.GetName()!r}  {path or '(no path)'}")
    return bad


def default_out_dir(tl) -> Path | None:
    """The finals folder of the project most of the timeline's clips live in."""
    roots = Counter(str(r) for r in (settings.find_project_root(p) for p in clip_paths(tl)) if r)
    if not roots:
        return None
    return Path(roots.most_common(1)[0][0]) / settings.layout("finals")


def slug(text: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-") or "master"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list projects and the project's timelines")
    ap.add_argument("--project", help="project name (default: the open project)")
    ap.add_argument("--timeline", help="timeline name (default: the current timeline)")
    ap.add_argument("--out-dir", help="default: <project>/<finals folder> from settings")
    ap.add_argument("--name", help="file name without extension (default: <project>-master)")
    ap.add_argument("--preset", help="a render preset to load first (your own, saved on the Deliver page)")
    ap.add_argument("--codec", default="H265", help="MP4 codec when no preset is given: H265 (default) or H264")
    ap.add_argument("--width", type=int, help="default: the timeline's width")
    ap.add_argument("--height", type=int, help="default: the timeline's height")
    ap.add_argument("--preflight-only", action="store_true")
    a = ap.parse_args(argv)

    try:
        resolve = connect()
        pm = resolve.GetProjectManager()
        proj = pm.LoadProject(a.project) if a.project else pm.GetCurrentProject()
        if proj is None:
            log(f"project {a.project!r} not found. Projects here: {pm.GetProjectListInCurrentFolder()}")
            return 2
        if a.list:
            cur = proj.GetCurrentTimeline()
            print(json.dumps({"project": proj.GetName(), "current_timeline": cur.GetName() if cur else None,
                              "timelines": [{"name": t.GetName(),
                                             "frames": t.GetEndFrame() - t.GetStartFrame(),
                                             "fps": t.GetSetting("timelineFrameRate"),
                                             "size": f"{t.GetSetting('timelineResolutionWidth')}x"
                                                     f"{t.GetSetting('timelineResolutionHeight')}"}
                                            for t in timelines(proj)]}, indent=2))
            return 0
        if a.timeline:
            tl = next((t for t in timelines(proj) if t.GetName() == a.timeline), None)
            if tl is None:
                log(f"timeline {a.timeline!r} not found: {[t.GetName() for t in timelines(proj)]}")
                return 2
        else:
            tl = proj.GetCurrentTimeline()
        if tl is None:
            log("no timeline is open in this project")
            return 2
        if "backup" in tl.GetName().lower():
            log(f"refusing to render a backup timeline ({tl.GetName()!r}): name the deliverable with --timeline")
            return 2
        proj.SetCurrentTimeline(tl)
        fps = float(tl.GetSetting("timelineFrameRate"))
        log(f"project : {proj.GetName()}\ntimeline: {tl.GetName()} "
            f"({tl.GetEndFrame() - tl.GetStartFrame()} frames @ {fps} fps)")

        bad = preflight(tl)
        if bad:
            log("OFFLINE MEDIA: Resolve would abort the render at the first of these. Relink them "
                "(right-click > Relink) and run again:\n  " + "\n  ".join(bad))
            return 2
        log("preflight: all media online")
        if a.preflight_only:
            return 0

        out_dir = Path(a.out_dir).expanduser() if a.out_dir else default_out_dir(tl)
        if out_dir is None:
            log("could not tell which project folder this timeline belongs to: pass --out-dir")
            return 2
        out_dir.mkdir(parents=True, exist_ok=True)
        name = a.name or f"{slug(proj.GetName())}-master"
        width = a.width or int(tl.GetSetting("timelineResolutionWidth"))
        height = a.height or int(tl.GetSetting("timelineResolutionHeight"))

        if a.preset:
            if not proj.LoadRenderPreset(a.preset):
                log(f"render preset {a.preset!r} not found: {proj.GetRenderPresetList()}")
                return 2
        else:
            codecs = proj.GetRenderCodecs("mp4") or {}
            want = [v for k, v in codecs.items() if v == a.codec or k.replace(".", "") == a.codec]
            fallback = [v for v in codecs.values() if v == "H264"]
            codec = (want or fallback or [None])[0]
            if not codec or not proj.SetCurrentRenderFormatAndCodec("mp4", codec):
                log(f"could not select MP4/{a.codec}: available {codecs}")
                return 2
            log(f"format  : mp4 / {codec}")
        proj.SetRenderSettings({"SelectAllFrames": 1, "TargetDir": str(out_dir), "CustomName": name,
                                "ExportVideo": True, "ExportAudio": True,
                                "FormatWidth": width, "FormatHeight": height})
        job = proj.AddRenderJob()
        if not job:
            log("AddRenderJob failed (is the output folder an absolute path?)")
            return 3
        info = next((j for j in proj.GetRenderJobList() or [] if j.get("JobId") == job), None)
        if info is None:
            log(f"the queued job {job} is missing from the render queue")
            return 3
        log(f"render  : {info.get('FormatWidth')}x{info.get('FormatHeight')} frames "
            f"{info.get('MarkIn')}-{info.get('MarkOut')} -> {info.get('OutputFilename')}")
        proj.StartRendering([job], isInteractiveMode=False)
        last = None
        while proj.IsRenderingInProgress():
            pct = (proj.GetRenderJobStatus(job) or {}).get("CompletionPercentage")
            if pct != last:
                log(f"  {pct}%")
                last = pct
            time.sleep(5)
        # Resolve may drop the job record once the queue drains: the file is the verdict.
        st = proj.GetRenderJobStatus(job) or {}
        path = out_dir / info["OutputFilename"]
        if st and st.get("JobStatus") not in ("Complete", None):
            log(f"RENDER FAILED: {st}")
            return 3
        if not path.exists():
            log(f"RENDER FAILED: no file at {path}")
            return 3
        expected = (int(info["MarkOut"]) - int(info["MarkIn"]) + 1) / float(info.get("FrameRate") or fps)
        probe = media.probe(path)
        if not probe["has_video"]:
            log("RENDER FAILED: the file has no video stream (the Deliver page was on an audio-only setting): "
                "pick a video preset and run again")
            return 3
        if abs((probe["duration"] or 0) - expected) > 1.0:
            log(f"RENDER INCOMPLETE: {probe['duration']:.1f}s on disk, {expected:.1f}s expected")
            return 3
        time.sleep(3)
        uploaded = youtube_upload_logged(path)   # a YouTube preset can upload while rendering
        result = {"master": str(path), "duration_s": probe["duration"], "width": probe["width"],
                  "height": probe["height"], "vcodec": probe["vcodec"],
                  "bytes": path.stat().st_size, "resolve_also_uploaded_to_youtube": uploaded}
        if uploaded:
            log("NOTE: Resolve's log shows a YouTube upload of this file: the preset had 'Upload directly to "
                "YouTube' ticked. Tell the user; it is on their channel with the Deliver page's privacy.")
        print(json.dumps(result, indent=2))
        return 0
    except settings.SettingMissing as e:
        settings.exit_missing(e)


if __name__ == "__main__":
    sys.exit(main())
