#!/usr/bin/env python3
"""Cut a planned sequence into separate library clips, numbered in sequence order,
and file each one in the b-roll library (broll-library skill) with its description,
tags and contact sheet.

A sequence is a run of separate clips, one per beat, so each beat is its own
library entry (description, sheet, search hit) and laying them back to back in
index order rebuilds the paced sequence. Each record carries `sequence`,
`sequence_index`, `sequence_start` and `sequence_end` (the beat's place in the
sequence) so a search can show a beat's neighbours.

    export_clips.py PLAN.json --slug <library folder slug> [--start-index 1] [--sequence "unboxing: <product>"]
                    [--res 2160|1080] [--dry-run]

PLAN.json is sequence.py's plan at the agreed pace (its moments file supplies
the sources, flip and speech settings, and each beat's description). Clips go to
<library>/footage/<slug>/<NNN>_<label>.mp4 (H.264 through vidkit.media, the
beat's audio exactly as the preview carries it: speech mute, fades), with a
contact sheet in the catalog's sheets folder. Re-running replaces a beat whose
range changed and keeps its id when it did not. One ffmpeg at a time.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.exit("this script needs numpy scipy: python3 -m pip install numpy scipy")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "broll-library" / "scripts"))
import common as C  # noqa: E402
import sequence  # noqa: E402
from vidkit import media  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--slug", required=True, help="library sub-folder and source_project name, e.g. phone-x-unboxing")
    ap.add_argument("--start-index", type=int, default=1)
    ap.add_argument("--sequence", help="sequence name (default: '<kind>: <product>')")
    ap.add_argument("--res", type=int, choices=(1080, 2160), default=2160)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    plan = json.load(open(a.plan))
    spec = json.load(open(plan["moments_file"]))
    sources = {k: sequence.Source(k, v) for k, v in spec["sources"].items()}
    by_label = {m.get("label"): m for m in spec["moments"]}
    seq_name = a.sequence or f'{spec.get("kind", "unboxing")}: {spec.get("product") or spec.get("name")}'
    slug = C.slugify(a.slug)
    lib = C.settings.get_path("paths.broll_library_dir") if a.dry_run else None
    if lib and not lib.is_dir() and lib.parent.is_dir():   # a dry run creates nothing: the real run makes the folder
        root = lib
        print(f"(the library folder {lib} does not exist yet; the real run creates it)")
    else:
        root = C.root_or_exit(create=not a.dry_run)
    out_dir = root / "footage" / slug
    fade = plan["pace_profile"]["fade"]
    h = 2160 if a.res == 2160 else 1080

    rows = []
    for i, b in enumerate(plan["beats"]):
        src = sources[b["src"]]
        fps = src.fps
        n = b["f_out"] - b["f_in"]
        s_in, s_out = b["f_in"] / fps, b["f_out"] / fps
        label = re.sub(r"[^A-Za-z0-9]+", "-", b["label"]).strip("-")[:40] or b["kind"]
        fname = f"{a.start_index + i:03d}_{label}.mp4"
        out = out_dir / fname
        desc = " ".join(by_label.get(lb, {}).get("description", "") for lb in b["label"].split(" + ")).strip()
        tags = sorted(set(spec.get("tags", []) + by_label.get(b["label"].split(" + ")[0], {}).get("tags", [])
                          + [spec.get("kind", "unboxing"), b["kind"], b["section"], "sequence"]) - {""})
        rows.append((i, b, src, fps, n, s_in, s_out, out, desc or b["label"], tags))
        print(f"{fname}  {n / fps:5.2f}s  {b['kind']:9s} {b['label'][:60]}" + ("  (dry run)" if a.dry_run else ""))
    if a.dry_run:
        print(f"{len(rows)} clips -> {out_dir}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_dir = C.catalog_dir(root) / "sheets"
    with C.Lock(root, "unboxing-cut export"):
        data = C.load_catalog(root)
        for i, b, src, fps, n, s_in, s_out, out, desc, tags in rows:
            rec_id = C.clip_id(src.path, s_in, s_out)
            old = next((c for c in data["clips"] if c["id"] == rec_id), None)
            if not (old and out.exists() and (old.get("sequence_meta") or {}).get("speech") == src.speech):
                # audio exactly as the preview carries it (speech mute, fades), video frame-exact from the frame start
                x = sequence.pcm(src.path, s_in, s_out - s_in, 2)
                aud = sequence.beat_audio(src, b, x, s_in, fade)
                tmp = tempfile.NamedTemporaryFile(suffix=".f32", delete=False)
                aud.astype(np.float32).tofile(tmp.name)
                tmp.close()
                seek = math.floor(math.floor(s_in * fps + 1e-6) / fps * 1e6) / 1e6
                vf = ["hflip,vflip"] if src.flip else []
                vf.append("format=yuv420p")
                cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-ss", f"{seek:.6f}", "-i", src.path,
                       "-f", "f32le", "-ar", str(sequence.SR), "-ac", "2", "-i", tmp.name,
                       "-map", "0:v:0", "-map", "1:a", "-frames:v", str(n), "-vf", ",".join(vf)]
                cmd += media.h264_args("final", height=min(h, src.meta["height"]))
                cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
                media.run(cmd, check=True)
                os.remove(tmp.name)
            info = C.safe_probe(out) or {}
            sheet = sheet_dir / f"{rec_id}.jpg"
            C.make_sheet(out, sheet, force=True)
            rec = C.new_record(root, path=out, start=0.0, end=info.get("duration") or (n / fps), in_place=False,
                               source_project=slug, source_file=src.path, source_in=s_in, source_out=s_out,
                               origin="unboxing-cut", info=info, description=desc, tags=tags,
                               described_by="unboxing-cut (the moments file)")
            rec["sheet"] = C.to_stored(root, sheet)
            rec["sequence"] = seq_name
            rec["sequence_index"] = a.start_index + i
            rec["sequence_start"] = b["start_s"]
            rec["sequence_end"] = b["end_s"]
            rec["sequence_meta"] = {"pace": plan["pace"], "beat": i + 1, "beats": len(plan["beats"]), "kind": b["kind"],
                                    "label": b["label"], "section": b["section"], "hero": bool(b.get("hero")),
                                    "flip": src.flip, "speech": src.speech, "moments_file": plan["moments_file"]}
            # one record per clip file: the same range replaces its record wholesale (the clip was re-cut or kept),
            # and a changed range drops the old record that pointed at this file (ffmpeg just overwrote it)
            data["clips"] = [c for c in data["clips"] if c["id"] != rec_id and c.get("path") != rec["path"]]
            data["clips"].append(rec)
        C.save_catalog(root, data)
    print(json.dumps({"clips": len(rows), "folder": str(out_dir), "sequence": seq_name,
                      "next": f"search them: search.py \"{spec.get('product') or slug}\"; a wrong beat: "
                              f"catalog.py remove <id>, fix the moments file, re-run"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
