#!/usr/bin/env python3
"""Speech-seam audit of a LIVE Resolve a-roll timeline, measured on the audio
the audience actually hears, plus the repair plan for ripple_extend.py --plan.

Why: a silence-cut edit snaps cuts to pauses, but when a removed filler word
touches a kept word ("and, uh, I" -> "and | I") there is no pause to snap to
and the cut lands inside the kept word. Transcript timestamps cannot see that;
the waveform can. This audit reads the loudness envelope at every seam.

A seam = two consecutive items of the same source on --audio-track whose
source ranges are not continuous. Per seam:
  out_db / in_db   loudness in the last / first 20 ms of the kept audio
  gap              quiet already heard across the seam (seconds)
  hard             out_db or in_db >= floor + --hard-db (a word is cut into)
  abrupt           gap < 0.10 s

Plan (--plan): per seam, how many source frames to restore on each side so
that (a) no boundary sits on speech and (b) the heard pause reaches
--target-gap, using quiet material only:
  * a loud boundary walks into the removed span until sustained quiet, but
    never more than --tolerance past the transcript edge of the removed words;
  * if that fails and the removed span is <= --max-restore, the whole span is
    restored (a small stutter beats a clipped word);
  * a longer span that still cannot be made clean is left alone and FLAGGED
    for a human decision (usually a broken sentence, not a snapping problem);
  * a kept a-roll item shorter than --min-keep (a sliver: two jump cuts in a
    blink) restores its shorter neighbouring removed span if <= --max-restore.

Usage:
  seam_audit.py --project P --timeline T [--audio-track 1] [--aroll-track 1]
        [--wav heard_16k.wav] [--transcript sidecar.json --transcript-offset 0.0]
        [--target-gap 0.30] [--plan plan.json] [-o report.json]

--wav: 16-bit mono PCM of the HEARD source file (extracted with ffmpeg when
absent). --transcript: word-level sidecar (<stem>.transcript.json; found next
to the source automatically). --transcript-offset: seconds to SUBTRACT from its
timestamps to land on the heard file's clock (a second camera that started
recording later has a positive offset).

Pure Python (no numpy). Exit 0 always: the counts are the gate (hard == 0,
flagged ones listed for the user).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import wave
from array import array
from collections import Counter
from operator import mul

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _brick as B  # noqa: E402

HOP, WIN, SUSTAIN = 0.010, 0.025, 0.08


def percentile(vals, q):
    """Linear-interpolated percentile (numpy's default), q in 0..100."""
    s = sorted(vals)
    if not s:
        return 0.0
    pos = (len(s) - 1) * q / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def envelope_db(samples, sr):
    """RMS envelope in dBFS: WIN-long windows every HOP seconds.

    Sums of squares are taken per block of gcd(hop, win) samples (C-speed
    sum(map(mul))), then windows are added from block prefix sums, which gives
    exactly the per-window RMS without numpy."""
    hop, win = int(HOP * sr), int(WIN * sr)
    blk = math.gcd(hop, win)
    nb = len(samples) // blk
    prefix = [0]
    acc = 0
    for i in range(nb):
        s = samples[i * blk:(i + 1) * blk]
        acc += sum(map(mul, s, s))
        prefix.append(acc)
    n = max(1, (len(samples) - win) // hop)
    hb, wb = hop // blk, win // blk
    norm = float(win) * 32768.0 * 32768.0
    out = []
    for k in range(n):
        a = k * hb
        b = min(a + wb, nb)
        e = (prefix[b] - prefix[min(a, nb)]) / norm if b > a else 0.0
        out.append(20.0 * math.log10(math.sqrt(max(e, 0.0)) + 1e-9))
    return out


class Env:
    """Loudness envelope with the quiet-run queries the planner needs."""

    def __init__(self, db):
        self.db = list(db) or [-180.0]
        self.n = len(self.db)
        self.floor = float(percentile(self.db, 5))

    @classmethod
    def from_wav(cls, path):
        wf = wave.open(path)
        sr = wf.getframerate()
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            sys.exit(f"{path} must be 16-bit mono PCM")
        a = array("h")
        a.frombytes(wf.readframes(wf.getnframes()))
        if sys.byteorder == "big":
            a.byteswap()
        return cls(envelope_db(a, sr))

    def at(self, t):
        return float(self.db[min(max(int(t / HOP), 0), self.n - 1)])

    def quiet(self, t, thr):
        return self.at(t) < thr

    def quiet_sustained(self, t, thr, sus=SUSTAIN):
        return all(self.quiet(t + k * HOP, thr) for k in range(int(sus / HOP) + 1))

    def quiet_sustained_before(self, t, thr, sus=SUSTAIN):
        return all(self.quiet(t - k * HOP, thr) for k in range(1, int(sus / HOP) + 2))

    def quiet_run_after(self, t, lim, thr):
        r = 0.0
        while t + r < lim and self.quiet(t + r, thr):
            r += HOP
        return r

    def quiet_run_before(self, t, lim, thr):
        r = 0.0
        while t - r > lim and self.quiet(t - r - HOP, thr):
            r += HOP
        return r


def extract_wav(source, out):
    subprocess.run([B.media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", source, "-vn",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out], check=True)
    return out


def merge_continuous(items):
    """Butt-cut pieces of one continuous source are one item to the ear."""
    out = []
    for it in items:
        p = out[-1] if out else None
        if p and p["media"] == it["media"] and p["end"] == it["start"] \
                and p["left"] + (p["end"] - p["start"]) == it["left"]:
            p["end"] = it["end"]
        else:
            out.append(dict(it))
    return out


def audit(items, aroll_items, env, fps, words, a):
    """items: heard-audio items {start, end, left, media} (timeline frames from
    the timeline start; left = source in-point in timeline frames), sorted.
    aroll_items: a-roll video items for the sliver rule. words: sorted
    (start, end) seconds on the source clock. Returns the seam list."""
    thr = env.floor + a.margin_db
    hard_db = env.floor + a.hard_db
    wstart = [w[0] for w in words] if words else None
    wend = [w[1] for w in words] if words else None
    seams = []
    for p, nx in zip(items, items[1:]):
        if p["media"] != nx["media"]:
            continue
        pdur = p["end"] - p["start"]
        g = nx["left"] - (p["left"] + pdur)
        if g <= 0:
            continue
        out = (p["left"] + pdur) / fps
        inn = nx["left"] / fps
        removed = g / fps
        out_db, in_db = env.at(out - 0.02), env.at(inn)
        qb = env.quiet_run_before(out, out - pdur / fps, thr)
        qa = env.quiet_run_after(inn, inn + (nx["end"] - nx["start"]) / fps, thr)
        gap = qb + qa
        s = {"F": nx["start"], "tc": B.tc(nx["start"], fps), "g": g, "removed_s": round(removed, 2),
             "out_db": round(out_db, 1), "in_db": round(in_db, 1), "gap": round(gap, 2),
             "hard": bool(out_db >= hard_db or in_db >= hard_db), "abrupt": bool(gap < 0.10),
             "tail_f": 0, "head_f": 0, "kind": "none", "flag": False}
        # tail walk: only when the out point sits on energy
        tail, tail_ok = 0.0, True
        if out_db >= thr:
            lim = min(out + a.max_ext, inn)
            if wstart is not None:  # first removed word's start + tolerance
                nxt = [w for w in wstart if out - 0.05 < w < inn]
                if nxt:
                    lim = min(lim, nxt[0] + a.tolerance)
            t = out
            while t < lim and not env.quiet_sustained(t, thr):
                t += HOP
            tail_ok = t < lim or env.quiet_sustained(t, thr)
            tail = t - out if tail_ok else 0.0
        head, head_ok = 0.0, True
        if in_db >= thr:
            lim = max(inn - a.max_ext, out)
            if wend is not None:  # last removed word's end - tolerance
                prv = [w for w in wend if out < w < inn + 0.05]
                if prv:
                    lim = max(lim, prv[-1] - a.tolerance)
            t = inn
            while t > lim and not env.quiet_sustained_before(t, thr):
                t -= HOP
            head_ok = t > lim or env.quiet_sustained_before(t, thr)
            head = inn - t if head_ok else 0.0
        if not (tail_ok and head_ok):
            if removed <= a.max_restore:
                s.update(kind="restore", tail_f=g, head_f=0)
                seams.append(s)
                continue
            # the loud side stays (extending would replay removed speech); a
            # human decision only when it is a real clipped word
            s["flag"] = bool((not tail_ok and out_db >= hard_db) or (not head_ok and in_db >= hard_db))
        # quiet padding towards the target heard pause
        need = max(0.0, a.target_gap - gap)
        if need > 0 or tail > 0 or head > 0:
            avail_t = env.quiet_run_after(out + tail, inn - head, thr)
            avail_h = env.quiet_run_before(inn - head, out + tail, thr)
            want_t = need / 2 + (a.out_pad if tail > 0 else 0.0)
            want_h = need / 2 + (a.in_pad if head > 0 else 0.0)
            tail += min(avail_t, want_t)
            head += min(avail_h, want_h)
        tf, hf = int(round(tail * fps)), int(round(head * fps))
        if tf + hf >= g - 2:
            tf, hf = g, 0
            s["kind"] = "restore" if removed <= a.max_restore else "restore-long"
        elif tf or hf:
            s["kind"] = "partial"
        if tf + hf > g:
            hf = g - tf
        s.update(tail_f=tf, head_f=hf)
        seams.append(s)
    # slivers on the a-roll track: restore the shorter neighbouring removed span
    by_f = {s["F"]: s for s in seams}
    min_keep_f = int(round(a.min_keep * fps))
    for i in range(1, len(aroll_items) - 1):
        it = aroll_items[i]
        n = it["end"] - it["start"]
        if n >= min_keep_f:
            continue
        before, after = by_f.get(it["start"]), by_f.get(it["end"])
        opts = [(x["g"], x) for x in (before, after) if x and x["g"] <= a.max_restore * fps]
        if not opts:
            for x in (before, after):
                if x:
                    x["sliver"] = "boxed in (no neighbouring span <= max-restore)"
            continue
        _, x = min(opts, key=lambda o: o[0])
        if x["kind"] != "restore":
            x.update(kind="restore", tail_f=x["g"], head_f=0, flag=False)
            x["sliver"] = f"restored for the {n}-frame sliver at {B.tc(it['start'], fps)}"
    return seams


def report(seams, fps, floor, meta):
    hard = [s for s in seams if s["hard"]]
    abrupt = [s for s in seams if s["abrupt"] and not s["hard"]]
    flagged = [s for s in seams if s["flag"]]
    rep = dict(meta, floor_db=round(floor, 1), seams=len(seams), hard=len(hard), abrupt=len(abrupt),
               flagged=len(flagged), plan_kinds=dict(Counter(s["kind"] for s in seams)),
               added_frames=sum(s["tail_f"] + s["head_f"] for s in seams), items=seams)
    return rep, hard, abrupt, flagged


def plan_entries(seams):
    return [{"F": s["F"], "tc": s["tc"], "tail_f": s["tail_f"], "head_f": s["head_f"], "kind": s["kind"],
             "flag": s["flag"]} for s in seams if s["tail_f"] or s["head_f"]]


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="Resolve project name")
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--audio-track", type=int, default=1, help="the HEARD (unmuted) audio track")
    ap.add_argument("--aroll-track", type=int, default=1, help="a-roll video track for the sliver rule")
    ap.add_argument("--wav", default=None, help="16-bit mono WAV of the heard source (default: extracted)")
    ap.add_argument("--transcript", default=None, help="word-level transcript sidecar of the heard source")
    ap.add_argument("--transcript-offset", type=float, default=0.0)
    ap.add_argument("--margin-db", type=float, default=10.0, help="quiet = noise floor + this")
    ap.add_argument("--hard-db", type=float, default=17.0, help="hard seam = boundary loudness >= floor + this")
    ap.add_argument("--target-gap", type=float, default=0.30, help="heard pause to aim for at every seam (s)")
    ap.add_argument("--max-restore", type=float, default=1.5, help="longest removed span restored whole (s)")
    ap.add_argument("--max-ext", type=float, default=1.0)
    ap.add_argument("--tolerance", type=float, default=0.15)
    ap.add_argument("--out-pad", type=float, default=0.05)
    ap.add_argument("--in-pad", type=float, default=0.12)
    ap.add_argument("--min-keep", type=float, default=1.0, help="a-roll items shorter than this are slivers (s)")
    ap.add_argument("--plan", default=None, help="write the ripple_extend.py --plan JSON here")
    ap.add_argument("-o", "--out", default=None, help="write the full report JSON here")
    return ap


def main():
    a = build_parser().parse_args()
    B.refuse_protected(a.timeline)  # read-only, but a backup is never the cut being audited
    _, proj = B.open_project(a.project)
    tl = B.timeline_by_name(proj, a.timeline)
    fps = B.fps_of(tl)
    t0 = tl.GetStartFrame()

    def dump(kind, idx):
        out = []
        for it in tl.GetItemListInTrack(kind, idx) or []:
            mpi = it.GetMediaPoolItem()
            out.append({"start": it.GetStart() - t0, "end": it.GetEnd() - t0, "left": it.GetLeftOffset(),
                        "media": (mpi.GetClipProperty("File Path") if mpi else it.GetName())})
        return sorted(out, key=lambda i: i["start"])

    items = merge_continuous(dump("audio", a.audio_track))
    aroll = merge_continuous(dump("video", a.aroll_track))
    if not items:
        sys.exit(f"audio track A{a.audio_track} is empty on {a.timeline!r}")
    medias = {i["media"] for i in items}
    main_media = max(medias, key=lambda m: sum(i["end"] - i["start"] for i in items if i["media"] == m))
    items = [i for i in items if i["media"] == main_media]  # inserts from other takes get their own run
    wav = a.wav
    if not wav:
        out_dir = os.path.dirname(os.path.abspath(a.out or a.plan)) if (a.out or a.plan) else B.work_dir(a.project, "seams")
        wav = os.path.join(out_dir, os.path.splitext(os.path.basename(main_media))[0] + ".16k.wav")
        if not os.path.exists(wav):
            B.log(f"extracting the heard audio -> {wav}")
            extract_wav(main_media, wav)
    env = Env.from_wav(wav)
    words = []
    tpath = a.transcript
    if not tpath:
        cand = os.path.splitext(main_media)[0] + ".transcript.json"
        if os.path.exists(cand):
            tpath = cand
        else:
            try:  # read-only media folders keep the sidecar in the cache
                from vidkit.transcript import find_sidecar
                found = find_sidecar(main_media)
                tpath = str(found) if found else None
            except Exception:
                pass
    if tpath:
        with open(tpath, encoding="utf-8") as f:
            d = json.load(f)
        words = sorted((w["start"] - a.transcript_offset, w["end"] - a.transcript_offset)
                       for s in d.get("segments", []) for w in s.get("words", [])
                       if w.get("start") is not None and w.get("end") is not None)
    seams = audit(items, aroll, env, fps, words, a)
    rep, hard, abrupt, flagged = report(seams, fps, env.floor, {"timeline": a.timeline, "fps": fps,
                                                                "heard_media": main_media, "wav": wav})
    for s in hard + abrupt:
        B.log(f"{s['tc']}  {'HARD  ' if s['hard'] else 'ABRUPT'} out {s['out_db']:6.1f} in {s['in_db']:6.1f} "
              f"gap {s['gap']:.2f} removed {s['removed_s']:5.2f}s -> {s['kind']} +{s['tail_f']}/{s['head_f']}f"
              f"{'  FLAG' if s['flag'] else ''}")
    B.log(f"{len(seams)} seams: {len(hard)} hard, {len(abrupt)} abrupt, {len(flagged)} flagged; plan "
          f"{rep['plan_kinds']} adds {rep['added_frames']} frames ({rep['added_frames'] / fps:.1f}s); "
          f"floor {env.floor:.1f} dB")
    if a.out:
        with open(a.out, "w") as f:
            json.dump(rep, f, indent=1)
    if a.plan:
        with open(a.plan, "w") as f:
            json.dump(plan_entries(seams), f, indent=1)
    print(json.dumps({k: rep[k] for k in ("seams", "hard", "abrupt", "flagged", "plan_kinds", "added_frames")}))


if __name__ == "__main__":
    main()
