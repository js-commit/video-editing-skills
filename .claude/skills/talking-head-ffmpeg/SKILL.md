---
name: talking-head-ffmpeg
description: Edit a one-camera talking-head video without an editing app - aroll-draft's cut becomes a JSON recipe, b-roll is matched to the transcript from contact sheets, and ffmpeg renders a 1080p draft (then the full-resolution final), with measured QC and EditReview notes rounds. The no-Resolve path; motion-graphics writes animated overlays into the same recipe. Use when asked to "edit this with ffmpeg", "add b-roll without Resolve", "make a draft with b-roll", "render the recipe", "apply my notes" on a video this skill built, or when editor.nle is "none" / "resolve-free".
argument-hint: "<take(s) or project> -- which takes, in what order"
allowed-tools: Read, Write, Edit, Agent, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../broll-library/scripts/search.py *), Bash(python3 .claude/skills/broll-library/scripts/search.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/../motion-graphics/scripts/render.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/vidkit/media.py *), Bash(python3 tools/vidkit/media.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/vidkit/settings.py *), Bash(python3 tools/vidkit/settings.py *), Bash(ffmpeg *), Bash(ffprobe *)
---

# Talking head, ffmpeg edit

**What it makes:** a finished talking-head edit from a single camera: the a-roll cut (the speaker on camera, with
mistakes and pauses removed), b-roll laid over it (other footage shown while the voice continues), optional overlays
and motion graphics, the speaker's sound loudness-normalised for YouTube. The whole edit is one JSON file, the recipe,
that ffmpeg renders. It is diffable, every round is a new version, and nothing needs an editing app.

Terms, the first time they matter (skip if preferences say the user is experienced):
- **Jump cut**: two kept pieces of the same shot joined, so the speaker "jumps". Normal on YouTube; b-roll over the cut
  hides it.
- **Cutaway / b-roll brick**: a few seconds of other footage over the speech, picture only. Here each one is a "brick".
- **J-cut / L-cut**: the sound and picture change at different moments (J: you hear the next shot before you see it;
  L: the picture changes while the previous sound continues). Every brick here is a natural L-cut: the picture leaves
  the speaker while their voice carries on. Starting a brick a beat after the words it illustrates begin feels smooth.
- **Lower third**: a name or label in the bottom third of the frame: the motion-graphics skill makes them.
- **LUFS**: perceived loudness. YouTube plays everything at about -14 LUFS, so the render targets that.

```
K=${CLAUDE_SKILL_DIR}/scripts          # python3 (stdlib + ffmpeg); every script has --help
W=<project>/<work>/talking-head        # recipes, sheets, segment cache (timeline.py prints it)
```

## Before you start

- Read `user/preferences.md`: `## talking-head-ffmpeg` and `## general` override the defaults below.
- Settings used (all optional; scripts exit 4 if one they need is missing, then ask and `settings.py set` it):
  `paths.projects_dir` + `project_layout.*` (where drafts / finals / work go), `render.draft_height` (default 1080),
  `render.video_encoder` (auto: VideoToolbox, NVENC or libx264), `paths.broll_library_dir` (library search).
- Check tools: `python3 tools/vidkit/media.py check` (ffmpeg + ffprobe required; nothing else).
- The cut comes first: each take needs aroll-draft's `<stem>.aroll.tb.json` and its `<stem>.transcript.json` next to
  it. If missing, run the **aroll-draft** skill on the take (it transcribes once and writes both).
- A separate mic recording (a lav or desk recorder)? Sync it before aroll-draft:
  `python3 $K/sync_audio.py <take> <recorder file> --wav <work>/synced.wav` (needs numpy). Its sidecar makes the
  renderer use the recorder's sound for that take.

## Steps

1. **Timeline.** `python3 $K/timeline.py <take.mp4> [<pickup.mp4> ...]` (takes in play order; or `--project <name>`)
   -> `$W/recipe_v0.json` + `edited_transcript.md` (the kept words on the finished video's clock, `|` = a jump cut).
   Check aroll-draft's report for unresolved rough seams and list them for the user with timecodes.
2. **Contact sheets.** `python3 $K/sheets.py broll $W/recipe_v0.json` (every non-take clip in the footage folder;
   `--files clip@start-end` adds any clip) and `python3 $K/sheets.py aroll $W/recipe_v0.json` (a tile every 6 s on the
   record clock: where the speaker shows something to the camera).
3. **Plan the bricks.** Read the whole transcript and every sheet, search the b-roll library for what the words need,
   then write `$W/recipe_v1.json` = v0 + `broll` + `needs`. Rules and sources: `reference/broll-planning.md`. Schema:
   `reference/recipe-schema.md`. Ask the user only what the footage cannot answer (one question round).
4. **Lint.** `python3 $K/recipe.py lint $W/recipe_v1.json --fix` until it passes (`recipe.py show` lists every piece).
5. **Draft.** `python3 $K/render_recipe.py $W/recipe_v1.json` -> `<project>/<drafts>/<name>-draft-v1.mp4` (1080p, fast
   hardware encode), then measured QC (frame count, black frames, loudness, true peak, silences; exit 1 on a failure)
   and EditReview's `cuts.json`. Fix any QC error before showing the user.
6. **Hand over** (name every file by absolute path): the draft and which recipe it holds; source length -> cut length,
   keeps, bricks, coverage; every brick as `time -> clip -> why`; `needs` as a shoot list (timecode, the line, a
   suggested shot); the rough seams to listen to. Open the draft (`open <file>` on macOS) or suggest EditReview.
7. **Motion graphics** (optional): the **motion-graphics** skill adds animated cutaways and panels into the next recipe.
8. **Notes rounds:** `reference/notes-rounds.md`. Each round writes `recipe_v(N+1).json`, re-renders only what changed,
   and ends with `review.py changes` so EditReview shows what moved.
9. **Final** (only when the user approves the draft): re-render motion-graphics clips at full size if any (the final
   warns), then `python3 $K/render_recipe.py $W/recipe_vN.json --final` -> `<project>/<finals>/<name>-final.mp4` at
   the source resolution. An existing final is never overwritten: the render stops and says so; pass `--replace` only
   when the user wants the old master replaced. For a YouTube release, the **youtube-release** skill checks loudness on
   the master and writes the paste sheet the user uploads from in YouTube Studio.

## Scripts

| script | does |
|---|---|
| `timeline.py` | cut list(s) + transcripts -> `recipe_v0.json`, edited transcript on the record clock |
| `sheets.py` | b-roll contact sheets (source time) + catalog; a-roll sheets (record time) |
| `recipe.py` | `lint [--fix]`, `show`, `carry` (re-place bricks after the a-roll changed, through the source) |
| `render_recipe.py` | recipe -> draft / `--final` mp4: cached segments, sample-exact a-roll sound, loudnorm, QC, cuts.json |
| `qc.py` | measured QC of any render (also run by the renderer) |
| `review.py` | EditReview: `notes` worksheet, `cuts` and `changes` sidecars |
| `still_clip.py` | a screenshot / chart -> a clip with a slow push-in, ready as a brick |
| `sync_audio.py` | a separate mic recording synced to a take, drift included (numpy) |

## Hard rules

- The draft is local. Never upload; releasing is the youtube-release skill's job, on the user's go.
- Never move, delete or overwrite the user's media. Renders go to the drafts / finals folders; moving a clip into the
  project needs the exact list and a yes.
- Never invent b-roll meaning: a brick shows what the words are about, or it is a `needs` entry.
- No `--final` until the user approves a draft. Never show a draft that failed QC without saying what failed.
- Screenshots and screen recordings: check for private details (addresses, order numbers, notifications) before use.

## What the user can customize

Everything in the rules above is a default. Common changes, recorded as bullets under `## talking-head-ffmpeg`:
coverage level, the no-brick opening length, brick length range, draft height, loudness target (`--lufs` on
timeline.py, or the recipe's `lufs`), always-blur portrait clips. Bigger changes (a true J-cut on the a-roll, HEVC
masters, a colour LUT on every piece: one more filter in `render_recipe.py`'s per-piece chain) go through the
`customize` skill, which edits these scripts in the user's copy.
