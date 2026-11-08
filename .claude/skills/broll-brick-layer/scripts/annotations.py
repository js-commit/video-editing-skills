#!/usr/bin/env python3
"""B-roll annotation store, keyed by the media file's CONTENT, not its path.

The key is md5(first 4 MB + last 4 MB + size), so an annotation survives
renames, moves and copies of the clip. One JSON per clip, stored:
  * in the clip's project: <project>/<work>/broll-annotations/  (when the clip
    sits inside a project folder, see settings paths.projects_dir), else
  * in the shared cache: <paths.cache_dir>/broll-annotations/
--store DIR overrides both. `get` looks in the project store, then the cache.

Document shape: reference/formats.md ("Annotation"). `put` validates it and
protects human work: when the stored document says "annotator": "human", an
agent's document may only fill EMPTY descriptions; boundaries, product,
device, quality and director notes stay as the human left them.

Usage:
  annotations.py hash FILE
  annotations.py get FILE                 (exit 1 if none)
  annotations.py put FILE ANNOT.json
  annotations.py status FILE...           (annotated / MISSING per file)
  annotations.py dump FILE... [-o all.json]   (every annotation, for the matcher)
  annotations.py where FILE               (the store this file's annotation lives in)
  common option: --store DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402

QUALITY = {"good", "usable", "poor"}


def content_key(path):
    size = os.path.getsize(path)
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read(4 * 1024 * 1024))
        if size > 8 * 1024 * 1024:
            f.seek(-4 * 1024 * 1024, os.SEEK_END)
            h.update(f.read())
    h.update(str(size).encode())
    return h.hexdigest()


def stores_for(path, store=None):
    """Candidate store folders for a file, most specific first."""
    if store:
        return [Path(store)]
    out = []
    try:
        proj = B.settings.find_project_root(path)
    except Exception:
        proj = None
    if proj:
        out.append(proj / B.settings.layout("work") / "broll-annotations")
    out.append(B.settings.cache_dir("broll-annotations"))
    return out


def find(path, store=None):
    key = content_key(path)
    for d in stores_for(path, store):
        p = d / f"{key}.json"
        if p.exists():
            return p
    return None


def validate(doc):
    """Returns a list of problems (empty = valid)."""
    errs = []
    segs = doc.get("segments")
    if not isinstance(segs, list) or not segs:
        return ["'segments' must be a non-empty list"]
    prev_end = None
    for i, s in enumerate(segs):
        for k in ("start_s", "end_s", "description"):
            if k not in s:
                errs.append(f"segment {i} has no {k!r}")
        if "start_s" in s and "end_s" in s and not s["end_s"] > s["start_s"]:
            errs.append(f"segment {i}: end_s must be after start_s")
        if s.get("quality") is not None and s["quality"] not in QUALITY:
            errs.append(f"segment {i}: quality must be one of {sorted(QUALITY)}")
        if prev_end is not None and "start_s" in s and s["start_s"] < prev_end - 0.05:
            errs.append(f"segment {i} overlaps the previous one")
        prev_end = s.get("end_s", prev_end)
    dur = doc.get("duration_s")
    if dur and prev_end is not None and prev_end < dur - 1.5:
        errs.append(f"segments end at {prev_end}s but the clip is {dur}s: cover the whole clip")
    return errs


def merge_into_human(human, agent):
    """Keep every human label; fill only EMPTY descriptions from the agent's
    segment with the same boundaries (or the one covering the midpoint)."""
    out = json.loads(json.dumps(human))
    for s in out.get("segments", []):
        if (s.get("description") or "").strip():
            continue
        mid = (s["start_s"] + s["end_s"]) / 2
        for t in agent.get("segments", []):
            if t["start_s"] <= mid < t["end_s"] and (t.get("description") or "").strip():
                s["description"] = t["description"]
                break
    return out


def cmd_put(path, annot, store=None):
    with open(annot, encoding="utf-8") as f:
        doc = json.load(f)
    errs = validate(doc)
    if errs:
        print("annotation rejected:\n  " + "\n  ".join(errs), file=sys.stderr)
        sys.exit(3)
    doc["file"] = os.path.abspath(path)
    existing = find(path, store)
    if existing and doc.get("annotator") != "human":
        with open(existing, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("annotator") == "human":
            doc = merge_into_human(old, doc)
            doc["file"] = os.path.abspath(path)
            B.log("kept the human annotation; filled empty descriptions only")
    d = stores_for(path, store)[0]
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{content_key(path)}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["hash", "get", "put", "status", "dump", "where"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--store", default=None)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    if a.cmd == "hash":
        print(content_key(a.args[0]))
    elif a.cmd == "where":
        print(stores_for(a.args[0], a.store)[0])
    elif a.cmd == "get":
        p = find(a.args[0], a.store)
        if not p:
            sys.exit(1)
        print(p.read_text(encoding="utf-8"))
    elif a.cmd == "put":
        if len(a.args) != 2:
            sys.exit("usage: annotations.py put FILE ANNOT.json")
        cmd_put(a.args[0], a.args[1], a.store)
    elif a.cmd == "status":
        missing = 0
        for f in a.args:
            try:
                state = "annotated" if find(f, a.store) else "MISSING"
            except OSError:
                state = "unreadable"
            missing += state != "annotated"
            print(f"{state}\t{f}")
        B.log(f"{len(a.args) - missing}/{len(a.args)} annotated")
    elif a.cmd == "dump":
        docs = []
        for f in a.args:
            p = find(f, a.store)
            if p:
                d = json.loads(p.read_text(encoding="utf-8"))
                d["file"] = os.path.abspath(f)
                docs.append(d)
            else:
                B.log(f"no annotation: {f}")
        blob = json.dumps(docs, indent=1, ensure_ascii=False)
        if a.out:
            Path(a.out).write_text(blob, encoding="utf-8")
            B.log(f"{len(docs)} annotations -> {a.out}")
        else:
            print(blob)


if __name__ == "__main__":
    main()
