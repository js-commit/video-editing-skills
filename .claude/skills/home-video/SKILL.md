---
name: home-video
description: Make a personal montage - vacation, family, pet, birthday or memorial video - from a pile of phone and camera clips. Finds the footage, picks the moments (from contact sheets, or in privacy mode from motion / sound numbers and the user's own picks only), plans a story scored with 2-3 mood-matched songs, renders a draft with one command (ffmpeg; a DaVinci Resolve timeline optional), measures every draft before the user sees it, and iterates on their review notes (EditReview or any player). Use for "make a video of our trip", "holiday montage", "highlight reel from these clips", "family video", "cut the dog's best moments into three minutes", "memorial video for <name>", and for review notes on a montage this skill made. Not for talking-head videos (aroll-draft) or Shorts (shorts).
allowed-tools: Read, Write, Edit, Agent, Skill, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../apps/*/scripts/*), Bash(ffmpeg *), Bash(ffprobe *)
---

# Home video

A montage is a story told with moments and music: who was there, where it went, what was funny,
and how it felt. This skill holds the editorial rules and the order of operations; the scripts
hold the mechanics. Every decision is a file in the project's `work/` folder, so any later
session can resume (`scripts/hv.py` lists them).

```
K=${CLAUDE_SKILL_DIR}/scripts
python3 $K/init_project.py NAME --source DIR --privacy frames|local|no-frames [--subject "..."]
python3 $K/survey.py PROJECT              # clip facts, shake, activity, sound -> work/survey.md (+ sheets)
python3 $K/describe.py PROJECT            # privacy local: the on-device vision model describes every clip -> work/descriptions.md
python3 $K/sheets.py PROJECT --dense ID   # 1 still/s of one clip; --zoom ID 12 15 for a head/tail
python3 $K/beat_walk.py PROJECT           # check picks.json lengths on the beat grid (no render)
python3 $K/make_draft.py PROJECT          # THE one command: walk, lint, stabilize, mix, render, QC, sidecars
python3 $K/review_notes.py PROJECT DRAFT  # the user's EditReview notes -> the shots they mean
python3 $K/make_draft.py PROJECT --final  # the keeper, full size, after the user approves
```

## Before you start

- Read `user/preferences.md`: `## home-video`, `## montage-music`, `## general`. They override
  everything below (shot length, teaser, song count, "I'm experienced, skip the explanations").
- **Privacy mode, asked once.** Personal footage can be sensitive (children, health, homes). Look
  for a `privacy:` bullet under `## home-video`. If there is none, ask once, offering three ways:
  **frames** (Claude reads contact sheets of the footage: the best picks), **local** (only a
  vision model running on this computer looks at frames and describes them; Claude picks from
  its text and the survey numbers; no frame leaves the computer, only those text descriptions; needs
  `python3 tools/vlm-describe/vlm_describe.py --check` to say available, Apple silicon Mac), or
  **no-frames** (nothing looks at a frame; Claude works from motion, sound and timing numbers and
  the user's own picks). For a personal archive of family footage suggest `local` when it can
  run here. Save the answer as `- privacy: frames|local|no-frames` and say so. A project can
  differ when the user says so (`--privacy` on that project).
- Settings: footage comes from a folder the user names, else `paths.home_videos_dir` or
  `paths.inbox_dir`; music from `paths.music_dir`; projects under `paths.projects_dir`. A script
  exiting 4 names the missing setting: ask one short question, save it, re-run.
- Tools: ffmpeg (`python3 tools/vidkit/media.py check`). Optional: vid.stab in ffmpeg (stabilizing),
  librosa (better beat detection), EditReview (reviewing). Install nothing without a yes.

## 0. Brief (ask only what cannot be inferred)

Take what you can from the request, state your assumptions in one line, keep going:
- **Who it is about** (`--subject`): the people and pets the video is for. Anyone else is someone
  you cannot place: a friend or a passer-by. Never drop a shot for who is in it (see People).
- **Must-have moments**, and which one is the **climax** (the big moment the video builds to).
- **Length**: none by default, the footage decides (every distinct moment once). Only when the
  user names one: "five minutes" = 4:45-5:00, "under three minutes" = 2:30-2:55.
- **Shape**: a 10-15 s **teaser** (cold open: the best shots, fast) then the story in shot order,
  by day or chapter. Only an explicit "no teaser" removes it ("chronological" does not).

## 1. Find and stage

- A messy import dump (mixed projects, screenshots, duplicates) goes through `footage-triage`
  first. Otherwise point `init_project.py` at the folder(s): footage is read **in place**, never
  copied or moved.
- `survey.py` gives every clip an id and writes `work/survey.md`: when it was shot, length, size
  (portrait/landscape), shake (median/worst), steady stretches, loud moments, and flags: **copies**
  (a clip sent through a messenger or a cloud backup is re-compressed: look for the original by
  date), portrait, no sound, high frame rate (real slow motion available).
- In privacy `frames` it also writes a contact sheet per clip (`work/sheets/<id>.jpg`, tiles
  labelled with the clip time). In privacy `local` the sheets are written too, but only for the
  local model: never Read them.
- Privacy `local` (optional in `frames`): `describe.py PROJECT` has the on-device vision model
  describe every clip (people seen, setting, action, camera, quality, a 1-5 appeal guess, one
  phrase per sampled frame) into `work/descriptions.md`. One heavy job; resumable.

## 2. Pick: coverage, not a quota

Write one line per clip in `work/notes.md`: verdict (PICK / maybe / skip + why), source ranges,
tags (`[people]` `[unplaced]` `[line: "..."]` `[sound: waves]` `[shaky]` `[portrait]` `[dup of X]`).
Mark the climax candidates and decide the hook (first 3 s), the climax and the ending now.

- **Every distinct scene, view, moment or action, once**, in its best clean take, in shot order.
  Of five angles on one scene keep one or two. When in doubt whether a clean shot is distinct,
  include it. Leave out only near-duplicates, murky / blurry / tilted frames, camera defects and
  weak shots, and say why for each.
- **Ranges end before** the camera drops, whips, zooms into nothing or a finger covers the lens,
  and start after the camera settles. Phone clips: start at 0.3 s or later (late first frames freeze).
- **Video first.** A photo only for a spot no clip shows, one per spot (it plays as a slow push-in).
- **People.** A prominent person you cannot place (faces the lens, fills the foreground) is never
  dropped on identity alone: first try a re-range or a small zoom that keeps the shot without
  them; if the shot only works with them, list it as **held** with the reason, keep it out of the
  draft, and ask the user in the hand-over ("3 shots held: clip X 12-15 s, a man in the foreground..."). A
  thumbs up puts it back. Distant small figures need nothing. Optional, on a Mac with BulkCut
  (`apps/bulk-cut/prebuilt/BulkCut.app`, ready to use): let the user judge the held shots there (`apps/bulk-cut/SPEC.md`, "Recipe:
  shots to check"): each is a purple range they keep (and may trim) or remove; read the answer
  back with `bulkcut.py read`. Works in privacy `no-frames` too: only the user looks.
- **Shaky shots** are the user's call: note `[shaky]`, prefer a calmer stretch or a steadier clip;
  stabilize (`"stabilize": true`) when the user flags it or agrees.

**Privacy `frames`:** read every sheet yourself up to ~25 clips; check exact heads and tails with
`sheets.py --zoom`. More than ~25 clips: one `montage-picker` agent per batch of up to 25 clips
(a day, or part of one), background, at most two at a time; tell the user the agent count first.
Give each the project path, its clip ids, the subject, the must-haves and the output path
`work/picks/<batch>.json`; merge the batches in time order.

**Privacy `local`:** never Read a sheet, still or frame of this footage and never run `sheets.py`
(it refuses). Pick from `work/descriptions.md` (what the model saw: who is visible, the setting,
the action, the camera move, quality flags, appeal, a phrase per sampled frame with its time)
together with `work/survey.md` (steady stretches, loud moments). Ranges: start at a steady,
sharp stretch and use the frame phrases to place the moment; when the model flags "shaky",
"dark" or "lens obstructed" on a frame, keep the range clear of that time. People you cannot
place from the description are held exactly as in `frames`. Say in the hand-over that the picks
came from a local model's descriptions, so the user should expect to move a few ranges in their
notes.

**Privacy `no-frames`:** never Read a sheet, still or frame of this footage and never run
`sheets.py` (it refuses). Pick from `work/survey.md`: capture times give the chapters, steady
stretches give clean ranges, loud moments mark laughs, splashes and voices, activity tells action
from scenery. Ask the user for their must-have moments ("the jump off the dock, second day") and
which clips matter. Transcribe clips only if the user agrees, and only on this computer:
`python3 tools/transcribe.py <clip> --engine voz` (Apple silicon, macOS 26+). Where `voz` cannot
run, say that transcribing means uploading the audio to ElevenLabs and do it only on a yes. Draft 1 is a rough cut by numbers; the user's notes in EditReview do the rest. Say so.

## 3. Story and score before any cut list

Write `work/story.md`: one row per chapter (day, place or event) with its cuts, seconds and mood,
grouped into the story's 2-3 **mood arcs**, one song each. The music comes from the
**montage-music** skill (which tracks, where they start, how loud). The shape (more in
`reference/story.md`):
- **Teaser** 10-15 s of the best shots from anywhere, 2.1-2.5 s each, best shot first, on an
  upbeat cue. Its shots leave their place in the body.
- **Chapters** in shot order, a new song only where the mood turns; a song starts on the FIRST
  shot of its chapter. 2-3 songs for 4-5 minutes, each cue at least 60 s (never under 12 s).
- **Climax**: room before it, a musical hit aimed at it, held a little longer.
- **Ending**: the song's own ending on the last shot (`end_at`), a final hold of 2-2.7 s inside a
  clean stretch.
Post the cue sheet (chapter -> track -> why) with montage-music's samples; build once they pick.

Then write `work/picks.json` (schema: `python3 $K/beat_walk.py --help`): sections in story order,
each with its music and cuts (clip id, in_s, dur, note, plus optional zoom, fit, bed_db, j/l,
stabilize, moment). Check lengths with `beat_walk.py` before rendering.

## 4. Draft N: one command

`python3 $K/make_draft.py PROJECT` walks every section onto its song's beat grid (every cut starts
on a beat), lints the cut list (stops on errors), stabilizes the shots marked `stabilize`, mixes
the soundtrack (montage-music `mixdown.py`), renders `<project>/<drafts>/<name>-vN.mp4` (1080p),
runs QC and writes EditReview's `cuts.json` (and `changes.json` on a notes round). Earlier drafts
stay, each with its own notes.

### Draft rules (each one came from real viewers' notes)

Coverage and people
- [ ] Every distinct scene in, in shot order; nothing cut for length unless a length was asked for.
- [ ] Nobody you cannot place featured: re-range, zoom, or hold for the user's OK.
- [ ] Faces beat scenery: no 30 s stretch without the people it is about. Hold a good shot of a
      person longer than a view.
- [ ] Zoom only as far as the subject needs (every zoom on a same-size canvas upscales; past
      ~1.15x it looks soft).
Pacing
- [ ] Shots 2-3.5 s (a memorial may breathe to 4); longer only when the action is the point.
- [ ] At most 3 shots in a row of one subject; never the same moment twice.
- [ ] Two stretches of one clip back to back read as a flicker: put another shot between.
- [ ] The payoff (the splash, the laugh) inside the cut, on or just after a beat. The last third
      gets cut hardest when something has to go.
Sound
- [ ] The clips' own sound (the "bed") on under the music the whole way, LOW not muted: wind,
      chatter and traffic at `bed_db` -6; `bed_db` +3..6 where the sound is the point (waves,
      a crowd). `bed: false` only for a swear or a cut whose line is a featured moment.
- [ ] Duck the music only under a spoken line worth hearing (`moment` with `duck`, `speech`);
      laughs, barks and splashes sit on top. Never a duck under ~1.2 s.
- [ ] Use J-cuts (`"j": 0.5`: hear the next shot's sound before you see it) into a new place.
Ending
- [ ] Final hold 2-2.7 s inside the clean range; the music ends by itself.

## 5. Review gate: measured QC, then the user

1. make_draft.py already linted and measured the draft (black frames, frozen heads, bars,
   loudness per cue and the steps between them, true peak, the clips' sound against the music).
   Fix every ERROR and re-run before anyone watches. Warnings: look, fix or explain.
2. Hand the draft to the user (section 6). They review it in **EditReview** (or any player and
   send notes as "m:ss what"). Short rounds together are the loop.
3. An agent review (`montage-reviewer`, Opus) runs **only when the user says yes**, at most once
   per version, after you tell them it costs a few dollars of usage. In privacy `local` it gets
   the cut list, QC, survey and `work/descriptions.md`, never frames; in `no-frames` numbers only.

## 6. Hand over

The draft by absolute path, which version it is, and five lines: length; the cue sheet; the
climax treatment; what QC caught and what you fixed; open questions (held shots, copies used,
reverted stabilizations). "Local file, nothing uploaded."
Open it: `open -a EditReview <draft>` (or `open apps/edit-review/prebuilt/EditReview.app --args <draft>`),
or the user's player. Teach the review loop once: play, and when something bugs you type a note
and press Return (SPACE pauses; ↑/↓ jump cut to cut; on later drafts ⌥↑/⌥↓ step through what changed).

## 7. Notes rounds

1. `review_notes.py PROJECT <draft>` maps each note to the shot under the playhead (and the one
   before: people stamp a beat late). Privacy `frames`: look at the frames in question
   (`sheets.py --zoom`); `local`: the frame phrases in `work/descriptions.md` and the numbers;
   `no-frames`: the note text and the numbers. Ask if unclear.
2. Edit `work/picks.json` (keep a copy as `picks_v<N>.json`): only what the notes ask for.
   Everything the user did not note stays as it was; a removed shot shifts the rest by whole beats.
3. **Generalise every note**: "remove that person" means check every cut for them; "too slow here"
   means re-time the whole section; "this song is wrong" goes through montage-music and its taste
   bullet into preferences.
4. Write `work/changes_v<N+1>.json`, one entry per note plus anything else that changed (schema:
   `python3 $K/sidecars.py --help`). A question with no change still gets an entry (`kind: "answer"`).
   make_draft fails on a change the list does not announce: cover it or undo it.
5. `make_draft.py PROJECT` -> v<N+1>. Lasting corrections go into `user/preferences.md` (one bullet,
   say so in one line).

## 8. Final, sharing and archiving (only when the user says it is done)

- `make_draft.py PROJECT --final` renders the keeper at the full canvas size to the project's
  finals folder (`<name>-final.mp4`) and runs the same QC.
- DaVinci Resolve Studio users who want to hand-finish (colour, dissolves, titles):
  `python3 $K/resolve_timeline.py work/cut_vN.json work/mix_vN.wav` builds a new timeline (clips
  on V1 frame-exact, the mix on A1). Free Resolve: import the final mp4, or the clips by hand.
- Uploading is the **youtube-release** skill (on the user's explicit go; the music must be licensed
  for it, see montage-music). Archiving the project is **archive-project**.

## Hard rules

- Footage is read in place: never moved, renamed or deleted. Renders stay inside the project.
- Privacy `no-frames` means no frame, still, sheet or render image of this footage reaches Claude
  or an agent, ever, in this project. Privacy `local` means the same for Claude and its agents;
  only `tools/vlm-describe` (a model on this computer) sees frames.
- No upload, no publishing, no Resolve automation the user did not ask for.

## What the user can customize

Privacy mode, teaser on/off, shot length, song count, loudness (`target_lufs`, `bed_rms_db` in
`work/project.json`), draft size (`render.draft_height`), and every rule above: say "from now on..."
and it goes into preferences, or use the `customize` skill to change this file. Teaching material:
`reference/story.md` (story structure, cutting to the beat, J-cuts, stabilization tradeoffs).
