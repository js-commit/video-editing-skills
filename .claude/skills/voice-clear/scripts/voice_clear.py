#!/usr/bin/env python3
"""voice-clear: take the room out of an on-camera voice with Desert Ant Labs' Clear (a fine-tuned DeepFilterNet 3:
denoise + dereverb, Core ML on the Neural Engine, hundreds of times faster than real time, your audio stays on this Mac).
Apple silicon Mac, macOS 15 or newer.

  check IN... [--json]                          rate each recording SOURCE (not each clip) on the room scale below
        IN = files, folders, or a talking-head-ffmpeg recipe JSON. Clips are grouped by origin (folder + device tags +
        audio format) and ONE sample per group is measured: the 90 s with the most speech from its longest clip
  clean IN... [--out-dir D] [--variant studio|natural] [--strength 1.0] [--force]
        <stem>.clear.wav, mono 48 kHz, sample-aligned with the source, not loudness-normalised: in D, else in the
        project's work folder (work/voice-clear/) for a file inside a project, else beside it
  mux   VIDEO [--out OUT] [--lufs -14] [--variant ..] [--strength ..]
        a copy of VIDEO with the cleaned voice (video stream-copied, two-pass loudnorm, stereo AAC); VIDEO is never touched
  reel  CLIP --window S-E [--window S-E ...] [--variants original,studio,natural] [--out-dir D]
        blind, loudness-matched listening reel (numbered versions, same numbers in every window) in D, else in the
        project's drafts folder for a clip inside a project
  reveal ROUND                                  print a reel's key, then delete the reel and its work files
  build                                         rebuild scripts/bin/clearlab (committed) after a wrapper / SDK change

Room scale (check): syllable contrast = inside running speech, the median over 1 s windows of the gap between the loud
(p90) and quiet (p10) 10 ms levels. Room reverb fills the quiet moments between syllables, so a roomy take reads low.
    0  dry         >= 26 dB   skip       (a close mic, a voice-over booth)
    1  light room  23-26 dB   optional
    2  roomy       18-23 dB   recommend  (a shotgun or camera mic in an untreated room)
    3  very roomy  < 18 dB    recommend
A speech-to-floor SNR under 25 dB (a noisy room) lifts the rating to at least 2; under 15 dB it is not a talking source
("no speech"). Folder scans skip b-roll folders. The scale is a hint for a question to the user, never a reason to
process without asking.

Library: `voice_clear.clean(src, out_wav, "studio", 1.0)`, `voice_clear.clean_cached(src)` (the talking-head-ffmpeg
render calls these for the recipe's "voice_clear" key).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402

PKG = HERE / "clearlab"
BIN = HERE / "bin" / "clearlab"                        # committed: a standalone ~1.5 MB arm64 program
PKG_SDK = "3.5.0"                                      # keep in step with clearlab/Package.swift
SR = 48000
VARIANTS = ("studio", "natural")
MEDIA = {".mp4", ".mov", ".m4v", ".mxf", ".mkv", ".m4a", ".wav", ".mp3", ".aac", ".flac"}
SCALE = [(26.0, 0, "dry", "skip"), (23.0, 1, "light room", "optional"),
         (18.0, 2, "roomy", "recommend"), (-1e9, 3, "very roomy", "recommend")]
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"]


def cache(sub: str = "") -> Path:
    d = settings.cache_dir("voice-clear")
    d = d / sub if sub else d
    d.mkdir(parents=True, exist_ok=True)
    return d


def ff(*args):
    r = subprocess.run([media.ffmpeg(), "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit("ffmpeg: " + r.stderr[-600:])


def problem() -> str | None:
    """Why Clear cannot run on this computer, or None."""
    import platform
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return "needs an Apple silicon Mac (the model runs on the Neural Engine)"
    try:
        if int((platform.mac_ver()[0] or "0").split(".")[0]) < 15:
            return f"needs macOS 15 or newer (this Mac has {platform.mac_ver()[0]})"
    except ValueError:
        pass
    if not os.access(BIN, os.X_OK):
        return f"engine binary missing: {BIN} (voice_clear.py build)"
    return None


def build(force=False):
    """The clearlab program, committed at scripts/bin/clearlab (arm64, macOS 15+). It is standalone (the SDK is
    compiled in; only macOS frameworks load at run time), so nothing builds on a normal run. `build` rebuilds it after a
    wrapper or SDK change (about 15 s with swift from Xcode or the Command Line Tools; the compiler leftovers are deleted)."""
    if BIN.exists() and not force:
        return str(BIN)
    print("building clearlab (Desert Ant Labs Clear SDK) ...", file=sys.stderr, flush=True)
    scratch = cache("build-tmp")
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        pkg, tmp = PKG.resolve(), scratch.resolve()
        maps = [x for root in (pkg, tmp) for x in ("-Xswiftc", "-file-prefix-map", "-Xswiftc", f"{root}=.",
                                                     "-Xcc", f"-ffile-prefix-map={root}=.")]
        r = subprocess.run(["swift", "build", "-c", "release", "--package-path", str(pkg), "--scratch-path", str(tmp)] + maps,
                           capture_output=True, text=True)
        built = scratch / "release" / "clearlab"
        if r.returncode or not built.exists():
            sys.exit("swift build failed:\n" + (r.stdout + r.stderr)[-1500:])
        BIN.parent.mkdir(parents=True, exist_ok=True)
        tmp_bin = str(BIN) + ".tmp"
        shutil.copy2(built, tmp_bin)
        subprocess.run(["strip", "-S", "-x", tmp_bin], check=True)      # no build-machine paths in what ships
        load_cmds = subprocess.run(["otool", "-l", tmp_bin], capture_output=True, text=True, check=True).stdout
        for rpath in re.findall(r"cmd LC_RPATH\n.*\n\s+path (/\S.*?) \(offset", load_cmds):
            if not rpath.startswith("/usr/lib"):                        # the toolchain folder of whoever built it
                subprocess.run(["install_name_tool", "-delete_rpath", rpath, tmp_bin], check=True, capture_output=True)
        subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", "clearlab", tmp_bin], check=True, capture_output=True)
        os.replace(tmp_bin, BIN)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"built {BIN} (signed ad hoc for this Mac)", file=sys.stderr)
    return str(BIN)


def clean(src, out, variant="studio", strength=1.0):
    """Run Clear on SRC (any audio/video ffmpeg reads) -> OUT, a mono 48 kHz 16-bit WAV, sample-aligned with SRC's audio.
    Mastering is bypassed: the caller loudness-normalises. Returns clearlab's JSON (variant, model_revision, realtime)."""
    if variant not in VARIANTS:
        sys.exit(f"variant must be one of {VARIANTS}")
    why = problem()
    if why:
        sys.exit(f"voice-clear {why}")
    src, out = str(src), str(out)
    with tempfile.TemporaryDirectory(dir=str(cache())) as td:
        wav = src
        if not src.lower().endswith(".wav"):
            wav = os.path.join(td, "in.wav")              # ffmpeg decodes what AVFoundation might not (mkv, ...)
            ff("-i", src, "-vn", "-c:a", "pcm_s24le", "-ar", str(SR), wav)
        r = subprocess.run([str(BIN), wav, out, variant, str(strength)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"clearlab failed on {src}:\n{r.stderr[-800:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def project_dir_for(src):
    """The project folder SRC sits in (settings paths.projects_dir and the project layout), else None."""
    return settings.find_project_root(src)


def work_dir_for(src):
    p = project_dir_for(src)
    return p / settings.layout("work") / "voice-clear" if p else None


def clean_cached(src, variant="studio", strength=1.0):
    """clean() into the cache, keyed by the source's path, size and mtime: a re-render reuses it. Entries nobody has
    used for 30 days are pruned on every call."""
    st = os.stat(src)
    h = hashlib.sha1(f"{os.path.abspath(src)}|{st.st_size}|{st.st_mtime}|{variant}|{strength}|{PKG_SDK}".encode()).hexdigest()[:16]
    d = cache("clean")
    out = d / f"{h}.wav"
    for f in d.iterdir():
        if f.stat().st_mtime < time.time() - 30 * 86400:
            f.unlink()
    if not out.exists():
        clean(src, str(out) + ".tmp.wav", variant, strength)
        os.replace(str(out) + ".tmp.wav", out)
    os.utime(out)                                          # a use keeps it
    return str(out)


def origin(path):
    """What makes two clips 'the same recording setup': folder, container brand, device tags, audio format."""
    r = subprocess.run([media.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                        "format_tags:stream=codec_type,codec_name,sample_rate,channels", "-of", "json", path],
                       capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    tags = j.get("format", {}).get("tags", {})
    dev = tuple(sorted((k, v) for k, v in tags.items()
                       if k in ("major_brand", "com.apple.quicktime.make", "com.apple.quicktime.model")
                       or k.startswith("com.android.manufacturer") or k.startswith("com.android.model")))
    au = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not au:
        return None
    return (os.path.dirname(os.path.abspath(path)), dev, au.get("codec_name"), au.get("sample_rate"), au.get("channels"))


def room_score(path):
    """Syllable contrast and SNR of the 90 s with the most speech in PATH (cached by path + size + mtime)."""
    import numpy as np
    st = os.stat(path)
    ck = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime}"
    cache_f = cache() / "checks.json"
    try:
        cached = json.load(open(cache_f))
    except (OSError, ValueError):
        cached = {}
    if ck in cached:
        return cached[ck]
    sr, hop = 16000, 160                                   # 10 ms levels
    raw = subprocess.run([media.ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < sr * 5:
        return None
    f = x[:len(x) // hop * hop].reshape(-1, hop)
    d = 10 * np.log10((f.astype(np.float64) ** 2).mean(1) + 1e-12)
    W = 9000                                               # 90 s of 10 ms frames
    act = (d > np.percentile(d, 95) - 25).astype(float)
    i = int(np.argmax(np.convolve(act, np.ones(W), "valid"))) if len(d) > W else 0
    w = d[i:i + W]
    mid = np.percentile(w, 50)
    gaps = [np.percentile(w[j:j + 100], 90) - np.percentile(w[j:j + 100], 10)
            for j in range(0, len(w) - 100, 50) if (w[j:j + 100] > mid).mean() > 0.5]
    res = {"contrast_db": round(float(np.median(gaps)), 1) if gaps else None,
           "snr_db": round(float(np.percentile(d, 95) - np.percentile(d, 5)), 1),
           "window_s": round(i * hop / sr, 1)}
    cached[ck] = res
    json.dump(cached, open(cache_f, "w"), indent=0)
    return res


def rate(score):
    c = score["contrast_db"]
    if c is None or score["snr_db"] < 15:                  # nothing stands clear of the floor: not a talking source
        return 0, "no speech", "skip"
    lvl, name, act = next((l, n, a) for t, l, n, a in SCALE if c >= t)
    if score["snr_db"] < 25 and lvl < 2:
        lvl, name, act = 2, "noisy", "recommend"
    return lvl, name, act


def expand(inputs):
    files = []
    for p in inputs:
        if os.path.isdir(p):
            for dp, ds, fs in os.walk(p):                  # skip b-roll, aroll-draft intermediates, dot dirs
                ds[:] = [d for d in ds if not (d.startswith(("broll", "b-roll", ".")) or d.endswith("_aroll_draft"))]
                files += [os.path.join(dp, f) for f in sorted(fs)
                          if os.path.splitext(f)[1].lower() in MEDIA and ".clear." not in f and not f.startswith(".")
                          and not re.search(r"(^audio_16k|\.16k|\.raw|\.tight)\.wav$", f)]
        elif p.lower().endswith(".json"):
            r = json.load(open(p))
            heard = r.get("take_audio") or {}              # talking-head: a take's sound can come from a synced mic
            files += [(heard.get(k["file"]) or {}).get("file") or k["file"] for k in r.get("aroll", [])]
            if isinstance(r.get("vo"), dict) and r["vo"].get("file"):
                files.append(r["vo"]["file"])
        else:
            files.append(p)
    return list(dict.fromkeys(os.path.abspath(f) for f in files))


def loudnorm_pass(src, lufs, pre=""):
    """Two-pass loudnorm filter string for SRC (pre = filters that run before it in both passes)."""
    ln = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    m = subprocess.run([media.ffmpeg(), "-hide_banner", "-nostats", "-i", src, "-af", f"{pre}{ln}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
    return (f"{pre}{ln}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
            f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true,aresample={SR}")


def measure(path, start, dur):
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-nostats", "-ss", str(start), "-t", str(dur), "-i", path,
                        "-af", "pan=mono|c0=c0,ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    t = r.stderr[r.stderr.rfind("Summary:"):]
    return (float(re.search(r"I:\s+(-?[\d.]+) LUFS", t).group(1)),
            float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", t).group(1)))


def font() -> str | None:
    return next((f for f in FONTS if os.path.exists(f)), None)


# ------------------------------------------------------------------------------------------------------------ commands
def cmd_check(a):
    try:
        import numpy  # noqa: F401
    except ImportError:
        sys.exit("check needs numpy: python3 -m pip install numpy")
    groups = {}
    for f in expand(a.inputs):
        k = origin(f)
        if k:
            groups.setdefault(k, []).append(f)
    out = []
    for k, fs in groups.items():
        sample = max(fs, key=os.path.getsize)
        s = room_score(sample)
        if not s:
            continue
        lvl, name, act = rate(s)
        out.append({"source": k[0], "clips": fs, "sample": sample, **s, "rating": lvl, "label": name, "action": act})
    if a.json:
        print(json.dumps(out, indent=1))
        return
    for g in out:
        print(f"[{g['rating']}] {g['label']:10s} {g['action']:9s}  contrast {g['contrast_db']} dB, SNR {g['snr_db']} dB  "
              f"{len(g['clips'])} clip(s) in {g['source']}  (sampled {os.path.basename(g['sample'])} @ {g['window_s']} s)")


def cmd_clean(a):
    for src in a.inputs:
        stem = os.path.splitext(os.path.basename(src))[0]
        d = Path(a.out_dir) if a.out_dir else (work_dir_for(src) or Path(os.path.dirname(os.path.abspath(src))))
        d.mkdir(parents=True, exist_ok=True)
        out = d / f"{stem}.clear.wav"
        if out.exists() and not a.force:
            print(f"skip {out} (exists; --force to redo)")
            continue
        j = clean(src, out, a.variant, a.strength)
        print(f"{out}  {j['variant']} x{a.strength}  {j['duration_s']:.0f} s at {j['realtime_factor']:.0f}x realtime")


def cmd_mux(a):
    stem, _ = os.path.splitext(os.path.abspath(a.video))
    out = a.out or f"{stem}.clear.mp4"
    if os.path.abspath(out) == os.path.abspath(a.video):
        sys.exit("refusing to overwrite the input")
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "clear.wav")
        j = clean(a.video, wav, a.variant, a.strength)
        af = loudnorm_pass(wav, a.lufs, pre="pan=stereo|c0=c0|c1=c0,")
        ff("-i", a.video, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", af,
           "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-shortest", out)
    print(f"{out}  voice: {j['variant']} x{a.strength}, {a.lufs} LUFS")


def cmd_reel(a):
    proj = project_dir_for(a.clip)
    out_dir = Path(a.out_dir) if a.out_dir else (settings.drafts_dir(a.clip) if proj else None)
    if not out_dir:
        sys.exit(f"{a.clip} is not inside a project: pass --out-dir")
    wins = []
    for w in a.window:
        s, e = (float(x) for x in w.split("-"))
        wins.append((s, e))
    names = a.variants.split(",")
    for n in names:
        if n != "original" and not re.fullmatch(r"(studio|natural)(@[\d.]+)?", n):
            sys.exit(f"variant {n!r}: original, studio, natural, or studio@0.5 / natural@0.7")
    stem = os.path.splitext(os.path.basename(a.clip))[0]
    rnd = f"{stem}-{datetime.datetime.now():%Y%m%d-%H%M}"
    work = cache("reels") / rnd
    work.mkdir(parents=True, exist_ok=True)
    rounds = cache("rounds")
    src = work / "original.wav"
    ff("-i", a.clip, "-vn", "-ac", "1", "-c:a", "pcm_s24le", "-ar", str(SR), str(src))
    files = {"original": str(src)}
    for n in names:
        if n != "original":
            v, _, s = n.partition("@")
            files[n] = str(work / (n.replace("@", "-") + ".wav"))
            clean(str(src), files[n], v, float(s or 1.0))
    order = names[:]
    random.shuffle(order)
    key = {str(i + 1): n for i, n in enumerate(order)}
    m = {(w, n): measure(files[n], s, e - s) for w, (s, e) in enumerate(wins) for n in names}
    target = min(-16.0, min(L - pk - 1.0 for L, pk in m.values()))   # one target, the hottest clip peaks <= -1 dBFS
    enc = media.h264_args("draft") + ["-pix_fmt", "yuv420p", "-r", "24000/1001",
                                      "-c:a", "aac", "-b:a", "256k", "-ar", str(SR), "-ac", "2"]
    fit = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    fnt = font()
    ff_font = f"fontfile='{fnt}':" if fnt else ""
    parts = []
    for w, (s, e) in enumerate(wins):
        for n in range(1, len(names) + 1):
            v = key[str(n)]
            card, clip = work / f"card_{w}_{n}.mp4", work / f"clip_{w}_{n}.mp4"
            ff("-f", "lavfi", "-i", "color=black:s=1920x1080:r=24000/1001:d=0.8", "-f", "lavfi", "-i",
               f"anullsrc=r={SR}:cl=stereo", "-t", "0.8",
               "-vf", f"drawtext={ff_font}text='{n}':fontsize=320:fontcolor=white:x=(w-tw)/2:y=(h-th)/2", *enc, str(card))
            gain = target - m[(w, v)][0]
            ff("-ss", str(s), "-t", str(e - s), "-i", a.clip, "-ss", str(s), "-t", str(e - s), "-i", files[v],
               "-map", "0:v", "-map", "1:a",
               "-vf", f"{fit},drawtext={ff_font}text='{n}':fontsize=110:fontcolor=white:borderw=6:bordercolor=black:x=50:y=40",
               "-af", f"volume={gain:.2f}dB,pan=stereo|c0=c0|c1=c0,afade=t=in:d=0.03,afade=t=out:st={e - s - 0.05:.3f}:d=0.05",
               *enc, str(clip))
            parts += [card, clip]
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{stem}-voice-blind.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out))
    json.dump({"clip": os.path.abspath(a.clip), "windows": wins, "key": key, "target_lufs": target, "reel": str(out),
               "work": str(work)}, open(rounds / (rnd + ".json"), "w"), indent=1)
    print(f"reel {out}\nround {rnd}: {len(wins)} windows x {len(names)} versions, all at {target:.1f} LUFS "
          f"(reveal with: voice_clear.py reveal {rnd})")


def cmd_reveal(a):
    rounds = cache("rounds")
    p = rounds / (a.round + ".json")
    if not p.exists():
        sys.exit(f"no round {a.round}; have: " + ", ".join(sorted(f.stem for f in rounds.glob("*.json"))))
    rnd = json.load(open(p))
    for n, v in rnd["key"].items():
        print(n, v)
    if os.path.exists(rnd["reel"]):                        # the round is over: the key stays, the media goes
        os.remove(rnd["reel"])
    shutil.rmtree(rnd["work"], ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check"); p.add_argument("inputs", nargs="+"); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("clean"); p.add_argument("inputs", nargs="+"); p.add_argument("--out-dir")
    p.add_argument("--variant", default="studio", choices=VARIANTS); p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_clean)
    p = sub.add_parser("mux"); p.add_argument("video"); p.add_argument("--out"); p.add_argument("--lufs", type=float, default=-14.0)
    p.add_argument("--variant", default="studio", choices=VARIANTS); p.add_argument("--strength", type=float, default=1.0)
    p.set_defaults(fn=cmd_mux)
    p = sub.add_parser("reel"); p.add_argument("clip"); p.add_argument("--window", action="append", required=True)
    p.add_argument("--variants", default="original,studio,natural"); p.add_argument("--out-dir"); p.set_defaults(fn=cmd_reel)
    p = sub.add_parser("reveal"); p.add_argument("round"); p.set_defaults(fn=cmd_reveal)
    p = sub.add_parser("build"); p.set_defaults(fn=lambda a: print(build(force=True)))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
