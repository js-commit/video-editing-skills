#!/usr/bin/env python3
"""Check a Short and its title/description before anything is uploaded.

    check_metadata.py SHORT.mp4 --title "..." --description-file desc.txt
    check_metadata.py --spec my-short.spec.json            # file, title and description from the spec

The file must really be a Short (vertical or square, <= 3 minutes, with audio),
and the metadata must not be silently rejected or ignored by YouTube: title
<= 100 characters without < or >, at most 15 hashtags (more and YouTube ignores
all of them; only the first 3 show), no chapter timestamps (Shorts have no
chapters), a disclosure near any affiliate-looking link. Prints a JSON report;
exit 0 = fine (warnings allowed), 3 = fix first.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortslib as sl  # noqa: E402

HASHTAG = re.compile(r"(?<![\w&])#(\w+)")
TIMESTAMP = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?![\d:])")
AFFILIATE = re.compile(r"amzn\.to/|[?&]tag=[\w-]+|[?&]aff(iliate)?[_-]?id=|/ref=|shareasale|awin1\.com|go\.skimresources", re.I)
DISCLOSURE = re.compile(r"affiliate|commission|i earn|sponsored|paid partnership|\b#?ad\b", re.I)


def check(video: str | None, title: str, desc: str) -> dict:
    errors, warnings = [], []
    if video:
        info = sl.media.probe(video)
        w, h, d = info["width"] or 0, info["height"] or 0, info["duration"] or 0
        if w > h:
            errors.append(f"{w}x{h} is landscape: YouTube only treats vertical or square videos as Shorts")
        if d > 180:
            errors.append(f"{d:.1f} s: over 3 minutes is a regular upload, not a Short")
        elif d > 60:
            warnings.append(f"{d:.1f} s: allowed, but the feed rewards tighter Shorts")
        if not info["has_audio"]:
            errors.append("no audio track")
    t = title.strip()
    if not t:
        errors.append("empty title")
    if len(t) > 100:
        errors.append(f"title is {len(t)} characters; YouTube's limit is 100")
    elif len(t) > 70:
        warnings.append(f"title is {len(t)} characters; the player shows about the first 40")
    if "<" in t or ">" in t:
        errors.append("the title contains < or >, which YouTube rejects")
    if t and t.upper() == t and any(c.isalpha() for c in t):
        warnings.append("an all-caps title reads as spam; the captions already shout")
    if HASHTAG.search(t):
        warnings.append("hashtags in the title cost visible characters; put them in the description")
    if len(desc) > 5000:
        errors.append(f"description is {len(desc)} characters; YouTube's limit is 5000")
    elif len(desc) > 1000:
        warnings.append("long description: on a Short almost nobody expands it; 300-800 characters is plenty")
    tags = HASHTAG.findall(desc)
    if len(tags) > 15:
        errors.append(f"{len(tags)} hashtags: over 15 and YouTube ignores all of them")
    elif len(tags) > 3:
        warnings.append(f"{len(tags)} hashtags: only the first 3 show above the title")
    if "shorts" not in [x.lower() for x in tags]:
        warnings.append("no #shorts hashtag (optional: vertical + under 3 min is what makes a Short)")
    if TIMESTAMP.search(desc):
        warnings.append("the description has a timestamp; Shorts have no chapters, so drop it")
    if AFFILIATE.search(desc) and not DISCLOSURE.search(desc):
        errors.append("an affiliate-looking link with no disclosure; say that you earn from it, right after the links")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "title_chars": len(t), "description_chars": len(desc), "hashtags": tags}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--description-file")
    ap.add_argument("--spec", help="take the output file, title and description from a render spec")
    a = ap.parse_args()
    video, title, desc = a.video, a.title, a.description
    if a.spec:
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        video = video or spec.get("output")
        title = title if title is not None else spec.get("title", "")
        desc = desc if desc is not None else spec.get("description", "")
    if a.description_file:
        desc = Path(a.description_file).read_text(encoding="utf-8")
    if title is None:
        ap.error("give --title (or --spec)")
    rep = check(video, title, desc or "")
    print(json.dumps(rep, indent=2))
    return 0 if rep["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
