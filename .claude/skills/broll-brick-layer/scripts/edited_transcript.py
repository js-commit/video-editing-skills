#!/usr/bin/env python3
"""The transcript of the video as the audience hears it, in timeline seconds.

Each a-roll SOURCE file is transcribed once (word level, the
<stem>.transcript.json sidecar next to it, made by tools/transcribe.py). The
edited timeline keeps only slices of the source; this maps every word whose
midpoint survives the cut onto the timeline:
    timeline_s = item.record_s + (word_s - item.src_start_s)
record_s counts from the timeline start, the same clock as a full render.

Sidecars are found next to each source automatically; --transcribe creates
missing ones (tools/transcribe.py, the engine from settings). --map
SUBSTRING=FILE points sources whose path contains SUBSTRING at a transcript
stored elsewhere (a read-only source folder).

Usage:
  edited_transcript.py --inventory inventory.json [--track audio:1]
        [--transcribe] [--map SUBSTRING=TRANSCRIPT.json ...] [-o edited_transcript.json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402

TRANSCRIBE = B.TOOLS / "transcribe.py"


def load_words(path):
    try:
        from vidkit.transcript import load_transcript  # shared sidecar reader
        d = load_transcript(path)
    except ImportError:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    return [w for s in d.get("segments", []) for w in s.get("words", [])
            if w.get("start") is not None and w.get("end") is not None]


def sidecar_for(media_path, transcribe=False):
    cand = os.path.splitext(media_path)[0] + ".transcript.json"
    if os.path.exists(cand):
        return cand
    try:  # read-only media folders keep the sidecar in the cache
        from vidkit.transcript import find_sidecar
        found = find_sidecar(media_path)
        if found:
            return str(found)
    except Exception:
        pass
    if not transcribe:
        return None
    try:
        from vidkit.transcript import ensure_transcript
        return str(ensure_transcript(media_path))
    except ImportError:
        r = subprocess.run([sys.executable, str(TRANSCRIBE), media_path], capture_output=True, text=True)
        if r.returncode == 4:
            sys.stderr.write(r.stderr)
            sys.exit(4)
        if r.returncode:
            sys.exit(f"transcription failed for {media_path}: {r.stderr.strip()[-400:]}")
        return r.stdout.strip().splitlines()[-1]


def project_words(items, words_for):
    """Pure: items = inventory items of the speech track; words_for(item) ->
    word list on that item's source clock or None. Returns timeline words."""
    placed = []
    for item in items:
        words = words_for(item)
        if words is None or item.get("src_start_s") is None:
            continue
        s0, s1, rec = item["src_start_s"], item["src_end_s"], item["record_s"]
        for w in words:
            mid = (w["start"] + w["end"]) / 2
            if s0 <= mid < s1:
                placed.append({"word": w["word"], "start": round(rec + (w["start"] - s0), 3),
                               "end": round(rec + (w["end"] - s0), 3)})
    placed.sort(key=lambda w: w["start"])
    return placed


def segment(placed, gap=1.2):
    """Sentence-ish segments: break on terminal punctuation or a >gap jump."""
    segs, cur = [], []
    for w in placed:
        if cur and w["start"] - cur[-1]["end"] > gap:
            segs.append(cur)
            cur = []
        cur.append(w)
        if w["word"].rstrip('"’\'').endswith((".", "!", "?")):
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return [{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["word"].strip() for w in s), "words": s}
            for s in segs if s]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--track", default="audio:1", help="the track carrying the speech (default audio:1)")
    ap.add_argument("--transcribe", action="store_true", help="transcribe sources that have no sidecar yet")
    ap.add_argument("--map", action="append", default=[], metavar="SUBSTRING=TRANSCRIPT.json")
    ap.add_argument("-o", "--output", default=None)
    a = ap.parse_args()

    with open(a.inventory) as f:
        inv = json.load(f)
    aroll = inv["aroll"]
    kind, idx = a.track.split(":")
    track = next((t for t in aroll[f"{kind}_tracks"] if t["index"] == int(idx)), None)
    if track is None:
        sys.exit(f"no {a.track} track on {aroll['name']!r}")
    mapped = []
    for m in a.map:
        sub, path = m.split("=", 1)
        mapped.append((sub, load_words(path)))
    cache, missing = {}, set()

    def words_for(item):
        key = (item.get("file_path") or "") + " " + item["name"]
        for sub, w in mapped:
            if sub in key:
                return w
        path = item.get("file_path")
        if not path:
            return None
        if path not in cache:
            sc = sidecar_for(path, a.transcribe)
            cache[path] = load_words(sc) if sc else None
            if sc is None:
                missing.add(path)
        return cache[path]

    placed = project_words(track["items"], words_for)
    out = {"timeline": aroll["name"], "fps": aroll["fps"], "clock": "seconds from the timeline start",
           "word_count": len(placed), "segments": segment(placed)}
    for p in sorted(missing):
        B.log(f"no transcript for {p} (re-run with --transcribe, or --map it)")
    blob = json.dumps(out, indent=1)
    if a.output:
        with open(a.output, "w") as f:
            f.write(blob)
        B.log(f"wrote {a.output} ({len(placed)} words, {len(out['segments'])} segments)")
    else:
        print(blob)


if __name__ == "__main__":
    main()
