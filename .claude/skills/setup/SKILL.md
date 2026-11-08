---
name: setup
description: First-run onboarding for this video-editing toolkit - checks what the computer has (ffmpeg, DaVinci Resolve, transcription), asks a few short, skippable questions about how the user works (what they make, their editor, where projects, archives and b-roll live, NAS or not, transcription engine, review app, YouTube uploads), saves the answers to user/settings.json and starts user/preferences.md. Re-runnable - shows current answers and only asks what is unset or what they want to change. Use for "/setup", "set me up", "get started", "onboarding", "change my settings", "I moved my projects folder", "redo setup", or when the session-start note says this copy has not been set up yet.
---

# setup

Gets a new user from "just cloned it" to "ready to edit" in about ten
minutes. Every question can be skipped; skills ask for anything still missing
the first time they need it, so nothing here is mandatory.

Paths below: `REPO` is `${CLAUDE_SKILL_DIR}/../../..`, `SET` is
`python3 "REPO/tools/vidkit/settings.py"`, `PREFS` is
`python3 "${CLAUDE_SKILL_DIR}/../customize/scripts/prefs.py"`.
(On Windows, `python` instead of `python3` if that is what works.)

## Tone

- Friendly and short. Two-sentence welcome, then small batches of questions.
- Every question offers a sensible default and a way to skip ("skip" or
  "not now"). Never push; never lecture.
- Use the AskUserQuestion tool whenever the choices are discrete (it allows
  up to 4 questions per call and 2-4 options each, and always adds an "Other"
  box for free text). Ask folder paths as plain questions with the suggested
  path shown, so the user can just say "yes".
- Explain a term in one clause the first time it matters (NAS = a network
  drive at home; b-roll = the extra footage laid over the talking).
- Name every file and folder by its absolute path.

## Before you start

1. Read `REPO/user/preferences.md` if it exists (`## setup` and `## general`).
2. `SET exists` (exit 0 = settings file exists). If it exists, this is a
   **re-run**: show a compact summary of what is set (`SET show`, only the
   non-empty values, in plain words) plus the skipped steps, then ask:
   "Fill in what's missing / Change something / Start over / All good".
   Only ask what they pick. "Fill in what's missing" = the steps in neither
   `completed_steps` nor `skipped_steps`, then one line offering the skipped
   ones. "Change something" = ask which, run just that step. Never wipe
   values on "start over" without a yes; re-ask each question with the
   current value as the default instead.
3. First run: welcome in two sentences, e.g. "Hi! I'm going to set this
   toolkit up for the way you make videos: a quick check of your computer,
   then a few questions, all skippable." Ask if now is a good time. If they
   would rather skip setup entirely, ask once whether to stop offering it; on
   yes run `SET init` and `SET step-skip <step>` for every step below, and say
   they can run /setup any time.

## Steps

Mark each step as you finish it: `SET step-done <step>` when answered,
`SET step-skip <step>` when skipped (step names: `about`, `plan`, `editor`,
`folders`, `nas`, `archive`, `broll`, `transcription`, `vision`, `review`,
`youtube`, `tools`, `preferences`; the check in step 1 is not a step). Save each answer right away with
`SET set <key> <value>` (values are parsed as JSON when they look like JSON,
so lists are `'["vlogs","shorts"]'` and booleans `true`/`false`). That makes
setup resumable: if the session ends halfway, the next run picks up there.

The question details, defaults and explanations are in
`${CLAUDE_SKILL_DIR}/reference/questions.md`. Read it before asking.

1. **Check the computer** (read-only):
   `python3 "${CLAUDE_SKILL_DIR}/scripts/env_check.py" --text`
   Summarize in at most six lines: what is ready, what is missing and what
   that blocks. If ffmpeg or ffprobe is missing, offer the install now (it is
   required); everything else waits for step 9. Don't install anything yet.
2. **about** - what they make (multi-select) and their editing experience.
   Saves `about.content_types`; write the experience and "I mainly make"
   bullets to `## general` right away with `PREFS add` (see questions.md), so
   they survive an interrupted setup.
   Then **plan** - which Claude plan they are on: Pro (about $20 a month) or
   Max ($100 a month or more). Saves `claude.plan`, then
   `python3 "REPO/tools/agent_models.py" apply` sets the subagents' models to
   match (Max: Opus at full effort for the frame judges and planners too).
   Say in one line what changed (`git diff --stat .claude/agents`).
3. **editor** - DaVinci Resolve Studio / DaVinci Resolve (free) / no editor
   (ffmpeg only). Saves `editor.nle`. Studio: explain external scripting and
   how to switch it on. Free: what is manual. None: everything renders with
   ffmpeg. Optionally `editor.timeline_resolution`.
4. **folders** - projects folder (`paths.projects_dir`, suggest the OS
   default from the check), project layout (keep the default or describe
   their own: `project_layout.*`), import inbox (`paths.inbox_dir`).
   Offer to create the projects folder if it does not exist.
5. **nas** - do they have a NAS? If yes: where it mounts (`nas.enabled`,
   `nas.mount_path`), mount it before archiving, prefer a stable wired
   connection, never put addresses or passwords in this repo; point to
   `REPO/docs/nas.md`. If the share is not mounted right now, save the path
   anyway and say skills will check it when they need it.
6. **archive** - where finished projects go (`paths.archive_dir`, on the NAS
   if they have one) and lean vs keep (`archive.default_mode`). Optionally a
   central folder for finished videos (`paths.finals_dir`).
   Then **broll** - where a b-roll library should live
   (`paths.broll_library_dir`), or skip ("no library yet").
   If they make home videos or vlogs, also `paths.home_videos_dir` and
   `paths.music_dir` (both optional). Mark the step names `archive` and `broll`.
7. **transcription** - which engine (`transcription.engine`, optional
   `transcription.language`). Ask whether they have an ElevenLabs account
   (Scribe: best for cutting, free tier then per minute, audio uploaded);
   otherwise on an Apple silicon Mac with macOS 26+ suggest `voz` (offline,
   free, fewer fillers). API keys go in environment variables, set by the
   user in their own terminal, never in this repo or the chat. If
   `tools/transcribe.py` is missing, skip this step.
   Then **vision** (only on an Apple silicon Mac, else `SET step-skip vision`):
   do they have private footage (family, kids) they want sorted or cut
   without any frame leaving the computer? If yes, offer the local vision
   model (`questions.md`, step `vision`): a one-time ~5.6 GB download into its
   own Python environment, then `vision.python`. Install nothing without a yes.
8. **review** - how they watch drafts (`review.app`): EditReview on macOS
   (ready to use; offer `apps/install_apps.sh`), else QuickTime / VLC / Resolve. On macOS mention
   BulkCut too (keyboard triage of footage, `apps/bulk-cut`, also ready to use). Then **youtube** -
   the privacy they usually start uploads with (`youtube.default_privacy`) and
   their made-for-kids answer; they always upload by hand in YouTube Studio.
   Optional `about.channel_name`. Mark `review` and `youtube`.
9. **tools** - from the check, list only the missing tools that matter for
   their answers (e.g. exiftool only if they sort footage, swiftc
   only if they want to change an app), each with the exact install command and what it
   unlocks. Ask which to install (multi-select, "none" is fine). Run a
   command only after an explicit yes for that tool, one at a time, show the
   result, then re-run the check. Never install Python packages globally
   without saying so; `python3 -m pip install --user <pkg>` is the default.
10. **preferences** - add any remaining starter bullets with `PREFS add`
    (see questions.md for the bullets each answer produces; the script skips
    duplicates, so re-runs are safe). Show the file's absolute path and its
    `## general` section, and say they can edit it by hand any time.
11. **Wrap up** - three lines max:
    - Keyboard tip: DaVinci Resolve's keys are customizable under
      DaVinci Resolve > Keyboard Customization (presets for people coming
      from Premiere Pro, Final Cut Pro, Avid...); EditReview shows its keys
      with ⌘/. Full list: `REPO/docs/keyboard-shortcuts.md`.
    - Offer two next steps (AskUserQuestion): "Create my first project"
      (the new-project skill) or "Try a first cut on a clip" (the
      aroll-draft skill: they give a talking-head clip's path).
    - Mention they can change anything later by saying so or re-running /setup,
      and that "from now on..." sentences are remembered (customize skill).

## Hard rules

- Read-only until the user answers: the check installs and changes nothing.
- Install only on an explicit yes for that exact command. Never run `sudo`
  yourself: print the command and let the user run it in their terminal.
- Never ask for, store or echo passwords, API keys, tokens or network
  addresses. To check that an API key is set, test presence only
  (`python3 -c "import os;print(bool(os.environ.get('NAME')))"`), never print it.
- Never create `user/settings.json` values the user did not give or accept.
  "Skip" means leave it null.
- Don't create folders on a path whose drive or share is not connected (a
  missing `/Volumes/...` or drive letter): save the setting and say why.
- Don't launch DaVinci Resolve or install EditReview or BulkCut without a yes.

## What the user can customize

- The questions, their order and the defaults: edit
  `${CLAUDE_SKILL_DIR}/reference/questions.md` (or ask the customize skill).
- Which steps run: `SET step-skip <step>` hides a step on re-runs.
