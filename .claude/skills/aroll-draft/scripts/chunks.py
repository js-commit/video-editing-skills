#!/usr/bin/env python3
"""A-roll edit chunking: split a word-level transcript into editor-sized chunks,
compose each chunk's prompt, validate the tilde-edited answers, and merge them
into a revision file.

The edit protocol (Video Haircut's): each chunk is a JSON array of segment
strings; the editor may only wrap words it wants cut in tildes (~word~), never
add, reorder or change words. Segment strings are the segment's words joined by
single spaces, so whitespace-split tokens map 1:1 onto word timestamps.

Chunks are edited one after another, and each prompt carries the edited tail of
the previous chunk as read-only context, so a retake that straddles a chunk
boundary can still be resolved. The prompt also carries the user's
`## aroll-draft` preferences (user/preferences.md) and, for non-English speech,
a language note. The instructions stay in English for every language.

Usage:
  python3 chunks.py plan     <transcript.json> <workdir> [--words-per-chunk 1100]
  python3 chunks.py prompt   <workdir> <N> [--preferences FILE]   # writes chunk_NN.prompt.md, prints its path
  python3 chunks.py validate <workdir> <N>                        # checks chunk_NN.edited.json
  python3 chunks.py merge    <workdir> <transcript.json> -o revision.json

Files in <workdir>: plan.json, chunk_NN.json, chunk_NN.prompt.md,
chunk_NN.edited.json (written by the editor agent).

Exit codes: 0 ok, 2 usage / missing input, 3 validation failed or the edited
chunk is missing (re-run the editor with the stderr as feedback).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from llm_json import extract_json_array
from prefs import language_block, preferences_block

SENTENCE_END = re.compile(r'[.!?。！？]["\'”」]?$')
CONTEXT_SEGMENTS = 8  # edited tail segments of the previous chunk shown as context
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reference", "edit-prompt.md")


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_json(path):
    if not os.path.exists(path):
        die(f"missing file: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data, indent=2):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def segment_strings(transcript):
    """One string per segment, words joined by single spaces (1:1 token map)."""
    out = []
    for seg in transcript["segments"]:
        words = [w["word"].strip() for w in seg.get("words") or []]
        words = [w for w in words if w]
        out.append(" ".join(words))
    return out


def strip_tildes(token):
    return token.replace("~", "")


def tokens(s):
    return [t for t in s.split() if t]


# ---------------------------------------------------------------- plan

def cmd_plan(args):
    transcript = load_json(args.transcript)
    segs = segment_strings(transcript)
    if not segs or not any(segs):
        die("transcript has no words")
    os.makedirs(args.workdir, exist_ok=True)

    word_counts = [len(tokens(s)) for s in segs]
    boundaries = []  # exclusive end index of each chunk
    i, n = 0, len(segs)
    while i < n:
        count, j = 0, i
        while j < n and count < args.words_per_chunk:
            count += word_counts[j]
            j += 1
        if j < n:
            # nudge the boundary up to 3 segments to land after sentence-ending punctuation
            best = None
            for cand in range(j, max(i, j - 4), -1):
                if SENTENCE_END.search(segs[cand - 1].rstrip()):
                    best = cand
                    break
            if best is None:
                for cand in range(j + 1, min(n, j + 4) + 1):
                    if SENTENCE_END.search(segs[cand - 1].rstrip()):
                        best = cand
                        break
            j = best if best is not None else j
        boundaries.append(j)
        i = j

    chunks = []
    start = 0
    for idx, end in enumerate(boundaries, start=1):
        write_json(os.path.join(args.workdir, f"chunk_{idx:02d}.json"), segs[start:end])
        chunks.append({"index": idx, "seg_start": start, "seg_end": end,
                       "words": sum(word_counts[start:end])})
        start = end

    plan = {"transcript": os.path.abspath(args.transcript),
            "num_segments": n, "num_chunks": len(chunks), "chunks": chunks}
    write_json(os.path.join(args.workdir, "plan.json"), plan)
    print(json.dumps({"num_chunks": len(chunks),
                      "chunks": [{"index": c["index"], "segments": c["seg_end"] - c["seg_start"],
                                  "words": c["words"]} for c in chunks]}))


# ---------------------------------------------------------------- prompt

def cmd_prompt(args):
    workdir, n = args.workdir, args.n
    plan = load_json(os.path.join(workdir, "plan.json"))
    if not 1 <= n <= plan["num_chunks"]:
        die(f"chunk {n} out of range 1..{plan['num_chunks']}")
    chunk = load_json(os.path.join(workdir, f"chunk_{n:02d}.json"))
    with open(TEMPLATE, encoding="utf-8") as f:
        template = f.read()

    context_block = ""
    if n > 1:
        prev_path = os.path.join(workdir, f"chunk_{n - 1:02d}.edited.json")
        if not os.path.exists(prev_path):
            die(f"chunk {n - 1} must be edited before prompting chunk {n} (missing {prev_path})")
        tail = load_json(prev_path)[-CONTEXT_SEGMENTS:]
        context_block = (
            "<context>\n"
            "The transcript continues from earlier material that has ALREADY been edited "
            "(you cannot change it). Words wrapped in ~tildes~ were already cut. Use it "
            "to spot retakes and restarts that begin before your section, and to make your "
            "section's opening flow from what was kept. If your section retakes something the "
            "context kept, still keep the better take in your section (usually yours, the later "
            "one): the revision pass removes the earlier duplicate.\n\n"
            "```json\n" + json.dumps(tail, indent=2, ensure_ascii=False) + "\n```\n"
            "</context>\n\n"
        )

    transcript = {}
    if os.path.exists(plan.get("transcript", "")):
        transcript = load_json(plan["transcript"])

    prompt = (template
              .replace("{{PREFERENCES}}", preferences_block(args.preferences))
              .replace("{{LANGUAGE}}", language_block(transcript))
              .replace("{{CONTEXT}}", context_block)
              .replace("{{TRANSCRIPTION}}", json.dumps(chunk, indent=2, ensure_ascii=False)))
    out_path = os.path.join(workdir, f"chunk_{n:02d}.prompt.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(out_path)


# ---------------------------------------------------------------- validate

def repair_edited(raw):
    """Light repairs for common agent output damage. Returns the parsed list."""
    data = json.loads(extract_json_array(raw))
    if not isinstance(data, list) or not all(isinstance(s, str) for s in data):
        raise ValueError("edited chunk is not a JSON array of strings")
    # punctuation trapped outside a closing tilde: "~word~." -> "~word.~"
    return [re.sub(r"~([^~\s]+)~([.,!?;:]+)", r"~\1\2~", s) for s in data]


def validate_chunk(original, edited):
    """List of error strings; empty means valid."""
    errors = []
    if len(edited) != len(original):
        return [f"segment count mismatch: expected {len(original)}, got {len(edited)}"]
    for i, (orig, ed) in enumerate(zip(original, edited)):
        otoks, etoks = tokens(orig), tokens(ed)
        if len(otoks) != len(etoks):
            errors.append(
                f"segment {i}: word count mismatch: expected {len(otoks)} got {len(etoks)}\n"
                f"  original: {orig}\n  edited:   {ed}")
            continue
        for j, (ot, et) in enumerate(zip(otoks, etoks)):
            core = strip_tildes(et)
            if core != ot:
                errors.append(f"segment {i} word {j}: expected {ot!r} got {et!r}")
            elif "~" in et and not (et.startswith("~") and et.endswith("~")):
                errors.append(f"segment {i} word {j}: malformed tildes in {et!r}")
    return errors


def cmd_validate(args):
    workdir, n = args.workdir, args.n
    original = load_json(os.path.join(workdir, f"chunk_{n:02d}.json"))
    edited_path = os.path.join(workdir, f"chunk_{n:02d}.edited.json")
    if not os.path.exists(edited_path):
        # retryable, like a validation failure: the editor did not write its output
        die(f"missing {edited_path}: the editor did not write its output", 3)
    with open(edited_path, encoding="utf-8") as f:
        raw = f.read()
    try:
        edited = repair_edited(raw)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"validation failed: unparseable edited chunk: {e}", file=sys.stderr)
        sys.exit(3)
    errors = validate_chunk(original, edited)
    if errors:
        print(f"validation failed: {len(errors)} error(s) in chunk {n}:", file=sys.stderr)
        for e in errors[:20]:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(3)
    write_json(edited_path, edited)  # the repaired, canonical form
    cut = sum(1 for s in edited for t in tokens(s) if t.startswith("~"))
    total = sum(len(tokens(s)) for s in edited)
    print(json.dumps({"chunk": n, "ok": True, "words": total, "cut_words": cut}))


# ---------------------------------------------------------------- merge

def cmd_merge(args):
    transcript = load_json(args.transcript)
    plan = load_json(os.path.join(args.workdir, "plan.json"))
    segs = segment_strings(transcript)

    edited_all = []
    for c in plan["chunks"]:
        chunk = load_json(os.path.join(args.workdir, f"chunk_{c['index']:02d}.edited.json"))
        original = load_json(os.path.join(args.workdir, f"chunk_{c['index']:02d}.json"))
        if validate_chunk(original, chunk):
            die(f"chunk {c['index']} no longer validates; re-run validate", 3)
        edited_all.extend(chunk)
    if len(edited_all) != len(segs):
        die(f"merged segment count {len(edited_all)} != transcript {len(segs)}", 3)

    kept_words = cut_words = 0
    for seg, edited in zip(transcript["segments"], edited_all):
        etoks = tokens(edited)
        words = [w for w in seg.get("words") or [] if w["word"].strip()]
        if len(etoks) != len(words):
            die(f"internal token/word mismatch in segment: {edited!r}", 3)
        for w, et in zip(words, etoks):
            w["cut"] = et.startswith("~") and et.endswith("~")
            if w["cut"]:
                cut_words += 1
            else:
                kept_words += 1

    write_json(args.output, transcript)
    kept_dur = sum(w["end"] - w["start"] for s in transcript["segments"]
                   for w in s.get("words") or [] if w["word"].strip() and not w.get("cut"))
    print(json.dumps({"revision": args.output, "kept_words": kept_words,
                      "cut_words": cut_words, "kept_speech_seconds": round(kept_dur, 1)}))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    sp = sub.add_parser("plan")
    sp.add_argument("transcript")
    sp.add_argument("workdir")
    sp.add_argument("--words-per-chunk", type=int, default=1100)
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("prompt")
    sp.add_argument("workdir")
    sp.add_argument("n", type=int)
    sp.add_argument("--preferences", help="preferences file (default <repo>/user/preferences.md)")
    sp.set_defaults(func=cmd_prompt)

    sp = sub.add_parser("validate")
    sp.add_argument("workdir")
    sp.add_argument("n", type=int)
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("merge")
    sp.add_argument("workdir")
    sp.add_argument("transcript")
    sp.add_argument("-o", "--output", required=True)
    sp.set_defaults(func=cmd_merge)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
