# Settings

Your setup lives in `user/settings.json` (created by the `setup` skill, never
committed). Defaults come from `user/settings.example.json`; any key you leave
empty (`null`) is asked for the first time a skill needs it, then saved.

Change a value by asking Claude ("my archive is now on the NAS"), by running
`/setup` again, or yourself:

```sh
python3 tools/vidkit/settings.py show                          # everything
python3 tools/vidkit/settings.py get paths.projects_dir        # one value (exit 4 if unset)
python3 tools/vidkit/settings.py set paths.projects_dir "~/Movies/VideoProjects"
python3 tools/vidkit/settings.py set about.content_types '["talking-head","shorts"]'
python3 tools/vidkit/settings.py unset paths.music_dir
python3 tools/vidkit/settings.py missing                       # keys still empty
```

Values that look like JSON (`true`, `1080`, `["a","b"]`) are stored as JSON;
anything else as text. Paths may use `~`. For a single run you can override a
key with an environment variable: dots become underscores, upper case, `VES_`
in front (`VES_PATHS_PROJECTS_DIR=/tmp/test`). `VES_SETTINGS=<file>` points at
a different settings file (handy for testing).

Never put passwords, API keys or network addresses in this file. API keys go
in environment variables (see `docs/getting-started.md`).

## about

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `about.name` | Your name, for descriptions and credits. Optional. | `"Sam"` | context for any skill (e.g. youtube-release descriptions) |
| `about.channel_name` | Your channel name, for descriptions and thumbnails. Optional. | `"Sam Makes Things"` | context for youtube-release and youtube-thumbnails |
| `about.content_types` | What you make. Picks examples and defaults. One or more of `talking-head`, `tutorials`, `vlogs`, `home-videos`, `shorts`, `stop-motion`, `podcasts`. | `["talking-head","shorts"]` | setup, editing-coach |
| `about.notes` | One line about how you work, for context. | `"I film in a small, echoey room"` | any skill |

## claude

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `claude.plan` | Your Claude plan: `pro` (about $20 a month) or `max` ($100 a month or more). Sets which model and effort the subagents use: `python3 tools/agent_models.py apply` rewrites `.claude/agents/*.md` to match (`show` lists both tiers). Empty = the shipped `pro` tier. The a-roll editor and reviser use Opus at the highest effort on both. | `"max"` | setup, tools/agent_models.py |

## paths

All optional until a skill needs them. Use absolute paths. A folder on an
external drive or NAS works; skills check it is connected before writing.

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `paths.projects_dir` | The folder holding one sub-folder per video project. | `"~/Movies/VideoProjects"` | new-project, footage-triage, archive-project, broll-library, broll-brick-layer, every skill that finds a project's folders |
| `paths.inbox_dir` | Where new imports land before sorting (camera cards, phone dumps). Keep it outside the projects folder. | `"~/Movies/VideoInbox"` | footage-triage |
| `paths.archive_dir` | Where finished projects go when archived. Local folder, external drive or NAS. | `"/Volumes/<share>/video-archive"` | archive-project |
| `paths.finals_dir` | One folder collecting every finished video. Empty = finals stay in each project's finals folder. | `"/Volumes/<share>/final-videos"` | archive-project |
| `paths.broll_library_dir` | The searchable b-roll library (reusable footage from finished projects). Empty = no library; searches return nothing. | `"~/Movies/BrollLibrary"` | broll-library, archive-project, footage-triage, talking-head-ffmpeg |
| `paths.music_dir` | Music you have the rights to use. | `"~/Music/Licensed"` | montage-music, archive-project |
| `paths.home_videos_dir` | Family, trip and pet footage and finished home videos. | `"/Volumes/<share>/home-videos"` | home-video, footage-triage, archive-project |
| `paths.cache_dir` | Regenerable working files (contact sheets, analysis). Empty = `user/cache/` in this repo. Safe to delete. | `"~/Movies/.video-cache"` | many skills (through `settings.cache_dir()`) |

## project_layout

The folders inside every project, relative to the project folder. `setup`
asks whether to keep these; `new-project` creates them. See
`docs/folder-layout.md`.

| Key | Meaning | Default | Used by |
|---|---|---|---|
| `project_layout.footage` | Camera originals (never edited in place). | `"footage"` | aroll-draft, footage-triage, broll skills, archive-project |
| `project_layout.audio` | Separate audio: mic recordings, music, voiceover. | `"audio"` | aroll-draft, montage skills |
| `project_layout.graphics` | Logos, screenshots, titles, thumbnails. | `"graphics"` | youtube-thumbnails, motion-graphics |
| `project_layout.drafts` | Draft renders for review. | `"output/drafts"` | aroll-draft, resolve-export-draft, talking-head-ffmpeg, shorts |
| `project_layout.finals` | Final renders. | `"output"` | youtube-release, archive-project |
| `project_layout.work` | Scratch files skills make; deleted when archiving. | `"work"` | most skills |

Changing the layout affects how skills look inside **every** project, so
older projects may need the new folders (re-running `new-project` on one adds
missing folders).

## nas

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `nas.enabled` | You have a NAS (network drive) for archives or libraries. | `true` | archive-project, broll-library |
| `nas.mount_path` | Where the NAS share appears on this computer when connected. Skills stop if it is missing instead of writing to a local folder. | macOS `"/Volumes/<share>"`, Windows `"Z:\\"`, Linux `"/mnt/<share>"` | archive-project, broll-library, talking-head-ffmpeg |
| `nas.notes` | A reminder shown when the NAS is needed (no addresses or passwords). | `"Turn the NAS on and connect over Ethernet"` | archive-project |

More in `docs/nas.md`.

## editor

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `editor.nle` | Your editing app: `resolve-studio` (full automation through external scripting), `resolve-free` (import XML/EDL by hand; drafts rendered with ffmpeg), `none` (ffmpeg only). Empty = skills ask. | `"resolve-studio"` | every Resolve skill, aroll-draft, multicam-angles, archive-project |
| `editor.timeline_resolution` | Resolution for timelines skills build, `WIDTHxHEIGHT`. | `"3840x2160"` (4K), `"1920x1080"`, `"2160x3840"` (vertical) | aroll-draft, Resolve skills |

## transcription

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `transcription.engine` | Speech-to-text engine: `elevenlabs` (ElevenLabs Scribe; account with a free tier, then per minute; best word timings, the engine for cutting) or `voz` (offline on an Apple silicon Mac, macOS 26+; free; fewer fillers). `python3 tools/transcribe.py --check` shows which run here. | `"elevenlabs"` | tools/transcribe.py, aroll-draft, edit-review-notes, youtube-release, youtube-thumbnails, EditReview |
| `transcription.language` | Spoken language code. Empty = auto-detect (`voz`: English). | `"en"` | tools/transcribe.py |

Details and tradeoffs: `docs/transcription.md`.

## vision

A vision model that runs on this computer and describes frames, so private
footage never reaches a cloud model (`tools/vlm-describe/README.md`). Used by
home-video privacy `local`, footage-triage `--local` and broll-library
`describe.py local`. Optional: without it those skills use the cloud agents or
their no-frames modes.

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `vision.python` | The `python3` of the virtual environment where `mlx-vlm` and `pillow` are installed. Empty = the local model is not set up. | `"~/.venvs/local-vision/bin/python3"` | tools/vlm-describe |
| `vision.backend` | Which model: `qwen35-mlx` (Qwen3.5-9B 4-bit, Apple silicon; the default) or `echo` (no model, for tests). | `"qwen35-mlx"` | tools/vlm-describe |

## render

| Key | Meaning | Default | Used by |
|---|---|---|---|
| `render.video_encoder` | H.264 encoder for ffmpeg renders. `auto` picks VideoToolbox on macOS, NVENC on NVIDIA, else `libx264`. Force one with `libx264`, `h264_videotoolbox`, `h264_nvenc`, `h264_qsv`, `h264_amf`. | `"auto"` | every ffmpeg render (through `vidkit.media`) |
| `render.draft_height` | Height of draft/preview renders in pixels. | `1080` | aroll-draft, talking-head-ffmpeg |

## review

| Key | Meaning | Example | Used by |
|---|---|---|---|
| `review.app` | How you watch drafts and give notes: `editreview` (the macOS app in `apps/edit-review`, notes saved as JSON), `quicktime`, `vlc`, `resolve`, or `other`. | `"editreview"` | aroll-draft, talking-head-ffmpeg, edit-review-notes |

## youtube

| Key | Meaning | Default | Used by |
|---|---|---|---|
| `youtube.default_privacy` | The privacy the paste sheet suggests for your uploads: `unlisted`, `private` or `public`. | `"unlisted"` | youtube-release |
| `youtube.made_for_kids` | Your standing answer to YouTube's "made for kids" question. Shown on the paste sheet. Unset: the sheet asks each time. | `null` | youtube-release, shorts |

## archive

| Key | Meaning | Default | Used by |
|---|---|---|---|
| `archive.default_mode` | `lean` keeps only the finals, thumbnails and reusable b-roll; `keep` moves the whole cleaned project (footage included) to the archive. Every run still shows the list and asks. | `"lean"` | archive-project |

## onboarding

Written by the `setup` skill; you don't need to edit these.

| Key | Meaning |
|---|---|
| `onboarding.completed_steps` | Setup steps answered (`about`, `plan`, `editor`, `folders`, `nas`, `archive`, `broll`, `transcription`, `vision`, `review`, `youtube`, `tools`, `preferences`). |
| `onboarding.skipped_steps` | Steps you skipped; offered again only when relevant. |
| `onboarding.last_run` | Date setup last ran. |

## Optional keys read by individual skills

Not in the example file; set them only if you want to change the default.

| Key | Meaning | Default |
|---|---|---|
| `transcription.elevenlabs_model` | ElevenLabs speech-to-text model id. | the engine's current default |
| `triage.session_gap_hours` | A gap this long between clips starts a new shooting session when sorting an import. | `3` |
| `triage.trash_dir` | Where footage-triage puts rejected clips. | `_trash` inside the folder being sorted |
| `archive.checksum` | Verify archive copies with checksums (slower, safer). | `false` |
| `editor.never_touch_timelines` | Resolve timeline names skills must never modify (anything with "backup" in its name is always protected). | `[]` |
| `editor.draft_render_preset` | Name of your own Resolve render preset to use for draft renders. | built-in 1080p H.264 settings |
| `youtube.category` | YouTube category (name or id), shown on the paste sheet. | `22` (People & Blogs) |
| `youtube.language` | Language of your videos' title and description (e.g. `en`), shown on the paste sheet. | not shown |
| `youtube.contains_synthetic_media` | Your standing answer to YouTube's altered or synthetic content question, shown on the paste sheet. | asked per upload |
| `youtube.thumbnail_font` | Font file (or style name) for thumbnail titles. | the first condensed bold font found |
| `motion_graphics.browser` | Path to the Chrome/Chromium-type browser used to render motion graphics. | found automatically |
