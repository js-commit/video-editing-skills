---
name: camera-ab-compare
description: Build a DaVinci Resolve A/B camera-comparison video from a dump of photos and videos shot on two cameras/phones - identify which device shot each file from metadata, find matching pairs (same scene, same moment), pick the usable window in each take, lay them side-by-side on a 4K timeline with camera/lens titles and 2x punch-ins, then render. Use when asked to "compare cameras/phones", build a "side-by-side" or "A/B comparison" video, or figure out "which phone shot this" from an import dump. Needs DaVinci Resolve Studio (scripting) for the build; the survey and pairing steps work without it.
argument-hint: [import-dump-dirs-or-work-dir]
allowed-tools: Read, Write, Agent, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *), Bash(ls *), Bash(mkdir *)
---

Turn a raw import dump (photos + videos from two cameras) into a rendered 4K side-by-side
comparison. Older/reference camera on the LEFT, newer/challenger on the RIGHT, consistently
throughout. Compare like with like only: same scene, same subject, same moment, matching lens.

**Hard rules**

- Every project lives under settings `paths.projects_dir` as its own folder (`new-project`
  skill, or `python3 tools/vidkit/settings.py project-dir <name>`): work files, assets and
  renders all inside it, never loose elsewhere. `ls` the projects folder before creating one:
  names are free-form, so this shoot may already have a project.
- MOVE source files out of the import dump into the project at organize time (§4), before
  Resolve imports anything, and only after the user has seen the exact list (every file, from ->
  to, new name, and any orientation fix) and said yes. Never touch non-project dump files.
  Orientation fixes are made on the files in the project's work dir, never in the dump.
- Never load a `YouTube - *` render preset (they carry a hidden upload-on-render checkbox).
  The build script sets the render format explicitly.
- Nothing is uploaded anywhere. Delivery target follows the REQUEST: the render lands in the
  project; copy it elsewhere (an external drive, a NAS) only when asked.
- Present the pairing table and segment plan to the user before building the Resolve project,
  unless they asked for the finished thing and said they'll review it at the end.
- Python packages: `clip_survey.py` needs numpy; `align_centers.py` and `verify_geometry.py`
  need numpy and opencv-python (`python3 -m pip install numpy opencv-python`; ask before installing).

## 1. Identify which device shot each file

Read [reference/metadata-detection.md](reference/metadata-detection.md). Summary:
`exiftool -a -G1` exposes `UserData:Author` and `Samsung:SamsungModel` in Samsung MP4s
(ffprobe shows neither); photos carry full EXIF (Model, FocalLength, LensModel); screenshots
in the same dump fingerprint the device by screen resolution. Other brands: `Make`/`Model`
in the container tags, else the lens table in the reference. Record the evidence: the
comparison is worthless if the sides are swapped.

## 2. Pair the files

Pair by filename timestamp (phones: `YYYYMMDD_HHMMSS` = recording start; simultaneous
handheld recordings differ by 0-2 s), similar duration, and same orientation. Photos pair by
timestamp AND lens (sessions typically cycle wide → ultra-wide → tele on both devices). Files
without a counterpart on the other camera are organized but excluded from the timeline. Note
per pair the head-trim needed to align starts (from the timestamp delta).

Contact sheets settle lens order fast (a wide → ultra-wide → tele run is unmistakable side by
side), and hands/walk-ins show up in the same pass:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/clip_survey.py sheets <outdir> <clip> ...
```

## 2b. Pick the usable window inside each clip

Takes are almost never usable end to end: the shooter walks in, talks, or reaches into a flat
lay. Do NOT eyeball this across a dozen clips.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/clip_survey.py windows --mode talking-head --length 7 <clip> ...
python3 ${CLAUDE_SKILL_DIR}/scripts/clip_survey.py windows --mode static-scene --runs <clip> ...
```

`talking-head` scores audio RMS (speech) plus deviation from the median frame (walking
in/out) and returns the quietest, stillest N seconds, which is what "just looking at the
camera, not talking" reduces to. `static-scene` drops the audio term and finds hands-free
stretches in a product/flat-lay shot.

Two traps the script handles: skin-tone detection cannot find hands over a wood table (wood
sits inside every standard YCbCr skin gate), and handheld top-downs drift constantly, so hand
events are separated from drift by MAGNITUDE (`--thresh`), not an absolute motion threshold.

When no window of the requested length exists, `--runs` gives the real clean stretches.
Prefer a genuinely shorter segment over looping a take: a loop cut on a near-static shot
reads as a glitch. Tell the user which segments came up short and why.

## 3. Verify every pair visually

Extract one aligned frame per clip (`ffmpeg -ss <t>`), hstack the pair, and LOOK at it: same
scene/subject, sides not swapped, FOV plausible for the claimed lens. Drop pairs that don't
match. This is also where video lens claims get settled when metadata is silent.

Also audit ORIENTATION per file (accidental upside-down / sideways shooting; one side of a
pair can be wrong while the other is fine): extract an orientation-applied frame per video,
build per-pair contact sheets, and have an `orientation-judge` agent (or view yourself) judge
each side from gravity cues (floors, furniture, posture). Fix the files in the work dir:
photos via lossless EXIF `Orientation` rewrite (exiftool), videos via stream-copy remux
(`ffmpeg -display_rotation <deg> -i in.mp4 -c copy out.mp4`), then re-extract and re-verify.
Mid-clip zoom check: compare start/mid/end frames per clip, but distinguish LENS ZOOM from the
shooter walking closer: a zoom scales the image with the viewing angle unchanged; walking in
changes perspective and shows identically on both phones.

## 4. Organize

MOVE the source files out of the import dump into the project work dir BEFORE importing
anything into Resolve: files left in the dump get confused with the next import. Move every
file from the shoot, unused takes included. First show the user the whole plan as a table
(source path -> new path with its new name, plus the orientation fixes from §3) and move only
on their yes; then remove the dump folders that are now empty (empty folders only).

Layout: `<work>/left-cam/` + `<work>/right-cam/` (real device slugs), files renamed
`pairN_HHMM_<device>_<lens>.{mp4,jpg}`. Write a README.md recording the device-identification
evidence, the pair table, the lens findings, and which dump each device dir came from.

## 4b. If media moves after Resolve has imported it

A late move takes every media-pool clip offline, and nothing announces it: the project opens
with the item count unchanged, and `Online Status` still reads "Online". The check that works
is `os.path.exists` on each clip's `File Path`. Repair the whole chain:

1. `mp.RelinkClips(clips, new_folder)`: ONE call per destination folder, matched by filename.
   Fall back to per-clip `MediaPoolItem.ReplaceClip(new_path)` only when the move also
   renamed. Include the title `.mov`s, not just camera sources.
2. `pm.SaveProject()` immediately: an unsaved relink is lost at the next project switch.
3. Rewrite the absolute paths in the job JSON and the project's own tooling.
4. Only now verify with §7's `stills` grab. LOOK at the frame: real pixels, not a slate.

## 5. Generate assets

Recipes with exact ffmpeg incantations: [reference/asset-recipes.md](reference/asset-recipes.md).

- **Title overlays**: per-half bottom labels naming device + lens ("PHONE A — WIDE 1x"). For
  video segments render the title as a transparent ProRes 4444 .mov (Resolve trims video
  precisely; it pins PNG stills to a fixed default length). Captions state the ACTUAL lens per
  segment: photos from EXIF per file; videos verified per clip; if the shooter zoomed or
  switched lens mid-clip, split the segment at the change or caption the range ("1x → 3x").
  Everything sits on the bottom row; the scene/variation context goes in a small multi-line
  block centred between the two labels. MEASURE the fit before committing (recipe + check in
  asset-recipes.md).
  - Native Resolve Text+ titles are scriptable (`tl.InsertFusionTitleIntoTimeline("Text+")`,
    then `item.GetFusionCompByIndex(1)` → the TextPlus tool's `SetInput`), but the API only
    inserts at the playhead on an auto-picked track, and an invalid Font/Style combo renders
    NOTHING silently (always set Style "Regular" together with Font). The overlay .movs stay
    the default.
- **Punch-ins: live or frozen.** Ask which shape the user wants.
  - *Live* (preferred for a static subject): repeat the SAME time window at successive zoom
    levels as ordinary video segments; each variation is just a smaller `left_win`.
  - *Frozen*: a 5 s paused 2x punch-in after each video pair. Only worth it when the subject
    moves and a held frame is the only way to compare detail. Pick a SHARP frame (candidates
    every 0.25 s within ±1.5 s; largest JPEG at fixed quality is a good sharpness proxy) and
    centre the punch-in ON THE SUBJECT, not the frame centre.
  - Consider opening each lens on the FULL uncropped frame before any cropped variation.
- **Still-segment composites**: freezes and photo pairs are pre-composited into single
  full-frame images (side-by-side + title baked in) with ffmpeg. Name generated files so they
  differ by LETTERS, not only digits (`ImportMedia` collapses digit-only-differing names into
  an image sequence).

## 6. Build the Resolve project

Resolve Studio must be running (macOS: `open -a "DaVinci Resolve"`, wait ~25 s; the process
is named `Resolve`). The asset recipes use macOS encoders and fonts (`prores_videotoolbox`,
Helvetica Neue); on Windows/Linux use `prores_ks` and a font you have, as noted in the recipes. Write a job JSON (schema in the script docstring) and run:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/build_ab_project.py create <job.json> [--fresh | --replace]
# --fresh replaces the whole Resolve project named in the job (after exporting it to
# <work>/resolve-backups/<name>-<time>.drp). Ask the user before using it.
# --replace: the job's timeline already exists. Without it, create refuses rather than
# delete it; with it, that timeline is deleted and rebuilt and any hand edits to it are
# lost. Ask first, or give the job a new "timeline" name.
```

Timelines with "backup" in the name, on settings `editor.never_touch_timelines` or on
the job's `"never_touch"` list are never rebuilt.

Left clip V1 (with its audio), right clip V2 (video only), title overlay V3; per-pair
zoom/pan fills each 1920x2160 half exactly. The script encodes the non-obvious Resolve API
behaviours (Pan units, still-duration cap, rotation-applied Resolution): read its docstring
before changing transform math.

LANDSCAPE pairs can't use the plain half-fill transform. Give those segments an explicit
source window: `"left_win": [sx0, sy0, sw, sh]` and `"right_win"`, in the clip's DISPLAY
pixels (rotation applied: read `stream_side_data=rotation` and swap dims when |rotation| is
90), plus `"win_mode": "fill"` (or `"fit"`). The build script warns when a job breaks the
bounds or the half's aspect (16:18 on a 4K timeline), because the result is a silent shift
or seam spill, not an error.

Aim both halves at the SAME physical point: detect the subject in the LEFT frame and map it
into the right (detecting each side independently doubles the disagreement at 2x):

```
python3 ${CLAUDE_SKILL_DIR}/scripts/align_centers.py --pairs pairs.json --centers centers.json --out aligned.json
```

The reported right/left scale doubles as a pairing check: genuine matched takes land within
a few percent of 1.0. A scale far off, or inliers in the low tens, means these two clips are
not showing the same thing; re-pair. **Do NOT use that scale to equalise the sides**; both
stay at native magnification or the comparison shows resampling instead of real detail.
Haar face detection fails on a tight telephoto (face too large, cropped at the top): sanity
check any detected face against the expected size; if implausible, read the position off a
gridded frame by eye (`drawgrid=w=iw/10:h=ih/10:color=yellow@0.6:thickness=3`).

If segments come out shifted or spilling across the seam, check the transform model before
debugging the job: `python3 ${CLAUDE_SKILL_DIR}/scripts/verify_geometry.py <landscape-clip>
<portrait-clip>` re-measures Resolve's Crop/Zoom/Pan/Tilt behaviour from grabbed stills.

## 7. Verify BEFORE the full render

```
python3 ${CLAUDE_SKILL_DIR}/scripts/build_ab_project.py stills <job.json> <outdir> <t1> <t2> ...
```

One still per video pair plus a freeze and a photo segment; LOOK at them: halves filled with
no spill across the centre seam, correct side, sync, titles right. The stills are the exact
rendered frames. (`ExportCurrentFrameAsStill` only works on the Edit page and exports what
the viewer currently shows, which lags `SetCurrentTimecode`; the script handles both.)

## 7b. Say what's imperfect

Report what the footage could NOT support rather than papering over it: segments that came
in short, pairs dropped, captions that had to generalise. The user can reshoot; they can't
fix what they weren't told about.

## 8. Render and deliver

```
python3 ${CLAUDE_SKILL_DIR}/scripts/build_ab_project.py render <job.json> <work>/render <name>
```

Renders mp4/H.265 (H.264 fallback) at timeline resolution into the project and
ffprobe-verifies duration. The scripting API cannot set the bitrate, so it is
whatever the Deliver page's Quality setting is (Automatic by default). Then ffprobe the OUTPUT for codec / resolution / fps / bitrate,
and spot-check 2-3 frames pulled from the rendered file itself. Give the user a contact sheet
of frames from the finished render plus the absolute path.
