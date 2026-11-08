#!/usr/bin/env python3
"""Read-only check of what this computer has, for the setup skill.

    env_check.py          JSON on stdout
    env_check.py --text   a short checklist for people

Looks at: OS and Python, ffmpeg/ffprobe and optional tools (with the install
command for this OS and what each one unlocks), useful ffmpeg filters and
Python modules, DaVinci Resolve (installed? scripting module present?), the
transcription engines (`tools/transcribe.py --check`, if present), the
EditReview app, and the current settings (unset keys, finished/skipped setup
steps) plus suggested default folders. Installs, launches and changes nothing.
Exit 0 always (a missing tool is a finding, not an error).
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402

OS = platform.system()  # Darwin / Windows / Linux

# tool -> (what it unlocks, {os: install command})
OPTIONAL_TOOLS = {
    "ffmpeg": ("everything: cutting, previews, renders, contact sheets (required)", {
        "Darwin": "brew install ffmpeg", "Windows": "winget install --id Gyan.FFmpeg",
        "Linux": "sudo apt install ffmpeg"}),
    "ffprobe": ("reading clip facts (duration, frame rate); comes with ffmpeg (required)", {
        "Darwin": "brew install ffmpeg", "Windows": "winget install --id Gyan.FFmpeg",
        "Linux": "sudo apt install ffmpeg"}),
    "exiftool": ("camera/phone metadata (shooting date, device) for footage sorting and home videos", {
        "Darwin": "brew install exiftool", "Windows": "winget install --id OliverBetz.ExifTool",
        "Linux": "sudo apt install libimage-exiftool-perl"}),
    "yt-dlp": ("downloading music or reference clips you have the rights to use", {
        "Darwin": "brew install yt-dlp", "Windows": "winget install --id yt-dlp.yt-dlp",
        "Linux": "python3 -m pip install --user yt-dlp"}),
    "swiftc": ("changing and rebuilding EditReview or BulkCut (both ship ready to use)", {
        "Darwin": "xcode-select --install"}),
}

PY_MODULES = {
    "numpy": "faster audio analysis (waveform snapping, beat detection)",
    "scipy": "audio analysis helpers",
    "PIL": "thumbnails and image overlays (package name: pillow)",
    "cv2": "frame analysis (package name: opencv-python)",
    "librosa": "music beat and energy analysis for montages",
}
PIP_NAME = {"PIL": "pillow", "cv2": "opencv-python"}

FILTERS = {
    "vidstabdetect": "stabilizing shaky clips",
    "drawtext": "text on contact sheets and titles",
    "subtitles": "burned-in captions",
    "loudnorm": "loudness normalization for YouTube (-14 LUFS)",
    "zscale": "HDR/log to normal (Rec.709) conversion",
}


def package_manager() -> dict:
    found = {m: bool(shutil.which(m)) for m in ("brew", "winget", "apt", "dnf", "pacman", "choco")}
    hint = None
    if OS == "Darwin" and not found["brew"]:
        hint = "Homebrew is not installed; most install commands below use it. Get it from https://brew.sh"
    return {"found": [m for m, ok in found.items() if ok], "hint": hint}


def resolve_info() -> dict:
    info = {"scripting_module": False, "app_found": False, "app_path": None}
    try:
        from vidkit import resolve  # path setup only; does not connect
        info["scripting_module"] = bool(resolve.resolve_installed())
    except Exception as e:  # pragma: no cover
        info["error"] = str(e)
    candidates = {
        "Darwin": ["/Applications/DaVinci Resolve/DaVinci Resolve.app",
                   "/Applications/DaVinci Resolve Studio/DaVinci Resolve.app"],
        "Windows": [os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                                 "Blackmagic Design", "DaVinci Resolve", "Resolve.exe")],
        "Linux": ["/opt/resolve/bin/resolve"],
    }.get(OS, [])
    for c in candidates:
        if os.path.exists(c):
            info["app_found"], info["app_path"] = True, c
            break
    info["installed"] = info["app_found"] or info["scripting_module"]
    info["note"] = ("Free and Studio look the same from here: ask which one. Automation needs Studio with "
                    "Preferences > System > General > External scripting using = Local.")
    return info


def transcription_info() -> dict:
    script = REPO / "tools" / "transcribe.py"
    if not script.is_file():
        return {"available": False, "note": "tools/transcribe.py is not in this copy; skip the engine question "
                                            "(skills ask when they first need a transcript)."}
    try:
        r = subprocess.run([sys.executable, "-B", str(script), "--check"], capture_output=True,
                           text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return {"available": True, "check_ok": False, "note": "transcribe.py --check timed out"}
    out = {"available": True, "check_ok": r.returncode == 0, "exit_code": r.returncode}
    try:
        out["report"] = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        out["report_text"] = (r.stdout.strip() or r.stderr.strip())[-3000:]
    return out


def vision_info() -> dict:
    script = REPO / "tools" / "vlm-describe" / "vlm_describe.py"
    if not script.is_file():
        return {"available": False, "note": "tools/vlm-describe is not in this copy"}
    try:
        r = subprocess.run([sys.executable, "-B", str(script), "--check"], capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return {"available": False, "note": "vlm_describe.py --check failed"}


def editreview_info() -> dict:
    app_dir = REPO / "apps" / "edit-review"
    info = {"source_present": app_dir.is_dir(), "build_script": None, "built_app": None,
            "can_build": OS == "Darwin" and bool(shutil.which("swiftc"))}
    if app_dir.is_dir():
        for cand in (app_dir / "build.sh", app_dir / "app" / "build.sh"):
            if cand.is_file():
                info["build_script"] = str(cand)
                break
        for app in (app_dir / "build" / "EditReview.app", app_dir / "prebuilt" / "EditReview.app"):
            if app.is_dir():
                info["built_app"] = str(app)
                break
    if OS != "Darwin":
        info["note"] = "EditReview is macOS only; use VLC, your OS player or Resolve to review drafts."
    return info


def suggested_folders() -> dict:
    home = Path.home()
    videos = home / ("Movies" if OS == "Darwin" else "Videos")
    return {
        "paths.projects_dir": str(videos / "VideoProjects"),
        "paths.inbox_dir": str(videos / "VideoInbox"),
        "paths.archive_dir": str(videos / "VideoArchive"),
        "paths.broll_library_dir": str(videos / "BrollLibrary"),
        "paths.music_dir": str(videos / "Music for videos"),
        "paths.home_videos_dir": str(videos / "Home videos"),
        "nas_examples": {"Darwin": "/Volumes/<share>", "Windows": "Z:\\ (a mapped drive)",
                         "Linux": "/mnt/<share>"}.get(OS),
    }


def settings_info() -> dict:
    data = settings.load()
    ob = data.get("onboarding", {})
    prefs = settings.PREFERENCES_PATH
    return {
        "file": str(settings.settings_path()),
        "exists": settings.exists(),
        "unset_keys": settings.unset_keys(data),
        "completed_steps": ob.get("completed_steps", []),
        "skipped_steps": ob.get("skipped_steps", []),
        "last_run": ob.get("last_run"),
        "preferences_file": str(prefs),
        "preferences_exists": prefs.is_file(),
    }


def collect() -> dict:
    tools = {}
    for name, (unlocks, cmds) in OPTIONAL_TOOLS.items():
        if name == "swiftc" and OS != "Darwin":
            continue
        path = shutil.which(name)
        tools[name] = {"installed": bool(path), "unlocks": unlocks,
                       "install": None if path else cmds.get(OS, cmds.get("Linux"))}
    filters = {}
    if tools["ffmpeg"]["installed"]:
        listing = subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-filters"],
                                 capture_output=True, text=True).stdout
        filters = {f: {"present": f" {f} " in listing, "for": why} for f, why in FILTERS.items()}
    mods = {}
    for mod, why in PY_MODULES.items():
        try:
            __import__(mod)
            ok = True
        except Exception:
            ok = False
        mods[mod] = {"installed": ok, "for": why,
                     "install": None if ok else f"{Path(sys.executable).name} -m pip install {PIP_NAME.get(mod, mod)}"}
    encoder = media.h264_encoder() if tools["ffmpeg"]["installed"] else None
    return {
        "os": OS,
        "python": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 9),
        "package_manager": package_manager(),
        "tools": tools,
        "h264_encoder": encoder,
        "ffmpeg_filters": filters,
        "python_modules": mods,
        "resolve": resolve_info(),
        "transcription": transcription_info(),
        "vision": vision_info(),
        "editreview": editreview_info(),
        "settings": settings_info(),
        "suggested": suggested_folders(),
    }


def as_text(r: dict) -> str:
    ok, no = "[ok]", "[--]"
    lines = [f"System: {r['os']}, Python {r['python']}" + ("" if r["python_ok"] else "  (needs 3.9 or newer)")]
    if r["package_manager"]["hint"]:
        lines.append(f"  note: {r['package_manager']['hint']}")
    lines.append("Tools:")
    for name, t in r["tools"].items():
        if t["installed"]:
            lines.append(f"  {ok} {name}")
        else:
            lines.append(f"  {no} {name}: {t['unlocks']}\n        install: {t['install']}")
    if r["h264_encoder"]:
        lines.append(f"  video encoder for drafts: {r['h264_encoder']}")
    missing_f = [f"{f} ({v['for']})" for f, v in r["ffmpeg_filters"].items() if not v["present"]]
    if missing_f:
        lines.append("  ffmpeg lacks: " + "; ".join(missing_f)
                     + ". A fuller ffmpeg build adds them (macOS: brew install ffmpeg-full, then follow brew's PATH note).")
    missing_m = [f"{m} ({v['for']})" for m, v in r["python_modules"].items() if not v["installed"]]
    if missing_m:
        lines.append("  optional Python modules not installed: " + "; ".join(missing_m))
    rv = r["resolve"]
    lines.append(f"DaVinci Resolve: {ok + ' installed' if rv['installed'] else no + ' not found'}"
                 + ("" if rv["scripting_module"] or not rv["installed"] else " (scripting module not found)"))
    tr = r["transcription"]
    if not tr["available"]:
        lines.append(f"Transcription: {no} {tr['note']}")
    elif isinstance(tr.get("report"), dict) and isinstance(tr["report"].get("engines"), list):
        rep = tr["report"]
        lines.append(f"Transcription: configured engine = {rep.get('configured_engine') or 'none yet'}")
        for e in rep["engines"]:
            state = ok if e.get("available") else no
            extra = "" if e.get("available") else f" - {e.get('why_not')}"
            lines.append(f"  {state} {e.get('engine')}: {e.get('where', '')}; {e.get('cost', '')}{extra}")
            if e.get("setup"):
                lines.append(f"        setup: {e['setup']}")
        if rep.get("recommendation"):
            lines.append(f"  recommendation: {rep['recommendation']}")
    else:
        status = ok if tr.get("check_ok") else no
        detail = json.dumps(tr["report"]) if "report" in tr else tr.get("report_text", tr.get("note", ""))
        lines.append(f"Transcription: {status} {detail[:1500]}")
    vi = r["vision"]
    if vi.get("available"):
        lines.append(f"Local vision model: {ok} {vi.get('backend')} in {vi.get('python')}"
                     + ("" if vi.get("model_cached") else " (model downloads on first use)"))
    else:
        lines.append(f"Local vision model: {no} not set up ({vi.get('why_not') or vi.get('note')}); optional, "
                     f"for private footage. install: {vi.get('install') or 'see tools/vlm-describe/README.md'}")
    er = r["editreview"]
    if r["os"] == "Darwin":
        if er["built_app"]:
            lines.append(f"EditReview: {ok} ready at {er['built_app']}")
        elif er["source_present"]:
            lines.append(f"EditReview: {no} app missing"
                         + (f" (build: {er['build_script']})" if er["build_script"] else "")
                         + ("" if er["can_build"] else "; needs swiftc: xcode-select --install"))
        else:
            lines.append(f"EditReview: {no} not in this copy")
    s = r["settings"]
    lines.append(f"Settings: {'found' if s['exists'] else 'not created yet'} ({s['file']})")
    if s["exists"]:
        lines.append(f"  done steps: {', '.join(s['completed_steps']) or 'none'}; "
                     f"skipped: {', '.join(s['skipped_steps']) or 'none'}")
        lines.append(f"  unset: {', '.join(s['unset_keys']) or 'nothing'}")
    lines.append(f"Preferences: {'found' if s['preferences_exists'] else 'none yet'} ({s['preferences_file']})")
    lines.append("Suggested folders: " + ", ".join(f"{k.split('.')[-1]}={v}" for k, v in r["suggested"].items()
                                                if k.startswith("paths.")))
    return "\n".join(lines)


def main(argv: list) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    r = collect()
    print(as_text(r) if "--text" in argv else json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
