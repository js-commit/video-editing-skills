# Identifying device and lens from file metadata

Worked out on two Samsung phones of different generations. Other Samsungs behave the same; other brands vary but the
*method* (exiftool deep dump -> corroborate -> visual check) carries over.

## Videos (MP4)

ffprobe shows NO model tag on Samsung videos. Use exiftool:

```
exiftool -a -G1 -s <file>.mp4
```

- `[UserData] Author` — e.g. `Galaxy Z Fold<N>`, `Galaxy S<N>` (the jackpot)
- `[Samsung] SamsungModel` — e.g. `SM-F9xx`, `SM-S9xx`
- `[Keys] AndroidVersion` — corroborates when two phones run different versions
- `[Keys] SamsungAndroidUtcOffset` — converts `creation_time` (UTC) to local
- `location` / GPSCoordinates — confirms same-place shooting

### Video lens

Newer Samsung camera apps write a SEF trailer the standard tools cannot
extract; parse the file tail bytes directly (read last ~400 KB, regex):

- `lens` block: bytes like `lens\0\0\0\0\x02\0\x17\0\x17\0` — `0x17` = 23
  (mm equiv), i.e. wide 1x.
- `cami` block: CSV string like `3, 2, 2445, -112, 1.0` — the LAST field is
  the capture zoom ratio at record start, and the SECOND field is a lens id:
  `2` = wide, `3` = ultra-wide, `4` = telephoto (verified across a shoot's clips:
  `2 … 1.0`, `3 … 0.6`, `4 … 3.0` in perfect agreement). So a
  shooter who cycled lenses on video is caught even when the filename says
  nothing — don't assume video pairs are wide 1x.

Older camera apps write NO lens info into videos at all. Then:
verify by FOV comparison against the paired clip / a photo with known EXIF
lens, on extracted frames. Only caption what was verified — and check
start/mid/end frames: the SEF zoom covers the start of the clip only, so a
mid-clip zoom must be caught visually and the caption split or ranged.

### Frame-rate lie

Some phones' 4K clips can report `r_frame_rate=120/1` in the container while really
being ~30 fps VFR (`[Track1] VideoFrameRate` shows the truth, e.g. 29.85).
DaVinci Resolve imports them correctly (~29.97); don't "fix" the fps.

### Rotation-tag lie (both phones)

Steep top-down (near-nadir) shots can latch a stale orientation: a clip shot
LANDSCAPE gets a spurious `rotation=-90` display matrix, and BOTH phones make
the same mistake simultaneously (seen on both clips of one pair). Top-down
content looks plausible in any rotation, so it slips past a casual glance -
judge from gravity cues (furniture legs, hanging fabric, readable text) on a
per-file frame, and verify with `ffmpeg -noautorotate` extraction: if the
"unrotated" frame is the upright one, the tag is bogus. Fix by stream-copy
remux: `ffmpeg -display_rotation 0 -i in.mp4 -c copy out.mp4` (verify stream
MD5 unchanged). A pair that flips to landscape needs cropped half
intermediates for the side-by-side (e.g. `crop=1920:2160:<x>:0` to ProRes),
since a landscape source at half-fill zoom 1.0 spills across the center seam.

## Photos (JPG)

Full EXIF: `Model`, `FocalLength`, `FocalLengthIn35mmFormat`, `LensModel`
(some models only), `DigitalZoomRatio`. Typical Samsung lens table:

| lens | 35mm equiv | notes |
|---|---|---|
| ultra-wide 0.6x | 13 mm | f/1.9-2.2 |
| wide 1x | 23 mm | main sensor |
| telephoto 3x | 69 mm | some models show DigitalZoomRatio=3 |

`Orientation` = 6 means portrait (rotate 90 CW); pixel dims stay landscape.
Samsung may also burn a corner watermark with the model name into photos —
free provenance in the comparison video.

## Screenshot fingerprint (when videos lack model tags)

Screenshots in the same dump reveal the device by screen resolution
(`sips -g pixelWidth -g pixelHeight`, or `ffprobe`): phone models differ in screen
resolution, so two phones' screenshots rarely match. Match dump -> device, then every camera file in that
dump inherits the identity.

## Import-dump heuristics

Phone imports usually land as one folder per import (a dated folder holding the
phone's camera roll, e.g. `DCIM/Camera/`). One phone may produce several dumps (a full roll + a fresh "just the new
clips" grab minutes later) — dedupe by filename + size; near-duplicates with
±1 s filenames and ~0.3% size difference are the SAME moment from DIFFERENT
phones, i.e. exactly the pairs being hunted.
