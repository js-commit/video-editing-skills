---
name: <skill-name>
description: <What it makes, in one sentence.> Use when asked to "<trigger phrase>", "<another phrase>", or <situation>.
---

# <skill-name>

<One or two sentences: what the user gets at the end.>

## Before you start

- Read `${CLAUDE_SKILL_DIR}/../../../user/preferences.md` if it exists
  (`## <skill-name>` and `## general`); preferences override the defaults below.
- Settings it needs (ask once if unset, then save):
  `python3 "${CLAUDE_SKILL_DIR}/../../../tools/vidkit/settings.py" get <key>`
  (exit 4 = unset: ask the user one short question, `settings.py set` it, re-run).
- Tools it needs: ffmpeg (through `tools/vidkit/media.py`), <others>. If one
  is missing, print the install command and ask before installing.

## Steps

1. <Step. Mention the keyboard shortcut if the user does this by hand in
   DaVinci Resolve. Explain a term in one clause the first time.>
2. <Step. Scripts: `python3 "${CLAUDE_SKILL_DIR}/scripts/<script>.py" ...`;
   JSON on stdout.>
3. <Show the result by absolute path.>

## Hard rules

- Never delete, move or overwrite media without showing the list and getting a yes.
- Never upload or publish without an explicit go.
- <Rules specific to this skill, stated as general lessons.>

## What the user can customize

- <Defaults worth changing, and where they live.>
