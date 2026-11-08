---
name: multicam-angles
description: Pick the camera angle for every cut of a two-camera DaVinci Resolve a-roll timeline built by aroll-draft's multicam variant - camera A (the main angle, usually the face), camera B (the second angle - overhead, wide, side...), or B with a small camera-A picture-in-picture - from the transcript, with frame checks for unclear moments, an anti-flicker pass and rendered-frame verification. Use when asked to "pick the angles", "do the multicam / angle pass", "switch to the overhead / second camera where I show things", "add the face PiP / inset", or after the user has reviewed an aroll-draft multicam timeline. Laying b-roll is broll-brick-layer, not this skill.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *), Read, Write, Agent
---

# Multicam angles

**What it makes.** Multicam editing means one take filmed by several
cameras at once, cut as one: the editor switches between the cameras
("angles") to show what matters at each moment. aroll-draft's multicam
variant already built the timeline: camera A (the cut source) on V1/A1,
camera B on V2/A2 with every V2 clip switched off, same cuts on both. This
skill decides, segment by segment, which of three angles plays:

| id | angle | on the timeline |
|---|---|---|
| `a` | camera A full frame (the speaker talking to the viewer) | V2 clip off |
| `b` | camera B full frame (overhead, wide, side...) | V2 clip on |
| `pip` | camera B with a small camera-A inset in a corner (picture-in-picture) | V2 on + a V3 clip of camera A |

The words decide most segments (one agent per ~5 minutes of timeline), a
frame judge looks at both cameras where the words cannot tell, one agent
reads the whole plan to fix flicker and batch seams, short runs are
merged, and rendered frames prove the result. Output: the angles applied
in Resolve, a backup timeline, `angle_list.txt` (timecode, angle, length per
run) and verify frames.

## Before you start

1. Read `user/preferences.md`: `## general` and `## multicam-angles`. They
   override everything below (camera names, PiP corner, "no PiP", how often
   to show camera B...). The batch prompts embed them automatically.
2. `python3 tools/vidkit/settings.py get editor.nle`:
   - `resolve-studio`: the full pipeline below. DaVinci Resolve must be
     running with the project open (ask the user to open it; never launch or
     quit it while they might be editing).
   - `resolve-free` (scripts cannot read or change the timeline): run the
     decision steps on a dump made from the cut list (`timeline_transcript.py
     fromcuts <stem>.aroll.tb.json <cameraA> -o WORK/angle_dump.json --fps F
     --start-frame 86400 --job ...`, use the timeline's real start frame), stop at
     `angle_list.txt`, and teach the user to apply it by hand (below).
   - `none`: this skill needs Resolve. Say so; talking-head-ffmpeg is the
     one-camera ffmpeg path.
3. Find the work folder: where aroll-draft wrote `angle_job.json` (ask, or
   search the project folder for it). Call it WORK. The job has `project`,
   `timeline`, `never_touch`, `primary_path` (camera A), `secondary_path`
   (camera B), `secondary_rotate180`, `offset_s`, `fps`.
4. Describe the setup in the job (once; ask the user if preferences don't
   say). Add to `angle_job.json`:
   ```json
   "angles": {"a":   {"name": "face", "describe": "front camera on the speaker"},
              "b":   {"name": "overhead", "describe": "top-down camera on the desk and hands"},
              "pip": {"name": "overhead + face", "describe": "overhead with a small face inset"}},
   "allowed_angles": ["a", "b", "pip"],
   "min_run_s": 2.0, "target_run_s": 4.0,
   "pip": {"corner": "top-right", "face_box": [0.34, 0.0, 0.66, 0.49], "inset_width": 0.23}
   ```
   `face_box` = where the face is in camera A's frame, `[x0, y0, x1, y1]` as
   fractions from the top-left. Extract one camera-A still
   (`ffmpeg -ss 60 -i <cameraA> -frames:v 1 WORK/camA.jpg`), look at it, and
   set a box a bit larger than head and shoulders. Pick the corner where
   camera B's picture has nothing important (the action is usually
   centre-bottom on an overhead, so a top corner). No PiP wanted: drop
   `"pip"` from `allowed_angles`.

Scripts: `S=${CLAUDE_SKILL_DIR}/scripts`. Every command prints JSON.

## Steps

1. **Backup.** List the project's timelines and put every copy the user
   made into `never_touch`. Then
   `python3 $S/resolve_angle.py backup WORK/angle_job.json "pre-angles"`
   (it adds the copy to `never_touch`; every subcommand refuses those names).
2. **Dump the LIVE timeline** (the cut list is stale after hand edits):
   `python3 $S/resolve_angle.py dump WORK/angle_job.json WORK/angle_dump.json`.
   `counts_match` must be true; `v3_not_ours` lists the user's own V3 clips
   (they are left alone).
3. **Words onto the timeline.** `python3 tools/transcribe.py <camera A>` creates
   or reuses the transcript, then
   `python3 $S/timeline_transcript.py map WORK/angle_dump.json -o WORK/angle_transcript.json --job WORK/angle_job.json`
   (finds `<stem>.transcript.json` beside each clip's media; if only camera
   B has one: `--sidecar <B transcript> --shift-s <offset_s>`). The word count
   should be close to the cut's kept words; `silent_segments` are demos.
4. **Batch prompts:** `python3 $S/timeline_transcript.py batches WORK/angle_transcript.json WORK/angle_batches --job WORK/angle_job.json`.
5. **Decide, in parallel.** For every batch, spawn an **angle-selector** agent
   (all at once): "Prompt file: <batch_NN.prompt.md>. Write your decisions to
   <batch_NN.decisions.json>." (paths from `plan.json`). Then
   `python3 $S/timeline_transcript.py merge WORK/angle_batches -o WORK/angle_decisions.json --job WORK/angle_job.json`.
   Exit 3 = a batch skipped or repeated ids: re-spawn that batch with the
   problem list.
6. **Frames for the unclear segments** (`low_confidence` from merge; skip if
   none): `timeline_transcript.py jobs WORK/angle_decisions.json WORK/angle_transcript.json WORK/angle_jobs --job ...`,
   then `resolve_angle.py frames WORK/angle_job.json WORK/angle_dump.json WORK/angle_frames WORK/angle_jobs/only.json`
   (both cameras side by side, 2+ samples per segment), then
   `timeline_transcript.py brief WORK/angle_frames WORK/angle_decisions.json WORK/angle_transcript.json -o WORK/angle_frame_brief.md --out WORK/angle_frame_verdicts.json --job ...`.
   Spawn one **angle-frame-judge**: "Brief: <angle_frame_brief.md>". Apply:
   `timeline_transcript.py apply WORK/angle_decisions.json WORK/angle_frame_verdicts.json --source frames --job ...`.
7. **Overpass:** `timeline_transcript.py review WORK/angle_decisions.json WORK/angle_transcript.json -o WORK/angle_review.md --out WORK/angle_corrections.json --plan WORK/angle_batches/plan.json --job ...`,
   spawn an **angle-blender**: "Review file: <angle_review.md>. Write
   corrections to <angle_corrections.json>.", then `apply` them. One round
   is normally enough; at most two.
8. **Minimum runs:** `timeline_transcript.py smooth WORK/angle_decisions.json WORK/angle_transcript.json --job ...`
   merges every run under `min_run_s` into its longer neighbour (a B <-> PiP
   switch counts too). Then `jobs` again: it rewrites `decisions.json`,
   `pip.json` and `angle_list.txt`.
9. **Apply in Resolve** (re-dump first if the user touched the timeline since
   step 2; record starts go stale):
   - `resolve_angle.py apply WORK/angle_job.json WORK/angle_jobs/decisions.json`
   - `resolve_angle.py pip WORK/angle_job.json WORK/angle_jobs/pip.json`
     (rounded inset with a soft shadow, built in Fusion; idempotent).
   - `resolve_angle.py smooth WORK/angle_job.json WORK/angle_jobs/smoothed.json`:
     safety net on the live timeline, should flip nothing. `pip_conflicts`
     non-empty = remove those starts from `pip.json` and re-run `pip`.
   - If broll-brick-layer is installed, its `flicker_audit.py --project P --timeline T`
     must report 0 findings (it sees slivers across all tracks).
10. **Verify with rendered frames:** `resolve_angle.py verify WORK/angle_job.json WORK/angle_verify <record_in> ...`
    for 4-6 PiP segments spread over the video plus a B one. Read every
    image: right camera? inset clear of the action and the face inside it?
    any table edge or floor showing on camera B? Fix (`pip` block in the
    job, then `pip` again, or `restyle` when only the look changed) and
    verify again. Never trust property read-backs.
11. **Report** to the user: seconds per angle, number of runs and the
    shortest, what the frame judge and the blender changed, the verify
    images (absolute paths), the backup timeline's name, and how to review.

## Reviewing and fixing by hand (teach this)

Play the timeline at normal speed in Resolve's Edit page (`Space` play,
`J`/`K`/`L` back/stop/forward, `Up`/`Down` arrow jump to the previous/next
cut). Watch for a camera switch that comes too often, an inset covering the
action, or the wrong camera on a reveal. Or render a draft
(resolve-export-draft) and leave timestamped notes in EditReview.

To change one segment on this layout: click its V2 clip and press `D`
(enable/disable clip) to switch between camera A and B; delete or copy the
V3 clip above it to remove or add the inset. `Cmd+B` (`Ctrl+B` on Windows)
splits a clip at the playhead if a switch must happen mid-segment (do it on
V1, V2 and V3 together). Turning a whole track off (its monitor icon at the
track header) previews camera A only. Or just tell Claude "the segment at
01:04:10 should be camera A".

Resolve's own multicam tool, for doing it all by hand (handy with the free
version and `angle_list.txt`): in the Media Pool select both camera files,
right-click > **Create New Multicam Clip Using Selected Clips**, angle sync
**Sound**. Cut that clip on the timeline, set the source viewer to
**Multicam** (the viewer's mode menu), play, and click an angle to cut to
it; `Option`/`Alt`-click switches the current segment without adding a cut.
On the timeline, right-click a multicam segment > **Switch Multicam Clip
Angle**.

When the user corrects angles, add the lesson to `user/preferences.md`
under `## multicam-angles` (say so in one line); if it is a rule about
looking at frames, offer to add it to `reference/frame-rules.md` too.

## Hard rules

- A successful `backup` comes before any change; `never_touch` names every
  timeline that is not the working one.
- Re-dump before mutating; the user edits between passes.
- Whole segments only: never split clips, trust the cut boundaries.
- Agents get the transcript; frames only for what the words cannot settle.
- No angle run under `min_run_s` (default 2 s): a few frames of another
  camera read as a glitch, not a cut.
- Camera B's rotation and zoom are aroll-draft's job
  (`resolve_angle.py transform`); don't redo them here.
- Sync comes from the audio (`offset_s`), never from file timestamps.
- No b-roll here: broll-brick-layer runs after this pass.
- "Scripting server not responding": ask the user to save and restart
  Resolve, then re-run.

## What the user can customize

- Camera names, descriptions, allowed angles, run lengths and PiP placement:
  `angle_job.json` (this run) or `## multicam-angles` in
  `user/preferences.md` (every run).
- The angle rules the agents follow: `reference/angle-rules.md`; the frame
  rules: `reference/frame-rules.md`.
- The PiP look (corner radius, shadow, an outline): the `pip` block
  (`corner_radius`, `shadow_offset`, `shadow_softness`, `shadow_alpha`,
  `outline_px` + `outline_alpha`), or `"style": "inspector"` for a plain
  crop without Fusion. Defaults: `PIP_DEFAULTS` in `scripts/angles.py`.
- Agent models: `.claude/agents/angle-*.md`.

Script details (job format, the Fusion graph, transform sign traps, frame
export caveats) are in the scripts' headers and
[reference/resolve-notes.md](reference/resolve-notes.md): load them when
something fails.
