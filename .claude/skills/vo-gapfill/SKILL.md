---
name: vo-gapfill
description: Fill an a-roll gap with a generated voiceover. Writes a short VO script in the speaker's own on-camera voice (from the take's transcript sidecar), has the user's text-to-speech service synthesize it (a cloned voice if they have one; through its website in the Chrome extension or its API), tightens the TTS pauses to YouTube pacing, files the clip under the project's audio folder, and inserts it into the DaVinci Resolve timeline at the gap, rippling the tail so everything fits (or hands the tight take to a talking-head-ffmpeg recipe). Use when the user says "do a voiceover for that gap", "fill in the gap", or hands over talking points for a section with no real a-roll.
argument-hint: [talking points or marker name]
allowed-tools: Read, Write, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *), Bash(ls *), Bash(date *)
---

# VO gap-fill

Turns the user's talking points into a placed voiceover: script → TTS → audio clip in the
project → inserted in the Resolve timeline gap (or into a talking-head-ffmpeg recipe).
Runs whenever a gap in the timeline needs narration: leave a marker at the gap (its note can
hold the talking points) and this fills it. B-roll to cover the gap visually is a different skill
(broll-brick-layer) and happens later; the gap stays visually empty here.

## 0. Which TTS

Read `user/preferences.md` `## vo-gapfill`. The first time, ask what the user uses and save it:

- **A cloned voice on a TTS website** (ElevenLabs, MiniMax and others offer voice cloning):
  the natural match for an a-roll gap. Driven through the Claude in Chrome extension; the
  user is signed in; generation spends their credits. Save the site, the voice name and the
  settings that matter (model, speed, emotion) as bullets.
- **ElevenLabs' API** when they already have a key for transcription: the same account does
  TTS. Save the voice id; then generation is a curl, no browser.
- **No TTS**: say so and offer to write the script for them to record themselves.

Cloning a voice needs a few minutes of clean reference audio of the speaker; keep those
takes in one place the user names (never copied into projects).

**Only the user's own voice, or one whose owner gave written permission.** Never clone or
generate anyone else's voice, and never put words in a real person's mouth they did not
approve. A voiceover in someone else's cloned voice (even with permission) is altered or
synthetic content: say so, so the upload's disclosure is answered yes
(`youtube.contains_synthetic_media` or the paste sheet). Cloning your own voice for your own
voiceover needs no disclosure.

## 1. Write the script in the speaker's voice

- Source material: the talking points (chat or the gap marker's note) + the take's
  transcript sidecar (`<stem>.transcript.json` next to the footage) to match register.
- It is SPOKEN TO AN AUDIENCE, not written: contractions ("I wanna", "I'm gonna"), short
  direct sentences, the speaker's own vocabulary from the transcript.
- **No em dashes.** Commas and periods create real pauses in the TTS; use them only where a
  pause is wanted; prefer restructuring over comma-splicing.
- Length: cloned voices read fast (about 4 words per second at speed 1.05; recalibrate from
  the first generation). The placement script resizes the gap to fit, so don't contort the
  script to hit the gap length.
- Spell for the ear: "M four" not "M4", "R P Ms" not "RPM"; a question mark mid-sentence
  moves the lift, so end the question at the sentence end.
- **Append a sacrificial outro line** ("Thanks for watching, and I will see you in the next
  video.") when the service is known to clip the last second; it is trimmed off the decoded
  WAV afterwards. Say so when generating, so the line in the text box is not a surprise.
- Show the final script text in the report: regeneration is cheap and the user often wants
  one wording tweak.

## 2. Generate

Website route (Chrome extension): reuse the session's tab; settings persist per tab, so
verify them once per session, not per generation. Set the voice, model, speed (and any
emotion control the site has; "happy" reads noticeably better for an upbeat channel),
paste the script, generate, download (MP3 or WAV) to `~/Downloads`. The text box has a
character cap (5,000 on some services): a long script goes in chunks of one or two
paragraphs, each with its own sacrificial line. Clear the box between chunks and check the
character count before generating: a paste on top of old text is the common failure.

API route: the service's text-to-speech endpoint with the saved voice id, MP3 out.

Decode to WAV and hard-trim at the end of the real script's last word before step 3; do
every trim on the decoded WAV (MP3 `-ss`/`-c copy` trims are VBR-sloppy by up to a second).

## 3. Tighten the pauses (always, before import)

TTS paces like an audiobook; YouTube wants tighter gaps.

`python3 ${CLAUDE_SKILL_DIR}/scripts/tighten_vo.py <clip>` detects silences (-35 dB) and cuts
every pause longer than 0.35 s down to 0.25 s (the cut sits inside the silence, inaudible).
Writes `<stem>.tight.wav` (PCM, no second lossy encode) next to the input; the raw download
stays for reference. **The .tight.wav is what gets imported and placed.** Sanity: the
shortened-pause list should line up with the sentence boundaries of the script.

**Verify the words.** Transcribe the tight take (`tools/transcribe.py`) and diff it against
the script. A dropped small word ("always on display" heard as "always display") can be the
transcriber's: check a 5 s snippet with the other engine before regenerating. A wrong word:
regenerate the sentence alone and splice it in at the quietest 20 ms of the pauses around it.

## 3b. File the clip in the project

- Destination: the project's audio folder (settings `project_layout.audio`, default `audio/`).
- Rename descriptively (generated names are random): `vo-<topic>.mp3` / `.tight.wav`.
- Write the exact script text next to it as `<same-stem>.txt`: the record of what the clip
  says, and the input for regeneration.

## 4. Insert into the timeline (DaVinci Resolve Studio)

`python3 ${CLAUDE_SKILL_DIR}/scripts/place_vo.py job.json`, job fields:

```json
{
  "project": "my-video",
  "timeline": "aroll draft",
  "never_touch": ["my-video backup", "my-video original"],
  "audio_path": "/abs/path/audio/vo-intro.tight.wav",
  "bin": "audio",
  "marker_name": "VO: intro",
  "tail_pad_s": 0.5,
  "slack_s": 1.0
}
```

What it does (in order):

1. Refuses `never_touch` timelines; **duplicates the timeline to `<name> pre-vo backup`
   first** (the user deletes it after review).
2. Finds the gap: marker (by name substring) = gap start; the earliest item start after it
   on ANY track = gap end. Errors if anything overlaps the gap start. The gap may be
   ZERO-WIDTH (marker exactly at a cut boundary: a new gap is opened by rippling, which is
   how a VO is INSERTED mid-timeline), and a marker at/past the last item means
   append-at-end (no ripple).
3. Measures the audio and **resizes the gap to fit** (VO length + `tail_pad_s`, skipped
   when the VO already fits within `slack_s`): every item starting at/after gap end, on
   every track, is delete + re-appended shifted by the delta (the Resolve API has no move
   operation). Linked V/A pairs re-append as one, clip-enabled state, transform properties
   and markers past the gap ride along.
4. Imports the audio into the named bin (skipped if already in the pool) and appends it at
   gap start on the first free ENABLED audio track (muted tracks are skipped; adds a track
   if needed).
5. Stamps the gap marker's note with what was placed, saves, verifies the item count after
   the save, and prints a JSON summary.

Verify after: a screenshot of the timeline at the gap (`vidkit.resolve.resolve_window_id()`).
The user edits the timeline between visits: never assume the placed VO, the gap or clip
positions match the last run; re-read live state before touching anything.

**No Resolve** (talking-head-ffmpeg): skip `place_vo.py`. The tight take is an a-roll keep
with its own sound in the recipe (`aroll[]` entry with the VO file and a `gain_db` to level
it), or the sound of a chart / still insert; the cut points come from transcribing the
TIGHT take (the raw take's times are before the pauses were cut).

## Review notes on a voiceover: pickups by paragraph

Put every changed paragraph in ONE generation (with one sacrificial line), then rebuild the
master from rows of (source take, first words, last words), cutting each paragraph at the
quietest 20 ms of the pause before and after it. Pieces join with no added silence and keep
the voice's rhythm; approved paragraphs keep their audio. When only the end of a paragraph
changed, keep the earlier take's sentences and start the new take at the first changed
sentence. Diff the joined master's words against the script before placing it.
