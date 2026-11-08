#!/usr/bin/env python3
"""One worksheet for a notes round: every live note of a draft with the words
spoken around it, the clip under it, and a first guess at its class.

    notes_worksheet.py DRAFT.mp4 [-o notes_map.json] [--transcribe] [--before 14] [--after 10]

Reads <draft-stem>.review/notes.json (EditReview, or import_notes.py), the
draft's word-level transcript (<draft-stem>.transcript.json next to it;
--transcribe makes it with tools/transcribe.py when missing) and, when there,
<draft-stem>.review/cuts.json and changes.json. Writes notes_map.json (default:
inside the .review folder) and prints a readable summary on stderr.

Notes are stamped LATE: the reviewer pauses after noticing, so the words that
matter usually end just before the stamp. The window is 14 s back and 10 s
forward by default; pick the word the note is about, not the stamp.

suggested_class is a keyword guess, nothing more: "additive" (lands on a layer
above the a-roll: b-roll, screenshot, text, graphic; never changes timing),
"structural" (cut, trim, restore, re-record, add section: shifts every later
timestamp) or "other" (audio, colour, questions). Claude sets "class" for
every note after reading it.

Exit codes: 0 ok, 1 bad input, 4 transcription engine not configured (with --transcribe).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))

STRUCTURAL = {
    "trim": ["trim", "tighten", "too long", "shorter", "speed this up", "drags"],
    "cut": ["cut this", "cut that", "cut out", "remove", "delete", "get rid of", "take out", "lose this"],
    "repeat": ["repeat", "twice", "duplicate", "again i said", "said that already", "double take"],
    "delete-section": ["drop this section", "drop the section", "drop the bit", "don't need this section",
                       "do not need this section", "don't need the bit", "skip this part"],
    "restore": ["put the pause back", "too tight", "let it breathe", "cut too early", "cut off",
                "clipped", "restore", "bring back"],
    "re-record": ["re-record", "rerecord", "reshoot", "re-shoot", "redo this line", "change the script"],
    "add-section": ["add a section", "insert a section", "add a bit about", "add the part"],
}
ADDITIVE = {
    "b-roll": ["b-roll", "broll", "b roll", "footage", "show a shot", "shot of", "show me", "close-up",
               "closeup", "cutaway", "show the", "show it", "show a"],
    "screenshot": ["screenshot", "screen shot", "website", "web page", "webpage", "screen recording", "capture"],
    "text": ["text", "title", "caption", "lower third", "overlay", "label", "big number", "on screen",
             "callout", "spell", "metric"],
    "graphic": ["graphic", "animation", "chart", "diagram", "arrow", "zoom in", "punch in", "punch-in"],
}
OTHER = {
    "audio": ["loud", "quiet", "volume", "audio", "music", "noise", "hum", "mic"],
    "color": ["colour", "color", "exposure", "too dark", "too bright", "white balance", "grade"],
}


def classify(text: str):
    t = " " + text.lower() + " "
    for cls, table in (("structural", STRUCTURAL), ("additive", ADDITIVE), ("other", OTHER)):
        for kind, words in table.items():
            if any(w in t for w in words):
                return cls, kind
    return "other", "unclear"


def load_json(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def transcript_words(draft: Path, make: bool) -> list:
    side = draft.with_name(draft.stem + ".transcript.json")
    if not side.exists() and make:
        r = subprocess.run([sys.executable, str(REPO / "tools" / "transcribe.py"), str(draft)],
                           stdout=subprocess.PIPE, text=True)
        if r.returncode == 4:
            print("no transcription engine is configured: ask the user which one to use, then "
                  "`python3 tools/vidkit/settings.py set transcription.engine <name>`", file=sys.stderr)
            sys.exit(4)
        if r.returncode == 0 and r.stdout.strip():
            side = Path(r.stdout.strip().splitlines()[-1])
    doc = load_json(side) if side.exists() else None
    if not doc:
        return []
    words = []
    for seg in doc.get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("start") is not None and (w.get("word") or "").strip():
                words.append((float(w["start"]), float(w.get("end", w["start"])), w["word"].strip()))
    return words


def tc(seconds: float, fps: float, start_frames: int = 0) -> str:
    base = max(1, round(fps))
    f = int(seconds * fps + 1e-6) + start_frames
    return "%02d:%02d:%02d:%02d" % (f // (base * 3600), (f // (base * 60)) % 60, (f // base) % 60, f % base)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft", type=Path, help="the reviewed render (or its .review folder)")
    ap.add_argument("-o", "--out", type=Path, help="notes_map.json path (default: in the .review folder)")
    ap.add_argument("--transcribe", action="store_true", help="make the transcript if it is missing")
    ap.add_argument("--before", type=float, default=14.0, help="seconds of words before the stamp (default 14)")
    ap.add_argument("--after", type=float, default=10.0, help="seconds of words after the stamp (default 10)")
    args = ap.parse_args()

    p = args.draft.expanduser().resolve()
    review = p if p.suffix == ".review" and p.is_dir() else p.with_suffix(".review")
    notes_doc = load_json(review / "notes.json")
    if not notes_doc:
        sys.exit(f"no readable notes.json in {review} (review the draft in EditReview, or use import_notes.py)")
    draft = review.parent / (notes_doc.get("video") or (p.name if p.is_file() else ""))
    fps = float(notes_doc.get("frame_rate") or 24.0)
    sf = 0
    stc = notes_doc.get("start_timecode") or "00:00:00:00"
    try:
        h, m, s, f = (int(x) for x in stc.replace(";", ":").split(":"))
        sf = ((h * 60 + m) * 60 + s) * max(1, round(fps)) + f
    except ValueError:
        pass

    words = transcript_words(draft, args.transcribe) if draft.is_file() else []
    cuts_doc = load_json(review / "cuts.json") or {}
    cuts = cuts_doc.get("cuts", [])
    changes = (load_json(review / "changes.json") or {}).get("changes", [])
    if not words:
        print(f"note: no transcript next to {draft.name}; run with --transcribe to make one", file=sys.stderr)

    rows = []
    for n, note in enumerate(sorted(notes_doc.get("notes", []), key=lambda x: float(x["seconds"])), 1):
        t = float(note["seconds"])
        text = (note.get("text") or "").strip()
        cls, kind = classify(text)
        win = [w for w in words if t - args.before <= w[0] <= t + args.after]
        context = " ".join(("▮ " if i == next((k for k, w in enumerate(win) if w[0] > t), None) else "") + w[2]
                           for i, w in enumerate(win))
        clip = next((c for c in cuts if c["start_s"] <= t < c["end_s"]), None)
        change = next((c for c in changes if c["start_s"] - 0.75 <= t <= c["end_s"] + 2.0), None)
        rows.append({
            "n": n, "id": note.get("id"), "seconds": round(t, 3), "timecode": tc(t, fps, sf), "text": text,
            "class": None, "type": None, "suggested_class": cls, "suggested_type": kind,
            "words": [[round(w[0], 3), round(w[1], 3), w[2]] for w in win],
            "context": context,
            "clip": ({"index": clip["index"], "name": clip.get("name"), "track": clip.get("track"),
                      "start_s": clip["start_s"], "end_s": clip["end_s"], "source": clip.get("source"),
                      "offset_s": round(t - clip["start_s"], 3)} if clip else None),
            "previous_change": ({"id": change["id"], "title": change.get("title")} if change else None),
            "plan": None, "done": None,
        })

    out = args.out or (review / "notes_map.json")
    out.write_text(json.dumps({
        "schema": "edit-review-notes-map/1", "video": draft.name, "review_dir": str(review),
        "frame_rate": fps, "start_timecode": stc,
        "timeline": " / ".join(x for x in (cuts_doc.get("project"), cuts_doc.get("timeline")) if x) or None,
        "transcript": bool(words), "notes": rows}, indent=2, ensure_ascii=False) + "\n")
    for r in rows:
        where = f" [{r['clip']['name']}]" if r["clip"] else ""
        print(f"#{r['n']:>2} {r['timecode']}{where} ({r['suggested_class']}/{r['suggested_type']}) {r['text']}\n"
              f"     …{r['context'][-220:]}", file=sys.stderr)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
