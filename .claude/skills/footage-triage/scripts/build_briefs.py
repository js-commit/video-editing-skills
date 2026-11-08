#!/usr/bin/env python3
"""Step 4: bundle the units into briefs, one per footage-classifier agent.

  build_briefs.py --inventory W/inventory.json [--hints "TEXT"] [--local | --metadata-only]
                  [--max-sheets 20]

Each brief holds whole units (never split across agents) with every file's
metadata, sound measurements, transcript snippet and contact sheet path, plus
the destinations the user has set up and their existing projects. With
--metadata-only no sheet paths are included, so the agents never see a frame
(for private footage): they decide from file names, dates, devices, lengths
and transcript snippets, and say so. With --local the vision model on this
computer (tools/vlm-describe) describes every sheet first and the briefs carry
those descriptions instead of sheet paths: the agents still never see a frame.
The descriptions are kept in W/local_descriptions.jsonl (resumable). In every
mode a clip's transcript snippet (its first 400 characters) is included when
W/audio.json has one: leave audio_check.py out to keep speech out of the briefs.

A unit with more sheets than --max-sheets gets an evenly spread subset.
Writes W/briefs/brief_N.json; each names the verdicts file its agent writes
(W/verdicts/brief_N.json). stdout: JSON with the brief paths.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

VLM = Path(__file__).resolve().parents[4] / "tools" / "vlm-describe" / "vlm_describe.py"
SHEET_PROMPT = (
    "This image is a contact sheet: {n} frame(s) from one video clip in time order (left to right, "
    "top to bottom; ignore the small time labels). In two or three sentences say what the clip shows: "
    "the subject (a person talking to the camera, a product, a pet, people, scenery, a screen), the "
    "action, the setting, the camera framing and movement, and whether it looks like junk (black, a "
    "lens cap, the floor, a bag). Do not guess brand names or people's names.")
PHOTO_PROMPT = ("Describe this photo in one or two sentences: the subject, the setting, and whether it "
                "looks accidental or unusable. Do not guess brand names or people's names.")


def local_descriptions(work: Path, manifest: dict, inv: dict) -> dict:
    """file id -> the local model's description of its sheet. Resumable through
    W/local_descriptions.jsonl; exits 2 with the --check hint when the model is not set up."""
    store = work / "local_descriptions.jsonl"
    done = {}
    if store.exists():
        for line in store.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("id") and rec.get("clip"):
                done[rec["id"]] = rec["clip"]
    kinds = {f["id"]: f["kind"] for u in inv["units"] for f in u["files"]}
    todo = [{"id": fid, "images": [{"path": str(m["sheet"])}], "per": "clip",
             "clip_prompt": PHOTO_PROMPT if kinds.get(fid) == "photo"
             else SHEET_PROMPT.replace("{n}", str(len(m.get("times") or []) or "several"))}
            for fid, m in manifest.items() if fid not in done and m.get("sheet")]
    if todo:
        batch = work / "local_batch.json"
        C.write_json(batch, todo)
        print(f"describing {len(todo)} sheet(s) with the local vision model (no frame leaves this computer)...",
              file=sys.stderr, flush=True)
        with open(store, "a", encoding="utf-8") as out:
            r = subprocess.run([sys.executable, str(VLM), "--batch", str(batch), "--quiet"],
                               stdout=out, stderr=subprocess.PIPE, text=True)
        if r.returncode == 2:
            sys.exit("the local vision model is not set up:\n" + r.stderr.strip()
                     + "\n(python3 tools/vlm-describe/vlm_describe.py --check shows how)")
        if r.returncode == 3:
            sys.exit("another local-model run is busy; try again when it is done")
        for line in store.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("id") and rec.get("clip"):
                done[rec["id"]] = rec["clip"]
        missing = [t["id"] for t in todo if t["id"] not in done]
        if missing:
            print(f"warning: {len(missing)} sheet(s) got no description ({r.stderr.strip()[-300:]})",
                  file=sys.stderr, flush=True)
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--hints", default="")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--metadata-only", action="store_true", help="agents see no frames: metadata and sound only")
    g.add_argument("--local", action="store_true",
                   help="agents see no frames: a vision model on this computer describes every sheet first")
    ap.add_argument("--max-sheets", type=int, default=20)
    a = ap.parse_args()
    inv = C.load_json(a.inventory)
    work = Path(inv["work_dir"])
    mpath = work / "sheets" / "manifest.json"
    manifest = C.load_json(mpath) if mpath.exists() else {}
    apath = work / "audio.json"
    audio = C.load_json(apath) if apath.exists() else {}
    if not manifest and not a.metadata_only:
        sys.exit("no contact sheets yet: run contact_sheets.py first (or pass --metadata-only)")
    described = local_descriptions(work, manifest, inv) if a.local else {}

    dests = inv["destinations"]
    available = {"project": bool(dests.get("projects_dir")), "home-videos": bool(dests.get("home_videos_dir")),
                 "broll-library": bool(dests.get("broll_library_dir")), "trash": True}
    units = []
    for u in inv["units"]:
        with_sheet = [f["id"] for f in u["files"] if f["id"] in manifest] if not (a.metadata_only or a.local) else []
        if len(with_sheet) > a.max_sheets:
            step = len(with_sheet) / a.max_sheets
            with_sheet = [with_sheet[int(i * step)] for i in range(a.max_sheets)]
        keep = set(with_sheet)
        files = []
        for f in u["files"]:
            au = audio.get(f["id"], {})
            files.append({k: v for k, v in {
                "file": f["rel"], "kind": f["kind"], "duration_s": f.get("duration"),
                "resolution": f"{f['width']}x{f['height']}" if f.get("width") else None, "fps": f.get("fps"),
                "capture_time": f["capture_time"], "time_source": f["time_source"],
                "mb": round(f["bytes"] / 1e6, 1), "has_audio": f["has_audio"],
                "sound_fraction": au.get("sound_fraction"), "mean_db": au.get("mean_db"),
                "speech_coverage": au.get("speech_coverage"), "transcript_snippet": au.get("snippet"),
                "sheet": manifest[f["id"]]["sheet"] if f["id"] in keep else None,
                "sheet_tile_times": manifest[f["id"]]["times"] if f["id"] in keep and f["kind"] == "video" else None,
                "description": described.get(f["id"]) if a.local else None,
            }.items() if v is not None})
        units.append({"unit_id": u["id"], "name": u["name"], "folder": u["folder"], "device": u["device"],
                      "first": u["first"], "last": u["last"], "counts": u["counts"], "minutes": u["minutes"],
                      "sheets_shown": len(keep), "files": files})

    bdir, vdir = work / "briefs", work / "verdicts"
    vdir.mkdir(parents=True, exist_ok=True)
    for old in bdir.glob("brief_*.json"):
        old.unlink()
    briefs, cur, cur_n = [], [], 0
    for u in units:
        if cur and cur_n + u["sheets_shown"] > a.max_sheets:
            briefs.append(cur)
            cur, cur_n = [], 0
        cur.append(u)
        cur_n += u["sheets_shown"]
        if (a.metadata_only or a.local) and len(cur) >= 15:
            briefs.append(cur)
            cur, cur_n = [], 0
    if cur:
        briefs.append(cur)
    paths = []
    for n, us in enumerate(briefs, 1):
        p = bdir / f"brief_{n}.json"
        C.write_json(p, {
            "verdicts_path": str(vdir / f"brief_{n}.json"), "hints": a.hints, "metadata_only": a.metadata_only,
            "local_descriptions": a.local,
            "destinations_available": available,
            "projects": [{"name": x["name"], "modified": x["modified"], "footage_folders": x["footage_folders"]}
                         for x in inv["projects"]],
            "units": us})
        paths.append(str(p))
    print(json.dumps({"briefs": paths, "units": len(units), "metadata_only": a.metadata_only, "local": a.local,
                      "next": "spawn one footage-classifier per brief (prompt: 'Brief: <path>'), all in one message; "
                              "then make_plan.py"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
