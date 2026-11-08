#!/usr/bin/env python3
"""Check Shorts proposals against the transcript, print them as prose, and turn
the user's picks into render specs.

    proposals.py workdir <long-form video>            # prints the work folder for its shorts
    proposals.py check   <proposals.json>             # exit 3 + the problems when it needs fixing
    proposals.py text    <proposals.json> [--slug S]  # each short's words back to back, to read as prose
    proposals.py spec    <proposals.json> --pick a,b [--size 1080x1920] [--out-dir DIR]

proposals.json (written by the shorts-scout agent):

    {"source": "/abs/long-form.mp4",
     "transcript": "/abs/long-form.transcript.json",      # default: <source stem>.transcript.json
     "shorts": [
       {"slug": "the-one-setting",                        # file-name safe, unique
        "title": "The one setting nobody changes",        # <= 100 chars, aim for the first ~40
        "description": "One line of payoff. #shorts",
        "keyword": "camera settings",                     # the search phrase this short targets
        "angle": "why this short exists, one line",
        "segments": [                                     # PLAYBACK order: the hook comes first
          {"start": 61.42, "end": 64.10,                  # start of the first word, end of the last
           "first_words": "turn this off first", "last_words": "the whole time",
           "note": "hook"}]}]}

Checks: every boundary sits on a word (start of a word / end of a word), the
first/last words match, segments of one short do not overlap, the hook starts a
sentence, the ending ends one, each segment is >= 1 s, the short is 15-60 s of
speech, titles fit. Errors exit 3 (fix and re-run); warnings are judgment calls.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortslib as sl  # noqa: E402

BOUNDARY_EPS = 0.02
SENTENCE_GAP = 0.35   # a pause this long reads as a sentence break even without punctuation


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    p["_path"] = str(Path(path).resolve())
    if not p.get("source"):
        sl.die("proposals.json needs a 'source' (the long-form video)", 2)
    p.setdefault("transcript", str(sl.default_transcript(p["source"])))
    if not Path(p["transcript"]).exists():
        sl.die(f"transcript not found: {p['transcript']} (make it with tools/transcribe.py)", 2)
    return p


def nearest(words, t, key):
    return min(words, key=lambda w: abs(w[key] - t)) if words else None


def segment_words(words, seg):
    return sl.words_between(words, float(seg["start"]), float(seg["end"]), BOUNDARY_EPS)


def check(p: dict) -> dict:
    words = sl.load_words(p["transcript"])
    if not words:
        sl.die("the transcript has no word timings", 2)
    index = {id(w): i for i, w in enumerate(words)}
    errors, warnings, summary = [], [], []
    slugs, used = set(), []
    for si, s in enumerate(p.get("shorts", [])):
        tag = s.get("slug") or f"short {si + 1}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", s.get("slug", "")):
            errors.append(f"{tag}: slug must be lower-case letters, digits and dashes")
        if tag in slugs:
            errors.append(f"{tag}: duplicate slug")
        slugs.add(tag)
        title = s.get("title", "")
        if not title:
            errors.append(f"{tag}: no title")
        elif len(title) > 100:
            errors.append(f"{tag}: title is {len(title)} chars (YouTube's limit is 100)")
        elif len(title) > 70:
            warnings.append(f"{tag}: title is {len(title)} chars; the player shows about the first 40")
        if "<" in title or ">" in title:
            errors.append(f"{tag}: '<' or '>' in the title (YouTube rejects them)")
        if "#shorts" not in s.get("description", "").lower():
            warnings.append(f"{tag}: description has no #shorts hashtag")
        segs = s.get("segments") or []
        if not segs:
            errors.append(f"{tag}: no segments")
            continue
        total, spoken, spans = 0.0, [], []
        for gi, g in enumerate(segs):
            gt = f"{tag} seg {gi + 1}"
            try:
                a, b = float(g["start"]), float(g["end"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{gt}: needs numeric start and end")
                continue
            if b <= a:
                errors.append(f"{gt}: end {b} <= start {a}")
                continue
            ws = nearest(words, a, "start")
            we = nearest(words, b, "end")
            if abs(ws["start"] - a) > BOUNDARY_EPS:
                errors.append(f"{gt}: start {a:.3f} is not a word start (nearest: {ws['word']!r} at {ws['start']:.3f})")
            if abs(we["end"] - b) > BOUNDARY_EPS:
                errors.append(f"{gt}: end {b:.3f} is not a word end (nearest: {we['word']!r} ends {we['end']:.3f})")
            inside = segment_words(words, g)
            if not inside:
                errors.append(f"{gt}: no words between {a:.2f} and {b:.2f}")
                continue
            for key, part in (("first_words", inside[:4]), ("last_words", inside[-4:])):
                want = sl.norm(g.get(key, ""))
                got = sl.norm(" ".join(w["word"] for w in part))
                if want and not (got.startswith(want) or got.endswith(want) or want in got):
                    errors.append(f"{gt}: {key} {g[key]!r} but the transcript says {got!r}")
            if b - a < 1.0:
                warnings.append(f"{gt}: {b - a:.2f} s long; a piece under 1 s reads as a glitch")
            i0, i1 = index[id(inside[0])], index[id(inside[-1])]
            if gi == 0:
                prev = words[i0 - 1] if i0 > 0 else None
                if prev and not sl.ends_sentence(prev["word"]) and inside[0]["start"] - prev["end"] < SENTENCE_GAP:
                    warnings.append(f"{gt}: the hook starts mid-sentence (after {prev['word']!r}); "
                                    f"a hook that sounds like a continuation loses the viewer")
            if gi == len(segs) - 1:
                nxt = words[i1 + 1] if i1 + 1 < len(words) else None
                if nxt and not sl.ends_sentence(inside[-1]["word"]) and nxt["start"] - inside[-1]["end"] < SENTENCE_GAP:
                    warnings.append(f"{gt}: the short ends mid-sentence (before {nxt['word']!r})")
            for x0, x1 in spans:
                if a < x1 and b > x0:
                    errors.append(f"{gt}: overlaps another segment of the same short")
            spans.append((a, b))
            total += b - a
            spoken += [w["word"] for w in inside]
        if total and total < 10:
            errors.append(f"{tag}: only {total:.1f} s of speech")
        elif total and not (15 <= total <= 60):
            warnings.append(f"{tag}: {total:.1f} s of speech; aim for 15-60 s")
        for other, ospans in used:
            if any(a < y and b > x for a, b in spans for x, y in ospans):
                warnings.append(f"{tag}: reuses a passage from {other}; make each short a different angle")
        used.append((tag, spans))
        summary.append({"slug": tag, "speech_s": round(total, 2), "segments": len(segs),
                        "hook": " ".join(spoken[:8]), "title": title})
    if not p.get("shorts"):
        errors.append("no shorts in the proposals")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "shorts": summary}


def cmd_check(a):
    rep = check(load(a.proposals))
    print(json.dumps(rep, indent=2))
    return 0 if rep["ok"] else 3


def cmd_text(a):
    p = load(a.proposals)
    words = sl.load_words(p["transcript"])
    for s in p["shorts"]:
        if a.slug and s.get("slug") != a.slug:
            continue
        parts = [" ".join(w["word"] for w in segment_words(words, g)) for g in s.get("segments", [])]
        dur = sum(float(g["end"]) - float(g["start"]) for g in s.get("segments", []))
        print(f"## {s.get('slug')}  ({dur:.1f} s)  {s.get('title', '')}")
        print("  //  ".join(parts))
        print()
    return 0


def cmd_spec(a):
    p = load(a.proposals)
    rep = check(p)
    if not rep["ok"]:
        print(json.dumps(rep, indent=2))
        sl.die("fix the proposals first (errors above)", 3)
    picks = None if a.pick in (None, "all") else [x.strip() for x in a.pick.split(",") if x.strip()]
    chosen = [s for s in p["shorts"] if picks is None or s["slug"] in picks]
    missing = set(picks or []) - {s["slug"] for s in chosen}
    if missing:
        sl.die(f"no such slug(s): {', '.join(sorted(missing))}", 2)
    w, h = sl.parse_size(a.size)
    out_dir = Path(a.out_dir).expanduser().resolve() if a.out_dir else sl.work_dir(p["source"])
    out_dir.mkdir(parents=True, exist_ok=True)
    drafts = sl.settings.drafts_dir(p["source"])
    written = []
    for s in chosen:
        spec = {
            "source": p["source"], "transcript": p["transcript"],
            "output": str(drafts / f"{s['slug']}.mp4"),
            "slug": s["slug"], "title": s.get("title", ""), "description": s.get("description", ""),
            "width": w, "height": h,
            "captions": True, "caption_style": {},
            "segments": [{"start": float(g["start"]), "end": float(g["end"]), "note": g.get("note", ""),
                          "framing": [{"mode": "crop", "crop_center": 0.5}]} for g in s["segments"]],
        }
        path = out_dir / f"{s['slug']}.spec.json"
        if path.exists() and not a.force:
            sl.log(f"kept existing {path} (use --force to overwrite)")
        else:
            path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        written.append(str(path))
    print(json.dumps({"specs": written}, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("workdir", help="print (and create) the work folder for a long-form video")
    w.add_argument("source")
    c = sub.add_parser("check", help="validate proposals against the transcript")
    c.add_argument("proposals")
    t = sub.add_parser("text", help="print each short as prose")
    t.add_argument("proposals"); t.add_argument("--slug")
    s = sub.add_parser("spec", help="write render specs for the picked shorts")
    s.add_argument("proposals")
    s.add_argument("--pick", default="all", help="comma-separated slugs, or 'all'")
    s.add_argument("--size", default="1080x1920", help="output WIDTHxHEIGHT (preferences may say 2160x3840)")
    s.add_argument("--out-dir", help="where the specs go (default: the work folder)")
    s.add_argument("--force", action="store_true", help="overwrite existing specs")
    a = ap.parse_args()
    if a.cmd == "workdir":
        print(sl.work_dir(a.source))
        return 0
    try:
        return {"check": cmd_check, "text": cmd_text, "spec": cmd_spec}[a.cmd](a)
    except sl.settings.SettingMissing as e:
        sl.settings.exit_missing(e)


if __name__ == "__main__":
    sys.exit(main())
