# Color basics

Two jobs, in this order: **correction** (make it look right and consistent:
exposure, white balance, contrast) then **grading** (a look or mood). Most
talking-head videos only need good correction.

## Words

- **Exposure**: overall brightness. **Contrast**: the spread between darks and
  brights.
- **White balance**: making white look white (no orange or blue cast).
  Temperature = blue-orange, tint = green-magenta.
- **Saturation**: how strong the colors are.
- **Log footage**: a flat, grey-looking recording mode (S-Log, V-Log, C-Log,
  Apple Log...) that keeps more highlight and shadow detail. It must be
  converted to normal (Rec.709) before it looks right.
- **LUT** (look-up table): a file that maps colors to other colors. A
  *technical* LUT converts log to Rec.709; a *creative* LUT adds a look.
- **Rec.709**: the standard color space for normal (SDR) video on the web.

## Scopes: trust them over your eyes

Open them on the Color page (Workspace > Video Scopes, or the scopes button
in the panel, in recent versions).

- **Waveform**: brightness from left to right of the frame; bottom = black,
  top = white. Keep the image between roughly 0 and 100 (or 0-1023): nothing
  crushed flat at the bottom or clipped flat at the top unless intended.
- **Parade**: the waveform split into red, green, blue. When something white
  or grey has the three at the same height, the white balance is right.
- **Vectorscope**: hue and saturation. Turn on the skin tone indicator: faces
  of every skin color fall near that line when the balance is right.
- **Histogram**: how many pixels at each brightness.

## Nodes

The Color page builds a grade from **nodes**, small boxes each holding one
adjustment, processed left to right.

- Add a serial node: ⌥S (Alt+S). Parallel: ⌥P. Layer: ⌥L.
- Turn the selected node off/on: ⌘D. Bypass all grading to compare: ⇧D
  (in recent versions).
- Label nodes (right-click > Node Label): "exposure", "WB", "look".
- A simple, robust tree: 1 balance (exposure, white balance), 2 contrast,
  3 saturation, 4 a window (power window) for the face if needed, 5 look.

## Primaries

The color wheels panel (Primaries):
- **Lift** (shadows), **Gamma** (midtones), **Gain** (highlights), **Offset**
  (everything at once). Drag the wheel's center to tint, the ring below to
  brighten or darken.
- Start with exposure (Offset or Gain/Lift) watching the waveform, then
  white balance (Temp/Tint, or the wheels) watching the parade, then contrast
  and saturation.
- Auto balance (the "A" button in the primaries panel, in recent versions)
  is a decent starting point.
- Match shots: grab a still of a good shot (⌥⌘G / right-click viewer > Grab
  Still), then compare with the split-screen wipe in the viewer.
- Copy a grade to other clips: select the target clips, then middle-click
  the source thumbnail (or, in the Color menu, Apply Grade from One Clip
  Prior); or save it as a still and apply it.

## Log footage

1. Know the camera's log profile and gamut (from the camera settings).
2. Convert to Rec.709, one of:
   - **Color Space Transform** effect on a node (Effects > Color Space
     Transform): input = camera gamut and gamma, output = Rec.709 / Gamma 2.4.
     Grade on a node *before* it for exposure/WB.
   - The camera maker's official **technical LUT** on a node.
   - **Color management**: File > Project Settings > Color Management >
     DaVinci YRGB Color Managed, then set each clip's input color space
     (right-click clip > Input Color Space).
3. Then correct as normal. Never stack a creative LUT on raw log: convert
   first.
4. Exposing log: follow the camera maker's guidance (often a little brighter
   than looks right); underexposed log gets noisy.

## LUTs

- Install: Project Settings > Color Management > Open LUT Folder, copy the
  .cube files in, then Update Lists.
- Apply: right-click a node > LUT, or drag from the LUT browser.
- Creative LUTs are strong: put them on their own node and lower the Key
  Output Gain (node's Key tab) to blend.

## Common mistakes

- Grading on an uncalibrated, very bright laptop screen at night: check on a
  phone too.
- Orange skin: too much saturation or warm white balance. Check the
  vectorscope's skin line.
- Crushed blacks/clipped highlights for "punch": watch the waveform.
- Different shots in one scene not matched: grab a still and compare.
