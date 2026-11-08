#!/usr/bin/env python3
"""Flag transcript words that may have swallowed an immediate retake.

When a speaker flubs a line and immediately re-reads it, speech recognisers can
emit the sentence ONCE, aligned to the first (flubbed) take, and stretch a single
word over "pause + the whole second take". The transcript then claims the line
was said once, cleanly: the edit keeps the flubbed take and nobody notices.

The detector is deliberately small:

- One absolute duration bar per word (default 1.2 s). Per-language speaking-rate
  gates and per-take duration statistics were tried and did worse.
- No auto-cut, ever. Where inside the stretched word the second take begins is
  exactly what the timestamps lost. Flags are for a human ear.
- The flagged word's TAIL (the part after the word itself was spoken) is checked
  with ffmpeg silencedetect. A quiet tail is an absorbed pause (recognisers also
  swallow plain silence, and talking-head takes have quiet demo stretches); an
  AUDIBLE tail is where a swallowed second take would live, so it must be
  auditioned. A noisy-but-speechless tail stays flagged: that costs a listen,
  never a miss.
- With --cuts, flags split into IN-CUT (the draft would contain the hidden flub)
  and already-removed.

Standard library only (plus ffmpeg for the tail check).

Usage:
  flag_retakes.py <media-or-transcript.json> [--cuts cuts.tb.json]
                  [--min-word-s 1.2] [--no-audio-check] [--json out.json]

The transcript is <media-dir>/<stem>.transcript.json unless a .json is given
(then there is no audio check).

Exit codes: 0 nothing to audition, 2 audible-tail flags survive into the cut
(or, without --cuts, exist at all), 1 error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402

DEFAULT_MIN_WORD_S = 1.2
WORD_HEAD_S = 0.6       # the word's own utterance, excluded from the tail
SILENCE_DB = "-33dB"    # silencedetect noise floor for "quiet"
MIN_TAIL_AUDIO_S = 1.0  # an audible tail shorter than this is breath or rustle

CAVEAT = (
    "A flag is not a cut point: where inside the stretched word the second "
    "take begins is precisely what the transcript lost - audition it. "
    "No flags is weak evidence, not proof: a swallow smeared across "
    "several words never clears the bar."
)


def sidecar_path(path):
    if path.endswith(".json"):
        return path
    stem, _ = os.path.splitext(path)
    return stem + ".transcript.json"


def load_words(doc):
    """[(start, end, word, segment_text)] from a transcript sidecar."""
    words = []
    for seg in doc.get("segments") or []:
        seg_text = (seg.get("text") or "").strip()
        for w in seg.get("words") or []:
            s, e = w.get("start"), w.get("end")
            if isinstance(s, (int, float)) and isinstance(e, (int, float)):
                words.append((float(s), float(e), (w.get("word") or "").strip(), seg_text))
    return words


def load_keeps(cuts_path):
    """[(src_start, src_end, out_start)] from a TimeBolt op list, in order."""
    with open(cuts_path, encoding="utf-8") as f:
        ops = json.load(f)
    keeps, out = [], 0.0
    for c in ops:
        if c.get("operation") == "remove":
            continue
        s, d = float(c["start"]), float(c["duration"])
        keeps.append((s, s + d, out))
        out += d
    return keeps


def out_time(keeps, t):
    """Output-timeline position of source second t, or None if removed."""
    for s, e, out in keeps:
        if s <= t < e:
            return out + (t - s)
    return None


def hms(t):
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:05.2f}"


def tail_audio_seconds(media_path, start, end):
    """Non-silent seconds in [start, end] of the media's audio, or None on error."""
    dur = end - start
    if dur <= 0:
        return 0.0
    try:
        r = subprocess.run(
            [media.ffmpeg(), "-hide_banner", "-nostats", "-ss", f"{start:.3f}",
             "-t", f"{dur:.3f}", "-i", media_path, "-vn",
             "-af", f"silencedetect=n={SILENCE_DB}:d=0.25",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    silent = 0.0
    opened = None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            opened = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and opened is not None:
            silent += float(m.group(1)) - opened
            opened = None
    if opened is not None:  # silence ran to the end of the window
        silent += dur - opened
    return max(0.0, dur - silent)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", help="media file (transcript looked up next to it) or a transcript .json")
    ap.add_argument("--cuts", help="TimeBolt cut list: splits flags into in-cut vs removed")
    ap.add_argument("--min-word-s", type=float, default=DEFAULT_MIN_WORD_S)
    ap.add_argument("--no-audio-check", action="store_true",
                    help="skip the ffmpeg tail check (every flag stays suspect)")
    ap.add_argument("--json", dest="json_out", help="also write the report here")
    args = ap.parse_args()

    sc = sidecar_path(args.media)
    if not os.path.exists(sc):
        print(f"no transcript: {sc} (run tools/transcribe.py on the media first)", file=sys.stderr)
        return 1
    with open(sc, encoding="utf-8") as f:
        words = load_words(json.load(f))
    if not words:
        print(f"transcript holds no words: {sc}", file=sys.stderr)
        return 1
    keeps = load_keeps(args.cuts) if args.cuts else None
    media_path = None if args.media.endswith(".json") else args.media
    probe_audio = media_path is not None and not args.no_audio_check

    flags = []
    for s, e, word, seg_text in words:
        dur = e - s
        if dur < args.min_word_s:
            continue
        f = {"word": word, "start_s": round(s, 3), "end_s": round(e, 3),
             "duration_s": round(dur, 2), "segment": seg_text}
        if keeps is not None:
            # in-cut if ANY of the span survives into the output
            ot = next((out_time(keeps, t) for t in (s, (s + e) / 2, e)
                       if out_time(keeps, t) is not None), None)
            f["kept"] = ot is not None
            if ot is not None:
                f["output_s"] = round(ot, 2)
        if probe_audio:
            tail = tail_audio_seconds(media_path, s + WORD_HEAD_S, e)
            f["tail_audio_s"] = None if tail is None else round(tail, 2)
            f["suspect"] = tail is None or tail >= MIN_TAIL_AUDIO_S
        else:
            f["suspect"] = True
        flags.append(f)

    suspects = [f for f in flags if f["suspect"] and f.get("kept", True)]
    quiet_kept = [f for f in flags if not f["suspect"] and f.get("kept", True)]
    removed = [f for f in flags if not f.get("kept", True)]
    total_s = words[-1][1]
    print(f"{len(flags)} stretched word(s) over the {args.min_word_s}s bar in "
          f"{hms(total_s)} of speech ({os.path.basename(sc)})")

    if suspects:
        where = "in the cut" if keeps is not None else "no cut list given"
        print(f"\nAUDITION THESE - audible tail, {where} "
              f"(a swallowed second take would sound exactly like this):")
        for f in suspects:
            at = f"  @ output {hms(f['output_s'])}" if "output_s" in f else ""
            tail = (f", tail audio {f['tail_audio_s']}s" if f.get("tail_audio_s") is not None else "")
            print(f"  {hms(f['start_s'])}-{hms(f['end_s'])}  {f['duration_s']:5.2f}s  "
                  f"{f['word']!r}{tail}{at}")
            print(f"      segment: {f['segment'][:100]}")
            print(f"      audition: ffplay -ss {max(0.0, f['start_s'] - 1):.2f} "
                  f"-t {f['duration_s'] + 2:.2f} -autoexit -nodisp "
                  f"\"{media_path or '<media>'}\"")
    else:
        print("\nNothing to audition: no stretched word in the cut has an audible tail.")
    if quiet_kept:
        print("\nquiet tails, in cut (absorbed pauses, informational): "
              + ", ".join(f"{f['word']!r}@{hms(f['start_s'])}" for f in quiet_kept))
    if removed:
        print(f"{len(removed)} flag(s) fall in material the cut already removes.")
    if flags:
        print(f"\n{CAVEAT}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"sidecar": sc, "min_word_s": args.min_word_s,
                       "flags": flags, "caveat": CAVEAT}, fh, indent=1, ensure_ascii=False)
    return 2 if suspects else 0


if __name__ == "__main__":
    sys.exit(main())
