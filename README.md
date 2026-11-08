# Video Editing Skills for Claude Code

Claude Code skills that edit your videos with the apps already on your computer:
**ffmpeg** for everything, **DaVinci Resolve** when you have it. Point it at a raw
talking-head take and get a clean first cut in minutes. Then let it lay b-roll,
apply your review notes, cut Shorts, make thumbnails, write titles and chapters,
and archive the project when you are done.

**See what it does: [js-commit.github.io/video-editing-skills](https://js-commit.github.io/video-editing-skills/)**

It is a starting point, not a product: every skill is a plain text file you (or
Claude) can change. It learns your taste as you work.

## Install

1. Install [Claude Code](https://code.claude.com/docs/en/setup).
2. Let Claude download it (no git needed), then open it:

   ```sh
   claude "install github.com/js-commit/video-editing-skills to ~/video-editing-skills"
   cd ~/video-editing-skills && claude
   ```

   Or clone it yourself: `git clone https://github.com/js-commit/video-editing-skills`.
3. Type **`/setup`** (a fresh copy offers it on its own). Claude checks what is installed and asks a few questions
   (where your projects live, whether you use DaVinci Resolve, where to archive,
   whether you have a NAS…). Every question can be skipped; skills ask for what
   they need later.

Always start Claude from this folder: that is where the skills live. Your video
projects can be anywhere.

## Your first a-roll draft

```
> draft this a-roll: /path/to/my-raw-take.mp4
```

You get, next to the video:

- `<name>.aroll.tb.json` and `<name>.aroll.revision.json` — the cut list and the
  edited transcript (they also open in Video Haircut).
- `<name>…xml` and `<name>…edl` — import into DaVinci Resolve
  (File > Import > Timeline). With DaVinci Resolve Studio, Claude builds the
  timeline for you.
- A list of spots worth a listen (possible swallowed retakes, long pauses).
- Optionally a quick preview MP4 in the project's drafts folder.

## What's inside

| Skill | Say something like |
|---|---|
| `setup` | "/setup", "change my archive folder" |
| `aroll-draft` | "draft this a-roll", "cut the retakes and silences out of this" |
| `talking-head-ffmpeg` | "edit this with b-roll, no Resolve" |
| `broll-brick-layer` | "lay b-roll on this Resolve timeline" |
| `multicam-angles` | "pick the camera angles" (two-camera shoots, Resolve Studio) |
| `motion-graphics` | "add an animated stat / callout here" |
| `edit-review-notes` | "apply my review notes" |
| `resolve-export-draft` | "render a draft of the timeline" |
| `shorts` | "make Shorts from this video" |
| `youtube-thumbnails` | "make thumbnails" |
| `youtube-release` | "write the title, description and chapters", "is the volume right for YouTube?" |
| `ship-it` | "ship it" |
| `broll-library` | "add this b-roll to my library", "do I have footage of X?" |
| `footage-triage` | "sort this import folder" |
| `archive-project` | "archive this project", "what can I clean up?" |
| `home-video` | "make a video of our trip" |
| `montage-music` | "fit this song to the montage" |
| `stabilize-clips` | "stabilize these clips" |
| `voice-clear` | "clean up my voice / remove the room echo" (Apple silicon, on request only) |
| `vo-gapfill` | "do a voiceover for that gap" |
| `studio-thumbnails` | "Ask Studio thumbnails", "Gemini thumbnails with my face" |
| `unboxing-cut` | "cut the unboxing into a sequence" |
| `camera-ab-compare` | "compare these two phones side by side" (Resolve Studio) |
| `aroll-benchmark` | "score the auto cut against my edit" (dev) |
| `editing-coach` | "how do I color correct in Resolve?", "teach me stop motion" |
| `customize` | "from now on…", "change how thumbnails work" |
| `new-project` | "start a new project called X" |

## It learns

- **Preferences.** Say "the cuts are too tight" or "always keep my jokes" and
  Claude writes it to `user/preferences.md`. Every skill reads that file first.
- **Your copy.** Ask Claude to change how any skill works, add a step, or write a
  new skill. It edits the files in this folder; `git diff` shows what changed.
- **Settings.** `user/settings.json` holds your folders and tools. Ask Claude to
  change them or edit the file. Your own files in `user/` (settings, preferences, cache,
  backups) are git-ignored.

## Customize your keyboard shortcuts

Editing is a keyboard job. Set up shortcuts you like before your first edit:

- **DaVinci Resolve:** DaVinci Resolve > Keyboard Customization. There are presets
  for people coming from other editors. See `docs/keyboard-shortcuts.md`.
- **EditReview** (the review app in `apps/edit-review`, macOS): see its README.
- **BulkCut** (the triage app in `apps/bulk-cut`, macOS, optional): Settings
  (⌘,) or a `shortcuts.json` file; every key is listed in its README.

## Requirements

- Claude Code with a plan that includes Claude Opus. The a-roll editor and
  reviser agents run on Opus at the highest effort for the best cut; on
  lower-tier plans a long take can hit usage limits. `/setup` asks whether you
  are on Pro or Max and sets the other agents to match (Max: Opus at full effort
  for the frame-reading agents too; `python3 tools/agent_models.py apply max`).
  Switch any agent to another model or effort in `.claude/agents/`.
- Python 3.9 or newer and ffmpeg. On a Mac, Apple's Command Line Tools include Python: run
  `python3 --version` and accept the install if macOS offers it.
- A transcription engine: ElevenLabs Scribe through their API (best for cutting:
  keeps "um"s and has precise word times; account with a free tier, then per
  minute) or, on an Apple silicon Mac with macOS 26+, `voz` (offline, free,
  instant, fewer fillers). See `docs/transcription.md`.
- Optional: DaVinci Resolve Studio for full automation (the free version works
  through XML import), a NAS or external drive for archiving, EditReview for
  hands-free review notes (macOS 14+) and BulkCut for keyboard triage of footage
  (macOS 15+).

On a Mac there is nothing to compile: `voz`, `voice-clear`, EditReview and BulkCut
ship ready to run, signed and notarized.

macOS gets the most testing. The ffmpeg paths are written to work on Windows and
Linux too.

## Privacy and cost

- Your video files stay on your computer; nothing here uploads them. What does
  leave it: Claude (Anthropic) reads the transcripts, text and contact sheets
  (grids of still frames) a skill shows it, and skills that look at frames say
  so. Thumbnail and voiceover skills send what you hand them to the image or
  voice service you pick. For private footage there is a **local vision model** (`tools/vlm-describe`,
  Apple silicon): it describes the frames on your Mac and Claude works from the
  text, so no frame leaves the computer, only those descriptions (home-video privacy `local`,
  footage-triage `--local`, broll-library `describe.py local`). Or the no-frames
  modes, where nothing looks at a frame at all.
- Transcription with the ElevenLabs API sends audio to ElevenLabs. `voz` keeps
  it on your Mac. `voz` and `voice-clear` use the Desert Ant Labs SDK, which sends
  its maker a small usage signal (a generated device id, a call count, the
  program and SDK names, and your OS name and major version; never audio or text).
- Claude Code usage counts against your plan. A 15-minute a-roll draft runs a
  handful of Opus subagents.
- Nothing is ever uploaded to YouTube for you: you upload in YouTube Studio.
  None of your footage or projects is deleted, moved or overwritten, and nothing is
  installed, without your explicit yes.

## Folder map

```
.claude/skills/   the skills (SKILL.md + scripts)
.claude/agents/   subagents the skills use
tools/            shared helpers: settings, ffmpeg, DaVinci Resolve, transcription (Scribe, voz),
                  the local vision model (vlm-describe)
apps/edit-review/ EditReview, a macOS app for hands-free review notes (signed copy in prebuilt/)
apps/bulk-cut/    BulkCut, a macOS app for triaging footage from the keyboard (signed copy in prebuilt/)
docs/             getting started, settings, shortcuts, NAS, transcription, conventions
site/             the project page (build.py fills in the skill list; published by .github/workflows/pages.yml)
user/             your settings and preferences (not committed)
```

Writing or changing skills: `docs/skill-conventions.md`.

## Related apps

- **[Video Haircut](https://github.com/js-commit/video-haircut)** is the maintainer's desktop app for text-based editing of
  talking-head footage; `aroll-draft`'s cut list (`.aroll.tb.json`) and
  edited transcript open in it for manual touch-ups. Not required.
- **EditReview** (in `apps/edit-review`) and **BulkCut** (in `apps/bulk-cut`:
  go down a folder of clips and photos, trash the duds, keep the good parts,
  turn and zoom, one Apply; skills also hand it picks to review) are part of
  this repo. macOS, optional, and ready to use: open
  `apps/edit-review/prebuilt/EditReview.app` or `apps/bulk-cut/prebuilt/BulkCut.app`,
  or run `apps/install_apps.sh` to put both in `~/Applications`. Changed the source?
  Rebuild with the `build.sh` next to it.

## Contributing and support

Issues and pull requests are welcome; support is best effort. Changing a skill
for yourself? Just ask Claude: see `docs/skill-conventions.md` for how skills
are put together.

## Trademarks

DaVinci Resolve is a trademark of Blackmagic Design. YouTube and Gemini are trademarks
of Google. ElevenLabs, MiniMax, Premiere Pro, Final Cut Pro, Avid Media Composer, Pro
Tools, TimeBolt, Claude and other product names belong to their respective owners. This
project is not affiliated with or endorsed by any of them.

## License

MIT. See `LICENSE`. Third-party notices (the Desert Ant Labs SDK inside the two prebuilt
command-line programs, the Qwen model `vlm-describe` downloads, the motion-graphics engine):
`THIRD-PARTY-NOTICES.md`.
