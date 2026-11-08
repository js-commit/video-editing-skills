#!/usr/bin/env python3
"""One draft round, start to finish: picks -> beat walk -> lint -> stabilize -> mix -> render -> QC -> EditReview sidecars.

  make_draft.py PROJECT [--version N] [--final] [--force] [--no-stabilize]

  --version N    which version to write (default: one more than the last work/cut_vN.json)
  --final        render the keeper at the full canvas size, high quality, to the finals folder
                 (only once the user approves a draft)
  --force        render even when the lint finds errors (to look at a problem, never to hand over)
  --no-stabilize skip stabilize-clips for cuts marked "stabilize": true

Inputs:  work/picks.json (the story), work/changes_vN.json (a notes round's change list, optional)
Outputs: work/cut_vN.json, work/mix_vN.wav (+ -bed.wav), work/qc_vN.json,
         <project>/<drafts>/<name>-vN.mp4 and its <name>-vN.review/ folder with cuts.json
         (and changes.json on a notes round) for EditReview. Earlier drafts stay, so every
         version keeps its own notes.
Prints one JSON line: {"draft", "version", "length_s", "cues", "lint": {...}, "qc": {...}}.
Exit 1 when lint or QC found an ERROR (or a change the change list does not announce).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402
from hv import settings  # noqa: E402
import beat_walk  # noqa: E402
import lint_cut  # noqa: E402
import qc_render  # noqa: E402
import render as renderer  # noqa: E402
import sidecars  # noqa: E402

STABILIZE = hv.SKILLS / "stabilize-clips" / "scripts" / "stabilize.py"
MIXDOWN = hv.SKILLS / "montage-music" / "scripts" / "mixdown.py"


def next_version(W: Path) -> int:
    vs = [int(m.group(1)) for f in W.glob("cut_v*.json") if (m := re.fullmatch(r"cut_v(\d+)\.json", f.name))]
    return max(vs, default=0) + 1


def stabilize_cuts(p: Path, job: dict) -> list:
    """Cuts marked "stabilize": true get a stabilized stretch (cached by clip + range)."""
    report = []
    out_dir = hv.work(p) / "stabilized"
    for c in job["cuts"]:
        if not c.get("stabilize") or c.get("photo"):
            continue
        src, a, b = c["file"], c["in_s"], c["out_s"]
        out = out_dir / f"{Path(src).stem}_{a:.2f}_{b:.2f}.mp4"
        res = None
        side = Path(str(out) + ".stab.json")
        if out.exists() and side.exists():
            res = hv.load_json(side)
        else:
            hv.log(f"stabilize cut {c['i']} ({Path(src).name} {a:.2f}-{b:.2f})")
            r = subprocess.run([sys.executable, "-B", str(STABILIZE), src, "-o", str(out), "--range", str(a), str(b), "--force"],
                               capture_output=True, text=True)
            line = (r.stdout.strip().splitlines() or ["{}"])[-1]
            try:
                res = json.loads(line)
            except json.JSONDecodeError:
                res = {"status": "error", "reason": r.stderr.strip()[-300:]}
            if r.returncode and res.get("status") != "error":
                res = {"status": "error", "reason": r.stderr.strip()[-300:]}
        report.append({"cut": c["i"], "status": res.get("status"), "reason": res.get("reason")})
        if res.get("status") == "kept" and res.get("out") and Path(res["out"]).exists():
            c["stab"] = {"source": src, "source_in_s": res["source_in_s"], "gain": res.get("gain"), "zoom_pct": res.get("zoom_pct")}
            c["src_in_s"] = a
            c["file"] = res["out"]
            c["in_s"] = round(a - res["source_in_s"], 3)
            c["out_s"] = round(b - res["source_in_s"], 3)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--version", type=int)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-stabilize", action="store_true")
    a = ap.parse_args()
    try:
        p = hv.project_root(a.project)
        cfg = hv.project_cfg(p)
        W = hv.work(p)
        picks_path = W / "picks.json"
        if not picks_path.exists():
            hv.die(f"no {picks_path}: write the story (sections, music, cuts) first - see beat_walk.py --help", 2)
        N = a.version or (next_version(W) - (1 if a.final else 0)) or 1
        name = cfg.get("name", p.name)
        tag = "final" if a.final else f"v{N}"

        hv.log(f"== v{N}: beat walk")
        job, walk_warn = beat_walk.build(p, hv.load_json(picks_path), N)
        hv.log(f"== v{N}: lint")
        err, warn = lint_cut.lint(p, job)
        warn = walk_warn + warn
        for x in err:
            hv.log("ERROR " + x)
        for x in warn:
            hv.log("WARN  " + x)
        if err and not a.force:
            hv.save_json(W / f"cut_{tag}.json", job)
            hv.die(f"lint found {len(err)} error(s): fix work/picks.json and re-run (or --force to look anyway)")

        stab = [] if a.no_stabilize else stabilize_cuts(p, job)
        for s in stab:
            hv.log(f"stabilize cut {s['cut']}: {s['status']} - {s['reason']}")
        hv.save_json(W / f"cut_{tag}.json", job)

        hv.log(f"== v{N}: mix")
        mix = W / f"mix_{tag}.wav"
        prefs_lufs = cfg.get("target_lufs", -16)
        r = subprocess.run([sys.executable, "-B", str(MIXDOWN), str(W / f"cut_{tag}.json"), str(mix),
                            "--target-lufs", str(prefs_lufs), "--bed-rms-db", str(cfg.get("bed_rms_db", -21))],
                           capture_output=True, text=True)
        if r.returncode:
            hv.die(f"mixdown failed:\n{r.stderr[-800:]}")
        mixinfo = json.loads(r.stdout.strip().splitlines()[-1])

        hv.log(f"== v{N}: render ({'final' if a.final else 'draft'})")
        out = (hv.finals_dir(p) / f"{name}-final.mp4") if a.final else (hv.drafts_dir(p) / f"{name}-v{N}.mp4")
        rres = renderer.render(job, str(mix), out, final=a.final, work_dir=W)

        hv.log(f"== v{N}: QC")
        q = qc_render.qc(str(out), job, str(mix))
        hv.save_json(W / f"qc_{tag}.json", {**q, "lint_errors": err, "lint_warnings": warn, "stabilize": stab})
        for x in q["info"]:
            hv.log("  " + x)
        for x in q["errors"]:
            hv.log("ERROR " + x)
        for x in q["warnings"]:
            hv.log("WARN  " + x)

        side = sidecars.write_cuts(job, out)
        uncovered = []
        spec = W / f"changes_v{N}.json"
        prev = W / f"cut_v{N - 1}.json"
        if spec.exists() and not a.final:
            _, uncovered = sidecars.write_changes(job, out, hv.load_json(spec), hv.load_json(prev) if prev.exists() else None)
            for u in uncovered:
                hv.log("UNCOVERED " + u)
        elif N > 1 and not a.final:
            hv.log(f"note: no work/changes_v{N}.json - write one (an entry per note) so EditReview shows what changed")
    except settings.SettingMissing as e:
        settings.exit_missing(e)

    bad = bool(err) or bool(q["errors"]) or bool(uncovered)
    print(json.dumps({"draft": str(out), "version": N, "length_s": job["end_s"], "cuts": len(job["cuts"]),
                      "cues": [Path(c["file"]).name for c in job["cues"]], "review_folder": str(side.parent),
                      "lint": {"errors": len(err), "warnings": len(warn)},
                      "qc": {"errors": len(q["errors"]), "warnings": len(q["warnings"]), "lufs": q.get("lufs"),
                             "true_peak": q.get("true_peak")},
                      "mix_lufs": mixinfo.get("lufs"), "uncovered_changes": len(uncovered),
                      "render_s": rres["seconds"], "segments_encoded": rres["encoded"]}))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
