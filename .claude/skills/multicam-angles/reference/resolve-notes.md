# Resolve scripting notes for the angle pass

Load this when a `resolve_angle.py` subcommand fails or behaves oddly. These
are measured behaviours of the Resolve scripting API (Resolve 19-21).

## Why stacked tracks instead of a real multicam clip

The scripting API cannot create multicam clips. aroll-draft therefore lays
every keep on each camera's own tracks, already synced: camera A video on
V1 (audio A1), camera B on V2 (audio A2), every V2 clip disabled. Switching
a segment to camera B = enabling its V2 clip; PiP = V2 enabled plus a V3
clip of camera A over it. The result behaves like a multicam edit and the
user can still change any segment by hand (select the V2 clip, press `D`).

- Camera-A time for a V2 sample = `(left_offset + t) / fps + offset_s`,
  taken from the V2 clip itself, so it survives hand edits on V1.
- `offset_s` comes from the audio (aroll-draft's sync step). Never sync from
  file timestamps or `creation_time`: two cameras' clocks can be minutes or
  an hour apart, and even their start order can be wrong.
- Both cameras should run at the timeline's frame rate; `left_offset` is
  read in timeline frames.

## The user's own clips

- Users park their own clips on V3. `pip` only removes V3 clips whose record
  start equals a V1 segment start (ours by construction) and leaves the rest.
  `dump` lists V3 clips that are not ours (`v3_not_ours`): check before a pass.
- Record starts go stale whenever the user edits. Re-`dump` and re-`map`
  before `apply` / `pip`; `smooth` reads the live timeline itself.
- `backup` uses `Timeline.DuplicateTimeline`, which makes the copy current;
  the script switches back to the working timeline. Every subcommand refuses
  a timeline on `never_touch`.

## PiP, Fusion style (default)

`AddFusionComp()` on the V3 clip, then `comp.AddTool(id, -32768, -32768)`.
Tool ids that exist: `Background`, `Merge`, `Transform`, `RectangleMask`,
`Shadow`, `MatteControl`, `Crop`. Ids that do NOT: `Rectangle`,
`DropShadow`, `Resize`. Points are tables: `SetInput("Center", {1: x, 2: y, 3: 0})`;
wiring is `ConnectInput("Foreground", other_tool)`. Fusion coordinates are
normalised with the origin at the BOTTOM-left (the job's `face_box` uses a
top-left origin like an image; `angles.pip_geometry` converts).

- `Shadow.ShadowOffset` is an absolute screen point: (0.5, 0.5) is straight
  under the input, not (0, 0). The script adds 0.5 to the relative offset.
- `Background.Type` takes the label ("Solid", "Horizontal"...), not a number.
- Comp lifecycle: `DeleteFusionCompByName` refuses the comp that is loaded
  on the clip, and `AddFusionComp` loads the new one. Add + load the new comp
  first, delete the old ones after; otherwise comps pile up. `restyle`
  reports `clips_with_multiple_comps`.
- `GetInputList()` keys come back as numbers; to discover input names,
  export the comp (`item.ExportFusionComp(path, 1)`) and read the text.
  Inputs still at their default are omitted from the export.
- The clip's own Inspector transform applies AFTER the comp: do not mix the
  two PiP styles on one clip.

## PiP, Inspector style (`"style": "inspector"`)

`TimelineItem.SetProperty` with CropLeft/Right/Top/Bottom, ZoomX/Y, Pan,
Tilt. Crop values are in SOURCE pixels and stay glued to the image through
zoom and pan. No rounded corners or shadow this way (CropSoftness only
feathers the edge). **Positive Tilt moves the image UP; positive Pan moves
it right.** Never trust the corner math alone: render one frame with
`verify`, adjust, repeat (`pip.json` may carry an `"inspector": {...}`
block that overrides the computed values).

## Rendered-frame verification

`project.ExportCurrentFrameAsStill(path)` writes the exact rendered timeline
frame at full resolution, without UI, even with the screen locked. But it
works only on the Edit page, and it exports what the viewer currently
SHOWS: wait until `GetCurrentTimecode()` reads back the target, then let it
render (a fresh Fusion comp needs about 4 s; earlier exports came back as
the unmasked source). Do not verify with `GrabStill` (Color page, grabs the
clip source) or with property read-backs: they can read correctly while
the picture is wrong. The macOS fallback is a screenshot of Resolve's window.

Resolve timecode is integer-based: 23.976 fps counts 24 frames per timecode
second (the start frame 86400 shows as 01:00:00:00).

## Camera B geometry (aroll-draft runs this, reference only)

A camera mounted facing the speaker (e.g. overhead, pointing back at them)
films upside down relative to them: `transform job.json 2 props.json` with
`{"RotationAngle": 180.0, "ZoomX": 1.15, "ZoomY": 1.15}` rotates the whole
track and punches in past the table edge. Pick the zoom from one rotated
still (`ffmpeg -ss 30 -i camB.mov -vf hflip,vflip -frames:v 1 still.jpg`):
how much floor or table edge shows? If the subject sits low, add a positive
Tilt to move the image up. Pass `record_lt` when a single-camera section
was appended after the multicam region (it must not be rotated).

## Other traps

- Still images appended to a timeline get a fixed duration and ignore
  `endFrame`; for an overlay of exact length render a short alpha video
  (ProRes 4444) with ffmpeg and append that.
- `DeleteClips` works only on the Edit page; `vidkit.resolve.delete_clips_checked`
  switches pages and retries.
- "Scripting server not responding": Resolve's scripting server is stuck
  (happens after long sessions, no dialog on screen). The user saves and
  restarts Resolve; it answers about 25 s after launch.
