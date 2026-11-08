# Asset recipes (ffmpeg)

All examples assume a 3840x2160 timeline; halves are 1920x2160. Adjust
numbers for other frame sizes. Fonts: use `font=Helvetica Neue` (fontconfig
name; any installed sans-serif on Windows/Linux) — `fontfile=` pointing at a `.ttc` collection fails on homebrew ffmpeg
with a misleading "Either text, a valid file..." error. Pass label text via
`textfile=` to dodge quoting bugs.

Quality: every `scale=` in composite work gets `:flags=lanczos` (ffmpeg's
default bicubic visibly softens the punch-in upscales); intermediates stay
PNG end-to-end (no JPEG round-trips). The render restricts to 40000 kb/s
HEVC (about a mirrorless camera's own bitrate; hardware-decodable) — set in the
build script, not a preset.

## Title overlay PNG (transparent, per-half bottom labels)

```bash
ffmpeg -f lavfi -i "color=c=black@0.0:s=3840x2160:d=1,format=rgba" -frames:v 1 -vf "\
drawtext=font=Helvetica Neue:textfile=left.txt:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.60:boxborderw=22:x=(1920-text_w)/2:y=1960,\
drawtext=font=Helvetica Neue:textfile=right.txt:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.60:boxborderw=22:x=1920+(1920-text_w)/2:y=1960" \
title.png
```

The scene/variation banner does NOT go at the top of the frame (a banner up
there reads as a chyron and steals the eye): it is a small multi-line block centred between the
two labels on the same bottom row, bottom-aligned with them. The banner
below composes with the exact label values above — label boxes end at
y = 1960 + 64 (text) + 22 (border) ≈ 2046, so with its own boxborderw 16 the
banner uses `y = 2046 - 16 - text_h`; re-derive that if the label numbers
change:

```
drawtext=font=Helvetica Neue:textfile=banner.txt:fontsize=42:fontcolor=white:\
box=1:boxcolor=black@0.55:boxborderw=16:text_align=center:\
x=(3840-text_w)/2:y=2030-text_h
```

`banner.txt` holds one part per line (scene / lens / variation), and any
part containing " - " wraps at it - that keeps the block narrower than the
gap between the ultra-wide labels (the widest pair) at a readable size.
`text_align` needs ffmpeg 6+. Don't trust size estimates: render the widest
label pair + banner on transparent canvases, measure the alpha extents, and
after generating check every title has exactly three separate lit column
runs with 30 px+ gaps in the bottom band (alpha > 8, rows 1700-2160).

Zoom-range captions ("WIDE 1x -> 3x ZOOM"): use ASCII `->`. A Unicode arrow
`→` renders as a tofu box through drawtext + fontconfig Helvetica Neue. Also:
the freeze title carries lens labels too, so non-wide pairs need matching
freeze-title variants, not just video titles.

## Title overlay as video (for VIDEO segments)

Resolve pins PNG stills to the default still length and ignores their
endFrame, so titles that must span an arbitrary video segment are encoded as
a transparent ProRes 4444 clip, made once at max-segment length + slack and
trimmed per segment at append time. Every frame is identical, so encode ONE
second and extend by stream copy — ProRes is intra-only, so the loop is
lossless and frame-exact, and far faster than encoding the full length.
ProRes is encoded on the VideoToolbox hardware on a Mac (`ayuv64le` keeps the alpha); elsewhere
use `-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le`:

```bash
ffmpeg -loop 1 -i title.png -t 1 -r 30 -c:v prores_videotoolbox -profile:v 4444 \
  -pix_fmt ayuv64le one_sec.mov
ffmpeg -stream_loop -1 -i one_sec.mov -c copy -t 51 title_51s.mov
```

## Sharp freeze-frame selection (punch-in candidates)

Motion-blurred pause frames are useless. Extract candidates around the
nominal time and keep the sharpest — JPEG size at fixed quality is a cheap
sharpness proxy (blurry compresses smaller):

```bash
for dt in -1.5 -1.25 -1.0 -0.75 -0.5 -0.25 0 0.25 0.5 0.75 1.0 1.25 1.5; do
  t=$(echo "$T0 + $dt" | bc)
  ffmpeg -v error -ss $t -i clip.mp4 -frames:v 1 -q:v 2 -y "cand_${dt}.jpg"
done
ls -S cand_*.jpg | head -1   # sharpest candidate
```

Sweep BOTH cameras' clips at each dt and score by `min(size_left,
size_right)` so one blurry side disqualifies the instant; if the best dt
lands at the window edge, extend the sweep in that direction before
accepting it. Use the SAME chosen offset on both clips (after start
alignment) so the freeze shows the same instant. Then VIEW the winner: the
subject must be in frame and the moment representative. Extract the final
full-res frames as PNG (ffmpeg auto-applies rotation metadata -> portrait
comes out portrait).

## Side-by-side composite for still segments (freezes and photos)

One full-frame image per segment, title baked in; Resolve then places it
with no transforms. `CX` is the horizontal crop center IN SCALED PIXELS —
**center the punch-in on the subject**, not blindly on the middle: view the
frame, pick the subject x (and y), convert by the scale factor, clamp so the
window stays inside the image. Same center on both sides.

```bash
# portrait source W x H; fill scale s1 = max(1920/W, 2160/H); punch-in = 2*s1
ffmpeg -i left.png -i right.png -i title.png -filter_complex "\
[0]scale=iw*${S}:-1,crop=1920:2160:${CX}:${CY}[l];\
[1]scale=iw*${S}:-1,crop=1920:2160:${CX}:${CY}[r];\
[l][r]hstack[b];[b][2]overlay=format=auto" -frames:v 1 comp_A.png
```

(omit `:${CX}:${CY}` to center-crop — right for full photos, usually wrong
for punch-ins). For photos use `S = s1` (no punch-in), 5 s per segment.
`CX`/`CY` may differ per side when the two cameras framed the scene
differently — the SUBJECT is the anchor, not the frame coordinates.

Picking the subject point: view the frame with a 10% grid burned in
(`drawgrid=w=iw/10:h=ih/10:color=yellow@0.6:thickness=3`) and read off the
fractions — much more accurate than eyeballing an ungridded frame, especially
for dark subjects (a dark object on a dark floor). Then VIEW the composite; expect
to nudge 2-4 of them per batch.

## Landscape video pairs (pre-crop intermediates — FALLBACK ONLY)

The primary path for landscape sources is `left_win`/`right_win` in the job
JSON (SKILL.md §6): the build script places the window with native
Crop+Zoom+Pan, no intermediates, and the timeline stays tweakable. Use this
recipe only when a segment needs something the window transform can't
express (e.g. per-side filtering or speed changes baked into the source).
The problem it works around: at half-fill zoom a landscape source's full
width spills across the center seam. Pre-crop each side to a 1920-wide
window (subject-chosen x offset, full height) as a ProRes intermediate and
feed THOSE to the timeline; a 1920x2160 source hits half-fill zoom 1.0 with
zero spill:

```bash
ffmpeg -hwaccel videotoolbox -i left.mp4  -vf "crop=1920:2160:${XL}:0" -c:v prores_videotoolbox -profile:v standard -c:a copy left_crop.mov
ffmpeg -hwaccel videotoolbox -i right.mp4 -vf "crop=1920:2160:${XR}:0" -c:v prores_videotoolbox -profile:v standard -an      right_crop.mov
```

Freeze punch-ins from the FULL landscape frame: `s1 = max(1920/W, 2160/H)`
(= 1.0 for 3840x2160), punch-in `S = 2*s1` -> `scale=7680:-2`, then the same
1920x2160 subject-centered crop.

## Naming

Generated files that differ only by a digit (`freeze_1.png`, `freeze_2.png`)
get collapsed by Resolve's `ImportMedia` into ONE image-sequence clip. Use
letters: `comp_freeze_A.png`, `comp_freeze_B.png`, ...

## Verifying a claimed EXIF/SEF lens visually

Same scene from the same spot: ultra-wide shows ~2x more scene width than
wide; 3x tele shows ~1/3. If two paired frames show near-identical scene
coverage, they used the same lens.
