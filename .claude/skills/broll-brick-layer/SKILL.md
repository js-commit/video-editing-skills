---
name: broll-brick-layer
description: Lay b-roll onto a cut talking-head timeline in DaVinci Resolve Studio - annotate the project's b-roll from contact sheets, match shots to what the speaker says, check and adversarially verify the plan, place the bricks, then audit for flicker and clipped speech. Also fills red NEED BROLL markers (from the project, the b-roll library or free stock online) and runs the seam / flicker audits other skills call. Use when asked to "lay / add / apply b-roll", "cover the talking head", "annotate my b-roll", "match footage to what I say", "fill the NEED BROLL markers", "find a shot for 2:15", "check the timeline for flicker" or "audit the seams". Without Resolve Studio, use talking-head-ffmpeg.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *), Read, Write, Agent
---

# B-roll brick layer

**What it makes.** B-roll is the footage that plays over the speaker while
you keep hearing them: the product they talk about, the place, the hands
doing the thing. The talking-head footage is the a-roll. Each piece of
b-roll sits on its own track above the a-roll like a brick: one shot, one
source range, laid edge to edge with the cuts underneath. Bricks are easy
to see, move, trim or delete by hand, and the a-roll never changes when a
brick does. This skill reads your b-roll, matches it to your words, and
lays the bricks on a "B-roll bricks" track in your Resolve timeline. The
rationale for every brick stays in `plan.json`, and only the gaps it could
not fill get a red NEED BROLL marker.

Scripts live in `${CLAUDE_SKILL_DIR}/scripts/` (call that `S`; `REPO` is
`${CLAUDE_SKILL_DIR}/../../..`). Each one has `--help`; its docstring carries
its own gotchas. Read it before first use.

## Before you start

1. Read `REPO/user/preferences.md`: `## general` and `## broll-brick-layer`
   override everything below (brick length, how much to cover, shots to
   avoid, track name...).
2. `python3 REPO/tools/vidkit/settings.py get editor.nle`:
   - `resolve-studio`: the steps below. DaVinci Resolve must be running
     with the project open. Never launch, quit or switch projects on the
     user while they might be editing: ask them to open it.
   - `resolve-free` or `none`: external scripting is a Studio feature, so
     this skill cannot touch the timeline. Use **talking-head-ffmpeg** (the
     same matching, rendered by ffmpeg). The annotation and matching steps
     (3-7) still work on files if the user wants a shot list to place by hand.
   - unset: ask which they use (exit code 4 means the same for any script).
3. Work folder: `<project>/<project_layout.work>/broll-brick-layer/` (the
   scripts default to it; `python3 REPO/tools/vidkit/settings.py project-dir
   "<Resolve project name>"`). Call it WORK. Put `plan.json`, `needs.json`,
   the brief and verdicts there.
4. Teach as you go if the user is new: what a brick is, why the scripts
   back up first, and the review shortcuts at the end.

## Steps

### 1. Back up, then read the live timeline

```
python3 S/backup.py create --project "P" --timeline "T" -m "before b-roll"
python3 S/inventory.py --project "P" --aroll "T" -o WORK/inventory.json
```

Edits made by scripts do not land in Resolve's undo history: the `.drp`
backup and the "T backup <time>" timeline are the undo. `inventory.py`
records every track (frames and seconds), the brick track and the a-roll
camera tracks, and refuses backups and never-touch timelines. b-roll that
only exists as files is fine: placements can point at files directly.

### 2. The transcript as the audience hears it

```
python3 S/edited_transcript.py --inventory WORK/inventory.json --transcribe -o WORK/edited_transcript.json
```

It projects each a-roll source's word-level `<stem>.transcript.json` (made
once by `tools/transcribe.py`, reused by every skill) through the cuts.
Times are seconds from the timeline start: the same clock as a draft render
and its review notes. Pass `--track audio:N` if the voice is not on A1.

### 3. Find and profile the b-roll

The project's footage folder (`project_layout.footage`) and any supply
timelines in the inventory. Ask if unclear. Bricks are CUT out of a supply
timeline, so only a timeline named as b-roll (`"dedicated_supply": true`)
is supply by default; to use any other one (an earlier cut, a client
version), ask the user and list it in the plan's `supply_timelines`:
check_plan.py and apply_plan.py refuse it otherwise. A "b-roll" clip whose
transcript is full of speech is probably a misfiled a-roll take: ask before
treating it as b-roll. Then, for each clip:

```
python3 S/annotations.py status <clips...>           # content-hash store: renamed or moved clips keep their notes
python3 S/profile_clip.py <clip> -o WORK/profile/<stem>.json      # scene cuts + calm/shaky spans
python3 S/frames.py <clip> WORK/frames/<stem> --sheet             # sharpest frame every 2.5 s + contact sheets
```

### 4. Annotate (one agent per 4-5 clips)

Write `WORK/annotator_brief.md`: one paragraph on the video's topic, the
names and vocabulary from the transcript, and a **disambiguation checklist**
(the visible differences between look-alike things the video talks about:
two models of one product, phone vs tablet, before vs after). Then spawn
`broll-annotator` agents for the clips still MISSING, at most ~5 clips and
~150 frames each (a long take gets its own agent: an agent drowning in
images gets sloppy). The prompt names the brief,
`${CLAUDE_SKILL_DIR}/reference/formats.md`, each clip's profile and frames
folder, and `S/annotations.py`. Re-run `annotations.py status` after.

### 5. The user checks the annotations

Show a compact table (clip, segments, what each shows, quality) and ask
for corrections. Their word beats any agent: write corrections into the
annotation, set `"annotator": "human"` on clips they labelled, and add any
placement order they give as a segment's `director_note`. Skip the wait
only if preferences say so.

### 6. Match and write the plan

Read `edited_transcript.json`, every annotation (`annotations.py dump`) and
what already sits on the brick track. Then decide:

- `director_note`s first: they are orders. One that cannot be honoured is
  reported, never dropped.
- Cover as much of the talking head as the words allow, but the picture
  must show what the words say: same product, same device, same action.
  `unsure` segments never go over specific speech. If nothing fits, place
  nothing and add a need to `WORK/needs.json`. A wrong brick is worse than
  a gap.
- 3-15 s per brick; trim long segments to their best sub-range, inside one
  scene, with in and out points in calm spans (`profile.json`).
- Each source range is used once. Do not butt two ranges of the same
  locked-off shot (it reads as a jump cut).
- Leave the speaker on screen when they show something to the camera
  ("look at this", "right here"): check the a-roll frames there
  (`frames.py <a-roll source> ... --start S --end E --interval 0.5`).
- Coverage audit: every stretch over 15 s with no b-roll gets a brick, a
  need, or a stated reason.

Write `WORK/plan.json` and `WORK/needs.json` (shapes in
`reference/formats.md`), each placement with a one-line `why`.

### 7. Check, snap, verify

```
python3 S/check_plan.py WORK/plan.json --inventory WORK/inventory.json --transcript WORK/edited_transcript.json --write
```

Exit 3 = errors or flashes to fix (overlaps, a reused range, a brick a few
frames off a cut it cannot reach). It snaps brick edges onto the a-roll's
cut frames: bricks are planned in seconds, cuts are exact frames, and a
brick that starts 5 frames after a cut flashes the talking head for 5
frames. Then fan out `broll-verifier` agents (~5 placements each) with the
plan, the frames folders, the transcript and an output path. They read the
actual frames inside each source range and veto, pass, or offer a better
sub-range. Apply verdicts (vetoed placements become needs), re-run
check_plan, re-verify what changed.

### 8. Apply

The user may have edited the timeline while you worked. Re-read it first:

```
python3 S/inventory.py --project "P" --aroll "T" --compare WORK/inventory.json -o WORK/inventory.json
python3 S/check_plan.py WORK/plan.json --inventory WORK/inventory.json --write
python3 S/apply_plan.py WORK/plan.json --dry-run
python3 S/apply_plan.py WORK/plan.json -o WORK/apply_report.json
python3 S/add_markers.py --needs WORK/needs.json --clear-first
```

A brick the user moved, trimmed or deleted is their decision: never put it
back. `apply_plan.py` exports a `.drp` backup first, only fills empty
space, and re-reads the saved track.

### 9. Audit until clean

```
python3 S/flicker_audit.py --project "P" --timeline "T"
```

The required result is **0 findings**, counted fresh every time (never "no
new findings"). Fixes: `ripple_extend.py --project P --timeline T
--snap-top-track` (brick edges a few frames off a cut), `close_gaps.py
--project P --timeline T` (sub-second gaps between bricks), and for
one-word slivers in the a-roll `seam_audit.py ... --plan WORK/seams.json`
then `ripple_extend.py ... --plan WORK/seams.json`. Listen to restored
pauses: a "silence" can be a sound the viewer was meant to hear. Details and
every flag: `reference/audits.md`.

### 10. Report and review

Report: bricks placed (timecode, clip, why), NEED BROLL spots, uncovered
stretches and why, unused b-roll, the backup to restore from. Write
`WORK/shoot_list.md` when needs remain (timecode, the line, a suggested
shot) while the products are still at hand. Offer a draft render
(resolve-export-draft) for review in EditReview.

Reviewing in Resolve (Edit page): Space plays/stops, J / K / L shuttle
back / stop / forward (tap twice for faster), Up / Down arrow jump to the
previous / next edit, Shift+Up / Shift+Down to the previous / next marker,
Shift+Z fits the whole timeline in view, D turns the selected clip off and
on (compare with and without a brick). Cmd+Z / Ctrl+Z does NOT undo what a
script did: restore with `backup.py restore`.

## Filling NEED BROLL markers

Spawn one `broll-hunt` agent per slot. Its brief: the spoken words and
times, slot length, timeline resolution and fps, the sources in scope (the
project's footage, the b-roll library via
`python3 ${CLAUDE_SKILL_DIR}/../broll-library/scripts/search.py "<query>" --json`,
other projects under `paths.projects_dir`, and free stock or press images
online only if the user agrees: `reference/stock-sources.md`), and the
output path. It writes a pick JSON; you read its frames, merge the pick into
`plan.json` and go through steps 7-9. Online picks need their licence and
credit line in the report.

## Hard rules

1. Back up before every change (backup.py; the mutating scripts also do it
   themselves and stop if the export fails).
2. Never read from or write to a backup timeline ("backup" in its name) or
   one on the never-touch list (`editor.never_touch_timelines`, or a plan's
   `never_touch`). The scripts refuse; do not work around them.
3. Re-read the live timeline before planning and before applying: the user
   edits between passes, and their edits are ground truth.
4. Verify the actual frames inside each source range before a brick lands.
   Names, folders and old notes are leads, not evidence.
5. Only fill empty space on the brick track; one source range, one use.
6. No flicker: a visible shot under 0.6 s is a flash. Brick edges sit ON
   cuts. Audit to 0 findings.
7. Only red NEED BROLL markers go on the timeline.
8. Think in seconds (frame rates are mixed); frames only at cut edges.

## Customize

Users change: the brick track name (`--track-name`, the plan's
`track_name`), brick length range, how much to cover, annotation fields
(add your own to the annotation format), agent models (`python3
REPO/tools/agent_models.py apply pro|max` matches them to the Claude plan;
hand edits to `.claude/agents/broll-*.md` stick except on broll-annotator
and broll-hunt, which that command rewrites), the flash threshold
(`--min-run-s`). Record lasting choices in `REPO/user/preferences.md` under
`## broll-brick-layer`; use the `customize` skill to change how the skill
itself works. Tests: `python3 -B S/tests/run_all.py` (no Resolve needed).
