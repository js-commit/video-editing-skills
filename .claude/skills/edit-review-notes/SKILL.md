---
name: edit-review-notes
description: Turn timestamped review notes on a draft render into edit changes - b-roll, screenshots and big-text overlays first, then the cuts, trims and restored pauses that shift timestamps - in a DaVinci Resolve Studio timeline or a talking-head-ffmpeg recipe, render the next draft, and leave changes.json + cuts.json beside it so the user reviews only what changed. Notes come from EditReview (notes.json), Resolve markers, or a plain text file of "1:23 note" lines. Use for "apply my notes", "here are my review notes on the draft", "I left notes in EditReview", "apply my markers", "do the notes round", or when handed a .review folder or notes.json.
argument-hint: <draft render, its .review folder, or a notes text file>
---

# Edit-review notes round

Makes: the next draft of a video with every review note applied, plus
`changes.json` (one entry per change: what was done, what to watch, the note
it answers) and `cuts.json` (the new edit points) in the new render's
`<stem>.review/` folder, and a short report. EditReview shows both files:
the user presses Option-Down to jump from change to change. File formats:
`apps/edit-review/SPEC.md`.

Words used here: the **a-roll** is the main talking track (the person on
camera and their voice); **b-roll** is footage laid over it; a **ripple**
edit closes the gap a cut leaves by pulling everything after it earlier.

## Before you start

- Read `user/preferences.md` if it exists: `## edit-review-notes` and
  `## general` override the defaults below.
- `REPO` = `${CLAUDE_SKILL_DIR}/../../..`. Scripts: `S=${CLAUDE_SKILL_DIR}/scripts`,
  `APP=REPO/apps/edit-review/scripts`.
- Which edit made the draft? A `recipe_vN.json` in the project's work folder
  means **talking-head-ffmpeg** (the ffmpeg path). A DaVinci Resolve timeline
  means the **Resolve path**, which needs `editor.nle` = `resolve-studio`
  (`python3 REPO/tools/vidkit/settings.py get editor.nle`): the free version
  has no external scripting, so with it you plan the changes and the user
  applies them by hand from your list. If unclear, ask one question.
- Get the notes into `<draft-stem>.review/notes.json`:
  - EditReview already wrote it: nothing to do.
  - Resolve markers: `python3 $S/import_notes.py DRAFT --resolve-markers [--timeline T] [--color C]`
    (Studio), or a marker EDL: `--edl markers.edl`.
  - A text file of `1:23 note` lines: `python3 $S/import_notes.py DRAFT --text notes.txt`.
- For the Resolve path, don't connect while the user is mid-edit: ask them to
  save and stop editing for the round. Resolve has one scripting connection
  and one timeline; you are the only writer until the round ends.

## Steps

### 1. Worksheet and plan

```
python3 $S/notes_worksheet.py DRAFT --transcribe      # -> <stem>.review/notes_map.json
```

It lists every live note with the words spoken 14 s before to 10 s after
the stamp (`▮` marks the stamp), the clip under it (from cuts.json) and a
keyword guess at its class. **Stamps are late**: the reviewer pauses after
noticing, so the note is usually about the sentence that just ended. Anchor
every note to the exact words it is about (first word ... last word, with
their times) before planning anything.

Class each note in `notes_map.json` (`class`, `type`, `plan`), using
`reference/note-types.md`:

- **additive**: lands on a layer above the a-roll and never changes timing:
  b-roll, a screenshot card, big text, a graphic, a replaced or moved b-roll
  shot.
- **structural**: changes the a-roll and shifts every later timestamp: cut,
  trim a repeat, drop a section, restore a pause, re-record, add a section.
- **other**: audio level, colour, a question (answer it in the report).

Split a note that is both ("cut the repeat and show the box") into two
entries. Show the user the plan as a short table (note, class, what you will
do) and carry on unless preferences say to wait for a yes.

### 2. Phase 1: every additive note

Why first: every note's time is on the draft's clock, which stays true only
until the first cut. Layers laid now ride along when phase 2 ripples the
a-roll, so their positions stay exact.

- **B-roll**: search, in order: the project's own footage, the b-roll library
  (`python3 REPO/.claude/skills/broll-library/scripts/search.py "<what the words say>" --limit 10 --json`;
  returns `[]` with a note when no library is set up), then sibling projects
  under `paths.projects_dir`. Look before you pick: extract frames of each
  candidate range with ffmpeg and read them. The shot must show what the
  words say (the same product, device and action); a wrong shot is worse
  than none. Nothing fits: leave a marker or recipe "need" named
  `NEED BROLL: <subject>` with the note and where you looked, and report it.
  Many b-roll notes: `reference/broll-hunt-brief.md` has a brief for one
  helper agent per note (they only write a pick file; you apply).
- **Screenshots**: ask the user for the image (or a URL and their OK to
  capture it with a browser tool, if this session has one). Place it as a
  full-frame card: the screenshot enlarged over a blurred copy of itself,
  never stretched to fill.
- **Big text / metrics**: a transparent PNG card or an animated overlay (the
  `motion-graphics` skill). Numbers come from the transcript; a figure the
  user quotes from memory goes in as given and is flagged in the report.
  Read the frame under the slot first: text never covers the face or an
  on-camera demo.
- Placement rules for all of them: start on a word start; end on an a-roll
  cut or the next layer's edge; at least 1.5 s on screen (3 s or more for
  anything with text to read); no sliver of a-roll under 0.6 s between a
  layer edge and a cut (it reads as a flicker); don't cover "you can see /
  look at this" moments where the person shows something to the camera.

Apply them with the path's tools: **Resolve** `reference/resolve-path.md`,
**ffmpeg** `reference/ffmpeg-path.md`. Phase-1 gate: the a-roll must be
exactly the draft's (Resolve: `resolve_notes.py verify`; ffmpeg: the recipe's
keeps unchanged) and the flicker check clean.

### 3. Phase 2: structural notes, latest first

- Apply them from the **highest `seconds` down**, so earlier notes'
  positions stay valid while you work. Never cut from the top using the
  original seconds.
- Cut on silence, not on word times: snap each edge into the pause around
  the span. Keep cuts hard (no crossfades) unless the user asks.
- A repeat: remove the take the user names; if they don't say, remove the
  first and keep the one that flows into the next sentence. Never remove a
  sentence the note did not name; a vague "too long" trims the longest pause
  near the stamp and says so in the report.
- Restore a pause ("cut too tight", "let it breathe"): bring back frames
  from the source gap; listen to what you restore.
- Re-record / add a section: never invent a-roll. Cut the old span if asked
  and leave a marker (`RE-RECORD: <note>` / `ADD: <note>`) for the user.
- Ripple every track, so phase-1 layers move with the a-roll. Afterwards
  check that no layer now spills onto words it was not laid for.

### 4. Render the next draft and write the two files

1. Render: Resolve, the `resolve-export-draft` skill; ffmpeg,
   `render_recipe.py` (talking-head-ffmpeg). Use a new file name (draft-N+1),
   so the old draft and its notes stay as they were.
2. `cuts.json` in the new render's `.review/`: written by the ffmpeg
   renderer; for Resolve, `python3 $APP/export_cuts.py NEW_DRAFT` if the
   render step did not write one.
3. `changes.json`: write one row per change **on the new render's clock**
   (read positions from the edited timeline or recipe, never by adding and
   subtracting the old seconds), with `title`, `what`, `watch`, `note` (the
   note verbatim) and `kind`, then:
   `python3 $S/write_changes.py NEW_DRAFT --list changes.in.json --round vN+1 --previous vN --summary "…"`
   (ffmpeg path: `review.py changes` does the same). Exit 3 lists rows to fix.
   A removal is a point (`start_s == end_s`) at the join.

### 5. Report

Lead with the new draft's absolute path, its length (old -> new) and the
gates (a-roll unchanged after phase 1, flicker check clean). Then one line
per note: what was done and its new time, or why not (NEED BROLL, a
question answered, needs the user). Then: "Open it in EditReview and press
⌥↓ to step through the N changes" (or list the times for another player).
Mention the backup timeline / previous recipe as the restore point.

## Hard rules

- Additive before structural, always. After phase 1 the a-roll is
  item-for-item the draft's.
- Back up before the first change (Resolve: `resolve_notes.py backup`; ffmpeg:
  a new recipe version). Never edit a timeline with "backup" in its name.
- One writer: only you touch the timeline or recipe, one operation at a
  time, re-reading positions after each. Helper agents never touch Resolve.
- Never substitute a look-alike shot, never invent a-roll, never delete or
  move media files. No uploads.
- Every round ends with changes.json + cuts.json in the new render's
  `.review/` folder.
- Teach as you go (unless preferences say the user is experienced): explain
  a term the first time, and name the key for anything the user does by
  hand (Resolve: B blade tool, Cmd/Ctrl+B split at the playhead,
  Shift+Delete ripple delete, M marker; EditReview: ⌥↑/⌥↓ changes, ⌘/ keys).

## What the user can customize

Say it ("from now on ...") and the preference lands in `user/preferences.md`;
bigger changes go through the `customize` skill. Common ones: confirm the
plan before applying; the stamp window (14 s back / 10 s forward); minimum
on-screen times; which take to keep on a repeat; marker colours; whether text
cards go left or right. EditReview's keys are theirs to change too
(`apps/edit-review/README.md` > Customizing the keys): remind a new user once
that the keys can be rebound if they clash with their dictation app.
