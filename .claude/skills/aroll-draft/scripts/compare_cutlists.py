#!/usr/bin/env python3
"""Score an automatic first cut against another cut of the same take (your own
hand edit, a Video Haircut / TimeBolt cut, or an earlier draft), measured against
one shared word-level transcript.

Inputs: two cut lists. Each may be a TimeBolt / Video Haircut op list
(`.json`: [{start, duration, operation: keep|remove}]) or a timeline exported
from DaVinci Resolve as FCP7 XML (`.xml`: File > Export > Timeline > FCP 7 XML;
only clips of the take on video track 1 count, other media such as b-roll is
ignored). The first is the benchmark (usually your hand edit), the second the
candidate (usually <stem>.aroll.tb.json).

Metrics
  agreement  overlap of kept time, both directions
  bleed      a word the cut DROPPED whose audio partly survives (you hear a fragment)
  clipped    a word the cut KEPT whose audio is partly missing (head or tail chopped)
  energy     RMS level (dBFS) at each cut boundary; quiet is good, loud = mid-speech

Bleeds and clips are the objective part (target 0 / 0). Agreement is context: two
good editors disagree; read --divergence to see whether a difference is an
abandoned take removed (good) or a real sentence lost (bad).

Usage:
  compare_cutlists.py BENCH CAND --transcript <stem>.transcript.json (--wav A.wav | --media VIDEO)
      [--divergence 12] [--detail] [--source NAME] [--record results.jsonl --label TEXT]

Standard library only. Summary JSON on stdout; divergence/detail on stderr.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import wave
import xml.etree.ElementTree as ET
from array import array
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

EPS = 1e-6  # float slop; exact containment must not register as an event


# ---------------------------------------------------------------- cut lists

def xml_keep_ops(path, source=None):
    """Keep ops (source seconds) from an FCP7 XML timeline: clips of one media file on video track 1."""
    root = ET.parse(path).getroot()
    seq = root.find(".//sequence")
    if seq is None:
        raise SystemExit(f"{path}: no <sequence> in this XML")
    names = {}
    for f in root.iter("file"):
        fid = f.get("id")
        name = f.findtext("name") or ""
        url = f.findtext("pathurl") or ""
        if fid and (name or url):
            names[fid] = name or os.path.basename(unquote(url))
    track = seq.find("./media/video/track")
    if track is None:
        raise SystemExit(f"{path}: no video track")
    clips = []
    for ci in track.findall("clipitem"):
        if (ci.findtext("enabled") or "TRUE").upper() == "FALSE":
            continue
        f = ci.find("file")
        name = names.get(f.get("id"), "") if f is not None else ""
        tb = float(ci.findtext("rate/timebase") or seq.findtext("rate/timebase") or 0)
        ntsc = (ci.findtext("rate/ntsc") or seq.findtext("rate/ntsc") or "FALSE").upper() == "TRUE"
        fps = tb * 1000 / 1001 if ntsc else tb
        try:
            i, o = int(ci.findtext("in")), int(ci.findtext("out"))
        except (TypeError, ValueError):
            continue
        if fps and o > i >= 0:
            clips.append((name, i / fps, o / fps))
    if not clips:
        raise SystemExit(f"{path}: no clips on video track 1")
    want = source or Counter(n for n, _, _ in clips).most_common(1)[0][0]
    want_stem = Path(want).stem.lower()
    ops = [{"start": s, "duration": e - s, "operation": "keep"}
           for n, s, e in clips if Path(n).stem.lower() == want_stem]
    print(f"{path}: {len(ops)} clips of {want} on video track 1", file=sys.stderr)
    return ops


def load_ops(path, source=None):
    if str(path).lower().endswith(".xml"):
        return xml_keep_ops(path, source)
    with open(path, encoding="utf-8") as f:
        ops = json.load(f)
    if not isinstance(ops, list):
        raise SystemExit(f"{path}: expected a list of ops, got {type(ops).__name__}")
    return ops


def keep_intervals(ops):
    """Merged, sorted keep intervals."""
    raw = sorted((float(o["start"]), float(o["start"]) + float(o["duration"]))
                 for o in ops if o.get("operation") == "keep")
    merged = []
    for s, e in raw:
        if e <= s:
            continue
        if merged and s <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def total(iv):
    return sum(e - s for s, e in iv)


def overlap(a, b):
    """Total overlap seconds between two sorted interval lists."""
    i = j = 0
    acc = 0.0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if hi > lo:
            acc += hi - lo
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return acc


# ---------------------------------------------------------------- words

def load_words(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    segs = d.get("segments", d) if isinstance(d, dict) else d
    words = []
    for s in segs:
        for w in s.get("words", []):
            st, en = w.get("start"), w.get("end")
            if st is None or en is None or en <= st:
                continue
            words.append((float(st), float(en), w.get("word", "")))
    words.sort()
    return words


def word_overlap(w_start, w_end, iv):
    acc = 0.0
    for s, e in iv:
        if e <= w_start:
            continue
        if s >= w_end:
            break
        acc += min(e, w_end) - max(s, w_start)
    return acc


def boundary_stats(words, iv, tol, keep_thresh):
    """Bleed and clipped-word events. A word present for at least keep_thresh of
    its duration counts as kept (anything missing is a clip); below that it is a
    removed word (anything surviving is a bleed)."""
    bleeds, clipped = [], []
    for st, en, txt in words:
        dur = en - st
        ov = word_overlap(st, en, iv)
        if ov / dur < keep_thresh:
            if ov > max(tol, EPS):
                bleeds.append((st, en, txt, round(ov, 3)))
        else:
            missing = dur - ov
            if missing > max(tol, EPS):
                clipped.append((st, en, txt, round(missing, 3)))
    return bleeds, clipped


def subtract(a, b, min_len=0.3):
    """Regions of a not covered by b, ignoring slivers below min_len."""
    out = []
    for s, e in a:
        cur = [(s, e)]
        for bs, be in b:
            nxt = []
            for cs, ce in cur:
                if be <= cs or bs >= ce:
                    nxt.append((cs, ce))
                    continue
                if bs > cs:
                    nxt.append((cs, bs))
                if be < ce:
                    nxt.append((be, ce))
            cur = nxt
        out.extend(cur)
    return [(s, e) for s, e in out if e - s >= min_len]


def region_text(words, s, e, pad=0.05):
    return " ".join(w for st, en, w in words if en > s + pad and st < e - pad)


def report_divergence(words, a_iv, b_iv, top, min_len=0.3):
    for label, iv in (("BENCHMARK kept, candidate CUT", subtract(a_iv, b_iv, min_len)),
                      ("CANDIDATE kept, benchmark CUT", subtract(b_iv, a_iv, min_len))):
        span = sum(e - s for s, e in iv)
        print(f"\n===== {label}: {len(iv)} regions >= {min_len}s, {span:.1f}s total =====", file=sys.stderr)
        for s, e in sorted(iv, key=lambda x: -(x[1] - x[0]))[:top]:
            print(f"  {e - s:5.2f}s @ {s:8.2f}  {region_text(words, s, e)[:160]!r}", file=sys.stderr)


# ---------------------------------------------------------------- audio

def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit(f"{path}: expected 16-bit PCM")
        rate, ch = w.getframerate(), w.getnchannels()
        data = array("h")
        data.frombytes(w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        data.byteswap()
    if ch > 1:
        data = [sum(data[i:i + ch]) / ch for i in range(0, len(data) - len(data) % ch, ch)]
    return data, rate


def extract_wav(media_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
    from vidkit import media
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    media.run([media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", media_path,
               "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", tmp.name], check=True)
    return tmp.name


def cut_boundaries(iv, media_end, edge_tol=0.02):
    """Interior cut points: keep edges that are not the media edges."""
    pts = []
    for s, e in iv:
        if s > edge_tol:
            pts.append(s)
        if e < media_end - edge_tol:
            pts.append(e)
    return sorted(pts)


def boundary_energy(sig, rate, pts, half_win=0.025):
    """RMS dBFS in a window centred on each boundary."""
    out = []
    hw = int(half_win * rate)
    for t in pts:
        c = int(round(t * rate))
        lo, hi = max(0, c - hw), min(len(sig), c + hw)
        if hi <= lo:
            continue
        acc = 0.0
        for x in sig[lo:hi]:
            v = x / 32768.0
            acc += v * v
        rms = math.sqrt(acc / (hi - lo))
        out.append(20 * math.log10(max(rms, 1e-9)))
    return out


def percentile(values, q):
    """Linear-interpolated percentile (numpy's default method)."""
    v = sorted(values)
    if not v:
        return 0.0
    pos = (len(v) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def summarize(name, ops, iv, words, sig, rate, media_end, tol, keep_thresh):
    bleeds, clipped = boundary_stats(words, iv, tol, keep_thresh)
    pts = cut_boundaries(iv, media_end)
    energies = boundary_energy(sig, rate, pts) or [0.0]
    row = {
        "name": name,
        "ops": len(ops),
        "keeps": sum(1 for o in ops if o.get("operation") == "keep"),
        "removes": sum(1 for o in ops if o.get("operation") == "remove"),
        "kept_seconds": round(total(iv), 2),
        "kept_regions": len(iv),
        "bleeds": len(bleeds),
        "clipped": len(clipped),
        "boundaries": len(pts),
        "energy_median_db": round(percentile(energies, 50), 1),
        "energy_p90_db": round(percentile(energies, 90), 1),
    }
    return row, bleeds, clipped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bench", help="benchmark cut (.json op list or Resolve FCP7 .xml)")
    ap.add_argument("cand", help="candidate cut (.json op list or .xml)")
    ap.add_argument("--transcript", required=True, help="the take's <stem>.transcript.json")
    ap.add_argument("--wav", help="16-bit PCM wav of the take (e.g. the work folder's audio_16k.wav)")
    ap.add_argument("--media", help="the take itself (audio is extracted when --wav is not given)")
    ap.add_argument("--source", help="file name of the take inside an XML timeline (default: the most used clip)")
    ap.add_argument("--tol", type=float, default=0.0, help="seconds of fragment before it counts (default 0)")
    ap.add_argument("--keep-thresh", type=float, default=0.75,
                    help="fraction of a word that must survive to count as kept-but-clipped (default 0.75)")
    ap.add_argument("--detail", action="store_true", help="list every bleed/clip event")
    ap.add_argument("--divergence", type=int, default=0, metavar="N",
                    help="print the N largest regions each side kept alone, with their words")
    ap.add_argument("--record", help="append a one-line JSON summary to this .jsonl")
    ap.add_argument("--label", help="name for this comparison in the recorded row")
    args = ap.parse_args()
    if not args.wav and not args.media:
        ap.error("give --wav or --media")

    words = load_words(args.transcript)
    tmp = None
    wav = args.wav or (tmp := extract_wav(args.media))
    try:
        sig, rate = read_wav(wav)
    finally:
        if tmp:
            os.unlink(tmp)
    media_end = len(sig) / rate

    rows, ivs, details = [], [], []
    for name, path in (("benchmark", args.bench), ("candidate", args.cand)):
        ops = load_ops(path, args.source)
        iv = keep_intervals(ops)
        row, bleeds, clipped = summarize(name, ops, iv, words, sig, rate, media_end, args.tol, args.keep_thresh)
        rows.append(row)
        ivs.append(iv)
        details.append((bleeds, clipped))

    b_iv, c_iv = ivs
    inter = overlap(b_iv, c_iv)
    agreement = {
        "shared_kept_seconds": round(inter, 2),
        "pct_of_benchmark_kept_also_kept_by_candidate": round(100 * inter / total(b_iv), 1) if b_iv else 0.0,
        "pct_of_candidate_kept_also_kept_by_benchmark": round(100 * inter / total(c_iv), 1) if c_iv else 0.0,
        "benchmark_only_seconds": round(total(b_iv) - inter, 2),
        "candidate_only_seconds": round(total(c_iv) - inter, 2),
    }
    out = {"media_seconds": round(media_end, 2), "transcript_words": len(words), "tolerance_s": args.tol,
           "keep_thresh": args.keep_thresh, "agreement": agreement, "sides": rows}
    print(json.dumps(out, indent=2))

    if args.divergence:
        report_divergence(words, b_iv, c_iv, args.divergence)

    if args.record:
        b_s, c_s = rows
        rec = {
            "label": args.label or os.path.basename(args.cand),
            "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "benchmark_path": os.path.abspath(args.bench), "candidate_path": os.path.abspath(args.cand),
            "media_seconds": out["media_seconds"], "keep_thresh": args.keep_thresh, "tolerance_s": args.tol,
            "agreement_pct_of_benchmark": agreement["pct_of_benchmark_kept_also_kept_by_candidate"],
            "agreement_pct_of_candidate": agreement["pct_of_candidate_kept_also_kept_by_benchmark"],
            "bench_keeps": b_s["keeps"], "cand_keeps": c_s["keeps"],
            "bench_kept_s": b_s["kept_seconds"], "cand_kept_s": c_s["kept_seconds"],
            "bench_bleeds": b_s["bleeds"], "cand_bleeds": c_s["bleeds"],
            "bench_clipped": b_s["clipped"], "cand_clipped": c_s["clipped"],
            "bench_energy_p90_db": b_s["energy_p90_db"], "cand_energy_p90_db": c_s["energy_p90_db"],
        }
        with open(args.record, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"recorded -> {args.record}", file=sys.stderr)

    if args.detail:
        for row, (bleeds, clipped) in zip(rows, details):
            print(f"\n=== {row['name']}: {len(bleeds)} bleeds ===", file=sys.stderr)
            for st, en, txt, ov in bleeds:
                print(f"  {st:8.2f}-{en:8.2f}  {ov:.3f}s of '{txt}'", file=sys.stderr)
            print(f"\n=== {row['name']}: {len(clipped)} clipped ===", file=sys.stderr)
            for st, en, txt, ms in clipped:
                print(f"  {st:8.2f}-{en:8.2f}  {ms:.3f}s missing from '{txt}'", file=sys.stderr)


if __name__ == "__main__":
    main()
