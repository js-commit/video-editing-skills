# EditReview

A small macOS app for reviewing a draft render hands-free. You watch the
video; the note field under it always has the keyboard focus. Spot something,
press SPACE to pause (or don't), type or dictate the note and press Return:
the note is stamped with the playhead time and playback carries on. No
tabbing to a notepad, no writing down timecodes.

The notes land in `<video>.review/notes.json` next to the render, and the
`edit-review-notes` skill turns them into timeline changes (in DaVinci
Resolve, or in a talking-head-ffmpeg recipe). When the next draft comes back,
EditReview shows **what changed** (purple bands, Option-Up / Option-Down to
step through them) so you review the changes instead of the whole video.

macOS 14 or later. Optional: the skills work without it (see
`docs/review-workflow.md` for reviewing with Resolve markers or any player).

> **Customize the keys.** Every review key can be changed without touching
> code: see [Customizing the keys](#customizing-the-keys). If a key clashes with
> your dictation app or your habits, change it; ask Claude ("change the
> EditReview shortcut for play/pause to ctrl+space") and the `customize`
> skill does it.

## Install

Nothing to compile. The repo ships a signed, notarized copy (macOS 14+, Apple
silicon and Intel):

```sh
open apps/edit-review/prebuilt/EditReview.app --args /path/to/draft.mp4
apps/install_apps.sh edit-review     # or copy it to ~/Applications and register it
```

## Build it yourself

Only if you change the source:

```sh
apps/edit-review/build.sh             # -> apps/edit-review/build/EditReview.app
open apps/edit-review/build/EditReview.app --args /path/to/draft.mp4
apps/edit-review/build.sh --install   # also copies it to ~/Applications
```

Needs the Swift toolchain: Xcode, or the Command Line Tools
(`xcode-select --install`). There is no Xcode project; `build.sh` calls
`swiftc`, draws the icon (`scripts/make_icon.swift`) and signs the bundle
ad hoc so it runs on your Mac without prompts. Nothing is installed unless
you pass `--install`, which copies the app to `~/Applications` and registers
it with Launch Services so Finder's "Open With" lists it. The app needs no
privacy permission (no microphone: your dictation app types into the field).

The bundle identifier is `io.github.js-commit.edit-review`; macOS keys the
app's settings and caches by it. If you maintain your own fork, change it in
`Info.plist` before you start relying on it.

### Optional: make it the default video player

Only if you want double-clicking a `.mp4` / `.mov` / `.m4v` in Finder to open
EditReview. Either use Finder (select a video, ⌘I, "Open with", EditReview,
"Change All…"), or, with the third-party `duti` tool, after `--install`:

```sh
duti -s io.github.js-commit.edit-review public.mpeg-4 all
duti -s io.github.js-commit.edit-review com.apple.quicktime-movie all
duti -s io.github.js-commit.edit-review com.apple.m4v-video all
```

## Dictation

Any dictation app that types into the focused text field works: macOS
Dictation (press the dictation key, or set a shortcut in System Settings >
Keyboard > Dictation), or a third-party app. Every EditReview key is one a
dictation app never types (SPACE only plays/pauses while the field is empty),
so dictated text goes into the note. If your dictation app's hotkey clashes
with a review key, rebind the review key.

## Opening a video

- **⌘O** opens the file panel in the folder the last video came from. In the
  panel, ⌘⇧G takes a typed or pasted path.
- **⌘⇧O** opens the path on the clipboard (Finder's ⌥⌘C "Copy as Pathname",
  a path from a terminal, or a `file://` URL).
- **File > Open Recent**, drag and drop onto the window, or a path argument.

Plays what AVFoundation plays: H.264 / H.265 / ProRes in `.mp4` / `.mov`.

## Keys

The note field is always focused; letters go into it. These are the
defaults (the in-app legend, **⌘/**, shows the keys actually in force).

**Review keys (customizable):**

| action name | default | what it does |
|---|---|---|
| `playPause` | SPACE | play / pause. With text in the field it types a space (multi-word notes) |
| `speedUp` | TAB | faster: 1× → 1.5× → 1.7× → 2× → 2.5× → 3× → 1× (pitch-corrected; audio may drop at 3×) |
| `speedDown` | ⇧TAB | the same list backwards |
| `seekBack` / `seekForward` | ← / → | 2 s. Paused with a note selected: move that note instead (the playhead follows) |
| `seekBackBig` / `seekForwardBig` | ⇧← / ⇧→ | 10 s (same note rule) |
| `frameBack` / `frameForward` | ⌃← / ⌃→ | one frame; hold to run (same note rule) |
| `halfSecondBack` / `halfSecondForward` | ⌃⇧← / ⌃⇧→ | ½ s (same note rule) |
| `zoomIn` / `zoomOut` | ⌃E / ⌃W | zoom the waveform and seek bar in / out around the playhead (down to 2 s across) |
| `previousCut` / `nextCut` | ↑ / ↓ | previous / next edit point, as in Resolve (needs cuts.json). Paused with a note selected: move the note there |
| `previousChange` / `nextChange` | ⌥↑ / ⌥↓ | previous / next change since the last render, played from 1 s before (needs changes.json) |
| `goToStart` / `goToEnd` | HOME / END | jump to the start / end |
| `deleteNote` | ⌫ / ⌦ | empty field + notes selected: delete them |
| `archiveNotes` | ⌘⌫ | archive the selected notes: kept, but left out of the export ("dealt with") |
| `undo` | ⌘Z | undo the last delete, add, archive or restore (empty field; otherwise it undoes typing) |
| `selectAllNotes` | ⌘A | select every note (empty field; otherwise it selects the field's text) |
| `find` | ⌘F | find in the transcript |
| `findNext` / `findPrevious` | ⌘G / ⇧⌘G | next / previous find hit, from anywhere |

**Fixed keys and menus:**

| key | what it does |
|---|---|
| ⏎ | stamp the field's text as a note at the playhead, clear the field, resume. Empty field + notes selected under *Previous cut*: bring them back to this cut |
| ESC | clear the field (with an empty field: close the find bar). In an inline note edit: hand the keys back to the note field |
| ⏎ / ⇧⏎ in the find bar | next / previous hit; ESC closes the bar |
| ⌥⏎ | in an inline note edit: a line break |
| ⇧-click / ⌘-click | select a range of notes / add one to the selection |
| ⌥-drag on the timeline | seek without snapping to cuts |
| scroll / ⇧scroll over the timeline | zoom around the pointer / move the window (a sideways trackpad swipe moves it too) |
| ⌘O / ⌘⇧O | open a video / open the path on the clipboard |
| ⌘⇧C | copy the live notes to the clipboard as JSON |
| ⌘/ | the keyboard legend |
| ⌘= / ⌘- / ⌘0 | bigger / smaller / default transcript and notes text (View > Text Size) |

### Customizing the keys

**No rebuild:** create
`~/Library/Application Support/EditReview/shortcuts.json` listing only the
actions you want to change, then quit and reopen the app:

```json
{
  "_comment": "keys starting with _ are ignored",
  "playPause": "ctrl+space",
  "zoomIn": ["ctrl+e", "cmd+="],
  "goToEnd": []
}
```

- A value is one key string or a list of them; `[]` unbinds the action.
- Key string: modifiers `cmd`, `ctrl`, `opt` (or `alt`), `shift` joined with
  `+` in front of one key: `space`, `tab`, `left`, `right`, `up`, `down`,
  `home`, `end`, `pageup`, `pagedown`, `delete` (⌫), `forwarddelete` (⌦), or
  one character (`e`, `=`, `/`).
- A plain character without cmd / ctrl / opt is refused (the note field
  always has focus, so it would eat your typing), and so are Return and ESC.
  Problems are listed in orange at the top of the ⌘/ legend; the default key
  stays in force.
- The seek steps (2 s, 10 s, ½ s) are constants in `Sources/Shortcuts.swift`.

**Change the defaults for good:** edit the key strings in the `table` at the
top of `Sources/Shortcuts.swift` (one row per action), update the table
above, and rebuild with `build.sh`.

**Menu shortcuts** (⌘O, ⌘/, ⌘⇧C…) are macOS menu items: rebind them in
System Settings > Keyboard > Keyboard Shortcuts > App Shortcuts, by menu item
name.

## The window

- **Timeline** (under the timecode): the audio waveform with a time ruler
  over the seek bar. Click or drag to seek; hover for the timecode and a
  thumbnail; an orange tick per note (click one to select it).
- **Clip strip** (with a cuts.json): one block per clip of the edit (main
  track grey, upper tracks teal, gaps dark), the clip under the playhead
  outlined and named next to the timecode, first and last frames at the
  block's ends and a filmstrip in between when zoomed in (⌃E). A click near a
  cut snaps to it (⌥ to avoid that); a snapped playhead lands a quarter frame
  inside the incoming clip, so a note stamped there belongs to that clip.
- **What changed** (with a changes.json): each change is a purple band over
  the waveform (a dashed line where something was removed), a numbered flag,
  and a row in the What changed pane with what was done, what to watch and
  the note it answers. Click a row or flag, or press ⌥↑ / ⌥↓, to play it from
  a second before. A change played to its end gets a ✓ (Review > Forget Which
  Changes Were Seen clears them).
- **Transcript** (side panel): the word being spoken is highlighted and kept
  in view; click a word or a paragraph's timecode to seek. Paragraphs break
  at pauses over 1.5 s. ⌘F finds forgivingly: case, accents, punctuation and
  spaces are ignored ("set up" finds "setup"), number words match digits
  ("five" finds "5"), the last word may be partial, and when nothing matches
  exactly it falls back to near misses (shown with ≈).
- **Notes** (side panel): click a note to pause and jump to it. The selected
  note expands and is editable in place; arrows then move it. Archived notes
  sit in their own section; notes from an earlier cut sit, dimmed, under
  *Previous cut*.

## Transcript

The transcript pane reads `<video>.transcript.json` next to the video, the
same sidecar every skill uses (format: `docs/transcription.md`). Without one,
the pane offers **Transcribe**, which runs the repo's
`python3 tools/transcribe.py <video>` with the engine you chose in setup
(`transcription.engine`). **Review > Transcribe When a Video Opens** does it
automatically (off by default, because your engine may be a paid cloud
service). A transcript made from an earlier version of the file is marked
**stale** and offers Re-transcribe; the old one is parked with that cut's
notes. Files on a network volume are never transcribed automatically.

The app finds the repo from its own place in it, and `apps/install_apps.sh`
records it for an installed copy. If you moved the repo, use **Review > Set Skills Repo Folder…**. The
transcript is optional: everything else works without it.

## Review data and caches

Notes autosave to `<video>.review/notes.json` after every change, made with
the first note. Formats: [SPEC.md](SPEC.md).

- **Same cut re-exported** (same length): every note is kept.
- **Different length** (a new cut under the same file name): the notes no
  longer line up, so they move to *Previous cut*, dimmed, with `≈` times. A
  click still seeks roughly there; ⏎ brings a selected one back to this cut.
- **Passes:** review, apply the notes, re-export, then select the notes you
  dealt with and archive them (⌘⌫). Archived notes stay visible but are left
  out of `export_review.py` and the skill.

Waveform, scrub thumbnails and cut thumbnails are cached in
`~/Library/Caches/<bundle id>/`, never next to the video; folders unused for
90 days are pruned at launch. Files on a network share do not build them on
open (every thumbnail would be a network read): click **Build** under the
empty waveform.

## Scripts

Python 3.9+, standard library (ffprobe through the repo's `tools/vidkit`).

```sh
# cuts.json for a render, from the open DaVinci Resolve (Studio) project, read-only:
python3 apps/edit-review/scripts/export_cuts.py draft.mp4 [--timeline NAME] [--project P]
# ...or from a segment list, for ffmpeg renders:
python3 apps/edit-review/scripts/export_cuts.py draft.mp4 --segments segments.json
# review.jsonl + markers.edl from notes.json; --to-resolve adds markers to the open timeline:
python3 apps/edit-review/scripts/export_review.py draft.mp4 [--to-resolve] [--clear-resolve]
```

**Review > Get Cuts from Resolve** in the app runs `export_cuts.py` for the
open video while the project is open in Resolve. Without `--timeline` it
takes the current timeline if its length matches the file, else the one
timeline that does (several: the one named in the file name), and refuses
when none does.

## Testing hooks

`EDIT_REVIEW_KEYS` posts real key events into the app's own queue, so
scripted runs go through the same path as physical keys:

```sh
EDIT_REVIEW_KEYS="wait:5,space,wait:1,type:jump cut,enter,space,dump,quit" \
  open -n -W --stderr /tmp/er.log apps/edit-review/build/EditReview.app --args draft.mp4
```

Commands: key names `space enter esc tab left right up down home end delete
z a e w f g` with `shift+` / `cmd+` / `ctrl+` / `opt+` prefixes,
`type:<text>`, `wait:<seconds>`, `seek:<seconds>`, `dump` (state and notes
to stderr), `quit`. Also: `EDIT_REVIEW_AUTO_TRANSCRIBE=yes|no` (force the
transcribe-on-open), `EDIT_REVIEW_ZOOM=<seconds>` (open zoomed in),
`EDIT_REVIEW_REPO=<path>` (the repo to run scripts from),
`EDIT_REVIEW_SHORTCUTS=<path>` (another shortcuts.json).
