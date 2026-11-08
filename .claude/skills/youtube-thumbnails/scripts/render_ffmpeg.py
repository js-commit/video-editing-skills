#!/usr/bin/env python3
"""ffmpeg-only renderer for compose_thumbnail.py (no Pillow needed).

Builds one filtergraph from the layout plan: crop/rotate/retouch the source
frame(s), split or subject band, colour pop or grade, scrim, then each text
block as a blurred shadow layer plus drawtext with an outline. Not meant to be
run directly.
"""
from __future__ import annotations

import functools
import subprocess
import tempfile
from pathlib import Path

import thumbkit as tk
from vidkit import media

ROT = {0: "", 90: ",transpose=2", 180: ",transpose=2,transpose=2", 270: ",transpose=1"}


@functools.lru_cache(None)
def _has_y_align() -> bool:
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-h", "filter=drawtext"], capture_output=True, text=True)
    return "y_align" in r.stdout


def _hex(color: str) -> str:
    return "0x%02X%02X%02X" % tk.hex_rgb(color)


def _median(vals: list) -> float:
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else 0


def _ring_colors(src: dict, box: tuple) -> tuple:
    """Median colour of the strip just above and just below `box` (in the
    rotated source), read through ffmpeg as raw RGB."""
    sw, sh = src["size"]
    x0, y0, x1, y1 = box
    ring = max(4, round(0.08 * min(x1 - x0, y1 - y0)))
    wx0, wy0 = max(0, x0 - ring), max(0, y0 - ring)
    wx1, wy1 = min(sw, x1 + ring), min(sh, y1 + ring)
    ww, wh = wx1 - wx0, wy1 - wy0
    r = tk.ffrun(["-i", src["path"], "-vf", f"format=rgb24{ROT[src['rotate']]},crop={ww}:{wh}:{wx0}:{wy0}",
                  "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], "retouch colour probe")
    px = r.stdout

    def region(rx0, ry0, rx1, ry1):
        out = []
        for y in range(max(0, ry0 - wy0), min(wh, ry1 - wy0)):
            row = y * ww * 3
            for x in range(max(0, rx0 - wx0), min(ww, rx1 - wx0)):
                i = row + 3 * x
                out.append(px[i:i + 3])
        return out

    above = region(x0, y0 - ring, x1, y0)
    below = region(x0, y1, x1, y1 + ring)
    sides = region(x0 - ring, y0 - ring, x0, y1 + ring) + region(x1, y0 - ring, x1 + ring, y1 + ring)
    allpx = above + below + sides

    def med(p):
        p = p or allpx
        return tuple(int(_median([c[k] for c in p])) for k in range(3)) if p else (0, 0, 0)

    return med(above), med(below)


class Graph:
    def __init__(self):
        self.stmts, self.n = [], 0

    def label(self, stem: str = "v") -> str:
        self.n += 1
        return f"{stem}{self.n}"

    def add(self, s: str):
        self.stmts.append(s)

    def text(self) -> str:
        return ";\n".join(self.stmts)


def _source_chain(g: Graph, i: int, src: dict) -> str:
    cur = g.label("s")
    g.add(f"[{i}:v]format=rgb24{ROT[src['rotate']]},setsar=1[{cur}]")
    for (x0, y0, x1, y1) in src["blur"]:
        w, h = x1 - x0, y1 - y0
        a, b, c, nxt = g.label("a"), g.label("b"), g.label("c"), g.label("s")
        g.add(f"[{cur}]split[{a}][{b}]")
        g.add(f"[{b}]crop={w}:{h}:{x0}:{y0},gblur=sigma=24[{c}]")
        g.add(f"[{a}][{c}]overlay={x0}:{y0}:format=rgb[{nxt}]")
        cur = nxt
    sw, sh = src["size"]
    for box in src["fill"]:
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        top, bot = _ring_colors(src, box)
        f = max(2, round(0.10 * min(w, h)))
        wx0, wy0 = max(0, x0 - 2 * f), max(0, y0 - 2 * f)
        wx1, wy1 = min(sw, x1 + 2 * f), min(sh, y1 + 2 * f)
        ww, wh = wx1 - wx0, wy1 - wy0
        t = f"clip((Y-{y0 - wy0})/{h}\\,0\\,1)"
        ch = [f"{top[k]}+({bot[k] - top[k]})*{t}" for k in range(3)]
        p, m, pm, nxt = g.label("p"), g.label("m"), g.label("pm"), g.label("s")
        g.add(f"color=c=black:s={ww}x{wh}:r=1:d=1,format=gbrp,geq=r={ch[0]}:g={ch[1]}:b={ch[2]}[{p}]")
        mx0, my0 = max(0, x0 - f - wx0), max(0, y0 - f - wy0)
        inside = f"between(X\\,{mx0}\\,{mx0 + w + 2 * f})*between(Y\\,{my0}\\,{my0 + h + 2 * f})"
        g.add(f"color=c=black:s={ww}x{wh}:r=1:d=1,format=gray,geq=lum={inside}*255,"
              f"gblur=sigma={max(1, f / 2):.1f}[{m}]")
        g.add(f"[{p}][{m}]alphamerge[{pm}]")
        g.add(f"[{cur}][{pm}]overlay={wx0}:{wy0}:format=rgb[{nxt}]")
        cur = nxt
    return cur


def _crop_scale(g: Graph, cur: str, crop: tuple, dw: int, dh: int) -> str:
    x, y, w, h = crop
    out = g.label("t")
    g.add(f"[{cur}]crop={w}:{h}:{x}:{y},scale={dw}:{dh}:flags=lanczos,setsar=1,format=rgb24[{out}]")
    return out


def _grade_filters(s: float, W: int, H: int, pop: bool) -> str:
    pts = []
    for x in (0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.72, 0.85, 1.0):
        y = x ** (1.0 / (1.0 + 0.22 * s))
        if y > 0.72:
            y = 0.72 + (y - 0.72) * (1 - 0.30 * s)
        y = min(1.0, y * (1 + 0.02 * s))
        pts.append(f"{x:.2f}/{y:.3f}")
    vig = (f"(1-{0.13 * s:.4f}*pow(max(hypot((X-W/2)/(W/2)\\,(Y-H/2)/(H/2))-0.55\\,0)\\,1.6))")
    f = (f"curves=all='{' '.join(pts)}',vibrance=intensity={min(2.0, 0.15 * s):.3f},format=gbrp,"
         f"geq=r='r(X\\,Y)*{vig}':g='g(X\\,Y)*{vig}':b='b(X\\,Y)*{vig}',format=rgb24")
    if pop:
        f += ",unsharp=5:5:0.6:5:5:0"
    return f


def _scrim(g: Graph, base: str, sc: dict, W: int, H: int) -> str:
    if sc["kind"] == "band":
        top, bot = sc["top"], sc["bot"]
        span = max(1, bot - top)
        a = f"if(between(Y\\,{top}\\,{bot})\\,120*pow(1-abs(2*(Y-{top})/{span}-1)\\,0.7)\\,0)"
    elif sc["kind"] == "left":
        e = max(1, sc["edge"])
        a = f"if(lt(X\\,{e})\\,150*pow(1-X/{e}\\,1.2)\\,0)"
    else:
        e = sc["edge"]
        a = f"if(gte(X\\,{e})\\,150*pow((X-{e})/{max(1, W - e)}\\,1.2)\\,0)"
    lay, out = g.label("scr"), g.label("b")
    g.add(f"color=c=black:s={W}x{H}:r=1:d=1,format=gbrap,geq=r=0:g=0:b=0:a='{a}'[{lay}]")
    g.add(f"[{base}][{lay}]overlay=0:0:format=rgb[{out}]")
    return out


def _text_block(g: Graph, base: str, block: dict, font: Path, tdir: Path, W: int, H: int) -> str:
    size, st = block["size"], block["stroke"]
    use_base = _has_y_align()

    def dt(line, color, border_color, idx):
        txt = tdir / f"line_{g.label('l')}.txt"
        txt.write_text(line["text"], encoding="utf-8")
        y = line["baseline"] if use_base else line["top"]
        f = tk.drawtext(txt, font, size, color, str(line["x"]), str(y), border=st, border_color=border_color)
        return f + (":y_align=baseline" if use_base else "")

    sh, out = g.label("sh"), g.label("b")
    shadow = ",".join(dt(ln, "black@0.75", "black@0.75", i) for i, ln in enumerate(block["lines"]))
    g.add(f"color=c=black@0.0:s={W}x{H}:r=1:d=1,format=rgba,{shadow},gblur=sigma={max(1, size // 16)}[{sh}]")
    off = max(1, size // 14)
    mid = g.label("b")
    g.add(f"[{base}][{sh}]overlay={off}:{off}:format=rgb[{mid}]")
    main = ",".join(dt(ln, _hex(ln["color"]), "black", i) for i, ln in enumerate(block["lines"]))
    g.add(f"[{mid}]{main}[{out}]")
    return out


def build_graph(plan: dict, tdir: Path) -> tuple:
    W, H = plan["W"], plan["H"]
    g = Graph()
    inputs = []
    srcs = plan["sources"]
    for i, src in enumerate(srcs):
        inputs += ["-i", src["path"]]
    chains = [_source_chain(g, i, s) for i, s in enumerate(srcs)]
    if plan["subject"]:
        s = plan["subject"]
        bgc, bnd = g.label("bg"), g.label("bd")
        g.add(f"[{chains[0]}]split[{bgc}][{bnd}]")
        x, y, w, h = s["bg_crop"]
        bg = g.label("bg")
        g.add(f"[{bgc}]crop={w}:{h}:{x}:{y},scale={W}:{H}:flags=lanczos,gblur=sigma=28,"
              f"colorchannelmixer=rr=0.5:gg=0.5:bb=0.5,setsar=1[{bg}]")
        bx0, by0, bx1, by1 = s["band"]
        fe = s["feather"]
        band = g.label("band")
        g.add(f"[{bnd}]crop={bx1 - bx0}:{by1 - by0}:{bx0}:{by0},scale={W}:{s['height']}:flags=lanczos,setsar=1,"
              f"format=gbrap,geq=r='r(X\\,Y)':g='g(X\\,Y)':b='b(X\\,Y)':a='255*clip(min(Y\\,H-1-Y)/{fe}\\,0\\,1)'[{band}]")
        base = g.label("b")
        g.add(f"[{bg}][{band}]overlay=0:{s['top']}:format=rgb[{base}]")
    elif len(srcs) == 2:
        t0 = _crop_scale(g, chains[0], srcs[0]["crop"], srcs[0]["dest"][2], srcs[0]["dest"][3])
        t1 = _crop_scale(g, chains[1], srcs[1]["crop"], srcs[1]["dest"][2], srcs[1]["dest"][3])
        d = plan["divider"]
        base = g.label("b")
        stack = "vstack" if d["stacked"] else "hstack"
        if d["stacked"]:
            bars = [f"drawbox=x=0:y={d['cut'] - w // 2}:w={W}:h={w}:color={c}:t=fill"
                    for w, c in ((d["thick"], "black"), (d["thin"], _hex(d["color"])))]
        else:
            bars = [f"drawbox=x={d['cut'] - w // 2}:y=0:w={w}:h={H}:color={c}:t=fill"
                    for w, c in ((d["thick"], "black"), (d["thin"], _hex(d["color"])))]
        g.add(f"[{t0}][{t1}]{stack}=inputs=2,{','.join(bars)}[{base}]")
    else:
        base = _crop_scale(g, chains[0], srcs[0]["crop"], W, H)

    tone = g.label("b")
    if plan["grade"] > 0:
        g.add(f"[{base}]{_grade_filters(plan['grade'], W, H, plan['pop'])}[{tone}]")
    elif plan["pop"]:
        g.add(f"[{base}]eq=saturation=1.15:contrast=1.06,unsharp=5:5:0.6:5:5:0,format=rgb24[{tone}]")
    else:
        g.add(f"[{base}]format=rgb24[{tone}]")
    base = tone
    if plan["scrim"]:
        base = _scrim(g, base, plan["scrim"], W, H)
    for block in plan["blocks"]:
        base = _text_block(g, base, block, Path(plan["font"]), tdir, W, H)
    g.add(f"[{base}]format=rgb24[out]")
    return inputs, g.text()


def render(plan: dict, out: Path, max_bytes: int) -> None:
    with tempfile.TemporaryDirectory(prefix="thumb-ff-") as td:
        tdir = Path(td)
        inputs, graph = build_graph(plan, tdir)
        script = tdir / "graph.txt"
        script.write_text(graph, encoding="utf-8")
        png = tdir / "render.png"
        tk.ffrun(inputs + ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-update", "1", str(png)],
                 f"ffmpeg compose (graph saved at {script} while running)")
        if out.suffix.lower() == ".png":
            out.write_bytes(png.read_bytes())
            if out.stat().st_size > max_bytes:
                out.unlink()
                raise SystemExit("the PNG is over 2 MB; write a .jpg instead")
        else:
            tk.save_jpeg_under(["-i", str(png)], out, max_bytes)
