#!/usr/bin/env python3
"""Build a two-camera A/B comparison project in DaVinci Resolve.

Creates a fresh project with one 4K timeline of side-by-side segments:
left clip on V1, right clip on V2, title overlay stills on V3. Each video
pair is followed by a freeze-frame "punch-in" segment (pre-extracted stills
at extra zoom), then still-pair segments (photos). Vertical sources are
zoomed to fill their half of the frame (center crop).

Everything is driven by a job JSON:

  {
    "project": "my-ab-project",
    "timeline": "AB-comparison",      # optional; several jobs may share one
                                      # project, one timeline each (like
                                      # Premiere sequences)
    "width": 3840, "height": 2160, "fps": 30,
    "segments": [
      {"kind": "video", "left": "/abs/l.mp4", "right": "/abs/r.mp4",
       "left_trim_s": 0.0, "right_trim_s": 1.0,   # head trims (start align)
       "max_dur_s": 23.0,                         # optional tail cap
       "left_win": [960, 0, 1920, 2160],          # optional source window,
       "right_win": [928, 0, 1920, 2160],         #   (sx0, sy0, sw, sh) in
       "win_mode": "fill",                        #   DISPLAY px; see
       "title": "/abs/title.mov"},                #   window_transform()
      {"kind": "still", "file": "/abs/composite.png"},
      ...
    ]
  }

kind=video: both clips trimmed by *_trim_s at the head and cut to the common
remaining duration (minus a small safety margin). Audio comes from the LEFT
clip only; the right clip is appended video-only. "title" is a frame-size
overlay VIDEO with alpha (e.g. transparent ProRes 4444) at the timeline fps,
at least as long as the segment — it is trimmed to the exact segment length
(video clips trim reliably; Resolve pins STILLS to the project's default
still length and ignores their endFrame, which is why titles are movs).
kind=still: one pre-composited full-frame image shown for Resolve's default
still duration (5 s). Compose side-by-side/punch-in still segments with
ffmpeg beforehand — pixel-exact and immune to still-handling quirks.

left_win/right_win give each side an explicit source window (Crop + Zoom +
Pan) instead of the default half-fill zoom. That is what makes LANDSCAPE
pairs and punch-ins work on the original camera files, with no pre-cropped
ProRes intermediates and every segment still tweakable in the Edit page.
See window_transform() for the measured Resolve geometry.

Layout notes learned the hard way (Resolve 21):
- GetClipProperty("Resolution") reports the DISPLAY (rotation-applied)
  resolution for phone video, so no rotation handling is needed.
- Item zoom scales about the panned image center: a half-frame clip zoomed
  past its half spills across the seam. Fill exactly (zoom makes displayed
  width == half) or pre-compose.

Usage:
  build_ab_project.py create job.json [--fresh]   # build project + timeline
  build_ab_project.py inspect job.json            # dump imported clip props
  build_ab_project.py stills job.json OUTDIR T [T ...]   # grab stills at
                                                  # timeline seconds T for review
  build_ab_project.py render job.json OUTDIR NAME # render (explicit settings,
                                                  # NO preset -> no upload path)

Resolve (Studio) must be running. `create` on an existing project (without
--fresh) reuses it: media already in the pool is not re-imported, and only
the job's named timeline is deleted and rebuilt — other timelines are left
alone. --fresh deletes the WHOLE project named in the job JSON first, after
exporting it to <job dir>/resolve-backups/<name>-<time>.drp (no backup, no delete).
`stills` and `render` operate on the job's named timeline.
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools"))
import vidkit.resolve  # noqa: E402,F401  (puts Resolve's scripting module on sys.path for macOS, Windows, Linux)

TIMELINE_NAME = "AB-comparison"   # default; override with "timeline" in the job JSON
SAFETY_S = 0.15          # shaved off each video pair's common duration
TITLE_TRACK = 3


_RESOLVE = None


def connect(timeout_s=30):
    """Attach to Resolve, failing fast instead of hanging forever.

    scriptapp() blocks in native code when Resolve's scripting server
    wedges (long sessions, no dialog visible), so signal handlers never
    run — only a watchdog thread can still bail out. Timeout exceeds the
    ~25s a freshly launched Resolve needs before its server answers.

    The handle is cached per process so helpers can call connect()
    themselves without paying another attach.
    """
    global _RESOLVE
    if _RESOLVE is not None:
        return _RESOLVE
    import threading
    import DaVinciResolveScript as dvr
    done = threading.Event()

    def watchdog():
        if not done.wait(timeout_s):
            print(f"ERROR: Resolve scripting server not responding within "
                  f"{timeout_s}s — known wedge: save your work and relaunch "
                  f"Resolve, then re-run.", file=sys.stderr)
            os._exit(3)

    threading.Thread(target=watchdog, daemon=True).start()
    resolve = dvr.scriptapp("Resolve")
    done.set()
    if resolve is None:
        sys.exit("Cannot connect to DaVinci Resolve. Is it running? "
                 "(open -a 'DaVinci Resolve'; wait ~25s. When checking, "
                 "the process is named `Resolve`, not `DaVinci Resolve`.)")
    _RESOLVE = resolve
    return resolve


def delete_clips_checked(tl, items, ripple=False):
    """Timeline.DeleteClips, guarded against the Edit-page gate.

    DeleteClips returns False and deletes nothing while the UI sits on
    another page (measured upstream on Studio 21: three retries against
    132 valid items all False on Fairlight; one OpenPage("edit") then
    True — a page gate, not a lock). A first attempt has also been seen
    to fail once where an immediate retry succeeded, so try twice.
    """
    if not items:
        return True
    resolve = connect()
    prev = resolve.GetCurrentPage()
    if prev != "edit":
        resolve.OpenPage("edit")
    try:
        for _ in range(2):
            if tl.DeleteClips(items, ripple):
                return True
        return False
    finally:
        if prev and prev != "edit":
            resolve.OpenPage(prev)


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json", "-show_entries",
         "format=duration", path], capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def verify_render_output(path, expected_s, fw, fh):
    """Assert the rendered file is complete, has video, and is fw x fh.

    SetRenderSettings applies ON TOP of whatever Deliver-page state a
    loaded preset left behind, and that base state is unreadable (the API
    has no GetRenderSettings) — measured upstream: an 'Audio Only' base
    produced a video-less mp4 while the queued job read back
    IsExportVideo=True. The rendered file is the only witness that video
    was actually exported. One ffprobe covers duration and the stream;
    returns the actual duration for the caller's report.
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-of", "json",
         "-show_entries", "format=duration:stream=width,height", path],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    actual = float(info["format"]["duration"])
    if abs(actual - expected_s) > 1.0:
        sys.exit(f"RENDER INCOMPLETE: {actual:.1f}s on disk vs "
                 f"{expected_s:.1f}s expected")
    streams = info.get("streams") or []
    if not streams:
        sys.exit("RENDER FAILED: no video stream in the output — the Deliver "
                 "page held an audio-only base state (see verify_render_output)")
    got = (int(streams[0].get("width") or 0), int(streams[0].get("height") or 0))
    if got != (fw, fh):
        sys.exit(f"RENDER FAILED: output is {got[0]}x{got[1]}, wanted {fw}x{fh}")
    return actual


def clip_fps(mpi):
    try:
        return float(mpi.GetClipProperty("FPS"))
    except (TypeError, ValueError):
        return 0.0


def import_all(mp, job):
    """Import every file referenced by the job into per-role bins.

    Returns {abs_path: MediaPoolItem}."""
    root = mp.GetRootFolder()
    paths = {"left": set(), "right": set(), "titles": set(), "comps": set()}
    for seg in job["segments"]:
        if seg["kind"] == "still":
            paths["comps"].add(seg["file"])
        else:
            paths["left"].add(seg["left"])
            paths["right"].add(seg["right"])
            paths["titles"].add(seg["title"])
    paths = {k: v for k, v in paths.items() if v}

    # Reuse clips already in the pool (second timeline in an existing
    # project): re-importing the same path would duplicate pool entries.
    by_path = {}

    def walk(folder):
        for clip in folder.GetClipList() or []:
            p = clip.GetClipProperty("File Path")
            if p:
                by_path[p] = clip
        for sub in folder.GetSubFolderList() or []:
            walk(sub)

    walk(root)
    existing_bins = {f.GetName(): f for f in root.GetSubFolderList() or []}
    for bin_name, group in sorted(paths.items()):
        need = sorted(group - set(by_path))
        if not need:
            continue
        folder = existing_bins.get(bin_name) or mp.AddSubFolder(root, bin_name)
        if folder is None:
            sys.exit(f"AddSubFolder({bin_name!r}) failed")
        mp.SetCurrentFolder(folder)
        items = mp.ImportMedia(need) or []
        for it in items:
            p = it.GetClipProperty("File Path")
            if p:
                by_path[p] = it
        missing = group - set(by_path)
        if missing:
            sys.exit(f"ImportMedia dropped {len(missing)} file(s) in {bin_name}: "
                     f"{sorted(missing)[:3]}")
    mp.SetCurrentFolder(root)
    return by_path


def fit_width(mpi, frame_w, frame_h):
    """Displayed width (timeline px) at zoom 1.0 under scale-to-fit.

    GetClipProperty("Resolution") is the display resolution (rotation from
    phone metadata already applied), so it can be used directly."""
    w, h = clip_size(mpi)
    fit = min(frame_w / w, frame_h / h)
    return w * fit, h * fit


def half_fill_zoom(mpi, frame_w, frame_h):
    """Zoom that makes the clip fill a (frame_w/2 x frame_h) half."""
    disp_w, disp_h = fit_width(mpi, frame_w, frame_h)
    return max((frame_w / 2) / disp_w, frame_h / disp_h)


def pan_units(mpi, frame_w, frame_h, shift_px):
    """Convert a desired horizontal shift in timeline pixels to Resolve's
    Pan property units.

    Measured empirically (Resolve 21): the rendered shift equals
    Pan * (zoom-1 fitted width / frame width), independent of ZoomX. So a
    portrait clip fitted to 1215 px on a 3840 px timeline moves only
    ~0.316 px per Pan unit."""
    disp_w, _ = fit_width(mpi, frame_w, frame_h)
    return shift_px * frame_w / disp_w


def set_transform(item, zoom, pan):
    ok = True
    ok &= item.SetProperty("ZoomX", zoom)
    ok &= item.SetProperty("ZoomY", zoom)
    ok &= item.SetProperty("Pan", pan)
    return ok


def clip_size(mpi):
    res = mpi.GetClipProperty("Resolution")
    w, h = (int(x) for x in res.split("x"))
    return w, h


def window_transform(mpi, frame_w, frame_h, win, target_cx, target_cy,
                     target_w, target_h, mode="fill"):
    """Place a SOURCE-pixel window into a target rect using Crop + Zoom + Pan.

    `win` is (sx0, sy0, sw, sh) in the clip's DISPLAY pixel space (the same
    space GetClipProperty("Resolution") reports, i.e. phone rotation already
    applied). mode="fill" scales the window to cover the target rect exactly
    (use a window with the target's aspect ratio); mode="fit" scales it to
    sit inside the rect, letter/pillarboxed.

    Why crop at all: a landscape source on a same-aspect timeline is already
    full width at zoom 1.0, so zooming to fill a half spills across the
    centre seam and covers the other clip. Cropping first, in fitted pixels,
    keeps each side inside its half at native 1:1 - and needs no pre-rendered
    intermediates, so the result stays tweakable in the Edit page.

    Measured on Resolve 21 (verify_geometry.py re-measures it):
      - Crop* are in TIMELINE pixels of the scale-to-fit image, applied
        BEFORE Zoom (crop 1440/1440 + 540/540 then zoom 2.0 gives exactly a
        960x1080 source window blown up 2x).
      - Zoom scales about the FRAME centre.
      - Pan  = +1 px/unit * (fitted_w / frame_w)   (positive -> right)
      - Tilt = -1 px/unit * (fitted_h / frame_h)   (positive -> up)
      - On a rotation-90 phone clip the HORIZONTAL crop edges are swapped:
        CropLeft trims the display-RIGHT edge and vice versa. Vertical edges
        are unaffected. Keyed off display aspect, which is what was measured.
    """
    W, H = clip_size(mpi)
    fit = min(frame_w / W, frame_h / H)
    w0, h0 = W * fit, H * fit
    sx0, sy0, sw, sh = win
    pick = min if mode == "fit" else max
    zoom = pick(target_w / (fit * sw), target_h / (fit * sh))

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
    crops = {"CropLeft": crop_r if rotated else crop_l,
             "CropRight": crop_l if rotated else crop_r,
             "CropTop": crop_t, "CropBottom": crop_b}
    return zoom, pan, tilt, crops


def apply_window(item, mpi, frame_w, frame_h, win, target_cx, mode, label):
    """Put `win` into the half centred on target_cx; warn (as `label`) about
    windows the transform cannot place faithfully. Returns refused props."""
    W, H = clip_size(mpi)
    sx0, sy0, sw, sh = win
    if sx0 < 0 or sy0 < 0 or sx0 + sw > W or sy0 + sh > H:
        print(f"WARNING {label}: window {win} exceeds the {W}x{H} source - "
              f"crops go negative and the pan lands off-target; clamp the "
              f"window inside the clip", file=sys.stderr)
    if mode == "fill":
        aspect = (sw / sh) / ((frame_w / 2) / frame_h)
        if abs(aspect - 1) > 0.01:
            print(f"WARNING {label}: fill window {win} is {aspect:.2f}x the "
                  f"half's aspect - the overflow spills across the centre "
                  f"seam", file=sys.stderr)
    zoom, pan, tilt, crops = window_transform(
        mpi, frame_w, frame_h, win, target_cx, frame_h / 2,
        frame_w / 2, frame_h, mode)
    props = {"ZoomX": zoom, "ZoomY": zoom, "Pan": pan, "Tilt": tilt}
    props.update(crops)
    return [k for k, v in props.items() if not item.SetProperty(k, v)]


def append_one(mp, tl, info, expect=1):
    added = mp.AppendToTimeline([info]) or []
    if len(added) != expect and not added:
        sys.exit(f"AppendToTimeline failed for {info}")
    return added[0]


def item_len(item):
    d = item.GetDuration()
    if not d:
        try:
            d = item.GetEnd() - item.GetStart()
        except TypeError:
            d = 0
    return d


def load_job(path):
    job = json.load(open(path))
    for seg in job["segments"]:
        keys = ("file",) if seg["kind"] == "still" else ("left", "right", "title")
        for k in keys:
            if not os.path.exists(seg[k]):
                sys.exit(f"missing file: {seg[k]}")
    return job


def get_project(resolve, job, must_exist):
    pm = resolve.GetProjectManager()
    name = job["project"]
    if must_exist:
        proj = pm.LoadProject(name)
        if proj is None:
            sys.exit(f"Project {name!r} not found; run create first.")
        return pm, proj
    return pm, None


def select_timeline(proj, job):
    """Make the job's named timeline current (projects can hold several)."""
    want = job.get("timeline", TIMELINE_NAME)
    for i in range(1, (proj.GetTimelineCount() or 0) + 1):
        tl = proj.GetTimelineByIndex(i)
        if tl and tl.GetName() == want:
            proj.SetCurrentTimeline(tl)
            return tl
    sys.exit(f"Timeline {want!r} not found in project {proj.GetName()!r}")


def cmd_create(args):
    job = load_job(args.job)
    fw, fh, fps = job.get("width", 3840), job.get("height", 2160), job.get("fps", 30)

    resolve = connect()
    pm = resolve.GetProjectManager()
    name = job["project"]
    tl_name = job.get("timeline", TIMELINE_NAME)
    existing = pm.GetProjectListInCurrentFolder() or []
    proj = None
    if name in existing:
        if args.fresh:
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(args.job)), "resolve-backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup = os.path.join(backup_dir, f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.drp")
            cur = pm.GetCurrentProject()
            if cur and cur.GetName() == name:
                pm.SaveProject()
                pm.CloseProject(cur)
            if not pm.ExportProject(name, backup, False) or not os.path.exists(backup):
                sys.exit(f"could not back up project {name!r} to {backup}; not deleting it")
            print(f"backed up project {name!r} to {backup}")
            if not pm.DeleteProject(name):
                sys.exit(f"DeleteProject({name!r}) failed")
            print(f"deleted existing project {name!r}")
        else:
            # Reuse the project; only the job's named timeline is (re)built.
            proj = pm.LoadProject(name)
            if proj is None:
                sys.exit(f"LoadProject({name!r}) failed")
            print(f"reusing project {name!r} (rebuilding timeline {tl_name!r})")
    if proj is None:
        proj = pm.CreateProject(name)
        if proj is None:
            sys.exit(f"CreateProject({name!r}) failed")

    for key, val in (("timelineResolutionWidth", str(fw)),
                     ("timelineResolutionHeight", str(fh)),
                     ("timelineFrameRate", str(fps))):
        if not proj.SetSetting(key, val):
            print(f"WARNING: SetSetting({key}, {val}) refused", file=sys.stderr)

    mp = proj.GetMediaPool()
    by_path = import_all(mp, job)

    for i in range(1, (proj.GetTimelineCount() or 0) + 1):
        old = proj.GetTimelineByIndex(i)
        if old and old.GetName() == tl_name:
            if not mp.DeleteTimelines([old]):
                sys.exit(f"DeleteTimelines({tl_name!r}) failed")
            print(f"deleted existing timeline {tl_name!r}")
            break
    tl = mp.CreateEmptyTimeline(tl_name)
    if tl is None:
        sys.exit("CreateEmptyTimeline failed")
    proj.SetCurrentTimeline(tl)
    while tl.GetTrackCount("video") < TITLE_TRACK:
        if not tl.AddTrack("video"):
            sys.exit("AddTrack failed")

    base = tl.GetStartFrame()
    cursor = 0
    report = []
    for i, seg in enumerate(job["segments"]):
        if seg["kind"] == "still":
            item = append_one(mp, tl, {
                "mediaPoolItem": by_path[seg["file"]], "trackIndex": 1,
                "mediaType": 1, "recordFrame": base + cursor,
            })
            length = item_len(item)
            if not length:
                sys.exit(f"seg{i}: still landed with unreadable duration")
            report.append((i, "still", cursor / fps, length / fps,
                           os.path.basename(seg["file"])))
            cursor += length
            continue

        li, ri, ti = by_path[seg["left"]], by_path[seg["right"]], by_path[seg["title"]]
        lfps, rfps = clip_fps(li), clip_fps(ri)
        ldur = ffprobe_duration(seg["left"]) - seg.get("left_trim_s", 0.0)
        rdur = ffprobe_duration(seg["right"]) - seg.get("right_trim_s", 0.0)
        common = min(ldur, rdur) - SAFETY_S
        # optional tail cut (e.g. to keep an off-camera person out of frame)
        if "max_dur_s" in seg:
            common = min(common, seg["max_dur_s"])
        lt, rt = seg.get("left_trim_s", 0.0), seg.get("right_trim_s", 0.0)
        litem = append_one(mp, tl, {
            "mediaPoolItem": li, "trackIndex": 1,
            "startFrame": round(lt * lfps),
            "endFrame": round((lt + common) * lfps) - 1,
            "recordFrame": base + cursor,
        })
        length = item_len(litem)
        # Match the right side to the left's TIMELINE length exactly; source
        # fps differ slightly between the phones, so nudge the source out
        # point until the item durations agree (no 1-frame gap/overlap).
        want_src = round(length * rfps / fps)
        ritem = None
        for _ in range(4):
            info = {"mediaPoolItem": ri, "trackIndex": 2, "mediaType": 1,
                    "startFrame": round(rt * rfps),
                    "endFrame": round(rt * rfps) + want_src - 1,
                    "recordFrame": base + cursor}
            ritem = append_one(mp, tl, info)
            got = item_len(ritem)
            diff = length - got
            if diff == 0:
                break
            if got == 0:
                # ghost append (launch race, see build_short): nothing landed,
                # so a failed delete of the ghost handle is expected —
                # best-effort delete, then retry the same params
                tl.DeleteClips([ritem])
                time.sleep(1.5)
                continue
            if not delete_clips_checked(tl, [ritem]):
                sys.exit(f"seg{i}: could not delete the mis-sized right item "
                         "to retry (DeleteClips failed even on the edit page)")
            want_src += diff if abs(diff) > 1 else (1 if diff > 0 else -1)
        if item_len(ritem) != length:
            print(f"WARNING seg{i}: right is {item_len(ritem)} frames vs "
                  f"left {length}", file=sys.stderr)

        # Explicit source windows (Crop+Zoom+Pan, native 1:1, no pre-render)
        # when the job supplies them; plain half-fill zoom otherwise.
        mode = seg.get("win_mode", "fill")
        for side, item, mpi, cx, shift in (("left", litem, li, fw / 4, -fw / 4),
                                           ("right", ritem, ri, 3 * fw / 4, fw / 4)):
            if f"{side}_win" in seg:
                bad = apply_window(item, mpi, fw, fh, seg[f"{side}_win"],
                                   cx, mode, f"seg{i} {side}")
                if bad:
                    print(f"WARNING seg{i}: {side} refused {bad}",
                          file=sys.stderr)
            elif not set_transform(item, half_fill_zoom(mpi, fw, fh),
                                   pan_units(mpi, fw, fh, shift)):
                print(f"WARNING seg{i}: {side} transform refused",
                      file=sys.stderr)

        # title overlay: a video clip with alpha, trimmed to the segment
        tfps = clip_fps(ti) or fps
        append_one(mp, tl, {
            "mediaPoolItem": ti, "trackIndex": TITLE_TRACK, "mediaType": 1,
            "startFrame": 0, "endFrame": round(length * tfps / fps) - 1,
            "recordFrame": base + cursor,
        })
        report.append((i, "video", cursor / fps, length / fps,
                       os.path.basename(seg["left"])))
        cursor += length

    pm.SaveProject()
    print(f"project : {name}")
    print(f"timeline: {tl_name}  {cursor} frames = {cursor / fps:.1f}s @ {fps}fps")
    for i, kind, at, dur, left in report:
        print(f"  seg{i:02d} {kind:5s} @ {at:7.2f}s  {dur:6.2f}s  {left}")
    return 0


def cmd_inspect(args):
    job = load_job(args.job)
    resolve = connect()
    pm, proj = get_project(resolve, job, must_exist=True)
    mp = proj.GetMediaPool()

    def walk(folder, acc):
        for clip in folder.GetClipList() or []:
            p = clip.GetClipProperty("File Path")
            if p:
                acc[p] = clip
        for sub in folder.GetSubFolderList() or []:
            walk(sub, acc)

    by_path = {}
    walk(mp.GetRootFolder(), by_path)
    for p, mpi in sorted(by_path.items()):
        print(f"{os.path.basename(p)}\n"
              f"    res={mpi.GetClipProperty('Resolution')} "
              f"fps={mpi.GetClipProperty('FPS')} "
              f"frames={mpi.GetClipProperty('Frames')} "
              f"dur={mpi.GetClipProperty('Duration')}")
    for tname in ("video", "audio"):
        tl = proj.GetCurrentTimeline()
        if tl:
            for i in range(1, tl.GetTrackCount(tname) + 1):
                items = tl.GetItemListInTrack(tname, i) or []
                print(f"{tname} track {i}: {len(items)} items")
    return 0


def cmd_stills(args):
    job = load_job(args.job)
    resolve = connect()
    pm, proj = get_project(resolve, job, must_exist=True)
    tl = select_timeline(proj, job)
    fps = float(tl.GetSetting("timelineFrameRate"))
    os.makedirs(args.outdir, exist_ok=True)
    # ExportCurrentFrameAsStill instead of the Gallery (GrabStill/ExportStills):
    # the gallery path duplicated grabs and sometimes wrote zero files; the
    # direct export writes the exact rendered frame to a deterministic
    # filename. It only works on the edit page (returns False on deliver -
    # measured), so switch and restore.
    prev_page = resolve.GetCurrentPage()
    if prev_page != "edit" and not resolve.OpenPage("edit"):
        sys.exit("OpenPage(edit) refused - stills need the edit page")
    exported = []
    try:
        for t in args.seconds:
            frame = tl.GetStartFrame() + int(float(t) * fps)
            h, rem = divmod(frame, int(fps) * 3600)
            m, rem = divmod(rem, int(fps) * 60)
            s, f = divmod(rem, int(fps))
            tc = f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
            if not tl.SetCurrentTimecode(tc):
                print(f"WARNING: SetCurrentTimecode({tc}) refused",
                      file=sys.stderr)
            # ExportCurrentFrameAsStill exports what the viewer currently
            # SHOWS, which lags the park - without the settle it exported
            # the previous park's frame (identical md5s, measured
            # measured). Poll the readback, then let the viewer render.
            for _ in range(20):
                if tl.GetCurrentTimecode() == tc:
                    break
                time.sleep(0.25)
            time.sleep(1.5)
            path = os.path.abspath(
                os.path.join(args.outdir, f"abcheck_{float(t):g}s.png"))
            if os.path.exists(path):
                os.remove(path)
            if not (proj.ExportCurrentFrameAsStill(path)
                    and os.path.exists(path) and os.path.getsize(path) > 0):
                sys.exit(f"ExportCurrentFrameAsStill failed at {t}s -> {path}")
            exported.append(path)
    finally:
        if prev_page != "edit":
            resolve.OpenPage(prev_page)
    print(f"exported {len(exported)} stills to {args.outdir}")
    return 0


def cmd_render(args):
    job = load_job(args.job)
    resolve = connect()
    pm, proj = get_project(resolve, job, must_exist=True)
    tl = select_timeline(proj, job)
    fw, fh = job.get("width", 3840), job.get("height", 2160)
    os.makedirs(args.outdir, exist_ok=True)

    # Job-scoped queue handling: never DeleteAllRenderJobs() - clearing the
    # queue can cancel someone else's in-flight render/upload job (measured
    # on the shorts skill). Only ever add, start and delete our OWN jobId.
    # Explicit format/codec, deliberately NOT LoadRenderPreset: presets can
    # carry click-only Deliver-page state (e.g. upload-to-YouTube).
    if not proj.SetCurrentRenderFormatAndCodec("mp4", "H265"):
        if not proj.SetCurrentRenderFormatAndCodec("mp4", "H264"):
            sys.exit("Could not set mp4/H265 nor mp4/H264 render format")
    proj.SetRenderSettings({
        "SelectAllFrames": 1,
        "TargetDir": args.outdir,
        "CustomName": args.name,
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": fw,
        "FormatHeight": fh,
        # Restrict-to bitrate in kb/s. 40 Mbps HEVC ~= a mirrorless camera's own
        # camera footage; comfortably above phone-source quality while
        # staying hardware-decodable on playback devices.
        "VideoQuality": 40000,
    })
    job_id = proj.AddRenderJob()
    if not job_id:
        sys.exit("AddRenderJob returned nothing (TargetDir not absolute?)")
    info = next((j for j in proj.GetRenderJobList() or []
                 if j.get("JobId") == job_id), None)
    if info is None:
        sys.exit(f"queued job {job_id} missing from GetRenderJobList")
    print(f"render  : {info['VideoFormat']}/{info['VideoCodec']} "
          f"{info['FormatWidth']}x{info['FormatHeight']} @ {info['FrameRate']} "
          f"frames {info['MarkIn']}-{info['MarkOut']} -> {info['OutputFilename']}")

    proj.StartRendering([job_id], isInteractiveMode=False)
    last = None
    while proj.IsRenderingInProgress():
        st = proj.GetRenderJobStatus(job_id) or {}
        pct = st.get("CompletionPercentage")
        if pct != last:
            print(f"  {pct}%", flush=True)
            last = pct
        time.sleep(5)

    st = proj.GetRenderJobStatus(job_id) or {}
    path = os.path.join(args.outdir, info["OutputFilename"])
    expected = (info["MarkOut"] - info["MarkIn"] + 1) / float(info["FrameRate"])
    if st and st.get("JobStatus") not in ("Complete", None):
        sys.exit(f"RENDER FAILED: {st}")
    if not os.path.exists(path):
        sys.exit(f"RENDER FAILED: no output at {path}")
    actual = verify_render_output(path, expected, fw, fh)
    proj.DeleteRenderJob(job_id)  # tidy only our own, verified-done job
    print(f"done: {path}\nsize: {os.path.getsize(path) / 1e6:.0f} MB  "
          f"duration: {actual:.1f}s (expected {expected:.1f}s)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("job"); c.add_argument("--fresh", action="store_true")
    i = sub.add_parser("inspect"); i.add_argument("job")
    s = sub.add_parser("stills"); s.add_argument("job"); s.add_argument("outdir")
    s.add_argument("seconds", nargs="+", type=float)
    r = sub.add_parser("render"); r.add_argument("job"); r.add_argument("outdir")
    r.add_argument("name")
    args = ap.parse_args()
    # ExportStills/TargetDir run inside the Resolve process, which resolves
    # relative paths against ITS OWN cwd - a relative outdir "succeeds" but
    # the files land somewhere else entirely. Always hand Resolve an abspath.
    if hasattr(args, "outdir"):
        args.outdir = os.path.abspath(args.outdir)
    return {"create": cmd_create, "inspect": cmd_inspect,
            "stills": cmd_stills, "render": cmd_render}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
