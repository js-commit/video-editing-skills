---
name: broll-library
description: Build and search a b-roll library - harvest the b-roll a finished DaVinci Resolve edit used (.drp export, or the open timeline in Resolve Studio), index a folder of raw b-roll in place, salvage the good unused footage of a finished project before it is archived, describe every clip from contact sheets so it can be found, and search it by keywords. Use when asked to "harvest the b-roll from X", "add this folder to the b-roll library", "salvage the unused footage", "find b-roll of Y", "have I ever shot Z", "describe / clean up the library", or to set up a b-roll library.
argument-hint: "[search terms | project .drp | folder]"
---

# B-roll library

Turns footage you already shot into a searchable library: every clip gets a
contact sheet (a grid of frames from the shot), a one-line description and
tags, so "overhead shot of hands typing" finds the clip three years later.

**B-roll** is the footage you cut to while someone keeps talking: close-ups of
the thing being discussed, hands at work, the place, a screen. (**A-roll** is
the talking itself.) Good b-roll takes time to shoot and most of it is
reusable: the same product close-up, city skyline or slow-motion pour fits the
next video too. A library pays off the first time it saves you a reshoot, and
it keeps the best moments of a project alive after its folder is archived.

Scripts: `S="${CLAUDE_SKILL_DIR}/scripts"`. Every script has `--help`; JSON on
stdout, progress on stderr.

## Before you start

1. Read `user/preferences.md` if it exists (`## broll-library` and `## general`);
   the user's preferences override this skill.
2. The library folder is settings `paths.broll_library_dir`. If a script exits
   with code 4 it is unset: ask the user where the library should live (suggest
   a folder on their biggest drive, e.g. `~/Videos/B-roll Library`, or a NAS
   share if they have one), save it with
   `python3 "${CLAUDE_SKILL_DIR}/../../../tools/vidkit/settings.py" set paths.broll_library_dir "<folder>"`,
   and re-run. The folder is created on the first harvest.
3. A NAS is optional (`nas.enabled`). If the scripts say the library is not
   reachable, the share is not mounted: ask the user to mount it (macOS Finder:
   Go > Connect to Server, Cmd+K) and never work on a local copy instead.
4. Needs ffmpeg/ffprobe (`python3 tools/vidkit/media.py check`). Nothing else.
5. Privacy: describing, judging and salvaging send contact sheets to Claude (a
   cloud model). Fine for footage made to be published. For private footage
   (family, home), ask first; a search never sends anything.

How the library is laid out, and how to organize footage folders so this works
well: `reference/folder-structure.md` (read it when setting up a library or when
the user asks how to organize their footage).

## Search (the common case)

```
python3 "$S/search.py" "<words>" [--limit 10] [--json] [--include-faces]
```

Keyword scoring over tags, description and the source project / file name;
clips matching every word come first. `--json` gives
`[{path, start, end, description, tags, source_project}]`: use the stretch
`start`..`end` of `path` (a raw file indexed in place is a range of a longer
file). Other skills call this exact command. A description is a search key, not
proof: before telling the user a hit shows something, open its contact sheet
(`--json --verbose` adds the `sheet` path) and look.

## Harvest a finished DaVinci Resolve project

The b-roll an edit used is the best b-roll you have: it already passed your
own taste test.

1. Get the timeline. Either:
   - a **.drp export**: in Resolve's Project Manager, right-click the project >
     Export Project. Works with the free version, Resolve need not be running.
   - **the open timeline** (DaVinci Resolve Studio only, external scripting on
     in Preferences > System > General): `--resolve`. Read-only: it never
     loads, saves or edits anything, and reads the current project.
2. Preview (always first): `python3 "$S/harvest_project.py" <project.drp | --resolve> --dry-run`.
   Check the timeline it picked (the one with the most clips; `--timeline NAME`
   to choose; backup timelines are skipped), the clip count, and
   `missing_media` (moved drive: `--media-root <folder>` relinks by file name).
3. B-roll = clips on video track 2 and up, minus files that also sit on V1
   (the talking head). If the user edits differently, use `--broll-tracks`
   (e.g. `1-` when there is no a-roll). Leave out stock footage or screen
   recordings with `--exclude-under <folder>`.
4. Harvest: the same command without `--dry-run`. Each used stretch is cut out
   of the camera original with half a second of handle on each side (an exact
   H.264 re-encode; `--copy` keeps the original bits but cuts on keyframes),
   into `<library>/clips/<project>/`. Slow motion made by conforming
   high-frame-rate footage in Clip Attributes is baked in; speed changes made
   with Resolve's retime tools are not read (those clips come out at 1x).
   Safe to re-run: already-cut clips are reused.
5. Describe (below), then report: clips, seconds, folder, anything skipped.

## Index a folder of raw b-roll (no project)

For footage that never made it into an edit: a folder of product shots, travel
clips, a card dump the user wants findable. Nothing is copied: each shot is a
time range of the original file.

```
python3 "$S/index_folder.py" "<folder>" [--name <label>] --dry-run
python3 "$S/index_folder.py" "<folder>" [--name <label>]
```

Files are split into shots where the picture changes and every 30 s in long
takes (`--max-length`). Sub-folders named a-roll / aroll are skipped (talking
heads do not belong in a b-roll library; `--include-aroll` to override). If the
user wants the folder moved into the library first, move it into
`<library>/footage/<name>/` (show them the move and get a yes; footage-triage
does this for whole import dumps), then index it there. Then describe.

## Salvage a finished project's unused footage

Before a project is archived or its footage deleted, take one last look at what
the edit did not use. Agents propose; nothing is cut without the user seeing it.

1. `python3 "$S/salvage.py" prep "<project folder>" -o <scratch work dir> --drp <edit.drp>`
   (or `--resolve`, or neither if there is no edit). It finds what the edit and
   the library already used, sheets the rest, and writes `brief.md` and
   `batches.json`.
2. Fill in the "What this project is about" section of `brief.md`: the
   subjects and how to tell them apart on camera, anything the user asked to
   keep or skip.
3. Spawn one `broll-salvage-picker` agent per batch, all in one message
   (`subagent_type: broll-salvage-picker`, prompt: the brief path, the batch's
   `info_files` and its `picks` path).
4. `python3 "$S/salvage.py" apply <work dir> --dry-run`. Exit 3 lists picks to
   fix. Show the user the picks (descriptions, and the sheets for a few); on
   their yes run `apply` without `--dry-run`. Clips land in
   `<library>/clips/<project>-salvage/` already described.

Optional, on a Mac with BulkCut (`apps/bulk-cut`): before step 4, offer
to review the picks in BulkCut, where the user plays each pick, drags its in
and out points, removes the weak ones and marks good moments the agents missed:

```
B="${CLAUDE_SKILL_DIR}/../../../apps/bulk-cut/scripts"
python3 "$B/salvage_review.py" stage <work dir>        # -> <work dir>/bulkcut
python3 "$B/bulkcut.py" open <work dir>/bulkcut
python3 "$B/salvage_review.py" collect <work dir>      # when they say done (BulkCut's Save picks button runs it too)
```

`collect` rewrites `picks/` from the review (the agents' originals stay in
`picks-agent/`). Ranges the user drew without typing a description come back
under `need_description`: look at their frames and write one into the picks
file. Then step 4.

## Describe (after every harvest or index)

```
python3 "$S/describe.py" briefs -o <scratch dir>/describe        # clips with no description
```

Spawn one `frame-describer` agent per printed brief, all in one message
(`subagent_type: frame-describer`, prompt `Brief: <path>`). Then
`python3 "$S/describe.py" collect <scratch dir>/describe` (exit 1 = a brief has
no answers: spawn it again). About 20 clips per agent.

Private footage, or no cloud wanted: `python3 "$S/describe.py" local` does the
same step with the vision model on this computer (`tools/vlm-describe`; nothing
leaves the computer, no agents). It needs `python3 tools/vlm-describe/vlm_describe.py --check`
to say available (Apple silicon Mac). One heavy job; resumable.

## Keep it clean (talking heads and junk out)

```
python3 "$S/judge.py" briefs -o <scratch dir>/judge     # suspicious clips only (--all: every unjudged clip)
```

Spawn one `broll-judge` per brief (prompt `Brief: <path>`), then
`judge.py collect <dir>`. `judge.py prune` lists the a-roll and junk verdicts:
show the user a few sheets with the reasons, then `judge.py prune --apply` on
their yes (`--except ID ...` for clips they want to keep this time, `judge.py
keep ID ...` to keep them for good). Removing never deletes: a cut clip's file
moves to `<library>/_trash/` (the user empties it), a raw original is never
touched, only its catalog entry goes.

## Upkeep

- `catalog.py status`: counts, how many are described and judged.
- `catalog.py check [--apply]`: entries whose file is gone (moved or deleted).
  If most of the library is missing it refuses: that is an unmounted drive.
- `catalog.py remove ID ... [--apply]`: take clips out by hand.
- The catalog is one file, `<library>/catalog/catalog.json`. Only one script
  writes at a time (a lock folder `catalog/.lock`); a second one exits naming
  the holder. Delete the lock folder only if that run is known to be dead.

## Hard rules

- Camera originals and project files are read-only. Never move, re-encode in
  place or delete them.
- Dry run first for every harvest, index and removal; removals need the user's
  yes for the exact list.
- Never delete anything: removed clips go to `_trash/`, the user empties it.
- No Premiere Pro projects: DaVinci Resolve is the only supported editor. A
  Premiere user can open the project in Resolve (File > Import > Timeline,
  from an XML export) and export a .drp, or index the footage folder instead.
- Don't let a description stand in for looking: verify a hit's sheet before
  you claim what it shows.

## What the user can customize

- Which tracks count as b-roll, the handles, clip codec (`--copy`), shot length
  (`--max-length`), the a-roll folder rule.
- The description prompt (`CLIP_PROMPT` in `scripts/describe.py`) and the
  agents' models (`.claude/agents/frame-describer.md` etc.).
- Search scoring (`scripts/search.py`): weights, stop words, synonyms.
- Use `describe.py local` (the on-device model) instead of the cloud agents, always or per folder.
Record lasting choices under `## broll-library` in `user/preferences.md`.
