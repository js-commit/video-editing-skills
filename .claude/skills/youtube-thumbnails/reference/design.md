# Thumbnail design rules

## Formats and what the feed hides

| Target | Canvas | Keep text and subject inside | Why |
|---|---|---|---|
| Long-form | 1280x720 | the frame minus 64 px; bottom-right corner clear | The duration badge covers the bottom-right corner; TVs and embeds trim edges |
| Short | 1080x1920 | the centred 1080x1350 band (5:4) minus 90 px | Home and subscription feeds crop a Short's tile to about 5:4 |

Both must be under 2 MB, JPG or PNG. `compose_thumbnail.py` builds the exact canvas,
fits the text into the safe zone and re-encodes under the cap. `--guides` draws the
zones (`_guides.jpg`) and a feed-size preview (`_feed200.jpg`). Look at both.

When nobody says which format, `thumb_pool.py info` reads it from the video's shape
(rotation included): taller than wide -> `short`.

## Picking the image

- **It must read at feed size.** Judge at about 200 px wide (contact-sheet tiles are
  close). A shot that only works full screen is a bad thumbnail.
- **On-message beats pretty.** The frame must contain the thing the video is about. For
  a camera comparison, the camera bumps beat a prettier shot of two lit home screens.
- **The subject recognisable:** fronts, screens lit, facing the camera; never just the
  back of a device. For a comparison, ideally both subjects in one frame, clearly
  different.
- **One focal point, clean background, strong separation** (light on dark or dark on light).
- **Out:** motion blur, half-closed eyes, mid-word mouths, odd hand poses, the shooter's
  reflection in a screen. The sampler catches blur, not expressions: that's your look.
- **Crop on the subject.** Read the subject's x,y (0-1) off the frame and pass `--focus`.
  `--zoom 1.2` makes it bigger and lets it slide off-centre to open space for text.
- **Text beside a face:** put the title on the side the face isn't (`--align left|right`,
  `--column` for the strip width). If the user's preferences fix a face side, follow it.
- **A wide subject in a vertical canvas** (two products side by side in a 16:9 frame
  can't fit a 9:16 crop): `--subject x0,y0,x1,y1` scales that band to the canvas width
  over a blurred, darkened copy of the frame. Plain, dark backdrops hide the band's edge best.
- **Upside-down cameras:** the pixels are rotated, not just the metadata, so pass
  `--rotate 180`.

## Privacy retouches

- **Text on a lit screen** (notifications, calendar rows, a device or network name, a
  map route): `--fill-box x0,y0,x1,y1` paints it with the screen's own colours around it.
  A blur on a dark screen leaves a grey smear that looks worse than the text.
- **Printed text on a device back or a label** (serial numbers, IMEI, barcodes):
  `--blur-box x0,y0,x1,y1`.
- Coordinates are 0-1 in the source frame (after `--rotate`), one box per text line;
  tilted text needs a box covering the slant. Prefix `2:` for the `--split` frame.
- Find coordinates on a zoomed crop of the source, then check the composite at full
  size: a tilted device moves the text and a hand-placed box can miss by a few pixels.
- A screen whose interface reads sideways or upside-down disqualifies the frame;
  that isn't fixable with a box.

## Titles

- **3-5 words in total, 1-3 lines,** capitals. The thumbnail text is a hook, never the
  video title again. Add what the image can't show ("WEEK 2 VERDICT", "$300 CHEAPER");
  don't restate what it does.
- **Condensed bold fonts** (DIN Condensed, Impact, Bebas Neue, Oswald) set a 1-3 word hook
  roughly half again bigger than a wide heavy font in the same width, which is what reads
  at feed size. A heavy wide font (`--font heavy`) suits a longer 2-3 line title.
- White with a thick black outline and a soft shadow; one accent line (default yellow)
  for the pivot word: the verdict, a number, "VS".
- **No thin glyphs.** A thin arrow or a light font weight vanishes at 200 px. Use "VS",
  a split, or a heavy word instead.
- Text must not cover the subject. Move it (`--pos top|center|bottom`, `--align`); if no
  clean area exists, pick another frame rather than shrink the text.
- `--scrim auto` darkens behind the text on busy frames; `--scrim none` on a clean wall
  or sky where the gradient would show.

## Labels and splits

- `--label "TEXT@x,y"` names each subject of a pair (canvas coordinates, 0-1). After
  composing, check every label sits beside the subject it names: a label next to the
  wrong product is a publish-regret fault.
- `--split B.jpg`: each half cropped around its own `--focus` / `--focus2`, an accent
  divider between them (stacked top/bottom on a Short). One word or number per side as
  labels, "VS" as a small centred title (`--max-size ~110` on landscape) that doesn't
  cover either subject.

## A set of thumbnails

- Same style (font, colours, accent position, corner logic for labels), distinct images.
  Byte-identical bases across a set read as duplicates in the feed.
- One font size: compose the longest title first, read `title_px`, pass it as
  `--max-size` to the others (it pins the size whenever the text fits).
- Several videos from one shoot (Shorts from one long video): matching poses from the
  same scene are ideal, but a different frame per video.
