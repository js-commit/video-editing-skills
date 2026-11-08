---
name: customize
description: Make this toolkit work the user's way - remember a standing preference ("from now on...", "always...", "never..."), change how a skill works (edit its SKILL.md or scripts), create a new skill from a description, change an EditReview or BulkCut keyboard shortcut, or undo any of these. Use for "from now on", "remember that I like...", "stop doing X", "change how <skill> works", "make a skill that...", "add a step to...", "rebind / change the shortcut for...", "undo that change", "put the skill back how it was", "what have I customized?".
---

# customize

This copy of the repo belongs to the user: they can change anything. This
skill does it safely - smallest change that does the job, a backup first,
a one-line summary after, and an easy undo.

Paths: `REPO` = `${CLAUDE_SKILL_DIR}/../../..`;
`PREFS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/prefs.py"`;
`BACKUP` = `python3 "${CLAUDE_SKILL_DIR}/scripts/backup.py"`.

## Before you start

- Read `REPO/user/preferences.md` (`## customize`, `## general`).
- Work out which of the five jobs below the user means. A short, lasting
  rule about results ("cuts too tight", "always 1080p drafts") is a
  **preference** (a). A change to a skill's steps, defaults or scripts is (b).
  If unsure, ask: "Should I just remember that, or change how the skill works?"
  Preferences are lighter and survive updates to the repo; prefer them.

## (a) Remember a preference

1. Pick the heading: the skill it applies to (its folder name under
   `REPO/.claude/skills/`, e.g. `aroll-draft`), or `general` for anything
   that applies everywhere. If it is unclear which skill, ask.
2. Phrase it as one short, general rule in the user's terms, e.g.
   "Leave about half a second of air after each sentence." Not a story.
3. `PREFS add <heading> "<rule>"` (creates the file/heading if missing,
   skips exact duplicates).
4. Confirm in one line: "Noted under aroll-draft in
   <absolute path of user/preferences.md>."

To forget one: `PREFS remove <heading> "<words from it>"`. To list:
`PREFS show [heading]`.

## (b) Change how a skill works

1. Find the skill: `ls REPO/.claude/skills/`, then read its `SKILL.md` and
   any script the change touches. Read `REPO/docs/skill-conventions.md`.
2. Say in one or two sentences what you will change and where; for anything
   bigger than a wording tweak, wait for a yes.
3. Back up first, always (also in a git clone: it protects uncommitted work):
   `BACKUP save <each file you will touch> --label "<few words>"`.
   For files you are about to create, include their paths too: undo then
   removes them.
4. Make the **smallest** edit that does it: change a default, add or reword a
   step, add a hard rule. Keep the conventions: settings through
   `tools/vidkit/settings.py` (never hardcode paths), exit 4 on a missing
   setting, JSON on stdout, Python 3.9+, standard library first, dry runs
   before anything destructive.
5. Verify: `python3 -m py_compile <script>` for every edited script and run
   its `--help`. If the change can be exercised on a short test clip, do it.
6. Summarize in at most four lines: what changed, in which files (absolute
   paths), the backup id, and how to undo ("say 'undo that'"). If `REPO` is a
   git clone (`git -C REPO rev-parse --is-inside-work-tree` prints true),
   add: "`git diff` shows exactly what changed."
7. If the user's preference contradicts the skill's old default, also add a
   preference bullet only when it is a rule about results; don't duplicate.

## (c) Create a new skill

1. Ask (briefly) what it should make, when it should trigger (phrases), and
   which settings or tools it needs. Check no existing skill already does it;
   if one is close, offer to extend that one instead.
2. Name: lowercase, hyphenated, a few words (`podcast-clips`).
3. `BACKUP save .claude/skills/<name> --label "new skill <name>"` (records it
   as new, so undo deletes it).
4. Write `REPO/.claude/skills/<name>/SKILL.md` from
   `${CLAUDE_SKILL_DIR}/reference/skill-template.md`, plus `scripts/` only if
   it needs code. Follow `docs/skill-conventions.md`: frontmatter `name` and
   `description` (what it does + trigger phrases), read preferences first,
   settings via settings.py, teaching tone, hard rules.
5. If it needs a new setting, read it with
   `settings.get("<section>.<key>", default=...)` and tell the user the
   `settings.py set` command; don't edit `user/settings.example.json` unless
   they want it shared.
6. Tell the user the skill exists now and how to trigger it. Claude Code
   picks up new skills in a new session (or right away in recent versions).

## (d) Change an EditReview or BulkCut shortcut (macOS apps)

Read `REPO/apps/edit-review/Sources/Shortcuts.swift` first: its header
explains the current mechanism and the action names. As built in this repo:

- **No rebuild (preferred):** write or update
  `~/Library/Application Support/EditReview/shortcuts.json` with only the
  actions that change, e.g. `{ "zoomIn": ["ctrl+e", "cmd+="] }`; `[]`
  unbinds. If the file exists, show it and save a copy next to it as
  `shortcuts.json.bak` before writing. Then quit and reopen EditReview.
  Plain letters without cmd/ctrl/opt are refused (the note field always has
  focus), and Return/Esc and menu shortcuts are fixed.
- **Change the defaults for good:** back up `Shortcuts.swift`, edit the key
  strings in its `table`, update the shortcut table in the app's README if it
  lists them, then rebuild with `REPO/apps/edit-review/build.sh` and, if the user installed
  it, `REPO/apps/install_apps.sh edit-review` (ask first;
  it takes a minute and needs swiftc).
- Menu shortcuts (⌘O, ⌘/...) can be rebound without code in macOS System
  Settings > Keyboard > Keyboard Shortcuts > App Shortcuts.

If the app's code has changed and these instructions don't match, follow the
file's own header and say so.

**BulkCut** (`REPO/apps/bulk-cut`, the triage app) works the same way: read
the header of `REPO/apps/bulk-cut/Sources/Keymap.swift` for the action names.
Write `~/Library/Application Support/BulkCut/shortcuts.json` with only the
actions that change, e.g. `{ "setIn": "i", "setOut": "o", "loop": [] }` (one
key per action; plain letters are fine here), with the same `.bak` rule, then
quit and reopen BulkCut. A key the user set in BulkCut's Settings (⌘,) wins
over the file. For good: edit `builtIn` in `Keymap.swift`, update the key table
in `REPO/apps/bulk-cut/README.md`, rebuild with `REPO/apps/bulk-cut/build.sh` (then `REPO/apps/install_apps.sh bulk-cut` if installed)
(ask first).

DaVinci Resolve shortcuts are not code: send the user to DaVinci Resolve >
Keyboard Customization (see the editing-coach skill's Resolve tour).

## (e) Undo

1. `BACKUP list` - pick the backup for the change they mean (match the label
   and time; ask if several fit). Note that each undo makes its own
   "before-undo-..." backup, so "latest" may be that one.
2. `BACKUP restore <id>` (dry run) - show what would be restored or
   removed, in plain words.
3. On a yes: `BACKUP restore <id> --yes`. Report the files and that the undo
   itself can be undone (the script prints that backup's id).
4. Git alternative: when the files have no backup but the folder is a git
   clone, show `git -C REPO diff -- <path>` and, on a yes,
   `git -C REPO restore -- <path>` (this discards every uncommitted change in
   that file: say so first).
5. A preference is undone with `PREFS remove`.

## Hard rules

- Back up before every edit to a skill, script, agent or app source file.
- Smallest change; don't refactor, reformat or "improve" nearby text.
- Never edit `user/settings.json` by hand here: use `settings.py set`.
- Never remove the safety rules of a skill (dry runs, asking before deleting,
  uploading or installing) even if asked casually; if the user insists,
  explain the risk once, then do it and note it in the summary.
- No secrets, personal addresses or passwords in any skill file.
- Name every changed file by its absolute path.

## What the user can customize

Everything, including this skill. Its own defaults: backups go to
`REPO/user/backups/` (git-ignored, safe to delete old ones).
