#!/usr/bin/env python3
"""Start a home-video project: folders from your project layout plus work/project.json.

  init_project.py NAME --source DIR [--source DIR ...] --privacy frames|local|no-frames
                  [--subject "who it is about"] [--target-s 240] [--no-teaser] [--size 3840x2160]

NAME        a project name (created under settings paths.projects_dir) or a folder path
--source    footage folder(s), read IN PLACE: nothing is copied or moved. Sub-folders are included.
            Default: settings paths.inbox_dir
--privacy   frames     Claude may read contact sheets of this footage (best picks)
            local      only a vision model on this computer looks at frames (tools/vlm-describe);
                       Claude picks from its descriptions and the survey numbers
            no-frames  nothing looks at a frame: Claude works from metadata, motion and audio
                       numbers and from your own picks and review notes
--subject   the people / pets it is about ("us"), used in pick and review instructions
--target-s  a length cap in seconds, only when the user names one. Default: none, the footage
            decides (every distinct moment once)
--no-teaser leave out the 10-15 s teaser of the best shots that opens a montage by default
--size      the edit canvas (default settings editor.timeline_resolution, else 1920x1080).
            Drafts render at settings render.draft_height; the final at this size.

Re-running is safe: an existing project.json is updated only for the flags you pass.
Prints the project path on stdout.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402
from hv import settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--privacy", choices=hv.PRIVACY)
    ap.add_argument("--subject")
    ap.add_argument("--target-s", type=float)
    ap.add_argument("--no-teaser", action="store_true")
    ap.add_argument("--size")
    a = ap.parse_args()

    try:
        p = settings.project_dir(a.name)
        sources = [str(Path(s).expanduser().resolve()) for s in a.source]
        if not sources:
            inbox = settings.get_path("paths.inbox_dir")
            if inbox is None:
                hv.die("no --source given and settings paths.inbox_dir is unset: ask the user where the clips are", 2)
            sources = [str(inbox.resolve())]
        size = a.size or settings.get("editor.timeline_resolution", default="1920x1080")
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    for s in sources:
        if not Path(s).is_dir():
            hv.die(f"footage folder not found: {s}", 2)
    try:
        w, h = (int(x) for x in str(size).lower().split("x"))
    except ValueError:
        hv.die(f"--size must look like 1920x1080, got {size!r}", 2)

    cfg_path = p / "work" / "project.json"
    cfg = hv.load_json(cfg_path, {})
    if not cfg and not a.privacy:
        hv.die("--privacy frames|local|no-frames is required for a new project: read the user's preference in "
               "user/preferences.md (## home-video), or ask them once and save the answer there", 2)
    for part in ("footage", "audio", "drafts", "finals", "work"):
        (p / settings.layout(part)).mkdir(parents=True, exist_ok=True)
    for sub in ("meta", "music", "sheets", "stabilized"):
        (p / "work" / sub).mkdir(parents=True, exist_ok=True)

    cfg.setdefault("name", p.name)
    cfg.setdefault("teaser", True)
    cfg.setdefault("target_s", None)
    cfg.setdefault("fps", 30)
    if a.privacy:
        cfg["privacy"] = a.privacy
    if a.subject is not None:
        cfg["subject"] = a.subject
    if a.target_s is not None:
        cfg["target_s"] = a.target_s
    if a.no_teaser:
        cfg["teaser"] = False
    if a.source or "sources" not in cfg:
        cfg["sources"] = sorted(set(cfg.get("sources", []) + sources))
    if a.size or "width" not in cfg:
        cfg["width"], cfg["height"] = w, h
    hv.save_json(cfg_path, cfg)
    notes = p / "work" / "notes.md"
    if not notes.exists():
        notes.write_text(f"# {cfg['name']}: pick notes\n\n"
                         "One line per clip: id | verdict (PICK / maybe / skip + why) | ranges | tags\n"
                         "Tags: [people] [unplaced] [line: \"...\"] [sound: waves] [shaky] [portrait] [dup of <id>]\n\n",
                         encoding="utf-8")
    hv.log(f"project {p}: privacy {cfg['privacy']}, canvas {cfg['width']}x{cfg['height']}, "
           f"teaser {'on' if cfg['teaser'] else 'off'}, sources {len(cfg['sources'])}")
    print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
