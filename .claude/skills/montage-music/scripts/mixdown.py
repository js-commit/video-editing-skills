#!/usr/bin/env python3
"""Mix a montage's soundtrack into one wav: the music cues, the clips' own sound (the "bed")
kept low underneath, and featured moments (a laugh, a line) on top.

  mixdown.py CUT.json OUT.wav [--target-lufs -16] [--bed-rms-db -21] [--speech-lufs -15]

CUT.json is home-video's cut list (make_draft.py writes it). It reads:
  cues     [{file, record_s, in_s, out_s, fade_in, fade_out, target_lufs?, gain_db?}]
           target_lufs levels the stretch that actually plays (measured, not the whole track)
  bed      [{file, in_s, out_s, record_s, gain_db?, fade_in?, fade_out?}]
           each clip's own audio for the time its shot is on screen (or a little before:
           a J-cut), levelled to --bed-rms-db plus its gain_db, high-passed against wind rumble
  moments  [{file, in_s, out_s, record_s, duck?, gain_db?, speech?}]
           featured sounds; duck: true (a spoken line worth hearing, >= 1.2 s) dips the music
           about 6 dB under it. Laughs, splashes and barks sit on top without ducking.
  end_s    the length of the video

Writes OUT.wav (48 kHz stereo) normalised to --target-lufs with peaks under -1 dBFS,
OUT-bed.wav (the bed alone at the same scale, for QC) and prints one JSON line:
{"mix", "bed", "lufs", "gain_db", "cues": [{file, measured_lufs, gain_db}]}.

Why these numbers (learned on real montages):
  - Cues around -20 LUFS over a bed at -21 dB RMS keep the clips audible: people notice
    when a montage's own sound disappears under the music. Lower, not muted.
  - A duck deeper than ~6 dB, or one shorter than ~1.2 s, sounds like a dropout.
  - Every cue edge gets at least a 5 ms fade, or a cut mid-waveform clicks.
  - ffmpeg's alimiter re-normalises to 0 dBFS unless level=disabled; latency=1 keeps the
    bed sample-aligned with the moments (otherwise a featured line doubles with its own bed copy).
"""
from __future__ import annotations

import argparse
import atexit
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402

EDGE_FADE_S = 0.005
DUCK_MIN_S = 1.2
BED_MAX_GAIN = 15.0
END_FADE_S = 2.5


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def ff(*args) -> list:
    return [media.ffmpeg(), "-hide_banner", "-nostdin", *args]


def run(cmd: list, what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"mixdown ({what}) failed: {r.stderr.strip()[-800:]}")


def lufs(path: str, start: float = 0.0, dur: float | None = None) -> float | None:
    r = subprocess.run(ff("-nostats", *(["-ss", f"{start:.3f}"] if start else []), *(["-t", f"{dur:.3f}"] if dur else []),
                          "-i", path, "-map", "0:a:0", "-af", "ebur128", "-f", "null", "-"), capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    v = float(m[-1]) if m else None
    return v if v is not None and v > -70 else None


def volume_stats(path: str, start: float = 0.0, dur: float | None = None) -> tuple:
    r = subprocess.run(ff(*(["-ss", f"{start:.3f}"] if start else []), *(["-t", f"{dur:.3f}"] if dur else []),
                          "-i", path, "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"), capture_output=True, text=True)
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", r.stderr)
    return (float(mean.group(1)) if mean else None, float(peak.group(1)) if peak else None)


def ms(t: float) -> int:
    return max(0, int(round(t * 1000)))


def render_bed(bed: list, end_s: float, rms_db: float, out: str) -> int:
    ins, fl, k = [], [], 0
    for b in bed:
        L = float(b["out_s"]) - float(b["in_s"])
        if L <= 0.05:
            continue
        mv, _ = volume_stats(b["file"], b["in_s"], L)
        if mv is None or mv < -70:
            continue                      # no audio stream, or digital silence
        g = min(BED_MAX_GAIN, rms_db - mv) + float(b.get("gain_db", 0.0))
        fi, fo = float(b.get("fade_in", 0.12)), float(b.get("fade_out", 0.12))
        ins += ["-ss", f"{b['in_s']:.3f}", "-t", f"{L:.3f}", "-i", b["file"]]
        d = ms(b["record_s"])
        fl.append(f"[{k}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,highpass=f=180,volume={g:.1f}dB,"
                  f"afade=t=in:st=0:d={fi:.3f},afade=t=out:st={max(0.0, L - fo):.3f}:d={fo:.3f},adelay={d}|{d}[b{k}]")
        k += 1
    if not k:
        run(ff("-v", "error", "-y", "-f", "lavfi", "-t", f"{end_s:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
               "-c:a", "pcm_s16le", out), "silent bed")
        return 0
    fl.append("".join(f"[b{i}]" for i in range(k)) + f"amix=inputs={k}:normalize=0,"
              f"alimiter=limit=0.5:level=disabled:attack=5:release=80:latency=1,apad=whole_dur={end_s:.3f},"
              f"afade=t=out:st={max(0.0, end_s - END_FADE_S):.3f}:d={END_FADE_S}[out]")
    run(ff("-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[out]", "-t", f"{end_s:.3f}",
           "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", out), "bed")
    return k


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cut")
    ap.add_argument("out")
    ap.add_argument("--target-lufs", type=float, default=-16.0, help="loudness of the finished mix (default -16)")
    ap.add_argument("--bed-rms-db", type=float, default=-21.0, help="level of the clips' own sound before the master gain")
    ap.add_argument("--speech-lufs", type=float, default=-15.0, help="level of a featured spoken line (moment with speech: true)")
    a = ap.parse_args()
    job = json.load(open(a.cut))
    end = float(job["end_s"])
    out = Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cues, moments, bed = job.get("cues", []), job.get("moments", []), job.get("bed", [])
    if not cues and not bed and not moments:
        sys.exit("nothing to mix: the cut list has no cues, bed or moments")

    td = tempfile.mkdtemp(prefix="mixdown-")
    atexit.register(shutil.rmtree, td, True)   # also when a step fails and exits
    ins, fl, labels, report = [], [], [], []
    n = 0
    # music cues
    for c in cues:
        a_in, a_out = float(c.get("in_s", 0.0)), float(c["out_s"])
        L = a_out - a_in
        gain = float(c.get("gain_db", 0.0))
        meas = None
        if c.get("target_lufs") is not None:
            meas = lufs(c["file"], a_in, L)
            if meas is not None:
                gain += float(c["target_lufs"]) - meas
        report.append({"file": c["file"], "measured_lufs": meas, "gain_db": round(gain, 1)})
        fi = max(float(c.get("fade_in") or 0), EDGE_FADE_S)
        fo = max(float(c.get("fade_out") or 0), EDGE_FADE_S)
        chain = [f"atrim={a_in:.3f}:{a_out:.3f}", "asetpts=PTS-STARTPTS", f"volume={gain:.2f}dB"]
        if gain > 0:
            chain.append("alimiter=limit=0.95:level=disabled:attack=5:release=60:latency=1")
        chain += [f"afade=t=in:st=0:d={fi:.3f}", f"afade=t=out:st={max(0.0, L - fo):.3f}:d={fo:.3f}",
                  "aformat=sample_rates=48000:channel_layouts=stereo", f"adelay={ms(c['record_s'])}|{ms(c['record_s'])}"]
        ins += ["-i", c["file"]]
        fl.append(f"[{n}:a:0]" + ",".join(chain) + f"[m{n}]")
        labels.append(f"[m{n}]")
        n += 1
    if labels:
        fl.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,apad=whole_dur={end:.3f}[music]")
    # featured moments
    mom_labels, duck_labels = [], []
    for k, m in enumerate(moments):
        L = float(m["out_s"]) - float(m["in_s"])
        if L <= 0.05:
            continue
        g = float(m.get("gain_db", 0.0))
        if m.get("speech"):
            li = lufs(m["file"], m["in_s"], L)
            g += (a.speech_lufs - li) if li is not None else 0.0
            comp = "acompressor=threshold=0.063:ratio=2.5:attack=4:release=120,"
        else:
            _, pk = volume_stats(m["file"], m["in_s"], L)
            g += min(24.0, -3.0 - pk) if pk is not None else 0.0
            comp = ""
        d = ms(m["record_s"])
        ins += ["-ss", f"{m['in_s']:.3f}", "-t", f"{L:.3f}", "-i", m["file"]]
        fl.append(f"[{n}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,highpass=f=100,{comp}volume={g:.1f}dB,"
                  f"alimiter=limit=0.9:level=disabled:attack=3:release=60:latency=1,"
                  f"afade=t=in:st=0:d=0.08,afade=t=out:st={max(0.0, L - 0.12):.3f}:d=0.12,adelay={d}|{d},asplit[x{k}][s{k}]")
        mom_labels.append(f"[x{k}]")
        if m.get("duck") and L >= DUCK_MIN_S and labels:   # no music cue: nothing to duck
            duck_labels.append(f"[s{k}]")
        else:
            fl.append(f"[s{k}]anullsink")
        n += 1
    bus = []
    if labels and duck_labels:
        fl.append("".join(duck_labels) + f"amix=inputs={len(duck_labels)}:normalize=0,apad=whole_dur={end:.3f}[sc]")
        fl.append("[music][sc]sidechaincompress=threshold=0.02:ratio=2.5:attack=10:release=900:makeup=1:mix=0.5[duck]")
        bus.append("[duck]")
    elif labels:
        bus.append("[music]")
    if mom_labels:
        fl.append("".join(mom_labels) + f"amix=inputs={len(mom_labels)}:normalize=0,apad=whole_dur={end:.3f}[mom]")
        bus.append("[mom]")
    # bed (own pass keeps the main graph small)
    bed_wav = str(Path(td) / "bed.wav")
    nb = render_bed(bed, end, a.bed_rms_db, bed_wav) if bed else 0
    if nb:
        ins += ["-i", bed_wav]
        fl.append(f"[{n}:a:0]anull[bed]")
        bus.append("[bed]")
        n += 1
    if not bus:
        sys.exit("nothing audible to mix (every clip silent and no music)")
    pre = str(Path(td) / "pre.wav")
    fl.append("".join(bus) + f"amix=inputs={len(bus)}:normalize=0[out]" if len(bus) > 1 else f"{bus[0]}anull[out]")
    run(ff("-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[out]", "-t", f"{end:.3f}",
           "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le", pre), "mix")

    # master: one gain to the target loudness, then a peak limiter at -1 dBFS
    li = lufs(pre)
    gain = (a.target_lufs - li) if li is not None else 0.0
    run(ff("-v", "error", "-y", "-i", pre, "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89:level=disabled:attack=3:release=80:latency=1",
           "-ar", "48000", "-c:a", "pcm_s16le", str(out)), "master")
    bed_out = out.with_name(out.stem + "-bed.wav")
    if nb:
        run(ff("-v", "error", "-y", "-i", bed_wav, "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(bed_out)), "bed copy")
    shutil.rmtree(td, ignore_errors=True)
    final = lufs(str(out))
    print(json.dumps({"mix": str(out), "bed": str(bed_out) if nb else None, "lufs": final, "gain_db": round(gain, 1),
                      "bed_clips": nb, "moments": len(mom_labels), "ducking": len(duck_labels), "cues": report}))
    log(f"mix -> {out}: {len(cues)} cues, {nb} bed clips, {len(mom_labels)} moments ({len(duck_labels)} duck), "
        f"{final} LUFS (master {gain:+.1f} dB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
