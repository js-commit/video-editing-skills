#!/usr/bin/env python3
"""Where thumbnails go, the candidate pool, and the user's pick.

  <dest>/thumbnail-candidates/own-N-<concept>.jpg     composited from real footage (ids O1, O2 ...)
  <dest>/thumbnail-candidates/ai-N-<concept>.jpg      from the optional AI round   (ids A1, A2 ...)
  <dest>/thumbnail-candidates/studio-N-<concept>.png  YouTube Studio's Ask Studio  (ids S1, S2 ...; studio-thumbnails skill)
  <dest>/thumbnail-candidates/gemini-N-<concept>.jpg  a Gemini image round         (ids G1, G2 ...; studio-thumbnails skill)
  <dest>/thumbnail-candidates/CANDIDATES.jpg        numbered contact sheet of the pool
  <dest>/thumbnail-candidates/INDEX.txt             one line per add / pick (with the compose command)
  <dest>/thumb-1.jpg, thumb-2.jpg, thumb-3.jpg      the picks, in the user's order

<dest> is the project's finals folder (settings project_layout.finals, default
"output"), or the folder of the video when it is not inside a project. Work
files (sampled frames, composites, references) go in <project>/<work>/thumbnails/.

  thumb_pool.py info <video-or-project>       JSON: project, dest, work dir, format
  thumb_pool.py add <dest> own|ai|studio|gemini FILE... [--concepts C ...] [--note TEXT] [--format F]
  thumb_pool.py sheet <dest>                  build CANDIDATES.jpg, list ids + paths
  thumb_pool.py pick <dest> O2 A1 O3          copy the picks to thumb-1..3

`add` fits anything that isn't exactly 1280x720 / 1080x1920 or is over 2 MB
(centre crop, resize, re-encode), so AI images from any tool can go straight
in. The pool only grows; `pick` never overwrites a delivered thumbnail: an
existing thumb-N is moved into thumbnail-candidates/replaced/ first.
Standard library + ffmpeg only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import thumbkit as tk  # noqa: E402
from vidkit import media, settings  # noqa: E402

SOURCES = {"own": ("O", "real footage"), "ai": ("A", "AI round"),
           "studio": ("S", "Ask Studio"), "gemini": ("G", "Gemini")}
PATTERN = re.compile(r"(own|ai|studio|gemini)-(\d+)(?:-(.*))?\.(jpe?g|png)$", re.I)
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".mxf", ".avi", ".webm", ".mts"}


def pool_dir(dest: Path) -> Path:
    return dest / "thumbnail-candidates"


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:48] or "concept"


def log(dest: Path, lines: list) -> None:
    pool_dir(dest).mkdir(parents=True, exist_ok=True)
    with open(pool_dir(dest) / "INDEX.txt", "a", encoding="utf-8") as f:
        f.write("".join(f"{datetime.now():%Y-%m-%d %H:%M}  {ln}\n" for ln in lines))


def candidates(dest: Path) -> list:
    """[(id, path, source, concept)] - own first, then ai, each by number."""
    found = []
    for p in pool_dir(dest).glob("*"):
        m = PATTERN.fullmatch(p.name)
        if m:
            src = m[1].lower()
            found.append((list(SOURCES).index(src), int(m[2]), p, src, (m[3] or "").replace("-", " ")))
    found.sort(key=lambda c: c[:2])
    return [(f"{SOURCES[s][0]}{n}", p, s, concept) for _, n, p, s, concept in found]


def info(target: str) -> dict:
    p = Path(target).expanduser()
    if not p.exists():
        p = settings.project_dir(target)
    p = p.resolve()
    video = p if p.is_file() else None
    project = settings.find_project_root(p) if video else (p if p.is_dir() else None)
    if project and not video:
        finals = project / settings.layout("finals")
        vids = sorted((f for f in finals.glob("*") if f.suffix.lower() in VIDEO_EXT),
                      key=lambda f: f.stat().st_mtime, reverse=True) if finals.is_dir() else []
        video = vids[0] if vids else None
    if project:
        dest = project / settings.layout("finals")
        work = project / settings.layout("work") / "thumbnails"
    else:
        dest = p.parent if video else p
        work = dest / "thumbnails-work"
    fmt = None
    if video:
        v = media.probe(video)
        w, h = v["width"] or 16, v["height"] or 9
        if abs(v.get("rotation") or 0) in (90, 270):
            w, h = h, w
        fmt = "short" if h > w else "landscape"
    transcript = None
    if video:
        try:
            from vidkit.transcript import find_sidecar
            transcript = find_sidecar(video)
        except ImportError:
            transcript = video.with_name(video.stem + ".transcript.json")
    return {"project": str(project) if project else None, "video": str(video) if video else None,
            "format": fmt, "dest": str(dest), "pool": str(pool_dir(dest)), "work": str(work),
            "transcript": str(transcript) if transcript and transcript.exists() else None}


def fit(src: Path, dst: Path, fmt: str | None) -> Path:
    """Centre-crop + resize to the YouTube canvas and re-encode under 2 MB."""
    w, h = tk.image_size(src)
    if fmt is None:
        fmt = "short" if h > w else "landscape"
    W, H = tk.FORMATS[fmt]
    if (w, h) == (W, H) and src.stat().st_size < tk.MAX_BYTES and src.suffix.lower() == dst.suffix.lower():
        shutil.copy2(src, dst)
        return dst
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1"
    dst = dst.with_suffix(".jpg")
    tk.save_jpeg_under(["-i", str(src)], dst, tk.MAX_BYTES, vf=vf)
    return dst


def add(dest: Path, source: str, files: list, concepts=(), note: str = "", fmt: str | None = None) -> list:
    pool = pool_dir(dest)
    pool.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(m[2]) for p in pool.glob(f"{source}-*") if (m := PATTERN.fullmatch(p.name))), default=0)
    files = [Path(f) for f in files]
    bad = [str(f) for f in files if not f.is_file()]
    if bad:
        raise SystemExit(f"no such file: {', '.join(bad)}")
    out, lines = [], []
    for i, f in enumerate(files):
        concept = concepts[i] if i < len(concepts) else f.stem
        dst = fit(f, pool / f"{source}-{n + i}-{slug(concept)}{f.suffix.lower()}", fmt)
        if dst.stat().st_size >= tk.MAX_BYTES:
            dst.unlink()
            raise SystemExit(f"{f}: still over 2 MB after fitting")
        out.append(dst)
        lines.append(f"{dst.name} = {SOURCES[source][0]}{n + i}  from {f.resolve()}" + (f"  | {note}" if note else ""))
    log(dest, lines)
    return out


def sheet(dest: Path) -> None:
    cands = candidates(dest)
    if not cands:
        raise SystemExit(f"no own-N / ai-N candidates in {pool_dir(dest)}")
    sizes = [tk.image_size(p) for _, p, _, _ in cands]
    vertical = sizes[0][1] > sizes[0][0]
    tw, th = (360, 640) if vertical else (640, 360)
    tiles = [(p, (f"{cid}  {concept}" + ("" if src == "own" else f"  ({SOURCES[src][1]})"))[:46])
             for cid, p, src, concept in cands]
    sheets = tk.contact_sheet(tiles, pool_dir(dest) / "CANDIDATES.jpg", cols=4 if vertical else 3,
                              tile_w=tw, tile_h=th, strip=48, per_sheet=12 if vertical else 9)
    print(json.dumps({"sheets": [str(s.resolve()) for s in sheets],
                      "candidates": [{"id": cid, "path": str(p.resolve()), "size": f"{w}x{h}",
                                      "mb": round(p.stat().st_size / 1e6, 2), "concept": concept}
                                     for (cid, p, _, concept), (w, h) in zip(cands, sizes)]}, indent=2))


def pick(dest: Path, ids: list) -> None:
    if not 1 <= len(ids) <= 3:
        raise SystemExit("pick 1 to 3 ids (a Short takes one)")
    by_id = {cid: p for cid, p, _, _ in candidates(dest)}
    ids = [i.upper() for i in ids]
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"unknown id(s) {missing}; the pool has {sorted(by_id)}")
    if len(set(ids)) != len(ids):
        raise SystemExit("an id is picked twice")
    replaced = pool_dir(dest) / "replaced"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    lines, out = [], []
    for n, cid in enumerate(ids, 1):
        src = by_id[cid]
        for old in sorted(dest.glob(f"thumb-{n}.*")):
            replaced.mkdir(parents=True, exist_ok=True)
            keep = replaced / f"{stamp}-{old.name}"
            k = 2
            while keep.exists():
                keep, k = replaced / f"{stamp}-{k}-{old.name}", k + 1
            shutil.move(str(old), str(keep))
            lines.append(f"{old.name} moved to replaced/{keep.name}")
        slot = dest / f"thumb-{n}{src.suffix.lower()}"
        shutil.copy2(src, slot)
        lines.append(f"{slot.name} = {cid} {src.name}  (pick {n})")
        out.append({"slot": n, "id": cid, "path": str(slot.resolve())})
    log(dest, lines)
    print(json.dumps(out, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info").add_argument("target")
    a = sub.add_parser("add")
    a.add_argument("dest", type=Path)
    a.add_argument("source", choices=SOURCES)
    a.add_argument("files", nargs="+")
    a.add_argument("--concepts", nargs="*", default=[])
    a.add_argument("--note", default="", help="logged with each file, e.g. the compose command")
    a.add_argument("--format", choices=tk.FORMATS, default=None, help="canvas to fit to (default: by shape)")
    sub.add_parser("sheet").add_argument("dest", type=Path)
    p = sub.add_parser("pick")
    p.add_argument("dest", type=Path)
    p.add_argument("ids", nargs="+")
    args = ap.parse_args()
    try:
        if args.cmd == "info":
            print(json.dumps(info(args.target), indent=2))
        elif args.cmd == "add":
            for f in add(args.dest, args.source, args.files, args.concepts, args.note, args.format):
                print(f.resolve())
        elif args.cmd == "sheet":
            sheet(args.dest)
        else:
            pick(args.dest, args.ids)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
