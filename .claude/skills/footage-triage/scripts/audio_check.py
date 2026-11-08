#!/usr/bin/env python3
"""Step 3: how much sound each clip has, and (optional) what is said in it.

  audio_check.py --inventory W/inventory.json [--transcribe] [--max-minutes 30]

For every video/audio file with a sound track it measures loudness and how much
of the clip is above a quiet floor (`sound_fraction`). With --transcribe, clips
that have sound get a transcript through this repo's tools/transcribe.py (the
engine set up in settings transcription.engine). The transcript is saved next
to the clip as <name>.transcript.json - the one file triage writes beside the
media; it moves with the clip. A short snippet goes into the triage, so the
classifier knows a talking-head take from b-roll with music.

If no transcription engine is configured, transcription is skipped with a note
(exit 0): sorting still works from pictures and metadata.

Writes <work>/audio.json {file id: {...}}. stdout: JSON summary.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from vidkit import media  # noqa: E402

TRANSCRIBE = C.REPO / "tools" / "transcribe.py"


def loudness(path: str, duration: float) -> dict:
    cmd = [media.ffmpeg(), "-hide_banner", "-nostats", "-i", path, "-vn",
           "-af", "silencedetect=n=-40dB:d=0.5,volumedetect", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    err = r.stderr or ""
    mean = re.search(r"mean_volume: (-?[0-9.]+) dB", err)
    peak = re.search(r"max_volume: (-?[0-9.]+) dB", err)
    silent = sum(float(x) for x in re.findall(r"silence_duration: ([0-9.]+)", err))
    starts = re.findall(r"silence_start: (-?[0-9.]+)", err)
    ends = re.findall(r"silence_end: ([0-9.]+)", err)
    if len(starts) > len(ends) and duration:          # silence running to the end
        silent += max(0.0, duration - float(starts[-1]))
    return {"mean_db": float(mean.group(1)) if mean else None, "peak_db": float(peak.group(1)) if peak else None,
            "sound_fraction": round(max(0.0, 1 - silent / duration), 2) if duration else None}


def transcribe(path: str) -> tuple:
    """(sidecar path or None, note)."""
    if not TRANSCRIBE.exists():
        return None, "tools/transcribe.py is missing from this copy of the repo"
    r = subprocess.run([sys.executable, str(TRANSCRIBE), path], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode == 4:
        return None, "no-engine"
    if r.returncode != 0:
        lines = (r.stderr or "").strip().splitlines()
        return None, lines[-1] if lines else f"exit {r.returncode}"
    out = (r.stdout or "").strip().splitlines()
    return (out[-1] if out else None), "ok"


def snippet(sidecar: str, duration: float) -> dict:
    try:
        data = C.load_json(sidecar)
    except (OSError, ValueError):
        return {}
    segs = data.get("segments") or []
    text = " ".join((s.get("text") or "").strip() for s in segs).strip()
    spoken = sum(max(0.0, float(s.get("end", 0)) - float(s.get("start", 0))) for s in segs)
    return {"transcript": sidecar, "snippet": text[:400], "words": len(text.split()),
            "speech_coverage": round(min(1.0, spoken / duration), 2) if duration else None,
            "language": data.get("language")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--transcribe", action="store_true")
    ap.add_argument("--max-minutes", type=float, default=30.0, help="stop transcribing after this much audio")
    a = ap.parse_args()
    inv = C.load_json(a.inventory)
    outp = Path(inv["work_dir"]) / "audio.json"
    res = C.load_json(outp) if outp.exists() else {}
    files = [f for u in inv["units"] for f in u["files"] if f["kind"] in ("video", "audio") and f["has_audio"]]
    budget = a.max_minutes * 60
    note = None
    for f in files:
        dur = f.get("duration") or 0
        r = res.get(f["id"]) or loudness(f["path"], dur)
        existing = Path(f["path"]).with_name(Path(f["path"]).stem + ".transcript.json")
        if existing.exists() and "snippet" not in r:
            r.update(snippet(str(existing), dur))
        elif a.transcribe and note != "no-engine" and "snippet" not in r and (r.get("sound_fraction") or 0) >= 0.2 \
                and dur >= 2 and budget > 0:
            side, why = transcribe(f["path"])
            if side:
                r.update(snippet(side, dur))
                budget -= dur
            elif why == "no-engine":
                note = "no-engine"
            else:
                r["transcribe_error"] = why
        res[f["id"]] = r
    C.write_json(outp, res)
    summary = {"audio": str(outp), "clips_with_sound": len(files),
               "transcribed": sum(1 for r in res.values() if r.get("snippet") is not None)}
    if note == "no-engine":
        summary["note"] = ("no transcription engine is configured (settings transcription.engine): skipped. "
                           "Triage works without it; offer the setup skill if the user wants transcripts.")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
