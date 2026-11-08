#!/usr/bin/env python3
"""Search the b-roll library by keywords.

  python3 search.py "<query>" [--limit N] [--json] [--source NAME] [--include-faces]

Scores each clip by how many query words appear in its tags (strongest), its
description, and its source project / file name. Words shorter than two
letters and common filler words are ignored; plurals match singulars.
Clips judged a-roll or junk are never returned. Clips judged "broll-face"
(a person on screen) come back only with --include-faces, or when nothing
else matches.

--json prints a JSON list of {path, start, end, description, tags,
source_project}: path is the absolute media file, start/end the seconds to use
inside it (a raw original indexed in place is a range of a longer file).

No library configured (settings paths.broll_library_dir unset) or not
reachable: prints a note on stderr and an empty result (exit 0), so callers
can always run it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

STOP = {"a", "an", "the", "of", "and", "or", "with", "in", "on", "at", "to", "for", "from", "by", "is",
        "it", "this", "that", "some", "any", "shot", "shots", "clip", "clips", "footage", "broll", "b-roll", "video"}


def norm(word: str) -> str:
    w = word.lower()
    for suf in ("ies", "es", "s"):
        if len(w) > 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def words(text: str) -> list:
    return [norm(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1 and w not in STOP]


def score(clip: dict, terms: list, phrase: str) -> float:
    tags = set()
    for t in clip.get("tags") or []:
        tags.update(words(t.replace("-", " ")))
        tags.add(norm(t))
    desc = set(words(clip.get("description", "")))
    meta = set(words(f"{clip.get('source_project', '')} {Path(clip.get('path', '')).stem}".replace("-", " ").replace("_", " ")))
    s, hit = 0.0, 0
    for t in terms:
        got = 3.0 if t in tags else 2.0 if t in desc else 1.0 if t in meta else 0.0
        if got:
            hit += 1
        s += got
    if not hit:
        return 0.0
    s *= hit / len(terms)                      # clips matching every word rank first
    if len(terms) > 1 and phrase in (clip.get("description", "").lower()):
        s += 2.0
    if clip.get("verdict") == "broll":
        s += 0.25                              # checked by a judge or the user
    return s


def search(query: str, limit: int = 10, source: str | None = None, include_faces: bool = False) -> list:
    try:
        root = C.library_root(required=False)
    except C.LibraryUnavailable as e:
        C.log(f"note: {e} Returning no results.")
        return []
    if root is None:
        C.log("note: no b-roll library is set up (settings paths.broll_library_dir). Returning no results. "
              "Set one up with the broll-library skill.")
        return []
    cat = C.catalog_path(root)
    if not cat.exists():
        C.log(f"note: the b-roll library at {root} has no catalog yet (nothing harvested). Returning no results.")
        return []
    terms = words(query)
    if not terms:
        return []
    phrase = " ".join(query.lower().split())
    clips = [c for c in C.load_catalog(root)["clips"] if c.get("verdict") not in ("aroll", "junk")]
    if source:
        clips = [c for c in clips if c.get("source_project") == C.slugify(source)]
    ranked = sorted(((score(c, terms, phrase), c) for c in clips), key=lambda x: -x[0])
    ranked = [(s, c) for s, c in ranked if s > 0]
    if not include_faces:
        plain = [(s, c) for s, c in ranked if c.get("verdict") != "broll-face"]
        ranked = plain or ranked
    out = []
    for s, c in ranked[:limit]:
        out.append({"path": str(C.to_abs(root, c["path"])), "start": c["start"], "end": c["end"],
                    "description": c.get("description", ""), "tags": c.get("tags") or [],
                    "source_project": c.get("source_project", ""),
                    "_score": round(s, 2), "_id": c["id"],
                    "_sheet": str(C.to_abs(root, c["sheet"])) if c.get("sheet") else ""})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--source", help="only clips from this source project")
    ap.add_argument("--include-faces", action="store_true", help="also clips with a person on screen")
    ap.add_argument("--verbose", action="store_true", help="with --json: add each hit's id, score and sheet")
    a = ap.parse_args()
    hits = search(a.query, a.limit, a.source, a.include_faces)
    if a.json:
        keys = ("path", "start", "end", "description", "tags", "source_project")
        rows = []
        for h in hits:
            row = {k: h[k] for k in keys}
            if a.verbose:
                row.update(id=h["_id"], score=h["_score"], sheet=h["_sheet"])
            rows.append(row)
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not hits:
        print("no matches")
    for i, h in enumerate(hits, 1):
        print(f"{i}. {h['path']}  [{h['start']:.1f}-{h['end']:.1f}s]  ({h['source_project']})\n"
              f"   {h['description'] or '(no description yet)'}\n   tags: {', '.join(h['tags'])}\n"
              f"   sheet: {h['_sheet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
