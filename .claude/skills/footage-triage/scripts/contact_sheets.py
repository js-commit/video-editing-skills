#!/usr/bin/env python3
"""Step 2: one contact sheet (a grid of frames) per video and a thumbnail per
photo, into <work>/sheets/. The review page shows all of them; the classifier
agents read them unless the triage runs metadata-only.

  contact_sheets.py --inventory W/inventory.json [--force]

Re-runs skip sheets that already exist, so an interrupted run resumes with the
same command. Writes <work>/sheets/manifest.json {file id: {sheet, times}}.
stdout: JSON summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    inv = C.load_json(a.inventory)
    out = Path(inv["work_dir"]) / "sheets"
    mpath = out / "manifest.json"
    manifest = C.load_json(mpath) if mpath.exists() and not a.force else {}
    made = failed = 0
    files = [f for u in inv["units"] for f in u["files"]]
    for i, f in enumerate(files, 1):
        sp = out / f"{f['id']}.jpg"
        if f["id"] in manifest and sp.exists() and not a.force:
            continue
        if f["kind"] == "video":
            times = C.make_sheet(f["path"], sp, f.get("duration") or 0)
            ok = times is not None
        elif f["kind"] == "photo":
            times, ok = [], C.make_photo_thumb(f["path"], sp)
        else:
            continue
        if ok:
            manifest[f["id"]] = {"sheet": str(sp), "times": times}
            made += 1
        else:
            failed += 1
            C.log(f"  no sheet for {f['rel']}")
        if i % 20 == 0:
            C.log(f"  {i}/{len(files)}")
            C.write_json(mpath, manifest)
    C.write_json(mpath, manifest)
    print(json.dumps({"manifest": str(mpath), "made": made, "failed": failed, "total": len(manifest)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
