#!/usr/bin/env python3
"""Survey a project's footage: what every clip is, how shaky, how busy and how loud, second
by second, without anyone looking at a frame. Contact sheets too, in privacy mode "frames".

  survey.py PROJECT [--no-sheets] [--force]

Finds every video (and photo) under the project's footage folders (work/project.json "sources",
read in place) and its own footage folder, gives each an id (its file name without extension),
and writes:
  work/clips.json       id -> path, kind, capture time (chronological order)
  work/meta/<id>.json   size as displayed (rotation applied), real fps, bitrate, capture time,
                        "copy" (why it looks like a messenger / cloud re-encode, else null),
                        motion every 0.5 s: activity (how much changes), pan (camera travel),
                        shake (frame-to-frame jitter left after removing the camera path,
                        px per 1/15 s at 960 px wide), and audio level every 0.5 s (dBFS)
  work/survey.md        one line per clip: the facts, steady stretches, loud moments, flags
  work/sheets/<id>.jpg  contact sheets (privacy "frames" only; skipped with --no-sheets)

The shake number is a triage hint: for a real measurement of a clip you plan to use, run
stabilize-clips' `stabilize.py --analyze`. Already surveyed clips are skipped (--force redoes).
Prints the survey.md path on stdout.
"""
from __future__ import annotations

import argparse
import array
import math
import re
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402
from hv import media, settings  # noqa: E402

COPY_NAME = re.compile(r"(whatsapp|-WA\d{3,}|^video-\d{9,}|^received_\d+|messenger|signal-\d|-EDIT|~\d\.)", re.I)
CAMERA_SIDES = {3840, 2160, 1920, 1080, 1280, 720, 2560, 1440, 4096, 2704, 1520, 2880, 1620, 5312, 2988, 7680, 4320, 3024, 4032, 1600, 900}
MOTION_FPS = 15
BUCKET_S = 0.5
SHAKY = 3.0          # survey shake (px per 1/15 s at 960 px) above which a stretch reads as shaky
STEADY = 1.2


def copy_reason(name: str, codec: str | None, w: int, h: int, fps: float, bitrate: float) -> str | None:
    """Why a clip looks re-compressed (sent through a messenger or a cloud backup) rather than
    a camera original. Originals look better: find them by date when this fires."""
    if COPY_NAME.search(name):
        return "messenger-style file name"
    if w not in CAMERA_SIDES or h not in CAMERA_SIDES:
        return f"odd frame size {w}x{h}"
    bpp = bitrate / max(1.0, w * h * max(fps, 1.0))
    if bpp < (0.12 if codec == "h264" else 0.04):
        return f"low bitrate for {codec} ({bitrate / 1e6:.1f} Mbps)"
    return None


def find_media(p: Path, cfg: dict) -> list:
    roots = [Path(s) for s in cfg.get("sources", [])] + [p / settings.layout("footage")]
    seen, out = set(), []
    for root in roots:
        if not root.is_dir():
            hv.log(f"MISSING footage folder: {root} (unplugged drive or unmounted share?)")
            continue
        for f in sorted(root.rglob("*")):
            if f.name.startswith(".") or not f.is_file() or "stabilized" in f.parts:
                continue
            ext = f.suffix.lower()
            if ext in hv.VIDEO_EXT or ext in hv.PHOTO_EXT:
                r = f.resolve()
                if r not in seen:
                    seen.add(r)
                    out.append(r)
    return out


def assign_ids(files: list, old: dict) -> dict:
    by_path = {v["path"]: k for k, v in old.items()}
    ids = {}
    used = set(old)
    for f in files:
        if str(f) in by_path:
            ids[by_path[str(f)]] = f
            continue
        base = re.sub(r"[^A-Za-z0-9_.-]+", "_", f.stem)
        cid, k = base, 2
        while cid in used:
            cid, k = f"{base}-{k}", k + 1
        used.add(cid)
        ids[cid] = f
    return ids


# ------------------------------------------------------------------ motion

def gray_frames(path: str, w: int, h: int):
    cmd = [media.ffmpeg(), "-v", "error", "-nostdin", "-i", path, "-an",
           "-vf", f"fps={MOTION_FPS},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(media.hw(cmd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                return
            yield buf
    finally:
        proc.stdout.close()
        proc.wait()


def profile(buf: bytes, w: int, h: int) -> tuple:
    cols = [sum(buf[c::w]) / h for c in range(w)]
    rows = [sum(buf[r * w:(r + 1) * w]) / w for r in range(h)]
    mc, mr = sum(cols) / w, sum(rows) / h
    return [x - mc for x in cols], [x - mr for x in rows]


def best_shift(a: list, b: list, maxs: int) -> float:
    """Shift of profile b against a (sub-pixel), by least mean absolute difference."""
    n = len(a)
    errs = {}
    for s in range(-maxs, maxs + 1):
        lo, hi = max(0, s), min(n, n + s)
        if hi - lo < n // 2:
            continue
        errs[s] = sum(abs(a[i] - b[i - s]) for i in range(lo, hi)) / (hi - lo)
    s0 = min(errs, key=errs.get)
    if s0 - 1 in errs and s0 + 1 in errs:
        e1, e2, e3 = errs[s0 - 1], errs[s0], errs[s0 + 1]
        den = e1 - 2 * e2 + e3
        if den > 0:
            return s0 + 0.5 * (e1 - e3) / den
    return float(s0)


def motion_profile(path: str, disp_w: int, disp_h: int) -> dict:
    if disp_w >= disp_h:
        w, h = 160, max(2, round(160 * disp_h / max(1, disp_w) / 2) * 2)
    else:
        h, w = 160, max(2, round(160 * disp_w / max(1, disp_h) / 2) * 2)
    to960 = 960 / max(w, h)
    prev, prof_prev = None, None
    moves, acts = [], []
    for buf in gray_frames(path, w, h):
        pr = profile(buf, w, h)
        if prev is not None:
            dx = best_shift(prof_prev[0], pr[0], 8)
            dy = best_shift(prof_prev[1], pr[1], 6)
            moves.append((dx, dy))
            acts.append(sum(abs(buf[i] - prev[i]) for i in range(0, len(buf), 4)) / (len(buf) / 4))
        prev, prof_prev = buf, pr
    n = len(moves)
    per_bucket = max(1, int(MOTION_FPS * BUCKET_S))
    if n < 3:
        return {"bucket_s": BUCKET_S, "activity": [], "pan": [], "shake": []}
    half = 2
    jit = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        ax = sum(m[0] for m in moves[lo:hi]) / (hi - lo)
        ay = sum(m[1] for m in moves[lo:hi]) / (hi - lo)
        jit.append(math.hypot(moves[i][0] - ax, moves[i][1] - ay) * to960)
    def buckets(xs, scale=1.0):
        return [round(sum(xs[i:i + per_bucket]) / len(xs[i:i + per_bucket]) * scale, 2) for i in range(0, len(xs), per_bucket)]
    return {"bucket_s": BUCKET_S, "activity": buckets(acts), "pan": buckets([math.hypot(*m) for m in moves], to960),
            "shake": buckets(jit)}


def audio_profile(path: str) -> list:
    r = subprocess.run([media.ffmpeg(), "-v", "error", "-nostdin", "-i", path, "-vn", "-map", "0:a:0", "-ac", "1",
                        "-ar", "8000", "-f", "s16le", "-acodec", "pcm_s16le", "-"], capture_output=True)
    if r.returncode or not r.stdout:
        return []
    a = array.array("h")
    a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    step = int(8000 * BUCKET_S)
    out = []
    for i in range(0, len(a), step):
        seg = a[i:i + step]
        p = sum(v * v for v in seg) / max(1, len(seg))
        out.append(round(10 * math.log10(p / 32768.0 ** 2 + 1e-10), 1))
    return out


# ------------------------------------------------------------------ summary

def stretches(vals: list, ok, min_len: int) -> list:
    out, start = [], None
    for i, v in enumerate(vals + [None]):
        if v is not None and ok(v):
            start = i if start is None else start
        else:
            if start is not None and i - start >= min_len:
                out.append((start * BUCKET_S, i * BUCKET_S))
            start = None
    return out


def summarize(m: dict) -> dict:
    sh, au = m.get("motion", {}).get("shake", []), m.get("audio", [])
    s = {}
    if sh:
        srt = sorted(sh)
        s["shake_median"] = srt[len(srt) // 2]
        s["shake_worst"] = srt[int(0.9 * (len(srt) - 1))]
        dur = m.get("dur") or len(sh) * BUCKET_S
        s["steady"] = [[a, min(b, round(dur, 1))] for a, b in stretches(sh, lambda v: v <= STEADY, 4)][:4]
        s["shaky"] = s["shake_median"] > SHAKY
    if au:
        med = statistics.median(au)
        s["audio_median_db"] = round(med, 1)
        loud = [i for i, v in enumerate(au) if v > med + 10 and v > -45]
        events, last = [], -10
        for i in loud:
            if i - last > 2:
                events.append(round(i * BUCKET_S, 1))
            last = i
        s["loud_moments"] = events[:8]
        s["silent"] = med < -60
    return s


def survey_one(cid: str, f: Path) -> dict:
    kind = "photo" if f.suffix.lower() in hv.PHOTO_EXT else "video"
    info = media.probe(f)
    w, h = hv.display_size(info)
    created, how = hv.capture_time(f, info.get("creation_time"))
    m = {"id": cid, "path": str(f), "kind": kind, "w": w, "h": h, "created": created, "created_from": how,
         "orientation": "portrait" if h > w else "landscape"}
    if kind == "video":
        dur = info["duration"] or 0.0
        size = f.stat().st_size
        bitrate = size * 8 / dur if dur else 0
        m.update(dur=round(dur, 3), fps=info["fps_float"], codec=info["vcodec"], has_audio=info["has_audio"],
                 bitrate=int(bitrate), copy=copy_reason(f.name, info["vcodec"], w, h, info["fps_float"] or 30, bitrate))
        m["motion"] = motion_profile(str(f), w, h)
        m["audio"] = audio_profile(str(f)) if info["has_audio"] else []
        m["summary"] = summarize(m)
    return m


def line(m: dict) -> str:
    if m["kind"] == "photo":
        return f"| {m['id']} | {m['created'][5:16].replace('T', ' ')} | photo | {m['orientation']} | | | |"
    s = m.get("summary", {})
    flags = []
    if m.get("copy"):
        flags.append(f"COPY? {m['copy']}")
    if m["orientation"] == "portrait":
        flags.append("portrait")
    if not m.get("has_audio") or s.get("silent"):
        flags.append("no sound")
    if (m.get("fps") or 0) >= 50:
        flags.append(f"{m['fps']:.0f} fps (slow-mo possible)")
    if s.get("shaky"):
        flags.append("SHAKY")
    steady = " ".join(f"{a:.1f}-{b:.1f}" for a, b in s.get("steady", []))
    loud = " ".join(f"{t:.1f}" for t in s.get("loud_moments", []))
    shake = f"{s.get('shake_median', '-')}/{s.get('shake_worst', '-')}"
    return (f"| {m['id']} | {m['created'][5:16].replace('T', ' ')} | {m['dur']:.1f}s | {m['w']}x{m['h']} | {shake} | "
            f"{s.get('audio_median_db', '-')} dB; loud at {loud or '-'} | steady {steady or '-'} | {'; '.join(flags)} |")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    p = hv.project_root(a.project)
    cfg = hv.project_cfg(p)
    W = hv.work(p)
    files = find_media(p, cfg)
    if not files:
        hv.die("no video or photo files found in the footage folders", 1)
    ids = assign_ids(files, hv.clips(p))
    metas = {}
    for cid, f in ids.items():
        mf = W / "meta" / f"{cid}.json"
        if mf.exists() and not a.force:
            metas[cid] = hv.load_json(mf)
            continue
        hv.log(f"survey {cid}")
        metas[cid] = survey_one(cid, f)
        hv.save_json(mf, metas[cid], indent=None)
    order = sorted(metas, key=lambda k: (metas[k]["created"], k))
    hv.save_json(W / "clips.json", {k: {"path": metas[k]["path"], "kind": metas[k]["kind"], "created": metas[k]["created"],
                                        "dur": metas[k].get("dur")} for k in order})
    vids = [metas[k] for k in order if metas[k]["kind"] == "video"]
    total = sum(m["dur"] for m in vids)
    lines = [f"# Survey of {cfg.get('name', p.name)}",
             "",
             f"{len(vids)} clips ({total / 60:.1f} min), {len(order) - len(vids)} photos, in shot order.",
             f"shake = median/worst per 0.5 s (px per 1/15 s at 960 px; > {SHAKY} reads shaky, <= {STEADY} steady). "
             "steady = stretches (s) a shot can come from. loud = seconds where the sound jumps 10 dB over the clip "
             "(a laugh, a splash, a voice). Times are seconds in the clip.",
             "",
             "| id | when | length | size | shake | sound | steady | flags |",
             "|---|---|---|---|---|---|---|---|"]
    day = None
    for k in order:
        d = metas[k]["created"][:10]
        if d != day:
            lines.append(f"| **{d}** | | | | | | | |")
            day = d
        lines.append(line(metas[k]))
    copies = [m for m in vids if m.get("copy")]
    if copies:
        lines += ["", f"{len(copies)} clip(s) look like re-compressed copies: look for the originals by date, or use them knowingly."]
    out = W / "survey.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not a.no_sheets and cfg.get("privacy") in hv.SHEETS_MADE:
        import sheets  # noqa
        for m in vids:
            f = W / "sheets" / f"{m['id']}.jpg"
            if not f.exists() or a.force:
                try:
                    sheets.make_sheet(m["path"], sheets.overview_times(m["dur"]), f)
                except RuntimeError as e:
                    hv.log(str(e))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
