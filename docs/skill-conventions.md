# Skill conventions

How the skills in this repo are built, so they stay small, consistent and easy
to change. Read this before writing or editing a skill (Claude does too).

## Layout

```
.claude/skills/<skill>/SKILL.md        the instructions Claude follows
.claude/skills/<skill>/scripts/        the skill's own scripts (Python 3.9+)
.claude/skills/<skill>/reference/      longer docs the skill loads only when needed
.claude/agents/<agent>.md              subagents a skill spawns (one job each)
tools/vidkit/settings.py               the user's setup (paths, editor, engines)
tools/vidkit/media.py                  ffmpeg/ffprobe helpers, encoder choice, HEVC hw decode
tools/vidkit/resolve.py                DaVinci Resolve scripting helpers
tools/vidkit/transcript.py             transcript sidecars (read / ensure)
tools/transcribe.py                    word-level transcription CLI (ElevenLabs Scribe, voz)
tools/voz-engine/, tools/bin/          the offline transcription engine (Apple silicon)
tools/release/sign_release.sh          maintainer: rebuild, sign and notarize every prebuilt macOS program
tools/vlm-describe/                    the on-device vision model for private footage (Apple silicon)
user/settings.json                     the user's answers (not committed)
user/preferences.md                    the user's standing preferences (not committed)
apps/edit-review/                      EditReview, the macOS review app (optional)
apps/bulk-cut/                         BulkCut, the macOS footage-triage app (optional)
docs/                                  human docs (setup, shortcuts, NAS, folders)
```

Claude Code runs from the repo folder, so skills are project-scoped. Inside a
SKILL.md, `${CLAUDE_SKILL_DIR}` is the skill's folder and the repo root is
`${CLAUDE_SKILL_DIR}/../../..`.

## The skill list (names are stable: other skills refer to them)

| Skill | What it does |
|---|---|
| `setup` | First-run onboarding: checks tools, asks where things live, writes settings. Re-runnable. |
| `customize` | Remembers preferences and changes skills to fit the user ("from now on…", "change how X works"). |
| `editing-coach` | Teaches editing: talking heads, pacing, b-roll, audio, color, stop motion, Resolve basics, shortcuts. |
| `new-project` | Creates a project folder from the user's layout. |
| `aroll-draft` | Raw talking-head take -> first-cut edit (cut list, Resolve/XML/EDL exports, preview). The flagship. |
| `multicam-angles` | Picks the camera angle per cut on a two-camera Resolve timeline. |
| `broll-brick-layer` | Lays b-roll onto a cut a-roll timeline in Resolve; seam/flicker audits. |
| `resolve-export-draft` | Renders the current Resolve timeline to a draft file. |
| `talking-head-ffmpeg` | The no-Resolve edit: cut + b-roll as a JSON recipe rendered by ffmpeg. |
| `motion-graphics` | Animated overlays/cutaways timed to the words, rendered in a headless browser. |
| `edit-review-notes` | Turns timestamped review notes (EditReview `notes.json`) into timeline changes. |
| `broll-library` | Harvests b-roll from finished projects into a searchable library; searches it. |
| `footage-triage` | Sorts an import dump into projects / home videos / b-roll / trash, with a review page. |
| `archive-project` | Archives a finished project (lean: finals + b-roll only, or keep everything). |
| `youtube-release` | Title, description, chapters, loudness, and a paste sheet for uploading by hand in YouTube Studio. |
| `youtube-thumbnails` | Thumbnails from real footage (plus optional AI), privacy + legibility check. |
| `ship-it` | One command from approved draft to published video, in the user's order. |
| `shorts` | Vertical Shorts from a long-form video (ffmpeg default, Resolve optional). |
| `home-video` | Vacation / family / pet montages from phone and camera clips. |
| `montage-music` | Fits music the user has rights to onto a montage (beats, in-points, levels). |
| `stabilize-clips` | Smooths shaky clips with ffmpeg (vidstab). |
| `voice-clear` | Dereverb / denoise of an on-camera voice, on the user's request (Apple silicon). |
| `vo-gapfill` | A generated voiceover for a timeline gap: script, TTS, tightened pauses, placed. |
| `studio-thumbnails` | Ask Studio and Gemini thumbnail rounds into the youtube-thumbnails pool. |
| `unboxing-cut` | An overhead unboxing/install take -> paced beats filed as separate library clips. |
| `camera-ab-compare` | Two-camera side-by-side comparison video in Resolve Studio. |
| `aroll-benchmark` | Dev harness: scores aroll-draft against a hand-made cut. |

## Settings: ask once, remember, never block

- Read settings through `tools/vidkit/settings.py` (Python: `settings.get(...)`,
  `settings.get_path(...)`, shell: `settings.py get <key>`). The keys and their
  meaning are in `docs/settings.md`; defaults in `user/settings.example.json`.
- Every setting may be unset. A script that needs one calls
  `settings.get(key, required=True)`; when unset it raises `SettingMissing` and the
  script exits **4** with the `settings.py set` command to run. Claude then asks the
  user (one question, with a sensible suggestion), saves the answer, and re-runs.
  Onboarding can be skipped entirely; skills fill in what they need as they go.
- Never hardcode a machine, drive, user name or NAS path. Optional storage (NAS,
  b-roll library, archive) is off until the user sets it: skills degrade
  gracefully (e.g. archive to a local folder, skip the library search).
- Editor choice is `editor.nle`: `resolve-studio` (full automation through the
  scripting API), `resolve-free` (no external scripting: import the XML/EDL by
  hand, render drafts with ffmpeg), or `none` (ffmpeg-only path). Only DaVinci
  Resolve is supported as an NLE.

## Preferences: the skills learn

- `user/preferences.md` holds the user's standing preferences, one heading per
  skill (`## aroll-draft`, `## youtube-thumbnails`, …) plus `## general`.
- Every skill starts with: read `user/preferences.md` if it exists; the user's
  preferences override the skill's defaults.
- When the user corrects a result or states a lasting preference ("too tight",
  "never cut my jokes", "always 1080p drafts"), append one bullet under the
  skill's heading (create the file/heading if missing) and say so in one line.
  If unsure whether it is lasting, ask. Bigger changes to how a skill works go
  through the `customize` skill, which edits the skill itself: this copy belongs
  to the user.

## Scripts

- Python 3.9+ (the version macOS ships). Standard library first. A script that
  needs numpy, Pillow, OpenCV, librosa… imports it lazily and, if missing, exits
  with the exact `python3 -m pip install …` command and what it is for. Never
  install anything without the user's yes.
- Import shared code by path:
  `sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))`
  then `from vidkit import settings, media`.
- Machine-readable results (JSON) on stdout, progress and logs on stderr. Exit 0
  ok, 2 usage, 3 "retry with feedback" (validators), 4 setting missing.
- ffmpeg/ffprobe via `vidkit.media` (finds them, prints an install hint if
  missing, picks VideoToolbox / NVENC / libx264). Cross-platform where cheap
  (macOS first; Windows and Linux should work for the ffmpeg paths).
- Destructive steps (delete, move, overwrite media) are dry-run by default and
  need the user's explicit yes for the exact list. Uploads and publishing need an
  explicit go every time.

## Media conventions

- Transcribe once: the transcript lives next to the media as
  `<stem>.transcript.json` (see `tools/vidkit/transcript.py`) and every skill
  reuses it. `python3 tools/transcribe.py <media>` creates or reuses it and
  prints its path.
- Draft renders go in the project's drafts folder (`settings.drafts_dir(media)`),
  never next to the camera originals. Finals go in the project's finals folder.
- Sidecars travel with their clip: anything that moves a media file moves every
  `<stem>.*` sibling with it.
- Name files to the user by absolute path.

## Writing SKILL.md

- Frontmatter: `name`, `description` (what it does + the phrases that should
  trigger it), optional `allowed-tools`.
- Short sections in this order: what it makes; before you start (preferences,
  settings it needs, tools it checks); steps; hard rules; what the user can
  customize. Load long material from `reference/` only when needed.
- The user may be new to editing. Explain a term the first time it matters
  (a-roll, b-roll, J-cut, LUT…) in one clause, unless preferences say they are
  experienced. Point out the keyboard shortcut for what they are about to do.
- Rules are stated as general lessons, not stories about past projects.

## Agents

- One job per agent, file paths in and out, no conversation. Frontmatter:
  `name`, `description` ("Spawned by the X skill; not for direct use."),
  `tools`, `model`, `effort`.
- The a-roll editor and reviser run on `opus` (the cut quality depends on it).
  Judges that look at contact sheets can use `sonnet`. Users can change any
  agent's model in its file.
