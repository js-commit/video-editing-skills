#!/usr/bin/env python3
"""YouTube metadata helpers for youtube-release: a release folder drafted from
the video's transcript sidecar, chapter proposals and validation, the links
block from user/links.md, and a final check that writes a paste sheet.

    metadata.py draft <master.mp4 | transcript.json> [--release-dir D] [--count N]
        -> <master-stem>.release/ beside the master with chapters.proposed.txt,
           links.txt (matched from user/links.md), notes.md (hook lines, names,
           tag candidates). Claude then writes titles.txt, description.txt,
           tags.txt and chapters.txt there.
    metadata.py chapters propose <transcript.json> [--count N]
    metadata.py chapters validate <chapters.txt> (--media F | --duration S | --transcript T)
    metadata.py links <transcript.json> [--links-file F]
    metadata.py check <release-dir> [--media master.mp4] [--allow-url URL ...]
        -> validates titles/description/tags/chapters, refuses links that are not
           in user/links.md, writes paste-sheet.md for uploading by hand in Studio.

The transcript must be on the video's own clock: transcribe the final master
(python3 tools/transcribe.py <master>), not the camera original, or the
chapters land in the wrong place after the cuts.

YouTube shows chapters only when the description's time lines start at 00:00,
there are at least 3, and every chapter is at least 10 s long. One bad line
hides them all.

Exit codes: 0 ok, 2 usage / missing input, 3 problems found (fix and re-run),
4 a setting is missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "tools"))
from vidkit import media, settings  # noqa: E402

HERE = Path(__file__).resolve().parent
MIN_CHAPTER_S = 10.0
MAX_CHAPTER_S = 300.0          # longer chapters are allowed, just coarse: a warning
TITLE_MAX, TITLE_SOFT = 100, 70
DESC_MAX_BYTES = 5000
TAGS_CHARS_MAX = 500
STAMP_LINE = re.compile(r"^\s*((?:\d+:)?\d{1,2}:\d{2})\s+(.+?)\s*$")
URL = re.compile(r"https?://[^\s)>\]]+")
STOP = set("""a about above after again against all also am an and any are aren't as at be because been before
being below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during
each few for from further get got gonna had hadn't has hasn't have haven't having he he'd he'll he's her here here's
hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself just kind know let's
like look lot me more most much mustn't my myself no nor not now of off okay on once one only or other ought our ours
ourselves out over own pretty really right same see she she'd she'll she's should shouldn't so some something such
than that that's the their theirs them themselves then there there's these they they'd they'll they're they've thing
things think this those through to too under until up us very want was wasn't way we we'd we'll we're we've well were
weren't what what's when when's where where's which while who who's whom why why's will with won't would wouldn't
yeah yes you you'd you'll you're you've your yours yourself yourselves going go actually basically even still back
make made makes little bit good great just maybe sure say said says""".split())


# ------------------------------------------------------------------ transcript

def load_transcript(path: Path) -> dict:
    try:
        from vidkit.transcript import load_transcript as _load  # the shared sidecar reader
        return _load(path)
    except ImportError:
        return json.loads(Path(path).read_text(encoding="utf-8"))


def transcript_for(target: Path) -> Path:
    """The transcript sidecar for a media file (created if a transcription engine is set), or the file itself."""
    if target.suffix == ".json":
        return target
    side = target.with_name(target.stem + ".transcript.json")
    if side.is_file():
        return side
    try:
        from vidkit.transcript import ensure_transcript
    except ImportError:
        sys.exit(f"no transcript next to {target}. Make one first:\n  python3 {REPO_ROOT / 'tools/transcribe.py'} "
                 f"\"{target}\"")
    return Path(ensure_transcript(target))


def segments(doc: dict) -> list:
    segs = [s for s in doc.get("segments", []) if s.get("text", "").strip()]
    if not segs:
        sys.exit("the transcript has no segments")
    return segs


def duration_of(doc: dict) -> float:
    meta = doc.get("_meta") or {}
    return float(meta.get("source_duration_s") or max(s["end"] for s in segments(doc)))


def hhmmss(seconds: float) -> str:
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def parse_ts(text: str) -> int:
    return sum(int(p) * 60 ** i for i, p in enumerate(reversed(text.split(":"))))


# -------------------------------------------------------------------- chapters

def propose(doc: dict, count: int | None = None) -> list:
    """Candidate chapter starts at the longest pauses between sentences.

    A starting point only: pauses line up with topic changes often, not always,
    and the titles are raw transcript text. Rewrite every title to name what
    the section is about."""
    segs = segments(doc)
    dur = duration_of(doc)
    if dur < 3 * MIN_CHAPTER_S + 1:
        return []
    count = count or max(3, min(15, int(dur // 60) + 1))
    spacing = max(MIN_CHAPTER_S * 3, dur / (count * 2.5))
    gaps = sorted(((cur["start"] - prev["end"], cur["start"], cur["text"].strip())
                   for prev, cur in zip(segs, segs[1:])), reverse=True)
    picked = [(0.0, segs[0]["text"].strip())]
    for _, start, text in gaps:
        if len(picked) >= count:
            break
        if dur - start < spacing / 2:
            continue
        if all(abs(start - p) >= spacing for p, _ in picked):
            picked.append((start, text))
    picked.sort()
    return [(0.0 if i == 0 else start, text) for i, (start, text) in enumerate(picked)]


def load_rows(text: str, source: str = "chapters") -> tuple:
    rows, bad = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        m = STAMP_LINE.match(raw)
        if not m:
            bad.append(f"{source}:{n}: not '<time> <title>': {raw!r}")
            continue
        rows.append((parse_ts(m.group(1)), m.group(1), m.group(2)))
    return rows, bad


def validate_rows(rows: list, duration: float) -> tuple:
    """(errors, warnings, table lines) for a chapter list against YouTube's rules."""
    errors, warnings, table = [], [], []
    if not rows:
        return ["no chapter lines"], warnings, table
    if rows[0][0] != 0:
        errors.append(f"the first chapter must be 00:00, got {rows[0][1]}")
    if len(rows) < 3:
        errors.append(f"YouTube needs at least 3 chapters, got {len(rows)}")
    for i, (start, ts, title) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else duration
        length = end - start
        note = ""
        if i and start <= rows[i - 1][0]:
            errors.append(f"{ts} does not come after {rows[i - 1][1]}")
        elif length < MIN_CHAPTER_S:
            errors.append(f"{ts} {title!r} is {length:.0f}s (under {MIN_CHAPTER_S:.0f}s hides every chapter)")
            note = "  <-- too short"
        elif length > MAX_CHAPTER_S:
            warnings.append(f"{ts} {title!r} is {length:.0f}s: consider splitting it")
        if len(title) > 60:
            warnings.append(f"{ts} title is {len(title)} characters: keep chapter names short")
        table.append(f"{ts:>8}  {length:6.0f}s  {title}{note}")
    return errors, warnings, table


# ----------------------------------------------------------------------- links

def links_file(override: str | None = None) -> Path:
    return Path(override).expanduser() if override else (settings.USER_DIR / "links.md")


def parse_links(path: Path) -> dict:
    """user/links.md -> {"always": [...], "disclosure": [lines], "items": [{label, url, keywords, section}]}."""
    out = {"always": [], "disclosure": [], "items": []}
    if not path.is_file():
        return out
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        if section == "disclosure":
            out["disclosure"].append(line.lstrip("- ").strip())
            continue
        m = re.match(r"^[-*]\s*(.+?):\s*(https?://\S+)\s*(?:\((?:keywords?|match):\s*([^)]*)\))?\s*$", line, re.I)
        if not m:
            continue
        item = {"label": m.group(1).strip(), "url": m.group(2).strip(), "section": section,
                "keywords": [k.strip().lower() for k in (m.group(3) or "").split(",") if k.strip()]}
        (out["always"] if section == "always" else out["items"]).append(item)
    return out


def matched_links(doc: dict, links: dict) -> list:
    text = " " + " ".join(s["text"] for s in segments(doc)).lower() + " "
    hits = []
    for it in links["items"]:
        needles = it["keywords"] or [it["label"].lower()]
        if any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text) for n in needles):
            hits.append(it)
    return hits


def links_block(doc: dict, links: dict) -> str:
    hits = matched_links(doc, links)
    lines = [f"{it['label']}: {it['url']}" for it in hits]
    if hits and links["disclosure"]:
        lines += [""] + links["disclosure"]
    if links["always"]:
        lines += ([""] if lines else []) + [f"{it['label']}: {it['url']}" for it in links["always"]]
    return "\n".join(lines)


def known_urls(links: dict) -> set:
    return {it["url"].rstrip(".,") for it in links["items"] + links["always"]}


# --------------------------------------------------------------------- notes

def tag_candidates(doc: dict, n: int = 20) -> list:
    words = re.findall(r"[a-z][a-z0-9'+-]{2,}", " ".join(s["text"] for s in segments(doc)).lower())
    words = [w.strip("'-") for w in words]
    uni = Counter(w for w in words if w not in STOP and len(w) >= 4)
    bi = Counter(f"{a} {b}" for a, b in zip(words, words[1:]) if a not in STOP and b not in STOP)
    pool = [(c * 1.5, w) for w, c in bi.items() if c >= 2] + [(c, w) for w, c in uni.items() if c >= 2]
    seen, out = set(), []
    for _, w in sorted(pool, reverse=True):
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= n:
            break
    return out


def proper_names(doc: dict, n: int = 15) -> list:
    """Capitalized phrases that are not sentence starts: likely product, place or brand names."""
    c = Counter()
    for s in segments(doc):
        toks = s["text"].split()
        run = []
        for i, t in enumerate(toks + [""]):
            w = re.sub(r"[^\w'-]", "", t)
            start = i == 0 or toks[i - 1].endswith((".", "!", "?"))
            name_like = bool(w) and w[:1].isupper() and not start and w.lower() not in STOP \
                and w not in ("I", "I'm", "I've", "I'll", "I'd")
            if name_like:
                run.append(w)
            if run and (not name_like or t.endswith((",", ".", "!", "?", ";", ":"))):
                c[" ".join(run)] += 1
                run = []
    return [w for w, _ in c.most_common(n)]


# ----------------------------------------------------------------------- draft

def release_dir_for(master: Path) -> Path:
    return master.with_name(master.stem + ".release")


def cmd_draft(a) -> int:
    target = Path(a.target).expanduser().resolve()
    if not target.exists():
        sys.exit(f"not found: {target}")
    tpath = transcript_for(target)
    doc = load_transcript(tpath)
    dur = duration_of(doc)
    master = None if target.suffix == ".json" else target
    rdir = Path(a.release_dir).expanduser().resolve() if a.release_dir else \
        release_dir_for(master or target.with_name(target.name.replace(".transcript.json", "")))
    rdir.mkdir(parents=True, exist_ok=True)
    notes = [f"# Release notes (scratch: Claude reads this, the user never has to)", "",
             f"- transcript: {tpath}", f"- duration: {hhmmss(dur)} ({dur:.1f}s)"]
    if master:
        mdur = media.duration(master)
        notes.append(f"- master: {master} ({mdur:.1f}s)")
        last_word = max(s["end"] for s in segments(doc))
        if abs(mdur - dur) > 2.0 or last_word > mdur + 1.0:
            notes.append(f"- WARNING: transcript length {dur:.1f}s vs master {mdur:.1f}s: the transcript is "
                         f"probably not of this cut. Transcribe the master itself before writing chapters.")
        dur = mdur
    rows = propose(doc, a.count)
    prop = rdir / "chapters.proposed.txt"
    prop.write_text("".join(f"{hhmmss(s)} {t[:70]}\n" for s, t in rows), encoding="utf-8")
    links = parse_links(links_file(a.links_file))
    block = links_block(doc, links)
    (rdir / "links.txt").write_text(block + ("\n" if block else ""), encoding="utf-8")
    segs = segments(doc)
    opening = " ".join(s["text"].strip() for s in segs[:4])
    closing = " ".join(s["text"].strip() for s in segs[-3:])
    notes += ["", "## Opening (hook material)", opening, "", "## Closing (call to action material)", closing, "",
              "## Names said on camera (check spelling before using)", ", ".join(proper_names(doc)) or "(none)", "",
              "## Tag candidates (most frequent phrases)", ", ".join(tag_candidates(doc)) or "(none)", "",
              "## Links", (f"{len(matched_links(doc, links))} matched from {links_file(a.links_file)}"
                           if links_file(a.links_file).is_file() else
                           "no user/links.md: no links block (never invent links)"), "",
              "## Still to write here", "- titles.txt: 3-5 options, one per line, mark the pick with a leading *",
              "- chapters.txt: from chapters.proposed.txt, every title rewritten", "- description.txt: the full text "
              "(hook, links.txt, chapters, the rest; see reference/description-guide.md)",
              "- tags.txt: comma-separated", ""]
    (rdir / "notes.md").write_text("\n".join(notes), encoding="utf-8")
    print(json.dumps({"release_dir": str(rdir), "transcript": str(tpath), "duration_s": round(dur, 2),
                      "chapters_proposed": str(prop), "chapter_count": len(rows),
                      "links": str(rdir / "links.txt"), "notes": str(rdir / "notes.md")}, indent=2))
    return 0


# ----------------------------------------------------------------------- check

def read_titles(path: Path) -> tuple:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    pick = next((ln.lstrip("* ").strip() for ln in lines if ln.startswith("*")), None)
    titles = [ln.lstrip("* ").strip() for ln in lines]
    return (pick or (titles[0] if titles else "")), titles


def cmd_check(a) -> int:
    rdir = Path(a.release_dir).expanduser().resolve()
    errors, warnings = [], []
    tfile, dfile, gfile = rdir / "titles.txt", rdir / "description.txt", rdir / "tags.txt"
    for f in (tfile, dfile):
        if not f.is_file():
            errors.append(f"missing {f}")
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 3
    pick, titles = read_titles(tfile)
    for t in titles:
        if len(t) > TITLE_MAX:
            errors.append(f"title over {TITLE_MAX} characters ({len(t)}): {t!r}")
        elif len(t) > TITLE_SOFT:
            warnings.append(f"title is {len(t)} characters, phones cut around 60-70: {t!r}")
        if re.search(r"[<>]", t):
            errors.append(f"title contains < or >: {t!r}")
    if not pick:
        errors.append("titles.txt is empty")
    desc = dfile.read_text(encoding="utf-8").strip("\n")
    nbytes = len(desc.encode("utf-8"))
    if nbytes > DESC_MAX_BYTES:
        errors.append(f"description is {nbytes} bytes, YouTube's limit is {DESC_MAX_BYTES}")
    if re.search(r"[<>]", desc):
        errors.append("description contains < or >: YouTube rejects it")
    if "TODO" in desc or re.search(r"\[(?:hook|link|todo|title)[^\]]*\]", desc, re.I):
        errors.append("description still has a placeholder")
    # duration
    master = Path(a.media).expanduser().resolve() if a.media else None
    if master is None:
        rname = rdir.name[:-len(".release")] if rdir.name.endswith(".release") else None
        cands = [p for p in rdir.parent.glob(f"{rname}.*") if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".m4v")] \
            if rname else []
        master = cands[0] if cands else None
    duration = media.duration(master) if master and master.is_file() else None
    # chapters inside the description
    chap_lines = "\n".join(ln for ln in desc.splitlines() if STAMP_LINE.match(ln))
    rows, _ = load_rows(chap_lines, "description")
    if rows:
        if duration is None:
            warnings.append("no master found: chapter lengths not checked against the video (pass --media)")
        e, w, table = validate_rows(rows, duration or rows[-1][0] + MIN_CHAPTER_S)
        errors += e
        warnings += w
    else:
        table = []
        warnings.append("no chapters in the description (fine for a short video; chapters help longer ones)")
    cfile = rdir / "chapters.txt"
    if cfile.is_file() and rows:
        crows, _ = load_rows(cfile.read_text(encoding="utf-8"), "chapters.txt")
        if [r[0] for r in crows] != [r[0] for r in rows]:
            warnings.append("chapters.txt and the chapters inside description.txt differ: the description wins")
    # hashtags
    tags_in_desc = re.findall(r"(?<!\w)#\w+", desc)
    if len(tags_in_desc) > 3:
        warnings.append(f"{len(tags_in_desc)} hashtags: only the first three show above the title; keep it to 3")
    # links
    links = parse_links(links_file(a.links_file))
    allowed = known_urls(links) | {u.rstrip(".,") for u in (a.allow_url or [])}
    for u in URL.findall(desc):
        if u.rstrip(".,") not in allowed:
            errors.append(f"link not in {links_file(a.links_file)}: {u} (never invent links: add it there, or pass "
                          f"--allow-url for a link the user gave you)")
    # tags
    tags = []
    if gfile.is_file():
        tags = [t.strip() for t in re.split(r"[,\n]", gfile.read_text(encoding="utf-8")) if t.strip()]
        budget = sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)
        if budget > TAGS_CHARS_MAX:
            errors.append(f"tags use {budget} of YouTube's {TAGS_CHARS_MAX} characters")
        if any(re.search(r"[<>]", t) for t in tags):
            errors.append("a tag contains < or >")
    # paste sheet. The picked thumbnails (thumb-1.jpg ...) live in the folder that holds the
    # master (youtube-thumbnails' thumb_pool.py pick), one level above the release folder.
    thumbs = sorted(p for d in (rdir, rdir.parent) for p in d.glob("thumb*")
                    if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    sheet = rdir / "paste-sheet.md"
    sheet.write_text(paste_sheet(pick, titles, desc, tags, thumbs, master), encoding="utf-8")
    out = {"ok": not errors, "title": pick, "errors": errors, "warnings": warnings, "chapters": table,
           "description_bytes": nbytes, "paste_sheet": str(sheet),
           "thumbnail": str(thumbs[0]) if thumbs else None}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if not errors else 3


def paste_sheet(pick, titles, desc, tags, thumbs, master) -> str:
    alts = [t for t in titles if t != pick]
    lines = ["# Upload by hand in YouTube Studio", "",
             "studio.youtube.com > Create (top right) > Upload videos > pick the file:", "",
             f"    {master}" if master else "    (the final master)", "",
             "## Details page", "", "**Title**", "", "```", pick, "```"]
    if alts:
        lines += ["", "Other options: " + " | ".join(alts)]
    lines += ["", "**Description** (chapters are the time lines inside it)", "", "```", desc, "```", ""]
    if thumbs:
        lines += [f"**Thumbnail**: Upload file > {thumbs[0]}", ""]
    kids = settings.get("youtube.made_for_kids")
    kids_line = ("" if kids is None else f" Your standing answer: {'yes' if kids else 'no'}, made for kids.")
    lines += ["**Audience**: answer 'made for kids' honestly (a legal declaration)." + kids_line, "",
              "Click **Show more**:", ""]
    if tags:
        lines += ["**Tags**", "", "```", ", ".join(tags), "```", ""]
    synth, lang, cat = (settings.get(k) for k in ("youtube.contains_synthetic_media", "youtube.language",
                                                   "youtube.category"))
    privacy = settings.get("youtube.default_privacy", default="unlisted")
    lines += ["**Altered content**: yes only for realistic AI-made or altered people, places or events."
              + ("" if synth is None else f" Your standing answer: {'yes' if synth else 'no'}."),
              "**Language / Category**: set them; they help captions and search."
              + (f" Yours: {lang or 'not set'} / {cat or 'not set'}." if (lang or cat) else ""), "",
              "## Video elements, Checks", "", "Add an end screen if you like; wait for the copyright check.", "",
              "## Visibility", "", f"Suggested: {privacy}. Unlisted for a review link, Public or Schedule to release.",
              "", "Then give Claude the video's link (it goes in link.txt in this folder).", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------ main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draft", help="release folder + notes from the transcript")
    p.add_argument("target", help="the final master (its <stem>.transcript.json is used) or a transcript json")
    p.add_argument("--release-dir")
    p.add_argument("--count", type=int, help="how many chapters to propose (default: about one per minute)")
    p.add_argument("--links-file", help="default: user/links.md")
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("chapters", help="propose or validate chapters")
    csub = p.add_subparsers(dest="ccmd", required=True)
    q = csub.add_parser("propose")
    q.add_argument("transcript")
    q.add_argument("--count", type=int)
    q = csub.add_parser("validate")
    q.add_argument("chapters")
    src = q.add_mutually_exclusive_group(required=True)
    src.add_argument("--media")
    src.add_argument("--duration", type=float)
    src.add_argument("--transcript")

    p = sub.add_parser("links", help="the links block for this video from user/links.md")
    p.add_argument("transcript")
    p.add_argument("--links-file")

    p = sub.add_parser("check", help="validate a release folder and write paste-sheet.md")
    p.add_argument("release_dir")
    p.add_argument("--media", help="the master (default: the video beside the .release folder)")
    p.add_argument("--allow-url", action="append", help="a link the user gave you that is not in links.md")
    p.add_argument("--links-file")
    p.set_defaults(func=cmd_check)

    a = ap.parse_args(argv)
    try:
        if a.cmd == "chapters" and a.ccmd == "propose":
            doc = load_transcript(transcript_for(Path(a.transcript).expanduser().resolve()))
            rows = propose(doc, a.count)
            if not rows:
                print("# too short for chapters (YouTube needs 3 chapters of 10 s or more)")
                return 0
            print(f"# {len(rows)} candidate chapters over {hhmmss(duration_of(doc))}: REWRITE every title")
            for s, t in rows:
                print(f"{hhmmss(s)} {t[:70]}")
            return 0
        if a.cmd == "chapters":
            rows, bad = load_rows(Path(a.chapters).read_text(encoding="utf-8"), a.chapters)
            dur = (a.duration if a.duration is not None else media.duration(a.media) if a.media
                   else duration_of(load_transcript(Path(a.transcript))))
            errors, warnings, table = validate_rows(rows, dur)
            print("\n".join(table))
            for w in warnings:
                print(f"warn: {w}")
            if bad or errors:
                print("INVALID:\n  " + "\n  ".join(bad + errors))
                return 3
            print(f"VALID: {len(rows)} chapters over {hhmmss(dur)}")
            return 0
        if a.cmd == "links":
            block = links_block(load_transcript(Path(a.transcript)), parse_links(links_file(a.links_file)))
            print(block or f"# no matching links (file: {links_file(a.links_file)})")
            return 0
        return a.func(a)
    except settings.SettingMissing as e:
        settings.exit_missing(e)


if __name__ == "__main__":
    sys.exit(main())
