# The recipe (`recipe_vN.json`)

The whole edit as one JSON file: the ffmpeg counterpart of an editing timeline. It lives in
`<project>/<work>/talking-head/` (outside a project: `work/talking-head/` next to the take). `recipe_v0.json` is the bare
cut from `timeline.py`; every round writes a new `recipe_vN.json`, so the folder is the edit's history and any version
can be rendered again.

```json
{
 "name": "lamp-review",
 "project": "/abs/path/to/the/project",
 "fps": "30000/1001",
 "width": 3840, "height": 2160,
 "lufs": -14,
 "aroll": [
   {"file": "/abs/.../take-01.mp4", "in_s": 8.62, "out_s": 12.41},
   {"file": "/abs/.../fan-noise-phone.mp4", "in_s": 2.0, "out_s": 9.5, "gain_db": -6}
 ],
 "broll": [
   {"record_s": 44.4, "dur": 6.0, "file": "/abs/.../closeup.mp4", "in_s": 24.0, "speed": 0.4,
    "zoom": {"z": 1.3, "cx": 0.5, "cy": 0.4}, "fit": "cover",
    "why": "'thinner than the old one' - both lamps edge on"}
 ],
 "overlays": [
   {"record_s": 61.0, "dur": 4.0, "file": "/abs/.../price-tag.png", "fade": 0.2, "why": "'forty dollars' - price tag"},
   {"record_s": 80.0, "dur": 9.5, "file": "/abs/.../motion/out/02-side-panel.mov", "fade": 0, "why": "motion 02: ..."}
 ],
 "needs": [
   {"record_s": 140.6, "end_s": 152.0, "note": "the lamp at night - no shot of it lit in the dark"}
 ],
 "take_audio": {
   "/abs/.../take-01.mp4": {"file": "/abs/.../lav-recorder.wav", "offset_s": 2.2997, "rate": 0.99995859}
 }
}
```

## Clocks

- **Source time**: seconds inside a media file (`in_s`, `out_s`).
- **Record time**: the finished video's clock, the a-roll keeps laid end to end (`record_s`, `end_s`). The draft plays it
  1:1, so a review note's timestamp is a record time.
- Everything is snapped to the recipe's frame grid (`fps`, kept as a fraction so 29.97 never drifts) in one place,
  `recipe.flatten()`. The lint and the renderer both use it, so what passes the lint is exactly what renders.

## Fields

| field | meaning |
|---|---|
| `name` | output file stem: `<name>-draft-vN.mp4`, `<name>-final.mp4` |
| `project` | the project folder (finals go in its finals folder; files outside it get a WARN) |
| `fps`, `width`, `height` | the edit canvas: the first take's own rate and size. Drafts render smaller (settings `render.draft_height`), `--final` at this size |
| `lufs` | integrated loudness target (YouTube plays at about -14). True peak is held at -1.5 dBTP |
| `aroll[]` | the cut, in play order. Each keep plays `[in_s, out_s)` of `file`, picture and sound. `gain_db` levels a keep with its own sound (a phone clip, a voice-over insert) to the takes |
| `broll[]` | bricks: picture only, laid over the a-roll at `record_s` for `dur` seconds, playing `file` from `in_s`. The sound stays the a-roll's |
| `broll[].speed` | 1 = real time. 0.4 plays a 60 fps clip at 24 fps frame for frame (slow motion); it reads `dur x speed` seconds of the clip |
| `broll[].fit` | `contain` (default: scaled to fit, bars if the shape differs), `cover` (fills the frame, crops about the zoom focus), `blur` (the whole clip over a blurred copy of itself: a portrait phone clip without black bars) |
| `broll[].zoom` | `{"z", "cx", "cy"}`: z > 1 punches in (implies cover) toward the focus point (0-1). On a 4K source, z 2.0 is still full sharpness in a 1080p draft |
| `broll[].why` | one line: the words it covers -> what it shows. Notes rounds and the review worksheet read it |
| `overlays[]` | composited over whatever plays (talking head or brick). A PNG (frame-sized, RGBA) is held for the slot with an alpha fade of `fade` seconds; a `.mov` (ProRes 4444) or `.webm` (VP9) with alpha plays frame for frame from its start (`fade: 0`, it animates itself; must be at the recipe's fps and frame-shaped) |
| `needs[]` | spots that deserve b-roll the footage does not have. Never rendered; it becomes the shoot list |
| `voice_clear` | optional, only when the user asked for it: `{"variant": "studio"\|"natural", "sources": "all"\|[take files]}`. The voice-clear skill's dereverb runs over the joined a-roll; keeps from the listed takes play the cleaned sound, level-matched to the rest (Apple silicon Mac) |
| `take_audio` | a take's sound comes from a separately recorded mic, synced by `sync_audio.py`: `audio_s = offset_s + rate x take_s` |

## Lint rules (`recipe.py lint`)

- **Flicker (ERROR).** A visible run of talking head under 0.6 s beside a brick edge (a brick that starts or ends just
  off a jump cut), or under 1.1 s between two bricks. On screen these read as a flash. `--fix` stretches the neighbouring
  brick onto the cut when its clip has the frames to spare.
- **Structure (ERROR).** Overlapping bricks, a brick outside the timeline or reading past its clip's end, missing files,
  an overlay shorter than its fades or at the wrong fps / shape, a synced recorder that does not cover a keep.
- **Taste (WARN).** A brick under 1.5 s, two bricks reusing the same source range, a portrait clip left on `contain`, a
  file outside the project folder (move it in so archiving keeps it).

## Review sidecars (EditReview)

The render's review folder `<render stem>.review/` (format: `apps/edit-review/SPEC.md`):

- `notes.json`: written by EditReview while the user reviews; `review.py notes` reads it.
- `cuts.json` (schema `edit-review-cuts/1`): written by `render_recipe.py` after every render, from `flatten()`: every
  picture piece with `start_s`/`end_s`, `track` (1 a-roll, 2 b-roll), `source`, `source_start_frame`, and the brick's `why`.
  Overlays are listed under `overlays`.
- `changes.json` (schema `edit-review-changes/1`): written by `review.py changes` at the end of a notes round: one row per
  note of the previous round, on the new render's clock (`id`, `start_s`, `end_s`, `title` required; `kind`, `what`,
  `watch`, `note` optional; `start_s == end_s` marks a removal point).
