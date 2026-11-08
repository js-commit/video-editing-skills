#!/usr/bin/env python3
"""Build a Short as a NEW vertical timeline in an existing DaVinci Resolve
project, from the long-form timeline's own clips (needs DaVinci Resolve Studio:
the free version blocks external scripting).

    resolve_short.py snapshot SPEC --project P                      # .drp backup first (do this once per session)
    resolve_short.py create   SPEC --project P --long-timeline "Main edit" [--name "short - my-slug"] [--dry-run | --prepare-only]
    resolve_short.py stills   SPEC --project P --name "short - my-slug" 1.0 8.5 20
    resolve_short.py render   SPEC --project P --name "short - my-slug" [--out-dir DIR]

Same spec as make_short.py. The spec's times are times in the long-form RENDER
(that is what the transcript was made from); `create` maps them onto the
long-form timeline (render start = the timeline's first frame, or --offset) and
reuses the clip under each moment from the topmost enabled video track, so the
short stays editable in Resolve. B-roll from other files ("video": {...}) is
imported into a "shorts" bin.

Tracks on the new timeline: V1 = the picture (or a stack's bottom pane, or a fit
shot's dimmed backdrop), V2 = a stack's top pane / a fit shot's picture, V3 = the
captions (a transparent ProRes 4444 clip rendered by make_short.py), A1 = the
cut, loudness-matched audio (a WAV rendered by make_short.py, waveform-safe cuts
and fades included). Existing timelines are never touched: this script only
creates or replaces timelines whose name starts with "short".

Not copied from the long-form: per-clip transforms, speed changes and the
grades on its timeline items. Check the stills.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortslib as sl  # noqa: E402
from vidkit import resolve as vr  # noqa: E402

HERE = Path(__file__).resolve().parent
TITLE_TRACK = 3


# ---- the ffmpeg-made parts (audio, captions) and the plan ---------------------

def make_short(spec_path: str, *extra) -> dict:
    r = subprocess.run([sys.executable, "-B", str(HERE / "make_short.py"), spec_path, *extra],
                       capture_output=True, text=True)
    if r.returncode:
        sl.die(f"make_short.py {' '.join(extra)} failed:\n{r.stderr[-1500:]}")
    return json.loads(r.stdout[r.stdout.index("{"):])


def spec_hash(spec_path: str) -> str:
    return hashlib.sha1(Path(spec_path).read_bytes()).hexdigest()[:8]


def guard_name(name: str):
    if not name.lower().startswith("short"):
        sl.die(f"REFUSED: {name!r} does not start with 'short'; this script never touches other timelines")


# ---- placement (Crop + Zoom + Pan/Tilt; measured on Resolve 19-21) --------------

def clip_size(mpi) -> tuple:
    w, h = (int(x) for x in str(mpi.GetClipProperty("Resolution")).lower().split("x"))
    return w, h


def clip_fps(mpi) -> float:
    try:
        return float(mpi.GetClipProperty("FPS"))
    except (TypeError, ValueError):
        return 0.0


def window_transform(mpi, frame_w, frame_h, win, target_cx, target_cy, target_w, target_h, mode="fill"):
    """Place a source-pixel window (x, y, w, h, display pixels) into a target rect.

    Crop values are timeline pixels of the scale-to-fit image, applied before
    Zoom; Zoom scales about the frame centre; Pan = +1 px/unit * fitted_w/frame_w
    (right), Tilt = -1 px/unit * fitted_h/frame_h (up). On a portrait clip with
    rotation metadata the horizontal crop edges are swapped."""
    W, H = clip_size(mpi)
    fit = min(frame_w / W, frame_h / H)
    w0, h0 = W * fit, H * fit
    sx0, sy0, sw, sh = win
    zoom = (min if mode == "fit" else max)(target_w / (fit * sw), target_h / (fit * sh))
    fx0, fy0, fw_, fh_ = sx0 * fit, sy0 * fit, sw * fit, sh * fit
    crop_l, crop_r = fx0, w0 - (fx0 + fw_)
    crop_t, crop_b = fy0, h0 - (fy0 + fh_)
    cx1 = (frame_w - w0) / 2 + fx0 + fw_ / 2
    cy1 = (frame_h - h0) / 2 + fy0 + fh_ / 2
    cx2 = frame_w / 2 + zoom * (cx1 - frame_w / 2)
    cy2 = frame_h / 2 + zoom * (cy1 - frame_h / 2)
    pan = (target_cx - cx2) * frame_w / w0
    tilt = -(target_cy - cy2) * frame_h / h0
    rotated = H > W
    crops = {"CropLeft": crop_r if rotated else crop_l, "CropRight": crop_l if rotated else crop_r,
             "CropTop": crop_t, "CropBottom": crop_b}
    return zoom, pan, tilt, crops


def place(item, mpi, fw, fh, win, target, mode, label, opacity=None):
    tcx, tcy, tw, th = target
    zoom, pan, tilt, crops = window_transform(mpi, fw, fh, win, tcx, tcy, tw, th, mode)
    props = {"ZoomX": zoom, "ZoomY": zoom, "Pan": pan, "Tilt": tilt, **crops}
    if opacity is not None:
        props["Opacity"] = opacity
    bad = [k for k, v in props.items() if not item.SetProperty(k, v)]
    if bad:
        sl.log(f"WARNING {label}: Resolve refused {bad}")


def item_len(item) -> int:
    d = item.GetDuration()
    if not d:
        try:
            d = item.GetEnd() - item.GetStart()
        except TypeError:
            d = 0
    return int(d or 0)


def append_exact(mp, tl, mpi, start_src, n, tl_fps, track, record, media_type=1):
    """Append `n` timeline frames of `mpi` from source frame `start_src`.

    Source and timeline rates can differ, so ask, measure and correct. Resolve
    sometimes returns a zero-length ghost item while it is busy: delete it and
    retry. Settle one frame SHORT rather than long (long would overlap the next
    piece)."""
    sfps = clip_fps(mpi) or tl_fps
    want = round(n * sfps / tl_fps)
    best = None
    for _ in range(12):
        added = mp.AppendToTimeline([{"mediaPoolItem": mpi, "trackIndex": track, "mediaType": media_type,
                                      "startFrame": int(start_src), "endFrame": int(start_src + want - 1),
                                      "recordFrame": int(record)}]) or []
        if not added:
            sl.die(f"AppendToTimeline failed on V{track} at frame {record}")
        item = added[0]
        got = item_len(item)
        if got == n:
            return item
        if got == 0:
            tl.DeleteClips([item])
            time.sleep(1.5)
            continue
        if not vr.delete_clips_checked(tl, [item]):
            sl.die(f"could not delete a mis-sized item on V{track} at {record}; re-run create")
        if got < n and (best is None or got > best[0]):
            best = (got, want)
        want += n - got
    if best is None:
        sl.die(f"V{track} at frame {record}: could not place {n} frames; re-run create")
    sl.log(f"WARNING: V{track} at frame {record} settled for {best[0]} of {n} frames")
    return mp.AppendToTimeline([{"mediaPoolItem": mpi, "trackIndex": track, "mediaType": media_type,
                                 "startFrame": int(start_src), "endFrame": int(start_src + best[1] - 1),
                                 "recordFrame": int(record)}])[0]


# ---- reading the long-form timeline ---------------------------------------------

def timeline_by_name(project, name):
    t = next((t for t in vr.timelines(project) if t.GetName() == name), None)
    if t is None:
        sl.die(f"timeline {name!r} not found in project {project.GetName()!r}")
    return t


def long_items(tl) -> list:
    """Video items with media, topmost track first."""
    out = []
    for track in range(tl.GetTrackCount("video") or 0, 0, -1):
        try:
            if not tl.GetIsTrackEnabled("video", track):
                continue
        except Exception:
            pass
        for it in tl.GetItemListInTrack("video", track) or []:
            try:
                if not it.GetClipEnabled():
                    continue
            except Exception:
                pass
            mpi = it.GetMediaPoolItem()
            path = mpi.GetClipProperty("File Path") if mpi else ""
            if not path:
                continue   # titles, generators, compound clips without a file
            try:
                src0 = it.GetSourceStartFrame()
            except Exception:
                src0 = it.GetLeftOffset()
            out.append({"track": track, "start": it.GetStart(), "end": it.GetEnd(), "mpi": mpi,
                        "path": path, "src0": src0, "name": it.GetName()})
    return out


def map_range(items, f0, f1, tl_fps):
    """Split timeline frames [f0, f1) into (item, source frame, frames) runs, topmost clip first."""
    runs, f = [], f0
    while f < f1:
        it = next((i for i in items if i["start"] <= f < i["end"]), None)
        if it is None:
            sl.die(f"nothing with media on the long-form timeline at frame {f}; check --offset")
        end = min(f1, it["end"])
        for other in items:   # a higher clip starting inside this run cuts it short
            if other["track"] > it["track"] and f < other["start"] < end:
                end = other["start"]
        ratio = (clip_fps(it["mpi"]) or tl_fps) / tl_fps
        runs.append((it, it["src0"] + round((f - it["start"]) * ratio), end - f))
        f = end
    return runs


# ---- commands ---------------------------------------------------------------------

def connect_project(name):
    resolve = vr.connect()
    pm = resolve.GetProjectManager()
    return resolve, pm, vr.get_project(pm, name)


def cmd_snapshot(a, spec):
    _, pm, proj = connect_project(a.project)
    pm.SaveProject()
    out = Path(a.out_dir or sl.work_dir(spec["source"]) / "backup").expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{a.project}-{time.strftime('%Y%m%d-%H%M%S')}.drp"
    if not pm.ExportProject(a.project, str(path)) or not path.exists():
        sl.die(f"ExportProject failed -> {path}")
    print(json.dumps({"snapshot": str(path), "mb": round(path.stat().st_size / 1e6, 1)}))
    return 0


def cmd_create(a, spec):
    name = a.name or f"short - {spec.get('slug') or Path(a.spec).stem}"
    guard_name(name)
    W, H = sl.parse_size((spec.get("width", 1080), spec.get("height", 1920)))
    work = sl.work_dir(spec["source"])
    tag = spec_hash(a.spec)
    # fresh file names per spec version: Resolve keeps a re-rendered file's OLD length and
    # picture cached under the same path, silently (the stale-pool-clip trap)
    wav = work / f"{spec.get('slug', 'short')}.audio.{tag}.wav"
    mov = work / f"{spec.get('slug', 'short')}.captions.{tag}.mov"
    plan = make_short(a.spec, "--dry-run")
    if not wav.exists():
        make_short(a.spec, "--audio-only", str(wav))
    has_caps = plan["captions"]["engine"] != "off"
    if has_caps and not mov.exists():
        make_short(a.spec, "--captions-overlay", str(mov))

    if a.prepare_only:
        print(json.dumps({"timeline": name, "audio": str(wav), "captions": str(mov) if has_caps else None,
                          "pieces": len(plan["pieces"]), "duration_s": plan["duration_s"],
                          "note": "files ready; Resolve was not contacted"}, indent=2))
        return 0

    resolve, pm, proj = connect_project(a.project)
    mp = proj.GetMediaPool()
    long_tl = timeline_by_name(proj, a.long_timeline)
    tl_fps = float(vr.parse_fps(long_tl.GetSetting("timelineFrameRate")))
    items = long_items(long_tl)
    base_long = long_tl.GetStartFrame() + round(a.offset * tl_fps)
    master = os.path.realpath(spec["source"])

    # resolve every piece to (media pool item, source frame, frames, window, target, track)
    by_path = vr.pool_by_path(mp.GetRootFolder())
    need = sorted({s["file"] for p in plan["pieces"] for s in p["sources"] if os.path.realpath(s["file"]) != master}
                  | ({str(wav)} | ({str(mov)} if has_caps else set())))
    missing = [p for p in need if p not in by_path]
    if missing and not a.dry_run:
        root = mp.GetRootFolder()
        folder = next((f for f in root.GetSubFolderList() or [] if f.GetName() == "shorts"), None) \
            or mp.AddSubFolder(root, "shorts")
        mp.SetCurrentFolder(folder)
        for it in mp.ImportMedia(missing) or []:
            by_path[it.GetClipProperty("File Path")] = it
        mp.SetCurrentFolder(root)
        lost = [p for p in missing if p not in by_path]
        if lost:
            sl.die(f"ImportMedia did not take: {lost}")

    jobs = []
    for k, p in enumerate(plan["pieces"]):
        f0, f1 = round(p["out_start"] * tl_fps), round(p["out_end"] * tl_fps)
        if f1 <= f0:
            continue
        roles = ([("bottom", 1, (W / 2, 3 * H / 4, W, H / 2), W / (H / 2), p["sources"][1]),
                  ("top", 2, (W / 2, H / 4, W, H / 2), W / (H / 2), p["sources"][0])]
                 if p["mode"] == "stack" else
                 [("main", 2 if p["mode"] == "fit" else 1, (W / 2, H / 2, W, H), W / H, p["sources"][0])])
        if p["mode"] == "fit":
            roles.append(("backdrop", 1, (W / 2, H / 2, W, H), W / H, p["sources"][0]))
        for role, track, target, aspect, src in roles:
            if os.path.realpath(src["file"]) == master:
                lf0 = base_long + round(src["start"] * tl_fps)
                runs = map_range(items, lf0, lf0 + (f1 - f0), tl_fps)
            else:
                mpi = by_path.get(src["file"])
                runs = [({"mpi": mpi, "path": src["file"], "name": Path(src["file"]).name},
                         round(src["start"] * (clip_fps(mpi) or tl_fps)) if mpi else 0, f1 - f0)]
            rec = f0
            for it, s0, n in runs:
                jobs.append({"piece": k, "role": role, "track": track, "record": rec, "frames": n, "src_frame": s0,
                             "path": it["path"], "clip": it["name"], "mpi": it["mpi"], "target": target,
                             "aspect": aspect, "zoom": src["zoom"], "cx": src["cx"], "cy": src["cy"],
                             "mode": "fit" if role == "main" and p["mode"] == "fit" else "fill",
                             "opacity": 40.0 if role == "backdrop" else None})
                rec += n
    report = [{k: v for k, v in j.items() if k != "mpi"} for j in jobs]
    (work / f"{spec.get('slug', 'short')}.resolve-job.json").write_text(json.dumps(report, indent=2))
    if a.dry_run:
        print(json.dumps({"timeline": name, "fps": tl_fps, "placements": report}, indent=2))
        return 0

    # the new timeline (replacing an older "short..." of the same name)
    old = next((t for t in vr.timelines(proj) if t.GetName() == name), None)
    if old:
        guard_name(old.GetName())
        if not mp.DeleteTimelines([old]):
            sl.die(f"could not delete the old {name!r}")
    tl = mp.CreateEmptyTimeline(name)
    if tl is None:
        sl.die("CreateEmptyTimeline failed")
    proj.SetCurrentTimeline(tl)
    tl.SetSetting("useCustomSettings", "1")
    tl.SetSetting("timelineFrameRate", str(round(tl_fps, 3)))
    vr.ensure_resolution(proj, tl, W, H)
    tl.SetStartTimecode("00:00:00:00")
    while (tl.GetTrackCount("video") or 0) < TITLE_TRACK:
        if not tl.AddTrack("video"):
            sl.die("AddTrack(video) failed")
    base = tl.GetStartFrame()
    for j in sorted(jobs, key=lambda j: (j["track"], j["record"])):
        mpi = j["mpi"]
        item = append_exact(mp, tl, mpi, j["src_frame"], j["frames"], tl_fps, j["track"], base + j["record"])
        cw, ch = clip_size(mpi)
        win = sl.window(cw, ch, j["aspect"], 1.0 if j["mode"] == "fit" else j["zoom"], j["cx"], j["cy"]) \
            if j["mode"] != "fit" else (0, 0, cw, ch)
        place(item, mpi, W, H, win, j["target"], j["mode"], f"piece {j['piece']} {j['role']}", j["opacity"])
    total = round(plan["duration_s"] * tl_fps)
    if has_caps:
        cap = by_path[str(mov)]
        append_exact(mp, tl, cap, 0, total, tl_fps, TITLE_TRACK, base)
    if (tl.GetTrackCount("audio") or 0) < 1:
        tl.AddTrack("audio", "stereo")
    aud = by_path[str(wav)]
    if not mp.AppendToTimeline([{"mediaPoolItem": aud, "trackIndex": 1, "mediaType": 2, "recordFrame": base}]):
        sl.die("could not place the audio")
    a_items = tl.GetItemListInTrack("audio", 1) or []
    a_len = sum(item_len(i) for i in a_items)
    status = "OK" if abs(a_len - total) <= 1 else "MISMATCH"
    pm.SaveProject()
    print(json.dumps({"timeline": name, "frames": total, "fps": tl_fps, "size": f"{W}x{H}",
                      "placements": len(jobs), "audio_frames": a_len, "audio_vs_video": status,
                      "job": str(work / f"{spec.get('slug', 'short')}.resolve-job.json")}, indent=2))
    return 0 if status == "OK" else 1


def cmd_stills(a, spec):
    """Export the exact rendered frame at each time (Edit page only; the viewer lags a
    timecode change, so wait for it to read back and settle before exporting)."""
    guard_name(a.name)
    resolve, pm, proj = connect_project(a.project)
    tl = timeline_by_name(proj, a.name)
    proj.SetCurrentTimeline(tl)
    fps = float(tl.GetSetting("timelineFrameRate"))
    out = Path(a.out_dir or sl.work_dir(spec["source"]) / "stills").expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    prev = resolve.GetCurrentPage()
    if prev != "edit":
        resolve.OpenPage("edit")
    done = []
    try:
        for t in a.seconds:
            tc = vr.tc(tl.GetStartFrame() + int(float(t) * fps), fps)
            tl.SetCurrentTimecode(tc)
            for _ in range(20):
                if tl.GetCurrentTimecode() == tc:
                    break
                time.sleep(0.25)
            time.sleep(1.5)
            path = out / f"still_{float(t):g}s.png"
            if path.exists():
                path.unlink()
            if not (proj.ExportCurrentFrameAsStill(str(path)) and path.exists()):
                sl.die(f"ExportCurrentFrameAsStill failed at {t} s")
            done.append(str(path))
    finally:
        if prev and prev != "edit":
            resolve.OpenPage(prev)
    print(json.dumps({"stills": done}, indent=2))
    return 0


def cmd_render(a, spec):
    """Render only our own job, with explicit settings. Never clears the user's render queue.
    Resolve's "Upload directly to YouTube" box can stay on for the whole app session after a
    YouTube preset was used, and no preset choice clears it here: the skill asks the user to
    untick it first, and the log is checked afterwards."""
    guard_name(a.name)
    W, H = sl.parse_size((spec.get("width", 1080), spec.get("height", 1920)))
    resolve, pm, proj = connect_project(a.project)
    tl = timeline_by_name(proj, a.name)
    proj.SetCurrentTimeline(tl)
    out = Path(a.out_dir or sl.settings.drafts_dir(spec["source"])).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not proj.SetCurrentRenderFormatAndCodec("mp4", "H265") and not proj.SetCurrentRenderFormatAndCodec("mp4", "H264"):
        sl.die("could not set an mp4 H.265/H.264 render format")
    proj.SetRenderSettings({"SelectAllFrames": 1, "TargetDir": str(out), "CustomName": spec.get("slug", a.name),
                            "ExportVideo": True, "ExportAudio": True, "FormatWidth": W, "FormatHeight": H})
    job = proj.AddRenderJob()
    if not job:
        sl.die("AddRenderJob failed")
    info = next((j for j in proj.GetRenderJobList() or [] if j.get("JobId") == job), None)
    proj.StartRendering([job], isInteractiveMode=False)
    while proj.IsRenderingInProgress():
        time.sleep(3)
    st = proj.GetRenderJobStatus(job) or {}
    path = out / (info or {}).get("OutputFilename", f"{spec.get('slug', a.name)}.mp4")
    if st.get("JobStatus") not in ("Complete", None) or not path.exists():
        sl.die(f"render failed: {st}")
    got = sl.media.probe(path)
    if (got["width"], got["height"]) != (W, H) or not got["has_video"]:
        sl.die(f"render is {got['width']}x{got['height']} (video: {got['has_video']}), wanted {W}x{H}")
    proj.DeleteRenderJob(job)
    from vidkit.resolve import youtube_upload_logged
    uploaded = youtube_upload_logged(path)
    if uploaded:
        print(f"WARNING: Resolve's log shows a YouTube upload of {path.name}: the Deliver page's 'Upload directly "
              "to YouTube' box was on. Tell the user now; they delete it in YouTube Studio and untick the box.",
              file=sys.stderr)
    print(json.dumps({"output": str(path), "duration_s": got["duration"], "resolve_uploaded_to_youtube": uploaded},
                     indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("snapshot", "create", "stills", "render"):
        p = sub.add_parser(n)
        p.add_argument("spec")
        p.add_argument("--project", required=True, help="the Resolve project that holds the long-form edit")
        p.add_argument("--out-dir")
        if n == "create":
            p.add_argument("--long-timeline", required=True, help="the long-form timeline the master was rendered from")
            p.add_argument("--name", help="new timeline name (must start with 'short')")
            p.add_argument("--offset", type=float, default=0.0,
                           help="seconds into the long-form timeline where the master render starts")
            p.add_argument("--dry-run", action="store_true", help="map and print the placements, change nothing")
            p.add_argument("--prepare-only", action="store_true",
                           help="only render the audio WAV and caption overlay; do not contact Resolve")
        if n in ("stills", "render"):
            p.add_argument("--name", required=True)
        if n == "stills":
            p.add_argument("seconds", nargs="+", type=float)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    try:
        return {"snapshot": cmd_snapshot, "create": cmd_create, "stills": cmd_stills, "render": cmd_render}[a.cmd](a, spec)
    except sl.settings.SettingMissing as e:
        sl.settings.exit_missing(e)


if __name__ == "__main__":
    sys.exit(main())
