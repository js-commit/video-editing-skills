---
name: new-project
description: Create a folder for a new video project from the user's project layout (footage, audio, graphics, drafts, finals, work) under their projects folder, optionally noting the DaVinci Resolve project that goes with it, and explain briefly why the structure matters. Use when asked to "start a new project", "create a project for <video>", "new video called X", "set up folders for my next video", or right after setup.
---

# new-project

Makes one tidy folder per video so every skill knows where footage is and
where drafts and finals go, without asking each time.

`SET` = `python3 "${CLAUDE_SKILL_DIR}/../../../tools/vidkit/settings.py"`.

## Before you start

- Read `${CLAUDE_SKILL_DIR}/../../../user/preferences.md` if it exists
  (`## new-project`, `## general`), e.g. a naming habit like "prefix
  projects with the date".
- Needs `paths.projects_dir`. The script exits 4 if it is unset: ask "Where
  should your video projects live?" (suggest `~/Movies/VideoProjects` on macOS,
  `~/Videos/VideoProjects` on Windows/Linux, written as an absolute path),
  save with `SET set paths.projects_dir "<path>"`, re-run.
- The layout comes from settings `project_layout` (see `SET show`). It was
  chosen in setup; don't change it here unless asked.

## Steps

1. Get a project name if the user did not give one: short and descriptive
   ("phone case review", "kitchen tour"). Apply any naming preference.
2. Ask (one line, skippable) whether a DaVinci Resolve project goes with it,
   only if `editor.nle` is `resolve-studio` or `resolve-free`. Default: the
   same name.
3. Dry run, then create:
   `python3 "${CLAUDE_SKILL_DIR}/scripts/new_project.py" "<name>" [--resolve-project "<name>"] --dry-run`
   then the same without `--dry-run`. (A dry run is only worth showing when
   the name or location might surprise the user; otherwise create directly.
   The script never deletes or overwrites anything, and re-running it only
   adds missing folders.)
4. Show the result: the project path (absolute) and its folders as a small
   tree. Teach in two or three lines, unless preferences say they are
   experienced:
   - Camera originals go in the footage folder and are never edited in place.
   - Drafts go to the drafts folder, finals to the finals folder, so a review
     never mixes up versions; scratch files go to work/ and are safe to
     delete when archiving.
   - Transcripts and other sidecars (`<clip>.transcript.json`) sit next to
     their clip and move with it.
5. Resolve (if they use it): the project name was noted in `project.json`.
   Tell them how to create it themselves: in the Project Manager
   (File > Project Manager, or the house icon at the bottom right) click
   New Project and give it that name. Studio users with scripting on can ask
   a Resolve skill to do it. Point out ⌘I / Ctrl+I imports media on the
   Media or Edit page, and to import from the project's footage folder.
6. Offer the next step: copy or move footage into the footage folder (the
   footage-triage skill can sort an import dump), or a first cut with the
   aroll-draft skill.

## Hard rules

- Never move footage into the project without showing the list and getting
  a yes (moving is the footage-triage skill's job; copying is fine on request).
- If the projects folder is on a drive that is not connected, stop and say
  so: don't create a local stand-in.
- Never rename or restructure an existing project folder here.

## What the user can customize

- The folder layout: `SET set project_layout.<part> "<relative folder>"`
  (parts: footage, audio, graphics, drafts, finals, work). Existing projects
  keep their folders; re-run this skill on one to add missing folders.
- Extra folders or a naming scheme: ask the customize skill.
