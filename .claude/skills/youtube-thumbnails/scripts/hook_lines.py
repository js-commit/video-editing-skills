#!/usr/bin/env python3
"""Find thumbnail hooks and "this is the shot" moments in the speaker's own words.

Reads the transcript sidecar next to the video (<stem>.transcript.json, made
by tools/transcribe.py; created now if missing and a transcription engine is
set up). When an a-roll edit exists (<stem>.aroll.revision.json), words marked
"cut" are left out, so hooks only come from lines that made the edit.

Prints JSON: every sentence with its start/end time, and two short lists that
are only pointers for Claude, who still reads the whole transcript:
  hooks    verdicts, questions, surprises, comparisons, numbers - lines that
           could become 1-3 words of thumbnail text
  moments  places the speaker shows something to the lens or reacts
           ("look at this", "here it is", "thumbnail") - sample frames there

Usage:  hook_lines.py VIDEO [--top 15] [--text]
  --text   print a plain timestamped transcript instead of JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import settings  # noqa: E402

HOOK_CUES = [
    r"\bworth\b", r"\bverdict\b", r"\bshould (you|i)\b", r"\bwould(n't| not)? (buy|recommend)\b",
    r"\brecommend\b", r"\bdon'?t buy\b", r"\bskip\b", r"\bmistake\b", r"\bregret\b", r"\bsurpris",
    r"\bhonestly\b", r"\bbest\b", r"\bworst\b", r"\bbetter\b", r"\bworse\b", r"\bvs\.?\b", r"\bversus\b",
    r"\bupgrade\b", r"\bdowngrade\b", r"\bproblem\b", r"\bfail", r"\bfinally\b", r"\bnever\b",
    r"\bwould(n't| not)? go back\b", r"\bkeep\b", r"\breturn(ed|ing)?\b", r"\bfaster\b", r"\bcheaper\b",
    r"\bin the end\b", r"\bbottom line\b", r"\bso,? (is|was) it\b",
]
MOMENT_CUES = [
    r"\bthumbnail\b", r"\bthis is the shot\b", r"\blook at (this|that)\b", r"\bcheck (this|it) out\b",
    r"\bhere it is\b", r"\bwow\b", r"\bunbox", r"\bright here\b", r"\bsee (this|that|how)\b",
    r"\bside by side\b", r"\bnext to (each other|the)\b", r"\bin my hand\b", r"\bfirst look\b",
]
NUMBER = re.compile(r"\b\d+([.,]\d+)?\s?(x|%|percent|times|hours?|days?|dollars?|gb|tb|mm|fps|k)?\b", re.I)


def load(video: Path) -> dict:
    sidecar = video.with_name(video.stem + ".transcript.json")
    try:
        from vidkit.transcript import ensure_transcript, load_transcript
    except ImportError:
        if not sidecar.is_file():
            raise SystemExit(f"No transcript for {video}. Make one with:\n  python3 "
                             f"{Path(__file__).resolve().parents[4] / 'tools' / 'transcribe.py'} {video}")
        return json.loads(sidecar.read_text(encoding="utf-8"))
    try:
        return load_transcript(ensure_transcript(video))
    except settings.SettingMissing as e:
        settings.exit_missing(e)


def kept_words(video: Path, data: dict) -> list:
    rev = video.with_name(video.stem + ".aroll.revision.json")
    src = data
    if rev.is_file():
        try:
            src = json.loads(rev.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            src = data
    words = []
    for seg in src.get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("cut") or "start" not in w:
                continue
            words.append((float(w["start"]), float(w.get("end", w["start"])), str(w.get("word", "")).strip()))
    return words


def sentences(video: Path, data: dict) -> list:
    words = kept_words(video, data)
    if not words:   # no word timings: fall back to segments
        return [{"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": s["text"].strip()}
                for s in data.get("segments", []) if s.get("text", "").strip()]
    out, cur = [], []
    for i, (s, e, w) in enumerate(words):
        gap = s - words[i - 1][1] if i else 0
        if cur and gap > 1.2:
            out.append(cur)
            cur = []
        cur.append((s, e, w))
        if w.endswith((".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"start": round(c[0][0], 2), "end": round(c[-1][1], 2),
             "text": re.sub(r"\s+([,.?!])", r"\1", " ".join(w for _, _, w in c)).strip()} for c in out]


def score(text: str, cues: list) -> list:
    t = text.lower()
    return [m.group(0) for m in (re.search(c, t) for c in cues) if m]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--text", action="store_true")
    a = ap.parse_args()
    if not a.video.is_file():
        raise SystemExit(f"{a.video}: no such file")
    sents = sentences(a.video, load(a.video))
    if a.text:
        for s in sents:
            m, sec = divmod(s["start"], 60)
            print(f"[{int(m):02d}:{sec:05.2f}] {s['text']}")
        return 0
    hooks, moments = [], []
    for s in sents:
        why = score(s["text"], HOOK_CUES)
        if s["text"].endswith("?"):
            why.append("question")
        if NUMBER.search(s["text"]):
            why.append("number")
        if why:
            hooks.append(dict(s, why=why))
        mw = score(s["text"], MOMENT_CUES)
        if mw:
            moments.append(dict(s, why=mw))
    hooks.sort(key=lambda h: -len(h["why"]))
    print(json.dumps({"video": str(a.video.resolve()), "sentences": len(sents),
                      "hooks": hooks[:a.top], "moments": moments[:a.top * 2],
                      "note": "Pointers only: read the whole transcript (--text) and pick the speaker's real verdict."},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
