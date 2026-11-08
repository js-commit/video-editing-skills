#!/usr/bin/env python3
"""Turn a cut-flagged revision transcript into a TimeBolt / Video Haircut cut
list whose boundaries are snapped to the waveform.

Fixed padding around ASR word times clips word endings and keeps random breaths.
Instead, every boundary is placed by looking at the audio:

  * out-points (end of a kept span) move forward to where the speech tail has
    decayed below the noise floor, so word endings and room tone are not clipped;
  * in-points (start of a kept span) move back to just before the speech onset,
    leaving a short natural pre-roll;
  * searches never enter speech that was cut (retakes): they stop at the cut
    words' own timestamps;
  * a gap with no silence at all gets its cut on the lowest-energy dip;
  * a cut that snapping shrinks below --min-remove is dropped and the natural
    pause kept, unless the gap contains cut speech (dropping it would put the
    removed words' audio back);
  * no keep shorter than --min-keep: a sliver plays as a double jump cut, so it
    absorbs the shorter neighbouring removed pause when that is <= --max-absorb;
  * hard seams - a boundary still sitting on speech energy because the cut words
    touch the kept words ("and, uh, I": nothing quiet to land on) - are measured
    on the waveform: a removed span up to --max-absorb is restored (a stutter is
    less audible than a clipped word), a longer one may cross the cut word's ASR
    edge by 0.15 s to reach quiet, and anything left is reported as UNRESOLVED;
  * seam air is capped: at most ~0.25 s before the first voiced frame and ~0.30 s
    after the last one at every internal seam, measured from the voice rather
    than the word times (ASR often stretches a sentence's first word back over
    the pause). More than 2.5 s of air is left alone and reported.

Grouping: a cut happens where the gap between consecutive kept words is
>= --silence-thresh, or where the gap contains removed speech and is
>= --min-cut-gap.

Audio analysis: RMS envelope (20 ms window, 10 ms hop) of a 16 kHz mono 16-bit
WAV; noise floor = 5th percentile of the envelope in dB ("quiet" = floor +
--margin-db). A gated or denoised mic track (5th percentile under -75 dBFS,
digital silence between phrases) takes the 20th percentile instead, otherwise
every breath reads as sound. --floor-db sets the floor outright.

Standard library only (Python 3.9+); a 30-minute take analyses in seconds.

Usage:
  python3 smooth_cuts.py <revision.json> <media-file> -o <cuts.tb.json>
      [--wav audio_16k.wav]        # reuse an existing 16 kHz mono wav
      [--silence-thresh 0.6] [--min-cut-gap 0.4] [--min-remove 0.15]
      [--min-keep 1.0] [--max-absorb 1.5]
      [--margin-db 10] [--floor-db DB] [--max-extend 1.2]
      [--pause-min 1.5] [--no-motion] [--air-scale 1.0]

Writes <cuts.tb.json> and <cuts.tb.json>.decisions.json (every boundary
decision, long pauses, slivers, hard seams, tightened seams). Summary JSON on
stdout, logs on stderr.

Exit codes: 0 ok, 2 usage/input error.
"""
from __future__ import annotations

import argparse
import json
import math
import operator
import os
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402

HOP = 0.010             # s, envelope hop
WIN = 0.025             # s, envelope window (rounded to whole hops)
SUSTAIN = 0.08          # s of continuous quiet that counts as real silence
OUT_PAD = 0.05          # s kept after the detected speech-tail decay
IN_PAD = 0.12           # s of pre-roll before a detected onset
HEAD_PAD = 0.15         # s pre-roll before the very first word
TAIL_PAD = 0.35         # s of room after the very last word
GATED_DB = -75.0        # a 5th-percentile floor under this is a gated track's digital silence
VOICE_BELOW_P90 = 22.0  # dB under the take's loud speech (90th pct) that still counts as voice
VOICE_SUSTAIN = 0.04    # s of continuous voice that counts as the speech onset / end
MAX_HEAD = 0.25         # s of air allowed before a keep's first voiced frame (internal seams)
MAX_TAIL = 0.30         # s of air allowed after a keep's last voiced frame
HEAD_KEEP = 0.12        # s kept before the voice when trimming a head
TAIL_KEEP = 0.18        # s kept after the voice when trimming a tail (seam ~0.30 s)
MAX_AIR = 2.5           # s; more air than this at a seam is left alone and reported
GUARD = 0.06            # s clearance from cut-speech word timestamps
GUARD_PAUSE = 0.3       # s inside a keep's edges ignored when hunting pauses


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def log(msg):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- envelope

def block_energies(wav_path):
    """Sum of squared samples per 10 ms block (exact integers). Returns (rate, n_frames, hop_n, list)."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            die(f"{wav_path} must be mono 16-bit PCM")
        rate = wf.getframerate()
        n = wf.getnframes()
        hop_n = int(rate * HOP)
        block_sq = []
        mul = operator.mul
        remaining = n
        while remaining > 0:
            frames = wf.readframes(min(hop_n * 4000, remaining))
            if not frames:
                break
            remaining -= len(frames) // 2
            samples = array("h")
            samples.frombytes(frames)
            if sys.byteorder == "big":
                samples.byteswap()
            # a partial trailing block (< 10 ms) is dropped
            for off in range(0, len(samples) - len(samples) % hop_n, hop_n):
                block = samples[off:off + hop_n]
                block_sq.append(sum(map(mul, block, block)))
    return rate, n, hop_n, block_sq


class Envelope:
    def __init__(self, wav_path):
        self.rate, n, hop_n, block_sq = block_energies(wav_path)
        self.duration = n / self.rate
        win_n = int(self.rate * WIN)
        blocks_per_win = max(1, round(win_n / hop_n))
        env = []
        nb = len(block_sq)
        log10, sqrt = math.log10, math.sqrt
        for i in range(nb):
            j = min(nb, i + blocks_per_win)
            total = sum(block_sq[i:j])
            count = (j - i) * hop_n
            rms = sqrt(total / count) if count else 0.0
            env.append(20 * log10(rms / 32768.0 + 1e-9))
        self.db = env
        srt = sorted(env)
        self.noise_floor = srt[int(len(srt) * 0.05)] if env else -90.0
        self.gated = bool(env) and self.noise_floor < GATED_DB
        if self.gated:
            self.noise_floor = srt[int(len(srt) * 0.20)]

    def idx(self, t):
        return max(0, min(len(self.db) - 1, int(t / HOP)))

    def quiet_from(self, t, thr, sustain=SUSTAIN):
        """True if the envelope stays below thr for `sustain` seconds starting at t."""
        i0, i1 = self.idx(t), self.idx(t + sustain)
        return all(self.db[i] < thr for i in range(i0, i1 + 1))

    def first_quiet(self, t0, t1, thr):
        """Earliest t in [t0, t1] where quiet is sustained; None if none."""
        t = t0
        while t <= t1:
            if self.quiet_from(t, thr):
                return t
            t += HOP
        return None

    def last_quiet(self, t0, t1, thr):
        """Latest t in [t0, t1] where [t - sustain, t] is all quiet; None if none."""
        t = t1
        while t >= t0:
            i0, i1 = self.idx(t - SUSTAIN), self.idx(t)
            if all(self.db[i] < thr for i in range(i0, i1 + 1)):
                return t
            t -= HOP
        return None

    def min_dip(self, t0, t1):
        """Time of the lowest-energy point in [t0, t1]."""
        i0, i1 = self.idx(t0), self.idx(t1)
        best = min(range(i0, i1 + 1), key=lambda i: self.db[i])
        return best * HOP


# ---------------------------------------------------------------- grouping

def collect_words(revision):
    kept, cut = [], []
    for seg in revision["segments"]:
        for w in seg["words"]:
            if not w["word"].strip():
                continue
            (cut if w.get("cut") else kept).append(w)
    kept.sort(key=lambda w: w["start"])
    cut.sort(key=lambda w: w["start"])
    return kept, cut


def cut_speech_probe(cut):
    """f(a, b) -> cut-word (start, end) pairs overlapping the open span (a, b)."""
    cut_times = [(w["start"], w["end"]) for w in cut]

    def probe(a, b):
        return [(s, e) for s, e in cut_times if s < b and e > a]

    return probe


def build_groups(kept, cut, silence_thresh, min_cut_gap):
    """Group kept words into keep spans. `forced` marks a boundary whose gap holds
    cut speech: no later stage may collapse it (the cut words' audio would return)."""
    cut_speech_in = cut_speech_probe(cut)
    groups = []
    current = {"words": [kept[0]], "forced": False}
    for w in kept[1:]:
        gap = w["start"] - current["words"][-1]["end"]
        has_cut = bool(cut_speech_in(current["words"][-1]["end"], w["start"]))
        if gap >= silence_thresh or (has_cut and gap >= min_cut_gap):
            groups.append(current)
            current = {"words": [w], "forced": has_cut}
        else:
            current["words"].append(w)
    groups.append(current)
    return groups


# ---------------------------------------------------------------- snapping

def snap(env, groups, cut, args):
    thr = env.noise_floor + args.margin_db
    cut_speech_in = cut_speech_probe(cut)

    decisions = []
    spans = []

    for gi, grp in enumerate(groups):
        g = grp["words"]
        word_start, word_end = g[0]["start"], g[-1]["end"]

        # ---- in-point
        region_start = groups[gi - 1]["words"][-1]["end"] if gi > 0 else 0.0
        lo = max(region_start, word_start - args.max_extend)
        cuts_before = cut_speech_in(lo, word_start)
        if cuts_before:
            lo = max(lo, max(e for s, e in cuts_before) + GUARD)
        lo = min(lo, word_start)
        q = env.last_quiet(lo + SUSTAIN, word_start, thr)
        if q is not None:
            in_t = max(lo, q - IN_PAD if gi > 0 else q - HEAD_PAD)
            in_reason = "onset-silence"
        elif lo < word_start:
            in_t = env.min_dip(lo, word_start)
            in_reason = "min-dip"
        else:
            in_t = word_start
            in_reason = "no-room"
        in_t = min(in_t, word_start)

        # ---- out-point
        region_end = groups[gi + 1]["words"][0]["start"] if gi + 1 < len(groups) else env.duration
        hi = min(region_end - (GUARD if gi + 1 < len(groups) else 0),
                 word_end + (args.max_extend if gi + 1 < len(groups) else args.max_extend + 0.5))
        cuts_after = cut_speech_in(word_end, hi)
        if cuts_after:
            hi = min(hi, min(s for s, e in cuts_after) - GUARD)
        hi = max(hi, word_end)
        q = env.first_quiet(word_end, hi, thr)
        if q is not None:
            out_t = min(hi, q + (OUT_PAD if gi + 1 < len(groups) else TAIL_PAD))
            out_reason = "tail-decay"
        elif hi > word_end:
            out_t = env.min_dip(word_end, hi)
            out_reason = "min-dip"
        else:
            out_t = word_end
            out_reason = "no-room"
        out_t = max(out_t, word_end)

        spans.append({"in": in_t, "out": out_t, "words": g, "forced": grp["forced"]})
        decisions.append({
            "group": gi,
            "text_start": g[0]["word"], "text_end": g[-1]["word"],
            "word_in": round(word_start, 3), "snapped_in": round(in_t, 3), "in_reason": in_reason,
            "word_out": round(word_end, 3), "snapped_out": round(out_t, 3), "out_reason": out_reason,
        })

    # merge keeps whose separating cut collapsed below --min-remove, never across
    # a forced boundary (its gap holds cut speech)
    merged = [spans[0]]
    dropped = 0
    for s in spans[1:]:
        prev = merged[-1]
        if not s["forced"] and s["in"] - prev["out"] < args.min_remove:
            prev["out"] = s["out"]
            prev["words"] = prev["words"] + s["words"]
            dropped += 1
        else:
            merged.append(s)

    # no slivers: a keep shorter than --min-keep reads as a flicker (double jump
    # cut). It absorbs the SHORTER neighbouring removed pause, restoring source
    # continuity, when that pause is <= --max-absorb and not forced. A sliver
    # boxed in by long or forced pauses is kept and reported.
    slivers = []
    if getattr(args, "min_keep", 0) > 0:
        i = 0
        while i < len(merged):
            s = merged[i]
            if s["out"] - s["in"] >= args.min_keep:
                i += 1
                continue
            prev = merged[i - 1] if i > 0 else None
            nxt = merged[i + 1] if i + 1 < len(merged) else None
            options = []
            if prev is not None and not s["forced"]:
                options.append((s["in"] - prev["out"], "prev"))
            if nxt is not None and not nxt["forced"]:
                options.append((nxt["in"] - s["out"], "next"))
            options = [o for o in options if o[0] <= args.max_absorb]
            text = " ".join(w["word"].strip() for w in s["words"])[:60]
            if not options:
                slivers.append({"in": round(s["in"], 3), "out": round(s["out"], 3), "text": text,
                                "why": "boxed in by long or forced pauses; review by hand"})
                i += 1
                continue
            gap, side = min(options)
            if side == "prev":
                prev["out"] = s["out"]
                prev["words"] = prev["words"] + s["words"]
                merged.pop(i)
                i = max(i - 1, 0)          # re-check the merged span
            else:
                s["out"] = nxt["out"]
                s["words"] = s["words"] + nxt["words"]
                merged.pop(i + 1)          # boundary before s unchanged; re-check s
            slivers.append({"in": round(s["in"], 3), "out": round(s["out"], 3), "absorbed_s": round(gap, 3),
                            "side": side, "text": text, "why": "sliver merged by restoring the removed pause"})
    args._slivers = slivers

    # hard seams: a boundary on speech energy. Word-time checks miss these (the
    # boundary sits between the ASR words but inside the audio of a glued
    # filler), so they are measured on the waveform:
    #   * removed span <= --max-absorb -> restore it, even across a forced boundary;
    #   * else the loud edge may cross the cut word's ASR edge by <= 0.15 s if that
    #     reaches sustained quiet (ASR times are about that imprecise);
    #   * whatever is still loud is reported as UNRESOLVED for a human.
    hard = []
    if getattr(args, "max_absorb", 0) > 0 and len(merged) > 1:
        hard_db = env.noise_floor + args.margin_db + 7
        cut_words = sorted((w["start"], w["end"]) for w in cut)
        i = 1
        while i < len(merged):
            prev, s = merged[i - 1], merged[i]
            out_db, in_db = env.db[env.idx(prev["out"] - 0.02)], env.db[env.idx(s["in"])]
            if out_db < hard_db and in_db < hard_db:
                i += 1
                continue
            removed = s["in"] - prev["out"]
            if removed <= args.max_absorb:
                prev["out"] = s["out"]
                prev["words"] = prev["words"] + s["words"]
                merged.pop(i)
                hard.append({"t": round(s["in"], 3), "out_db": round(out_db, 1), "in_db": round(in_db, 1),
                             "removed_s": round(removed, 3), "fix": "restored"})
                continue
            fixed = []
            if out_db >= hard_db:
                nxt = next((ws for ws, we in cut_words if ws > prev["out"] - 0.05), s["in"])
                q = env.first_quiet(prev["out"], min(nxt + 0.15, s["in"]), thr)
                if q is not None:
                    prev["out"] = min(q + OUT_PAD, s["in"])
                    fixed.append("out")
            if in_db >= hard_db:
                prv = next((we for ws, we in reversed(cut_words) if we < s["in"] + 0.05), prev["out"])
                q = env.last_quiet(max(prv - 0.15, prev["out"]) + SUSTAIN, s["in"], thr)
                if q is not None:
                    s["in"] = max(q - IN_PAD, prev["out"])
                    fixed.append("in")
            hard.append({"t": round(s["in"], 3), "out_db": round(out_db, 1), "in_db": round(in_db, 1),
                         "removed_s": round(removed, 3),
                         "fix": ("re-snapped " + "+".join(fixed)) if fixed
                         else "UNRESOLVED: cut lands on a word; review by hand"})
            i += 1
    args._hard = hard
    args._tightened = tighten_seams(env, merged, thr)

    return merged, decisions, dropped, thr


def tighten_seams(env, spans, thr):
    """Cap the dead air on each side of every internal seam, measured from the voice.

    Two things leave long gaps that the snapper above cannot see: on a gated mic
    track the "quiet" threshold sits so low that the inhale before a sentence
    reads as sound, and ASR often stretches a sentence's first word back over the
    pause before it. Voice = within VOICE_BELOW_P90 dB of the take's loud speech
    (its 90th percentile), never below the quiet threshold. A keep whose first
    voiced frame (sustained VOICE_SUSTAIN) sits more than MAX_HEAD after its
    in-point starts HEAD_KEEP before it; one whose last voiced frame sits more than
    MAX_TAIL before its out-point ends TAIL_KEEP after it. The search never passes
    the first word's end / the last word's start, so a keep can only lose air, and
    more than MAX_AIR is left for a human (dead air and a silent demo look alike)."""
    srt = sorted(env.db)
    voice = max(thr, srt[int(len(srt) * 0.90)] - VOICE_BELOW_P90)
    n = max(1, round(VOICE_SUSTAIN / HOP))
    db = env.db
    last = len(db) - 1

    def voiced(i):
        return all(db[min(last, i + k)] >= voice for k in range(n))

    out = []
    for si, s in enumerate(spans):
        if si > 0:
            i, lim = env.idx(s["in"]), env.idx(max(s["words"][0]["end"], s["in"]))
            while i <= lim and not voiced(i):
                i += 1
            onset = i * HOP
            if i <= lim and MAX_HEAD < onset - s["in"] <= MAX_AIR:
                out.append({"group": si, "side": "in", "from": round(s["in"], 3), "to": round(onset - HEAD_KEEP, 3),
                            "air_s": round(onset - s["in"], 3)})
                s["in"] = onset - HEAD_KEEP
        if si + 1 < len(spans):
            i, lim = env.idx(s["out"]) - n, env.idx(min(s["words"][-1]["start"], s["out"]))
            while i >= lim and not voiced(i):
                i -= 1
            end = (i + n) * HOP
            if i >= lim and MAX_TAIL < s["out"] - end <= MAX_AIR:
                out.append({"group": si, "side": "out", "from": round(s["out"], 3), "to": round(end + TAIL_KEEP, 3),
                            "air_s": round(s["out"] - end, 3)})
                s["out"] = end + TAIL_KEEP
    return {"voice_db": round(voice, 1), "edges": out}


def find_long_pauses(env, spans, thr, min_len):
    """Quiet runs >= min_len inside final keeps. Report-only: neither audio nor
    motion reliably separates dead air from a silent product shot."""
    pauses = []
    for si, s in enumerate(spans):
        i0, i1 = env.idx(s["in"] + GUARD_PAUSE), env.idx(s["out"] - GUARD_PAUSE)
        start = None
        for i in range(i0, i1 + 1):
            if env.db[i] < thr:
                if start is None:
                    start = i
            else:
                if start is not None and (i - start) * HOP >= min_len:
                    pauses.append({"group": si, "start": round(start * HOP, 2),
                                   "end": round(i * HOP, 2),
                                   "duration": round((i - start) * HOP, 2)})
                start = None
        if start is not None and (i1 + 1 - start) * HOP >= min_len:
            pauses.append({"group": si, "start": round(start * HOP, 2),
                           "end": round((i1 + 1) * HOP, 2),
                           "duration": round((i1 + 1 - start) * HOP, 2)})
    return pauses


def motion_scores(media_path, env, spans, pauses):
    """Inter-frame motion of each pause relative to this video's motion during its
    loudest speech. Under ~0.35x reads as static, over 1x as clearly moving; in
    between is a guess, which is why this only annotates."""
    ffmpeg = media.ffmpeg()

    def score(t0, t1):
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
               "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", media_path,
               "-vf", "fps=6,scale=160:90,format=gray", "-f", "rawvideo", "-"]
        try:
            raw = media.run(cmd, capture_output=True, timeout=60).stdout
        except (subprocess.SubprocessError, OSError):
            return None
        n = len(raw) // (160 * 90)
        if n < 2:
            return None
        frames = [array("B", raw[k * 160 * 90:(k + 1) * 160 * 90]) for k in range(n)]
        acc = 0
        for a, b in zip(frames, frames[1:]):
            acc += sum(abs(x - y) for x, y in zip(a, b)) / len(a)
        return acc / (n - 1)

    # speech baseline: the six loudest non-overlapping 2 s windows inside keeps
    step = int(2.0 / HOP)
    windows = []
    for s in spans:
        i0, i1 = env.idx(s["in"]), env.idx(s["out"]) - step
        for i in range(i0, i1, step):
            windows.append((sum(env.db[i:i + step]) / step, i * HOP))
    windows.sort(reverse=True)
    picked = []
    for _, t in windows:
        if all(abs(t - p) > 30 for p in picked):
            picked.append(t)
        if len(picked) == 6:
            break
    base = [m for t in picked for m in [score(t, t + 2.0)] if m is not None]
    if not base:
        return
    base.sort()
    base_med = base[len(base) // 2]
    for p in pauses:
        m = score(p["start"], p["end"])
        p["motion_x_speech"] = round(m / base_med, 2) if (m is not None and base_med > 0) else None


def word_crossings(spans, kept, cut, eps=1e-3):
    """Boundaries that land strictly inside a word's timestamps (bleed or clip).
    Expected 0; anything else is worth locating."""
    words = sorted([(w["start"], w["end"], w["word"]) for w in kept + cut])
    hits = []
    for si, s in enumerate(spans):
        for b, side in ((s["in"], "in"), (s["out"], "out")):
            for ws, we, txt in words:
                if ws + eps < b < we - eps:
                    hits.append({"group": si, "side": side, "t": round(b, 3),
                                 "word": txt, "word_span": [round(ws, 3), round(we, 3)]})
                    break
                if ws > b:
                    break
    return hits


# ---------------------------------------------------------------- output

def make_ops(spans):
    """TimeBolt / Video Haircut op list: contiguous keep/remove ops from 0."""
    ops = []
    cursor = 0.0

    def add(op, start, end, txt=None):
        entry = {"start": round(start, 6), "duration": round(end - start, 6),
                 "type": "original", "punched": 1, "punchedPosition": "center",
                 "operation": op, "id": len(ops)}
        if txt is not None:
            entry["txt"] = txt
        ops.append(entry)

    for s in spans:
        if s["in"] > cursor + 1e-6:
            add("remove", cursor, s["in"])
        txt = " ".join(w["word"].strip() for w in s["words"])
        add("keep", s["in"], s["out"], txt)
        cursor = s["out"]
    return ops


def extract_wav(media_path, rate=16000):
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    media.run([media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
               "-i", media_path, "-vn", "-ac", "1", "-ar", str(rate),
               "-c:a", "pcm_s16le", tmp.name], check=True)
    return tmp.name


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("revision")
    p.add_argument("media")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--wav", help="existing 16 kHz mono 16-bit wav of the media (skips extraction)")
    p.add_argument("--silence-thresh", type=float, default=0.6,
                   help="a gap between kept words this long (s) always becomes a cut")
    p.add_argument("--min-cut-gap", type=float, default=0.4,
                   help="a gap holding removed words this long (s) becomes a cut")
    p.add_argument("--min-remove", type=float, default=0.15,
                   help="cuts that snap smaller than this (s) are dropped, keeping the pause")
    p.add_argument("--min-keep", type=float, default=1.0,
                   help="no kept span shorter than this (s); a sliver absorbs the shorter adjacent pause (0 = off)")
    p.add_argument("--max-absorb", type=float, default=1.5,
                   help="longest removed span (s) a sliver or hard seam may restore")
    p.add_argument("--margin-db", type=float, default=10.0,
                   help="quiet = noise floor + this many dB")
    p.add_argument("--floor-db", type=float,
                   help="noise floor in dBFS, overriding the measured one")
    p.add_argument("--max-extend", type=float, default=1.2,
                   help="how far (s) a boundary may move to find silence")
    p.add_argument("--pause-min", type=float, default=1.5,
                   help="report quiet runs inside keeps at least this long (s; 0 disables)")
    p.add_argument("--no-motion", action="store_true",
                   help="skip per-pause motion scoring (no video decode)")
    p.add_argument("--air-scale", type=float, default=1.0,
                   help="scale the air kept at every seam (pre-roll, tail, seam caps): 0.7 = tighter, "
                        "1.5 = more breathing room (default 1.0, a heard gap of ~0.3 s)")
    args = p.parse_args()
    if args.air_scale <= 0:
        die("--air-scale must be > 0")
    if args.air_scale != 1.0:
        global OUT_PAD, IN_PAD, MAX_HEAD, MAX_TAIL, HEAD_KEEP, TAIL_KEEP
        OUT_PAD, IN_PAD = OUT_PAD * args.air_scale, IN_PAD * args.air_scale
        MAX_HEAD, MAX_TAIL = MAX_HEAD * args.air_scale, MAX_TAIL * args.air_scale
        HEAD_KEEP, TAIL_KEEP = HEAD_KEEP * args.air_scale, TAIL_KEEP * args.air_scale

    with open(args.revision, encoding="utf-8") as f:
        revision = json.load(f)
    kept, cut = collect_words(revision)
    if not kept:
        die("no kept words in revision")

    wav = args.wav
    cleanup = None
    if not wav:
        log("extracting 16 kHz mono wav for analysis...")
        wav = cleanup = extract_wav(args.media)
    try:
        log("computing RMS envelope...")
        env = Envelope(wav)
        if args.floor_db is not None:
            env.noise_floor, env.gated = args.floor_db, False
        elif env.gated:
            log("gated track (digital silence between phrases): floor from the 20th percentile")
        log(f"noise floor: {env.noise_floor:.1f} dBFS; "
            f"quiet threshold: {env.noise_floor + args.margin_db:.1f} dBFS")

        groups = build_groups(kept, cut, args.silence_thresh, args.min_cut_gap)
        spans, decisions, dropped, thr = snap(env, groups, cut, args)
        ops = make_ops(spans)
        crossings = word_crossings(spans, kept, cut)
        # a hard-seam re-snap may sit up to 0.15 s inside a cut word's ASR span on purpose
        resnapped = {h["t"] for h in args._hard if h["fix"].startswith("re-snapped")}
        if resnapped:
            crossings = [c for c in crossings
                         if not (min(abs(c["t"] - t) for t in resnapped) < 0.5
                                 and min(c["t"] - c["word_span"][0], c["word_span"][1] - c["t"]) <= 0.16)]
        # a tightened edge sits inside a stretched word's ASR span on purpose
        tight = {e["to"] for e in args._tightened.get("edges", [])}
        crossings = [c for c in crossings if not any(abs(c["t"] - t) < 1e-3 for t in tight)]
        for h in args._hard:
            if h["fix"].startswith("UNRESOLVED"):
                log(f"WARNING: hard seam at {h['t']}s (out {h['out_db']} dB / in {h['in_db']} dB, "
                    f"{h['removed_s']}s removed) - {h['fix']}")
        for h in crossings:
            log(f"WARNING: boundary lands inside word {h['word']!r} "
                f"({h['side']} of group {h['group']} at {h['t']}s, "
                f"word span {h['word_span'][0]}-{h['word_span'][1]})")

        pauses = find_long_pauses(env, spans, thr, args.pause_min) if args.pause_min > 0 else []
        if pauses and not args.no_motion:
            log(f"scoring motion for {len(pauses)} long pauses...")
            motion_scores(args.media, env, spans, pauses)
        for pz in pauses:
            log(f"long pause: {pz['duration']}s at {pz['start']}s"
                + (f" (motion {pz['motion_x_speech']}x speech)"
                   if pz.get("motion_x_speech") is not None else ""))

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(ops, f, indent=2, ensure_ascii=False)
        with open(args.output + ".decisions.json", "w", encoding="utf-8") as f:
            json.dump({"noise_floor_db": round(env.noise_floor, 1),
                       "quiet_thr_db": round(thr, 1),
                       "word_crossings": crossings,
                       "long_pauses": pauses,
                       "slivers": args._slivers,
                       "hard_seams": args._hard,
                       "tightened": args._tightened,
                       "boundaries": decisions}, f, indent=2, ensure_ascii=False)

        keep_dur = sum(o["duration"] for o in ops if o["operation"] == "keep")
        fallbacks = sum(1 for d in decisions if "min-dip" in (d["in_reason"], d["out_reason"]))
        print(json.dumps({
            "output": args.output,
            "keeps": sum(1 for o in ops if o["operation"] == "keep"),
            "removes": sum(1 for o in ops if o["operation"] == "remove"),
            "kept_duration_s": round(keep_dur, 2),
            "cuts_dropped_as_too_small": dropped,
            "dip_fallback_boundaries": fallbacks,
            "word_crossing_boundaries": len(crossings),
            "long_pauses": len(pauses),
            "slivers_merged": sum(1 for x in args._slivers if "absorbed_s" in x),
            "slivers_left": sum(1 for x in args._slivers if "absorbed_s" not in x),
            "hard_seams_restored": sum(1 for x in args._hard if x["fix"] == "restored"),
            "hard_seams_resnapped": sum(1 for x in args._hard if x["fix"].startswith("re-snapped")),
            "hard_seams_unresolved": sum(1 for x in args._hard if x["fix"].startswith("UNRESOLVED")),
            "seam_edges_tightened": len(args._tightened.get("edges", [])),
        }))
    finally:
        if cleanup:
            os.unlink(cleanup)


if __name__ == "__main__":
    main()
