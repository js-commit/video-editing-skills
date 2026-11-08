# Keyboard shortcuts

Editing is much faster from the keyboard. Learn a handful at a time; the ones
marked ★ pay off first.

Keys are shown for macOS. On Windows and Linux, ⌘ (Command) is **Ctrl** and
⌥ (Option) is **Alt**. ⇧ is Shift, ⌃ is Control, ⌫ is Backspace/Delete,
⌦ is forward Delete.

## DaVinci Resolve

Defaults in recent versions. Resolve shows every command's current key next
to it in the menus; trust that over any list (including this one), especially
after customizing.

### Customize the keyboard

DaVinci Resolve > **Keyboard Customization** (⌥⌘K; Windows/Linux Ctrl+Alt+K).

- **Presets** (menu at the top right): DaVinci Resolve, plus layouts modeled
  on Adobe Premiere Pro, Apple Final Cut Pro, Avid Media Composer and Pro
  Tools, for people coming from those apps. The Premiere preset follows an
  older Premiere layout, so check a few keys after switching.
- Search a command, click its key field, press the new key. Resolve warns
  about conflicts.
- Save your layout as a **new preset**, and export it to keep a backup or use
  it on another computer.
- Coming from Premiere Pro? Ask the editing coach for the Premiere-to-Resolve
  cheat sheet.

### Playback and navigation

| Key | Does |
|---|---|
| ★ Space | Play / stop |
| ★ J / K / L | Play backward / stop / forward (tap J or L again to go faster) |
| ★ ← / → | One frame back / forward |
| ⇧← / ⇧→ | One second back / forward |
| ★ ↑ / ↓ | Previous / next cut (edit point) |
| Home / End | Start / end of the timeline |
| I / O | Mark in / out |
| ⌥X | Clear in and out |

### Editing (Edit page)

| Key | Does |
|---|---|
| ★ ⌘B | Cut (split) the clip at the playhead |
| ★ ⇧⌫ (or ⌦) | Ripple delete: remove and close the gap |
| ⌫ | Delete, leaving a gap |
| ★ ⌘⇧[ / ⌘⇧] | Ripple start / end to playhead (trim and close the gap in one step) |
| ⇧[ / ⇧] | Trim start / end to playhead (no ripple) |
| A / T / B | Selection / Trim / Blade tool |
| N | Snapping on / off |
| ⌘⇧L | Linked selection on / off |
| D | Enable / disable clip |
| M | Add marker |
| ⌘T | Add a transition |
| F9 / F10 | Insert / overwrite from the source viewer |
| F | Match frame |
| ⌘R | Retime (speed) controls |
| ⌘= / ⌘- / ⇧Z | Zoom timeline in / out / to fit |
| ★ ⌘Z / ⌘⇧Z / ⌘S | Undo / redo / save |

On a Mac, F-keys may need fn, or turn on "Use F1, F2, etc. keys as standard
function keys" in System Settings > Keyboard.

### Color page

| Key | Does |
|---|---|
| ⌥S | Add a serial node |
| ⌥P / ⌥L | Add a parallel / layer node |
| ⌘D | Turn the selected node off / on |
| ⇧D | Bypass all grades (before / after) |
| ⌥⌘G | Grab a still (for comparing shots) |

### Pages

In recent versions ⇧2 to ⇧8 switch between pages (Media, Cut, Edit, Fusion,
Color, Fairlight, Deliver); Workspace > Switch to Page shows the keys for
your version.

## EditReview (macOS review app in this repo)

EditReview plays a draft with its transcript; the note field always has the
keyboard focus, so you can type (or dictate) a note at any moment. Press **⌘/**
in the app for the current list.

| Key | Does |
|---|---|
| ★ Space | Play / pause (types a space when the field has text) |
| ★ ⏎ (Return) | Stamp the typed note at the playhead and resume playing |
| Esc | Clear the field |
| ★ Tab / ⇧Tab | Faster / slower (1× up to 3×) |
| ← / → | Back / forward 2 s (⇧ = 10 s) |
| ⌃← / ⌃→ | One frame back / forward (⌃⇧ = ½ s) |
| ↑ / ↓ | Previous / next cut (when the draft came with a cut list) |
| ⌥↑ / ⌥↓ | Previous / next change since the last round |
| ⌃E / ⌃W | Zoom the waveform in / out |
| Home / End | Start / end |
| ⌫ | (empty field) delete the selected notes |
| ⌘⌫ | Archive the selected notes (kept, left out of the export) |
| ⌘Z | Undo |
| ⌘F | Find in the transcript (⌘G / ⇧⌘G next / previous) |
| ⌘O / ⇧⌘O | Open a video / open the path on the clipboard |
| ⇧⌘C | Copy the notes as JSON |
| ⌘= / ⌘- / ⌘0 | Bigger / smaller / default text |

**Change a key** without rebuilding: ask Claude ("change EditReview's zoom
key to ⌘=") or write `~/Library/Application Support/EditReview/shortcuts.json`,
e.g. `{ "zoomIn": ["ctrl+e", "cmd+="] }`, and reopen the app. The action names
and rules are at the top of `apps/edit-review/Sources/Shortcuts.swift`.

macOS uses ⌃← / ⌃→ to switch Spaces (desktops) by default. If frame stepping
doesn't work, turn those off in System Settings > Keyboard > Keyboard
Shortcuts > Mission Control, or rebind the frame keys.

## BulkCut (optional, macOS)

BulkCut (in `apps/bulk-cut`) is the macOS app for triaging a folder of footage
from the keyboard: go down the clips, trash the duds, keep only the good parts,
turn sideways clips upright, then apply everything at once (crops are copied
without re-encoding). It is ready to use: `apps/bulk-cut/prebuilt/BulkCut.app`
(`apps/install_apps.sh` copies it to `~/Applications`). The full key list is in `apps/bulk-cut/README.md`.

| Key | Does |
|---|---|
| ★ ↑ / ↓ | Previous / next clip |
| ★ Space | Play / pause |
| ← / → | Back / forward a little (⌘← / ⌘→ = a lot) |
| ⌃← / ⌃→ | One frame back / forward |
| Tab / ⇧Tab | Faster / slower |
| ★ ⌫ | Mark / unmark the clip for the Trash |
| ★ Q / W | Keep from here / keep up to here (like Resolve's ripple start/end) |
| R / ⇧R | Rotate 90° right / left (lossless) |
| S | Play only the kept parts on / off |
| L | Loop on / off |
| ⌘Z / ⇧⌘Z | Undo / redo |
| ★ ⌘⏎ | Apply, after a review list (⌘S applies straight away) |
| ⌘/ | Show all shortcuts |

**Change a key:** click it in BulkCut's Settings (⌘,) and press the new one, or
ask Claude ("make BulkCut's crop keys I and O"), which writes
`~/Library/Application Support/BulkCut/shortcuts.json`, e.g.
`{ "setIn": "i", "setOut": "o" }`; reopen the app. The action names and rules
are in `apps/bulk-cut/README.md` and at the top of
`apps/bulk-cut/Sources/Keymap.swift`.

## Claude Code itself

| Key | Does |
|---|---|
| Esc | Stop Claude mid-task (your work so far is kept) |
| Esc Esc | Go back to an earlier message |
| ↑ | Previous prompt |
| ⇧Tab | Cycle permission modes |
| Drag a file into the terminal | Paste its full path |

Type `/` to see commands (like `/setup`), and ask Claude to help with Claude
Code's own shortcuts.
