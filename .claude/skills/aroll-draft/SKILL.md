---
name: aroll-draft
description: Raw talking-head take -> first-cut edit with no human in the loop. Transcribes the take once (word-level), has Claude editors cut retakes, false starts, mic checks and filler chunk by chunk, runs a revision pass, snaps every cut to the waveform so no word is clipped, flags hidden retakes and long pauses for review, and delivers a cut list (TimeBolt / Video Haircut format), a revision file, a DaVinci Resolve timeline (built directly in Resolve Studio, or XML/EDL to import) and an optional preview MP4. Works for any spoken language. Use when asked to "draft this a-roll", "make a first cut", "auto-edit this video", "haircut this video" (Video Haircut users), "cut the retakes / silences out of this take", or to turn raw talking-head footage into a rough cut.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Read, Agent
---

# A-roll draft

**What it makes.** A-roll is the footage of you talking to camera. A *first
cut* (rough cut) keeps your best take of every sentence, in order, with the
mistakes and dead air removed; b-roll, music and polish come later. From one
raw take this skill writes, next to the video:

- `<stem>.aroll.tb.json`: the cut list (keep/remove spans; opens in Video Haircut / TimeBolt)
- `<stem>.aroll.revision.json`: the transcript with `"cut": true/false` per word (Video Haircut `user_revision` format)
- `<stem>.aroll.xml` + `<stem>.aroll.edl`: the timeline for DaVinci Resolve
- optionally `<drafts folder>/<stem>.aroll_draft.mp4`: a preview render

`S` below is `${CLAUDE_SKILL_DIR}/scripts`, `REPO` is `${CLAUDE_SKILL_DIR}/../../..`.

## Before you start

1. Read `REPO/user/preferences.md` (`## general`, `## aroll-draft`). The
   `## aroll-draft` bullets are injected into the editor and reviser prompts
   automatically; map taste onto script flags with
   [reference/tuning.md](reference/tuning.md) ("tighter", "more air"...).
2. `python3 REPO/tools/vidkit/settings.py get editor.nle` (exit 4 = unset: ask
   "Do you edit in DaVinci Resolve Studio, the free DaVinci Resolve, or
   neither?" and save `resolve-studio` / `resolve-free` / `none`).
3. Tell the user in two lines what is about to happen and roughly how long
   (transcription runs about 2-10x faster than real time; the edit a few
   minutes per 10 minutes of footage).

## Steps (in order; every script prints JSON on stdout)

1. **Prepare**: `python3 S/prepare.py <video>` probes the take, transcribes it
   once with the default engine (reuses `<stem>.transcript.json`), extracts
   `audio_16k.wav` and plans the chunks. Add `--engine elevenlabs` when the user
   asks for ElevenLabs on this take (it replaces a `voz` transcript). Exit 4 = no transcription engine set: ask, `settings.py set
   transcription.engine <name>`, re-run. (A transcript the user already has
   from another app works too: `python3 REPO/tools/transcribe.py <video> --import <file>`,
   then re-run.) Note `work` and `num_chunks` (WORK below).
2. **Edit, one chunk at a time, never in parallel** (chunk N's prompt carries
   chunk N-1's edited tail). For N = 1..num_chunks:
   - `python3 S/chunks.py prompt WORK/edit N`
   - Spawn an **aroll-editor** agent (wait for it) with exactly:
     "Prompt file: WORK/edit/chunk_NN.prompt.md — write your edit to WORK/edit/chunk_NN.edited.json"
   - `python3 S/chunks.py validate WORK/edit N`. Exit 3: spawn the editor again
     with the validator's stderr appended ("your previous answer failed
     validation: ..."). At most 2 retries, then stop and report.
3. **Merge**: `python3 S/chunks.py merge WORK/edit WORK/transcript.json -o WORK/revision.json`
4. **Revise** (at most 3 rounds, R = 1, 2, 3):
   `python3 S/review.py pack WORK/revision.json -o WORK/review_R.md`, spawn an
   **aroll-reviser** (wait): "Review file: WORK/review_R.md — write corrections
   to WORK/corrections_R.json". `[]` = done; else
   `python3 S/review.py apply WORK/revision.json WORK/corrections_R.json`
   (exit 3 = some skipped as ambiguous; fine) and loop.
5. **Snap the cuts to the waveform**:
   `python3 S/smooth_cuts.py WORK/revision.json <video> --wav WORK/audio_16k.wav -o WORK/<stem>.aroll.tb.json`
   (plus any flags from preferences). `word_crossing_boundaries` and
   `hard_seams_unresolved` should be 0; anything else is a review point (it
   lands in the report with its timecode), never something to hide.
6. **Hidden retakes**: `python3 S/flag_retakes.py <video> --cuts WORK/<stem>.aroll.tb.json --json WORK/retake_flags.json`
   (exit 2 = there are spans to audition; that is not an error). A transcription
   engine can write a sentence that was read twice in a row ONCE, timed to the
   first (flubbed) read, so the pause and the whole second read hide inside one
   stretched word: invisible to the transcript, the editors and the reviser. The
   script flags stretched words (> 1.2 s) with sound in their tail that survive
   into the cut. List every flag in the report for the user to audition; never
   cut one on your own. When the run must finish unattended (a voiceover read
   going straight into a render): cut the flagged span out of the source with
   ffmpeg, transcribe it with `python3 REPO/tools/transcribe.py <span.wav> --engine voz`
   (Apple silicon; it splits what the other engine glued, with word times),
   render each candidate seam (`atrim` + `concat`), transcribe those, and keep
   the one that reads as one clean sentence. Still list the seam for the user to
   audition.
7. **Deliver**: `python3 S/deliver.py WORK <video>` copies the cut list and
   revision next to the video, writes the `.xml`/`.edl` and `WORK/report.md`.
8. **Hand it over** by `editor.nle`:
   - `resolve-studio`: ask the user to open DaVinci Resolve (never launch or
     quit it yourself), then `python3 S/resolve_timeline.py single <video> --report WORK/report.json`.
     It builds the timeline "<stem> first cut" with a marker on every review
     point. Then run the seam and flicker gate
     ([reference/multicam.md](reference/multicam.md), *Seam and flicker gate on a
     built timeline*): both audits must report 0. No preview render unless asked.
   - `resolve-free`: give the import steps from [reference/reviewing.md](reference/reviewing.md)
     (File > Import > Timeline, the `.xml`). Render the preview only if asked.
   - `none`: `python3 S/render_draft.py WORK/<stem>.aroll.tb.json <video>`
     (preview in the drafts folder), then suggest the talking-head-ffmpeg skill
     for b-roll and the finished edit.
9. **Report**: raw length -> first-cut length, clips, words cut, output paths
   (absolute), and every line of `WORK/report.md` under "Review points" in
   first-cut time, plus its "Left in on purpose" fillers (glued to the next
   word, so cutting them would clip speech; the user trims them by hand if
   they care). Then teach the review in a few lines: what to listen for
   and the keys to use ([reference/reviewing.md](reference/reviewing.md)), and
   remind them shortcuts can be changed. Skip the teaching if preferences say
   they are experienced.

Two cameras on the same take, rebuilding a cut from a sequence, and the seam
gate on a built timeline: [reference/multicam.md](reference/multicam.md).
Scoring a draft against the user's own hand edit:
[reference/scoring.md](reference/scoring.md). File formats:
[reference/pipeline-formats.md](reference/pipeline-formats.md) (load when
debugging a stage).

## Hard rules

- Never edit chunks in parallel and never let an unvalidated chunk through.
- Transcribe once: the sidecar next to the video is reused by every later run
  and every other skill. Re-running a later stage never re-transcribes.
- The editor only wraps words in tildes; it never rewords. Do not change the
  tilde protocol or the validator.
- Never auto-cut a long quiet stretch inside a kept passage, or a retake flag
  (silence between sentences is trimmed normally): dead air and a silent demo
  look the same to a script, and where a hidden second take starts is
  exactly what the transcript lost. They go to the user as review points
  (an unattended run resolves a retake flag only as step 6 describes).
- Keep the user's taste in their preferences, not in this file; a correction
  that should last becomes one bullet under `## aroll-draft` (say so in one line).
- Non-English takes work the same way: the prompts stay English and the
  editors are told the language; words are never translated.

## What the user can customize

- Taste ("tighter", "more air between sentences", "keep my tangents", "cut
  every um"): a bullet under `## aroll-draft` in `user/preferences.md`; the
  mapping to flags and prompt wording is in [reference/tuning.md](reference/tuning.md).
- Speed vs cost: the `aroll-editor` / `aroll-reviser` agents run on Opus at
  `effort: xhigh` for the best cut. Lower `effort` (or the model) in
  `.claude/agents/aroll-*.md` to make drafts faster and cheaper.
- The editing rules and examples: `reference/edit-prompt.md` (keep the
  `{{PREFERENCES}}`, `{{LANGUAGE}}`, `{{CONTEXT}}`, `{{TRANSCRIPTION}}` slots).
