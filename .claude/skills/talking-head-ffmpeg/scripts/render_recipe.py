#!/usr/bin/env python3
"""Recipe -> mp4 with ffmpeg only: talking head + b-roll bricks + overlays, the a-roll's own sound, loudness-normalised.

    render_recipe.py <work>/recipe_vN.json [OUT.mp4] [--final] [--size WxH] [--prune] [--no-qc] [--allow-black]

Where it goes:
  draft    <project drafts folder>/<name>-draft-vN.mp4 at settings render.draft_height (default 1080p), H.264 draft
           quality (vidkit.media.h264_args("draft"): VideoToolbox on a Mac, NVENC on NVIDIA, else libx264);
  --final  <project finals folder>/<name>-final.mp4 at the recipe's canvas (the source resolution), H.264 final quality.

Picture: recipe.flatten() cuts the record clock into pieces (a-roll between bricks, split at every keep, one piece per
brick, split again at overlay edges). Each piece is its own segment in <work>/segments/, named by a hash of (source,
size, mtime, in, frames, filter, encoder): a notes round that moves three bricks re-encodes only those pieces and their
neighbours, and the final join is a stream copy. Per segment: setpts, fps, tpad (a segment is never short), then the
fit (contain / cover with a zoom focus / blur), limited-range bt709, and a frame-count check.

Overlays: frame-sized RGBA PNGs (held for the slot, alpha fade in/out) or animated clips with alpha (.mov ProRes 4444
or .webm VP9, played frame for frame, fade 0) composited over whatever plays.

Sound: the a-roll only (b-roll is picture). One ffmpeg cuts every keep out of its take sample-exact on the keeps'
frame edges (so sound and picture cannot drift) - or out of a separately recorded mic synced to the take
("take_audio") - with 6 ms fades at each seam against clicks and a keep's "gain_db", joins them, and a two-pass
loudnorm takes it to the recipe's "lufs" (default -14, YouTube's reference) at -1.5 dBTP.

After the mux: qc.py's measured QC (frame count, black frames, loudness, true peak, silences; exit 1 on an error) and
EditReview's cuts.json in <render stem>.review/. --prune deletes cached segments the recipe no longer uses.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402

SR, FADE = 48000, 0.006
TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def geometry(p, W, H):
    """The piece's frame-filling filter. fit: contain (scale + pad, the default), cover (fill and crop about the zoom
    focus), blur (contained over a blurred, darkened copy of itself: a portrait phone clip without bars). A zoom z > 1
    implies cover and punches in; cx / cy is the focus (0-1), clamped so the crop never shows an edge."""
    z = p.get("zoom") or {}
    zf, cx, cy = float(z.get("z", 1.0)), float(z.get("cx", 0.5)), float(z.get("cy", 0.5))
    fit = p.get("fit") or ("cover" if zf > 1.001 else "contain")
    sc = "flags=lanczos:out_range=tv"
    if fit == "cover":
        zw, zh = int(W * zf) // 2 * 2, int(H * zf) // 2 * 2
        return (f"scale={zw}:{zh}:force_original_aspect_ratio=increase:{sc},"
                f"crop={W}:{H}:'min(max(iw*{cx:.4f}-{W / 2},0),iw-{W})':'min(max(ih*{cy:.4f}-{H / 2},0),ih-{H})'")
    if fit == "blur":
        return (f"split[bg][fg];[bg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
                f"boxblur=12:2,scale={W}:{H}:{sc},eq=brightness=-0.08[bgb];"
                f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:{sc}[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2")
    return f"scale={W}:{H}:force_original_aspect_ratio=decrease:{sc},pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"


@functools.lru_cache(None)
def retag(path):
    """",setparams=..." for a source not tagged limited-range bt709 (phone screen recordings are often full-range
    bt470bg), else "". Tagging the output bt709 while frames still say otherwise can crash some hardware encoders, so
    the frames are retagged first."""
    j = json.loads(subprocess.run([C.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=color_space,color_range", "-of", "json", path],
                                  capture_output=True, text=True).stdout or "{}")
    s = (j.get("streams") or [{}])[0]
    if s.get("color_space") == "bt709" and s.get("color_range") == "tv":
        return ""
    return ",setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"


@functools.lru_cache(None)
def channels(path):
    out = subprocess.run([C.ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else 0


def run_filter(head, graph, tail, script):
    """ffmpeg with a filter graph; a long one (hundreds of keeps) goes through a file, because it would overflow the
    command line on some systems. ffmpeg 7+ reads the file with -/filter_complex, older ones with -filter_complex_script."""
    if len(graph) < 24000:
        return subprocess.run([*head, "-filter_complex", graph, *tail], capture_output=True, text=True)
    script.write_text(graph, encoding="utf-8")
    res = subprocess.run([*head, "-/filter_complex", str(script), *tail], capture_output=True, text=True)
    if res.returncode and "filter_complex" in res.stderr and ("Unrecognized" in res.stderr or "not found" in res.stderr):
        res = subprocess.run([*head, "-filter_complex_script", str(script), *tail], capture_output=True, text=True)
    return res


def voice_clear_mix(raw, keeps, cfg, work, fps, ffmpeg):
    """The recipe's "voice_clear": {"variant": "studio", "sources": "all" | [take files]} (voice-clear skill; absent =
    the takes' own sound). Clear runs once over the whole joined a-roll (its output is sample-aligned with it); keeps
    from the listed takes play the cleaned sound, the rest (a close-mic voice-over) their own, the cleaned ranges
    level-matched to theirs."""
    if not cfg:
        return raw
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "voice-clear", "scripts"))
    import voice_clear as VC
    srcs = cfg.get("sources", "all")
    flagged = [k for k in keeps if srcs == "all" or k["file"] in srcs]
    if not flagged:
        return raw
    clean = work / "render_aroll_clear.wav"
    out = work / "render_aroll_voice.wav"
    info = VC.clean(str(raw), str(clean), cfg.get("variant", "studio"), float(cfg.get("strength", 1.0)))
    up = "pan=stereo|c0=c0|c1=c0"
    if len(flagged) == len(keeps):
        cmd = ["-i", str(clean), "-af", up]
    else:
        spans = []
        for k in flagged:                                  # merge the listed takes' keeps into record-clock ranges
            a0, a1 = k["rec_f"] / fps, (k["rec_f"] + k["n"]) / fps
            if spans and abs(spans[-1][1] - a0) < 1e-6:
                spans[-1][1] = a1
            else:
                spans.append([a0, a1])
        on = "+".join(f"between(t,{float(a):.6f},{float(b):.6f})" for a, b in spans)

        def lufs_in(f, pre=""):                            # both measured as stereo (a mono file reads 3 dB quieter)
            e = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(f), "-af",
                                f"{pre}aselect='{on}',asetpts=N/SR/TB,ebur128", "-f", "null", "-"],
                               capture_output=True, text=True).stderr
            return float(re.search(r"I:\s+(-?[\d.]+) LUFS", e[e.rfind("Summary:"):]).group(1))
        g = lufs_in(raw) - lufs_in(clean, up + ",")        # Clear lands ~2 dB under the take: match it to the rest
        cmd = ["-i", str(raw), "-i", str(clean), "-filter_complex",
               f"[0:a]volume=0:enable='{on}'[o];[1:a]{up},volume={g:.2f}dB,volume=0:enable='not({on})'[c];"
               f"[o][c]amix=inputs=2:normalize=0"]
    res = subprocess.run([ffmpeg, "-v", "error", "-y", *cmd, "-c:a", "pcm_s24le", str(out)], capture_output=True, text=True)
    if res.returncode:
        sys.exit("voice_clear: " + res.stderr[-400:])
    print(f"voice: {info['variant']} x{info['strength']} on {len(flagged)}/{len(keeps)} keeps", flush=True)
    return out


def even(x):
    return int(round(x / 2)) * 2


def out_path(rp, r, final):
    vn = rp.stem.split("_")[-1] if "_" in rp.stem else rp.stem
    name = r.get("name") or "edit"
    if final:
        proj = Path(r["project"]) if r.get("project") else None
        d = C.finals_dir(proj) if proj and proj.is_dir() else rp.parent
        return d / f"{name}-final.mp4"
    return C.settings.drafts_dir(r["aroll"][0]["file"]) / f"{name}-draft-{vn}.mp4"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--final", action="store_true", help="the master: canvas size, final quality, finals folder")
    ap.add_argument("--size", help="override the output size WxH")
    ap.add_argument("--prune", action="store_true", help="delete cached segments this recipe no longer uses")
    ap.add_argument("--no-qc", action="store_true")
    ap.add_argument("--allow-black", action="store_true", help="QC: black frames are intentional")
    a = ap.parse_args()
    rp = Path(a.recipe).resolve()
    work = rp.parent
    r = C.read_json(rp)
    errs, _, _ = R.lint(r)
    if errs:
        sys.exit("recipe has lint errors - run recipe.py lint first:\n  " + "\n  ".join(errs))
    ffmpeg = C.ffmpeg()
    fps = R.fps_of(r)
    fps_s = f"{fps.numerator}/{fps.denominator}"
    W, H = R.size_of(r)
    if not a.final:
        dh = int(C.settings.get("render.draft_height", default=1080) or 1080)
        if H > dh:
            W, H = even(W * dh / H), dh
    if a.size:
        W, H = map(int, a.size.lower().split("x"))
    pieces = R.with_overlays(r, R.flatten(r))
    if a.final:   # a motion-graphics clip rendered at draft size would be upscaled into the master
        for f in sorted({p["file"] for p in pieces} | {o[0] for p in pieces for o in p["ov"]}):
            if os.sep + "motion" + os.sep in f and not R.is_still(f) and R.probe(f)[2] < W:
                print(f"WARNING {os.path.basename(f)} is {R.probe(f)[2]} px wide in a {W}x{H} master: re-render it "
                      f"with motion-graphics render.py clip --scale {W / R.probe(f)[2]:g}", file=sys.stderr)
    try:
        out = Path(a.out).resolve() if a.out else out_path(rp, r, a.final)
    except C.settings.SettingMissing as e:
        C.settings.exit_missing(e)
    out.parent.mkdir(parents=True, exist_ok=True)
    F = R.total_frames(r)
    end_s = float(F / fps)
    seg_dir = work / "segments"
    seg_dir.mkdir(exist_ok=True)
    enc = C.media.h264_args("final" if a.final else "draft", height=H) + ["-g", str(round(float(fps)))] + TAGS
    t0 = time.time()
    print(f"rendering {len(pieces)} pieces at {W}x{H} with {enc[1]} -> {out}", file=sys.stderr, flush=True)

    # ---- picture
    lst, made = [], 0
    for i, p in enumerate(pieces):
        n = p["n"]
        geo = geometry(p, W, H)
        slow = f",setpts=PTS/{p['speed']:.6f}" if abs(p["speed"] - 1) > 1e-6 else ""
        vf = (f"setpts=PTS-STARTPTS{slow},fps={fps_s},tpad=stop_mode=clone:stop_duration=2,{geo},"
              f"format=yuv420p,setsar=1{retag(p['file'])}")
        ov_in, ov_key = [], ""
        if p["ov"]:
            fc = [f"[0:v]{vf}[b0]"]
            for j, (f, off, N, fd) in enumerate(p["ov"]):
                if R.is_still(f):
                    ov_in += ["-framerate", fps_s, "-loop", "1", "-t", f"{float((off + n) / fps) + 0.5:.4f}", "-i", f]
                else:
                    ov_in += (["-c:v", "libvpx-vp9"] if f.lower().endswith(".webm") else []) + ["-i", f]
                fades = (f"fade=t=in:st=0:d={fd}:alpha=1,fade=t=out:st={float(N / fps) - fd:.4f}:d={fd}:alpha=1,"
                         if fd > 0 else "")
                fc.append(f"[{j + 1}:v]format=rgba,{fades}trim=start_frame={off},setpts=PTS-STARTPTS,"
                          f"scale={W}:{H}:out_color_matrix=bt709:out_range=tv,format=yuva420p[o{j}];"
                          f"[b{j}][o{j}]overlay=0:0:eof_action=pass:format=yuv420[b{j + 1}]")
                so = os.stat(f)
                ov_key += f"|{os.path.realpath(f)}:{so.st_size}:{int(so.st_mtime)}"
            fc.append(f"[b{len(p['ov'])}]format=yuv420p,"
                      f"setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709[v]")
            vf_args = ["-filter_complex", ";".join(fc), "-map", "[v]"]
        else:
            vf_args = ["-vf", vf]
        st = os.stat(p["file"])
        key = (f"{os.path.realpath(p['file'])}|{st.st_size}|{int(st.st_mtime)}|{p['in_s']:.4f}|{n}|"
               f"{' '.join(vf_args)}{ov_key}|{' '.join(enc)}")
        seg = seg_dir / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".mp4")
        lst.append(seg)
        if seg.exists():
            continue
        tmp = seg.with_name(seg.stem + ".part.mp4")
        cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{p['in_s']:.4f}", "-i", p["file"], *ov_in, "-an", *vf_args,
               "-frames:v", str(n), *enc, str(tmp)]
        res = C.media.run(cmd, capture_output=True, text=True)
        if res.returncode:
            sys.exit(f"piece {i} ({p['kind']}, {os.path.basename(p['file'])} @ {p['in_s']:.2f}): "
                     f"exit {res.returncode} {res.stderr[-400:]}")
        import qc as Q
        got = Q.count_frames(tmp)
        if got != n:
            tmp.unlink()
            sys.exit(f"piece {i}: {got} frames, wanted {n} ({os.path.basename(p['file'])} @ {p['in_s']:.2f})")
        os.replace(tmp, seg)
        made += 1
        if made % 20 == 0:
            print(f"  {made} segments encoded ({i + 1}/{len(pieces)})", file=sys.stderr, flush=True)
    listing = seg_dir / "list.txt"
    listing.write_text("".join("file '" + str(s).replace("'", "'\\''") + "'\n" for s in lst), encoding="utf-8")

    # ---- sound: every keep, sample-exact on the record clock, 6 ms seam fades, joined
    keeps = R.aroll_frames(r)
    sound = [R.keep_sound(r, k) for k in keeps]
    files = list(dict.fromkeys(f for f, _ in sound))
    for f in files:
        if not channels(f):
            sys.exit(f"{f} has no audio track: the recipe's sound comes from the a-roll")
    ins = [x for f in files for x in ("-i", f)]
    fc, labels = [], []
    for f_i, f in enumerate(files):
        mine = [j for j, (sf, _) in enumerate(sound) if sf == f]
        up = ",pan=stereo|c0=c0|c1=c0" if channels(f) == 1 else ",aformat=channel_layouts=stereo"
        fc.append(f"[{f_i}:a]aresample={SR}{up},asplit={len(mine)}" + "".join(f"[s{j}]" for j in mine)
                  if len(mine) > 1 else f"[{f_i}:a]aresample={SR}{up}[s{mine[0]}]")
    for j, k in enumerate(keeps):
        a0, a1 = round(k["rec_f"] / fps * SR), round((k["rec_f"] + k["n"]) / fps * SR)
        s0 = round(sound[j][1] * SR)
        d = (a1 - a0) / SR
        fd = min(FADE, d / 4)
        gain = f"volume={k['gain_db']:.2f}dB," if k["gain_db"] else ""
        fc.append(f"[s{j}]atrim=start_sample={s0}:end_sample={s0 + a1 - a0},asetpts=PTS-STARTPTS,"
                  f"apad=whole_len={a1 - a0},{gain}afade=t=in:d={fd:.4f},afade=t=out:st={d - fd:.4f}:d={fd:.4f}[k{j}]")
        labels.append(f"[k{j}]")
    fc.append("".join(labels) + f"concat=n={len(keeps)}:v=0:a=1[cat]")
    raw, mixed = work / "render_aroll_raw.wav", work / "render_aroll_mix.wav"
    res = run_filter([ffmpeg, "-v", "error", "-y", *ins], ";".join(fc), ["-map", "[cat]", "-c:a", "pcm_s24le", str(raw)],
                     work / "render_audio_filter.txt")
    if res.returncode:
        sys.exit("audio: " + res.stderr[-400:])
    voiced = voice_clear_mix(raw, keeps, r.get("voice_clear"), work, fps, ffmpeg)
    lufs = float(r.get("lufs", -14))
    ln = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    m = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(voiced), "-af", ln + ":print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
    ln2 = (f"{ln}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
           f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    res = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(voiced), "-af", f"{ln2},aresample={SR}",
                          "-c:a", "pcm_s24le", str(mixed)], capture_output=True, text=True)
    if res.returncode:
        sys.exit("loudnorm: " + res.stderr[-400:])

    # ---- mux
    res = subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                          "-i", str(mixed), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
                          "-t", f"{end_s:.4f}", "-movflags", "+faststart", str(out)], capture_output=True, text=True)
    if res.returncode:
        sys.exit("mux: " + res.stderr[-400:])
    for f in (raw, mixed):
        f.unlink(missing_ok=True)
    if a.prune:
        keep = {str(s) for s in lst}
        gone = [f for f in seg_dir.glob("*.mp4") if str(f) not in keep]
        for f in gone:
            f.unlink()
        print(f"pruned {len(gone)} unused segments", file=sys.stderr)
    r["_recipe_file"] = rp.name
    import review
    cuts = review.write_cuts(out, r)
    print(f"rendered {out}: {len(pieces)} pieces ({made} encoded, {len(pieces) - made} reused), "
          f"{len(r.get('broll', []))} bricks, input {j['input_i']} LUFS -> {lufs}, in {time.time() - t0:.0f}s",
          file=sys.stderr, flush=True)
    result = {"out": str(out), "recipe": str(rp), **R.summary(r), "size": f"{W}x{H}", "segments": len(pieces),
              "encoded": made, "cuts": str(cuts)}
    if a.no_qc:
        print(json.dumps(result))
        return 0
    import qc as Q
    qc, qerrs, qwarns = Q.measure(out, lufs, F, float(fps), a.allow_black)
    print(json.dumps({**result, "qc": qc, "errors": qerrs, "warnings": qwarns}, indent=1))
    for w in qwarns:
        print("WARN ", w, file=sys.stderr)
    for e in qerrs:
        print("ERROR", e, file=sys.stderr)
    return 1 if qerrs else 0


if __name__ == "__main__":
    sys.exit(main())
