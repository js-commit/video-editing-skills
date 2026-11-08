# Transcription

Most skills need to know what was said and exactly when: aroll-draft cuts on
words (and on every "um" and "uh"), shorts and thumbnails quote you, chapters
come from the transcript. So each video or audio file is transcribed **once**,
word by word, and the result is kept next to it as `<name>.transcript.json`.
Every skill reuses that file; nothing is transcribed twice.

```sh
python3 tools/transcribe.py /path/to/clip.mp4     # makes or reuses clip.transcript.json, prints its path
python3 tools/transcribe.py --check               # which engines can run on this computer
```

You normally never run this yourself: the skills do it when they need it.

## Two engines

An *engine* is the speech-to-text program that does the listening. There are
two, both chosen because their word times hold up when a cut lands on a word.
Pick one with `python3 tools/vidkit/settings.py set transcription.engine <name>`
(the `setup` skill asks you); `--check` shows which are ready here.

| Engine | Where it runs | Cost | Fillers (um/uh) and word times |
|---|---|---|---|
| `elevenlabs` | ElevenLabs' servers (the audio is uploaded) | ElevenLabs account: free tier, then per minute of audio | **Best.** Keeps nearly every filler; precise word times. The engine for anything that cuts or shows words |
| `voz` | your Mac, offline (Apple silicon, macOS 26 or newer) | free | Good words, sharp word times (Voz + Align on the Neural Engine); keeps about half the fillers. A 16-minute take in a few seconds |

**Short version:** if you cut talking-head videos with aroll-draft, use
`elevenlabs`: the free tier covers a lot of a-roll, and the cuts are cleanest.
On a Mac, `voz` is the free, private, instant engine for everything that only
needs to know what a clip is about (sorting footage, home videos, b-roll
context), and the fallback for cutting when a take must not leave the
computer.

**Why fillers matter.** aroll-draft removes "um", "uh", false starts and
retakes by cutting around those words. A filler that is not in the transcript
cannot be cut, so with `voz` expect to trim a few more by hand.

**Why not Whisper?** Whisper-family models were trained to write tidy text:
they drop fillers, and on noise or silence they invent words. Both break
word-precise cutting, so they are not offered here.

**Cutting-grade vs. sorting-grade.** A transcript remembers which engine
made it. A `voz` transcript is reused whenever `voz` is asked for; when `elevenlabs` is
asked for, a `voz` transcript is moved aside (kept, not deleted) and the file
is transcribed again. Skills use your default engine unless told otherwise, so
with `voz` as the default, aroll-draft cuts on `voz` words (fewer fillers to
cut). For one take on ElevenLabs, say "use ElevenLabs for this one" (aroll-draft
runs `prepare.py <video> --engine elevenlabs`); to cut every take on it, make
`elevenlabs` the default.

**Cost and privacy.** With `elevenlabs`, only audio is sent: the tools extract
a small 16 kHz mono copy first, never the video. Check ElevenLabs' current
free-tier allowance and per-minute price on their site. `voz` never uploads
anything; it downloads its model (about 470 MB) the first time it runs.

Language: set `transcription.language` (e.g. `en`, `es`) or leave it empty to
auto-detect (`voz` then uses English); `--language` overrides it for one run.

## ElevenLabs: setting the API key

1. Create an account at elevenlabs.io (the free tier is enough to start), then
   make an API key (your profile > API keys). If it lets you limit the key,
   allow only speech-to-text.
2. Put the key in an **environment variable** called `ELEVENLABS_API_KEY`.
   Never paste it into a file inside this repo.

**macOS** (zsh, the default shell):
```sh
echo 'export ELEVENLABS_API_KEY="paste-your-key-here"' >> ~/.zprofile
```
**Linux** (bash):
```sh
echo 'export ELEVENLABS_API_KEY="paste-your-key-here"' >> ~/.bashrc
```
**Windows** (PowerShell or Command Prompt):
```
setx ELEVENLABS_API_KEY "paste-your-key-here"
```
(or Settings > System > About > Advanced system settings > Environment Variables).

Then close the terminal, open a new one and start Claude Code again from it:
programs only see variables that existed when they started. Check with
`python3 tools/transcribe.py --check` ("elevenlabs": available true).

## voz: nothing to install

`voz` is a small program shipped with this repo (`tools/bin/voz-engine`, source
in `tools/voz-engine/`) that runs [Desert Ant Labs'](https://github.com/Desert-Ant-Labs/desert-ant-core)
Voz and Align models on the Neural Engine. Requirements: an Apple silicon Mac
(M1 or newer) on macOS 26 or newer. The first run downloads the model into
`~/Library/Caches/desert-ant-models` (about 470 MB); after that it works
offline. Your audio and transcripts never leave the Mac. When online, the SDK
sends Desert Ant Labs a small usage signal (a generated device id, a call
count, the program and SDK names, and the OS name and major version; never audio
or text).

```sh
python3 tools/vidkit/settings.py set transcription.engine voz
```

Windows and Linux have no offline engine here; use `elevenlabs`.

## Good to know

- **Reuse.** A transcript is reused as long as its media file is unchanged.
  If you re-export the file, the old transcript is renamed
  `<name>.transcript.stale-<time>.json` (kept, not deleted) and a new one is
  made. `--force` re-transcribes on purpose (also keeping the old one).
- **Read-only folders** (a camera card, a locked network share): the
  transcript is saved in the cache folder instead (`paths.cache_dir`, default
  `user/cache/transcripts/`); the tools find it there.
- **Already have a transcript?** `--import FILE` turns it into the sidecar
  without transcribing again: ElevenLabs API JSON, voz-engine JSON, or any
  segments-with-words JSON (as saved by several editing and transcription
  apps).
- **Moving files.** Move `<name>.transcript.json` along with its video (the
  skills that move media do this for you).
- **The file format** (for anyone writing a skill): `segments` are sentences,
  each with `words` holding `start`, `end` (seconds) and `word`; splitting a
  segment's `text` on spaces gives exactly its words; `_meta.engine` names the
  engine. Python:
  `from vidkit.transcript import ensure_transcript, load_transcript, words`.
