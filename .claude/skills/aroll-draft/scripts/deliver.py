#!/usr/bin/env python3
"""Deliver an aroll-draft run: put the cut list and revision next to the video,
write the Resolve timeline files, and build the review report.

  <video folder>/<stem>.aroll.tb.json        cut list (TimeBolt / Video Haircut format)
  <video folder>/<stem>.aroll.revision.json  transcript with "cut": true/false per word
                                             (Video Haircut user_revision format)
  <video folder>/<stem>.aroll.xml / .edl     timelines for DaVinci Resolve (File > Import > Timeline)
  <work>/report.md                           the review points, in source AND first-cut time

Existing outputs are moved to <work>/previous/ first, never silently replaced.

Usage:
  python3 deliver.py <work> <video> [--no-exports]

Reads <work>/<stem>.aroll.tb.json (+ .decisions.json), <work>/revision.json,
<work>/transcript.json and <work>/retake_flags.json when present. Prints a JSON
summary (the same facts as report.md).

Exit codes: 0 ok, 2 missing input.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from export_timeline import export  # noqa: E402


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def load(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def hms(t):
    t = max(0.0, float(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}" if h else f"{int(m)}:{s:05.2f}"


def nearest_out(keeps, t):
    """First-cut time of the seam nearest source second t."""
    acc = 0.0
    for k in keeps:
        if t < k["start"]:
            return acc
        if t < k["start"] + k["duration"]:
            return acc + (t - k["start"])
        acc += k["duration"]
    return acc


def place(src: Path, dst: Path, backup: Path):
    if dst.exists():
        backup.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(backup / f"{dst.name}.{time.strftime('%Y%m%d-%H%M%S')}"))
    shutil.copyfile(src, dst)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("work")
    p.add_argument("video")
    p.add_argument("--no-exports", action="store_true", help="skip the .xml/.edl timeline files")
    args = p.parse_args()

    work = Path(args.work).expanduser().absolute()
    video = Path(args.video).expanduser().absolute()
    stem = video.stem
    cuts = work / f"{stem}.aroll.tb.json"
    revision = work / "revision.json"
    for f in (cuts, revision):
        if not f.exists():
            die(f"missing {f}: run the earlier steps first")
    ops = load(cuts)
    keeps = [o for o in ops if o["operation"] == "keep"]
    decisions = load(Path(str(cuts) + ".decisions.json"), {})
    rev = load(revision)
    flags = load(work / "retake_flags.json", {}).get("flags", [])
    prep = load(work / "prepare.json", {})

    backup = work / "previous"
    dest = video.parent
    out_cuts = dest / f"{stem}.aroll.tb.json"
    out_rev = dest / f"{stem}.aroll.revision.json"
    place(cuts, out_cuts, backup)
    place(revision, out_rev, backup)
    exports = {}
    if not args.no_exports:
        for ext in ("xml", "edl"):
            old = dest / f"{stem}.aroll.{ext}"
            if old.exists():
                backup.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(backup / f"{old.name}.{time.strftime('%Y%m%d-%H%M%S')}"))
        exports = export(str(out_cuts), str(video), str(dest))

    words = [w for s in rev["segments"] for w in s.get("words") or [] if w["word"].strip()]
    cut_words = sum(1 for w in words if w.get("cut"))
    src_dur = prep.get("duration_s") or (ops[-1]["start"] + ops[-1]["duration"] if ops else 0)
    cut_dur = sum(k["duration"] for k in keeps)

    review = []   # (kind, source_s, first_cut_s, text)
    for h in decisions.get("hard_seams", []):
        if h["fix"].startswith("UNRESOLVED"):
            review.append(("clipped-word seam", h["t"], nearest_out(keeps, h["t"]),
                           f"a cut lands on speech ({h['removed_s']} s removed); listen and nudge it"))
    for s in decisions.get("slivers", []):
        if "absorbed_s" not in s:
            review.append(("short clip", s["in"], nearest_out(keeps, s["in"]),
                           f"a {s['out'] - s['in']:.2f} s keep (\"{s['text']}\") reads as a flicker; "
                           "extend or remove it"))
    for pz in decisions.get("long_pauses", []):
        m = pz.get("motion_x_speech")
        hint = "" if m is None else (" - picture is static, probably dead air" if m < 0.35 else
                                     " - picture moves, maybe a silent demo" if m > 1 else "")
        review.append(("long pause", pz["start"], nearest_out(keeps, pz["start"]),
                       f"{pz['duration']} s without speech inside a keep{hint}; cut it if it is dead air"))
    for f in flags:
        if f.get("suspect") and f.get("kept", True):
            review.append(("possible hidden retake", f["start_s"], f.get("output_s", nearest_out(keeps, f["start_s"])),
                           f"the word {f['word']!r} lasts {f['duration_s']} s with sound after it: the transcript may "
                           "have swallowed a repeated take; listen and cut the flubbed one"))
    review.sort(key=lambda r: r[1])

    # Cuts the smoother put back on purpose: a filler or stutter glued to speech
    # with no pause to cut on would clip the kept words, so it stays in. List
    # them so the user doesn't think the edit missed them.
    restored = []   # (source_s, first_cut_s, text)
    for h in decisions.get("hard_seams", []):
        if h.get("fix") == "restored":
            end, start = h["t"], h["t"] - h.get("removed_s", 0)
            text = " ".join(w["word"].strip() for w in words
                            if w.get("cut") and w.get("start") is not None
                            and start - 0.05 <= w["start"] <= end + 0.05)
            restored.append((start, nearest_out(keeps, start), text or "a short filler"))
    restored.sort()

    summary = {
        "source": str(video),
        "source_duration_s": round(src_dur, 2),
        "cut_duration_s": round(cut_dur, 2),
        "removed_pct": round(100 * (1 - cut_dur / src_dur), 1) if src_dur else None,
        "clips": len(keeps),
        "words_total": len(words), "words_cut": cut_words,
        "hard_seams_unresolved": sum(1 for r in review if r[0] == "clipped-word seam"),
        "word_crossing_boundaries": len(decisions.get("word_crossings", [])),
        "outputs": {"cut_list": str(out_cuts), "revision": str(out_rev), **exports.get("written", {})},
        "timeline_name": exports.get("timeline_name"),
        "review_points": [{"kind": k, "source": hms(s), "first_cut": hms(o), "source_s": round(s, 3),
                           "first_cut_s": round(o, 3), "note": n} for k, s, o, n in review],
        "kept_on_purpose": [{"source": hms(s), "first_cut": hms(o), "words": t} for s, o, t in restored],
    }

    lines = [f"# First cut: {video.name}", "",
             f"- {hms(src_dur)} raw -> {hms(cut_dur)} first cut ({summary['removed_pct']}% removed), "
             f"{len(keeps)} clips, {cut_words} of {len(words)} words cut",
             f"- cut list: {out_cuts}", f"- revision: {out_rev}"]
    for kind, path in exports.get("written", {}).items():
        lines.append(f"- timeline ({kind}): {path}")
    lines += ["", "## Review points (times in the first cut, then in the raw take)", ""]
    if review:
        for k, s, o, n in review:
            lines.append(f"- {hms(o)} (raw {hms(s)}) {k}: {n}")
    else:
        lines.append("- none: play it through once anyway")
    if restored:
        lines += ["", "## Left in on purpose", "",
                  "These fillers or stutters run straight into the next word with no pause, so cutting them "
                  "would clip the words you kept. Trim them by hand if you want them gone:", ""]
        for s_, o, t in restored:
            lines.append(f"- {hms(o)} (raw {hms(s_)}): \"{t}\"")
    report = work / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary["report"] = str(report)
    with open(work / "report.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
