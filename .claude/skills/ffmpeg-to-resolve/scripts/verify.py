#!/usr/bin/env python3
"""Is the Resolve timeline the ffmpeg render? Measured three ways, written to <job folder>/verify_report.json.

    verify.py <job folder>/job.json [--reference DRAFT.mp4] [--resolve-render FILE.mp4] [--no-render] [--keep-render]
              [--old-renderer] [--sheets N]

1. Structure - every job item re-read from the saved timeline: track, record frame, length, source frame (sub-frame for
   a separately recorded mic), inspector values, fades, LUT. Whole frames, no tolerance.
2. Picture - Resolve renders the timeline (resolve-export-draft's render_draft.py) and every frame is compared with the
   ffmpeg draft of the same recipe: SSIM at the same frame, one frame early and one frame late. Per picture piece (the
   renderer's own pieces: a-roll between bricks, each brick, split at overlay edges) the verdict is
     ok         the same frame matches best, and well
     resampled  a clip at another rate or speed than the timeline's: ffmpeg rounds to the nearest source frame, Resolve
                takes the earlier one - same first frame, same length, some frames one source frame apart (a fast
                scroll reads that as a low SSIM, so these are judged on their first frame and on being the same shot)
     static     nothing moves, so a one-frame slip cannot be seen (the structure check covers it)
     draft-late only with --old-renderer, for a draft made before render_recipe.py seeked half a frame early: its
                4-decimal seek started some pieces one frame late. Predicted per piece from the recipe; the piece
                passes only if it matches one frame along, exactly as predicted
     SHIFTED    a neighbouring frame matches better where it should not: the source frame is off by one
     DIFFERENT  the right frame, but the picture is not the same (framing, colour, a missing layer)
     EDGE       the first or last frame of the piece is another shot: a cut is a frame off
     LEVEL      a frame's brightness or colour differs (a fade, a grade, a range mistake)
3. Sound - both mixes decoded to mono; per keep, the lag of Resolve against the draft by cross-correlation (ms) and the
   level difference (dB). Each side is loudness-normalised by its own tool, so only a keep far from the median fails.

The reference must be the draft of THIS recipe: the job's recipe hash is checked against the recipe file, the draft
must be newer than the recipe and have the timeline's frame count. Rows that fail get a side-by-side sheet (draft |
Resolve, the worst frame) in <job folder>/verify/ - read those, not the whole video. Exit 1 on any failed row.
Needs numpy (python3 -m pip install numpy; ask the user first).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.exit("verify.py needs numpy for the picture and sound comparison. Install it with:\n"
             "  python3 -m pip install numpy\n(ask the user first)")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "talking-head-ffmpeg" / "scripts"))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402

RENDER = HERE.parent.parent / "resolve-export-draft" / "scripts" / "render_draft.py"
CMP_W, CMP_H = 640, 360
SSIM_OK = 0.90          # same frame, same picture: scaler and decoder differences stay above this (fixture: 0.97+)
SHIFT_MARGIN = 0.004    # a neighbour has to beat the same frame by this to call a slip
STATIC = 0.0015         # all three within this: nothing moves
DARK = 24.0             # mean luma under this on both sides: a fade's tail
LEVEL_OK = 4.0          # mean Y, U or V difference a frame may have (8-bit levels)
RESAMPLED_FIRST = 0.95  # a clip at another rate: its first frame must be the draft's
RESAMPLED_OK = 0.75     # ... and the rest the same shot, a source frame apart at most
LAG_OK_MS = 1.0
LEVEL_DB_OK = 3.0       # a keep's level against the median keep: the draft's loudnorm and Resolve's delivery normaliser both move it
SR = 48000


def frames_of(path):
    out = subprocess.run([C.ffprobe(), "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries", "stream=nb_read_packets",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.split()
    return int(out[0].split(",")[0]) if out else 0


def ssim_three(res, ref, fps):
    """Per-frame luma SSIM of the Resolve render against the draft: same frame, Resolve one frame late, one early."""
    tmp = tempfile.mkdtemp(prefix="f2r-ssim-")
    norm = f"scale={CMP_W}:{CMP_H}:flags=bilinear,format=gray,setpts=N/({fps})/TB"
    fc = (f"[0:v]{norm},split=3[a0][a1][a2];[1:v]{norm},split=3[b0][b1][b2];"
          f"[a0][b0]ssim=stats_file={tmp}/s0.log[o0];"
          f"[a1]trim=start_frame=1,setpts=N/({fps})/TB[a1t];[a1t][b1]ssim=stats_file={tmp}/sp.log:shortest=1[o1];"
          f"[b2]trim=start_frame=1,setpts=N/({fps})/TB[b2t];[a2][b2t]ssim=stats_file={tmp}/sm.log:shortest=1[o2]")
    r = subprocess.run([C.ffmpeg(), "-v", "error", "-y", "-i", str(res), "-i", str(ref), "-filter_complex", fc,
                        "-map", "[o0]", "-f", "null", "-", "-map", "[o1]", "-f", "null", "-", "-map", "[o2]", "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit("ssim: " + r.stderr[-500:])

    def load(name):
        with open(os.path.join(tmp, name + ".log"), encoding="utf-8") as fh:
            return np.array([float(line.split("All:")[1].split()[0]) for line in fh])
    s0, sp, sm = load("s0"), load("sp"), load("sm")
    return s0, sp, sm      # sp[f]: Resolve f+1 vs draft f;  sm[f]: Resolve f vs draft f+1


def levels(path):
    """Mean Y, U and V (0-255) of every frame, from a 64x36 copy: brightness and colour, cheap enough for every frame.
    Clipped to the legal range first: the ffmpeg draft keeps a camera's super-white (a blown window at 255) and Resolve's
    delivery clips it at 235, which is the same white on a screen (measured: a 4-level "error" on a shot of a window)."""
    raw = subprocess.run([C.ffmpeg(), "-v", "error", "-i", str(path), "-an", "-vf", "format=yuv420p,lutyuv=y='clip(val,16,235)':u='clip(val,16,240)':v='clip(val,16,240)',scale=64:36:flags=area,format=yuv444p",
                          "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    d = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3, 64 * 36).mean(axis=2)
    return d[:, 0], d[:, 1], d[:, 2]


def mono(path):
    raw = subprocess.run([C.ffmpeg(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def lag_of(a, b, max_lag):
    """Samples by which b lags a (positive: b is late), and the normalised correlation at that lag."""
    n = len(a) + len(b)
    size = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    c = np.concatenate([c[-max_lag:], c[:max_lag + 1]])       # lags -max..+max of (a against b)
    i = int(np.argmax(c))
    peak = c[i] / (np.sqrt(np.dot(a, a) * np.dot(b, b)) + 1e-12)
    return -(i - max_lag), float(peak)


def sheet(ref, res, frame, fps, out, label):
    """Draft | Resolve at one frame, side by side."""
    t = float(frame / fps)
    back = min(t, 1.0)
    pick = f"select='gte(t,{back - 0.5 / float(fps):.4f})',scale=960:-2:out_range=tv,format=yuv420p,setpts=N/TB"
    subprocess.run([C.ffmpeg(), "-v", "error", "-y", "-ss", f"{t - back:.4f}", "-i", str(ref), "-ss", f"{t - back:.4f}", "-i", str(res),
                    "-filter_complex", f"[0:v]{pick}[a];[1:v]{pick}[b];[a][b]hstack", "-frames:v", "1", "-q:v", "3", str(out)], capture_output=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job")
    ap.add_argument("--reference", help="the ffmpeg draft of this recipe (default: where render_recipe.py puts it)")
    ap.add_argument("--resolve-render", help="an existing Resolve render of the timeline to compare instead of rendering")
    ap.add_argument("--no-render", action="store_true", help="structure only")
    ap.add_argument("--old-renderer", action="store_true",
                    help="the reference draft was rendered before render_recipe.py had seek(), when its 4-decimal seek started "
                         "some pieces a frame late: expect those pieces one frame along (draft-late) instead of failing them")
    ap.add_argument("--keep-render", action="store_true", help="keep Resolve's render in <job dir>/verify/ (it is deleted once measured)")
    ap.add_argument("--sheets", type=int, default=12, help="at most this many failure sheets")
    a = ap.parse_args()
    jp = Path(a.job).resolve()
    job = C.read_json(jp)
    out = jp.parent
    fps = Fraction(job["fps"])
    F = job["frames"]
    report = {"ok": False, "timeline": job["timeline"], "checks": {}}
    fails = []

    rec_path = Path(job["recipe"])
    if hashlib.sha1(rec_path.read_bytes()).hexdigest() != job["recipe_sha1"]:
        sys.exit(f"{rec_path} changed since this job was planned - plan, bake and build again")
    rec = json.loads(rec_path.read_bytes())

    # ---- 1. structure
    import build as B
    from vidkit.resolve import connect, timelines
    resolve = connect()
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if not proj or proj.GetName() != job["project"]:
        proj = pm.LoadProject(job["project"])
    if proj is None:
        sys.exit(f"project {job['project']!r} not found")
    tl = next((t for t in timelines(proj) if t.GetName() == job["timeline"]), None)
    if tl is None:
        sys.exit(f"timeline {job['timeline']!r} not found - build.py first")
    proj.SetCurrentTimeline(tl)
    base = tl.GetStartFrame()
    rows, bad, stray = B.readback(tl, job, base)
    length = tl.GetEndFrame() - base
    report["checks"]["structure"] = {"items": len(rows), "wrong": bad, "stray_items": stray, "timeline_frames": length, "want_frames": F}
    for r in rows:
        if not r["ok"]:
            fails.append(f"structure {r['id']} {r['track']} @ {r['rec_f']}: {'; '.join(r['why'])}")
    fails += [f"structure: an item the job does not know: {s}" for s in stray]
    if length != F:
        fails.append(f"structure: the timeline is {length} frames, the recipe {F}")

    if not a.no_render:
        import render_recipe as RR
        ref = Path(a.reference) if a.reference else RR.out_path(rec_path, rec, False)
        if not ref.exists():
            sys.exit(f"no reference draft at {ref}: render the recipe (render_recipe.py) or pass --reference")
        if ref.stat().st_mtime < rec_path.stat().st_mtime:
            sys.exit(f"{ref} is older than the recipe - it is not this recipe's draft; render it again")
        if frames_of(ref) != F:
            sys.exit(f"{ref} has {frames_of(ref)} frames, the recipe {F} - not this recipe's draft")
        # ---- render from Resolve
        if a.resolve_render:
            res = Path(a.resolve_render)
        else:
            rdir = out / "verify"
            rdir.mkdir(exist_ok=True)
            name = "resolve-render"
            for old in rdir.glob(name + ".*"):
                if old.is_file() and old.suffix.lower() in (".mp4", ".mov"):
                    old.unlink()
            h = min(job["width"], job["height"], int(C.settings.get("render.draft_height", default=1080) or 1080))   # the short side
            r = subprocess.run([sys.executable, str(RENDER), "--project", job["project"], "--timeline", job["timeline"],
                                "--out-dir", str(rdir), "--name", name, "--height", str(h)], capture_output=True, text=True)
            (rdir / "render.log").write_text(r.stdout + "\n" + r.stderr)
            got = sorted(rdir.glob(name + ".*"))
            got = [g for g in got if g.suffix.lower() in (".mp4", ".mov")]
            if r.returncode or not got:
                sys.exit(f"Resolve render failed (exit {r.returncode}): {(r.stderr or r.stdout)[-600:]}")
            res = got[0]
        got_f = frames_of(res)
        report["checks"]["render"] = {"file": str(res), "reference": str(ref), "frames": got_f, "want_frames": F}
        if got_f != F:
            fails.append(f"render: Resolve wrote {got_f} frames, the recipe has {F}")

        # ---- 2. picture
        from plan import old_seek_frame
        s0, sp, sm = ssim_three(res, ref, f"{fps.numerator}/{fps.denominator}")
        (ya, ua, va), (yb, ub, vb) = levels(ref), levels(res)
        n = min(len(s0), F, len(ya), len(yb))
        dark = (ya[:n] < DARK) & (yb[:n] < DARK)            # SSIM means nothing on black: those frames are judged on level
        bricks = {b["i"]: b for b in R.brick_frames(rec)}
        pieces = R.with_overlays(rec, R.flatten(rec))       # the renderer's own pieces: each one is a separate seek
        prow, sheets = [], []
        for i, p in enumerate(pieces):
            lo, hi = p["rec_f"], min(p["rec_f"] + p["n"], n)
            if hi <= lo:
                continue
            fn = R.probe(p["file"])[1]
            step = p["speed"] * float(fn) / float(fps)
            # where the draft starts this piece (ffmpeg's seek) against where the recipe says it starts
            expect = None
            if abs(step - 1) < 1e-4:
                first = (lambda f, t: old_seek_frame(t, fn, f)) if a.old_renderer else (lambda f, t: RR.seek(f, t)[0])
                got = first(p["file"], p["in_s"])
                if p["kind"] == "aroll":
                    want = round(p["in_s"] * fps)
                else:
                    b = bricks[p["brick"]]
                    want = RR.seek(b["file"], b["in_s"])[0] + (lo - b["rec_f"])
                expect = got - want
            idx = np.arange(lo, hi)
            keep = idx[~dark[lo:hi]]
            inner = keep[(keep > lo) & (keep < hi - 1)] if len(keep) > 4 else keep
            m0 = float(s0[inner].mean()) if len(inner) else 1.0
            late = inner[inner < len(sp)]
            mp_ = float(sp[late].mean()) if len(late) else 0.0
            early = inner[inner >= 1] - 1
            mm = float(sm[early].mean()) if len(early) else 0.0
            best = max(m0, mp_, mm)
            if not len(inner):
                verdict = "dark"
            elif best - min(m0, mp_, mm) < STATIC:
                verdict = "static" if best >= SSIM_OK else "DIFFERENT"
            elif expect == 0:
                verdict = "ok" if m0 >= best - SHIFT_MARGIN else "SHIFTED"
            elif expect == 1:
                verdict = "draft-late" if mp_ >= best - SHIFT_MARGIN else "SHIFTED"
            elif expect is None:
                verdict = "resampled"
            else:
                verdict = "SHIFTED"
            if verdict in ("ok", "draft-late") and best < SSIM_OK:
                verdict = "DIFFERENT"
            if verdict == "resampled":
                # the frames in between can be one source frame apart (fast scrolling reads that as a low SSIM), but the
                # first frame is the in-point and must be the draft's, and the piece must still be the same shot
                first = keep[0] if len(keep) else lo
                if max(s0[first], sp[first] if first < len(sp) else 0) < RESAMPLED_FIRST or best < RESAMPLED_OK:
                    verdict = "DIFFERENT"
            if verdict == "ok":
                ends = [f for f in (lo, hi - 1) if not dark[f]]
                if ends and min(s0[f] for f in ends) < best - 0.25:
                    verdict = "EDGE"
            elif verdict == "draft-late":       # the draft's frame f is Resolve's f + 1; the last one belongs to the next piece
                ends = [f for f in (lo, hi - 2) if lo <= f < len(sp) and not dark[f]]
                if ends and min(sp[f] for f in ends) < best - 0.25:
                    verdict = "EDGE"
            # brightness and colour, frame by frame; a piece that is a frame or a source frame apart is compared with
            # the neighbouring frames too (a screen that flashes is otherwise read as a level error)
            def worst_diff(x, y):
                d = np.abs(x[lo:hi] - y[lo:hi])
                if verdict in ("draft-late", "resampled"):
                    for sh in (-1, 1):
                        a_, b_ = max(lo, lo - sh), min(hi, hi - sh)
                        dd = np.full(hi - lo, np.inf); dd[a_ - lo:b_ - lo] = np.abs(x[a_:b_] - y[a_ + sh:b_ + sh])
                        d = np.minimum(d, dd)
                return float(d.max())
            lvl = max(worst_diff(ya, yb), worst_diff(ua, ub), worst_diff(va, vb))
            if verdict not in ("SHIFTED", "DIFFERENT", "EDGE") and lvl > LEVEL_OK:
                verdict = "LEVEL"
            row = {"piece": i, "kind": p["kind"], "brick": p["brick"], "rec_f": lo, "n": hi - lo, "file": os.path.basename(p["file"]),
                   "ssim": round(m0, 4), "resolve_late": round(mp_, 4), "resolve_early": round(mm, 4),
                   "first": round(float(s0[lo]), 4), "last": round(float(s0[hi - 1]), 4), "max_level_diff": round(lvl, 2),
                   "draft_frames_late": expect, "verdict": verdict}
            prow.append(row)
            if verdict in ("SHIFTED", "DIFFERENT", "EDGE", "LEVEL"):
                fails.append(f"picture piece {i} ({p['kind']}{'' if p['brick'] is None else ' ' + str(p['brick'])}, {row['file']}) @ frame {lo}: "
                             f"{verdict} ssim {row['ssim']} late {row['resolve_late']} early {row['resolve_early']} first {row['first']} "
                             f"last {row['last']} level {row['max_level_diff']} (draft expected {expect} frame(s) late)")
                worst = int(keep[np.argmin(s0[keep])]) if len(keep) else lo
                sheets.append((row, worst))
        counts = {}
        for r in prow:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        late_f = sum(r["n"] for r in prow if r["verdict"] == "draft-late")
        report["checks"]["picture"] = {"pieces": len(prow), "verdicts": counts, "mean_ssim": round(float(s0[:n][~dark].mean()), 4),
                                       "draft_late_frames": late_f, "rows": prow}
        if late_f:
            report.setdefault("notes", []).append(
                f"{counts.get('draft-late', 0)} pieces ({late_f} frames) of the ffmpeg draft show the picture one frame after the sound: "
                "render_recipe.py prints its seek with 4 decimals, and a seek that rounds up past the frame drops it. Resolve plays the "
                "recipe's frame, so these pieces match the draft one frame along, exactly as predicted.")
        if counts.get("resampled"):
            report.setdefault("notes", []).append(
                f"{counts['resampled']} pieces play a clip at another rate (or speed) than the timeline's: ffmpeg rounds to the nearest "
                "source frame, Resolve takes the earlier one, so about half their frames are one SOURCE frame apart. The in-point and the length are the same.")
        for row, f in sheets[:a.sheets]:
            sp_ = out / "verify" / f"piece{row['piece']:03d}_{row['verdict'].lower()}_f{f}.jpg"
            sp_.parent.mkdir(exist_ok=True)
            sheet(ref, res, f, fps, sp_, row["verdict"])
            row["sheet"] = str(sp_)

        # ---- 3. sound
        ar, ag = mono(ref), mono(res)
        keeps = R.aroll_frames(rec)
        arow = []
        for i, k in enumerate(keeps):
            s, e = round(k["rec_f"] / fps * SR), round((k["rec_f"] + k["n"]) / fps * SR)
            pad = min(int(0.05 * SR), (e - s) // 8)
            x, y = ar[s + pad:e - pad], ag[s + pad:min(e - pad, len(ag))]
            m = min(len(x), len(y))
            if m < SR // 20:
                arow.append({"keep": i, "verdict": "short"}); continue
            x, y = x[:m], y[:m]
            lag, peak = lag_of(x, y, min(int(0.1 * SR), m // 2))
            lvl = 20 * np.log10((np.sqrt(np.mean(y ** 2)) + 1e-9) / (np.sqrt(np.mean(x ** 2)) + 1e-9))
            row = {"keep": i, "rec_f": k["rec_f"], "n": k["n"], "file": os.path.basename(R.keep_sound(rec, k)[0]),
                   "lag_ms": round(lag / SR * 1000, 3), "lag_samples": int(lag), "corr": round(peak, 3), "level_db": round(float(lvl), 2)}
            arow.append(row)
        lv = [r["level_db"] for r in arow if "level_db" in r]
        med = float(np.median(lv)) if lv else 0.0
        for r in arow:
            if "lag_ms" not in r:
                continue
            r["verdict"] = "ok"
            if r["corr"] < 0.5:
                r["verdict"] = "DIFFERENT"
            elif abs(r["lag_ms"]) > LAG_OK_MS:
                r["verdict"] = "LAG"
            elif abs(r["level_db"] - med) > LEVEL_DB_OK:
                r["verdict"] = "LEVEL"
            if r["verdict"] != "ok":
                fails.append(f"sound keep {r['keep']} ({r['file']}) @ frame {r['rec_f']}: {r['verdict']} lag {r['lag_ms']} ms, corr {r['corr']}, "
                             f"level {r['level_db']} dB (median {med:.2f})")
        report["checks"]["sound"] = {"keeps": len(arow), "median_level_db": round(med, 2),
                                     "max_abs_lag_ms": max((abs(r["lag_ms"]) for r in arow if "lag_ms" in r), default=None), "rows": arow}

    if not a.no_render and not a.resolve_render and not a.keep_render and res.exists():
        res.unlink()
    report["ok"] = not fails
    report["fails"] = fails
    C.write_json(out / "verify_report.json", report)
    brief = {k: ({kk: vv for kk, vv in v.items() if kk != "rows"}) for k, v in report["checks"].items()}
    print(json.dumps({"ok": report["ok"], "report": str(out / "verify_report.json"), **brief}))
    for f in fails:
        print("FAIL", f)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
