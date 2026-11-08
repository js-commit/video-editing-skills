# Video editing skills

A suite of Claude Code skills that edit videos with the tools already on the
user's computer: ffmpeg for everything, DaVinci Resolve when they have it. The
flagship is `aroll-draft` (raw talking-head take -> first cut). The rest cover
b-roll, review notes, shorts, thumbnails, releasing, archiving, home videos and
teaching the user how to edit.

## First run

If `user/settings.json` does not exist, the user has not been set up. Before
anything else, greet them in one or two sentences and offer the `setup` skill
(about ten minutes, every question skippable). If they would rather dive in,
do what they asked: skills ask for any setting they need the first time.

## Every task

- Read `user/preferences.md` (if it exists) before starting any editing task.
  The user's preferences override skill defaults.
- Settings (folders, editor, transcription engine…) come from
  `python3 tools/vidkit/settings.py get <key>`. A script exiting with code 4
  means a setting is unset: ask the user one short question (suggest a sensible
  answer), save it with `settings.py set`, and re-run.
- Learn: when the user corrects a result or states a lasting preference, add
  one bullet under the right skill's heading in `user/preferences.md` and say so
  in one line. When they want a skill to work differently, use the `customize`
  skill: this copy of the repo is theirs to change.
- Teach as you go: the user may be new to editing. Explain a term the first time
  it matters, in a clause, and mention the keyboard shortcut for what they are
  about to do in DaVinci Resolve or EditReview. Skip this if preferences say
  they are experienced.

## Hard rules

- Never install software without the user's explicit yes. Print the command
  and what it is for; let them choose.
- Never delete, move or overwrite media without showing the exact list and
  getting a yes. Dry runs first.
- Never upload or publish anything without an explicit go for that video.
- Never commit secrets: API keys live in environment variables or the user's
  own config folders, never in this repo. `user/` is git-ignored.
- DaVinci Resolve is the only supported editing app. Its automation needs
  DaVinci Resolve Studio (external scripting); with the free version, import
  the exported XML/EDL by hand and render drafts with ffmpeg.
- Name files to the user by their absolute path.

## For contributors

How skills, scripts and agents are written: `docs/skill-conventions.md`.
Settings keys: `docs/settings.md`.
