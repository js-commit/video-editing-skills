#!/usr/bin/env python3
"""Clip fragments -> self-contained HTML pages (engine, page shell, cursor, the user's theme and local images inlined).

    build.py <motion>/clips/NN-name.html [...] [--out <motion>/dist] [--theme theme.json]
    build.py --show-theme                       # the theme the clips will get

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
    js = "window.THEME=" + json.dumps({"colors": theme.get("colors", {}), "brand": theme.get("brand", "")}) + ";"
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
    ap.add_argument("--show-theme", action="store_true")
    a = ap.parse_args()
    theme = json.loads(Path(a.theme).read_text(encoding="utf-8")) if a.theme else theme_from_preferences()
    if a.show_theme:
        print(json.dumps(theme, indent=1))
        return 0
    if not a.clips:
        ap.error("give clip fragments to build")
    for s in a.clips:
        out = Path(a.out) if a.out else Path(s).resolve().parent.parent / "dist"
        out.mkdir(parents=True, exist_ok=True)
        d = out / (Path(s).stem + ".html")
        build(s, d, theme)
        print(json.dumps({"built": str(d)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
