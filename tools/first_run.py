#!/usr/bin/env python3
"""SessionStart hook: tells Claude whether this copy has been set up yet."""
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
settings = Path(os.environ["VES_SETTINGS"]).expanduser() if os.environ.get("VES_SETTINGS") else root / "user" / "settings.json"
prefs = root / "user" / "preferences.md"

if not settings.is_file():
    print("FIRST RUN: this video-editing toolkit has not been set up yet (no user/settings.json). "
          "When the user first writes, greet them briefly and offer the `setup` skill "
          "(about ten minutes, every question skippable). If they want to dive straight in, "
          "do what they asked; skills ask for missing settings as they go.")
    sys.exit(0)

try:
    data = json.loads(settings.read_text(encoding="utf-8"))
except Exception as e:
    print(f"user/settings.json could not be read ({e}); offer to fix it or re-run the setup skill.")
    sys.exit(0)

ob = data.get("onboarding", {})
skipped = ob.get("skipped_steps", [])
msg = "Video-editing toolkit is set up."
if skipped:
    msg += " Skipped setup steps (offer them only when relevant): " + ", ".join(skipped) + "."
if prefs.is_file():
    msg += " Read user/preferences.md before editing tasks."
print(msg)
