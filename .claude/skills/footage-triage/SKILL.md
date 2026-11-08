---
name: footage-triage
description: Sort a folder of new footage (an import dump, a phone or card copy, any folder of clips and photos) into the right places - a video project, the home-videos archive, the b-roll library, or the trash - by grouping it into shooting sessions, looking at contact sheets, and proposing a plan the user reviews on an HTML page before anything moves. Use when asked to "triage / sort / organize / file this footage", "what's in my inbox folder", "where should these clips go", "clean up my import folder", or "these clips go to <project>".
argument-hint: "[folder] [-- hints, e.g. 'mostly the garden build, plus some cat clips']"
---

# Footage triage

Turns a pile of freshly copied footage into a filed library: work footage into
its project, personal clips into home videos, good general shots into the
b-roll library, junk into a trash folder. Claude proposes; the user approves an
exact list on a review page; only then does anything move. Nothing is ever
deleted.

Scripts: `S="${CLAUDE_SKILL_DIR}/scripts"`. Each has `--help`. JSON on stdout,
progress on stderr. All working files go in a work folder (`W`), never next to
the footage.

## Before you start

1. Read `user/preferences.md` if it exists (`## footage-triage`, `## general`).
2. The folder: the one the user names, else settings `paths.inbox_dir` (the
   inventory exits 4 if unset: ask where they copy footage off cards and phones,
   save it with `tools/vidkit/settings.py set paths.inbox_dir <folder>`).
3. Destinations come from settings: `paths.projects_dir`, `paths.home_videos_dir`,
   `paths.broll_library_dir`. The inventory lists any unset ones; ask for those
   only if the plan needs them (a destination that is unset shows up as
   "needs your decision"). Trash is `_trash` inside the folder being sorted unless
   `triage.trash_dir` is set. If a destination is on a NAS (`nas.enabled`) and not reachable, ask
   the user to mount it before moving.
4. Needs ffmpeg/ffprobe. exiftool, if installed, gives better dates and device
   names for photos and phones (optional; suggest it, never install it).
5. **Privacy.** Classification is done by Claude (a cloud model). What leaves
   this computer for it, per mode of step 4:
   - **Every mode**, as text: file and folder names, capture dates, device
     names, durations, resolutions, sizes, the sound measurements, the user's
     `--hints`, the names of their projects and project footage folders, and
     the first 400 characters of each clip's transcript when there is one
     (made by step 3 `--transcribe`, or a `<clip>.transcript.json` already
     next to the clip).
   - **Default**: also the contact sheets themselves (the frames).
   - **Local mode** (`--local`): no frames; instead a short text description
     of each sheet, written by a vision model on this computer. Needs
     `python3 tools/vlm-describe/vlm_describe.py --check` to say available.
   - **Metadata-only mode** (`--metadata-only`): no frames and no
     descriptions; the user decides more on the review page (the sheets are
     still made locally for that page, which only the user opens).

   Say this in one line before step 4, and for private footage (family, kids,
   anything sensitive) offer local or metadata-only mode. To keep what was
   said out as well, skip step 3: without `W/audio.json` the briefs carry no
   transcript text (and no sound measurements). Transcription itself can also
   be cloud depending on the engine (`transcription.engine`); check with
   `python3 tools/transcribe.py --check` and mention it if so.

## Steps

1. **Inventory** - `python3 "$S/inventory.py" [<folder>]`. Prints `work_dir`
   (use it as `W`). Files are grouped into units: one device, one sub-folder,
   one shooting session (a gap over 3 hours starts a new one;
   `triage.session_gap_hours`). Tell the user the scale: units, files, size,
   date range, and which destinations are set up.
2. **Contact sheets** - `python3 "$S/contact_sheets.py" --inventory W/inventory.json`.
   A grid of frames per video (time printed on each tile), a thumbnail per
   photo. Resumable.
3. **Sound and speech** - `python3 "$S/audio_check.py" --inventory W/inventory.json [--transcribe]`.
   Measures how much of each clip has sound. With `--transcribe` (only if a
   transcription engine is set up, and the user is fine with it) clips with
   sound get a transcript next to them (`<clip>.transcript.json`, reused by
   every other skill, moves with the clip) and the classifier gets a snippet: a
   talking-head take reads very differently from b-roll with wind noise.
4. **Briefs** - `python3 "$S/build_briefs.py" --inventory W/inventory.json --hints "<what the user said>" [--local | --metadata-only]`
   (`--local` first runs the on-device vision model over every sheet: one heavy job, resumable).
   Then spawn one `footage-classifier` agent per printed brief, all in ONE
   message (`subagent_type: footage-classifier`, prompt `Brief: <path>`). Each
   writes its verdicts file. Never hand-write verdicts for a brief an agent
   failed: spawn it again.
5. **Plan** - `python3 "$S/make_plan.py" --inventory W/inventory.json`. Exit 3 =
   a brief has no verdicts yet. Low-confidence units go to "needs your
   decision", never guessed. Fix any `problems` (a file that would overwrite
   another) before the user sees the page.
6. **Review page** - `python3 "$S/build_review.py" --plan W/plan.json --inventory W/inventory.json`,
   then open it for the user (`open <path>` on macOS, `start` on Windows,
   `xdg-open` on Linux) and give them its absolute path. Tell them how it works:
   each card shows the sheets, files, reason and confidence; change a
   destination with the dropdown or write feedback; **Copy decisions** and paste
   the result into the chat, or just say "approved". Clicking a file name opens
   the original clip (browsers play most MP4/MOV files; otherwise copy the path).
7. **Decisions** - save what they pasted to `W/decisions.json` and run
   `python3 "$S/apply_decisions.py" --plan W/plan.json --decisions W/decisions.json`.
   Act on everything under `needs_claude` (a rename: re-run with
   `{"<key>": {"choice": "keep", "folder_name": "<new>"}}`; a new project:
   `{"choice": "project:new", "project": "<name>"}`; "check this again": re-spawn
   a classifier for that unit). Rebuild the page if anything changed and let
   them look again.
8. **Final yes** - `python3 "$S/move.py" --plan W/plan.json` (dry run) and show
   the user the summary: "Move N files (X GB): A to projects, B to home videos,
   C to the b-roll library, D to trash; E units stay where they are. Go?" Only
   after an explicit yes: `move.py --plan W/plan.json --approve`, then
   `move.py --plan W/plan.json --execute`. Changing the plan after approving
   needs a new approval (the script checks).
9. **After** - report per destination the folders created (absolute paths) and
   counts, what stayed in the inbox, and where the trash folder is (the user
   empties it themselves). For the b-roll library folders, offer to index and
   describe them (broll-library skill; `move.py` prints the exact
   `index_folder.py` command). For a new project, offer the `new-project` skill
   to give it the full folder layout. Changed their mind? `move.py --undo
   W/moves.log.jsonl` (dry run, then `--execute`) puts everything back.

## Hard rules

- Nothing moves without the user's explicit yes to the exact dry-run list.
- Move, never copy and never delete. Across drives a move is copy, size check,
  then remove the source. Existing files are never overwritten.
- "Trash" is a folder the user empties (or drags to the system Trash); this
  skill never empties it.
- Sidecars travel: every file next to a clip whose name starts with the clip's
  name (transcripts, .xml, .lrf, .thm, .srt) moves with it.
- A unit moves as a whole unless the classifier is confident a clip belongs
  elsewhere (a pet clip in the middle of a work shoot).
- Never force a destination: unsure means "needs your decision".
- Nothing is written next to the footage except transcripts (`--transcribe`).

## Doing it by hand: BulkCut

Some people would rather sort footage themselves, fast, at the keyboard.
BulkCut (in `apps/bulk-cut`, macOS, optional) is for that: play through a
folder of clips and photos and decide on each one from the keyboard (⌫ trash,
Q / W keep from / up to here, R rotate, drag to zoom; one Apply, ⌘⏎). It ships
ready to use (`apps/bulk-cut/prebuilt/BulkCut.app`, macOS 15+):
`python3 apps/bulk-cut/scripts/bulkcut.py open "<folder>"`. Before the first
session, set the keys to ones you will remember (and that don't clash with your
editor's): BulkCut's Settings (⌘,), or ask Claude to write
`~/Library/Application Support/BulkCut/shortcuts.json` (`customize` skill).
It works well next to this skill: triage with Claude first, then fine-tune a
unit in BulkCut, or the other way round. BulkCut changes the folder it has open
(duds go to the Trash, trims are saved beside the originals unless the user picks
Overwrite), so use it on a folder before or after the move, not on one waiting for
the plan.

## What the user can customize

- The session gap (`triage.session_gap_hours`), the trash folder
  (`triage.trash_dir`).
- Folder naming (`folder_name` rules in `.claude/agents/footage-classifier.md`,
  dates for home videos in `scripts/common.py: dest_dir_for`).
- Extra destinations (e.g. a photos archive): add a kind to
  `DESTINATIONS` / `dest_dir_for` in `scripts/common.py` and describe it in the
  classifier agent.
- Default to metadata-only for everything (say so in preferences).
Record lasting choices under `## footage-triage` in `user/preferences.md`.
