#!/usr/bin/env python3
"""Render a vertical Short from a finished long-form video with ffmpeg.

    make_short.py SPEC.json                        # render (writes OUTPUT, OUTPUT.plan.json, OUTPUT.ass)
    make_short.py SPEC.json --dry-run              # check the spec, print the plan and the ffmpeg command
    make_short.py SPEC.json --audio-only OUT.wav   # just the cut, loudness-matched audio (for Resolve)
    make_short.py SPEC.json --captions-overlay OUT.mov   # captions on transparent ProRes 4444 (for Resolve)

Cuts land on word boundaries: each in-point / out-point is moved into the
quietest 10 ms of the gap next to the word (never into the neighbouring word)
and every join gets a short fade, so nothing clicks or clips. Framing is per
shot, captions are burned in (ASS through libass when ffmpeg has it, plain
drawtext otherwise), the audio is loudness-normalised in two passes, and
metadata (GPS tags from phone clips included) is stripped.

Spec (JSON; proposals.py spec writes a skeleton):

  {"source": "/abs/long-form.mp4",
   "transcript": "/abs/long-form.transcript.json",   # default: <source stem>.transcript.json
   "output": "/abs/drafts/my-short.mp4",             # default: the project's drafts folder
   "width": 1080, "height": 1920,                    # 9:16; 2160x3840 for a 4K short
   "fps": null,                                      # default: the source's frame rate
   "quality": "final",                               # or "draft" (faster, smaller)
   "lufs": -14,                                      # integrated loudness target; null = leave as is
   "captions": true,                                 # true (auto) | "ass" | "drawtext" | false
   "caption_style": {},                              # see CAPTION_DEFAULTS below
   "pad": {"in_max": 0.20, "out_max": 0.30, "fade_ms": 8},
   "segments": [                                     # playback order; times are SOURCE seconds
     {"start": 61.42, "end": 70.10,                  # word start / word end (from the proposal)
      "framing": [                                   # one piece per shot; all but the last need "until"
        {"until": 64.0, "mode": "crop", "crop_center": 0.62, "face_only": true},
        {"until": 67.5, "mode": "stack",
         "top":    {"crop_center": 0.6, "crop_y": 0.25, "zoom": 1.7},
         "bottom": {"video": {"file": "/abs/broll/close-up.mp4", "in": 3.2}}},
        {"mode": "fit", "video_from": 812.4}]}]}

Piece modes (every piece may carry "why" and "face_only": true|false):
  crop   9:16 window of the shot. crop_center 0 = left .. 1 = right, crop_y the
         same vertically, zoom 1 = full height (2 = a 2x punch-in).
  fit    the whole frame, scaled to the width, over a blurred, darkened copy of
         itself (never black bars). For wide subjects and screen recordings.
  stack  two panes (each W x H/2), seam at the middle: "top" and "bottom" each
         take crop_center / crop_y / zoom / video_from / video. "bottom" is
         required. A talking head in a pane reads best at zoom 1.5-2.
B-roll: "video_from": <source seconds> takes the picture from elsewhere in the
long-form; "video": {"file": ..., "in": seconds} from another file (project
footage, the b-roll library; a still image works too). The audio always
follows the segment.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from array import array
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortslib as sl  # noqa: E402

PLAY_W, PLAY_H = 1080, 1920   # caption geometry is designed at 1080x1920 and scaled to the output

CAPTION_DEFAULTS = {
    "font": "Arial Black",     # libass font name
    "fontfile": None,          # drawtext needs a file; found automatically when unset
    "size": 84,                # px at 1080x1920
    "color": "#FFFFFF",
    "highlight": "#FFD400",    # the word being spoken
    "outline": 8, "shadow": 3,
    "max_words": 3, "max_chars": 16,
    "uppercase": True,
    "margin_v": 700,           # bottom margin over crop shots: text sits in the middle band
    "margin_v_fit": 480,       # fit shots: in the blurred band under the picture, above the UI
    "margin_v_stack": 1060,    # stack shots: just above the seam
    "margin_l": 70, "margin_r": 150,   # wider on the right: the like/comment rail lives there
    "pop": True,               # each chunk pops in slightly larger
}


# ---- spec ---------------------------------------------------------------------

def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    spec["_path"] = str(Path(path).resolve())
    if not spec.get("source"):
        sl.die("spec needs 'source'", 2)
    spec["source"] = str(Path(spec["source"]).expanduser())
    spec.setdefault("transcript", str(sl.default_transcript(spec["source"])))
    if not spec.get("output"):
        slug = spec.get("slug") or Path(path).stem.replace(".spec", "")
        spec["output"] = str(sl.settings.drafts_dir(spec["source"]) / f"{slug}.mp4")
    w, h = sl.parse_size((spec.get("width", sl.DEFAULT_SIZE[0]), spec.get("height", sl.DEFAULT_SIZE[1])))
    spec["width"], spec["height"] = w, h
    if not spec.get("segments"):
        sl.die("spec has no segments", 2)
    return spec


# ---- waveform-safe cut points --------------------------------------------------

SR = 8000
FRAME = 80   # 10 ms at 8 kHz


def rms_frames(source: str, t0: float, dur: float) -> list:
    """10 ms RMS values of the source audio from t0 for dur seconds."""
    if dur <= 0.011:
        return []
    r = subprocess.run(sl.ffmpeg_cmd("-v", "error", "-ss", f"{max(0.0, t0):.4f}", "-t", f"{dur:.4f}", "-i", source,
                                     "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"),
                       capture_output=True)
    pcm = array("h")
    pcm.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    if sys.byteorder == "big":
        pcm.byteswap()
    out = []
    for i in range(0, len(pcm) - FRAME + 1, FRAME):
        block = pcm[i:i + FRAME]
        out.append((sum(x * x for x in block) / FRAME) ** 0.5)
    return out


def quietest(source: str, lo: float, hi: float, prefer_late: bool) -> float:
    """Time of the quietest 10 ms in [lo, hi]; among near-silent frames, the one
    nearest the word (latest for an in-point, earliest for an out-point)."""
    frames = rms_frames(source, lo, hi - lo)
    if not frames:
        return (lo + hi) / 2
    floor = min(frames)
    ok = [i for i, v in enumerate(frames) if v <= floor * 1.5 + 30]
    i = ok[-1] if prefer_late else ok[0]
    return lo + (i + 0.5) * FRAME / SR


def plan_cuts(spec: dict, words: list, src_dur: float) -> list:
    pad = spec.get("pad", {})
    in_max, out_max = float(pad.get("in_max", 0.20)), float(pad.get("out_max", 0.30))
    cuts, offset = [], 0.0
    for i, seg in enumerate(spec["segments"]):
        a, b = float(seg["start"]), float(seg["end"])
        if b <= a:
            sl.die(f"segment {i + 1}: end {b} <= start {a}")
        prev_end = max([w["end"] for w in words if w["end"] <= a + 0.02 and w["start"] < a - 0.02] or [a - in_max])
        next_start = min([w["start"] for w in words if w["start"] >= b - 0.02 and w["end"] > b + 0.02] or [b + out_max])
        lo, hi = max(prev_end + 0.005, a - in_max, 0.0), a - 0.005
        t0 = quietest(spec["source"], lo, hi, prefer_late=True) if hi - lo > 0.02 else max(0.0, min(a, (prev_end + a) / 2))
        lo, hi = b + 0.02, min(next_start - 0.01, b + out_max, src_dur)
        t1 = quietest(spec["source"], lo, hi, prefer_late=False) if hi - lo > 0.02 else min(src_dur, max(b, (b + next_start) / 2))
        cuts.append({"i": i, "t0": round(t0, 4), "t1": round(t1, 4), "word_start": a, "word_end": b,
                     "offset": round(offset, 4)})
        offset += t1 - t0
    return cuts


# ---- framing pieces -------------------------------------------------------------

def video_range(spec, raw: dict, default_start: float, dur: float, where: str) -> dict:
    """Where a piece's (or pane's) picture comes from."""
    if raw.get("video"):
        v = raw["video"]
        f = str(Path(v["file"]).expanduser())
        start = float(v.get("in", 0.0))
        if sl.is_image(f):
            return {"file": f, "start": 0.0, "image": True, "swapped": True}
        d = sl.probe(f)["duration"] or 0
        if start < 0 or start + dur > d + 0.05:
            sl.die(f"{where}: b-roll {Path(f).name} {start:.2f}+{dur:.2f} s runs past its end ({d:.2f} s)")
        return {"file": f, "start": start, "image": False, "swapped": True}
    start = float(raw.get("video_from", default_start))
    d = sl.probe(spec["source"])["duration"]
    if start < 0 or start + dur > d + 0.05:
        sl.die(f"{where}: video_from {start:.2f}+{dur:.2f} s is outside the source ({d:.2f} s)")
    return {"file": spec["source"], "start": start, "image": False, "swapped": "video_from" in raw}


def plan_pieces(spec: dict, cuts: list, fps: Fraction) -> list:
    pieces = []
    for seg, cut in zip(spec["segments"], cuts):
        framing = seg.get("framing") or [{"mode": "crop", "crop_center": seg.get("crop_center", 0.5)}]
        prev = cut["t0"]
        for j, fr in enumerate(framing):
            where = f"segment {cut['i'] + 1} piece {j + 1}"
            last = j == len(framing) - 1
            if last:
                if "until" in fr:
                    sl.die(f"{where}: the last piece runs to the segment end; drop its 'until'")
                end = cut["t1"]
            else:
                if "until" not in fr:
                    sl.die(f"{where}: needs 'until' (source seconds where the next piece starts)")
                end = float(fr["until"])
            if not (prev < end <= cut["t1"] + 1e-6):
                sl.die(f"{where}: until {end} must be inside ({prev:.3f}, {cut['t1']:.3f}]")
            out0 = cut["offset"] + (prev - cut["t0"])
            out1 = cut["offset"] + (end - cut["t0"])
            f0, f1 = round(out0 * fps), round(out1 * fps)
            n = f1 - f0
            mode = fr.get("mode", "crop")
            dur = float(n / fps) + 0.5
            p = {"seg": cut["i"], "mode": mode, "src_start": round(prev, 4), "src_end": round(end, 4),
                 "out_start": round(float(f0 / fps), 4), "out_end": round(float(f1 / fps), 4), "frames": n,
                 "face_only": bool(fr.get("face_only", False)), "why": fr.get("why", "")}
            if n <= 0:
                sl.log(f"warning: {where} is shorter than one frame; skipped")
                prev = end
                continue
            if mode == "stack":
                for bad in ("crop_center", "crop_y", "zoom", "video_from", "video"):
                    if bad in fr:
                        sl.die(f"{where}: in stack mode '{bad}' goes inside 'top' / 'bottom'")
                if not isinstance(fr.get("bottom"), dict):
                    sl.die(f"{where}: stack needs a 'bottom' pane")
                p["panes"] = []
                for name in ("top", "bottom"):
                    pane = fr.get(name) or {}
                    rng = video_range(spec, pane, prev, dur, f"{where} {name}")
                    rng.update({"cx": float(pane.get("crop_center", 0.5)), "cy": float(pane.get("crop_y", 0.5)),
                                "zoom": float(pane.get("zoom", 1.0))})
                    p["panes"].append(rng)
            elif mode in ("crop", "fit"):
                rng = video_range(spec, fr, prev, dur, where)
                rng.update({"cx": float(fr.get("crop_center", 0.5)), "cy": float(fr.get("crop_y", 0.5)),
                            "zoom": float(fr.get("zoom", 1.0))})
                p["panes"] = [rng]
            else:
                sl.die(f"{where}: unknown mode {mode!r} (crop, fit or stack)")
            pieces.append(p)
            prev = end
    return pieces


def src_chain(rng: dict) -> tuple:
    """Pre-filter for an input (square pixels) and its display size."""
    info = sl.probe(rng["file"])
    w, h = info["width"], info["height"]
    pre = ""
    if info.get("sar"):
        num, den = (int(x) for x in info["sar"].split(":"))
        w = int(round(w * num / den)) // 2 * 2
        pre = f"scale={w}:{h},setsar=1,"
    return pre, w, h


def piece_filter(k: int, p: dict, ins: list, W: int, H: int, fps: Fraction) -> str:
    tail = (f"tpad=stop_mode=clone:stop_duration=2,trim=end_frame={p['frames']},"
            f"setpts=PTS-STARTPTS,setsar=1,format=yuv420p")
    head = lambda i: f"[{i}:v]setpts=PTS-STARTPTS,fps={fps},"
    if p["mode"] == "stack":
        chains = []
        for tag, rng, i in zip(("t", "b"), p["panes"], ins):
            pre, w, h = src_chain(rng)
            x, y, cw, ch = sl.window(w, h, W / (H / 2), rng["zoom"], rng["cx"], rng["cy"])
            chains.append(f"{head(i)}{pre}crop={cw}:{ch}:{x}:{y},scale={W}:{H // 2}:flags=lanczos,setsar=1[{tag}{k}]")
        return ";".join(chains) + f";[t{k}][b{k}]vstack=inputs=2,{tail}[v{k}]"
    rng, i = p["panes"][0], ins[0]
    pre, w, h = src_chain(rng)
    if p["mode"] == "crop":
        x, y, cw, ch = sl.window(w, h, W / H, rng["zoom"], rng["cx"], rng["cy"])
        return f"{head(i)}{pre}crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,{tail}[v{k}]"
    # fit: the backdrop is built small (cheap blur), the picture fits inside the frame
    x, y, cw, ch = sl.window(w, h, W / H, 1.0, rng["cx"], 0.5)
    sigma = 45 * (W / 4) / 1080
    return (f"{head(i)}{pre}split[bs{k}][fs{k}];"
            f"[bs{k}]crop={cw}:{ch}:{x}:{y},scale={W // 4}:{H // 4}:flags=bilinear,gblur=sigma={sigma:g},"
            f"eq=brightness=-0.12,scale={W}:{H}:flags=bilinear[bb{k}];"
            f"[fs{k}]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1[ff{k}];"
            f"[bb{k}][ff{k}]overlay=(W-w)/2:(H-h)/2,{tail}[v{k}]")


# ---- captions --------------------------------------------------------------------

def caption_words(words: list, cuts: list) -> list:
    out = []
    for c in cuts:
        sel = sl.words_between(words, c["word_start"], c["word_end"], 0.02)
        if not sel:
            sl.log(f"warning: no transcript words inside {c['word_start']:.2f}-{c['word_end']:.2f}")
        out.append([{"word": w["word"], "start": w["start"] - c["t0"] + c["offset"],
                     "end": w["end"] - c["t0"] + c["offset"]} for w in sel])
    return out


def chunk(words: list, max_words: int, max_chars: int) -> list:
    """Caption chunks: break on word count, width, punctuation and pauses."""
    chunks, cur = [], []
    for w in words:
        if cur:
            width = len(" ".join(x["word"] for x in cur + [w]))
            if (len(cur) >= max_words or width > max_chars or w["start"] - cur[-1]["end"] > 0.6
                    or cur[-1]["word"][-1:] in ".!?,;:"):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def events(per_cut: list, style: dict, pieces: list, total: float) -> list:
    flat = [c for cw in per_cut for c in chunk(cw, int(style["max_words"]), int(style["max_chars"]))]
    out = []
    for ci, ch in enumerate(flat):
        start = ch[0]["start"]
        nxt = flat[ci + 1][0]["start"] if ci + 1 < len(flat) else total
        end = min(ch[-1]["end"] + 0.5, max(nxt, ch[-1]["end"]), total)
        mode = next((p["mode"] for p in pieces if p["out_start"] - 1e-6 <= start < p["out_end"]), "crop")
        margin = {"fit": style["margin_v_fit"], "stack": style["margin_v_stack"]}.get(mode, style["margin_v"])
        out.append({"start": round(max(0.0, start), 3), "end": round(end, 3), "mode": mode, "margin_v": margin,
                    "words": [{"word": w["word"].upper() if style["uppercase"] else w["word"],
                               "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in ch]})
    return out


def ass_color(hexrgb: str) -> str:
    h = hexrgb.lstrip("#")
    if len(h) != 6:
        sl.die(f"colour {hexrgb!r} is not #RRGGBB", 2)
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def build_ass(evs: list, style: dict) -> str:
    white, hi = ass_color(style["color"]), ass_color(style["highlight"])
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {PLAY_W}\nPlayResY: {PLAY_H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Cap,{style['font']},{int(style['size'])},{white},{white},&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,"
        f"{style['outline']},{style['shadow']},2,{int(style['margin_l'])},{int(style['margin_r'])},"
        f"{int(style['margin_v'])},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    esc = lambda s: s.replace("\\", "/").replace("{", "(").replace("}", ")")
    lines = []
    for ev in evs:
        ws = ev["words"]
        for wi, w in enumerate(ws):
            a = ev["start"] if wi == 0 else w["start"]
            b = ws[wi + 1]["start"] if wi + 1 < len(ws) else ev["end"]
            if b - a < 0.01:
                continue
            text = " ".join(f"{{\\1c{hi}}}{esc(x['word'])}{{\\1c{white}}}" if xi == wi else esc(x["word"])
                            for xi, x in enumerate(ws))
            pop = "{\\fscx112\\fscy112\\t(0,80,\\fscx100\\fscy100)}" if wi == 0 and style.get("pop") else ""
            lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,{int(ev['margin_v'])},,{pop}{text}")
    return head + "\n".join(lines) + "\n"


def drawtext_chain(evs: list, style: dict, W: int, H: int, text_dir: Path) -> str:
    """Fallback captions: one drawtext per chunk (no per-word highlight; the
    chunks inside the first 2 s use the highlight colour)."""
    font = sl.find_font(style.get("fontfile"))
    if not font:
        sl.die("no font file found for drawtext captions; set caption_style.fontfile to a .ttf")
    s = H / PLAY_H
    x0, x1 = style["margin_l"] * s, W - style["margin_r"] * s
    text_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, ev in enumerate(evs):
        text = " ".join(w["word"] for w in ev["words"])
        tf = text_dir / f"c{i:04d}.txt"
        tf.write_text(text, encoding="utf-8")
        size = min(style["size"] * s, (x1 - x0) / max(1, len(text) * 0.72))
        color = style["highlight"] if ev["start"] < 2.0 else style["color"]
        y = H - ev["margin_v"] * s
        parts.append(
            f"drawtext=fontfile='{sl.ff_escape_path(font)}':textfile='{sl.ff_escape_path(str(tf))}':expansion=none:"
            f"fontsize={size:.0f}:fontcolor=0x{color.lstrip('#')}:borderw={style['outline'] * s:.0f}:bordercolor=black:"
            f"shadowx={style['shadow'] * s:.0f}:shadowy={style['shadow'] * s:.0f}:"
            f"x={(x0 + x1) / 2:.0f}-text_w/2:y={y:.0f}-text_h:enable='between(t,{ev['start']:.3f},{ev['end']:.3f})'")
    return ",".join(parts)


# ---- loudness ---------------------------------------------------------------------

def audio_graph(cuts: list, first_input: int, fade: float) -> str:
    parts = []
    for k, c in enumerate(cuts):
        L = c["t1"] - c["t0"]
        f = min(fade, L / 4)
        parts.append(f"[{first_input + k}:a]asetpts=PTS-STARTPTS,atrim=duration={L:.4f},"
                     f"afade=t=in:st=0:d={f:.4f},afade=t=out:st={L - f:.4f}:d={f:.4f}[a{k}]")
    parts.append("".join(f"[a{k}]" for k in range(len(cuts))) + f"concat=n={len(cuts)}:v=0:a=1[acat]")
    return ";".join(parts)


def audio_inputs(spec: dict, cuts: list) -> list:
    args = []
    for c in cuts:
        args += ["-ss", f"{c['t0']:.4f}", "-t", f"{c['t1'] - c['t0'] + 0.1:.4f}", "-vn", "-i", spec["source"]]
    return args


def measure_loudness(spec: dict, cuts: list, fade: float, target: float) -> str:
    ln = f"loudnorm=I={target}:TP=-1.0:LRA=11"
    g = audio_graph(cuts, 0, fade) + f";[acat]{ln}:print_format=json[aout]"
    r = media_run(sl.ffmpeg_cmd("-nostats", *audio_inputs(spec, cuts), "-filter_complex", g,
                                "-map", "[aout]", "-f", "null", "-"))
    err = r.stderr or ""
    try:
        j = json.loads(err[err.rindex("{"):err.rindex("}") + 1])
        if j["input_i"] in ("-inf", "inf"):
            return ""
        return (f"{ln}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
                f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    except (ValueError, KeyError):
        sl.log("warning: loudness measurement failed; audio left at its own level")
        return ""


def media_run(cmd):
    return sl.media.run(cmd, capture_output=True, text=True)


# ---- main ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--dry-run", action="store_true", help="check the spec, print the plan and the command")
    ap.add_argument("--audio-only", metavar="WAV", help="write only the cut audio (48 kHz WAV)")
    ap.add_argument("--captions-overlay", metavar="MOV", help="write the captions on a transparent ProRes 4444 clip")
    ap.add_argument("--captions", choices=["auto", "ass", "drawtext", "off"], help="override the spec's caption engine")
    a = ap.parse_args()

    spec = load_spec(a.spec)
    W, H = spec["width"], spec["height"]
    src = sl.probe(spec["source"])
    if not src["has_audio"]:
        sl.die("the source has no audio track")
    fps = Fraction(str(spec.get("fps") or src["fps"] or "30")).limit_denominator(1001)
    words = sl.load_words(spec["transcript"]) if Path(spec["transcript"]).exists() else []
    cap_mode = a.captions or spec.get("captions", True)
    cap_mode = {True: "auto", False: "off", None: "off"}.get(cap_mode, cap_mode)
    if cap_mode != "off" and not words:
        sl.die(f"captions need the transcript ({spec['transcript']}); make it with tools/transcribe.py "
               f"or set \"captions\": false")
    if not words:
        sl.log("warning: no transcript: cuts use the given times without word snapping")

    cuts = plan_cuts(spec, words, src["duration"])
    pieces = plan_pieces(spec, cuts, fps)
    total_frames = sum(p["frames"] for p in pieces)
    total = float(Fraction(total_frames) / fps)
    fade = float(spec.get("pad", {}).get("fade_ms", 8)) / 1000
    out = Path(spec["output"]).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    style = dict(CAPTION_DEFAULTS, **(spec.get("caption_style") or {}))
    evs = events(caption_words(words, cuts), style, pieces, total) if cap_mode != "off" else []
    engine = "off"
    if evs:
        if cap_mode == "auto":
            engine = "ass" if (sl.has_filter("ass") or sl.has_filter("subtitles")) else "drawtext"
        else:
            engine = cap_mode
        if engine == "ass" and not (sl.has_filter("ass") or sl.has_filter("subtitles")):
            sl.die("this ffmpeg has no libass (ass/subtitles filter); use --captions drawtext")
        if engine == "drawtext" and not sl.has_filter("drawtext"):
            sl.die("this ffmpeg has neither libass nor drawtext; captions are impossible (set captions false)")
    ass_path = out.with_suffix(".ass")
    cap_filter = ""
    if engine == "ass":
        ass_path.write_text(build_ass(evs, style), encoding="utf-8")
        filt = "ass" if sl.has_filter("ass") else "subtitles"
        cap_filter = f"{filt}=filename='{sl.ff_escape_path(str(ass_path))}'"
    elif engine == "drawtext":
        cap_filter = drawtext_chain(evs, style, W, H, out.with_suffix(".captions"))

    plan = {"spec": spec["_path"], "output": str(out), "size": [W, H], "fps": str(fps),
            "duration_s": round(total, 3), "frames": total_frames, "cuts": cuts,
            "pieces": [dict({k: v for k, v in p.items() if k != "panes"}, sources=[
                {"file": r["file"], "start": round(r["start"], 3), "zoom": r["zoom"], "cx": r["cx"], "cy": r["cy"],
                 "swapped": r["swapped"]} for r in p["panes"]]) for p in pieces],
            "captions": {"engine": engine, "filter": cap_filter, "ass": str(ass_path) if engine == "ass" else None,
                         "events": evs, "style": style}}
    face = sum(p["out_end"] - p["out_start"] for p in pieces if p["face_only"])
    plan["face_only_s"] = round(face, 2)
    plan["face_only_frac"] = round(face / total, 3) if total else 0

    if a.captions_overlay:
        if engine == "off":
            sl.die("no captions to render")
        mov = Path(a.captions_overlay).expanduser().resolve()
        # the alpha must exist from the source on (converting to rgba later yields an opaque frame),
        # and libass only writes into it with alpha=1 (ffmpeg 5.1+)
        overlay = cap_filter
        if engine == "ass":
            if "alpha" not in subprocess.run(sl.ffmpeg_cmd("-h", "filter=ass"), capture_output=True, text=True).stdout:
                sl.die("this ffmpeg's ass filter cannot draw transparency; use --captions drawtext for the overlay")
            overlay = cap_filter + ":alpha=1"
        cmd = sl.ffmpeg_cmd("-y", "-f", "lavfi", "-i",
                            f"color=c=black@0.0:s={W}x{H}:r={fps}:d={total:.4f},format=rgba",
                            "-vf", f"{overlay},format=yuva444p10le", "-c:v", "prores_ks", "-profile:v", "4444",
                            "-pix_fmt", "yuva444p10le", "-an", str(mov))
        sl.run_ok(cmd, "caption overlay")
        print(json.dumps({"captions_overlay": str(mov), "duration_s": round(total, 3)}))
        return 0

    target = spec.get("lufs", -14)
    loud = measure_loudness(spec, cuts, fade, float(target)) if target is not None and not a.dry_run else ""
    if target is not None and a.dry_run:
        loud = f"loudnorm=I={target}:TP=-1.0:LRA=11"
    agraph = audio_graph(cuts, 0, fade) + f";[acat]{loud + ',' if loud else ''}aresample=48000,asetpts=N/SR/TB,apad=whole_dur={total:.4f}[aout]"

    if a.audio_only:
        wav = Path(a.audio_only).expanduser().resolve()
        cmd = sl.ffmpeg_cmd("-y", *audio_inputs(spec, cuts), "-filter_complex", agraph, "-map", "[aout]",
                            "-t", f"{total:.4f}", "-c:a", "pcm_s24le", str(wav))
        sl.run_ok(cmd, "audio render")
        print(json.dumps({"audio": str(wav), "duration_s": round(total, 3)}))
        return 0

    inputs = audio_inputs(spec, cuts)
    n_in = len(cuts)
    vf = []
    for k, p in enumerate(pieces):
        ins = []
        dur = p["frames"] / float(fps) + 0.5
        for r in p["panes"]:
            if r.get("image"):
                inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.4f}", "-i", r["file"]]
            else:
                inputs += ["-ss", f"{r['start']:.4f}", "-t", f"{dur:.4f}", "-an", "-i", r["file"]]
            ins.append(n_in)
            n_in += 1
        vf.append(piece_filter(k, p, ins, W, H, fps))
    vf.append("".join(f"[v{k}]" for k in range(len(pieces))) + f"concat=n={len(pieces)}:v=1:a=0[vcat]")
    vf.append(f"[vcat]{cap_filter + ',' if cap_filter else ''}format=yuv420p[vout]")
    graph = ";".join(vf) + ";" + agraph
    cmd = sl.ffmpeg_cmd("-y", *inputs, "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
                        *sl.media.h264_args(spec.get("quality", "final"), height=min(W, H)),
                        "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                        "-t", f"{total:.4f}", "-map_metadata", "-1", "-map_chapters", "-1",
                        "-movflags", "+faststart", str(out))
    plan_path = out.with_name(out.name + ".plan.json")
    if a.dry_run:
        print(json.dumps(plan, indent=2))
        print(" ".join(f"'{c}'" if (" " in c or ";" in c) else c for c in cmd), file=sys.stderr)
        return 0
    sl.log(f"rendering {out.name}: {len(cuts)} cuts, {len(pieces)} shots, {total:.2f} s at {W}x{H}, captions {engine}")
    sl.run_ok(cmd, "render")
    got = sl.media.probe(out)
    if got["duration"] is None or abs(got["duration"] - total) > 0.25:
        sl.die(f"rendered {got['duration']} s but planned {total:.2f} s")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "duration_s": round(got["duration"], 3), "plan": str(plan_path),
                      "captions": engine, "face_only_frac": plan["face_only_frac"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except sl.settings.SettingMissing as e:
        sl.settings.exit_missing(e)
