---
name: ffmpeg-to-resolve
description: Convert a finished talking-head-ffmpeg recipe into an editable DaVinci Resolve project - the keeps on V1 with their sound, the b-roll bricks on V2, graphics above, bins that separate used from unused footage - then prove the timeline is the ffmpeg draft, frame by frame and sample by sample. Use when asked to "convert this to Resolve", "move the ffmpeg edit into DaVinci", "open the recipe in Resolve", "I want to finish this by hand in Resolve", or to check a converted timeline against its draft. Needs DaVinci Resolve Studio 21.2 or later.
argument-hint: "<project or recipe_vN.json>"
allowed-tools: Read, Write, Edit, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../talking-head-ffmpeg/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *), Bash(open *)
---

# ffmpeg recipe -> Resolve timeline

**What it makes.** A talking-head-ffmpeg edit lives in one JSON file, the recipe, and ffmpeg renders it. That is fast
and repeatable, but some finishing is easier by hand: colour, a trim by eye, a transition. This skill rebuilds the
recipe as an ordinary DaVinci Resolve timeline made of the original clips, so every cut can be slipped, trimmed or
extended, and then measures that the timeline plays the same picture and sound as the ffmpeg draft.

Terms, the first time they matter (skip if preferences say the user is experienced):
- **Timeline / track**: Resolve's edit, in layers. V1, V2... are video tracks (higher covers lower), A1 is audio.
- **Bin**: a folder in Resolve's media pool, where the project's clips are listed.
- **Handles**: the unused frames of a clip before and after a cut. Original clips have them; a baked clip does not.
- **Baked clip**: a small pre-rendered clip that stands in for something Resolve's scripting cannot build.

It is **one way**. After the conversion Resolve is the edit and the recipe is history: changes made in Resolve do not
flow back. The user can keep editing the recipe and convert again later; each recipe version becomes its own timeline.

```
K=${CLAUDE_SKILL_DIR}/scripts            # python3; verify.py also needs numpy
T=${CLAUDE_SKILL_DIR}/../talking-head-ffmpeg/scripts
R=<work>/talking-head/recipe_vN.json     # the recipe to convert; it is only ever READ
J=<work>/talking-head/resolve/recipe_vN  # the job folder plan.py makes
```

## Before you start

1. Read `user/preferences.md`: `## general` and `## ffmpeg-to-resolve`.
2. `python3 tools/vidkit/settings.py get editor.nle` must be `resolve-studio`. The free version blocks external
   scripting, so there is nothing to build with: say so, and offer the XML/EDL that aroll-draft exports for the a-roll
   cut instead (the b-roll would be re-laid by hand).
3. Resolve Studio 21.2 or later (Help > About). The sub-frame audio placement this needs arrived in 21.1.2.
4. **Ask before converting a recipe the user is still editing.** Planning (step 1) is safe at any time; building makes a
   project in their Resolve library.
5. The recipe and the source media are never written. A recipe that changes after `plan.py` stops `verify.py` (its
   hash is in the job): plan again.

## 1. Plan (no Resolve)

```
python3 $K/plan.py $R [--project NAME] [--timeline NAME] [--exact-rates]     # -> $J/job.json + $J/luts/
```

The recipe must lint clean, and plan.py stops on any recipe key it does not know (`KNOWN`): a key that is skipped is an
edit that is lost without a word. When it stops, read what `render_recipe.py` does with the key, carry it or bake it
in plan.py, add a case to `fixture.py`, and only then convert. Read what it prints:
- `bakes`: what could not be a Resolve item (below). One or two per video is normal.
- `conformed`: slow-motion clips whose pool frame rate will be set to the timeline's.
- every `DEVIATION` line. These are the only places the timeline will not be the draft. Give them to the user word for
  word; do not soften them and do not add to them from memory.

| recipe | Resolve |
|---|---|
| `aroll` keep | video item on V1 (whole keeps: the a-roll runs on under the bricks), linked to its sound on A1 |
| `take_audio` | the separately recorded mic on A1 at `offset_s + rate * in_s`, a sub-frame source offset |
| `gain_db` | the sound item's Volume |
| `broll` brick | video-only item on V2, from the frame the renderer starts on (`render_recipe.seek()`) |
| `speed` | 59.94p at 0.4 on a 23.976 timeline: the pool clip is conformed (frame for frame). Any other speed: the item's Speed |
| `zoom`, `fit: cover` | Zoom + Pan + Tilt in the Inspector |
| `grade` | a `.cube` LUT from the renderer's own formula on the item's first colour node |
| zoom `to`, `fit: blur` | **baked** with the renderer's own filter (the scripting API has no transform keyframes and no blur amount); the original clip is in the pool beside it |
| `.mov` overlay | item on V3 (a second graphics track only where two overlap) |
| `.png` / `.webm` overlay | **baked** to a ProRes 4444 clip of its length (Resolve pins a still's length and does not read VP9 alpha) |
| `fade_out` | a **baked** black clip with the fade in its alpha on the top track, and a FadeOut on the last sound |
| `needs` | red NEED BROLL markers |
| `lufs`, the 6 ms seam fades, `voice_clear` | not on the timeline (deviations): loudness is set at delivery |

**Bins**: `a-roll/<folder>`, `b-roll/<folder>`, `graphics/<folder>`, each holding the clips the recipe uses, with an
`unused` bin inside it for every other media file in that footage folder, so everything is at hand for edits by hand.
Clips from the b-roll library or the NAS go in `b-roll/library`, another project's footage in `b-roll/from <project>`.
Nothing is copied: every clip is linked where it lives.

`--exact-rates` also bakes every brick whose clip runs at another rate than the timeline's (25 / 30 / 60 fps screen
recordings and stock at real time), for a frame-exact picture there too. Off by default: a baked brick is no longer a
source clip the user can slip or extend. Offer it; do not choose it for them.

## 2. Bake (ffmpeg)

```
python3 $K/bake.py $J/job.json            # -> $J/baked/
```

## 3. Build (Resolve running)

```
python3 $K/build.py $J/job.json [--replace]
```

Makes the project if it does not exist and ONE timeline named `<name> vN (ffmpeg)`. It refuses a name without that
suffix and a timeline that already exists (`--replace` rebuilds that one timeline). A project that already holds
timelines is exported to `$J/snapshots/*.drp` first, and a failed export stops the build: scripted edits are not in
Resolve's undo. Grade LUTs are copied into Resolve's own LUT folder under `ffmpeg-to-resolve/<project>/` (SetLUT
refuses a path elsewhere); tell the user that folder was written. It saves, re-reads every item from the saved
timeline, and writes `$J/build_report.json`. `ok: false` lists each row that is wrong. A 13-minute edit with 280 items
builds in about ten seconds.

## 4. Verify (the gate)

```
python3 $K/verify.py $J/job.json [--reference <draft.mp4>]    # -> $J/verify_report.json, $J/verify/
```

Resolve renders the timeline (resolve-export-draft's `render_draft.py`) and it is compared with the ffmpeg draft of the
same recipe: structure item by item, every frame's SSIM (a 0-1 similarity score) at the same frame and one frame either
side, and every keep's sound by cross-correlation. The reference defaults to where `render_recipe.py` puts the draft;
it must be newer than the recipe and have its frame count, or render the recipe again first. **Nothing is handed over
on `ok: false`.** Resolve's own render is deleted once measured (`--keep-render` keeps it).

Verdicts that pass: `ok`, `static`, and:
- `resampled`: a 25 / 30 / 60 fps clip at real time, or a Speed item. ffmpeg shows the nearest source frame, Resolve
  the earlier one. Same first frame, same length, some frames one SOURCE frame apart. A fast scroll reads that as a low
  SSIM, so these are judged on their first frame (the in-point) and on being the same shot. `--exact-rates` (step 1)
  makes them exact.
- `draft-late`: only with `--old-renderer`, for a draft rendered before `render_recipe.py` had `seek()`. Its seek,
  printed with 4 decimals, started some pieces one frame late (the picture one frame after the sound). Drafts from the
  current renderer have none; re-render an old draft instead of using the flag when you can.

Levels are compared in the legal range: the draft keeps a camera's super-white (a blown window at 255), Resolve's
delivery clips it at 235, and a screen shows the same white.

## When a row fails: the ladder

Read the row and its sheet in `$J/verify/` (draft on the left, Resolve on the right). Then, in this order:

1. **Run the step again.** A zero-length or missing item right after launch is Resolve's, and `build.py --replace`
   clears it. If the scripting server does not answer, the user saves and relaunches Resolve.
2. **`SHIFTED` / `EDGE` on one clip**: the job has the wrong frame, and it is almost always the FILE. Probe its streams
   (`ffprobe -show_entries stream=codec_type,start_time,time_base:format=start_time`): a picture that starts after the
   container does, a variable frame rate. Fix the model (`render_recipe.seek()`, plan.py's `lead`), never the timeline:
   a hand fix is lost at the next build and the fixture never learns it.
3. **`LAG` on every keep of one sound file by the same amount**: that file's stream start (`streams()["a_start"]`); an
   Apple AAC recording starts 0.044 s in. `LAG` on some keeps only: the sub-frame setters were refused or rounded
   (Resolve older than 21.2, or Preferences > User > Editing > "Align audio edits to frame boundaries" is on).
4. **`DIFFERENT` / `LEVEL`**: look at the sheet. Framing: `cover()` in plan.py. Washed out or crushed: the clip's Data
   Level in the pool (full-range phone recordings). A missing layer: the item's row in build_report.json.
5. **Something the API cannot do**: bake that one item (add the case to plan.py's bake list) and say so as a
   deviation. A baked clip is always exact because it is the renderer's own filter.
6. **Still wrong**: stop and show the user the row and the sheet. Do not hand over a timeline with a known mismatch
   described as fine.

A fix to plan.py or build.py is proved on the fixture before it touches a real project.

## The fixture (run it after every Resolve update)

```
python3 $K/fixture.py                                  # a synthetic project using every recipe feature once
F=<the "recipe" path it prints>                         # .../work/talking-head/recipe_v1.json
python3 $T/render_recipe.py $F
python3 $K/plan.py $F --project f2r-fixture && python3 $K/bake.py ${F%/*}/resolve/recipe_v1/job.json
python3 $K/build.py ${F%/*}/resolve/recipe_v1/job.json --replace && python3 $K/verify.py ${F%/*}/resolve/recipe_v1/job.json
```

Test patterns with the clip name and frame number burned in, noise for sound: two minutes, and a call whose behaviour
moved shows up on frames you can read. Expected on Resolve 21.2: 31 items, structure 0 wrong, 24 pieces (15 ok, 9
resampled), sound within 0.03 ms on every keep. It leaves a project named `f2r-fixture` in Resolve; say so.

## Hand over

- the project and timeline name, and that Resolve is now the edit (the recipe stays as history);
- verify's summary line, the `resampled` count, and every DEVIATION;
- what was baked and where the originals sit in the pool;
- the snapshot `.drp` if the project already existed;
- how to look around: Shift+Z fits the timeline to the window, the media pool's bins are on the left of the Edit page.

When the user states a lasting preference (always `--exact-rates`, a project naming rule), add a bullet under
`## ffmpeg-to-resolve` in `user/preferences.md` and say so.

## What Resolve 21.2's scripting API does (measured on macOS)

- `AppendToTimeline` lands whole-frame video ranges exactly, and rounds an AUDIO item's source start to a whole frame.
  `SetPosition`, `SetLeftOffset` and `SetRightOffset` with `subframePrecision=True` then place sound to a thousandth of
  a frame: append one frame short, slide by the fraction, pull both edges back. The render confirms it to one sample.
- A clip at another rate takes its source range in ITS OWN frames, and Resolve shows the EARLIER source frame where
  ffmpeg's `fps` filter shows the nearest. Reading the start back: `GetLeftOffset` is exact at the timeline's rate; at
  another rate use `GetSourceStartTime` x the clip's EXACT rate (60000/1001, not the "59.94" the pool reports) less the
  clip's Start TC (drop-frame when it has a `;`). `GetSourceStartFrame` reads one low on some items.
- **Resolve places a stream on the container's clock; ffmpeg counts from the stream's first sample.** An Apple AAC
  recording whose stream starts at 0.044 s (its encoder priming) plays 44 ms late unless that is added to the source
  offset. A clip whose picture starts at 0.0417 s shows black on its frame 0 and ffmpeg's frame k on k + 1. And
  ffmpeg's `-ss` counts from the CONTAINER's start, so the same clip with a sound stream at 0 seeks one frame
  differently from one without.
- `SetSpeed({"Percentage": 50})` on a real-time range doubles each frame from the same in-point, as ffmpeg's `setpts`.
- `SetFades` on video cannot span its whole item (29 asked, 28 set) and ends on full black; on audio its curve matches
  ffmpeg's `afade` to 0.1 dB.
- `SetProperties` is all-or-nothing and takes `AudioVolume` in dB. `SetLUT(1, path)` only takes a path inside
  Resolve's LUT folder, after `RefreshLUTList()`.
- `ImportMedia` with a list drops a file now and then (2 of 86, both on a network share); each imported alone.
- There are no transform keyframes, no blur amount on an effect, and a still's length is pinned.
- Resolve's delivery clips super-white at 235; a `.cube` grade clips colours outside the RGB gamut where `lutyuv` does
  not (visible on colour bars only).

Windows and Linux: the scripts choose Resolve's module and LUT folders for each system, but the measurements above
were made on macOS. Run the fixture first on another system and trust its report over this list.

## Scripts

| script | does |
|---|---|
| `plan.py` | recipe -> job.json: bins, items in whole frames, inspector values, LUTs, bakes, markers, deviations |
| `bake.py` | the job's bakes with ffmpeg: push-in and blur bricks, PNG / WebM overlays, the fade clip |
| `build.py` | job -> project, bins, one new timeline; save; read back; build_report.json |
| `verify.py` | structure + Resolve render vs ffmpeg draft (picture, sound); verify_report.json and failure sheets |
| `fixture.py` | the synthetic regression project |
