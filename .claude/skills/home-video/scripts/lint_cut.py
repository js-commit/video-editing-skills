#!/usr/bin/env python3
"""Check a cut list against the montage rules BEFORE rendering (JSON + headers only, nothing decoded).

  lint_cut.py PROJECT CUT.json

ERROR = it will render wrong (stop). WARN = look at it before the user does. Every check is
an editorial rule from home-video's SKILL.md; the numbers are where real viewers complained.
Exit 1 on any ERROR. Prints the findings, one per line (also as JSON with --json).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402


def lint(p: Path, job: dict) -> tuple:
    cfg = hv.project_cfg(p)
    cuts, end = job["cuts"], float(job["end_s"])
    err, warn = [], []

    def at(i):
        return f"cut {i} @ {hv.tc(cuts[i]['record_s'])} [{cuts[i].get('note', '')[:40]}]"

    def played(i):
        return (cuts[i + 1]["record_s"] if i + 1 < len(cuts) else end) - cuts[i]["record_s"]

    metas = {c["clip"]: hv.meta(p, c["clip"]) for c in cuts}
    for i, c in enumerate(cuts):
        m = metas.get(c["clip"]) or {}
        if not Path(c["file"]).exists():
            err.append(f"{at(i)}: file missing {c['file']}")
            continue
        d = played(i)
        if d < 0.7:
            warn.append(f"{at(i)}: {d:.2f}s is too short to read")
        if d > 4.5 and i + 1 < len(cuts) and not c.get("photo"):
            warn.append(f"{at(i)}: {d:.1f}s shot - long unless the action is the point")
        if not c.get("photo") and c["in_s"] < 0.25:
            warn.append(f"{at(i)}: starts at {c['in_s']}s - phone clips often freeze on a late first frame; start >= 0.3 s")
        if m.get("copy"):
            warn.append(f"{at(i)}: looks like a re-compressed copy ({m['copy']}): is there an original?")
        zf = float((c.get("zoom") or {}).get("z", 1.0))
        if zf > 2.0:
            err.append(f"{at(i)}: zoom {zf}x - far past what any source holds")
        elif m.get("h") and zf > 1.0:
            src_short = min(m["w"], m["h"])
            if src_short / zf < min(job["width"], job["height"]) / 1.15:
                warn.append(f"{at(i)}: zoom {zf}x upscales a {m['w']}x{m['h']} source on the {job['width']}x{job['height']} "
                            "canvas - it will look soft; zoom only as far as the subject needs")
        if m.get("orientation") == "portrait" and job["width"] > job["height"] and c.get("fit") == "cover" and not c.get("zoom"):
            warn.append(f"{at(i)}: portrait clip cropped to fill a landscape frame - keeps only a strip; blur-fill is the default")
        sh = (m.get("motion") or {}).get("shake") or []
        if sh and not c.get("stabilize") and not c.get("photo"):
            a, b = int(c["in_s"] / 0.5), max(int(c["in_s"] / 0.5) + 1, int(c["out_s"] / 0.5))
            seg = sh[a:b]
            if seg and sum(seg) / len(seg) > 3.0:
                warn.append(f"{at(i)}: the survey reads this stretch as shaky ({sum(seg) / len(seg):.1f}) - watch it; "
                            "a calmer stretch, another clip, or \"stabilize\": true if the user agrees")

    # repeats and jump cuts
    by_clip = {}
    for i, c in enumerate(cuts):
        by_clip.setdefault(c["file"], []).append(i)
    for f, idx in by_clip.items():
        for x in idx:
            for y in idx:
                if x < y and cuts[x]["in_s"] < cuts[y]["out_s"] and cuts[y]["in_s"] < cuts[x]["out_s"]:
                    warn.append(f"{at(y)}: replays the source range of cut {x} - the same moment twice")
    for i in range(1, len(cuts)):
        if cuts[i]["file"] == cuts[i - 1]["file"] and cuts[i].get("zoom") == cuts[i - 1].get("zoom"):
            warn.append(f"{at(i)}: same clip and framing as the cut before - reads as a flicker; put another shot between")
    run = 1
    for i in range(1, len(cuts)):
        run = run + 1 if cuts[i]["file"] == cuts[i - 1]["file"] else 1
        if run == 4:
            warn.append(f"{at(i)}: 4 shots in a row from one clip - break it up")

    # structure
    secs = job.get("cues", [])
    if cfg.get("teaser", True):
        first = secs[0]["title"].lower() if secs else ""
        if "teaser" not in first:
            warn.append("no teaser: the montage should open with 10-15 s of its best shots (a section titled 'Teaser'), "
                        "unless the user said no teaser")
        else:
            tcuts = [i for i, c in enumerate(cuts) if c.get("section", "").lower().startswith("teaser")]
            if tcuts:
                tl = sum(played(i) for i in tcuts)
                if not 8 <= tl <= 16:
                    warn.append(f"teaser runs {tl:.1f}s: aim for 10-15 s")
                if tl / len(tcuts) > 2.7:
                    warn.append(f"teaser shots average {tl / len(tcuts):.1f}s: a teaser moves fast (2.1-2.5 s)")
    n_songs = len(secs)
    if n_songs > 2 + int(end // 120):
        warn.append(f"{n_songs} songs in {hv.tc(end)}: change the song only where the mood turns (2-3 for a few minutes)")
    for k, s in enumerate(secs):
        nxt = secs[k + 1]["record_s"] if k + 1 < len(secs) else end
        if nxt - s["record_s"] < 12:
            warn.append(f"cue {Path(s['file']).name} plays only {nxt - s['record_s']:.1f}s - under 12 s a cue does not register")
        if k and abs(s["target_lufs"] - secs[k - 1]["target_lufs"]) > 3:
            warn.append(f"cue {Path(s['file']).name}: {s['target_lufs'] - secs[k - 1]['target_lufs']:+.0f} LU from the cue before "
                        "- over 3 LU needs a reason (a smash cut is one)")
    if played(len(cuts) - 1) > 3.0:
        warn.append(f"final hold {played(len(cuts) - 1):.1f}s: end inside the shot's clean range (<= ~2.7 s)")
    quiet = sum(1 for c in cuts if c.get("bed") is False and not c.get("photo"))
    if cuts and quiet / len(cuts) > 0.25:
        warn.append(f"{quiet} of {len(cuts)} cuts have their own sound switched off: keep it LOW (bed_db -6), not muted")
    ducks = sum(1 for m in job.get("moments", []) if m.get("duck"))
    if ducks > 6:
        warn.append(f"{ducks} moments duck the music: duck only under a spoken line worth hearing")
    if cfg.get("target_s"):
        T = float(cfg["target_s"])
        if abs(end - T) > 0.05 * T:
            warn.append(f"length {hv.tc(end)} vs the {hv.tc(T)} the user asked for")

    # chronology after the teaser
    body = [i for i, c in enumerate(cuts) if not c.get("section", "").lower().startswith("teaser")]
    for a, b in zip(body, body[1:]):
        ta, tb = (metas.get(cuts[a]["clip"]) or {}).get("created", ""), (metas.get(cuts[b]["clip"]) or {}).get("created", "")
        if ta and tb and tb[:10] < ta[:10]:
            warn.append(f"{at(b)}: goes back a day ({tb[:10]} after {ta[:10]}) - intended?")
    return err, warn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("cut")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = hv.project_root(a.project)
    err, warn = lint(p, json.load(open(a.cut)))
    if a.json:
        print(json.dumps({"errors": err, "warnings": warn}, indent=1))
    else:
        for x in err:
            print("ERROR", x)
        for x in warn:
            print("WARN ", x)
        print(f"{len(err)} errors, {len(warn)} warnings")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
