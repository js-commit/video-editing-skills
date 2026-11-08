#!/usr/bin/env python3
"""aroll-draft's cut list(s) -> the record clock: recipe_v0.json + the edited transcript to plan b-roll against.

    timeline.py TAKE.mp4 [PICKUP.mp4 ...] [--name NAME] [--size WxH] [--lufs -14] [--work DIR]
    timeline.py --project <project folder or name>          # every *.aroll.tb.json under its footage folder

Input is aroll-draft's cut, `<stem>.aroll.tb.json` next to each take (ordered keep/remove ops, seconds), plus the
`<stem>.transcript.json` sidecar. Pass the takes in the order the video plays (a main take, then a pickup). A take
with no cut list yet is an error: run the aroll-draft skill on it first. A `<stem>.audio_sync.json` beside a take
(sync_audio.py: a separately recorded mic) becomes the recipe's "take_audio".

Writes into <project>/<work>/talking-head/ (the project is found from the first take; outside a project, next to it):
  recipe_v0.json          fps / size / lufs + the a-roll keeps in play order, empty "broll" and "needs"
  edited_transcript.json  every kept word on the record clock: [{"w", "s", "e"}]
  edited_transcript.md    one line per sentence, "[m:ss.s-m:ss.s] text", jump cuts marked "|"  (what the planner reads)
The fps is the first take's own rate, kept as a fraction so frame counts never drift; the canvas is its size.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402


def source_for(tb):
    stem = tb[: -len(".aroll.tb.json")]
    for p in sorted(glob.glob(glob.escape(stem) + ".*")):
        if os.path.splitext(p)[1].lower() in C.VIDEO_EXT:
            return p
    sys.exit(f"no source video next to {tb}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("takes", nargs="*", help="a-roll source files, in play order")
    ap.add_argument("--project", help="find every *.aroll.tb.json under this project's footage folder")
    ap.add_argument("--name", help="output name (default: the project folder name)")
    ap.add_argument("--size", help="the edit canvas WxH (default: the first take's size)")
    ap.add_argument("--lufs", type=float, default=-14.0, help="loudness target, integrated LUFS (YouTube: -14)")
    ap.add_argument("--work", help="where recipes go (default <project>/<work>/talking-head)")
    a = ap.parse_args()
    try:
        if a.takes:
            pairs = []
            for src in a.takes:
                src = str(Path(src).resolve())
                tb = os.path.splitext(src)[0] + ".aroll.tb.json"
                if not os.path.exists(tb):
                    sys.exit(f"no cut list {tb}: run the aroll-draft skill on {os.path.basename(src)} first")
                pairs.append((src, tb))
            proj = C.project_root(pairs[0][0])
        elif a.project:
            proj = C.settings.project_dir(a.project)
            foot = proj / C.settings.layout("footage")
            tbs = sorted(glob.glob(str(foot / "**" / "*.aroll.tb.json"), recursive=True))
            if not tbs:
                sys.exit(f"no *.aroll.tb.json under {foot}: run the aroll-draft skill first")
            pairs = [(source_for(t), t) for t in tbs]
        else:
            ap.error("give the take(s) or --project")
        work = Path(a.work).resolve() if a.work else C.work_dir(proj)
        work.mkdir(parents=True, exist_ok=True)
    except C.settings.SettingMissing as e:
        C.settings.exit_missing(e)

    _, fps, w0, h0 = R.probe(pairs[0][0])
    W, H = map(int, a.size.lower().split("x")) if a.size else (w0, h0)
    keeps = []
    for src, tb in pairs:
        ops = C.read_json(tb)
        if isinstance(ops, dict):           # tolerate {"ops": [...]} / {"cuts": [...]} wrappers
            ops = ops.get("ops") or ops.get("cuts") or []
        for c in ops:
            if c.get("operation", "keep") == "keep":
                keeps.append({"file": src, "in_s": round(float(c["start"]), 4),
                              "out_s": round(float(c["start"]) + float(c["duration"]), 4)})
    if not keeps:
        sys.exit("the cut lists keep nothing")
    recipe = {"name": a.name or proj.name, "project": str(proj), "fps": f"{fps.numerator}/{fps.denominator}",
              "width": W, "height": H, "lufs": a.lufs, "aroll": keeps, "broll": [], "needs": [], "overlays": []}
    synced = {}
    for src, _ in pairs:
        side = os.path.splitext(src)[0] + ".audio_sync.json"
        if os.path.exists(side):
            s = C.read_json(side)
            synced[src] = {"file": s["audio"], "offset_s": s["offset_s"], "rate": s["rate"]}
    if synced:
        recipe["take_audio"] = synced

    by_src = {}
    for src, _ in pairs:
        ws = C.words_of(src)
        if ws is None:
            sys.exit(f"no transcript sidecar {C.transcript_path(src)}: run "
                     f"python3 {C.REPO / 'tools' / 'transcribe.py'} \"{src}\"")
        by_src[src] = ws
    words, lines, cur, cut_marks = [], [], [], R.cuts(recipe)
    for k in R.aroll_frames(recipe):        # a word belongs to the keep holding its midpoint
        k0, k1, r0 = k["in_s"], k["in_s"] + float(k["n"] / fps), float(k["rec_f"] / fps)
        first = True
        for w in by_src[k["file"]]:
            if k0 <= (w["start"] + w["end"]) / 2 < k1:
                s, e = r0 + max(w["start"], k0) - k0, r0 + min(w["end"], k1) - k0
                words.append({"w": w["word"].strip(), "s": round(s, 3), "e": round(e, 3)})
                if first and k["rec_f"] in cut_marks:
                    cur.append({"w": "|", "s": s, "e": s})
                first = False
                cur.append(words[-1])
                if words[-1]["w"].endswith((".", "?", "!")) and len(cur) >= 6:
                    lines.append(cur)
                    cur = []
    if cur:
        lines.append(cur)

    def tc(t):
        return f"{int(t // 60)}:{t % 60:04.1f}"
    total = float(R.total_frames(recipe) / fps)
    md = [f"# {recipe['name']} - edited a-roll on the record clock ({tc(total)}, {len(keeps)} keeps; '|' = a jump cut)", ""]
    md += [f"[{tc(l[0]['s'])}-{tc(l[-1]['e'])}] " + " ".join(x["w"] for x in l) for l in lines]
    (work / "edited_transcript.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    C.write_json(work / "edited_transcript.json", words, indent=None)
    out = work / "recipe_v0.json"
    C.write_json(out, recipe)
    print(json.dumps({"recipe": str(out), "fps": recipe["fps"], "size": f"{W}x{H}", "keeps": len(keeps),
                      "words": len(words), "timeline_s": round(total, 2), "transcript": str(work / "edited_transcript.md")}))


if __name__ == "__main__":
    main()
