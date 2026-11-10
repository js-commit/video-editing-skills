#!/usr/bin/env python3
"""Clip fragments -> self-contained HTML pages (engine, page shell, cursor, the user's theme, the video's look and
local images inlined).

    build.py <motion>/clips/NN-name.html [...] [--out <motion>/dist] [--theme theme.json] [--look look.json]
    build.py --show-theme [--look look.json]    # the theme the clips will get

A fragment is the clip's own <title>, <style>, slots (world / shape / over) and <script> calling M.scene
(reference/engine-api.md). The page that comes out runs on its own in any browser: open it to watch the clip loop, add
?t=2.4 to hold one frame; render.py loads it with ?render. An <img src="/abs/path.png"> (a screenshot, a logo) is
inlined as a data URI, so the page never depends on where it is opened from. Nothing is fetched.

Theme: the `## motion-graphics` section of user/preferences.md, lines like
    - background: #101418        - accent: #ff6a00        - font: Inter
    - card: #1b2027              - accent2: #2bb3a3       - mono font: JetBrains Mono
    - pill: #262c35              - highlight: #ffd400     - brand: My Channel
    - text: #ffffff              - muted: #8d939c
(any other bullet there is a free-text preference for Claude, not for this script). --theme FILE takes a JSON
{"colors": {"bg": ...}, "font": ..., "mono": ..., "brand": ...} instead. Colours must be #rrggbb. A font must be
installed on this computer; the system font is the fallback. --out defaults to ../dist beside the clips folder.

Look: <motion>/look.json (beside the clips folder, or --look) is ONE video's look, laid over the theme: its colours by
role, faces (a font file in the project is inlined), the shape's shadow, springs and swap blur (reference/look.md).
Every clip of the video gets the same one. A look whose text is under 4.5:1 on its surfaces is refused.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine"
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "tools"))
CURSOR = ('<svg id="cursor" viewBox="0 0 40 56"><path d="M3 3 L3 41 L12.5 32 L19 47 L25.5 44.2 L19.2 29.8 L32 29.8 Z" '
          'fill="#0B0B0B" stroke="#fff" stroke-width="2.6" stroke-linejoin="round"/></svg>')
KEYS = {"background": "bg", "bg": "bg", "canvas": "bg", "card": "card", "pill": "pill", "text": "ink", "ink": "ink",
        "text2": "ink2", "muted": "muted", "grid": "grid", "accent": "blue", "accent1": "blue", "accent2": "orange",
        "accent3": "aqua", "accent4": "yellow", "red": "red", "highlight": "ring", "ring": "ring", "light": "light"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
LOOK_KEYS = {"source", "line", "banned", "colors", "fonts", "shadow", "springs", "blur"}
SPRINGS = {"MORPH", "FAST", "SLOW", "SOFT", "CAM"}


def engine_palette():
    """The engine's default colours by role (M.C in engine/motion.js), plus accent."""
    js = (ENGINE / "motion.js").read_text(encoding="utf-8")
    pal = dict(re.findall(r"(\w+):'(#[0-9a-fA-F]{6})'", re.search(r"M\.C = \{(.*?)\};", js, re.S).group(1)))
    pal["accent"] = pal["blue"]
    return pal


def contrast(a, b):
    """WCAG contrast ratio of two #rrggbb colours."""
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_contrast(theme, what, fatal):
    """Text must read on the surfaces that carry it. A look is refused; a preferences theme only warns."""
    pal = engine_palette()
    colors = theme.get("colors", {})
    pal.update(colors)
    if "accent" not in colors:
        pal["accent"] = pal["blue"]
    for surface in ("bg", "card", "pill"):
        ratio = contrast(pal["ink"], pal[surface])
        if ratio < 4.5:
            msg = f"{what}: text {pal['ink']} on {surface} {pal[surface]} is {ratio:.1f}:1 - it needs 4.5:1 on bg, card and pill"
            if fatal:
                sys.exit(msg)
            print("WARN " + msg, file=sys.stderr)
    for k in ("accent", "ring"):
        if contrast(pal[k], pal["bg"]) < 3 and contrast(pal[k], pal["card"]) < 3:
            print(f"WARN {what}: {k} {pal[k]} is under 3:1 on both bg and card - it will not read as the focus", file=sys.stderr)


def apply_look(theme, path):
    """Lay one video's look.json over the theme. The prose keys (source, line, banned) stay in the file."""
    path = Path(path)
    look = json.loads(path.read_text(encoding="utf-8"))
    bad = set(look) - LOOK_KEYS
    if bad:
        sys.exit(f"{path}: unknown key(s) {sorted(bad)} - a look has {sorted(LOOK_KEYS)}")
    roles = engine_palette()
    for k, v in (look.get("colors") or {}).items():
        if k not in roles:
            sys.exit(f"{path}: colors has no role '{k}' - the roles are {sorted(roles)}")
        if not HEX.match(str(v)):
            sys.exit(f"{path}: colors.{k} is {v!r} - every colour is #rrggbb")
    bad = set(look.get("springs") or {}) - SPRINGS
    if bad:
        sys.exit(f"{path}: unknown spring(s) {sorted(bad)} - a look sets {sorted(SPRINGS)} as [stiffness, damping]")
    theme = dict(theme, colors=dict(theme.get("colors", {}), **{k: v.lower() for k, v in (look.get("colors") or {}).items()}))
    fonts = dict(look.get("fonts") or {})
    faces = []
    for f in fonts.pop("faces", []):
        p = Path(f["src"]) if os.path.isabs(f["src"]) else path.resolve().parent / f["src"]
        if not p.is_file():
            sys.exit(f"{path}: font file {p} not found - a face is a local file, never a web URL")
        faces.append({"family": f["family"], "src": str(p), "weight": f.get("weight", 400), "style": f.get("style", "normal")})
    theme["look"] = {"fonts": fonts, "faces": faces, "path": str(path),
                     **{k: look[k] for k in ("shadow", "springs", "blur") if k in look}}
    check_contrast(theme, str(path), fatal=True)
    return theme


def preferences_path():
    try:
        from vidkit import settings
        return settings.PREFERENCES_PATH
    except Exception:
        return REPO / "user" / "preferences.md"


def theme_from_preferences(path=None):
    p = Path(path) if path else preferences_path()
    theme = {"colors": {}}
    if not p.exists():
        return theme
    sec = re.search(r"^##\s*motion-graphics\s*$(.*?)(?=^##\s|\Z)", p.read_text(encoding="utf-8"), re.M | re.S)
    if not sec:
        return theme
    for line in sec.group(1).splitlines():
        m = re.match(r"^\s*[-*]\s*([A-Za-z][\w ]*?)\s*:\s*(.+?)\s*$", line)
        if not m:
            continue
        k, v = m.group(1).strip().lower(), m.group(2).strip().strip("`\"'")
        if k in KEYS:
            if HEX.match(v):
                theme["colors"][KEYS[k]] = v.lower()
            else:
                print(f"WARN preferences: '{k}: {v}' is not a #rrggbb colour - ignored", file=sys.stderr)
        elif k in ("font", "ui font"):
            theme["font"] = v
        elif k in ("mono font", "mono", "code font"):
            theme["mono"] = v
        elif k in ("brand", "brand name", "channel"):
            theme["brand"] = v
    return theme


def theme_css_js(theme):
    css = ""
    if theme.get("font"):
        css += f':root{{--font:"{theme["font"]}",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}'
    if theme.get("mono"):
        css += f':root{{--mono:"{theme["mono"]}","SF Mono",Menlo,Consolas,monospace}}'
    if theme.get("colors", {}).get("bg"):
        css += f'html,body,html:not(.alpha) body.preview{{background:{theme["colors"]["bg"]}}}'
    look = theme.get("look") or {}
    for f in look.get("faces", []):                     # inline_images turns the file into a data URI
        css += (f"@font-face{{font-family:'{f['family']}';src:url(\"{f['src']}\");font-weight:{f['weight']};"
                f"font-style:{f['style']}}}")
    for key, var in (("ui", "--font"), ("mono", "--mono"), ("display", "--display")):
        if look.get("fonts", {}).get(key):              # a look's faces are CSS font-family lists, used as written
            css += f":root{{{var}:{look['fonts'][key]}}}"
    if look.get("shadow") is not None:
        css += f":root{{--shadow:{look['shadow']}}}"
    th = {"colors": theme.get("colors", {}), "brand": theme.get("brand", "")}
    th.update({k: look[k] for k in ("springs", "blur") if k in look})
    js = "window.THEME=" + json.dumps(th).replace("</", "<\\/") + ";"
    return css, js


def inline_images(html, base):
    """src="..." / url(...) naming a local file -> a data URI (absolute, or relative to the fragment's folder)."""
    def data(path):
        p = Path(path) if os.path.isabs(path) else base / path
        if not p.is_file():
            return None
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

    def src(m):
        d = None if m.group(2).startswith(("data:", "http:", "https:", "#")) else data(m.group(2))
        return f'{m.group(1)}="{d}"' if d else m.group(0)
    html = re.sub(r'\b(src|href)="([^"]+)"', src, html)

    def url(m):
        d = None if m.group(1).startswith(("data:", "http:", "https:", "#")) else data(m.group(1))
        return f"url({d})" if d else m.group(0)
    return re.sub(r"url\(['\"]?([^'\")]+)['\"]?\)", url, html)


def build(src, dst, theme):
    frag = Path(src).read_text(encoding="utf-8")
    if re.search(r'https?://(?!www\.w3\.org/)', re.sub(r'<!--.*?-->', '', frag, flags=re.S)):
        print(f"WARN {Path(src).name}: names a web URL - a render must not depend on the network; save the asset "
              "locally and reference its path", file=sys.stderr)
    m = re.search(r"<title>(.*?)</title>", frag)
    title = m.group(1) if m else Path(src).stem
    css = "".join(re.findall(r"<style>(.*?)</style>", frag, re.S))
    js = "".join(re.findall(r"<script>(.*?)</script>", frag, re.S))

    def slot(n):
        s = re.search(rf'<div data-slot="{n}">(.*?)</div><!--/{n}-->', frag, re.S)
        if not s and f'data-slot="{n}"' in frag:
            sys.exit(f"{Path(src).name}: <div data-slot=\"{n}\"> needs its closing '</div><!--/{n}-->' marker")
        return s.group(1) if s else ""
    tcss, tjs = theme_css_js(theme)
    html = (f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>'
            f'<style>{(ENGINE / "base.css").read_text(encoding="utf-8")}{tcss}{css}</style></head><body>\n'
            f'<div id="wrap"><div id="stage"><div id="world">{slot("world")}<div id="shape">{slot("shape")}</div>'
            f'{slot("over")}</div>{CURSOR}</div></div>\n'
            f'<script>{tjs}</script><script>{(ENGINE / "motion.js").read_text(encoding="utf-8")}</script>'
            f'<script>{js}</script></body></html>')
    Path(dst).write_text(inline_images(html, Path(src).resolve().parent), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--theme", help="a theme JSON instead of user/preferences.md")
    ap.add_argument("--look", help="the video's look.json (default: look.json beside the clips folder)")
    ap.add_argument("--show-theme", action="store_true")
    a = ap.parse_args()
    if a.look and not Path(a.look).is_file():
        sys.exit(f"no look at {a.look}")
    theme = json.loads(Path(a.theme).read_text(encoding="utf-8")) if a.theme else theme_from_preferences()
    check_contrast(theme, "theme", fatal=False)
    if a.show_theme:
        print(json.dumps(apply_look(theme, a.look) if a.look else theme, indent=1))
        return 0
    if not a.clips:
        ap.error("give clip fragments to build")
    looks = {}
    for s in a.clips:
        out = Path(a.out) if a.out else Path(s).resolve().parent.parent / "dist"
        out.mkdir(parents=True, exist_ok=True)
        d = out / (Path(s).stem + ".html")
        look = Path(a.look) if a.look else Path(s).resolve().parent.parent / "look.json"
        look = look if look.is_file() else None
        if look not in looks:
            looks[look] = apply_look(theme, look) if look else theme
        build(s, d, looks[look])
        print(json.dumps({"built": str(d), "look": str(look) if look else None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
