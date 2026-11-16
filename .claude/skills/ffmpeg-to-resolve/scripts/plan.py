#!/usr/bin/env python3
"""Recipe -> Resolve job: everything the build needs, decided here, in whole frames, without Resolve.

    plan.py <work>/recipe_vN.json [--out DIR] [--project NAME] [--timeline NAME] [--exact-rates]

Reads a talking-head-ffmpeg recipe (never writes it) and writes DIR/job.json (default DIR: <recipe folder>/resolve/
<recipe stem>/). The job is the whole conversion as data: the bins, every timeline item with its track, record frame,
source frame and length, the transforms as Resolve inspector values, what has to be baked with ffmpeg first, the
markers, and every place the timeline will differ from the ffmpeg render ("deviations"). build.py only executes it and
verify.py checks Resolve against it, so a wrong timeline is a wrong job, and that is a file you can read and diff.

Tracks:  V1 a-roll keeps (whole keeps, not split under bricks)   A1 the keeps' sound (a separately recorded mic when the
         V2 b-roll bricks                                           recipe has take_audio, at a sub-frame source offset)
         V3+ overlays (a second track only where two overlap)
Bins:    a-roll/<folder>, b-roll/<folder>, graphics/<folder>, audio. Each holds the clips the recipe uses, with an
         "unused" bin inside it for the other media in that footage folder, so everything is at hand for edits by hand.
         Files outside the project: b-roll/library (the b-roll library or the NAS), b-roll/from <other project>.

What maps to what (measured on Resolve 21.2, see SKILL.md):
  keep                    video item, source frame = round(in_s * fps); linked to its sound
  take_audio              audio-only item from the mic recording at offset_s + rate * in_s (fractional frames)
  gain_db                 the item's AudioVolume
  brick                   video-only item on V2; source frame = render_recipe.seek(): the first frame at or after in_s
  speed                   a clip whose every use plays frame for frame (59.94p at 0.4 on 23.976) is conformed to the
                          timeline rate in the pool; any other speed is the item's Speed
  zoom / fit cover        ZoomX/ZoomY + Pan + Tilt
  grade                   a .cube LUT computed from the renderer's own formula, on the item's first node
  zoom "to", fit blur     baked with the renderer's own ffmpeg filter: the API has no transform keyframes and no blur
                          amount
  overlay .mov            video item on V3+ (alpha read from the file)
  overlay .png / .webm    baked to a ProRes 4444 clip of its length (Resolve pins a still's length; VP9 alpha is not read)
  fade_out                a black clip on the top track with the fade baked into its alpha, and a FadeOut on the last sound
  needs                   red NEED BROLL markers

Stops on any recipe key it does not know (KNOWN): a key that is skipped is an edit that is lost without a word.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "talking-head-ffmpeg" / "scripts"))
import _common as C  # noqa: E402
import recipe as R  # noqa: E402

SCHEMA = "ffmpeg-to-resolve/1"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mxf", ".mkv", ".avi", ".webm", ".mts"}
AUDIO_EXT = {".wav", ".m4a", ".mp3", ".aif", ".aiff", ".flac", ".aac"}
STILL_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".heic"}

KNOWN = {      # every recipe key this converter carries (or knowingly leaves out, with a deviation)
    "top": {"name", "project", "fps", "width", "height", "lufs", "aroll", "broll", "needs", "overlays", "take_audio", "fade_out",
            "voice_clear"},
    "aroll": {"file", "in_s", "out_s", "gain_db"},
    "broll": {"record_s", "dur", "file", "in_s", "speed", "zoom", "fit", "grade", "why"},
    "overlays": {"record_s", "dur", "file", "fade", "why"},
    "needs": {"record_s", "end_s", "note"},
}


def guard(r):
    unknown = [f"recipe: {k}" for k in sorted(set(r) - KNOWN["top"])]
    for part in ("aroll", "broll", "overlays", "needs"):
        seen = set().union(*[set(x) for x in r.get(part) or [{}]])
        unknown += [f"{part}[]: {k}" for k in sorted(seen - KNOWN[part])]
    if unknown:
        sys.exit("this recipe uses keys plan.py does not know. Read what render_recipe.py does with each, teach plan.py to carry "
                 "it (or to bake it), add it to KNOWN, and prove it on the fixture:\n  " + "\n  ".join(unknown))


def kind_of(path):
    e = os.path.splitext(path)[1].lower()
    return "video" if e in VIDEO_EXT else "audio" if e in AUDIO_EXT else "still" if e in STILL_EXT else None


def fps_name(fps):
    """Resolve's name for a frame rate: '23.976', '29.97', '59.94', '24', '30'."""
    f = float(fps)
    return str(int(f)) if abs(f - round(f)) < 1e-6 else f"{f:.3f}".rstrip("0")


@lru_cache(None)
def streams(path):
    """{"v_start": s, "a_start": s}: where each stream's first sample sits on the container's clock. 0 for most files;
    one frame on a clip whose picture starts after its sound; 0.044 s on an Apple AAC recording (its encoder priming)."""
    j = json.loads(subprocess.run([C.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "json", path],
                                  capture_output=True, text=True).stdout or "{}")
    out = {"v_start": None, "a_start": None}
    for st in j.get("streams", []):
        t = float(st["start_time"]) if st.get("start_time") not in (None, "N/A") else 0.0
        key = {"video": "v_start", "audio": "a_start"}.get(st.get("codec_type"))
        if key and out[key] is None:
            out[key] = t
    return {k: v or 0.0 for k, v in out.items()}


def lead(path, fn):
    """Frames Resolve's clip starts before ffmpeg's frame 0. Resolve places a clip on the container's clock, so a video
    stream whose first frame sits at 0.0417 s shows nothing on its frame 0 and ffmpeg's frame k on k + 1."""
    return round(streams(path)["v_start"] * float(fn))


def old_seek_frame(in_s, fn, path):
    """The source frame a draft from the renderer BEFORE its seek fix starts a piece on: in_s printed with 4 decimals,
    rounded by ffmpeg to the stream's time base, first frame at or after that tick. Only for verify.py --old-renderer."""
    j = json.loads(subprocess.run([C.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=time_base,start_time:format=start_time", "-of", "json", path],
                                  capture_output=True, text=True).stdout or "{}")
    st = (j.get("streams") or [{}])[0]

    def num(x):
        return Fraction(str(x)) if x not in (None, "N/A") else Fraction(0)
    tb = Fraction(st.get("time_base") or "1/1000000")
    ss = Fraction(f"{in_s:.4f}") + num((j.get("format") or {}).get("start_time")) - num(st.get("start_time"))
    tick = math.floor(ss / tb + Fraction(1, 2))
    per = 1 / (tb * Fraction(fn).limit_denominator(1001))
    return max(math.ceil(Fraction(tick) / per), 0)


def cover(sw, sh, W, H, z, cx, cy):
    """render_recipe.geometry()'s cover crop as Resolve inspector values. ffmpeg scales the source to cover W*z x H*z
    and crops W x H about (cx, cy), clamped inside the image. Resolve first fits the source in the frame, then Zoom
    scales about the frame centre and Pan / Tilt shift the result (Pan in frame px * W / fitted width, right is
    positive; Tilt in frame px * H / fitted height, up is positive)."""
    zw, zh = int(W * z) // 2 * 2, int(H * z) // 2 * 2
    k = max(zw / sw, zh / sh)                       # source px -> frame px
    iw, ih = sw * k, sh * k
    x = min(max(iw * cx - W / 2, 0), iw - W)
    y = min(max(ih * cy - H / 2, 0), ih - H)
    fit = min(W / sw, H / sh)
    w0, h0 = sw * fit, sh * fit
    dx = (x + W / 2) - iw / 2                        # the crop centre's offset from the image centre, frame px
    dy = (y + H / 2) - ih / 2
    zoom = k / fit
    return {"ZoomX": round(zoom, 5), "ZoomY": round(zoom, 5), "Pan": round(-dx * W / w0, 3), "Tilt": round(dy * H / h0, 3)}


def _under(path, root):
    if not root:
        return False
    root = os.path.realpath(os.path.expanduser(str(root)))
    return os.path.realpath(path).startswith(root + os.sep)


def bins_for(path, P):
    """The bin (a list of folder names) a file belongs in."""
    p = Path(path)
    try:
        rel = p.relative_to(P)
    except ValueError:
        if _under(path, C.settings.get("paths.broll_library_dir")) or _under(path, C.settings.get("nas.mount_path")):
            return ["b-roll", "library"]
        other = C.settings.find_project_root(path)
        return ["b-roll", "from " + other.name] if other else ["b-roll", "elsewhere"]
    parts = rel.parts
    foot = Path(C.settings.layout("footage")).parts
    if parts[:len(foot)] == foot and len(parts) > len(foot) + 1:
        sub = parts[len(foot):-1]
        name = sub[0].lower().replace("-", "").replace("_", "").replace(" ", "")
        top = "a-roll" if "aroll" in name else "b-roll" if "broll" in name else "footage"
        return [top, *sub]
    for part, top in (("work", "graphics"), ("graphics", "graphics"), ("audio", "audio")):
        lay = Path(C.settings.layout(part)).parts
        if parts[:len(lay)] == lay:
            rest = [x for x in parts[len(lay):-1] if x != "talking-head"]
            return [top, *rest[:1]] if top == "graphics" else [top]
    if kind_of(path) == "audio":
        return ["audio"]
    return ["other", *parts[:-1][:1]]


def lut_text(g, size=33):
    """render_recipe.grade()'s lutyuv as a .cube: gamma and gain on the luma, sat on the chroma about grey, in bt709
    Y'CbCr. Resolve hands a LUT full-range R'G'B' in 0..1 and the renderer works on the video-range code values, which
    is the same picture, so the formula carries over as it is. A colour the grade pushes outside the RGB gamut is
    clipped here and not by lutyuv (colour bars show it, footage does not)."""
    gamma, gain, sat = float(g.get("gamma", 1.0)), float(g.get("gain", 1.0)), float(g.get("sat", 1.0))
    kr, kb = 0.2126, 0.0722
    kg = 1 - kr - kb
    out = [f'TITLE "ffmpeg-to-resolve grade gamma {gamma} gain {gain} sat {sat}"', f"LUT_3D_SIZE {size}"]

    def c(v):
        return min(max(v, 0.0), 1.0)
    for bi in range(size):
        for gi in range(size):
            for ri in range(size):
                r, gg, b = ri / (size - 1), gi / (size - 1), bi / (size - 1)
                y = kr * r + kg * gg + kb * b
                cb, cr = (b - y) / (2 * (1 - kb)), (r - y) / (2 * (1 - kr))
                y2 = c(gain * (y ** (1 / gamma)))
                cb2, cr2 = c(cb * sat + 0.5) - 0.5, c(cr * sat + 0.5) - 0.5
                r2 = y2 + 2 * (1 - kr) * cr2
                b2 = y2 + 2 * (1 - kb) * cb2
                g2 = (y2 - kr * r2 - kb * b2) / kg
                out.append(f"{c(r2):.6f} {c(g2):.6f} {c(b2):.6f}")
    return "\n".join(out) + "\n"


def piece_filter(RR, p, fps_s, W, H):
    """render_recipe's own picture chain for one piece, as its main() builds it, by calling its functions."""
    slow = f",setpts=PTS/{p['speed']:.6f}" if abs(p["speed"] - 1) > 1e-6 else ""
    geo = RR.push_in(p, W, H, fps_s) if "to" in (p.get("zoom") or {}) else RR.geometry(p, W, H)
    return (f"setpts=PTS-STARTPTS{slow},fps={fps_s},tpad=stop_mode=clone:stop_duration=2,{geo},"
            f"format=yuv420p,setsar=1{RR.grade(p)}{RR.retag(p['file'])}")


def plan(recipe_path, out_dir=None, project=None, timeline=None, exact_rates=False):
    rp = Path(recipe_path).resolve()
    raw = rp.read_bytes()
    r = json.loads(raw)
    guard(r)
    errs, _, _ = R.lint(r)
    if errs:
        sys.exit("the recipe has lint errors (talking-head-ffmpeg recipe.py lint): convert a recipe that renders:\n  " + "\n  ".join(errs))
    P = Path(r["project"]).expanduser().resolve() if r.get("project") else C.project_root(rp)
    out = Path(out_dir).resolve() if out_dir else rp.parent / "resolve" / rp.stem
    fps = R.fps_of(r)
    fps_s = f"{fps.numerator}/{fps.denominator}"
    W, H = R.size_of(r)
    F = R.total_frames(r)
    fo = min(round(float(r.get("fade_out", 0) or 0) * fps), F)
    items, bakes, luts, deviations, media = [], [], {}, [], {}
    conform_votes = {}

    import render_recipe as RR
    if not hasattr(RR, "seek"):
        sys.exit("render_recipe.py has no seek(): this plan.py goes with a talking-head-ffmpeg that has it (update the repo)")

    def use(path, **kw):
        m = media.setdefault(path, {"file": path, "kind": kind_of(path) or "video", "used": True, "bin": bins_for(path, P)})
        m.update(kw)
        return m

    def baked_media(path):
        media[path] = {"file": path, "kind": "video", "used": True, "bin": ["graphics", "baked"], "fps": str(fps), "size": [W, H]}

    # ---- a-roll: one video item per keep on V1, its sound on A1
    keeps = R.aroll_frames(r)
    for i, k in enumerate(keeps):
        _, fn, sw, sh = R.probe(k["file"])
        use(k["file"], fps=str(fn), size=[sw, sh])
        if fn != fps:
            sys.exit(f"keep {i}: {os.path.basename(k['file'])} is {float(fn):.3f} fps on a {float(fps):.3f} timeline: "
                     "a-roll at another rate is not handled yet (wrap it as a clip at the recipe's rate first)")
        f0 = round(k["in_s"] * fps)
        sf, s0 = R.keep_sound(r, k)
        v = {"id": f"k{i}", "role": "aroll", "track": ["video", 1], "file": k["file"], "rec_f": k["rec_f"], "n": k["n"],
             "src_f": f0 + lead(k["file"], fn), "media": "video", "props": {}, "label": f"keep {i}"}
        # the renderer counts SAMPLES from the stream's first one; Resolve places the stream on the container's clock, so
        # a stream that starts at 0.044 s (an Apple AAC recording's priming) plays 44 ms late unless that is added
        a_src = (s0 + streams(sf)["a_start"]) * float(fps)
        a = {"id": f"k{i}a", "role": "aroll-sound", "track": ["audio", 1], "file": sf, "rec_f": k["rec_f"], "n": k["n"],
             "src_f": round(a_src) if abs(a_src - round(a_src)) < 1e-6 else round(a_src, 6), "media": "audio", "props": {},
             "link": f"k{i}", "label": f"keep {i} sound"}
        if sf != k["file"]:
            use(sf, fps=None)
        if k["gain_db"]:
            a["props"]["AudioVolume"] = round(k["gain_db"], 2)
        if abs(sw / sh - W / H) > 0.01:
            deviations.append(f"keep {i}: its {sw}x{sh} picture is fitted with bars, as in the render")
        items += [v, a]

    # ---- b-roll bricks on V2
    for b in R.brick_frames(r):
        _, fn, sw, sh = R.probe(b["file"])
        sp = b["speed"]
        z = b.get("zoom") or {}
        zf = float(z.get("z", 1.0))
        fit = b.get("fit") or ("cover" if zf > 1.001 or "to" in z else "contain")
        ratio = sp * float(fn) / float(fps)          # source frames per timeline frame
        frame_for_frame = abs(ratio - 1) < 1e-4
        it = {"id": f"b{b['i']}", "role": "broll", "track": ["video", 2], "file": b["file"], "rec_f": b["rec_f"], "n": b["n"],
              "media": "video", "props": {}, "label": f"brick {b['i']}", "why": b.get("why", "")}
        why = ("the scripting API has no transform keyframes" if "to" in z else "the scripting API has no blur amount" if fit == "blur"
               else "--exact-rates: at another rate Resolve picks the earlier source frame where ffmpeg picks the nearest"
               if exact_rates and not frame_for_frame and abs(sp - 1) < 1e-6 else None)
        if why:
            what = "push-in" if "to" in z else "blur-fit" if fit == "blur" else "resampled"
            p = {"file": b["file"], "in_s": b["in_s"], "n": b["n"], "brick_n": b["n"], "brick_off": 0, "speed": sp,
                 "zoom": b.get("zoom"), "fit": b.get("fit"), "grade": b.get("grade")}
            vf = piece_filter(RR, p, fps_s, W, H)
            st = os.stat(b["file"])
            ss = f"{RR.seek(b['file'], b['in_s'])[1]:.6f}"     # the renderer's own seek: the clip starts on the draft's frame
            key = hashlib.sha1(f"{os.path.realpath(b['file'])}|{st.st_size}|{int(st.st_mtime)}|ss{ss}|{b['n']}|{vf}".encode()).hexdigest()[:12]
            baked = str(out / "baked" / f"{it['id']}_{what}_{key}.mp4")
            bakes.append({"id": it["id"], "kind": "clip", "what": what, "out": baked, "src": b["file"], "ss": ss, "vf": vf,
                          "n": b["n"], "size": [W, H]})
            use(b["file"], fps=str(fn), size=[sw, sh])          # the original stays in the pool, in its bin
            baked_media(baked)
            it.update(file=baked, src_f=0, baked_from=b["file"])
            deviations.append(f"brick {b['i']} ({what}) is a baked clip: {why}. The original is in the pool")
            items.append(it)
            continue
        m = use(b["file"], fps=str(fn), size=[sw, sh])
        conform_votes.setdefault(b["file"], []).append(frame_for_frame and fn != fps)
        # ffmpeg's fps filter shows the NEAREST source frame and Resolve the earlier one. At 2.5 source frames per timeline
        # frame (59.94p at real time) that is a frame or two apart all the way; starting floor(step / 2) later puts the
        # first frame on ffmpeg's and halves the rest. Below 2 it is 0.
        it["src_f"] = RR.seek(b["file"], b["in_s"])[0] + lead(b["file"], fn) + (0 if frame_for_frame else math.floor(ratio / 2))
        it["src_step"] = round(ratio, 6)
        if not frame_for_frame and abs(sp - 1) > 1e-6:
            it["speed"] = round(sp * 100, 4)
        if fit == "cover":
            it["props"].update(cover(sw, sh, W, H, zf, float(z.get("cx", 0.5)), float(z.get("cy", 0.5))))
        if b.get("grade") and RR.grade(b):
            g = {k2: float(b["grade"].get(k2, 1.0)) for k2 in ("gamma", "gain", "sat")}
            key = hashlib.sha1(json.dumps(g, sort_keys=True).encode()).hexdigest()[:10]
            luts[key] = g
            it["lut"] = str(out / "luts" / f"grade_{key}.cube")
        if RR.retag(b["file"]):
            m["retag"] = True                        # not limited-range bt709 by its tags
        items.append(it)
    for f, votes in conform_votes.items():
        if any(votes):
            if not all(votes):
                sys.exit(f"{os.path.basename(f)} plays frame for frame in one brick and at another speed in another: "
                         "a pool clip has one conform rate; not handled yet")
            media[f]["conform_fps"] = fps_name(fps)
            for it in items:
                if it["file"] == f:
                    it["conformed"] = True

    # ---- overlays on V3+
    ends = []                                        # per overlay track: the frame its last item ends on
    for o in R.overlay_frames(r):
        t = next((j for j, e in enumerate(ends) if e <= o["rec_f"]), None)
        if t is None:
            ends.append(0)
            t = len(ends) - 1
        ends[t] = o["rec_f"] + o["n"]
        it = {"id": f"o{o['i']}", "role": "overlay", "track": ["video", 3 + t], "rec_f": o["rec_f"], "n": o["n"], "media": "video",
              "props": {}, "label": f"overlay {o['i']}", "why": o.get("why", "")}
        fd = round(o["fade_s"] * float(fps))
        still, webm = R.is_still(o["file"]), o["file"].lower().endswith(".webm")
        if still or webm:
            st = os.stat(o["file"])
            key = hashlib.sha1(f"{os.path.realpath(o['file'])}|{st.st_size}|{int(st.st_mtime)}|{o['n']}|{o['fade_s']}|{W}x{H}".encode()).hexdigest()[:12]
            baked = str(out / "baked" / f"o{o['i']}_{Path(o['file']).stem}_{key}.mov")
            bakes.append({"id": it["id"], "kind": "still-overlay" if still else "webm-overlay", "out": baked, "src": o["file"],
                          "n": o["n"], "fade_s": o["fade_s"], "size": [W, H]})
            use(o["file"])
            baked_media(baked)
            it.update(file=baked, src_f=0, baked_from=o["file"])
            deviations.append(f"overlay {o['i']} ({os.path.basename(o['file'])}) is a baked ProRes 4444 clip of its length"
                              + (" with its fades: Resolve pins a still's length" if still else ": Resolve does not read VP9 alpha"))
        else:
            _, fn, sw, sh = R.probe(o["file"])
            use(o["file"], fps=str(fn), size=[sw, sh])
            it.update(file=o["file"], src_f=0)
            if fd:
                it["fades"] = {"FadeIn": fd, "FadeOut": fd}
                if abs(fd - o["fade_s"] * float(fps)) > 0.01:
                    deviations.append(f"overlay {o['i']}: its {o['fade_s']} s fades are {fd} whole frames in Resolve")
        items.append(it)

    # ---- the fade-out: a black clip on the top track whose alpha ramps 0 -> (fo-1)/fo, the renderer's own fade. Fading the
    # items would show the a-roll through a fading brick, and a Resolve FadeIn cannot span its whole item (measured: 28 of
    # 29 frames) and ends on full black, which the render does not.
    fade_track = None
    if fo:
        fade_track = 3 + len(ends)
        black = str(out / "baked" / f"fade_to_black_{W}x{H}_{fo}f.mov")
        bakes.append({"id": "fade", "kind": "fade", "out": black, "n": fo, "size": [W, H]})
        baked_media(black)
        items.append({"id": "fade", "role": "fade", "track": ["video", fade_track], "file": black, "rec_f": F - fo, "n": fo, "src_f": 0,
                      "media": "video", "props": {}, "label": "fade to black"})
        deviations.append(f"fade_out: the picture fade is a {fo}-frame black clip with a baked alpha ramp on the top track; delete it to fade by hand")
        for it in [x for x in items if x["media"] == "audio" and x["rec_f"] + x["n"] == F]:
            it.setdefault("fades", {})["FadeOut"] = min(fo, it["n"] - 1)
            if it["n"] <= fo:
                deviations.append(f"fade_out: the last keep is {it['n']} frames, shorter than the {fo}-frame fade; only it fades in Resolve")

    # ---- unused media, for the bins
    foot = P / C.settings.layout("footage")
    if foot.is_dir():
        for p in sorted(foot.rglob("*")):
            if p.is_file() and not p.name.startswith(".") and kind_of(str(p)) and str(p) not in media:
                media[str(p)] = {"file": str(p), "kind": kind_of(str(p)), "used": False, "bin": bins_for(str(p), P) + ["unused"]}

    markers = [{"rec_f": round(n["record_s"] * fps), "n": max(round((n.get("end_s", n["record_s"]) - n["record_s"]) * fps), 1),
                "color": "Red", "name": "NEED BROLL", "note": n.get("note", "")} for n in r.get("needs", [])]
    if r.get("voice_clear"):
        deviations.append("voice_clear: the timeline plays the takes' own sound; the dereverb is not applied (use Resolve's Voice Isolation)")
    deviations.append(f"loudness: the render's two-pass loudnorm to {r.get('lufs', -14)} LUFS is not on the timeline; normalise at delivery")
    deviations.append("seams: the render's 6 ms sound fades at each keep edge are shorter than a frame and are not on the timeline")

    name = r.get("name") or P.name
    job = {"schema": SCHEMA, "recipe": str(rp), "recipe_sha1": hashlib.sha1(raw).hexdigest(), "project_dir": str(P), "out_dir": str(out),
           "project": project or name, "timeline": timeline or f"{name} {rp.stem.replace('recipe_', '')} (ffmpeg)",
           "fps": fps_s, "fps_name": fps_name(fps), "width": W, "height": H, "frames": F,
           "tracks": {"video": ["a-roll", "b-roll"] + [f"graphics {j + 1}" if len(ends) > 1 else "graphics" for j in range(len(ends))]
                               + (["fade"] if fade_track else []),
                      "audio": ["voice"]},
           "media": sorted(media.values(), key=lambda m: (m["bin"], m["file"])), "items": items, "bakes": bakes,
           "luts": [{"file": str(out / "luts" / f"grade_{k}.cube"), "grade": g} for k, g in luts.items()],
           "markers": markers, "deviations": deviations}
    return job, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe")
    ap.add_argument("--out", help="job folder (default <recipe folder>/resolve/<recipe stem>)")
    ap.add_argument("--project", help="Resolve project name (default the recipe's name)")
    ap.add_argument("--timeline", help='timeline name (default "<name> vN (ffmpeg)")')
    ap.add_argument("--exact-rates", action="store_true",
                    help="bake every brick whose clip runs at another rate than the timeline's (25 / 30 / 60 fps at real time), so "
                         "each frame is the draft's; they stop being trimmable source clips")
    a = ap.parse_args()
    job, out = plan(a.recipe, a.out, a.project, a.timeline, a.exact_rates)
    (out / "luts").mkdir(parents=True, exist_ok=True)
    for lut in job["luts"]:
        if not os.path.exists(lut["file"]):
            with open(lut["file"], "w", encoding="utf-8") as f:
                f.write(lut_text(lut["grade"]))
    C.write_json(out / "job.json", job)
    used = [m for m in job["media"] if m["used"]]
    print(json.dumps({"job": str(out / "job.json"), "project": job["project"], "timeline": job["timeline"], "frames": job["frames"],
                      "items": len(job["items"]), "media_used": len(used), "media_unused": len(job["media"]) - len(used),
                      "bakes": len(job["bakes"]), "luts": len(job["luts"]), "markers": len(job["markers"]),
                      "conformed": sorted(os.path.basename(m["file"]) for m in job["media"] if m.get("conform_fps"))}))
    for d in job["deviations"]:
        print("DEVIATION", d)


if __name__ == "__main__":
    main()
