# Shorts as DaVinci Resolve timelines

For DaVinci Resolve Studio users (`editor.nle` = `resolve-studio`) who want to
keep editing the short in Resolve. The free version blocks external scripting:
render with ffmpeg instead (the default path), then import the MP4 if wanted.

Enable scripting once: Resolve > Preferences > System > General > "External
scripting using" = Local. Resolve must be running with the project available.

## What `resolve_short.py create` builds

From the same spec the ffmpeg path uses, in the project that holds the long-form
edit, a NEW timeline `short - <slug>` at the spec's size (1080x1920 or 2160x3840)
and the long-form timeline's frame rate:

| track | holds |
|---|---|
| V1 | the picture; a stack's bottom pane; a fit shot's dimmed backdrop (Opacity 40) |
| V2 | a stack's top pane; a fit shot's picture |
| V3 | the captions: one transparent ProRes 4444 clip made by `make_short.py --captions-overlay` |
| A1 | the cut audio: one WAV made by `make_short.py --audio-only` (word-safe cuts, fades, loudness) |

Picture pieces come from the long-form timeline itself: the spec's times are
times in the long-form render, mapped onto the timeline (the render must start
at the timeline's first frame, or pass `--offset <seconds>`), and the clip under
each moment on the topmost enabled video track is reused with its source
in-point. B-roll from other files is imported into a `shorts` bin. Each clip is
placed with Crop + Zoom + Pan/Tilt so the chosen window fills its pane; the
values stay editable in the Inspector (the Inspector button at the top right of
the Edit page, Transform and Cropping sections).

## Order of operations

1. Ask the user to save; loading the project switches Resolve to it.
2. `snapshot` exports a `.drp` backup into the work folder (once per session,
   before the first `create`).
3. `create --dry-run` maps and prints every placement without changing
   anything; check that each piece found a clip (`clip`, `src_frame`).
4. `create` builds the timeline (it replaces an older timeline of the same name,
   and refuses any name not starting with "short"). Its last line compares the
   audio length with the picture: `MISMATCH` means re-check the spec, not trim.
5. `stills` exports the exact rendered frame at given seconds (it switches to the
   Edit page and back, and waits for the viewer to catch up before exporting).
   Read them in order, the hook first.
6. Render with `resolve_short.py render` (explicit H.265/H.264 MP4 settings, only
   its own render job, never clears the user's queue) or on the Deliver page
   (Shift+8). Before the first scripted render in a Resolve session, ask the user
   to check on the Deliver page that "Upload directly to YouTube" is unticked:
   after any YouTube preset it can stay on for the whole session, and scripts
   cannot see it. If the result says `resolve_uploaded_to_youtube`, tell the
   user at once. Then run `qc_short.py` on the file.

`create --prepare-only` renders just the WAV and the caption clip without
touching Resolve (useful while the user is mid-edit).

## Known limits (the scripting API, Resolve 19-21)

- No trim/slip setters on timeline items: every change is a rebuild (`create`
  again). That is cheap; edit the spec, not the timeline, until the structure is
  right, then polish by hand.
- A file re-rendered at the same path keeps its OLD length and picture in the
  media pool, silently. The script names the audio and caption files after the
  spec's content hash, so a changed spec always imports fresh files.
- The long-form's per-clip transforms, speed ramps and node grades are not copied;
  compound clips and generators are skipped (they have no file). Check the stills.
- A fit shot's backdrop is dimmed, not blurred (blur needs an effect the API
  cannot add): drag Effects > OpenFX > ResolveFX Blur > Gaussian Blur onto the V1
  clips by hand if wanted.
- Right after Resolve launches it restores its last project in the background;
  appends can return empty items in that window. The script retries; if `create`
  still fails, wait a few seconds and run it again.
- `ExportCurrentFrameAsStill` only works on the Edit page; `stills` handles it.
