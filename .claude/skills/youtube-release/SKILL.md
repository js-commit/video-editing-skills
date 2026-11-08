---
name: youtube-release
description: Get a finished video ready for YouTube - the final master (DaVinci Resolve Studio render, talking-head-ffmpeg --final, or a file the user names), loudness measured and fixed for YouTube, title options in the user's style, a description with chapters and the user's own links, tags, and a paste sheet the user follows to upload by hand in YouTube Studio. This skill never uploads. Use when asked to "release / publish this video", "get it ready for YouTube", "write a title / description / chapters", "is the volume right for YouTube", "normalize the audio", or "help me upload a draft to watch on my phone". The whole chain in one go is the ship-it skill; thumbnails are youtube-thumbnails; Shorts are the shorts skill.
---

# YouTube release

Makes everything YouTube needs from a finished edit, in a release folder next
to the master (`<master-stem>.release/`). The user uploads it themselves in
YouTube Studio, following the paste sheet. Nothing here talks to YouTube.

Two modes:

- **Review copy**: a draft the user uploads unlisted (or private) to watch the
  cut on their phone. No loudness, no chapters needed: a working title and a
  one-line description. Steps 1, 5, 6.
- **Release**: master, loudness, metadata, paste sheet, all steps.

## Before you start

- Read `user/preferences.md`: `## youtube-release` (title style, description
  habits, default category...) and `## general`. They override this file.
- Settings (`python3 tools/vidkit/settings.py get <key>`):
  `youtube.default_privacy` (unlisted), `youtube.made_for_kids`,
  `youtube.category`, `youtube.language`, `editor.nle`. A script exiting 4
  names the missing one: ask one short question, `settings.py set` it, re-run.

Scripts: `scripts/render_master.py` (Resolve), `scripts/loudness.py`,
`scripts/metadata.py`. Each says on stdout what it did; exit 0 ok, 3 "fix and
re-run", 4 a setting is missing.

## Steps

### 1. The master

Which file goes up, in this order of preference:

- A file the user names.
- **Resolve Studio** (`editor.nle` = `resolve-studio`): `python3
  ${CLAUDE_SKILL_DIR}/scripts/render_master.py [--timeline NAME] [--preset NAME]`
  renders the whole timeline at full resolution into the project's finals
  folder (`--list` shows timelines). Ask first if the user is working in
  Resolve right now. **Before the first scripted render in a Resolve session,
  ask the user to open the Deliver page (Shift+8) and check that "Upload
  directly to YouTube" is unticked**: once any YouTube preset has been used,
  Resolve can keep uploading every render until it restarts, and the scripting
  API cannot see or clear that box. The script reads Resolve's log afterwards
  and says loudly if an upload happened anyway. Details and other Deliver-page
  traps: [reference/rendering-and-uploading.md](reference/rendering-and-uploading.md).
- **Resolve free**: the user renders on the Deliver page (Shift+8) by hand.
- **talking-head-ffmpeg** edits: that skill's final render (`--final`).
- Review mode: the newest draft in the project's drafts folder is fine.

Name the master for what the video is (`2030-05-01_desk-lamp-review.mp4`),
never after the timeline. Say which file, its resolution and length.

### 2. Loudness

```
python3 ${CLAUDE_SKILL_DIR}/scripts/loudness.py <master>          # measure
python3 ${CLAUDE_SKILL_DIR}/scripts/loudness.py <master> --fix    # -> <stem>-loudnorm.mp4
```

Why it matters, in one line for the user: YouTube plays every video at about
-14 LUFS; it turns loud videos down but never turns quiet ones up, so a quiet
upload sounds weak next to everything else. `pass` and `loud` need nothing.
`quiet` or `peaks`: `--fix` (two-pass ffmpeg loudnorm, true peak held under
-1.5 dBTP, picture copied untouched) and upload the fixed file. `--in-place`
replaces the master only after the user's yes. Measure the exact file that
will be uploaded. Home videos with music beds: measure, but let the user
decide (music is mixed by ear).

### 3. Transcript on the master's clock

`python3 tools/transcribe.py <master>` (creates or reuses
`<stem>.transcript.json` beside it). Chapters from a transcript of the raw
footage land in the wrong place after the cuts. A loudness-fixed copy has the
same timing, so the original master's transcript works for it. With the
`elevenlabs` engine this sends the master's audio to ElevenLabs; say so the
first time.

### 4. Metadata

```
python3 ${CLAUDE_SKILL_DIR}/scripts/metadata.py draft <master>
```

Creates `<master-stem>.release/` with `chapters.proposed.txt`, `links.txt`
(only links from `user/links.md`; never invent one) and `notes.md` (opening and
closing lines, names said on camera, tag candidates). Read the transcript,
then write in that folder, following
[reference/description-guide.md](reference/description-guide.md) and the
user's preferences:

- `titles.txt`: 3-5 options, the recommended one marked `*`.
- `chapters.txt`: from the proposal, boundaries moved to real topic changes,
  every title rewritten.
- `description.txt`: hook, links block, chapters, substance, comment question,
  credits, up to 3 hashtags.
- `tags.txt`: comma-separated.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/metadata.py check <release-dir>
```

Fix every error it lists (exit 3) and re-run. It writes `paste-sheet.md`
(title, description, tags, the picked thumbnail, the master's path and every
Studio field in order). Show the user the titles (with the reason for each),
the description and the chapters; they pick the title.

The first time chapters come up, teach in one line: chapters split the
progress bar into named sections viewers can jump to, and YouTube shows them
only if they start at 00:00, number at least 3, and each lasts 10 s or more.

### 5. The user uploads in YouTube Studio

Give the user the absolute paths of `paste-sheet.md` and the file to upload,
and offer to open both (`open <file>` on macOS) plus
<https://studio.youtube.com>. The sheet walks them through Studio's pages:
Create > Upload videos, the details (title, description, thumbnail, audience),
Show more (tags, altered content, language, category), checks, visibility.
Suggest the privacy from `youtube.default_privacy` (unlisted) unless they said
otherwise; public, scheduling and premieres are their call in Studio.

Review mode: a working title, unlisted (or private, which only they can watch
while signed in), no chapters needed.

The first time privacy comes up, teach it: **unlisted** = anyone with the link,
never in search (review links, family); **private** = only you and people you
invite; **public** = everyone. Unlisted is the safe default.

### 6. Finish

- Ask for the video's link once it is uploaded and write it to
  `<release-dir>/link.txt`, so later steps (thumbnails in Studio, Shorts that
  link back) can find it.
- HD takes minutes to process after upload; until then a phone may play a
  blurry copy. Say so.
- Thumbnail: the youtube-thumbnails skill makes them; the user sets one in
  Studio (Details > Thumbnail > Upload file).
- Monetization (ads) is a Studio step: if the channel earns, the user switches
  ads on in Studio > Monetization.

## Hard rules

- Never upload, publish or schedule anything: the user does that in Studio.
  Scripted Resolve renders must not upload either (step 1).
- Never suggest public unless the user says public for this video.
- Never invent a link, a product name, a number or a claim: the transcript and
  `user/links.md` are the only sources. `metadata.py check` refuses unknown URLs.

## What the user can customize

- Title style, description blocks, standard footer, hashtags, default
  category: bullets under `## youtube-release` in `user/preferences.md`.
- Links: `user/links.md` (format in the description guide).
- Default privacy suggestion, made-for-kids, category, language: settings
  `youtube.*`.
- Loudness target (`--target`, e.g. -16 for podcasts on other platforms).
- Anything else through the `customize` skill: this copy is theirs.
