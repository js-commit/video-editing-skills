#!/usr/bin/env python3
"""Revision pass support: pack the whole edited transcript for the reviser agent,
and apply the corrections it returns.

`pack` renders the full revision (kept and cut words) as one document so the
reviser can judge global flow: hybrid sentences, retakes that both survived,
orphaned fragments, chunk-boundary artifacts, over-cuts. Cut words appear as
~word~; each segment is numbered. The user's `## aroll-draft` preferences and a
language note (non-English speech) are printed at the top.

`apply` takes the reviser's corrections:
  [ {"segment": 12, "match": "so I have been looking for", "action": "cut"},
    {"segment": 30, "match": "grain of salt.", "action": "keep"} ]
`match` is a case-insensitive exact word sequence within that segment (tildes
ignored). Ambiguous or unmatched spans are reported and skipped.

Usage:
  python3 review.py pack  <revision.json> [-o review.md] [--preferences FILE]
  python3 review.py apply <revision.json> <corrections.json> [-o revision.json]

Exit codes: 0 ok, 2 usage, 3 some corrections did not apply (details on stderr;
the rest were applied - carry on).
"""
from __future__ import annotations

import argparse
import json
import sys

from llm_json import extract_json_array
from prefs import language_of, preference_bullets


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_corrections(path):
    """The reviser's corrections, tolerating code fences and prose around the array."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(extract_json_array(text))
    except json.JSONDecodeError as e:
        print(f"error: corrections file is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)


def seg_words(seg):
    return [w for w in seg.get("words") or [] if w["word"].strip()]


def norm(token):
    return token.replace("~", "").lower()


def cmd_pack(args):
    rev = load(args.revision)
    header = []
    bullets = preference_bullets(args.preferences)
    if bullets:
        header.append("# Creator preferences (they override the default rules)")
        header += [f"- {b}" for b in bullets]
        header.append("")
    lang = language_of(rev)
    if lang and lang != "English":
        header.append(f"# Language: the speech is in {lang}. Judge it as a native speaker would; "
                      "match words exactly as written.")
        header.append("")
    lines = []
    kept_dur = 0.0
    for i, seg in enumerate(rev["segments"]):
        words = seg_words(seg)
        if not words:
            continue
        parts = []
        for w in words:
            t = w["word"].strip()
            parts.append(f"~{t}~" if w.get("cut") else t)
            if not w.get("cut"):
                kept_dur += w["end"] - w["start"]
        t0, t1 = words[0]["start"], words[-1]["end"]
        lines.append(f"[{i:03d}] ({t0:7.2f}-{t1:7.2f}) {' '.join(parts)}")
    doc = "\n".join(header + lines) + f"\n\n# kept speech: {kept_dur:.1f}s\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(doc)
        print(args.output)
    else:
        print(doc)


def find_span(words, match_tokens):
    """Start indices where match_tokens occurs in words."""
    toks = [norm(w["word"].strip()) for w in words]
    target = [norm(t) for t in match_tokens]
    return [i for i in range(len(toks) - len(target) + 1) if toks[i:i + len(target)] == target]


def cmd_apply(args):
    rev = load(args.revision)
    corrections = load_corrections(args.corrections)
    if not isinstance(corrections, list):
        print("error: corrections must be a JSON array", file=sys.stderr)
        sys.exit(2)
    failures, applied = [], 0
    for c in corrections:
        if not isinstance(c, dict):
            failures.append(f"malformed correction: {c}")
            continue
        idx = c.get("segment")
        action = c.get("action")
        match = (c.get("match") or "").split()
        if action not in ("cut", "keep") or not match or not isinstance(idx, int) \
                or not 0 <= idx < len(rev["segments"]):
            failures.append(f"malformed correction: {c}")
            continue
        words = seg_words(rev["segments"][idx])
        hits = find_span(words, match)
        if not hits:
            failures.append(f"segment {idx}: no match for {' '.join(match)!r}")
            continue
        if len(hits) > 1:
            failures.append(f"segment {idx}: ambiguous match ({len(hits)} hits) for {' '.join(match)!r}")
            continue
        for w in words[hits[0]:hits[0] + len(match)]:
            w["cut"] = (action == "cut")
        applied += 1
    out = args.output or args.revision
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rev, f, indent=2, ensure_ascii=False)
    print(json.dumps({"applied": applied, "failed": len(failures), "revision": out}))
    if failures:
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        sys.exit(3)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    sp = sub.add_parser("pack")
    sp.add_argument("revision")
    sp.add_argument("-o", "--output")
    sp.add_argument("--preferences", help="preferences file (default <repo>/user/preferences.md)")
    sp.set_defaults(func=cmd_pack)

    sp = sub.add_parser("apply")
    sp.add_argument("revision")
    sp.add_argument("corrections")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_apply)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
