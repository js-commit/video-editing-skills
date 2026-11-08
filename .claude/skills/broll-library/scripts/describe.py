#!/usr/bin/env python3
"""Give library clips a description and search tags, written by frame-describer
agents (Claude subagents) that look at each clip's contact sheet.

  describe.py briefs -o DIR [--only-missing | --all] [--source NAME] [--per-brief 20]
      writes DIR/brief_N.json (one per frame-describer agent) and prints their paths.
  describe.py collect DIR
      reads every DIR/answers_N.jsonl the agents wrote and files the descriptions
      and tags in the catalog. Exit 1 if a brief has no answers yet (re-spawn it).
  describe.py local [--only-missing | --all] [--source NAME]
      the same step with the vision model on THIS computer (tools/vlm-describe):
      no agents, no frame leaves the computer. One heavy job; resumable.

Privacy: with briefs/collect the contact sheets are sent to Claude (a cloud
model) when the agents read them. Do not describe private footage that way
unless the user agrees; use `local` instead.

stdout: JSON. Exit 0 ok, 1 unanswered briefs, 2 the local model is not set up,
4 a setting is unset.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

VLM = Path(__file__).resolve().parents[4] / "tools" / "vlm-describe" / "vlm_describe.py"

CLIP_PROMPT = (
    "These {n} frames are one b-roll shot, in time order (left to right, top to bottom). "
    "In one or two plain sentences (under 300 characters) say what the shot shows: the main subject, "
    "the action or camera move, the setting, framing (close-up, wide, overhead), and anything notable "
    "(slow motion feel, screen content, hands only, a person's face). Then give 5-10 lowercase search "
    "tags (single words or hyphenated, e.g. close-up, hands, desk, outdoor, screen, unboxing).")


def cmd_briefs(a):
    root = C.root_or_exit()
    data = C.load_catalog(root)
    out = Path(a.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    todo = [c for c in data["clips"] if c.get("sheet")
            and (a.all or not c.get("description"))
            and (not a.source or c["source_project"] == C.slugify(a.source))
            and c.get("verdict") not in ("aroll", "junk")]
    briefs = []
    for i in range(0, len(todo), a.per_brief):
        n = len(briefs) + 1
        chunk = todo[i:i + a.per_brief]
        brief = {"output": str(out / f"answers_{n}.jsonl"), "clip_prompt": CLIP_PROMPT,
                 "want_tags": True, "max_chars": 300,
                 "inputs": [{"id": c["id"], "images": [str(C.to_abs(root, c["sheet"]))],
                             "context": f"from: {c['source_project']}, {Path(c['path']).name}"}
                            for c in chunk]}
        p = out / f"brief_{n}.json"
        C.write_json(p, brief)
        briefs.append(str(p))
    print(json.dumps({"clips": len(todo), "briefs": briefs,
                      "next": "spawn one frame-describer agent per brief (prompt: 'Brief: <path>'), "
                              f"all in one message; then describe.py collect {out}"}, indent=2))
    return 0


LOCAL_PROMPT = CLIP_PROMPT + (" Ignore the small time labels in the tile corners. Write the description "
                              "first, then on a new line exactly \"Tags: tag1, tag2, ...\" with the tags.")
TAGS_LINE = re.compile(r"^\s*tags?\s*[:\-]\s*(.+)$", re.I | re.M)


def split_local(text: str) -> tuple:
    """The model's answer -> (description, [tags])."""
    text = (text or "").strip()
    m = TAGS_LINE.search(text)
    if not m:
        return text[:300], []
    desc = (text[:m.start()] + text[m.end():]).strip()
    tags = [t.strip(" .#*") for t in re.split(r"[,;]", m.group(1)) if t.strip(" .#*")]
    return desc[:300], tags


def cmd_local(a):
    root = C.root_or_exit()
    if not VLM.is_file():
        sys.exit(f"local vision tool missing: {VLM}")
    data = C.load_catalog(root)
    todo = [c for c in data["clips"] if c.get("sheet")
            and (a.all or not c.get("description"))
            and (not a.source or c["source_project"] == C.slugify(a.source))
            and c.get("verdict") not in ("aroll", "junk")]
    if not todo:
        print(json.dumps({"clips": 0, "filed": 0}))
        return 0
    entries = [{"id": c["id"], "images": [{"path": str(C.to_abs(root, c["sheet"]))}], "per": "clip",
                "clip_prompt": LOCAL_PROMPT.replace("{n}", "several")} for c in todo]
    answers = {}
    with tempfile.TemporaryDirectory(prefix="broll-describe-") as td:
        batch, raw = Path(td) / "batch.json", Path(td) / "raw.jsonl"
        C.write_json(batch, entries)
        print(f"describing {len(entries)} clip(s) with the local vision model (no frame leaves this computer)...",
              file=sys.stderr, flush=True)
        r = subprocess.run([sys.executable, str(VLM), "--batch", str(batch), "-o", str(raw), "--quiet"],
                           text=True, stderr=subprocess.PIPE)
        if r.returncode == 2:
            print("the local vision model is not set up:\n" + r.stderr.strip()
                  + "\n(python3 tools/vlm-describe/vlm_describe.py --check shows how)", file=sys.stderr)
            return 2
        if r.returncode == 3:
            print("another local-model run is busy; try again when it is done", file=sys.stderr)
            return 3
        if raw.is_file():
            for line in raw.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("id") and rec.get("clip"):
                    answers[rec["id"]] = rec["clip"]
    with C.Lock(root, "describe local"):
        data = C.load_catalog(root)
        filed = 0
        for c in data["clips"]:
            if c["id"] in answers:
                desc, tags = split_local(answers[c["id"]])
                if desc:
                    c["description"], c["tags"], c["described_by"] = desc, clean_tags(tags), "local-vlm"
                    filed += 1
        C.save_catalog(root, data)
    print(json.dumps({"clips": len(todo), "filed": filed, "failed": len(todo) - filed}, indent=2))
    return 0 if filed else 1


def clean_tags(tags) -> list:
    out = []
    for t in tags or []:
        t = C.slugify(t)
        if t and t != "untitled" and t not in out:
            out.append(t)
    return out[:12]


def cmd_collect(a):
    root = C.root_or_exit()
    d = Path(a.dir).expanduser().resolve()
    answers, unanswered, errors = {}, [], 0
    for bp in sorted(d.glob("brief_*.json")):
        brief = json.loads(bp.read_text())
        outp = Path(brief["output"])
        if not outp.exists():
            unanswered.append(str(bp))
            continue
        for line in outp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                continue
            if rec.get("error") or not rec.get("clip"):
                errors += 1
                continue
            answers[rec["id"]] = rec
    with C.Lock(root, "describe collect"):
        data = C.load_catalog(root)
        filed = 0
        for c in data["clips"]:
            rec = answers.get(c["id"])
            if rec:
                c["description"] = rec["clip"].strip()
                c["tags"] = clean_tags(rec.get("tags"))
                c["described_by"] = "frame-describer"
                filed += 1
        C.save_catalog(root, data)
    print(json.dumps({"filed": filed, "errors": errors, "unanswered_briefs": unanswered}, indent=2))
    return 1 if unanswered else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("briefs")
    b.add_argument("-o", "--out", required=True)
    g = b.add_mutually_exclusive_group()
    g.add_argument("--only-missing", action="store_true", help="clips with no description (default)")
    g.add_argument("--all", action="store_true", help="re-describe every clip")
    b.add_argument("--source", help="only clips from this source_project")
    b.add_argument("--per-brief", type=int, default=20)
    c = sub.add_parser("collect")
    c.add_argument("dir")
    lo = sub.add_parser("local", help="describe with the vision model on this computer")
    g2 = lo.add_mutually_exclusive_group()
    g2.add_argument("--only-missing", action="store_true", help="clips with no description (default)")
    g2.add_argument("--all", action="store_true", help="re-describe every clip")
    lo.add_argument("--source", help="only clips from this source_project")
    a = ap.parse_args()
    return {"briefs": cmd_briefs, "collect": cmd_collect, "local": cmd_local}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
