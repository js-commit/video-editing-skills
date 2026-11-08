#!/usr/bin/env python3
"""Build a draft's cut list as a DaVinci Resolve timeline, for hand-editing (Resolve Studio only:
the free version blocks external scripting - import the draft mp4 instead).

  resolve_timeline.py CUT.json MIX.wav [--project NAME] [--timeline NAME]

Resolve must be running with Preferences > System > General > "External scripting using" = Local.
Creates (or reuses) the project, imports the clips and the mix, and builds a NEW timeline (an
existing one of the same name is left alone: pick another name). V1 holds every cut, frame-exact
on the beat grid; A1 holds the finished mix (montage-music's mixdown): Resolve's scripting API
cannot set per-clip volume, so the clips go in video-only and their sound is already in the mix.
Zooms become Zoom/Position on the clip (Inspector). Portrait shots arrive pillarboxed: add a
blurred copy underneath by hand if you want the blur-fill the ffmpeg draft has.

A phone clip with an odd frame rate can land one frame long; the next cut then starts right
after it and ends on the grid, so a cut is at most one frame late and nothing accumulates.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import resolve as R  # noqa: E402


def import_all(mp, root, folder_name: str, paths: list) -> dict:
    by_path = R.pool_by_path(root)
    need = sorted(set(paths) - set(by_path))
    if need:
        folder = next((f for f in root.GetSubFolderList() or [] if f.GetName() == folder_name), None) or mp.AddSubFolder(root, folder_name)
        mp.SetCurrentFolder(folder)
        for k in range(0, len(need), 25):
            for it in mp.ImportMedia(need[k:k + 25]) or []:
                p = it.GetClipProperty("File Path")
                if p:
                    by_path[p] = it
        mp.SetCurrentFolder(root)
    missing = set(paths) - set(by_path)
    if missing:
        sys.exit(f"Resolve did not import: {sorted(missing)[:3]}")
    return by_path


def clip_fps(item) -> float:
    try:
        return float(item.GetClipProperty("FPS"))
    except (TypeError, ValueError):
        return 0.0


def item_len(item) -> int:
    d = item.GetDuration() if item else 0
    if not d and item:
        try:
            d = item.GetEnd() - item.GetStart()
        except TypeError:
            d = 0
    return d or 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cut")
    ap.add_argument("mix")
    ap.add_argument("--project")
    ap.add_argument("--timeline")
    a = ap.parse_args()
    job = json.load(open(a.cut))
    W, H, fps = int(job["width"]), int(job["height"]), int(job.get("fps", 30))
    mix = str(Path(a.mix).resolve())                       # ImportMedia needs absolute paths
    cuts = job["cuts"]
    if any(c.get("photo") for c in cuts):
        R.log("note: photo cuts are placed as stills without the push-in (animate them in the Inspector)")
    for c in cuts:
        if not os.path.exists(c["file"]):
            sys.exit(f"missing {c['file']}")
    name = a.project or job.get("project", "home-video")
    tl_name = a.timeline or f"{name} v{job.get('version', '')}".strip()

    resolve = R.connect()
    pm = resolve.GetProjectManager()
    proj = pm.LoadProject(name) if name in (pm.GetProjectListInCurrentFolder() or []) else None
    if proj is None:
        proj = pm.CreateProject(name)
        if proj is None:
            sys.exit(f"could not create the Resolve project {name!r}")
        for k, v in (("timelineResolutionWidth", str(W)), ("timelineResolutionHeight", str(H)), ("timelineFrameRate", str(fps))):
            proj.SetSetting(k, v)
    if any(t.GetName() == tl_name for t in R.timelines(proj)):
        sys.exit(f"a timeline named {tl_name!r} already exists: pass --timeline with a new name (nothing was changed)")
    mp = proj.GetMediaPool()
    root = mp.GetRootFolder()
    by_path = import_all(mp, root, "footage", sorted({c["file"] for c in cuts}))
    by_path.update(import_all(mp, root, "music", [mix]))
    tl = mp.CreateEmptyTimeline(tl_name)
    if tl is None:
        sys.exit("CreateEmptyTimeline failed")
    proj.SetCurrentTimeline(tl)
    R.ensure_resolution(proj, tl, W, H)
    tl.SetStartTimecode("00:00:00:00")
    resolve.OpenPage("edit")
    base = tl.GetStartFrame()
    end_frame = round(float(job["end_s"]) * fps)
    cursor, late = 0, 0
    for i, c in enumerate(cuts):
        mpi = by_path[c["file"]]
        cf = clip_fps(mpi) or fps
        rec = cursor if i else round(c["record_s"] * fps)
        nxt = round(cuts[i + 1]["record_s"] * fps) if i + 1 < len(cuts) else end_frame
        want = nxt - rec
        late = max(late, rec - round(c["record_s"] * fps))
        if want < 1:
            sys.exit(f"cut {i}: no room left on the grid")
        sf = round(c["in_s"] * cf)
        want_src = round(want * cf / fps)
        it, tried = None, {}
        for _ in range(5):
            added = mp.AppendToTimeline([{"mediaPoolItem": mpi, "trackIndex": 1, "mediaType": 1, "startFrame": sf,
                                          "endFrame": sf + want_src, "recordFrame": base + rec}]) or []
            it = added[0] if added else None
            got = item_len(it)
            if got == want:
                break
            if got == 0:
                time.sleep(1.0)
                continue
            tried[want_src] = got
            if got == want + 1 and (want_src - 1) in tried and tried[want_src - 1] < want:
                break                                    # odd fps: one frame long, the next cut gives it back
            if not R.delete_clips_checked(tl, [it]):
                sys.exit(f"cut {i}: could not remove a mis-sized clip to retry")
            it = None
            want_src += (want - got) if abs(want - got) > 1 else (1 if want > got else -1)
        if not it or item_len(it) not in (want, want + 1):
            sys.exit(f"cut {i}: could not place {want} frames of {c['file']} (tried {tried})")
        z = c.get("zoom")
        if z:
            zf = float(z.get("z", 1.0))
            lim = (zf - 1) / (2 * zf)
            cx = min(max(float(z.get("cx", 0.5)), 0.5 - lim), 0.5 + lim)
            cy = min(max(float(z.get("cy", 0.5)), 0.5 - lim), 0.5 + lim)
            it.SetProperty("ZoomX", zf)
            it.SetProperty("ZoomY", zf)
            it.SetProperty("Pan", -(cx - 0.5) * W * zf)
            it.SetProperty("Tilt", (cy - 0.5) * H * zf)
        cursor = rec + item_len(it)
    added = mp.AppendToTimeline([{"mediaPoolItem": by_path[mix], "trackIndex": 1, "mediaType": 2, "recordFrame": base}]) or []
    if not added:
        R.log("WARNING: the mix did not go onto A1; drag it from the music bin to the start of the timeline")
    pm.SaveProject()
    print(json.dumps({"project": name, "timeline": tl_name, "cuts": len(cuts), "frames": cursor, "max_frames_late": late}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
