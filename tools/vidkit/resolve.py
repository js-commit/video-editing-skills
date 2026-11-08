"""Shared DaVinci Resolve scripting helpers (needs DaVinci Resolve Studio:
the free version does not allow external scripting).

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tools"))
    from vidkit.resolve import connect, get_timeline, parse_fps, pool_by_path, tc, log

Enable scripting once in Resolve: Preferences > System > General >
"External scripting using" = Local. Resolve must be running.

Learned limits of the scripting API (Resolve 19-21): no trim/move/slip
setters on timeline items (rebuild from MediaPool.AppendToTimeline clipInfos
instead), no true multicam clip creation, DeleteClips only works on the Edit
page, and every call is a cross-process RPC (batch appends into one call).
"""
import os
import platform
import sys
from fractions import Fraction


def _module_dirs():
    env = os.environ.get("RESOLVE_SCRIPT_API")
    dirs = [os.path.join(env, "Modules")] if env else []
    system = platform.system()
    if system == "Darwin":
        dirs.append("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/")
    elif system == "Windows":
        pd = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        dirs.append(os.path.join(pd, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"))
    else:
        dirs += ["/opt/resolve/Developer/Scripting/Modules/", "/home/resolve/Developer/Scripting/Modules/"]
    return dirs


for _d in _module_dirs():
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.append(_d)


def resolve_installed():
    """True when Resolve's scripting module can be found on this machine."""
    return any(os.path.isfile(os.path.join(d, "DaVinciResolveScript.py")) for d in _module_dirs())


def launch_hint():
    system = platform.system()
    if system == "Darwin":
        return "open -a 'DaVinci Resolve' and wait ~25 s (the process is named Resolve)"
    if system == "Windows":
        return "start DaVinci Resolve from the Start menu and wait ~25 s"
    return "start /opt/resolve/bin/resolve and wait ~25 s"


# Must exceed the ~25s a freshly launched Resolve needs before its scripting
# server answers, or the watchdog kills a healthy just-launched app.
CONNECT_TIMEOUT_S = 30


def log(*a):
    print(*a, file=sys.stderr)


_RESOLVE = None


def connect(timeout_s=CONNECT_TIMEOUT_S):
    """Connect to Resolve, failing fast instead of hanging forever.

    scriptapp() blocks in native code when Resolve's scripting server
    wedges (happens after long sessions, no dialog visible), so a signal
    handler never runs — a watchdog thread is the only thing that can
    still bail out.

    The handle is cached per process so helpers can call connect()
    themselves without paying another attach.
    """
    global _RESOLVE
    if _RESOLVE is not None:
        return _RESOLVE
    import threading
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        sys.exit("DaVinci Resolve's scripting module was not found. Is DaVinci Resolve installed? "
                 "Set RESOLVE_SCRIPT_API to its Developer/Scripting folder if it lives somewhere unusual.")
    done = threading.Event()

    def watchdog():
        if not done.wait(timeout_s):
            log(f"ERROR: Resolve scripting server not responding within "
                f"{timeout_s}s — known wedge: save your work and relaunch "
                f"Resolve, then re-run. If Resolve isn't running: {launch_hint()}.")
            os._exit(3)

    threading.Thread(target=watchdog, daemon=True).start()
    resolve = dvr.scriptapp("Resolve")
    done.set()
    if resolve is None:
        sys.exit("Cannot connect to DaVinci Resolve. Is it running? "
                 f"({launch_hint()}. External scripting must be enabled in "
                 "Preferences > System > General, and it needs DaVinci "
                 "Resolve Studio: the free version blocks external scripts.)")
    _RESOLVE = resolve
    return resolve


def delete_clips_checked(tl, items, ripple=False):
    """Timeline.DeleteClips, guarded against the Edit-page gate.

    DeleteClips returns False and deletes nothing while the UI sits on
    another page (a page gate, not a lock: retries on another page all fail,
    one OpenPage("edit") fixes it). A first attempt has also been seen
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


def parse_fps(fps_str):
    f = float(fps_str)
    for whole, num in ((24, 24000), (30, 30000), (60, 60000)):
        if abs(f - whole * 1000 / 1001) < 0.01:
            return Fraction(num, 1001)
    return Fraction(fps_str)



RESOLVE_RATES = ["23.976", "24", "25", "29.97", "30", "47.952", "48", "50", "59.94", "60"]


def snap_rate(fps_float):
    """A frame rate as the string Resolve's timelineFrameRate takes (None for None)."""
    if not fps_float:
        return None
    best = min(RESOLVE_RATES, key=lambda r: abs(float(r) - fps_float))
    return best if abs(float(best) - fps_float) < 0.02 else str(round(fps_float, 3))


def media_rate(path):
    """A media file's frame rate (ffprobe), snapped to a Resolve rate; None if unreadable."""
    from . import media
    try:
        return snap_rate(media.probe(path).get("fps_float"))
    except (SystemExit, Exception):
        return None


def job_fps(job, media_path=None):
    """The job's "fps", else the frame rate of media_path (default: the first
    sequence item's media). Exits asking for "fps" rather than guessing one."""
    if job.get("fps"):
        return str(job["fps"])
    if media_path is None:
        seq = job.get("sequence") or []
        media_path = seq[0].get("media") if seq else None
    rate = media_rate(media_path) if media_path else None
    if not rate:
        sys.exit(f'could not read the frame rate of {media_path!r}: add "fps" (e.g. "29.97") to the job')
    return rate

def tc(frames, fps):
    # Resolve timecode is integer-base (24 for 23.976, non-drop): the
    # timeline start 86400 displays as 01:00:00:00. Dividing by the real
    # fps instead drifts ~4s/70min and points verification at the wrong
    # segment.
    base = round(float(fps))
    s, f = divmod(int(frames), base)
    return "%02d:%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60, f)


def get_project(pm, name):
    """Return the named project, reusing it if already open."""
    cur = pm.GetCurrentProject()
    if cur and cur.GetName() == name:
        return cur
    project = pm.LoadProject(name)
    if not project:
        sys.exit(f"could not load project {name!r}")
    return project


def timelines(project):
    for i in range(1, (project.GetTimelineCount() or 0) + 1):
        t = project.GetTimelineByIndex(i)
        if t:
            yield t


def protected_timeline(name, extra=()):
    """Why a script must not change timeline `name`, or None: a restore point
    ("backup" in the name), the user's settings editor.never_touch_timelines, or
    a job's own never_touch list."""
    n = (name or "").lower()
    if "backup" in n or "(bak" in n or n.endswith(" bak"):
        return "it is a backup (restore point)"
    from vidkit import settings
    user = settings.get("editor.never_touch_timelines", default=[]) or []
    if isinstance(user, str):
        user = [user]
    if name in user:
        return "it is on settings editor.never_touch_timelines"
    if name in (extra or []):
        return "it is on the job's never_touch list"
    return None


def check_never_touch(job, name):
    why = protected_timeline(name, job.get("never_touch", []))
    if why:
        sys.exit(f"refusing: timeline {name!r}: {why}. Work on another timeline.")


def get_timeline(job):
    """Connect, load the job's project, and make its timeline current.

    Refuses timelines on the job's never_touch list. Returns
    (pm, project, timeline). Skips the project load / timeline scan when
    they are already current (the angle workflow runs many subcommands
    back to back).
    """
    resolve = connect()
    pm = resolve.GetProjectManager()
    project = get_project(pm, job["project"])
    name = job["timeline"]
    check_never_touch(job, name)
    timeline = project.GetCurrentTimeline()
    if not timeline or timeline.GetName() != name:
        timeline = next((t for t in timelines(project)
                         if t.GetName() == name), None)
        if timeline is None:
            sys.exit(f"timeline {name!r} not found")
        project.SetCurrentTimeline(timeline)
    return pm, project, timeline


def resolve_window_id():
    """CGWindowID of Resolve's largest window, or None.

    macOS only (None elsewhere). Lets verification screenshots use
    `screencapture -l <id>` instead of activate + full-screen: activating
    Resolve steals focus from whatever the user is typing in, and a
    full-screen shot captures the frontmost app. The window server renders backgrounded windows (playhead moves
    included), so -l captures the correct frame without focus.

    Shells out to `swift -e` because system python3 has no Quartz module;
    first run pays a few seconds of compile time.
    """
    import subprocess
    if platform.system() != "Darwin":
        return None
    snippet = """
import CoreGraphics
if let wins = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID)
        as? [[String: Any]] {
    var best = (id: -1, area: 0)
    for w in wins {
        let owner = w["kCGWindowOwnerName"] as? String ?? ""
        guard owner.contains("Resolve") else { continue }
        let b = w["kCGWindowBounds"] as? [String: Any] ?? [:]
        let area = (b["Width"] as? Int ?? 0) * (b["Height"] as? Int ?? 0)
        if area > best.area { best = (w["kCGWindowNumber"] as? Int ?? -1, area) }
    }
    if best.id > 0 { print(best.id) }
}
"""
    try:
        out = subprocess.run(["swift", "-e", snippet], capture_output=True,
                             text=True, timeout=90).stdout.strip()
        return int(out) if out else None
    except Exception as e:
        log(f"resolve_window_id failed ({e}); falling back to full-screen")
        return None


def media_seconds(path):
    """Duration of a media file in seconds, via ffprobe."""
    import subprocess
    from vidkit import media
    out = subprocess.run(
        [media.ffprobe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit(f"ffprobe failed on {path}: {out.stderr.strip()}")
    return float(out.stdout.strip())


def duplicate_timeline(project, timeline, name):
    """DuplicateTimeline, undoing its make-the-copy-current side effect.

    Returns the duplicate (or None on failure) with the original timeline
    left current — naming/collision policy stays at the call site.
    """
    dup = timeline.DuplicateTimeline(name)
    if dup:
        project.SetCurrentTimeline(timeline)
    return dup


def ensure_resolution(project, timeline, width=None, height=None):
    """Set the timeline's resolution (default: settings editor.timeline_resolution,
    e.g. "3840x2160"; edit at full resolution, render drafts smaller). A new
    timeline takes the project's resolution; when that differs, set it on the
    project if this is the project's only timeline, else on this timeline alone
    (custom settings): flipping the project setting resizes every timeline that
    follows it."""
    if width is None or height is None:
        try:
            from vidkit import settings
            res = settings.get("editor.timeline_resolution", default="3840x2160")
        except Exception:
            res = "3840x2160"
        width, height = (int(x) for x in str(res).lower().split("x"))
    want = (str(width), str(height))
    size = lambda: (timeline.GetSetting("timelineResolutionWidth"), timeline.GetSetting("timelineResolutionHeight"))
    if size() == want:
        return
    if (project.GetTimelineCount() or 0) == 1:
        project.SetSetting("timelineResolutionWidth", want[0]); project.SetSetting("timelineResolutionHeight", want[1])
    if size() != want:
        for k, v in (("useCustomSettings", "1"), ("timelineResolutionWidth", want[0]), ("timelineResolutionHeight", want[1])):
            timeline.SetSetting(k, v)
    if size() != want:
        sys.exit(f"timeline {timeline.GetName()!r} is {'x'.join(size())}, not {width}x{height}: Resolve refused the size")
    log(f"timeline {timeline.GetName()!r} -> {width}x{height}")


def pool_by_path(root):
    by_path = {}

    def walk(folder):
        for clip in folder.GetClipList() or []:
            p = clip.GetClipProperty("File Path")
            if p:
                by_path[p] = clip
        for sub in folder.GetSubFolderList() or []:
            walk(sub)

    walk(root)
    return by_path


def resolve_log_path():
    """Resolve's main log file on this OS (it records its own YouTube upload jobs)."""
    from pathlib import Path
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve/logs/davinci_resolve.log"
    if platform.system() == "Windows":
        return (Path(os.environ.get("APPDATA", "")) / "Blackmagic Design" / "DaVinci Resolve" / "Support"
                / "logs" / "davinci_resolve.log")
    return Path.home() / ".local/share/DaVinciResolve/logs/davinci_resolve.log"


def youtube_upload_logged(path):
    """Did Resolve log a YouTube upload job for this rendered file? Resolve's
    "Upload directly to YouTube" box can stay on for a whole app session after
    any YouTube preset was used, and the scripting API can neither read nor
    clear it, so its log is the only witness."""
    try:
        with open(resolve_log_path(), errors="replace") as fh:
            tail = fh.readlines()[-4000:]
    except OSError:
        return False
    base = os.path.basename(str(path))
    return any("WebUploader" in ln and base in ln for ln in tail)
