"""Shared helpers for the broll-brick-layer scripts.

Pure helpers (timecode, slugs, never-touch rule, work folders) import nothing
from Resolve, so the audits' math can be tested without it. Resolve helpers
connect lazily through vidkit.resolve (DaVinci Resolve Studio, running).
"""
from __future__ import annotations

import functools
import glob
import os
import re
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[4] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from vidkit import media, settings  # noqa: E402

# The video track the bricks go on, found BY NAME (never by position: an empty
# track above it or a single-camera layout makes position lie).
BRICK_TRACK = "B-roll bricks"


def log(*a):
    print(*a, file=sys.stderr)


# ---- pure helpers ----------------------------------------------------------

def tc(frame, fps):
    """Resolve-style timecode. The frame base is the ROUNDED rate (24 for
    23.976, non-drop), which is what Resolve's timecode field shows."""
    base = max(1, round(float(fps)))
    s, ff = divmod(int(frame), base)
    return "%02d:%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60, ff)


def slugify(name):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (name or "").lower())).strip("-") or "unnamed"


def never_touch_list(extra=()):
    """Timeline names no script may read from or write to: the user's list in
    settings (editor.never_touch_timelines) plus a plan's own list."""
    names = settings.get("editor.never_touch_timelines", default=[]) or []
    if isinstance(names, str):
        names = [names]
    return list(names) + list(extra or [])


def is_protected(name, extra=()):
    """Backups (any timeline with 'backup' in its name) and never-touch timelines."""
    n = (name or "").lower()
    if "backup" in n or "(bak" in n or n.endswith(" bak"):
        return True
    return name in never_touch_list(extra)


def refuse_protected(name, extra=()):
    if is_protected(name, extra):
        sys.exit(f"refusing: timeline {name!r} is a backup or on the never-touch list "
                 f"(settings editor.never_touch_timelines). Work on another timeline.")


def work_dir(project_name, sub=""):
    """Scratch folder for one Resolve project: <project>/<work>/broll-brick-layer
    when the Resolve project name matches a folder under paths.projects_dir,
    else <cache_dir>/broll-brick-layer/<slug>. Absolute (Resolve resolves
    export paths in its own process)."""
    base = None
    try:
        root = settings.get_path("paths.projects_dir")
    except Exception:
        root = None
    if root and project_name and (root / project_name).is_dir():
        base = root / project_name / settings.layout("work") / "broll-brick-layer"
    if base is None:
        base = settings.cache_dir("broll-brick-layer") / slugify(project_name)
    d = base / sub if sub else base
    d.mkdir(parents=True, exist_ok=True)
    return str(d.resolve())


def prune_scratch(d, keep_days, keep_newest=True):
    """Age restore points (and the Fusion comps beside them) out of a scratch
    dir. The newest restore point is always kept. keep_days=0 disables."""
    if not keep_days or not os.path.isdir(d):
        return []
    cutoff = time.time() - keep_days * 86400
    restores = sorted(glob.glob(os.path.join(d, "restore_*.json")), key=os.path.getmtime)
    if keep_newest:
        restores = restores[:-1]
    victims = [p for p in restores + glob.glob(os.path.join(d, "*.comp")) if os.path.getmtime(p) < cutoff]
    for p in victims:
        try:
            os.remove(p)
        except OSError:
            pass
    return victims


@functools.lru_cache(None)
def native_fps_of_path(path):
    """The media FILE's real frame rate (ffprobe). Plan and annotation seconds
    are always native real-time seconds, even for a clip conformed in Resolve."""
    try:
        return media.probe(path).get("fps_float")
    except SystemExit:
        return None


# ---- Resolve helpers (need DaVinci Resolve Studio running) ----------------

def vr():
    from vidkit import resolve as _vr
    return _vr


def open_project(name):
    """(pm, project): connect and load `name`, reusing it if already open."""
    resolve = vr().connect()
    pm = resolve.GetProjectManager()
    if not name:
        proj = pm.GetCurrentProject()
        if proj is None:
            sys.exit("no project is open in Resolve; pass --project")
        return pm, proj
    return pm, vr().get_project(pm, name)


def timeline_by_name(proj, name):
    tls = list(vr().timelines(proj))
    for t in tls:
        if t.GetName() == name:
            return t
    sys.exit(f"timeline {name!r} not found. Available: {[t.GetName() for t in tls]}")


def fps_of(tl):
    return float(tl.GetSetting("timelineFrameRate"))


def delete_clips(tl, items):
    return vr().delete_clips_checked(tl, items)


def native_fps(mpi):
    path = mpi.GetClipProperty("File Path") or ""
    fps = native_fps_of_path(path) if path else None
    if not fps:
        try:
            fps = float(mpi.GetClipProperty("FPS"))
        except (TypeError, ValueError):
            fps = None
    return fps


def find_brick_track(tl, name=BRICK_TRACK, explicit=False):
    """Index of the brick track, by name. None when there is none.

    An explicit --track-name that is missing aborts. With the default name,
    a single other track whose name says b-roll is accepted; no such track
    means the timeline has no bricks yet (an a-roll fresh from aroll-draft)."""
    if not name:
        return None
    n = tl.GetTrackCount("video")
    names = {i: (tl.GetTrackName("video", i) or "") for i in range(1, n + 1)}
    for i, nm in names.items():
        if nm == name:
            return i
    if explicit:
        sys.exit(f"video track {name!r} not found (tracks: {list(names.values())}). "
                 f"Name the brick track with --track-name, or pass --track-name '' for none.")
    like = [i for i, nm in names.items() if re.search(r"b[\s_-]?roll", nm, re.I)]
    if len(like) == 1:
        log(f"brick track: using V{like[0]} {names[like[0]]!r} (no track named {name!r})")
        return like[0]
    if len(like) > 1:
        sys.exit(f"several tracks look like b-roll ({[names[i] for i in like]}); pass --track-name")
    log(f"no brick track on this timeline (no track named {name!r}); treating every track as a-roll")
    return None
