#!/usr/bin/env python3
"""Salvage: find the good b-roll a finished project shot but never used, before
its footage is archived or deleted. broll-salvage-picker agents read timestamped
contact sheets of the UNUSED stretches and pick short clips; apply cuts them
into the library.

  salvage.py prep PROJECT_DIR -o WORK [--drp EDIT.drp | --resolve] [--name SLUG]
             [--footage DIR] [--seconds-per-tile 2] [--batch-minutes 8]
      Lists the project's camera files, works out what the edit used (from the
      .drp / the open Resolve timeline, all tracks) and what the library already
      holds, makes contact sheets of everything else, splits it into batches and
      writes WORK/brief.md + WORK/batches.json. Prints one line per batch.
  salvage.py status WORK          which batches have a picks file yet
  salvage.py apply WORK [--dry-run] [--copy]
      Validates every WORK/picks/<batch>.json and cuts the picks into
      <library>/clips/<slug>-salvage/ with their descriptions.

Nothing in the project is changed. stdout: JSON. Exit 0 ok, 1 error, 3 picks
need fixing (details printed), 4 a setting is unset.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import drp  # noqa: E402
from vidkit import settings  # noqa: E402

HERE = Path(__file__).resolve().parent
AROLL_DIR = re.compile(r"a[-_ ]?roll", re.I)
MIN_FREE = 3.0
TILES = 12


def used_from_edit(a) -> tuple:
    """({file: [(in, out)]}, {files on V1}) from a .drp or the live timeline."""
    cuts = []
    if a.drp:
        p = drp.Project(a.drp)
        for tl in p.timelines():
            cuts += p.cuts(tl)
    elif a.resolve:
        import harvest_project
        cuts = harvest_project.cuts_from_resolve(None)[2]
    fps_cache = {}

    def real_fps(path):
        if path not in fps_cache:
            fps_cache[path] = (C.safe_probe(path) or {}).get("fps_float") if path and Path(path).exists() else None
        return fps_cache[path]

    cuts = [c for c in cuts if c.get("file_path")]
    drp.conform(cuts, real_fps)
    used, v1 = {}, set()
    for c in cuts:
        key = str(Path(c["file_path"]).resolve()) if Path(c["file_path"]).exists() else Path(c["file_path"]).name
        used.setdefault(key, []).append((c["source_in"], c["source_out"]))
        if c["track"] == 1:
            v1.add(key)
    return used, v1


def cmd_prep(a):
    proj = Path(a.project).expanduser().resolve()
    if not proj.is_dir():
        sys.exit(f"not a folder: {proj}")
    footage = Path(a.footage).expanduser().resolve() if a.footage else proj / settings.layout("footage")
    if not footage.is_dir():
        footage = proj
    slug = C.slugify(a.name or proj.name)
    work = Path(a.out).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    root = C.root_or_exit(create=True)

    used_edit, v1 = used_from_edit(a)
    lib_used = {}
    for c in C.load_catalog(root)["clips"]:
        lib_used.setdefault(str(C.to_abs(root, c["source_file"])), []).append((c["source_in"], c["source_out"]))

    files = [p for p in sorted(footage.rglob("*")) if p.is_file() and C.is_video(p)
             and not any(part.startswith((".", "_")) for part in p.relative_to(footage).parts)]
    infos, skipped = [], []
    for f in files:
        info = C.safe_probe(f)
        if not info or not info.get("duration"):
            skipped.append({"file": str(f), "why": "unreadable"})
            continue
        key = str(f.resolve())
        used = used_edit.get(key, []) + used_edit.get(f.name, []) + lib_used.get(key, [])
        free = [(round(s, 2), round(e, 2)) for s, e in C.subtract_ranges((0.0, info["duration"]), used)
                if e - s >= MIN_FREE]
        if not free:
            skipped.append({"file": str(f), "why": "fully used by the edit or already in the library"})
            continue
        aroll = key in v1 or f.name in v1 or any(AROLL_DIR.search(p) for p in f.relative_to(footage).parts[:-1])
        fdir = work / "files" / C.slugify(f.stem)
        sheets, n = [], 0
        win = a.seconds_per_tile * TILES
        for s, e in free:
            t = s
            while t < e - 0.5:
                t1 = min(e, t + win)
                n += 1
                sp = fdir / f"s{n:03d}.jpg"
                frames = max(1, min(TILES, int(round((t1 - t) / a.seconds_per_tile))))
                times = C.make_sheet(f, sp, t, t1, frames=frames, cols=4)
                if times:
                    sheets.append({"sheet": str(sp), "start": round(t, 2), "end": round(t1, 2), "tile_times": times})
                t = t1
        rec = {"file": str(f), "stem": f.stem, "duration": round(info["duration"], 2), "fps": info.get("fps_float"),
               "width": info.get("width"), "height": info.get("height"), "aroll": aroll,
               "used_ranges": [(round(s, 2), round(e, 2)) for s, e in C.merge_ranges(used, 0)],
               "free_ranges": free, "free_seconds": round(sum(e - s for s, e in free), 1), "sheets": sheets}
        C.write_json(fdir / "info.json", rec)
        infos.append((rec, fdir / "info.json"))
        C.log(f"  {f.name}: {rec['free_seconds']}s unused, {len(sheets)} sheets{'  (a-roll angle)' if aroll else ''}")

    batches, cur, cur_s, cur_n = [], [], 0.0, 0
    for rec, ip in infos:                 # ~8 min and at most 40 sheets per picker
        if cur and (cur_s + rec["free_seconds"] > a.batch_minutes * 60 or cur_n + len(rec["sheets"]) > 40):
            batches.append(cur)
            cur, cur_s, cur_n = [], 0.0, 0
        cur.append(str(ip))
        cur_s += rec["free_seconds"]
        cur_n += len(rec["sheets"])
    if cur:
        batches.append(cur)
    out = [{"batch": f"b{i}", "info_files": b, "picks": str(work / "picks" / f"b{i}.json")} for i, b in enumerate(batches, 1)]
    (work / "picks").mkdir(exist_ok=True)
    C.write_json(work / "batches.json", {"project": str(proj), "name": slug, "batches": out, "skipped": skipped})
    tmpl = (HERE.parent / "reference" / "salvage-brief.md").read_text(encoding="utf-8")
    brief = work / "brief.md"
    if not brief.exists():
        brief.write_text(tmpl.replace("{{PROJECT}}", proj.name).replace("{{WORK}}", str(work)), encoding="utf-8")
    print(json.dumps({"work": str(work), "brief": str(brief), "files": len(infos), "skipped": len(skipped),
                      "unused_seconds": round(sum(r["free_seconds"] for r, _ in infos), 1),
                      "batches": [{"batch": b["batch"], "files": len(b["info_files"]), "picks": b["picks"]} for b in out],
                      "next": "fill in the 'What this project is about' part of brief.md, then spawn one "
                              "broll-salvage-picker per batch; then salvage.py apply " + str(work)}, indent=2))
    return 0


def cmd_status(a):
    work = Path(a.work).expanduser().resolve()
    b = json.loads((work / "batches.json").read_text())
    rows = [{"batch": x["batch"], "done": Path(x["picks"]).exists()} for x in b["batches"]]
    print(json.dumps({"batches": rows, "missing": [r["batch"] for r in rows if not r["done"]]}, indent=2))
    return 0


def cmd_apply(a):
    work = Path(a.work).expanduser().resolve()
    b = json.loads((work / "batches.json").read_text())
    infos = {}
    for x in b["batches"]:
        for ip in x["info_files"]:
            rec = json.loads(Path(ip).read_text())
            infos[rec["file"]] = rec
            infos.setdefault(rec["stem"], rec)
    picks, problems, missing = [], [], []
    for x in b["batches"]:
        pp = Path(x["picks"])
        if not pp.exists():
            missing.append(x["batch"])
            continue
        for p in json.loads(pp.read_text()).get("picks", []):
            rec = infos.get(p.get("file")) or infos.get(p.get("stem"))
            s, e = float(p.get("source_in", -1)), float(p.get("source_out", -1))
            if not rec:
                problems.append(f"{x['batch']}: unknown file {p.get('file') or p.get('stem')}")
            elif not (e - s >= 1.0):
                problems.append(f"{x['batch']}: {rec['stem']} {s}-{e} is shorter than 1 s")
            elif not any(fs - 0.05 <= s and e <= fe + 0.05 for fs, fe in rec["free_ranges"]):
                problems.append(f"{x['batch']}: {rec['stem']} {s}-{e} overlaps footage the edit or library already used")
            elif not p.get("description"):
                problems.append(f"{x['batch']}: {rec['stem']} {s}-{e} has no description")
            else:
                picks.append((rec, s, e, p))
    if problems:
        print(json.dumps({"problems": problems, "note": "fix the picks files (or re-spawn that batch's picker)"}, indent=2))
        return 3
    summary = {"picks": len(picks), "seconds": round(sum(e - s for _, s, e, _ in picks), 1), "batches_without_picks": missing}
    if a.dry_run:
        summary["dry_run"] = True
        summary["plan"] = [{"file": r["file"], "in": s, "out": e, "description": p["description"]} for r, s, e, p in picks]
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    root = C.root_or_exit(create=True)
    slug = b["name"] + "-salvage"
    out_dir = root / "clips" / slug
    with C.Lock(root, f"salvage apply {slug}"):
        data = C.load_catalog(root)
        added = 0
        for rec, s, e, p in picks:
            dst = out_dir / f"{slug}_{C.slugify(rec['stem'])}_{s:.1f}s.mp4"
            if not dst.exists() and not C.extract(rec["file"], dst, s, e, 1.0, a.copy):
                continue
            info = C.safe_probe(dst) or {}
            tags = [C.slugify(t) for t in p.get("tags") or []]
            r = C.new_record(root, path=dst, start=0.0, end=info.get("duration") or e - s, in_place=False,
                             source_project=b["name"], source_file=rec["file"], source_in=s, source_out=e,
                             origin="salvage", info=info, description=p["description"], tags=tags,
                             described_by="broll-salvage-picker")
            sheet = C.catalog_dir(root) / "sheets" / f"{r['id']}.jpg"
            if C.make_sheet(dst, sheet, 0.0, r["end"]):
                r["sheet"] = C.to_stored(root, sheet)
            added += C.upsert(data, r)
        C.save_catalog(root, data)
    summary.update({"added": added, "folder": str(out_dir)})
    print(json.dumps(summary, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("project")
    p.add_argument("-o", "--out", required=True, help="work folder (scratch, outside the project is fine)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--drp")
    g.add_argument("--resolve", action="store_true")
    p.add_argument("--name")
    p.add_argument("--footage", help="the folder holding the camera files (default: the project's footage folder)")
    p.add_argument("--seconds-per-tile", type=float, default=2.0)
    p.add_argument("--batch-minutes", type=float, default=8.0)
    s = sub.add_parser("status")
    s.add_argument("work")
    ap_ = sub.add_parser("apply")
    ap_.add_argument("work")
    ap_.add_argument("--dry-run", action="store_true")
    ap_.add_argument("--copy", action="store_true")
    a = ap.parse_args()
    return {"prep": cmd_prep, "status": cmd_status, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
