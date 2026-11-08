---
name: voice-clear
description: Take the room out of an on-camera voice - neural denoise + dereverb with Desert Ant Labs' Clear (a fine-tuned DeepFilterNet 3, Core ML on the Neural Engine, hundreds of times faster than real time, your audio stays on the Mac) - ONLY when the user asks for it. Cleans the takes they name inside a talking-head-ffmpeg render, or a standalone file. Apple silicon Mac, macOS 15+.
when_to_use: Only on the user's own request ("clean this audio up", "clean up my voice", "remove the echo / reverb", "speech enhancement", "studio sound"). Never offered, sampled or rated on your own initiative - their audio is assumed fine until they say otherwise. Not for home videos (music and ambience would be pulled down as noise) and not for a finished mix with music or sound effects.
argument-hint: [clean|mux|reel] <files, folders or recipe>
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(ffmpeg *), Bash(ffprobe *), Read
---

# Voice clear

**Only when the user asks.** Their audio is assumed clean; they say during the edit when a video
needs its voice cleaned. No skill samples, rates or asks about the audio before a render; absent a
request, nothing is cleaned and nobody runs `check`. A standing preference ("always clean my
a-roll") under `## voice-clear` in `user/preferences.md` counts as asking.

`python3 ${CLAUDE_SKILL_DIR}/scripts/voice_clear.py --help` lists everything. The Clear SDK runs
through a small Swift wrapper (`scripts/clearlab`, pinned to desert-ant-core 3.5.0) compiled into
`scripts/bin/clearlab`: a standalone ~1.5 MB arm64 program, committed, so nothing builds on a
normal run; it is signed and notarized. It changes only when the wrapper or the SDK version does:
then `voice_clear.py build` (about 15 s; needs `swift` from Xcode or the Command Line Tools). The
model weights (9 MB) download once into `~/Library/Caches/desert-ant-models`. The SDK sends
Desert Ant Labs a small usage signal (a generated device id, a call count, the program and SDK names, and the OS
name and major version; never audio or text).

## Why this and not EQ

Room reverb is what makes a camera or shotgun mic in an untreated room sound amateur, and no EQ,
compression or treble lift removes reverb; in blind listening they lose to the untouched take.
A dereverb model fixes the actual problem.

- **Variant:** `studio` (default) or `natural`. They are close; studio is a touch more
  processed. Let the user pick in a listening reel if they care.
- **Strength 1.0, always.** A partial blend mixes the reverb back in.
- **Speech only.** Music, sound effects and an app's played-back sound get pulled down, so run
  it on the voice before the mix, never on a finished mix with music.

## Apply (once asked)

- **talking-head-ffmpeg:** the recipe key
  `"voice_clear": {"variant": "studio", "sources": "all" | ["<take file>", ...]}`. The render
  runs Clear once over the joined a-roll (sample-aligned). Keeps from the listed takes play the
  cleaned sound and the rest keep their own; the cleaned ranges are level-matched to the
  originals (Clear lands about 2 dB under), and loudnorm follows. The work files are
  `render_aroll_clear.wav` and `render_aroll_voice.wav` in the recipe's work folder.
- **Anything else** (a loose clip, a voice-over take):
  - `clean IN...` writes `<stem>.clear.wav` (mono 48 kHz, sample-aligned, not normalised) into
    the project's `<work>/voice-clear/` when the input is inside a project (archive-project deletes
    the work folder with the rest), else beside the input.
  - `mux VIDEO` writes `<stem>.clear.mp4`: video stream-copied, voice cleaned, loudnorm -14.
- DaVinci Resolve users: Resolve Studio has its own Voice Isolation. Clear is the choice when
  the edit is in the ffmpeg pipelines or the user prefers it; do not run both on one take.

## Where files go

- **Renders:** the project's work folder (settings `project_layout.work`).
- **Listening reels:** the project's drafts folder; `--out-dir` for a clip outside a project.
- **Cache** (settings `paths.cache_dir`, default `user/cache/voice-clear/`): `clean/` holds
  cached cleaned takes, pruned after 30 days unused; `rounds/` the listening reels' keys.
- **Model weights:** `~/Library/Caches/desert-ant-models/.../clear`, 9 MB.

## Listening tests (a new mic or room)

```
voice_clear.py reel CLIP --window 12.0-24.5 --window 150-162 [--variants original,studio,natural]
voice_clear.py reveal <round>
```

The reel is blind and loudness-matched, with the original as a control and the same numbers in
every window. `reveal` prints the key, then deletes the reel and its work files. Confirm
headphones before the user listens, and never hint at which number is which.

## Not on this computer

`voice_clear.py` exits with the reason when it cannot run here (Intel Mac, Windows, Linux, or
macOS older than 15). Say so and offer the alternatives: Resolve Studio's Voice Isolation, or a
desktop tool of the user's choice; nothing here uploads audio to a service.
