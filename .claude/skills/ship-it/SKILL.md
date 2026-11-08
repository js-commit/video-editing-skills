---
name: ship-it
description: One command from an approved draft to a video ready for YouTube, in the order the user configured - final master, loudness, title/description/chapters, thumbnails, and a paste sheet; the user then uploads in YouTube Studio and publishes or schedules. Holds only the order and the hand-offs; each step is done by its own skill (youtube-release, youtube-thumbnails, home-video, shorts). Use when the user says "ship it", "let's ship <video / project / draft>", "release the approved cut", "take this all the way to YouTube".
argument-hint: "<draft file, project name or folder>"
---

# Ship it

The user approved a draft; this runs everything after it, in their order, up
to the upload, which the user does in YouTube Studio. Nothing here uploads.

## Before you start

- Read `user/preferences.md`: `## ship-it` (the steps list), `## youtube-release`,
  `## youtube-thumbnails`, `## general`.
- Find what is being shipped: the draft the user names, else the newest file
  in the project's drafts folder (`python3 tools/vidkit/settings.py
  drafts-dir <any project file>`). Find what it was cut from: the Resolve
  timeline (when `editor.nle` is `resolve-studio`), or the talking-head-ffmpeg
  recipe of the same round, or a home-video project. Say in one line: draft,
  source, length.

## The steps list

The user's order lives in preferences, for example:

```
## ship-it
- steps: master, loudness, metadata, thumbnails, upload, publish
```

That is also the default when nothing is set. Step names:

| Step | Done by | What happens |
|---|---|---|
| `master` | youtube-release step 1 | Final render at full resolution (Resolve Studio `render_master.py`, talking-head-ffmpeg `--final`, or the file the user names). |
| `loudness` | youtube-release step 2 | Measure; fix a quiet or peaky master (`loudness.py --fix`). |
| `metadata` | youtube-release steps 3-4 | Transcript of the master, release folder, title options, description with chapters and links, tags, `metadata.py check`. |
| `thumbnails` | youtube-thumbnails skill | Thumbnail candidates from the footage; the user picks. Saved in the project's finals folder as `thumb-1.jpg` etc. |
| `upload` | the user, youtube-release step 5 | Claude hands over the paste sheet and the file; the user uploads in Studio (default privacy suggestion: unlisted) and gives Claude the link. |
| `publish` | the user | They flip it to public in Studio, or schedule it there. |
| `review` | youtube-release, review mode | Optional, before `master`: a draft the user uploads unlisted for a last phone check. |
| `shorts` | shorts skill | Optional, after `upload`: vertical Shorts cut from the release. |

Unknown step names: ask what the user meant and add it to their preferences.
Changing the order ("thumbnails before metadata", "no thumbnails") is a
one-line preference; say so the first time.

## Running it

1. Say the plan in one short list (the steps, the master, where the release
   folder will be) and start without waiting. Say what leaves the computer on
   the way: the master's audio when the transcription engine is `elevenlabs`,
   the stills Claude reads for thumbnails, and an AI image round only if the
   user asks for one.
2. Run the steps in order, each by its skill's own instructions. Two things can
   overlap: writing metadata while the master renders, and thumbnails while
   metadata is written. Only one heavy job at a time (a render, a
   transcription, frame sampling).
3. **At `upload`**, show together: the file (absolute path, resolution,
   length, loudness verdict), the title options with your pick, the
   description, the chapters, the tags, the thumbnail pick (or "none yet") and
   the suggested privacy, plus the paste sheet's path. Offer to open the file's
   folder and <https://studio.youtube.com>. Changes requested: redo the step,
   show again. Then wait for the user to upload and give you the link.
4. `publish`: tell the user how (Studio > Content > the video > Visibility,
   or Schedule there).

## Variants

- **Home video** (vacation, family, pet montages from the home-video skill):
  the master comes from home-video's final render; no links, no tags, usually
  no thumbnail; a warm title and chapters by day or place. Suggest the user
  uploads it **unlisted**, to whichever channel they choose in Studio's
  account switcher.
  Music follows the montage-music rule: anything uploaded, even unlisted,
  uses music the user has the rights to (their own, licensed, or Creative
  Commons / an audio library that allows it). Check the upload plays and
  report any copyright claim YouTube shows.
- **Shorts**: the shorts skill builds them (vertical, 3 minutes or less) with
  a title and description each; the user uploads them the same way. Run it
  as a `shorts` step after the main release or on its own.
- **Review only**: the `review` step alone is youtube-release's review mode.

## Report

- The paste sheet path, and the link once the user has uploaded.
- The title used and the alternatives (they can swap in Studio).
- The loudness line, the chapters, the thumbnail status.
- What is left for the user: publish or schedule, set the thumbnail if picked
  later, monetization in Studio if they earn from the channel.

## Hard rules

- Never upload, publish or schedule: the user does that in Studio. Scripted
  Resolve renders must not upload either (youtube-release step 1).
- Suggest unlisted unless the user says otherwise for this video.
- No invented links, facts or URLs; a missing link is reported as missing.
- Shipping is not archiving: the master and project stay where they are.
  Archiving is the archive-project skill, on the user's word.

## What the user can customize

The steps list and its order (`## ship-it` in preferences), the default
privacy suggestion (settings `youtube.default_privacy`), and everything each step's own skill lets them change.
