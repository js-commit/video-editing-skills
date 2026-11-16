#!/usr/bin/env python3
"""SessionStart hook: tells Claude whether this copy has been set up yet, and (at most once a day) whether a
newer version of the toolkit is out (tools/update.py check)."""
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
settings = Path(os.environ["VES_SETTINGS"]).expanduser() if os.environ.get("VES_SETTINGS") else root / "user" / "settings.json"
prefs = root / "user" / "preferences.md"


def setup_state() -> str:
    if not settings.is_file():
        return ("FIRST RUN: this video-editing toolkit has not been set up yet (no user/settings.json). "
                "When the user first writes, greet them briefly and offer the `setup` skill "
                "(about ten minutes, every question skippable). If they want to dive straight in, "
                "do what they asked; skills ask for missing settings as they go.")
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except Exception as e:
        return f"user/settings.json could not be read ({e}); offer to fix it or re-run the setup skill."
    skipped = data.get("onboarding", {}).get("skipped_steps", [])
    msg = "Video-editing toolkit is set up."
    if skipped:
        msg += " Skipped setup steps (offer them only when relevant): " + ", ".join(skipped) + "."
    if prefs.is_file():
        msg += " Read user/preferences.md before editing tasks."
    return msg


print(setup_state())
try:    # the update look must never stop or slow a session: it is silent on any failure
    sys.path.insert(0, str(root / "tools"))
    import update
    update.cmd_check()
except BaseException:
    pass
