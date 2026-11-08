#!/usr/bin/env python3
"""Transcript side of the multicam angle pass: map the words onto the LIVE
timeline, write the batch prompts for the angle-selector agents, merge and
correct their decisions, smooth flicker, and write the Resolve job lists.

Nothing here talks to Resolve: resolve_angle.py dumps the timeline and
applies the result. The decision files are plain JSON you can read and edit.

Subcommands (all accept --job angle_job.json for the angle names, the
allowed angles and the run lengths; without it the defaults apply):

  fromcuts <stem>.aroll.tb.json camA.mov -o dump.json --fps 24 [--start-frame 86400]
           The same dump built from aroll-draft's cut list, for DaVinci
           Resolve (free) where scripts cannot read the timeline: the plan
           then ends as angle_list.txt to apply by hand.
  map      dump.json [--sidecar S ...] -o angle_transcript.json [--shift-s X]
           Words per V1 clip. Each V1 clip's source in-point (left_offset)
           maps the transcript words to timeline frames exactly: no render,
           no second transcription. The sidecar is found next to each clip's
           media (<stem>.transcript.json); --sidecar names one explicitly.
           --shift-s adds seconds to the sidecar's times (use the job's
           offset_s when the only transcript is camera B's).
  batches  angle_transcript.json outdir [--minutes 5] [--context-s 30]
           ~5-minute prompts (batch_NN.prompt.md) with read-only context on
           either side, batch_NN.segments.json and plan.json.
  merge    outdir -o angle_decisions.json
           Validates every batch_NN.decisions.json (each segment exactly
           once, allowed angles only). Exit 3 lists the problems: re-spawn
           that batch with the list.
  brief    frames_dir angle_decisions.json angle_transcript.json -o brief.md
           --out corrections.json [--rules frame-rules.md]
           The frame judge's brief for the low-confidence segments.
  review   angle_decisions.json angle_transcript.json -o review.md
           --out corrections.json [--plan plan.json]
           The whole timeline in one document for the angle-blender.
  apply    angle_decisions.json corrections.json [--source overpass]
           Applies [{"id", "angle", "why"}] corrections in place.
  smooth   angle_decisions.json angle_transcript.json
           Absorbs every angle run shorter than min_run_s (default 2 s)
           into its longer neighbour, in place. All three angles count:
           a B <-> PiP switch is visible too.
  jobs     angle_decisions.json angle_transcript.json outdir
           -> outdir/decisions.json {"enable_v2": [...]},
              outdir/pip.json {"pip_v3": [...], ...job PiP settings},
              outdir/only.json {"record_in": [...low confidence...]},
              outdir/angle_list.txt (timecode, angle, length per run)

Segment ids are V1 clip indexes in record order; record_in (a frame number)
is what resolve_angle.py keys on.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import angles as A  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RULES = SKILL_DIR / "reference" / "angle-rules.md"
DEFAULT_FRAME_RULES = SKILL_DIR / "reference" / "frame-rules.md"
log = A.log


def load_json(path):
    try:
        return A.extract_json(Path(path).read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read {path}: {e}")


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1) + "\n")


def job_of(a):
    return A.load_job(a.job, need_offset=False) if getattr(a, "job", None) else {}


def load_transcript(path):
    """Sidecar dict, through the shared vidkit.transcript reader."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
        from vidkit.transcript import load_transcript as lt
        return lt(path)
    except ImportError:
        return json.loads(Path(path).read_text())


def sidecar_words(side, shift_s=0.0):
    words = [w for seg in side.get("segments", []) for w in seg.get("words", [])
             if str(w.get("word", "")).strip() and "start" in w and "end" in w]
    words.sort(key=lambda w: w["start"])
    for w in words:
        w["_s"] = float(w["start"]) + shift_s
        w["_e"] = float(w["end"]) + shift_s
        w["_m"] = (w["_s"] + w["_e"]) / 2
    return words


# ---- map ----------------------------------------------------------------------

def cmd_map(a):
    dump = load_json(a.dump)
    fps = A.parse_fps(a.fps or dump.get("fps") or "24")
    explicit = [Path(p) for p in (a.sidecar or [])]
    explicit_names = {e: load_transcript(e).get("_meta", {}).get("source_name")
                      for e in explicit}
    cache = {}

    def words_for(clip):
        path = clip.get("path")
        cand = None
        if path:
            p = Path(path)
            beside = p.with_name(p.stem + ".transcript.json")
            cand = next((e for e, n in explicit_names.items() if n == p.name), None)
            if cand is None and beside.exists():
                cand = beside
        if cand is None and len(explicit) == 1:
            cand = explicit[0]
        if cand is None:
            return None
        if cand not in cache:
            ws = sidecar_words(load_transcript(cand), a.shift_s)
            cache[cand] = (ws, [w["_m"] for w in ws])
        return cache[cand]

    out, missing = [], set()
    v2 = dump.get("v2", [])
    for i, c in enumerate(dump.get("v1", [])):
        src_in = float(c["left_offset"] / fps)
        src_out = float((c["left_offset"] + c["duration"]) / fps)
        rec_s = float(c["record_in"] / fps)
        seg_words = []
        found = words_for(c)
        if found is None:
            missing.add(c.get("path") or c.get("name"))
        else:
            ws, mids = found
            lo = bisect.bisect_left(mids, src_in)
            hi = bisect.bisect_left(mids, src_out)
            for w in ws[lo:hi]:
                seg_words.append({"w": str(w["word"]).strip(),
                                  "t": round(rec_s + (w["_s"] - src_in), 3)})
        out.append({
            "id": i,
            "record_in": c["record_in"],
            "record_out": c["record_out"],
            "tc": A.tc(c["record_in"], fps),
            "t": round(rec_s, 3),
            "dur_s": round(float(c["duration"] / fps), 2),
            "src_in_s": round(src_in, 3),
            "enabled_v2": v2[i]["enabled"] if i < len(v2) else None,
            "text": " ".join(w["w"] for w in seg_words),
            "words": seg_words,
        })
    if missing:
        log(f"WARN: no transcript for {sorted(map(str, missing))}: those "
            "clips are mapped with no words. Run tools/transcribe.py on the "
            "file, or pass --sidecar.")
    res = {"timeline": dump.get("timeline"), "fps": str(a.fps or dump.get("fps") or "24"),
           "segments": out}
    write_json(a.out, res)
    print(json.dumps({"segments": len(out),
                      "words": sum(len(s["words"]) for s in out),
                      "silent_segments": [s["id"] for s in out if not s["words"]],
                      "clips_without_transcript": len(missing),
                      "out": os.path.abspath(a.out)}))


def cmd_fromcuts(a):
    """A timeline dump built from aroll-draft's cut list instead of a live
    timeline: for DaVinci Resolve (free), where scripts cannot read the
    timeline. Keeps are laid end to end from start_frame, exactly like the
    draft timeline before any hand edit."""
    ops = load_json(a.cuts)
    if isinstance(ops, dict):
        ops = ops.get("ops") or ops.get("cuts") or []
    fps = A.parse_fps(a.fps)
    rec, v1 = int(a.start_frame), []
    for op in ops:
        if op.get("operation", "keep") != "keep":
            continue
        src_in = int(round(float(op["start"]) * fps))
        dur = int(round((float(op["start"]) + float(op["duration"])) * fps)) - src_in
        if dur <= 0:
            continue
        v1.append({"record_in": rec, "record_out": rec + dur, "duration": dur,
                   "left_offset": src_in, "enabled": True,
                   "name": Path(a.media).name, "path": os.path.abspath(a.media)})
        rec += dur
    # camera B's clips sit on its own clock: B time = A time - offset_s
    off_s = a.offset_s if a.offset_s is not None else float(job_of(a).get("offset_s", 0.0))
    off = int(round(off_s * fps))
    v2 = [{**c, "enabled": False, "left_offset": c["left_offset"] - off} for c in v1]
    write_json(a.out, {"timeline": a.timeline or Path(a.cuts).stem, "fps": a.fps,
                       "start_frame": int(a.start_frame), "from_cut_list": True,
                       "v1": v1, "v2": v2})
    print(json.dumps({"segments": len(v1), "duration_s": round((rec - int(a.start_frame)) / float(fps), 1),
                      "out": os.path.abspath(a.out)}))


# ---- prompts -------------------------------------------------------------------

def angle_section(job):
    voc, allow = A.vocab(job), A.allowed(job)
    lines = ["## The angles", ""]
    for k in allow:
        lines.append(f"- **{k}** (\"{voc[k]['name']}\"): {voc[k]['describe']}")
    lines += ["", f"Allowed angle ids: {', '.join(allow)}. Target run length: "
              f"{A.target_run_s(job):g} s; hard minimum {A.min_run_s(job):g} s "
              "(shorter runs are merged into a neighbour automatically, so "
              "do not rely on them)."]
    return "\n".join(lines)


def rules_section(path):
    try:
        text = Path(path).read_text().strip()
    except OSError:
        sys.exit(f"cannot read rules file {path}")
    return "## Rules\n\n" + text


def prefs_section():
    prefs = A.read_preferences()
    if not prefs:
        return ""
    return ("## The user's preferences (these override the rules above)\n\n"
            + prefs)


def fmt_seg(s):
    return f"[{s['id']}] {s['tc']} ({s['dur_s']}s) {s['text'] or '<silent>'}"


PROMPT = """# Angle selection: batch {n} of {total}

Choose, for EVERY segment under "## Segments", which camera angle plays.
Read the angles and rules first, then the whole batch, then decide. Write
the decisions to `{decisions_path}` as a raw JSON array (no fences, no
prose):

[{{"id": 12, "angle": "pip", "confidence": "high", "why": "pointing at the part while explaining it"}}, ...]

`id` is the number in [brackets]; `angle` is one of the allowed ids;
`confidence` is "high" or "low". Every segment under "## Segments" gets
exactly one entry. The context segments are read-only: do NOT output them.

{angles}

{rules}

{prefs}

## Context before (read-only, do not output)

{context_before}

## Segments

{segments}

## Context after (read-only, do not output)

{context_after}
"""


def cmd_batches(a):
    job = job_of(a)
    tt = load_json(a.transcript)
    segs = tt["segments"]
    os.makedirs(a.outdir, exist_ok=True)
    span = a.minutes * 60.0
    batches, cur, cur_start = [], [], 0.0
    for s in segs:
        if cur and s["t"] - cur_start >= span:
            batches.append(cur)
            cur = []
        if not cur:
            cur_start = s["t"]
        cur.append(s)
    if cur:
        batches.append(cur)
    angles, rules, prefs = angle_section(job), rules_section(a.rules), prefs_section()
    plan = []
    for n, b in enumerate(batches, 1):
        t0, t1 = b[0]["t"], b[-1]["t"] + b[-1]["dur_s"]
        before = [s for s in segs if t0 - a.context_s <= s["t"] < t0]
        after = [s for s in segs if t1 <= s["t"] < t1 + a.context_s]
        dec = os.path.abspath(os.path.join(a.outdir, f"batch_{n:02d}.decisions.json"))
        prompt = PROMPT.format(
            n=n, total=len(batches), decisions_path=dec, angles=angles,
            rules=rules, prefs=prefs,
            context_before="\n".join(map(fmt_seg, before)) or "(start of timeline)",
            segments="\n".join(map(fmt_seg, b)),
            context_after="\n".join(map(fmt_seg, after)) or "(end of timeline)")
        pp = os.path.abspath(os.path.join(a.outdir, f"batch_{n:02d}.prompt.md"))
        Path(pp).write_text(prompt)
        write_json(os.path.join(a.outdir, f"batch_{n:02d}.segments.json"),
                   [s["id"] for s in b])
        plan.append({"n": n, "prompt": pp, "decisions": dec,
                     "ids": [b[0]["id"], b[-1]["id"]],
                     "t": [round(t0, 1), round(t1, 1)],
                     "words": sum(len(s["words"]) for s in b)})
    write_json(os.path.join(a.outdir, "plan.json"), {"batches": plan})
    print(json.dumps({"batches": len(plan),
                      "plan": os.path.abspath(os.path.join(a.outdir, "plan.json")),
                      "prompts": [p["prompt"] for p in plan]}))


# ---- merge / apply / smooth ----------------------------------------------------

def load_decisions(path):
    return {d["id"]: d for d in load_json(path)}


def save_decisions(path, dec):
    write_json(path, [dec[i] for i in sorted(dec)])


def cmd_merge(a):
    job = job_of(a)
    voc, allow = A.vocab(job), A.allowed(job)
    plan = load_json(os.path.join(a.outdir, "plan.json"))
    merged, problems = {}, []
    for b in plan["batches"]:
        label = f"batch {b['n']}"
        ids = load_json(os.path.join(a.outdir, f"batch_{b['n']:02d}.segments.json"))
        if not os.path.exists(b["decisions"]):
            problems.append(f"{label}: decisions file missing ({b['decisions']})")
            continue
        try:
            decs = A.extract_json(Path(b["decisions"]).read_text())
        except ValueError as e:
            problems.append(f"{label}: unparseable JSON ({e})")
            continue
        by_id, probs = A.validate_batch(decs, ids, voc, allow, label)
        merged.update(by_id)
        problems += probs
    save_decisions(a.out, merged)
    counts = {k: sum(1 for d in merged.values() if d["angle"] == k) for k in allow}
    print(json.dumps({"decisions": len(merged), "angles": counts,
                      "low_confidence": [i for i, d in sorted(merged.items())
                                         if d["confidence"] == "low"],
                      "problems": problems, "out": os.path.abspath(a.out)}))
    if problems:
        sys.exit(3)


def cmd_apply(a):
    job = job_of(a)
    dec = load_decisions(a.decisions)
    corr = load_json(a.corrections)
    applied, skipped = A.apply_corrections(dec, corr, A.vocab(job), A.allowed(job),
                                           a.source)
    save_decisions(a.decisions, dec)
    print(json.dumps({"applied": len(applied),
                      "changed": [x["id"] for x in applied if x["changed"]],
                      "skipped": skipped}))


def cmd_smooth(a):
    job = job_of(a)
    tt = load_json(a.transcript)
    dec = load_decisions(a.decisions)
    fps = A.parse_fps(tt.get("fps", "24"))
    min_s = a.min_run_s if a.min_run_s is not None else A.min_run_s(job)
    flips = A.smooth_decisions(tt["segments"], dec, fps, min_s)
    save_decisions(a.decisions, dec)
    print(json.dumps({"min_run_s": min_s, "flips": flips,
                      **A.run_stats(tt["segments"], dec, fps)}))


# ---- review / brief / jobs -------------------------------------------------------

def cmd_review(a):
    job = job_of(a)
    voc = A.vocab(job)
    tt = load_json(a.transcript)
    dec = load_decisions(a.decisions)
    fps = A.parse_fps(tt.get("fps", "24"))
    target = A.target_run_s(job)
    seams = set()
    if a.plan and os.path.exists(a.plan):
        seams = {b["ids"][0] for b in load_json(a.plan)["batches"][1:]}
    lines = [f"# Angle plan review: {tt.get('timeline')}", "",
             "Every segment in order: `[id] timecode (duration) ANGLE - reason`, "
             "then the words. Batch seams are marked. Write corrections (only "
             f"ids whose angle must change) to `{os.path.abspath(a.out)}`.", "",
             angle_section(job), "", rules_section(a.rules), "", prefs_section(),
             "", "## Timeline", ""]
    for s in tt["segments"]:
        d = dec.get(s["id"], {})
        if s["id"] in seams:
            lines.append("---- batch seam ----")
        conf = " (LOW)" if d.get("confidence") == "low" else ""
        ang = d.get("angle", "?")
        name = voc.get(ang, {}).get("name", "?")
        lines.append(f"[{s['id']}] {s['tc']} ({s['dur_s']}s) {ang} \"{name}\"{conf}"
                     f" - {d.get('why', '')}")
        lines.append(f"    {s['text'] or '<silent>'}")
    rs = A.runs(A.decision_segments(tt["segments"], dec), tol=1)
    short = [r for r in rs if r["dur"] / float(fps) < target]
    lines += ["", f"## Runs shorter than {target:g} s (flicker candidates)", ""]
    lines += [f"- {A.tc(r['start'], fps)} {r['angle']} "
              f"{r['dur'] / float(fps):.1f}s ids {[x['id'] for x in r['segs']]}"
              for r in short] or ["(none)"]
    Path(a.review).write_text("\n".join(lines) + "\n")
    print(json.dumps({"segments": len(tt["segments"]), "runs": len(rs),
                      "short_runs": len(short), "review": os.path.abspath(a.review)}))


def cmd_brief(a):
    job = job_of(a)
    voc = A.vocab(job)
    idx = load_json(os.path.join(a.frames, "index.json"))
    tt = {s["record_in"]: s for s in load_json(a.transcript)["segments"]}
    dec = load_decisions(a.decisions)
    rules = Path(a.rules).read_text().strip()
    samples = {}
    for r in idx:
        samples.setdefault(r["i"], []).append(r)
    sheets = sorted({r["sheet"] for r in idx if r.get("sheet")})
    fdir = os.path.abspath(a.frames)
    lines = [f"# Frame judging: {len(samples)} low-confidence segments", "",
             "Contact sheets (read ALL of them):", ""]
    lines += [f"- {os.path.join(fdir, s)}" for s in sheets]
    lines += ["", "Each tile is one sample: camera A LEFT, camera B RIGHT "
              "(rotated upright). Sheets fill left to right, top to bottom, "
              f"{idx[0].get('cols', 2) if idx else 2} tiles per row; a tile "
              "label (top-left, when drawn) reads `III.k timecode duration`.", "",
              angle_section(job), "", rules, "", prefs_section(), "",
              "## Segments to judge", ""]
    for i, rows in sorted(samples.items()):
        s = tt.get(rows[0]["record_in"])
        if s is None:
            log(f"WARN: sample {i} has no transcript segment (stale dump?)")
            continue
        d = dec.get(s["id"], {})
        where = "; ".join(f"{r['sheet']} row {r['row']} col {r['col']}" for r in rows)
        guess = d.get("angle", "?")
        lines.append(f"- segment id {s['id']} (sample {i:03d}) at {s['tc']} "
                     f"({s['dur_s']}s); transcript guess: {guess} "
                     f"\"{voc.get(guess, {}).get('name', '?')}\" - {d.get('why', '')}\n"
                     f"    tiles: {where}\n"
                     f"    words: {s['text'] or '<silent>'}")
    lines += ["", f"Write a verdict for EVERY one of the {len(samples)} segments "
              f"to {os.path.abspath(a.out)} as a raw JSON array: "
              "[{\"id\": <segment id>, \"angle\": \"<allowed id>\", "
              "\"why\": \"what the frames show\"}]. Use the SEGMENT id, never "
              "the sample number."]
    Path(a.brief).write_text("\n".join(lines) + "\n")
    print(json.dumps({"segments": len(samples), "sheets": len(sheets),
                      "brief": os.path.abspath(a.brief),
                      "corrections": os.path.abspath(a.out)}))


def cmd_jobs(a):
    job = job_of(a)
    tt = load_json(a.transcript)
    dec = load_decisions(a.decisions)
    fps = A.parse_fps(tt.get("fps", "24"))
    j = A.build_jobs(tt["segments"], dec)
    if j["missing"]:
        log(f"WARN: {len(j['missing'])} segments have no decision: {j['missing']}")
    os.makedirs(a.outdir, exist_ok=True)
    write_json(os.path.join(a.outdir, "decisions.json"), {"enable_v2": j["enable_v2"]})
    pip = {"pip_v3": j["pip_v3"], **{k: v for k, v in (job.get("pip") or {}).items()}}
    if a.style:
        pip["style"] = a.style
    write_json(os.path.join(a.outdir, "pip.json"), pip)
    write_json(os.path.join(a.outdir, "only.json"), {"record_in": j["low"]})
    # the same plan as a cue list a person can read (or apply by hand)
    voc = A.vocab(job)
    rs = A.runs(A.decision_segments(tt["segments"], dec), tol=1)
    cues = [f"{A.tc(r['start'], fps)}  {r['angle']:<4} {voc[r['angle']]['name']:<20} "
            f"{r['dur'] / float(fps):6.1f}s" for r in rs]
    Path(a.outdir, "angle_list.txt").write_text(
        "timecode     angle name                 length\n" + "\n".join(cues) + "\n")
    print(json.dumps({"enable_v2": len(j["enable_v2"]), "pip_v3": len(j["pip_v3"]),
                      "low_confidence": len(j["low"]),
                      "angle_list": os.path.abspath(os.path.join(a.outdir, "angle_list.txt")),
                      **A.run_stats(tt["segments"], dec, fps),
                      "outdir": os.path.abspath(a.outdir)}))


def main():
    ap = argparse.ArgumentParser(
        description="Map the transcript onto a multicam timeline and manage "
                    "the per-segment angle decisions (no Resolve needed).",
        epilog="See the module docstring (this file's header) for the full workflow.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, func, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        p.add_argument("--job", help="angle_job.json (angle names, allowed angles, run lengths)")
        p.set_defaults(func=func)
        return p

    p = add("map", cmd_map, "words per V1 clip of a live timeline dump")
    p.add_argument("dump")
    p.add_argument("--sidecar", action="append", help="transcript sidecar (repeatable)")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--fps", help="timeline fps (default: the dump's)")
    p.add_argument("--shift-s", type=float, default=0.0,
                   help="seconds added to the sidecar's word times")
    p = add("fromcuts", cmd_fromcuts, "a dump made from aroll-draft's cut list (no Resolve scripting)")
    p.add_argument("cuts", help="<stem>.aroll.tb.json")
    p.add_argument("media", help="camera A's file (the cut source)")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--fps", required=True, help="timeline frame rate, e.g. 24, 25, 29.97")
    p.add_argument("--start-frame", type=int, default=0,
                   help="timeline start frame (Resolve's 01:00:00:00 is 3600 x the timecode base, e.g. 86400 at 24 fps)")
    p.add_argument("--timeline", help="name to show in the review")
    p.add_argument("--offset-s", type=float,
                   help="camera B's start delay (default: the job's offset_s, else 0)")
    p = add("batches", cmd_batches, "write the angle-selector batch prompts")
    p.add_argument("transcript")
    p.add_argument("outdir")
    p.add_argument("--minutes", type=float, default=5.0)
    p.add_argument("--context-s", type=float, default=30.0)
    p.add_argument("--rules", default=str(DEFAULT_RULES))
    p = add("merge", cmd_merge, "validate and merge the batch decisions")
    p.add_argument("outdir")
    p.add_argument("-o", "--out", required=True)
    p = add("brief", cmd_brief, "write the frame judge's brief")
    p.add_argument("frames")
    p.add_argument("decisions")
    p.add_argument("transcript")
    p.add_argument("-o", "--brief", required=True)
    p.add_argument("--out", required=True, help="where the judge writes its verdicts")
    p.add_argument("--rules", default=str(DEFAULT_FRAME_RULES))
    p = add("review", cmd_review, "write the angle-blender's whole-timeline review")
    p.add_argument("decisions")
    p.add_argument("transcript")
    p.add_argument("-o", "--review", required=True)
    p.add_argument("--out", required=True, help="where the blender writes corrections")
    p.add_argument("--plan", help="plan.json, to mark batch seams")
    p.add_argument("--rules", default=str(DEFAULT_RULES))
    p = add("apply", cmd_apply, "apply corrections to the decisions (in place)")
    p.add_argument("decisions")
    p.add_argument("corrections")
    p.add_argument("--source", default="overpass", help="label written into 'why'")
    p = add("smooth", cmd_smooth, "merge angle runs under the minimum (in place)")
    p.add_argument("decisions")
    p.add_argument("transcript")
    p.add_argument("--min-run-s", type=float)
    p = add("jobs", cmd_jobs, "write decisions.json / pip.json / only.json for resolve_angle.py")
    p.add_argument("decisions")
    p.add_argument("transcript")
    p.add_argument("outdir")
    p.add_argument("--style", choices=["fusion", "inspector"],
                   help="PiP style (default: the job's pip.style, else fusion)")
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
