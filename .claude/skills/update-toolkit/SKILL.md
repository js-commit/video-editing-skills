---
name: update-toolkit
description: Check whether a newer version of this video-editing toolkit is out and install it without losing the user's own changes - lists what is new in plain words, fast-forwards a git copy, turns a copy downloaded without git into a git one first, and merges by hand where the user changed the same file. Use for "update the toolkit", "check for updates", "is there a new version", "get the latest skills", "what's new", "stop checking for updates", and when the session-start line says UPDATE AVAILABLE.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/update.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/vidkit/settings.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/../customize/scripts/backup.py *), Read
---

# update-toolkit

**What it does.** The toolkit keeps changing: fixes, new skills. This copy looks once a day, when a Claude session
starts, whether a newer version is out, and says so in one line. This skill shows what is new and installs it. The
user's settings, preferences and their own changes to skills stay.

Paths: `REPO` = `${CLAUDE_SKILL_DIR}/../../..`; `UP` = `python3 REPO/tools/update.py` (its docstring has the details);
`BACKUP` = `python3 REPO/.claude/skills/customize/scripts/backup.py`.

## Before you start

- Read `REPO/user/preferences.md` (`## general`, `## update-toolkit`).
- Never update without the user's yes for this update. The session-start line is an offer, not a go.
- What the daily look sends: one request for the latest version's id to where this copy came from (GitHub).
  Nothing about the user, the computer or their files. Say so if they ask.

## 1. Look

```
UP status          # JSON; changes nothing in the folder
```

Tell the user, in a few lines:
- `available` false: this copy is up to date. Stop.
- how many versions behind (`behind`) and what they are: `commits`, newest first, retold in plain words and grouped
  by skill ("talking-head-ffmpeg: fades at the end; a new skill, ffmpeg-to-resolve"), not read out as a list.
- whether anything is in the way (`blocked`, below), and that their settings, preferences and own changes stay.

`kind` says how this copy knows its version: `git` (a git clone), `download` (downloaded without git; it carries the
id of the version it was made from), `unknown` (neither: it cannot be compared; the way forward is a fresh copy,
see "No git" below).

## 2. Install, on the user's yes

```
UP apply           # exit 0 updated, 3 blocked (nothing was changed), 5 git is needed, 1 failed
```

It only ever fast-forwards: a file the user changed is never overwritten, and `user/` is never touched. On exit 0
report `from` and `to` (the first 7 characters), what changed in a line or two, the `after` notes word for word,
and the `undo` command. Skills and agents that changed load in a new Claude session: say so.

### When it is blocked (exit 3)

- **`not-a-git-copy`**: this copy was downloaded without git, so there is nothing to update it with. Explain: with
  their yes it becomes a git copy (a hidden `.git` folder of a few megabytes is added and the toolkit's history is
  downloaded; no file of theirs is changed), and updates work from then on. Then `UP apply --convert`. Exit 5 means
  git is not installed: see "No git".
- **`overlap`**: the user (or the `customize` skill, or `agent_models.py`) changed files this update changes too:
  `overlap` lists them. For each one, read the user's version and say what their change was. Then:
  1. `BACKUP save <the overlap files> --label "before update"`.
  2. `git -C REPO stash push -- <the overlap files>`, `UP apply`, `git -C REPO stash pop`.
  3. A file with conflict markers (`<<<<<<<`): read both sides and write the new version with the user's change put
     back on top of it. Show them the result. Nothing of theirs is dropped without their say.
  4. `.claude/agents/*.md` whose only difference is the `model:` / `effort:` lines: take the new file, then
     `python3 REPO/tools/agent_models.py apply` puts their plan's models back.
- **`diverged`**: this copy has commits the other side does not (`ahead`). Look at
  `git -C REPO log --oneline <remote>..HEAD`. Their own commits: on their yes, `git -C REPO merge <remote>` and
  resolve conflicts as above. The toolkit's own old commits (its history was rebuilt): say so, back up the files
  they changed, and ask before moving this copy onto the new history.

### No git (exit 5, or `kind` unknown)

Git is the safe way to update. Print the install command for their system (`update.py` prints it) and let them
choose; never install it without a yes. If they would rather not: download a fresh copy next to this one, copy the
`user/` folder across, and tell them plainly that changes they made to skills are not carried over.

## The daily look

- Off: `python3 REPO/tools/vidkit/settings.py set updates.check false`. On again: `... set updates.check true`.
  `UP status` still works when it is off.
- It runs from the session-start hook (`tools/first_run.py`), at most once a day, takes a few seconds at most and
  stays silent offline. The line it prints repeats once a day until the copy is updated.

## Hard rules

- Never update, convert or merge without the user's yes for that step.
- Never discard the user's changes: no `git reset --hard`, no `git checkout -- .`, no `git clean`, no dropped stash.
- Never push anything anywhere. Never touch `user/`.
- Name every changed or conflicting file by its absolute path.

## What the user can customize

Whether the daily look runs (`updates.check`). Where a git copy gets its updates from is its own `origin` remote: a
fork follows the fork.
