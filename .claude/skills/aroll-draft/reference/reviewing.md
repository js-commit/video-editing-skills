# Reviewing a first cut

Load this for step 8-9 of the skill: handing the cut over and teaching the
user how to check it. Keep the teaching to a few lines unless they ask for more.

## What a first cut is (say it in a sentence or two)

The first cut keeps one good take of every sentence, in order, with the
retakes, false starts, mic checks and long silences removed. It is a starting
point for a person to watch, not a finished video: pacing, b-roll, music,
titles and color come after. The automatic cut is cautious: when unsure it
keeps material, so expect to trim a little more, rarely to restore.

## What to watch and listen for

- **Every seam** (each jump cut): no clipped first or last syllable, no breath
  cut in half, no doubled word.
- **Doubled or missing ideas**: a sentence said twice, or a step that vanished
  with a retake.
- **The review points** from the report (and the markers on a Resolve Studio
  timeline): clipped-word seams, very short clips, long pauses that may be dead
  air or a silent demo, and possible hidden retakes. These are the places the
  script could not decide alone.
- **Pacing**: does it breathe? If every seam feels rushed or slow, that is a
  preference to save (see tuning.md), not something to fix seam by seam.

## DaVinci Resolve (free or Studio)

Import (free version, or Studio when the timeline was not built by script):

1. Open or create a project (Project Manager), ideally an empty one.
2. **File > Import > Timeline...** (Mac **Cmd+Shift+I**, Windows/Linux
   **Ctrl+Shift+I**) and pick `<stem>.aroll.xml` next to the video.
3. In the import dialog keep "Automatically import source clips into media
   pool" ticked; in an empty project also tick "Automatically set project
   settings" so the frame rate matches the camera.
4. The timeline "<stem> first cut" appears in the media pool; double-click it.
   If clips show as offline (red), right-click them > Relink and point at the
   folder holding the video. The `.edl` is a fallback for other tools; the XML
   carries more and links more reliably.

Reviewing on the Edit page (default shortcuts):

| Key | Does |
|---|---|
| Space | play / stop |
| J / K / L | play backwards / stop / play forwards (tap L or J again to go faster) |
| Left / Right arrow | one frame back / forward |
| Up / Down arrow | jump to the previous / next cut |
| Shift+Z | zoom the timeline to fit |
| Cmd/Ctrl+B | razor: cut the clip under the playhead |
| A / B / T | selection / blade / trim edit mode |
| Backspace | delete the selected clip and leave a gap |
| Shift+Backspace (Shift+Delete on a Mac) | ripple delete: remove it and close the gap |
| M | add a marker |
| Cmd/Ctrl+Z | undo |

Trimming a seam: in trim mode (T), drag the edge of a clip to roll the cut
earlier or later; the rest of the timeline follows. Markers the script added
are listed in the Index panel (top-left of the Edit page, Markers).

Shortcuts can be changed in **DaVinci Resolve > Keyboard Customization** (Mac
**Cmd+Option+K**, Windows/Linux **Ctrl+Alt+K**), including presets that mimic
other editors. Remind the user of this once.

## EditReview (settings `review.app` = "editreview", macOS)

Open the preview MP4 (render it with `render_draft.py` if it does not exist)
in EditReview from `apps/edit-review`. The app shows its own keyboard keys; the
user leaves timestamped notes, which land in `<preview stem>.review/notes.json`
beside the render. The edit-review-notes skill turns those notes into changes.

## No editor (`editor.nle` = "none")

Play the preview MP4 in any player, note the times of anything wrong (times in
the first cut), and tell Claude: small fixes are edits to the revision or a
smooth_cuts flag and a re-run of steps 5-7. For b-roll and the finished video,
the talking-head-ffmpeg skill picks up `<stem>.aroll.tb.json` directly.
