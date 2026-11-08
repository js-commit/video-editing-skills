---
name: unboxing-cut
description: Cut a long overhead unboxing, case install or screen-protector install take into a paced, ASMR-style YouTube unboxing sequence. The box is shown first, then the knife / tear / shrink-wrap / peel sounds trimmed on the waveform with buffers, a hold on every product (keeping a side-to-side turn) and the dead time cut. The sequence is delivered as SEPARATE numbered b-roll library clips, one per beat, which rebuild it when laid back to back. Use when asked to "cut the unboxing", "make an unboxing sequence", "salvage the unboxing / screen protector install", "rapid edit of the unboxing", "extract the interesting parts of this unboxing", or when a finished project's unboxing and install takes should reach the b-roll library.
argument-hint: [take(s) or moments file]
allowed-tools: Read, Write, Agent, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../broll-library/scripts/*), Bash(ffmpeg *), Bash(ffprobe *)
---

# unboxing-cut

A long overhead take of an unboxing, case install or screen-protector install goes in. A
paced sequence of separate clips comes out: one per beat, numbered in playback order, each
with its own description and contact sheet in the b-roll library (`broll-library`), so every
beat is searchable alone and the sequence plays back from the index order.

## The editorial rules

- **Show the box first.** Then the opening, kept for its **sound**: the knife on the tape,
  tearing a seal, shrink wrap, peeling film, a lid sliding off. The goal is an ASMR-style
  pace: brisk, but never rushed.
- **Pause on every product** as it comes out. If the hands turn it side to side, keep that
  motion for a bit.
- **Cut the dead time:** moving stuff away, an empty frame, nothing happening.
- **Separate clips, not one long clip.** Each beat is its own library entry;
  `sequence_start` / `sequence_end` give the beat's place in the sequence.
- **Pace = `steady`** by default (`paces.json`; `relaxed` and `brisk` are there to compare:
  on one phone unboxing they came out 54 s / 43 s / 29 s). A standing choice goes under
  `## unboxing-cut` in `user/preferences.md`.
- **Narration over an unboxing:** `"speech": "mute"` on that source. The words are
  silenced and the sounds between them kept. Ask once on the first narrated take.

## Pipeline

`S=${CLAUDE_SKILL_DIR}/scripts`. Needs ffmpeg, numpy, scipy and Pillow (`python3 -m pip
install numpy scipy pillow`; ask before installing). One ffmpeg-based command at a time.

1. **Find the takes.** Unboxings and installs often sit in a-roll folders (narrated, or
   filmed as the talk). Check every take whose name or transcript says unbox, install,
   protector or case. `overview.py VIDEO --step 3 -o DIR [--flip]` prints timestamped sheets
   with each tile's sound drawn under it: grey for the full band, orange for 3-10 kHz.
2. **Map each take into a moments file.** Follow `reference/moments-brief.md`: kinds
   establish / sound / action / hold, `hero`, sections, a one-sentence description per beat,
   and the never-keep list. Map it yourself, or give each SEQUENCE to one agent with that
   brief (a general-purpose agent, Sonnet at high effort is enough). A sequence often spans
   several takes (the box shots, the opening, the install, the result were filmed as
   separate files): give one agent all of them as sources A, B, C... in filmed order.
   Agents run in parallel; only one ffmpeg-based command at a time (wrap each in a shared
   `lockf -k <lock> ...` on macOS, `flock` on Linux).
3. **Preview + QC (the editorial gate).**
   `sequence.py MOMENTS --pace steady -o <project drafts folder>/unboxing/<name>-steady.mp4`
   renders the 1080p assembled preview. It also writes `.plan.json` and `.review/cuts.json`,
   so EditReview names the beat under each note. Then `qc_sheet.py PREVIEW` shows each beat's
   first, middle and last frame. Read every page before the user sees anything: that is how
   a 0.3 s flash of a cable plug gets caught.
4. **The user watches the preview** (EditReview or any player) and sends notes. Fix the
   moments file and re-run 3 until they are happy with the pace and the beats.
5. **Export.** `export_clips.py PLAN --slug <library slug> [--start-index N]` cuts each beat
   frame-exact into `<library>/footage/<slug>/NNN_<label>.mp4` (H.264, the beat's audio as the
   preview carried it) and files each in the catalog with its description, tags, contact
   sheet and sequence fields. `--dry-run` lists the clips first. Re-running replaces a beat
   whose range changed. A wrong beat afterwards: `broll-library/scripts/catalog.py remove <id>`
   (dry run, then `--apply`), fix the moments file, re-run.
6. **Optional review in BulkCut** (macOS, `apps/bulk-cut`): open `<library>/footage/<slug>/`
   there to trash a dud or trim a clip, then `catalog.py check --apply` drops the removed
   ones from the index.

## How the beats are cut (sequence.py)

- **Sound events** are 20 ms frames where the 3-10 kHz band rises 9 dB over the source's
  quiet floor, or the full band rises 12 dB (a card tab tearing is mostly low-mid). Gaps
  under 0.25 s merge. Transcript words are masked out first, so on a narrated take only the
  sound BETWEEN the words is an event.
- A `sound` / `action` beat keeps the first event to the last event plus the pace's pre /
  post buffers, capped at the pace's max. Past the cap it takes the busiest window. With no
  events it keeps the head of the moment. `hold` / `establish` keep the head up to their max
  (`hero_max` for hero holds).
- **Cut points:** every cut moves, by at most `snap`, to the quietest 20 ms nearby, and never
  splits a spoken word (off under `speech: mute`, where the word is silent anyway). A named
  beat is never dropped for being short; it grows to `min_beat` inside its moment.
  Overlapping moments from one take never repeat a frame, and touching ones merge into one
  clip. No beat runs past the last frame of its take.
- **Audio:** each clip fades over 10 ms at both ends, so clips placed back to back don't click.
- **Speech mute** silences each word, padded by 80 ms and bridged across gaps under 0.25 s,
  and fills the hole with the beat's own room tone instead of digital silence. Check a muted
  preview by transcribing it (`tools/transcribe.py`, the offline engine if you have one)
  before export: untranscribed fillers ("all right", "okay") can still get through.

## Sources that need settings

- **Upside-down rigs:** `"flip": true` on the source. The clips get rotated 180°.
- **Transcript from another camera:** `"transcript_offset"` = this camera's time minus the
  transcript's. Measure it by cross-correlating 60 s of both cameras' audio at 8 kHz.
- **Transcript:** the take's `<stem>.transcript.json` sidecar (`tools/transcribe.py`).

## Files

- `paces.json`: the relaxed / steady / brisk profiles.
- `reference/moments-brief.md`: the mapping brief, used as an agent prompt.
- `scripts/overview.py`: timestamped sheets with sound.
- `scripts/sequence.py`: plans the beats, renders the preview, writes `cuts.json`.
- `scripts/qc_sheet.py`: the QC sheet.
- `scripts/export_clips.py`: the library clips and their catalog records.
