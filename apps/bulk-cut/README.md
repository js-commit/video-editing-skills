# BulkCut

A macOS app (SwiftUI + AVFoundation) for triaging a folder of footage and
photos from the keyboard. Go down the clips, trash the duds, crop the rest to
the parts worth keeping, turn sideways or upside-down ones the right way up,
zoom into the part of the picture that matters. Photos the same: trash them,
turn them 90° at a time, crop them. Then one Apply (⌘⏎, or ⌘S at once) does it
all, with no re-encoding except for zooms and photo crops.

It replaces "Finder at big icon size, Quick Look each clip, drag the duds to
the Trash, open the rest in an editor to trim."

Skills can also hand it work: a **review folder** of proposed ranges (salvage
picks, shots to check) that you correct with the same keys, and that the
skill reads back. See [Review folders](#review-folders-made-by-skills) and
[SPEC.md](SPEC.md).

macOS 15 or later. Optional: no skill needs it.

> **Customize the keys.** The defaults suit DaVinci Resolve users (Q / W are
> Resolve's ripple start / end with its Premiere Pro keyboard preset). Before
> your first session, change any key you won't remember or that clashes with
> your habits: in Settings (⌘,), or in a file, see
> [Customizing the keys](#customizing-the-keys). Or ask Claude ("make
> BulkCut's crop keys I and O") and the `customize` skill writes it.

## Install

Nothing to compile. The repo ships a signed, notarized copy (macOS 15+, Apple
silicon and Intel):

```sh
open apps/bulk-cut/prebuilt/BulkCut.app --args /path/to/folder
apps/install_apps.sh bulk-cut     # or copy it to ~/Applications and register it
```

## Build it yourself

Only if you change the source:

```sh
apps/bulk-cut/build.sh             # -> apps/bulk-cut/build/BulkCut.app
open apps/bulk-cut/build/BulkCut.app --args /path/to/folder
apps/bulk-cut/build.sh --install   # also copies it to ~/Applications
```

Needs the Swift toolchain: Xcode, or the Command Line Tools
(`xcode-select --install`). There is no Xcode project; `build.sh` calls
`swiftc`, draws the icon (`scripts/make_icon.swift`) and signs the bundle ad
hoc so it runs on your Mac without prompts. Nothing is installed unless you
pass `--install`, which copies the app to `~/Applications` and registers it
with Launch Services (Dock, Spotlight, Finder's "Open With").
`BULKCUT_BUILD_DIR=<folder>` builds somewhere else. The app needs no privacy
permission.

The bundle identifier is `io.github.js-commit.bulk-cut`; macOS keys the app's
settings, sessions and caches by it. If you maintain your own fork, change it in
`Info.plist` before you rely on it.

## Opening a folder

⌘O, drop a folder (or one video or photo in it) on the window or the Dock
icon, File > Open Recent, `python3 apps/bulk-cut/scripts/bulkcut.py open
<folder>`, or run `BulkCut.app/Contents/MacOS/BulkCut <folder>`.

## The window

- **Left, about 30%:** one row per video (`.mov` / `.mp4` / `.m4v`) and photo
  (`.jpg` / `.heic` / `.png` / `.tif` / `.gif` / `.bmp` / `.webp` / `.avif`) in
  Finder name order: a poster frame, the facts (duration, resolution, frame
  rate, codec, or a photo's size and format), the file size and what is staged
  for it. Drag the divider to resize the list; ⌘= / ⌘- change the thumbnail
  size.
- **Subfolders** (View > Include Subfolders, or the folder button above the
  list; on by default): after the folder's own files come each subfolder's,
  depth first, each under a header. ↑ / ↓ run straight through them. Hidden
  folders, packages, symlinked folders and `node_modules` are skipped.
- **Right:** the player, a timeline (waveform, ruler, kept ranges) and the
  transport. For a photo: the photo, turned and cropped as staged.
- **Notes** (⌘I): when the folder has a `bulkcut.json` from a skill, what it
  says about each clip (description, why it was picked, a privacy warning in
  orange, what a library already holds of it). Without one the panel stays
  empty.

## Keys

These are the defaults (⌘/ in the app shows the keys actually in force).

**Actions (customizable; the name is what `shortcuts.json` uses):**

| action name | default | what it does |
|---|---|---|
| `prevClip` / `nextClip` | ↑ / ↓ | previous / next clip (it starts playing if autoplay is on) |
| `selectAll` | ⌘A | select every clip (⌘-click / ⇧-click select several; a plain click or ↑ / ↓ selects one again) |
| `toggleDelete` | ⌫ | stage / unstage the clip (or every selected clip) for the Trash; ⌦ does the same |
| `copyPath` | ⌘C | copy the clip's absolute path (several selected: one a line) |
| `focusNext` / `focusPrev` | F / ⇧F | review folders: focus on the next / previous of Everything, each sequence, Picks only |
| `playPause` | SPACE | play / pause. Pausing turns autoplay off; playing turns it back on |
| `seekBack` / `seekForward` | ← / → | back / forward a little (1 s; Settings changes it) |
| `stepBack` / `stepForward` | ⌃← / ⌃→ | back / forward one frame |
| `jumpBack` / `jumpForward` | ⌘← / ⌘→ | back / forward a lot (5 s; Settings changes it) |
| `goStart` / `goEnd` | HOME / END | start / end of the clip |
| `speedUp` / `speedDown` | TAB / ⇧TAB | faster / slower: 1× → 1.5× → 1.7× → 2× → 2.5× → 3×, wrapping round |
| `sectionsOnly` | S | sections only on / off: play just the coloured stretches, jumping over the grey |
| `loop` | L | loop on / off: at the end, start over |
| `setIn` | Q | crop left: keep from this frame (Resolve: Ripple Start to Playhead) |
| `setOut` | W | crop right: keep up to this frame (Resolve: Ripple End to Playhead) |
| `prevEdge` / `nextEdge` | ⌥← / ⌥→ | previous / next crop edge |
| `removeRange` | ⌃⌫ | remove the kept range under the playhead |
| `clearRanges` | ⌃⇧⌫ | clear all crops on the clip |
| `turn` / `turnLeft` | R / ⇧R | rotate 90° right / left, losslessly (with several selected, all of them) |
| `clearZoom` | ⇧Z | clear the zoom (video) or crop (photo) |
| `zoomIn` / `zoomOut` | ⌃E / ⌃W | zoom the waveform and timeline in / out around the playhead; it then pages along as you play |

**Fixed keys, mouse and menus:**

| key | what it does |
|---|---|
| drag on the picture | zoom a video into that area, or crop a photo to it (hold ⇧ for any shape) |
| drag a range edge | move it frame by frame; onto its other edge deletes the range, onto the next range joins them |
| scroll / ⇧scroll over the timeline | zoom around the pointer / move along |
| ⌘Z / ⌘⇧Z | undo / redo any staging |
| ⌘⏎ | Apply, after a review sheet (in a review folder: finish the review) |
| ⌘S | Apply now, without the sheet |
| ⌘O / ⌘R / ⌘⇧R | open a folder / read it again / reveal the clip in Finder |
| ⌘= / ⌘- | bigger / smaller thumbnails |
| ⌘I | show / hide the notes panel |
| ⌘, | Settings: change the keys and the seek steps |
| ⌘/ | the shortcut list |

macOS uses ⌃← / ⌃→ to switch Spaces by default. If frame stepping does not
work, turn those off in System Settings > Keyboard > Keyboard Shortcuts >
Mission Control, or rebind the frame keys.

### Customizing the keys

**In the app:** Settings (⌘,), click an action's key and press the new one
(⎋ cancels). A key already in use moves to the new action. "Default" and
"Restore All Defaults" go back to the defaults. "A little" and "a lot" (the
seek steps) are set there too.

**In a file (no rebuild, easy to keep or share):** create
`~/Library/Application Support/BulkCut/shortcuts.json` listing only the
actions you want to change, then quit and reopen the app:

```json
{
  "_comment": "keys starting with _ are ignored",
  "setIn": "i",
  "setOut": "o",
  "zoomIn": "cmd+=",
  "loop": []
}
```

- A value is one key string; `[]` unbinds the action. (A list is accepted;
  only its first key is used: an action has one key.)
- Key string: modifiers `cmd`, `ctrl`, `opt` (or `alt`), `shift` joined with
  `+` in front of one key: `space`, `tab`, `return`, `esc`, `left`, `right`,
  `up`, `down`, `home`, `end`, `pageup`, `pagedown`, `delete` (⌫),
  `forwarddelete` (⌦), `f1`…`f12`, or one character: a letter, a digit, one of
  `-` `=` `[` `]` `;` `'` `,` `.` `/` `\`, or the backtick. Keys are matched by their place on a US keyboard
  (as Settings records them), so they stay put when you switch input language.
- A key given to an action is taken from any action that had it by default.
- These become the defaults: a key you set in Settings still wins, and
  Settings' "Default" buttons go back to the file's keys.
- Problems (unknown action, a typo in a key) are listed in orange in Settings
  and in the ⌘/ list; the built-in key stays in force.

**Change the built-in keys for good:** edit `builtIn` at the top of the
`Keymap` class in `Sources/Keymap.swift`, update the table above, and rebuild
with `build.sh`.

**Menu shortcuts** (⌘O, ⌘S, ⌘/…) are macOS menu items: rebind them in System
Settings > Keyboard > Keyboard Shortcuts > App Shortcuts, by menu item name.

## Cropping

Q and W set the edges of **kept ranges**. Whatever is outside every range is
greyed out on the timeline and dropped. Each range becomes its own file.

- On a fresh clip, Q crops from the left and W crops from the right.
- Inside a range, either key moves that range's edge to the playhead.
- In grey space, Q starts a new range and W ends one. So Q … W, then Q … W
  again, pulls several pieces out of one long clip.
- Q before the first range (or W after the last) without the other key
  extends that range.
- In points snap to the start of the frame on screen, out points to its end,
  so the frame you are looking at is kept.

**Sections only** (S) plays just the coloured stretches of a clip and stops
after the last; put the playhead in the grey by hand and the grey plays, so
you can still find something to keep. **Loop** (L) starts over at the end.

## Rotate and zoom

- **Rotate 90°** (R / ⇧R, or the buttons above the video). The player and the
  thumbnail show it at once. On Apply it is lossless: only the display matrix
  in the track header changes (like `ffmpeg -display_rotation`).
- **Zoom:** drag a rectangle on the video; the player zooms into it on
  release. It keeps the clip's shape unless ⇧ is held. Drag again inside a
  zoom to go further. ⇧Z clears it. A zoomed clip comes out at the area's own
  pixel size (a quarter of a 4K frame is 1920×1080), with no upscaling.

## Photos

- ⌫ stages a photo for the Trash. R / ⇧R turn it: a JPEG, HEIC or TIFF only
  has its orientation tag rewritten (no pixel is decoded); a PNG, GIF, BMP or
  AVIF is redrawn turned (PNG losslessly).
- Drag on the photo to crop it. The crop comes out at its exact pixel size in
  the photo's own format (PNG losslessly, JPEG and HEIC at 95% quality),
  keeping its metadata (date taken, location, camera). Animated GIFs and WebP
  files can only be trashed.

## Apply (⌘⏎, or ⌘S)

⌘⏎ opens a sheet listing every file going to the Trash and every crop, with
its timecodes and output names, before anything happens. ⌘S applies at once,
like a save, with the sheet's last Overwrite setting.

- **Deletes** go to the Trash, so they can be put back. A network share (SMB)
  has no Trash: there a delete is **permanent**; the sheet lists those apart,
  in red, and ⌘S asks first.
- **Crops** are passthrough exports: the compressed video and audio are
  copied, not re-encoded (same codec, bitrate and quality). Each piece starts
  and ends on the frame you chose (like QuickTime Player's Trim: the samples
  back to the previous keyframe ride along unseen).
- **Rotations** by 90° are passthrough too; a clip that is only turned is
  copied whole (an instant clone on APFS) as `name_rotated.ext`.
- **Zooms** re-encode at AVFoundation's highest quality in the clip's codec
  family: HEVC stays HEVC (10-bit and HDR too), ProRes stays ProRes, anything
  else becomes H.264.
- **Overwrite originals** (remembered): off, pieces are saved next to the
  original as `name_cropped.ext` (`_1`, `_2`, … for several); on, the original
  goes to the Trash and a single piece takes its name.
- Pieces keep the original's container and dates, so they sort where it did.
- Some cameras store gyro data in an extra metadata track; passthrough
  export does not copy it. Keep the originals if you stabilize with gyro data.

## Network shares

A NAS over SMB can take seconds to list a folder, so reading shows progress
(Stop works with what was found; ⌘R reads it all again), file headers and
thumbnails are read as rows come into view, waveforms wait for a click, every
cache stays on this Mac, and after Apply the list is updated in place.

## Review folders (made by skills)

A skill can stage clips for you to judge (salvage picks before they go into
the b-roll library, shots with a stranger in them for a home video) as a
folder with a `bulkcut.json` in review mode. Opening it:

- **Proposed ranges are already there**, in colour: purple for a pick, teal
  for a clip of a sequence, orange for what a library already holds (read
  only); yours are yellow. A legend sits over the timeline. Keep a range by
  leaving it, trim it by dragging its edges, remove it (⌃⌫, or drag an edge
  onto the other), add your own with Q / W. Files with nothing proposed may
  start "not kept".
- **The description box** under the clip's name shows the description of the
  range under the playhead and who wrote it. Click to type your own: Return
  saves, Esc cancels, ⌥Return adds a line; "Put it back" restores the tool's.
- **One sequence at a time:** F (or the chip beside Loop) focuses on one
  sequence end to end in beat order, or on the picks only; the rest is dimmed
  and skipped. Show All goes back.
- **Nothing in a review folder is trashed or trimmed.** Every change is saved
  to `bulkcut-review.json` in the folder as you go; the skill reads that.
  The toolbar button (⌘⏎) shows a summary and runs the skill's own command
  if it named one (the sheet shows the exact command first), or just says
  you are done.

The formats: [SPEC.md](SPEC.md). The helper script:
`scripts/bulkcut.py` (`stage`, `read`, `open`).

## Files

- Staged edits are autosaved per folder in
  `~/Library/Application Support/<bundle id>/sessions/`, so quitting halfway
  through a folder loses nothing. Nothing is written next to your footage
  except the crops themselves (and, in a review folder, `bulkcut-review.json`).
- Your key file: `~/Library/Application Support/BulkCut/shortcuts.json`.
- A debug log of every staged change, undo and Apply step goes to
  `$TMPDIR/BulkCut/<date>.log`, one file a day (Help > Show Debug Log).
- Waveforms and poster frames are cached in `~/Library/Caches/<bundle id>/`;
  folders unused for 90 days are pruned.
- `Sources/Waveform.swift`, `Timecode.swift` and `MediaCache.swift` are shared
  with `apps/edit-review`.

## Testing hooks

`BULKCUT_SHORTCUTS=<path>` reads another shortcuts.json.

## License

MIT, like the rest of this repository: see `LICENSE` at the repository root.
