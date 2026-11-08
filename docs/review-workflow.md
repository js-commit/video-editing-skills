# Reviewing a draft

A review is you watching a draft render and leaving timestamped notes ("cut
the long pause", "show the product here", "put the price on screen"). Claude
then applies them with the `edit-review-notes` skill, renders the next draft,
and tells you exactly what changed so the next pass only covers the changes.

Three ways to take the notes. Pick whichever fits; all three end up as the
same `notes.json` the skill reads.

## 1. EditReview (macOS, hands-free)

The repo's small review app, `apps/edit-review/` (ready to use:
`apps/edit-review/prebuilt/EditReview.app`). It plays the draft with a
note field that always has the keyboard focus:

1. Open the draft: drag it onto the window, or ⌘O.
2. Watch. When something needs fixing, just start typing, or dictate: macOS
   Dictation (System Settings > Keyboard > Dictation) or any dictation app
   that types into the focused field. Press SPACE first if you want to pause.
3. Press **Return**. The note is stamped with the playhead time and playback
   carries on. **ESC** clears a half-typed note.
4. Useful keys while reviewing: **TAB** speeds up (1.5×, 1.7×, 2×…),
   **← / →** skip 2 s, **↑ / ↓** jump between cuts, **⌥↑ / ⌥↓** play the next
   change from the last round, **⌘/** shows every key.
5. When done, tell Claude: "apply my notes on <draft path>".

Notes save themselves to `<draft>.review/notes.json` after every keystroke
that changes them. Don't worry about precise timing: a note stamped a second
or two late is expected; the skill reads the words around it.

**Customize the keys.** If SPACE or TAB clashes with your dictation app or
your muscle memory, change them: create
`~/Library/Application Support/EditReview/shortcuts.json`, e.g.
`{ "playPause": "ctrl+space" }`, and reopen the app, or just ask Claude to
"change the EditReview shortcut for play/pause". Full list and rules:
`apps/edit-review/README.md` > Customizing the keys.

## 2. DaVinci Resolve markers (the M key)

If you review inside Resolve (or on a computer without EditReview):

1. Play the timeline on the Edit page.
2. At each problem press **M** to add a marker at the playhead (it works
   while playing). Press **M** twice, or double-click the marker, to open it
   and type the note in its Name or Notes field; you can also drop all the
   markers first and fill them in afterwards. Pick one marker colour for
   review notes if you also use markers for other things.
3. Tell Claude: "apply my review markers on <timeline>". The skill reads them
   with `import_notes.py --resolve-markers` (DaVinci Resolve Studio, which
   allows external scripting) and works from there.

With the free version of Resolve, external scripts can't read markers:
export them instead (*File > Export > Timeline Markers to EDL…*) and hand
Claude the EDL, or use option 3.

Resolve's keys can be changed too: DaVinci Resolve > Keyboard Customization
(with presets for people coming from other editors).

## 3. Any player plus a text file

Watch in QuickTime, VLC, a browser, on a phone, anything that shows the
time. Write one note per line, time first:

```
0:42 cut the long pause
1:15 show the product close-up here
2:03 - I said this twice, keep the second one
03:10 put the price on screen
```

`m:ss`, `h:mm:ss`, plain seconds and `HH:MM:SS:FF` timecode all work; a line
without a time continues the note above it. Save it anywhere and tell Claude:
"here are my notes on <draft path>: <notes file>". The skill converts it with
`import_notes.py --text`.

## What happens next

The skill applies the notes in two phases: first everything that lands on
top of the edit (b-roll, screenshots, text on screen), while your timestamps
still point at the right moments, then the cuts and trims, which shift
everything after them. It renders the next draft and writes two files next
to it: `changes.json` (one entry per change, with what was done and what to
watch) and `cuts.json` (the edit points). Open the new draft in EditReview
and press **⌥↓** to jump from change to change; in another player, the skill's
report lists each change with its time.

## Tips

- Review at 1.5× or faster once the edit is close; slow down for the details.
- Say what you want, not just what is wrong: "too long, keep only the first
  sentence" beats "too long".
- One thing per note. "Cut the pause and show the box" works, but two notes
  are easier to track.
- Notes that are questions ("is this shot sharp?") get an answer in the
  report, not an edit.
