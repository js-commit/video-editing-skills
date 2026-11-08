#!/usr/bin/env python3
"""Pull sharp, distinct candidate frames out of video clips for a thumbnail.

Standard library + ffmpeg only. For each clip, one ffmpeg pass decodes a small
grey proxy every --interval seconds (ffmpeg applies the rotation tag, so phone
footage comes out upright). Each proxy is scored:

  sharpness  variance of the Laplacian, ranked within its own clip so dim or
             soft footage still competes fairly with crisp footage
  exposure   frames that are nearly black or blown out are penalised, not dropped
  sameness   near-identical frames (a difference hash) collapse onto the sharper one

The best frames are picked round-robin across clips (one long clip can't crowd
out the rest), re-extracted at FULL resolution as <clip>_t<seconds>s.jpg, and
laid out on numbered contact sheets (contact.jpg; contact_01.jpg ... when
there are more than 12) for Claude or you to
judge faces, expressions and subjects. candidates.json lists every pick.
Sharpness is only a blur signal: eyes, expression and whether the subject is
recognisable are judged by looking at the sheets.

Usage:
  sample_frames.py --outdir DIR [--interval 0.5] [--start S] [--end S]
                   [--top 24] [--per-clip N] CLIP [CLIP ...]

  --start/--end apply to every clip in the call (seconds in the clip). For a
  long video, sample the windows around the moments the transcript points at
  (one call per window) rather than the whole thing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import thumbkit as tk  # noqa: E402
from vidkit import media  # noqa: E402

PROXY_W = 256
EXPOSURE_PENALTY = 0.3
PTS = re.compile(r"pts_time:\s*([0-9.]+)")


def display_size(info: dict) -> tuple:
    w, h = info["width"], info["height"]
    if abs(info.get("rotation") or 0) in (90, 270):
        w, h = h, w
    return w, h


def proxy_frames(clip: Path, interval: float, start: float, end: float | None) -> list:
    """[(t_seconds, gray_bytes)] with w x h = PROXY_W x ph."""
    info = media.probe(clip)
    if not info["has_video"]:
        raise SystemExit(f"{clip}: no video stream")
    dw, dh = display_size(info)
    ph = max(2, round(PROXY_W * dh / dw / 2) * 2)
    dur = info["duration"] or 0
    t1 = min(end, dur) if end is not None and dur else (end or dur)
    sel = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{interval})'"
    base = [media.ffmpeg(), "-hide_banner", "-loglevel", "info", "-nostats", "-ss", str(start)]
    if t1:
        base += ["-to", str(t1)]
    base += ["-i", str(clip), "-an", "-vf", f"{sel},showinfo,scale={PROXY_W}:{ph}:flags=area,format=gray"]
    tail = ["-f", "rawvideo", "-pix_fmt", "gray", "-"]
    r = media.run(base + ["-fps_mode", "passthrough"] + tail, capture_output=True)
    if r.returncode != 0 and b"fps_mode" in r.stderr:
        r = media.run(base + ["-vsync", "0"] + tail, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg could not read {clip}:\n{r.stderr.decode('utf-8', 'replace')[-1500:]}")
    times = [start + float(m) for m in PTS.findall(r.stderr.decode("utf-8", "replace"))]
    size = PROXY_W * ph
    raw = r.stdout
    n = min(len(times), len(raw) // size)
    return [(times[i], raw[i * size:(i + 1) * size]) for i in range(n)], ph


def sharpness(px: bytes, w: int, h: int) -> float:
    """Variance of the 4-neighbour Laplacian (higher = more edge detail)."""
    s = s2 = n = 0
    for y in range(1, h - 1):
        up, row, dn = px[(y - 1) * w:y * w], px[y * w:(y + 1) * w], px[(y + 1) * w:(y + 2) * w]
        for u, l, c, r, d in zip(up[1:-1], row[:-2], row[1:-1], row[2:], dn[1:-1]):
            v = 4 * c - l - r - u - d
            s += v
            s2 += v * v
        n += w - 2
    if not n:
        return 0.0
    mean = s / n
    return s2 / n - mean * mean


def dhash(px: bytes, w: int, h: int) -> int:
    """64-bit difference hash from a 9x8 box-averaged thumbnail."""
    cells = []
    for gy in range(8):
        y0, y1 = gy * h // 8, (gy + 1) * h // 8
        row = []
        for gx in range(9):
            x0, x1 = gx * w // 9, (gx + 1) * w // 9
            tot = cnt = 0
            for y in range(y0, max(y1, y0 + 1)):
                seg = px[y * w + x0:y * w + max(x1, x0 + 1)]
                tot += sum(seg)
                cnt += len(seg)
            row.append(tot / max(1, cnt))
        cells.append(row)
    bits = 0
    for row in cells:
        for a, b in zip(row[:-1], row[1:]):
            bits = (bits << 1) | (1 if b > a else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def score_clip(clip: Path, args) -> list:
    frames, ph = proxy_frames(clip, args.interval, args.start, args.end)
    print(f"{clip.name}: {len(frames)} frames sampled", file=sys.stderr)
    measured = []
    for t, px in frames:
        mean = sum(px) / len(px)
        ok = 25.0 <= mean <= 235.0
        sh = sharpness(px, PROXY_W, ph)
        measured.append({"clip": str(clip.resolve()), "t": round(t, 3), "sharp": round(sh, 1),
                         "brightness": round(mean), "exposure_ok": ok,
                         "score": sh * (1.0 if ok else EXPOSURE_PENALTY), "hash": dhash(px, PROXY_W, ph)})
    if not measured:
        return []
    ranked = sorted(measured, key=lambda c: -c["score"])
    kept = []
    for c in ranked:
        if any(hamming(c["hash"], k["hash"]) < args.hash_dist for k in kept):
            continue
        kept.append(c)
        if args.per_clip and len(kept) >= args.per_clip:
            break
    return kept


def round_robin(per_clip: list, n: int) -> list:
    out, rank = [], 0
    while len(out) < n and any(len(c) > rank for c in per_clip):
        for c in per_clip:
            if rank < len(c) and len(out) < n:
                out.append(c[rank])
        rank += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 epilog="Details: see the top of this file.")
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--outdir", required=True, type=Path)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--top", type=int, default=24)
    ap.add_argument("--per-clip", type=int, default=None)
    ap.add_argument("--hash-dist", type=int, default=6, help="dHash bits under which two frames are the same moment")
    args = ap.parse_args()
    missing = [str(c) for c in args.clips if not c.is_file()]
    if missing:
        raise SystemExit(f"missing clip(s): {', '.join(missing)}")
    args.outdir.mkdir(parents=True, exist_ok=True)

    selected = round_robin([score_clip(c, args) for c in args.clips], args.top)
    if not selected:
        raise SystemExit("no frames extracted - check the clips and --start/--end")
    selected.sort(key=lambda c: -c["score"])
    tiles = []
    for rank, c in enumerate(selected, 1):
        c["rank"] = rank
        dest = args.outdir / f"{Path(c['clip']).stem}_t{c['t']:.2f}s.jpg"
        tk.ffrun(["-ss", f"{max(0.0, c['t'] - 0.0005):.4f}", "-i", c["clip"], "-frames:v", "1", "-update", "1",
                  "-q:v", "2", str(dest)], "full-resolution grab")
        c["file"] = str(dest.resolve())
        del c["hash"], c["score"]
        tiles.append((dest, f"#{rank} {Path(c['clip']).stem[:22]} @{c['t']:.1f}s"))
    sheets = tk.contact_sheet(tiles, args.outdir / "contact.jpg")
    (args.outdir / "candidates.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    print(json.dumps({"candidates": len(selected), "outdir": str(args.outdir.resolve()),
                      "contact_sheets": [str(s.resolve()) for s in sheets],
                      "candidates_json": str((args.outdir / "candidates.json").resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
