# Setup questions: wording, defaults and what each answer saves

`SET` = `python3 <repo>/tools/vidkit/settings.py`. Ask in the batches below.
Keep each question one line; put the explanation in the option descriptions.
Every batch can be answered with "skip".

## Step `about`

**Q1 What do you make?** (multi-select; AskUserQuestion allows 4 options per
question, so split into two questions or let "Other" catch the rest)

| Answer | Saved slug |
|---|---|
| Talking-head YouTube videos (you, on camera, explaining or reviewing) | `talking-head` |
| Tutorials / screen recordings | `tutorials` |
| Vlogs | `vlogs` |
| Home videos (trips, family, pets) | `home-videos` |
| Shorts / vertical video | `shorts` |
| Stop motion | `stop-motion` |
| Podcasts / interviews | `podcasts` |

Save: `SET set about.content_types '["talking-head","shorts"]'`

**Q2 How much editing have you done?**

- New to it -> preferences `## general`: "I'm new to editing: explain terms
  the first time you use them and tell me the keyboard shortcut for what
  I'm about to do."
- Some (I know cuts, tracks and rendering) -> "I know the basics: explain
  only less common terms; shortcut tips are welcome."
- A lot -> "I'm an experienced editor: skip explanations and shortcut tips
  unless I ask."

Optional free text: "Anything I should know about how you work?" ->
`about.notes` (one short line, never personal details they did not offer).

## Step `plan`

**Q Which Claude plan are you on?** (it decides how much of the work runs on
Opus, Anthropic's strongest model, which uses up a plan's limits faster)

| Answer | Saved |
|---|---|
| Pro (about $20 a month) | `pro` |
| Max ($100 a month or more) | `max` |
| Not sure / skip | nothing (the shipped `pro` tier stays) |

Save: `SET set claude.plan max`, then run
`python3 REPO/tools/agent_models.py apply`. It rewrites the `model:` and
`effort:` lines of a few agents in `REPO/.claude/agents/` and prints them.
On both plans the a-roll editor and reviser run on Opus at the highest effort,
because they decide the cut. Pro keeps Sonnet (or a lower effort) for the
batch work that reads many frames (b-roll annotation, footage sorting, frame
descriptions, Shorts framing), so a long project fits the usage limits; Max
moves those to Opus. They can switch any time ("I upgraded to Max"): set the
key and run `apply` again.

## Step `editor`

**Q Which editing app do you use?**

- **DaVinci Resolve Studio** (paid) -> `editor.nle = "resolve-studio"`.
  Skills can drive it directly: build timelines, lay b-roll, render drafts.
  That needs external scripting switched on once:
  DaVinci Resolve > Preferences > System > General >
  "External scripting using" = **Local**, then restart Resolve.
  (Menu names can shift between versions; if it is not there, search the
  Preferences window for "scripting".)
- **DaVinci Resolve (free)** -> `"resolve-free"`. The free version blocks
  external scripts, so skills export a timeline file (XML/EDL) you import
  with File > Import > Timeline (older versions: File > Import Timeline), and drafts render with ffmpeg.
- **No editor / ffmpeg only** -> `"none"`. Edits are JSON recipes rendered by
  ffmpeg; you review the result and give notes.
- Something else (Premiere Pro, Final Cut...) -> explain only DaVinci Resolve
  is supported for automation; save `"none"` and mention the free Resolve and
  the Premiere-to-Resolve keyboard cheat sheet in the editing-coach skill.

The check reports whether Resolve is installed; it cannot tell free from
Studio, so ask. If they don't have it: it is a free download from
Blackmagic Design's website; Studio is a one-time purchase.

**Optional Q: What resolution do you shoot?** 4K (default, `"3840x2160"`) or
1080p (`"1920x1080"`) -> `editor.timeline_resolution`. Vertical-first creators
can say `"2160x3840"`.

## Step `folders`

**Projects folder** - "Where should video projects live? I'd suggest
<suggested projects_dir>." Each video gets one folder in there. Big footage
can live on an external drive: any path works. Save
`SET set paths.projects_dir "<absolute path>"`. If it does not exist and its
parent does, offer to create it (`mkdir -p`); if the parent is missing (drive
not plugged in), save it and say so.

**Project layout** - show the default from the settings (`SET show`,
`project_layout`) as a tree:

```
<project>/
  footage/          camera originals
  audio/            separate mic recordings, music, voiceover
  graphics/         logos, screenshots, titles
  output/           finals
  output/drafts/    draft renders for review
  work/             scratch files skills make (safe to delete later)
```

"Keep this, or describe your own?" For their own, map each part to a
relative folder and save one key at a time:
`SET set project_layout.footage "01 Footage"`. All six keys are used by
skills; keep every one pointing somewhere. Explain in one line why it matters:
skills find footage and put drafts in the right place without asking.

**Inbox** - "Where do new imports land (camera cards, phone dumps) before
they are sorted?" Suggest the check's `inbox_dir`. Keep it outside the
projects folder. Save `paths.inbox_dir`, or skip.

## Step `nas`

"Do you have a NAS (a network drive at home) you keep footage or archives on?"

- No -> `SET set nas.enabled false`.
- Yes -> "Where does it show up on this computer when it's connected?"
  (macOS: `/Volumes/<share>`; Windows: a mapped drive letter like `Z:\`;
  Linux: e.g. `/mnt/<share>`). Save `nas.enabled true`, `nas.mount_path`.
  Tell them: connect it before archiving or harvesting (skills stop if the
  path is missing rather than writing to a local folder of the same name); a
  wired connection is more reliable for big copies than Wi-Fi; never store the
  NAS's address or password in this repo (the OS keeps the login). Link
  `<repo>/docs/nas.md`. Optional `nas.notes` for a reminder like "turn on
  the NAS first" (no addresses).

## Step `archive`

**Archive folder** - "When a video is finished, where should its project go?"
Suggest `<nas.mount_path>/video-archive` when they have a NAS, else the
check's `archive_dir` (an external drive is a good home). Save
`paths.archive_dir`.

**Lean or keep?** -> `archive.default_mode`:

- **lean** (default): keep the final video, thumbnails and any b-roll worth
  reusing; delete the rest (raw footage, caches, renders). Saves the most space.
- **keep**: move the whole cleaned project to the archive, footage included,
  so it can be re-edited later.

Every archive run still shows the exact list and asks before deleting.

Optional **finals folder** (`paths.finals_dir`): one place that collects every
finished video. Skip = finals stay in each project's finals folder.

## Step `broll`

"Want a b-roll library? Skills can save the good extra footage from finished
projects into one searchable folder and reuse it later." Suggest
`<nas.mount_path>/broll-library` or the check's `broll_library_dir`. Save
`paths.broll_library_dir`, or skip (the library search then just returns
nothing).

Only if content types include home videos or vlogs:
- `paths.home_videos_dir` - where family/trip footage and finished home
  videos are kept (often on the NAS).
- `paths.music_dir` - a folder of music they have the rights to use.

## Step `transcription`

Skills cut talking-head video from a word-level transcript, so this matters
for aroll-draft, shorts, chapters and review notes.

There are two engines (`tools/transcribe.py --check` shows which are ready
here; the full comparison is in `<repo>/docs/transcription.md`):

- **`elevenlabs`** (ElevenLabs Scribe, cloud): the best word times and it
  keeps the "um"s, which is what aroll-draft cuts on. Needs an ElevenLabs
  account and API key; **there is a free tier**, beyond it minutes of audio
  are billed. The audio is uploaded to ElevenLabs.
- **`voz`** (offline, Apple silicon Mac on macOS 26 or newer): free, the audio
  stays on the computer, a 16-minute take in a few seconds; keeps about half
  the fillers, so a-roll cuts need a little more hand-trimming. Downloads
  its model (about 470 MB) on first use, nothing to install.

Ask first: **"Do you have an ElevenLabs account?"** If yes (or they will make
one: the free tier is enough to start), `elevenlabs` is the engine; walk
them through the API key below. If no and the check says `voz` is ready,
suggest `voz` and say they can add an ElevenLabs key later for cutting-grade
transcripts (then make it the default, or ask for it per take). If
neither is possible (Windows/Linux without a key), say that transcription
needs an ElevenLabs account on this computer and leave the step unset.

Save `SET set transcription.engine "<elevenlabs|voz>"`. Optional
`transcription.language` (e.g. `"en"`; skip = auto-detect).

**API keys**: the user sets them in their own terminal, never in the chat and
never in this repo. Use the variable name in the engine's `setup` line from
the check (shown here as `ENGINE_API_KEY`):

- macOS (zsh): `echo 'export ENGINE_API_KEY="paste-key-here"' >> ~/.zprofile`
  (not `~/.zshrc`: apps such as EditReview run scripts in a login shell, which reads `~/.zprofile`),
  then open a new terminal.
- Linux (bash): the same line into `~/.bashrc`.
- Windows (PowerShell): `setx ENGINE_API_KEY "paste-key-here"`, then open a
  new terminal.

Then quit and restart Claude Code from the new terminal so it sees the key.
Check presence only: `python3 -c "import os;print(bool(os.environ.get('ENGINE_API_KEY')))"`.

## Step `vision` (optional, Apple silicon Macs)

"Do you have private footage (family, kids, anything sensitive) that you want
sorted into folders or cut into home videos without any frame leaving your
computer?" If no: skip. If yes, explain the local vision model: a model that
runs on this Mac describes what is in a clip, and Claude works from that text;
no cloud model ever sees a frame. It needs about 5.6 GB of disk (downloaded
once), 7 GB of memory while it runs, and its own Python environment:

```sh
python3 -m venv ~/.venvs/local-vision
~/.venvs/local-vision/bin/python3 -m pip install mlx-vlm pillow
```

Both are installs: show them, run them only after a yes, one at a time. Then
`SET set vision.python "~/.venvs/local-vision/bin/python3"` and check with
`python3 <repo>/tools/vlm-describe/vlm_describe.py --check` ("available":
true; the model itself downloads on first use). Record the preference bullets
the user wants with it (home-video `privacy: local`; footage-triage "use local
mode for home footage"). Details: `<repo>/tools/vlm-describe/README.md`.

## Step `review`

"How do you want to watch drafts and give notes?"

- **EditReview** (macOS, free, in this repo): plays a draft with its
  transcript; you pause, type a note, press Return, and the note is stamped
  at that moment. Skills turn the notes into edits. Ready to use (macOS 14+,
  signed): `<repo>/apps/edit-review/prebuilt/EditReview.app`. Offer
  `<repo>/apps/install_apps.sh`, which copies it and BulkCut to ~/Applications;
  ask first. Save `review.app "editreview"`.
- **QuickTime Player** / **VLC** / **DaVinci Resolve**: you tell Claude the
  timestamps yourself ("at 1:23 cut the pause"). Save `"quicktime"`, `"vlc"`
  or `"resolve"`.

On macOS, also mention BulkCut (`<repo>/apps/bulk-cut`), an optional app for
keyboard triage of a folder of footage and photos (trash the duds, keep the
good parts, turn and zoom, one Apply); skills can also hand it picks to review.
Ready to use (macOS 15+, signed): `<repo>/apps/bulk-cut/prebuilt/BulkCut.app`.
Its keys are set in
its Settings (⌘,) or `~/Library/Application Support/BulkCut/shortcuts.json`.

## Step `youtube`

Skills never upload: they write titles, descriptions with chapters, tags and
thumbnails, plus a paste sheet the user follows in YouTube Studio. Two quick
answers make that sheet ready to follow:

- "Which privacy do you usually start an upload with?" `youtube.default_privacy`:
  `unlisted` (default: anyone with the link, never in search), `private` or
  `public`.
- "Are your videos made for kids?" `youtube.made_for_kids` (`true` / `false`;
  YouTube asks this for every video, and it is a legal declaration). Skip =
  the sheet asks each time.

Optional: `about.channel_name` (used in descriptions), `about.name`.

## Step `preferences`: bullets from the answers

Write with `PREFS add <heading> "<text>"`:

- `general`: the experience bullet from Q2.
- `general`: "I mainly make: <content types in words>."
- `general` (editor none or free): "No Resolve automation: give me ffmpeg
  drafts and timeline files to import."
- `aroll-draft` (talking-head or tutorials, only if they said something
  specific about pacing). Otherwise leave skill headings for later.

Never invent preferences they did not express.
