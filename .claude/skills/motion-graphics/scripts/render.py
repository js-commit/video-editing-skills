#!/usr/bin/env python3
"""Built clip pages -> video, and stills sheets, with a Chromium-family browser already on this computer (headless).

    render.py clip   <motion>/dist/NN-name.html --recipe <recipe.json> [--out FILE] [--scale 2] [--sub 4] [--webm]
    render.py stills <motion>/dist/NN-name.html <sheet.jpg> T [T ...] [--recipe R --at RECORD_S]
                     [--tile 960 --cols 2 --crop w:h:x:y]

clip: every frame is seek(t) on the page and a screenshot; --sub screenshots per frame spread over a half-frame
shutter are averaged into motion blur (premultiplied, so a transparent panel's edges do not go dark):
  * an opaque clip (bg set)   -> .mp4 H.264 (vidkit.media.h264_args("final")): a full-frame cutaway, a b-roll brick;
  * a panel clip (bg: null)   -> .mov ProRes 4444 with alpha (prores_ks, any ffmpeg), or .webm VP9 with alpha with
    --webm (smaller files): an animated overlay laid over the picture.
The fps comes from the recipe and the size from the page (W x H, times --scale: a 1920x1080 stage renders at 3840x2160
with --scale 2, the same layout, sharp). --out defaults to <motion>/out/NN-name.(mp4|mov|webm). The RGB -> YUV
conversion is ffmpeg's (bt709, limited range), so colours match the rest of the edit.

stills: one screenshot per clip-local time T into a labelled contact sheet. With --recipe and --at (the clip's record
in-point) a transparent panel is drawn over the real picture at in + T (talking head or b-roll): that is how you check
it never covers the speaker's face or hands.

The browser runs headless with a temporary profile (browser.py): the user's own browser is never touched.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
TH = HERE.parent.parent / "talking-head-ffmpeg" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TH))
import _common as C  # noqa: E402  (talking-head-ffmpeg's: vidkit + paths)
from browser import Browser  # noqa: E402

TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
TO_YUV = "scale=out_color_matrix=bt709:out_range=tv"


def open_clip(b, html, scale=1.0):
    """Load a built clip in render mode and size the viewport to its stage. -> {T, W, H, alpha}."""
    b.send("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 1080, "deviceScaleFactor": scale,
                                                  "mobile": False}, page=True)
    b.send("Page.navigate", {"url": Path(html).resolve().as_uri() + "?render"}, page=True)
    for _ in range(200):
        if b.js("document.readyState==='complete' && typeof window.seek==='function'"):
            break
        time.sleep(0.05)
    else:
        sys.exit(f"{html}: never defined seek() - does the fragment call M.scene? " + "; ".join(map(str, b.events)))
    if b.events:
        sys.exit(f"{html}: page error: {b.events[0]}")
    b.js("document.fonts.ready.then(()=>true)", wait=True)
    info = b.js("({T:window.DURATION, W:document.getElementById('stage').offsetWidth, "
                "H:document.getElementById('stage').offsetHeight, "
                "alpha:document.documentElement.classList.contains('alpha')})")
    b.send("Emulation.setDeviceMetricsOverride", {"width": info["W"], "height": info["H"], "deviceScaleFactor": scale,
                                                  "mobile": False}, page=True)
    if info["alpha"]:
        b.send("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}}, page=True)
    return info


def shot(b, t):
    b.js(f"seek({t:.6f})")
    if b.events:
        sys.exit(f"page error at t={t:.3f}: {b.events[0]}")
    return b.screenshot()


def load_recipe(path):
    return (C.read_json(path), Path(path).resolve().parent) if path else (None, None)


def render_clip(a):
    import qc as Q
    r, _ = load_recipe(a.recipe)
    fps = Fraction(str(a.fps or (r or {}).get("fps") or "30"))
    html = Path(a.html).resolve()
    K = max(1, a.sub)
    b = Browser(a.transport)
    try:
        info = open_clip(b, html, a.scale)
        W, H = round(info["W"] * a.scale), round(info["H"] * a.scale)
        if r:
            rw, rh = r.get("width", 1920), r.get("height", 1080)
            if abs(info["W"] / info["H"] - rw / rh) > 0.01:
                sys.exit(f"{html.name}: the stage is {info['W']}x{info['H']}, the recipe {rw}x{rh} - set W/H in M.scene "
                         "to the recipe's shape")
        ext = (".webm" if a.webm else ".mov") if info["alpha"] else ".mp4"
        out = Path(a.out) if a.out else (html.parent.parent / "out" / (html.stem + ext))
        if out.suffix.lower() != ext:
            sys.exit(f"{html.name} is {'a transparent panel (bg: null)' if info['alpha'] else 'opaque'}: "
                     f"its output is {ext}, not {out.suffix}")
        out.parent.mkdir(parents=True, exist_ok=True)
        N = round(info["T"] * fps)
        sub_fps = fps * K
        blur = (f",tmix=frames={K}:weights='{' '.join(['1'] * K)}',select='eq(mod(n\\,{K})\\,{K - 1})'" if K > 1 else "")
        fr = f"{fps.numerator}/{fps.denominator}"
        if info["alpha"]:
            vf = f"format=rgba,premultiply=inplace=1{blur},unpremultiply=inplace=1,setpts=N/({fr})/TB"
            if a.webm:
                vf += ",format=yuva420p"
                enc = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "24", "-row-mt", "1",
                       "-deadline", "good", "-cpu-used", "4"]
            else:
                vf += f",{TO_YUV},format=yuva444p10le"
                enc = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
                       "-vendor", "apl0"]
        else:
            vf = f"format=gbrp{blur},setpts=N/({fr})/TB,{TO_YUV},format=yuv420p"
            enc = C.media.h264_args("final", height=H) + ["-g", str(round(float(fps)))]
        tmp = out.with_name(out.stem + ".part" + ext)
        cmd = [C.ffmpeg(), "-v", "error", "-y", "-f", "image2pipe", "-framerate",
               f"{sub_fps.numerator}/{sub_fps.denominator}", "-c:v", "png", "-i", "-", "-vf", vf, "-r", fr, *enc,
               *TAGS, "-frames:v", str(N), str(tmp)]
        t0 = time.time()
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            for f in range(N):
                for k in range(K):
                    t = max(0.0, f / float(fps) + (k - (K - 1) / 2) / (2 * K * float(fps)))
                    ff.stdin.write(shot(b, t))
                if f and f % 48 == 0:
                    print(f"  {f}/{N} frames", file=sys.stderr, flush=True)
            ff.stdin.close()
        except BrokenPipeError:
            pass
        if ff.wait():
            sys.exit(f"ffmpeg failed on {out.name}")
    finally:
        b.close()
    got = Q.count_frames(tmp)
    if got != N:
        tmp.unlink()
        sys.exit(f"{out.name}: {got} frames, wanted {N}")
    os.replace(tmp, out)
    print(json.dumps({"out": str(out), "frames": N, "seconds": round(N / float(fps), 3), "size": f"{W}x{H}",
                      "alpha": info["alpha"], "sub": K, "render_s": round(time.time() - t0, 1)}))


def picture_at(r, t):
    """(file, source seconds, piece) the recipe shows at record time t: the brick covering it, else the a-roll."""
    import recipe as R
    fps = R.fps_of(r)
    f = round(t * fps)
    for p in R.flatten(r):
        if p["rec_f"] <= f < p["rec_f"] + p["n"]:
            return p["file"], p["in_s"] + float((f - p["rec_f"]) / fps) * p["speed"], p
    return None, None, None


LABEL = ("(t=>{let d=document.getElementById('__t');if(!d){d=document.createElement('div');d.id='__t';"
         "d.style.cssText='position:fixed;left:14px;top:12px;z-index:99;font:600 54px system-ui;color:#fff;"
         "background:rgba(0,0,0,.62);padding:4px 16px;border-radius:12px';document.body.appendChild(d);}d.textContent=t;})")


def render_stills(a):
    r, _ = load_recipe(a.recipe)
    html = Path(a.html).resolve()
    over = r is not None and a.at is not None
    tmp = Path(tempfile.mkdtemp(prefix="motion-stills-"))
    ts = [float(x) for x in a.times]
    b = Browser(a.transport)
    try:
        info = open_clip(b, html, 1)
        W, H = info["W"], info["H"]
        for i, t in enumerate(ts):
            bg = "#000"                            # a panel on black when there is no recipe to show it over
            if over and info["alpha"]:
                import render_recipe as RR
                f, s, p = picture_at(r, a.at + t)
                if f:
                    jpg = tmp / f"bg{i:03d}.jpg"
                    geo = RR.geometry(p, W, H) if p.get("fit") != "blur" else f"scale={W}:{H}"
                    subprocess.run([C.ffmpeg(), "-v", "error", "-y", "-ss", f"{s:.3f}", "-i", f, "-frames:v", "1",
                                    "-vf", geo, "-q:v", "3", str(jpg)], check=True)
                    b.js(f"new Promise(r=>{{const i=new Image();i.onload=i.onerror=()=>r(1);i.src='{jpg.as_uri()}'}})",
                         wait=True)
                    bg = f"url({jpg.as_uri()}) 0 0/100% 100%"
            if info["alpha"]:
                b.js(f"document.documentElement.style.background={json.dumps(bg)}")
            b.js(f"{LABEL}({json.dumps(f'{t:.2f}s')})")
            (tmp / f"{i:03d}.png").write_bytes(shot(b, t))
    finally:
        b.close()
    cols = a.cols or min(4, len(ts))
    rows = -(-len(ts) // cols)
    out = Path(a.sheet)
    out.parent.mkdir(parents=True, exist_ok=True)
    crop = f"crop={a.crop}," if a.crop else ""
    subprocess.run([C.ffmpeg(), "-v", "error", "-y", "-framerate", "1", "-i", str(tmp / "%03d.png"), "-vf",
                    f"{crop}scale={a.tile}:-2,tile={cols}x{rows}:padding=6:color=white", "-frames:v", "1", "-q:v", "3",
                    str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"sheet": str(out), "stills": len(ts), "over_picture": bool(over and info["alpha"])}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd")
    c = sp.add_parser("clip", help="render a built page to video")
    c.add_argument("html")
    c.add_argument("--recipe")
    c.add_argument("--fps", help="without a recipe (default 30)")
    c.add_argument("--out")
    c.add_argument("--scale", type=float, default=1.0, help="2 renders a 1920 stage at 3840 (for a 4K --final)")
    c.add_argument("--sub", type=int, default=4, help="screenshots per frame for motion blur (1 = none, fast look)")
    c.add_argument("--webm", action="store_true", help="a panel as VP9 .webm with alpha instead of ProRes 4444 .mov")
    s = sp.add_parser("stills", help="a labelled contact sheet at clip times")
    s.add_argument("html")
    s.add_argument("sheet")
    s.add_argument("times", nargs="+")
    s.add_argument("--recipe")
    s.add_argument("--at", type=float, help="the clip's record in-point (panel drawn over the real picture)")
    s.add_argument("--tile", type=int, default=640, help="tile width px (960+ to read small text)")
    s.add_argument("--cols", type=int)
    s.add_argument("--crop", help="ffmpeg crop w:h:x:y on each still before tiling (check small text at 1:1)")
    for p in (c, s):
        p.add_argument("--transport", choices=["pipe", "ws"], help="DevTools transport (default: pipe; ws on Windows)")
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return 2
    render_clip(a) if a.cmd == "clip" else render_stills(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
