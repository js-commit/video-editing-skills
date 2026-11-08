#!/usr/bin/env python3
"""Describe every clip of a home-video project with the LOCAL vision model
(tools/vlm-describe), so the shots can be picked from text without anyone but
the model seeing a frame. Privacy mode "local" needs this; "frames" may use it
too; "no-frames" refuses it (the model is on this computer, but the user said
nothing may look).

  describe.py PROJECT [--force] [--clips ID ...]

Reads the clips in place (work/clips.json), samples 4-16 frames per clip by
length, and writes:
  work/descriptions.json   id -> {people, who, setting, landmark, action, camera, quality,
                                  appeal (1-5), frames: [{t, text}], slug}
  work/descriptions.md     the same as a table Claude reads next to work/survey.md

Resumable: clips already described are skipped unless --force. One heavy job:
do not run it beside a render or a transcription batch. Prints the .md path.
Exit 2 = privacy refuses or the local model is not set up (the message says how).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402

VLM = hv.REPO / "tools" / "vlm-describe" / "vlm_describe.py"
MAX_TOKENS = "360"   # the JSON scan below needs more than the default one-sentence budget

CLIP_PROMPT = (
    "These are {n} frames sampled in order from one home-video clip. Reply with ONLY a compact "
    "JSON object on one line (no code fence, no line breaks) with these keys: "
    '"people": "none" or how many people are clearly visible (a number as text); '
    '"who": the visible people and what they do (e.g. "a child in a red coat runs to the camera"), or "none"; '
    '"setting": indoor or outdoor plus the kind of place (e.g. "outdoor, beach", "indoor, kitchen"); '
    '"landmark": the landmark if it is clearly a famous one, else "none"; '
    '"action": one sentence, what happens over the clip; '
    '"camera": one of "static", "walking", "panning", "handheld shaky", "underwater", "vehicle window", "selfie"; '
    '"quality": comma-separated from "sharp", "soft", "shaky", "dark", "sideways", "lens obstructed", "overexposed"; '
    '"appeal": 1-5, how good the clip would look in a fun highlight video; '
    '"frames": a list of {n} phrases of at most six words, one per frame in order, each saying what that frame shows; '
    '"slug": a 3-6 word kebab-case summary. Do not guess brand names or people\'s names.')
PHOTO_PROMPT = (
    "Reply with ONLY a compact JSON object on one line with these keys: "
    '"people" ("none" or a number as text), "who", "setting", "landmark", "action" (what the photo shows), '
    '"camera": "photo", "quality" (comma-separated from "sharp", "soft", "dark", "sideways", "overexposed"), '
    '"appeal" (1-5), "frames": [one phrase of at most six words], "slug" (3-6 words, kebab-case). '
    "Do not guess brand names or people's names.")
KEYS = ("people", "who", "setting", "landmark", "action", "camera", "quality", "appeal", "frames", "slug")


def parse(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--clips", nargs="*", default=None, help="only these clip ids")
    a = ap.parse_args()
    p = hv.project_root(a.project)
    cfg = hv.project_cfg(p)
    if cfg.get("privacy") == "no-frames":
        hv.die("privacy mode is \"no-frames\" for this project: the user asked that nothing, not even a model on "
               "this computer, looks at the footage. Pick from work/survey.md and their notes instead.", 2)
    if not VLM.is_file():
        hv.die(f"local vision tool missing: {VLM}", 2)
    clips = hv.clips(p)
    if not clips:
        hv.die("no clips yet: run survey.py first", 2)
    W = hv.work(p)
    out_json, out_md = W / "descriptions.json", W / "descriptions.md"
    done = hv.load_json(out_json, {}) if not a.force else {}
    wanted = [i for i in clips if (a.clips is None or i in a.clips) and i not in done]
    if wanted:
        entries = []
        for i in wanted:
            c = clips[i]
            e = {"id": i, "path": c["path"], "kind": c.get("kind", "video"), "per": "clip"}
            e["clip_prompt"] = PHOTO_PROMPT if c.get("kind") == "photo" else CLIP_PROMPT
            entries.append(e)
        with tempfile.TemporaryDirectory(prefix="hv-describe-") as td:
            batch = Path(td) / "batch.json"
            raw = Path(td) / "raw.jsonl"
            batch.write_text(json.dumps(entries), encoding="utf-8")
            hv.log(f"describing {len(entries)} clip(s) with the local vision model (no frame leaves this computer)...")
            env = dict(os.environ, VLM_MAX_TOKENS=MAX_TOKENS)
            r = subprocess.run([sys.executable, str(VLM), "--batch", str(batch), "-o", str(raw), "--quiet"],
                               env=env, text=True, stderr=subprocess.PIPE)
            if r.returncode == 2:
                hv.die("the local vision model is not set up:\n" + r.stderr.strip()
                       + "\n(python3 tools/vlm-describe/vlm_describe.py --check shows how)", 2)
            if r.returncode == 3:
                hv.die("another local-model run is busy; try again when it is done", 3)
            if not raw.is_file():
                hv.die(f"vlm-describe failed:\n{r.stderr.strip()[-1500:]}", 1)
            for line in raw.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if "_meta" in rec or rec.get("error") or not rec.get("id"):
                    if rec.get("error"):
                        hv.log(f"{rec.get('id')}: {rec['error']}")
                    continue
                d = parse(rec.get("clip") or "")
                if not d:
                    hv.log(f"{rec['id']}: the model did not answer in JSON; kept its text")
                    d = {"action": (rec.get("clip") or "").strip()[:300]}
                row = {k: d.get(k) for k in KEYS if d.get(k) is not None}
                times = [f.get("t") for f in rec.get("frames") or []]
                if isinstance(row.get("frames"), list) and times:
                    row["frames"] = [{"t": t, "text": str(x)} for t, x in zip(times, row["frames"])]
                done[rec["id"]] = row
        hv.save_json(out_json, done)

    lines = ["# What the local vision model saw", "",
             "Nothing left this computer. Appeal is the model's 1-5 guess at how good the clip looks in a",
             "highlight video; `who` and `people` are what it could see, not who they are. Times in `frames`",
             "are seconds in the clip.", "",
             "| id | people | setting | action | camera | quality | appeal | slug |", "|---|---|---|---|---|---|---|---|"]
    for i in clips:
        d = done.get(i)
        if not d:
            continue
        cell = lambda k: str(d.get(k, "") or "").replace("|", "/").replace("\n", " ")  # noqa: E731
        lines.append(f"| {i} | {cell('people')} | {cell('setting')} | {cell('action')} | {cell('camera')} | "
                     f"{cell('quality')} | {cell('appeal')} | {cell('slug')} |")
    lines += ["", "## Frame by frame", ""]
    for i in clips:
        d = done.get(i)
        if not d or not isinstance(d.get("frames"), list):
            continue
        parts = [f"{f['t']}s {f['text']}" if isinstance(f, dict) else str(f) for f in d["frames"]]
        lines.append(f"- **{i}**" + (f" ({d.get('who')})" if d.get("who") and d.get("who") != "none" else "")
                     + (f" landmark: {d['landmark']}" if d.get("landmark") and d["landmark"] != "none" else "")
                     + ": " + "; ".join(parts))
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    hv.log(f"{len(done)} clip(s) described -> {out_md}")
    print(out_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
