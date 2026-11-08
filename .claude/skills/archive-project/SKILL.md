---
name: archive-project
description: Archive a finished video project off the working drive. LEAN (the default) keeps only the finals and thumbnails (plus reusable b-roll, harvested into the library first) and deletes the project folder; KEEP moves the cleaned, self-contained project (footage, Resolve .drp export, ffmpeg recipes repointed) to the archive drive or NAS; RECIPE keeps an ffmpeg-built video's master plus its JSON recipe and the camera originals it uses, so it can be rebuilt. Also CLEANs just the regenerable cruft (proxies, render cache, optimized media, a-roll draft work, drafts, scratch) out of a project, reference-gated. Dry run first, copy and verify before any delete, the user approves the exact list. Use when asked to "archive this project", "we're done with X", "free up space", "delete everything but the final", "keep the project", "move X to the NAS / backup drive", "clean up the project folder", or "how much cruft is in X".
argument-hint: "[project folder or name] [lean|keep|recipe|clean]"
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/archive_project.py scan:*), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/archive_project.py clean:*), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/archive_project.py archive:*), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/export_drp.py:*), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/selftest.py), Bash(python3 tools/vidkit/settings.py get:*), Bash(du:*), Bash(df:*), Bash(ls:*)
---

# Archive a finished project

When a video is out, its project folder should leave the working drive. Fast
drives are small and expensive: one finished project with camera originals,
proxies and render cache can take 50-200 GB. Archiving frees that space,
puts the finals somewhere safe, and keeps your working drive for what you
are editing now.

`A="python3 ${CLAUDE_SKILL_DIR}/scripts/archive_project.py"` (write the full path out
when you run it; the shell does not set `CLAUDE_SKILL_DIR`).

## The modes

| mode | what survives | where | what is deleted |
|---|---|---|---|
| **lean** (default) | finals (+ their `.srt`/transcript sidecars), thumbnails, reusable b-roll (in the library, via broll-library) | `paths.finals_dir/<project>/` | the whole project folder |
| **keep** | everything except cruft: footage, transcripts, the Resolve `.drp` export, recipes (repointed); finals also go to the finals folder | `paths.archive_dir/<project>/` | the local folder, once every copy verifies |
| **recipe** | for ffmpeg-built videos (talking-head-ffmpeg, home-video): the master + the JSON recipe, and every file the recipe plays (camera originals, music, graphics) with their sidecars | master + recipe in the finals folder, media in `paths.archive_dir/<project>/` | the local folder |
| **clean** | the project stays where it is | - | only regenerable cruft |

The default mode comes from `archive.default_mode` (lean unless the user changed
it). Pick keep only when the user says to keep the project / footage / timeline;
offer recipe when the video was built from an ffmpeg recipe and they might want
to re-render or re-edit it later. "Clean up X" or "what cruft is in X" is clean,
not an archive.

## Before you start

1. Read `user/preferences.md` (`## archive-project` and `## general`); it overrides
   these defaults (e.g. "always keep the project", "keep my .srt files").
2. Settings it reads (`python3 tools/vidkit/settings.py get <key>`; exit code 4 means
   unset: ask one short question, save with `settings.py set`, re-run):
   - `paths.finals_dir` - where finished videos live. If unset, finals go to
     `<paths.archive_dir>/final-videos`.
   - `paths.archive_dir` - keep / recipe destination: a folder on another drive or
     a NAS share. Suggest a backup drive, not the working drive.
   - `nas.enabled`, `nas.mount_path` - if the destination is on the NAS, it must be
     mounted first; the script says how (Finder: Cmd+K, `smb://<nas>/<share>`). Never
     write a NAS address or password into settings or this repo.
   - `paths.broll_library_dir` - when set, lean and recipe ask for the b-roll harvest.
   - `editor.nle` - Resolve users need a `.drp` export for keep mode.
   - `archive.checksum` (optional, default false) - always verify copies with SHA-256.
3. ffmpeg/ffprobe (to check each final plays). `zstd` lets the script read the
   compressed parts of `.drp` files; without it, unused-media cleaning is refused.

## Steps

1. **Find the project and the finals.** The project is a folder path or a name
   under `paths.projects_dir`. Finals are the videos in the project's finals folder
   (`project_layout.finals`, not its drafts). If the user's final lives elsewhere,
   pass `--final FILE`. A final that is not rendered yet blocks a lean archive.
2. **Scan** (read-only): `$A scan "<project>"`. Tell the user the size, the cruft
   per category, which files are protected because a `.drp` or recipe uses them,
   and any references outside the folder.
3. **Resolve users: export the project as `.drp`** (keep mode needs it; it also
   lets the reference gate see what Resolve uses). Ask the user to save first
   (Cmd+S / Ctrl+S). Studio: `python3 ${CLAUDE_SKILL_DIR}/scripts/export_drp.py --list`,
   then `--project "<name>" --out "<project>/resolve"` (read-only: it only exports).
   Free: Project Manager (Shift+1) > right-click the project > Export Project.
4. **B-roll (lean / recipe):** if a library is set up, offer the broll-library
   skill's harvest of this project's reusable shots before the footage goes:
   `.claude/skills/broll-library/scripts/harvest_project.py <project.drp | --resolve>`
   (what the edit used) and `salvage.py prep / apply` there (good footage no
   timeline used); that skill runs both. Then pass `--broll done`, or
   `--broll skip` if the user declines.
5. **Dry run:** `$A archive "<project>" [--mode keep|recipe] [--broll done|skip]`
   (or `$A clean "<project>"`). It writes a plan and a plain-text list of every file
   it would copy and delete, and lists blockers (unmounted NAS, missing final, not
   enough space, recipe pointing at missing files...). Fix blockers and re-run.
6. **Confirm.** Summarise: the mode, what survives and where (absolute paths), what
   is deleted (the per-folder summary), space freed, warnings. Offer the list file.
   Ask for an explicit yes. In clean mode, ask which categories (default set, plus
   `unused-media` only if they want it: `--category` replaces the default set).
7. **Execute:** `$A execute "<plan.json>" --yes` (add `--checksum` for SHA-256 on
   every copy). It copies, verifies, repoints recipes, writes `ARCHIVE-MANIFEST.json`
   and appends to `<archive_dir>/archive-log.jsonl`, and only then deletes. Files
   changed since the plan are skipped and reported.
8. **Report:** mode, freed space and free space left, every final's absolute path,
   thumbnails folder, the archive folder (keep / recipe), anything skipped or left
   behind. Then the things outside the folder the user may want to tidy:
   - the Resolve project still sits in Resolve's database with offline media;
     delete it from the Project Manager if they want (right-click > Delete);
   - Resolve's own render cache (Playback > Delete Render Cache > All);
   - a reminder that one copy is not a backup (below).

## Backups: the 3-2-1 rule

Keep 3 copies of anything you care about, on 2 different kinds of storage, 1 of
them off-site (cloud or another house). The archive drive is one copy, not a
backup. If the script warns that the destination is on the same drive as the
project, the files are tidied, not safer. Mention this once, briefly.

## Hard rules

- Dry run first, always. Only `execute ... --yes` changes anything, and only after
  the user approved that plan's list. Never edit a plan to add deletions.
- Copy, verify, then delete; a failed copy stops everything before any delete.
- Never delete outside the project folder. Never follow symlinks out of it. The script
  refuses a drive, a home folder (or its Desktop, Documents, Movies...) and any folder
  holding your projects, archive or library as "the project"; never work around that.
- Sidecars travel with their clip (`<stem>.transcript.json`, `.srt`...).
- A file a `.drp` export or a recipe still points at is never cleaned as cruft.
- Never connect to Resolve to change anything: the only Resolve call is the
  read-only `.drp` export.
- Never widen cruft rules with a one-off `rm`; change `rules.json` instead.

## Customize

- **What counts as keep / cruft:** `${CLAUDE_SKILL_DIR}/rules.json`. `keep.extras`
  adds files lean archives keep (e.g. `"*.srt"`, `"audio/voiceover/*"`);
  `cruft` holds the categories, their patterns and whether a default clean takes
  them. After editing, run `python3 ${CLAUDE_SKILL_DIR}/scripts/selftest.py`.
- **Default mode:** `settings.py set archive.default_mode keep`.
- Standing preferences ("always checksum", "never ask about b-roll") go in
  `user/preferences.md` under `## archive-project`; add one when the user says so.
- Details (the reference gate, plan format, restoring a kept project, moving an
  archive): `reference/details.md`.
