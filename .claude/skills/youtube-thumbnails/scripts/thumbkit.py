#!/usr/bin/env python3
"""Shared helpers for the youtube-thumbnails scripts (standard library only).

- formats and safe zones (what the YouTube feed hides),
- finding a bold system font on macOS / Windows / Linux (nothing downloaded),
- reading a font's advance widths straight from the .ttf/.otf/.ttc file, so
  titles can be fitted without Pillow,
- small ffmpeg helpers: image size, mean brightness, saving a JPEG under the
  2 MB cap, and labelled contact sheets.

Run it to see which fonts it finds:  python3 thumbkit.py fonts
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media, settings  # noqa: E402

MAX_BYTES = 2_000_000          # YouTube's custom-thumbnail cap is 2 MB; stay just under
FORMATS = {"short": (1080, 1920), "landscape": (1280, 720)}
PIP_HINT = "python3 -m pip install Pillow"


# ---- geometry ---------------------------------------------------------------

def feed_crop(W: int, H: int) -> tuple:
    """y-extent of the ~5:4 band the home/subscriptions feeds show of a Short."""
    crop_h = round(W * 5 / 4)
    y0 = (H - crop_h) // 2
    return y0, y0 + crop_h


def badge_zone(W: int, H: int) -> tuple:
    """Bottom-right rectangle the duration badge covers on a landscape card."""
    return (W - 150, H - 84, W - 10, H - 10)


def safe_zone(fmt: str, W: int, H: int) -> tuple:
    """(x0, y0, x1, y1) that titles and labels must stay inside."""
    if fmt == "short":
        y0, y1 = feed_crop(W, H)
        m = 90
        return (m, y0 + m, W - m, y1 - m)
    m = 64
    return (m, m, W - m, H - m)


def overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def crop_box(sw: int, sh: int, W: int, H: int, fx: float, fy: float, zoom: float = 1.0) -> tuple:
    """Largest W:H box in an sw x sh frame (smaller by `zoom`), centred on the
    normalized focus point and kept inside the frame. Returns (x, y, w, h)."""
    target = W / H
    cw = min(sw, round(sh * target))
    ch = round(cw / target)
    if ch > sh:
        ch = sh
        cw = round(ch * target)
    if zoom > 1.0:
        cw, ch = round(cw / zoom), round(ch / zoom)
    cw, ch = max(2, cw), max(2, ch)
    cx = min(max(round(fx * sw), cw // 2), sw - cw + cw // 2)
    cy = min(max(round(fy * sh), ch // 2), sh - ch + ch // 2)
    return (cx - cw // 2, cy - ch // 2, cw, ch)


def norm_box(spec: str, sw: int, sh: int) -> tuple:
    """'x0,y0,x1,y1' (0-1) -> pixel (x0, y0, x1, y1), clamped and at least 2 px."""
    x0, y0, x1, y1 = (float(v) for v in spec.split(","))
    b = [round(min(x0, x1) * sw), round(min(y0, y1) * sh), round(max(x0, x1) * sw), round(max(y0, y1) * sh)]
    b = [max(0, min(sw, b[0])), max(0, min(sh, b[1])), max(0, min(sw, b[2])), max(0, min(sh, b[3]))]
    b[2], b[3] = max(b[2], b[0] + 2), max(b[3], b[1] + 2)
    return tuple(b)


def hex_rgb(color: str) -> tuple:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise SystemExit(f"colour {color!r}: use #RRGGBB")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


# ---- fonts --------------------------------------------------------------------

# File names in order of preference. "condensed" fonts set a 1-3 word hook much
# bigger in the same width, which is what reads at feed size; "heavy" ones suit
# longer titles. Both lists cover macOS, Windows and common Linux packages.
FONT_STYLES = {
    "condensed": [
        "DIN Condensed Bold.ttf", "Impact.ttf", "impact.ttf", "BebasNeue-Regular.ttf",
        "Bebas Neue.ttf", "Anton-Regular.ttf", "Oswald-Bold.ttf", "RobotoCondensed-Bold.ttf",
        "Arial Narrow Bold.ttf", "ARIALNB.TTF", "arialnb.ttf", "LiberationSansNarrow-Bold.ttf",
        "Ubuntu-C.ttf", "DejaVuSansCondensed-Bold.ttf", "NotoSans-CondensedBlack.ttf",
    ],
    "heavy": [
        "Arial Black.ttf", "ariblk.ttf", "ARIBLK.TTF", "seguibl.ttf", "NotoSans-Black.ttf",
        "Arial Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf",
        "NotoSans-Bold.ttf", "Ubuntu-B.ttf", "Roboto-Black.ttf", "Roboto-Bold.ttf",
    ],
}


def font_dirs() -> list:
    home = Path.home()
    dirs = []
    if sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts"),
                 Path("/Library/Fonts"), home / "Library/Fonts"]
    elif os.name == "nt":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs += [windir / "Fonts"]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft/Windows/Fonts")
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                 home / ".local/share/fonts", home / ".fonts"]
    return [d for d in dirs if d.is_dir()]


@lru_cache(None)
def installed_fonts() -> dict:
    """lower-case file name -> path, for every .ttf/.otf/.ttc in the font folders."""
    found = {}
    for d in font_dirs():
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    found.setdefault(f.lower(), Path(root) / f)
    return found


def _fc_match(pattern: str) -> Path | None:
    exe = shutil.which("fc-match")
    if not exe:
        return None
    r = subprocess.run([exe, "-f", "%{file}", pattern], capture_output=True, text=True)
    p = Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    return p if p and p.is_file() else None


def find_font(choice: str | None = None) -> tuple:
    """Resolve the title font. Order: `choice` (a path, 'condensed', 'heavy', or
    part of a font file name), then settings youtube.thumbnail_font, then the
    first condensed font installed. Returns (path, how-it-was-chosen)."""
    setting = settings.get("youtube.thumbnail_font")
    for value, origin in ((choice, "--font"), (setting, "settings youtube.thumbnail_font")):
        if not value:
            continue
        p = Path(os.path.expandvars(str(value))).expanduser()
        if p.is_file():
            return p, origin
        if str(value).lower() in FONT_STYLES:
            hit = _first_installed(FONT_STYLES[str(value).lower()])
            if hit:
                return hit, f"{origin} style {value}"
            continue
        want = str(value).lower().replace(" ", "")
        for name, path in sorted(installed_fonts().items()):
            if want in name.replace(" ", ""):
                return path, f"{origin} name match"
        print(f"note: font {value!r} ({origin}) not found; using the default", file=sys.stderr)
    hit = _first_installed(FONT_STYLES["condensed"] + FONT_STYLES["heavy"])
    if hit:
        return hit, "auto"
    hit = _fc_match("sans:bold")
    if hit:
        return hit, "fc-match sans:bold"
    raise SystemExit("No bold font found in the system font folders. Set one with:\n  python3 "
                     f"{Path(settings.__file__).resolve()} set youtube.thumbnail_font /path/to/font.ttf")


def _first_installed(names: list) -> Path | None:
    have = installed_fonts()
    for n in names:
        if n.lower() in have:
            return have[n.lower()]
    return None


class FontMetrics:
    """Advance widths and vertical metrics read from a TrueType/OpenType file
    (cmap format 4/12, hmtx, hhea, OS/2). Good enough to fit a title: kerning
    is ignored, which only makes the estimate a little wide (the safe side)."""

    def __init__(self, path: str | Path, index: int = 0):
        data = Path(path).read_bytes()
        off = 0
        if data[:4] == b"ttcf":
            n = struct.unpack(">I", data[8:12])[0]
            off = struct.unpack(">I", data[12 + 4 * min(index, n - 1):16 + 4 * min(index, n - 1)])[0]
        num = struct.unpack(">H", data[off + 4:off + 6])[0]
        tables = {}
        for i in range(num):
            rec = off + 12 + 16 * i
            tag = data[rec:rec + 4].decode("latin-1")
            t_off, t_len = struct.unpack(">II", data[rec + 8:rec + 16])
            tables[tag] = (t_off, t_len)
        self.data, self.tables = data, tables
        h = tables["head"][0]
        self.upm = struct.unpack(">H", data[h + 18:h + 20])[0]
        hh = tables["hhea"][0]
        self.ascender, self.descender = struct.unpack(">hh", data[hh + 4:hh + 8])
        self.n_hmetrics = struct.unpack(">H", data[hh + 34:hh + 36])[0]
        self.cap = int(self.upm * 0.70)
        if "OS/2" in tables:
            o, ln = tables["OS/2"]
            ver = struct.unpack(">H", data[o:o + 2])[0]
            if ver >= 2 and ln >= 90:
                cap = struct.unpack(">h", data[o + 88:o + 90])[0]
                if cap > 0:
                    self.cap = cap
        self.cmap = self._read_cmap()
        hm = tables["hmtx"][0]
        self.advances = [struct.unpack(">H", data[hm + 4 * i:hm + 4 * i + 2])[0] for i in range(self.n_hmetrics)]

    def _read_cmap(self) -> dict:
        d = self.data
        c = self.tables["cmap"][0]
        n = struct.unpack(">H", d[c + 2:c + 4])[0]
        subs = []
        for i in range(n):
            pid, eid, so = struct.unpack(">HHI", d[c + 4 + 8 * i:c + 12 + 8 * i])
            fmt = struct.unpack(">H", d[c + so:c + so + 2])[0]
            subs.append((fmt, pid, eid, c + so))
        subs.sort(key=lambda s: (s[0] != 12, s[0] != 4))
        for fmt, _pid, _eid, o in subs:
            if fmt == 12:
                groups = struct.unpack(">I", d[o + 12:o + 16])[0]
                m = {}
                for g in range(groups):
                    start, end, gid = struct.unpack(">III", d[o + 16 + 12 * g:o + 28 + 12 * g])
                    if start > 0x2FFFF:
                        continue
                    for cp in range(start, min(end, 0x2FFFF) + 1):
                        m[cp] = gid + cp - start
                return m
            if fmt == 4:
                segx2 = struct.unpack(">H", d[o + 6:o + 8])[0]
                ends = struct.unpack(f">{segx2 // 2}H", d[o + 14:o + 14 + segx2])
                starts = struct.unpack(f">{segx2 // 2}H", d[o + 16 + segx2:o + 16 + 2 * segx2])
                deltas = struct.unpack(f">{segx2 // 2}h", d[o + 16 + 2 * segx2:o + 16 + 3 * segx2])
                ro_pos = o + 16 + 3 * segx2
                ranges = struct.unpack(f">{segx2 // 2}H", d[ro_pos:ro_pos + segx2])
                m = {}
                for i, (s, e, dl, ro) in enumerate(zip(starts, ends, deltas, ranges)):
                    for cp in range(s, e + 1):
                        if cp == 0xFFFF:
                            continue
                        if ro == 0:
                            gid = (cp + dl) & 0xFFFF
                        else:
                            p = ro_pos + 2 * i + ro + 2 * (cp - s)
                            gid = struct.unpack(">H", d[p:p + 2])[0]
                            gid = (gid + dl) & 0xFFFF if gid else 0
                        m[cp] = gid
                return m
        return {}

    def advance(self, ch: str) -> int:
        gid = self.cmap.get(ord(ch), 0)
        return self.advances[min(gid, self.n_hmetrics - 1)] if self.advances else self.upm // 2

    def width(self, text: str, size: float) -> float:
        return sum(self.advance(c) for c in text) * size / self.upm

    def cap_height(self, size: float) -> float:
        return self.cap * size / self.upm

    def descent(self, size: float) -> float:
        return -self.descender * size / self.upm


@lru_cache(None)
def metrics(path: str) -> FontMetrics:
    return FontMetrics(path)


# ---- ffmpeg helpers ---------------------------------------------------------

def ff_escape(value: str) -> str:
    """Escape a path/value for use as a filter option inside an ffmpeg filtergraph.

    Two parsers read it: the graph parser (special: , ; [ ] ' backslash) and then
    the filter's option parser (special: : ' backslash). Characters special to
    the option parser need a backslash that survives the graph parser."""
    out = []
    for ch in str(value).replace("\\", "/"):
        if ch in ":'":
            out.append("\\\\\\" + ch)
        elif ch in ",;[]":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def image_size(path: str | Path) -> tuple:
    info = media.probe(path)
    w, h = info["width"], info["height"]
    if not w or not h:
        raise SystemExit(f"{path}: not an image ffmpeg can read")
    if abs(info.get("rotation") or 0) in (90, 270):
        w, h = h, w
    return w, h


def ffrun(args: list, what: str = "ffmpeg") -> subprocess.CompletedProcess:
    cmd = [media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"] + [str(a) for a in args]
    r = media.run(cmd, capture_output=True)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace") if isinstance(r.stderr, bytes) else r.stderr
        raise SystemExit(f"{what} failed:\n{err.strip()[-2000:]}")
    return r


def mean_luma(path: str | Path, centre: float = 0.70) -> float:
    """Mean brightness (0-255) of the centre `centre` share of an image, where
    the subject sits. Whole-frame means can't tell a dim subject from a dark backdrop."""
    m = (1 - centre) / 2
    vf = (f"crop=iw*{centre}:ih*{centre}:iw*{m}:ih*{m},scale=16:16:flags=area,format=gray")
    r = ffrun(["-i", str(path), "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-"], "brightness probe")
    px = r.stdout
    return sum(px) / max(1, len(px))


def save_jpeg_under(src_args: list, out: Path, max_bytes: int = MAX_BYTES, vf: str | None = None) -> int:
    """Encode one frame to JPEG at the best quality that fits under max_bytes.
    src_args are ffmpeg input args (e.g. ['-i', 'in.png']). Returns the qscale used."""
    for q in (2, 3, 4, 5, 6, 8, 10, 13):
        args = list(src_args)
        if vf:
            args += ["-vf", vf]
        ffrun(args + ["-frames:v", "1", "-update", "1", "-pix_fmt", "yuvj444p", "-q:v", str(q), str(out)], "jpeg encode")
        if out.stat().st_size <= max_bytes:
            return q
    raise SystemExit(f"{out}: could not get it under {max_bytes} bytes")


@lru_cache(None)
def drawtext_ok() -> bool:
    r = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True)
    return " drawtext " in r.stdout


def drawtext(text_file: Path, font: Path | None, size: int, color: str, x: str, y: str,
             border: int = 0, border_color: str = "black") -> str:
    """A drawtext filter reading its text from a file (no escaping problems)."""
    parts = [f"textfile={ff_escape(text_file)}", "expansion=none", f"fontsize={size}",
             f"fontcolor={color}", f"x={x}", f"y={y}"]
    if font:
        parts.insert(0, f"fontfile={ff_escape(font)}")
    if border:
        parts += [f"borderw={border}", f"bordercolor={border_color}"]
    return "drawtext=" + ":".join(parts)


def contact_sheet(tiles: list, out: Path, cols: int = 4, tile_w: int = 480, tile_h: int | None = None,
                  strip: int = 44, per_sheet: int = 12) -> list:
    """Numbered/labelled contact sheets with ffmpeg only.

    tiles: [(image_path, label)]. Each tile is fitted into tile_w x tile_h with a
    black caption strip under it. Writes out (or out_01, out_02 ... when there
    are more than per_sheet tiles). Returns the sheet paths."""
    if not tiles:
        return []
    font = None
    try:
        font = find_font("heavy")[0]
    except SystemExit:
        pass
    if tile_h is None:
        w, h = image_size(tiles[0][0])
        tile_h = round(tile_w * h / w / 2) * 2
    sheets = []
    n_sheets = (len(tiles) + per_sheet - 1) // per_sheet
    with tempfile.TemporaryDirectory(prefix="thumbsheet-") as td:
        tdir = Path(td)
        for s in range(n_sheets):
            chunk = tiles[s * per_sheet:(s + 1) * per_sheet]
            for i, (img, label) in enumerate(chunk):
                txt = tdir / f"label_{i:03d}.txt"
                txt.write_text(label, encoding="utf-8")
                vf = (f"scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease,"
                      f"pad={tile_w}:{tile_h + strip}:(ow-iw)/2:(oh-{strip}-ih)/2:color=0x111111")
                if drawtext_ok():
                    vf += "," + drawtext(txt, font, round(strip * 0.6), "white", "10", f"{tile_h}+({strip}-th)/2")
                ffrun(["-i", str(img), "-vf", vf, "-frames:v", "1", "-update", "1",
                       str(tdir / f"tile_{i:03d}.png")], "contact-sheet tile")
            for i in range(len(chunk), cols * ((len(chunk) + cols - 1) // cols)):
                ffrun(["-f", "lavfi", "-i", f"color=c=0x111111:s={tile_w}x{tile_h + strip}",
                       "-frames:v", "1", "-update", "1", str(tdir / f"tile_{i:03d}.png")], "blank tile")
            rows = (len(chunk) + cols - 1) // cols
            dest = out if n_sheets == 1 else out.with_name(f"{out.stem}_{s + 1:02d}{out.suffix}")
            ffrun(["-framerate", "1", "-i", str(tdir / "tile_%03d.png"),
                   "-vf", f"tile={cols}x{rows}:padding=4:color=0x000000",
                   "-frames:v", "1", "-update", "1", "-q:v", "3", str(dest)], "contact sheet")
            for f in tdir.glob("tile_*.png"):
                f.unlink()
            sheets.append(dest)
    return sheets


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    if sys.argv[1:] == ["fonts"]:
        path, how = find_font()
        print(f"title font: {path}  ({how})")
        for style, names in FONT_STYLES.items():
            hit = _first_installed(names)
            print(f"{style:10} {hit or '(none installed)'}")
        print(f"Pillow: {'yes' if pillow_available() else 'no (ffmpeg engine; optional: ' + PIP_HINT + ')'}")
        print(f"ffmpeg drawtext: {'yes' if drawtext_ok() else 'NO - this ffmpeg was built without libfreetype'}")
    else:
        print(__doc__)
        sys.exit(0 if sys.argv[1:] in ([], ["-h"], ["--help"]) else 2)
