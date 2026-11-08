#!/usr/bin/env python3
"""Put the rendered motion clips into a talking-head recipe: full-frame cutaways as b-roll bricks, panels as overlays.

    place.py <motion>/plan.json <work>/recipe_vN.json <work>/recipe_vM.json [--yield-broll]

plan.json (written at the plan step; schema in the SKILL.md):
  {"recipe": "recipe_v3.json",                      # the recipe whose record clock "in"/"out" are on (beside the plan's
                                                    #   folder, i.e. in <work>/talking-head/)
   "clips": [{"id": "01", "name": "pill-to-chart", "kind": "full" | "panel", "in": 32.40, "out": 39.20,
              "line": "the words it covers", "why": "...", "illustrative": "what is not a real figure"}]}

Each clip's file is <motion>/out/<id>-<name>.mp4 (full) or .mov / .webm (panel), render.py's default. The output
recipe is recipe_vN with every earlier motion entry (a file under <motion>/out/) replaced by the plan's:
  full  -> "broll":    {"record_s", "dur", "file", "in_s": 0, "why": "motion <id>: ..."} - the lint's flicker rules
           apply, and the clip's 0.5 s tail hold lets `recipe.py lint --fix` stretch it onto a nearby jump cut;
  panel -> "overlays": {"record_s", "dur", "file", "fade": 0, "why"} - the clip animates its own entrance and exit.

When vN's a-roll differs from the plan's recipe (a notes round moved keeps), each in/out is carried through the
source frame for frame (talking-head-ffmpeg recipe.map_span). A clip whose in- or out-point was cut is an ERROR
(re-plan it); one whose words changed under it is a WARN (re-time its cues with cues.py --in and re-render).

A full cutaway over an existing b-roll brick is an ERROR unless --yield-broll, which trims the brick to the side the
cutaway leaves (or drops it when under 1.5 s would remain) and lists what it did. Decide that in the plan.
Runs the talking-head lint on the result (exit 1 on any ERROR).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "talking-head-ffmpeg" / "scripts"))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402


def text_between(r, words, a, b):
    return " ".join(w["w"] for w in words if a <= (w["s"] + w["e"]) / 2 < b)


def clip_file(out_dir, c):
    stem = out_dir / f"{c['id']}-{c['name']}"
    exts = [".mp4"] if c["kind"] == "full" else [".mov", ".webm"]
    for e in exts:
        if Path(str(stem) + e).exists():
            return str(stem) + e
    return str(stem) + exts[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("recipe")
    ap.add_argument("out")
    ap.add_argument("--yield-broll", action="store_true")
    a = ap.parse_args()
    plan_p = Path(a.plan).resolve()
    motion = plan_p.parent
    plan = C.read_json(plan_p)
    r = C.read_json(a.recipe)
    base_p = Path(plan["recipe"]) if os.path.isabs(plan["recipe"]) else motion.parent / plan["recipe"]
    base = C.read_json(base_p)
    fps = R.fps_of(r)
    frame = 1 / float(fps)
    same = [(k["file"], k["in_s"], k["out_s"]) for k in base["aroll"]] == \
           [(k["file"], k["in_s"], k["out_s"]) for k in r["aroll"]]
    out_dir = motion / "out"
    prefix = str(out_dir) + os.sep
    r["broll"] = [b for b in r.get("broll", []) if not b["file"].startswith(prefix)]
    r["overlays"] = [o for o in r.get("overlays", []) if not o["file"].startswith(prefix)]
    bw = R.record_words(base)[0] if not same else None
    nw = R.record_words(r)[0] if not same else None
    errs, warns, placed = [], [], []
    for c in plan["clips"]:
        tag = f"motion {c['id']}"
        f = clip_file(out_dir, c)
        if not os.path.exists(f):
            errs.append(f"{tag}: not rendered yet ({f})")
            continue
        f0 = round(c["in"] * fps)
        f1 = f0 + round((c["out"] - c["in"]) * fps)
        if not same:
            m = R.map_span(base, r, f0, f1)
            if m is None:
                errs.append(f"{tag}: its in- or out-point's moment was cut from the a-roll - re-plan it")
                continue
            n0, n1 = m
            if text_between(base, bw, f0 * frame, f1 * frame) != text_between(r, nw, n0 * frame, n1 * frame):
                warns.append(f"{tag}: the words under it changed ({(f1 - f0) * frame:.2f}s -> {(n1 - n0) * frame:.2f}s) - "
                             f"re-time its cues (cues.py --in {n0 * frame:.3f}) and re-render")
            f0, f1 = n0, n1
        t0, dur = round(f0 * frame, 4), round((f1 - f0) * frame, 4)
        t1 = t0 + dur
        clip_dur = R.probe(f)[0]
        if clip_dur + 0.02 < dur:
            errs.append(f"{tag}: the clip is {clip_dur:.2f}s, its slot {dur:.2f}s - raise T to the slot + 0.5 and re-render")
            continue
        why = f"{tag}: {c.get('why') or c.get('line', '')}"
        if c["kind"] == "full":
            for b in list(r["broll"]):
                bs, be = b["record_s"], b["record_s"] + b["dur"]
                if be <= t0 or bs >= t1 or b["file"].startswith(prefix):
                    continue
                if not a.yield_broll:
                    errs.append(f"{tag} covers b-roll brick @ {bs:.2f}-{be:.2f} ({b.get('why', '')[:60]}) - trim or drop "
                                "it, or --yield-broll")
                    continue
                head, tail = t0 - bs, be - t1
                sp = float(b.get("speed", 1.0))
                if head >= max(tail, R.SHORT_BRICK_S):
                    b["dur"] = round(head, 4)
                    warns.append(f"yield: brick @ {bs:.2f} trimmed to end at {t0:.2f}")
                elif tail >= R.SHORT_BRICK_S:
                    b["in_s"] = round(b["in_s"] + (t1 - bs) * sp, 4)
                    b["record_s"] = round(t1, 4)
                    b["dur"] = round(tail, 4)
                    warns.append(f"yield: brick @ {bs:.2f} now starts at {t1:.2f}")
                else:
                    r["broll"].remove(b)
                    warns.append(f"yield: brick @ {bs:.2f}-{be:.2f} dropped ({b.get('why', '')[:50]})")
            r["broll"].append({"record_s": t0, "dur": dur, "file": f, "in_s": 0.0, "why": why})
        else:
            r["overlays"].append({"record_s": t0, "dur": dur, "file": f, "fade": 0, "why": why})
        placed.append(f"{c['id']} {c['kind']:5} {t0:8.2f} +{dur:5.2f}s  {os.path.basename(f)}")
    r["broll"].sort(key=lambda b: b["record_s"])
    r["overlays"].sort(key=lambda o: o["record_s"])
    for p in placed:
        print("placed", p)
    for w in warns:
        print("WARN ", w)
    if errs:
        for e in errs:
            print("ERROR", e)
        return 1
    C.write_json(a.out, r)
    lerrs, lwarns, _ = R.lint(r)
    for w in lwarns:
        print("WARN ", w)
    for e in lerrs:
        print("ERROR", e)
    print(json.dumps({"recipe": a.out, "full": sum(c["kind"] == "full" for c in plan["clips"]),
                      "panel": sum(c["kind"] == "panel" for c in plan["clips"]), "lint_errors": len(lerrs)}))
    return 1 if lerrs else 0


if __name__ == "__main__":
    sys.exit(main())
