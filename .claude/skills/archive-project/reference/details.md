# archive-project: details

Load this when the user asks how the archive decides what to keep, wants to
restore or move an archive, or a run did something unexpected.

## Where things go

```
<finals_dir>/<project>/            final.mp4, final.srt (sidecars), shorts/..., thumbnails/,
                                   extras/ (rules.json keep.extras), the recipe (recipe mode),
                                   ARCHIVE-MANIFEST.json
<archive_dir>/<project>/           keep: the cleaned project folder, same layout as before
                                   recipe: the recipe(s), the media they play, small text files
<archive_dir>/<project>/external/  files outside the project a recipe used (bundled copies)
<archive_dir>/archive-log.jsonl    one line per archive: when, mode, finals, sizes
<cache_dir>/archive-project/       plans (.plan.json + .plan.txt) and run results (.done.json)
```

`finals_dir` defaults to `<archive_dir>/final-videos`. Nothing is ever overwritten:
an identical file already at the destination (same SHA-256) is skipped; a different
thumbnail, extra or recipe is saved beside it with a timestamp; a different final or
project file blocks the plan (an earlier archive with the same name: rename one).

The folder you archive must be one project's own folder. A drive (`/Volumes/<name>`,
a mount point), a home folder, the standard folders in it (Desktop, Documents,
Downloads, Movies, Music, Pictures...) and any folder that is or holds one of the
folders from settings (projects, inbox, archive, finals, b-roll library, home videos,
music) are refused, by the dry run and again by `execute`.

## The reference gate

Cruft rules only name things a tool can regenerate. Even so, a file that matches a
rule is kept when an editor file still points at it. The script reads:

1. every `.drp` in the project folder (a Resolve project export: a zip of XML whose
   media paths sit in plain text and in zstd-compressed blobs; `zstd` or the
   `zstandard` Python module is needed for the blobs);
2. every `.json` in the project (recipes, plans), except transcripts: any string that
   is a path into the project (absolute, relative, or recorded under another drive
   name: it matches on the part after `/<project folder name>/`).

A referenced folder protects everything inside it. The report lists what was kept
and which file holds it. `unused-media` (off by default) is the opposite: video and
images nothing references. It is refused when there is nothing to judge by (no
`.drp`, no recipe), for Resolve users without a `.drp` export, and when a `.drp`
could not be fully read.

Without a `.drp`, the gate cannot see what Resolve uses. Proxies, caches and drafts
are regenerable anyway (Resolve shows them offline and can rebuild them), but export
the `.drp` first when you can.

## Recipe mode

A recipe is the JSON an ffmpeg skill renders from (talking-head-ffmpeg's
`work/talking-head/recipe_vN.json`, home-video's `work/cut_vN.json`). The newest version
of each recipe family is used (`recipe_v3.json` over `recipe_v2.json`, home-video's
`cut_final.json` over any `cut_vN.json`); `--recipe FILE`
picks one by hand. Everything it plays is copied with its sidecars, external files
are bundled into `external/` unless they already live somewhere durable (the
archive, finals, b-roll library, home-videos or music folders from settings), and the
recipe is rewritten to point at the archived copies. A recipe that points at a file
that does not exist blocks the archive: the video could not be rebuilt.

To rebuild: give the archived recipe to the skill that made it. If the archive
folder moves later (new drive, new NAS share), re-aim its recipes:

```
$A repoint "<new folder>"            # reads the old location from ARCHIVE-MANIFEST.json
$A repoint "<new folder>" --old-root "<path the recipes point at now>"
```

## Restoring a kept project

Copy `<archive_dir>/<project>/` back under your projects folder (or work on it in
place if the drive is fast enough). In Resolve: Project Manager > right-click >
Import Project, pick the `.drp` in `resolve/`, then relink: select the offline clips
in the Media Pool > right-click > Relink Selected Clips, and point at the folder.
ffmpeg recipes already point at the archive folder; after copying them back, run
`$A repoint "<restored folder>"`.

## The plan file

`archive` and `clean` write `<cache_dir>/archive-project/<project>-<mode>-<time>.plan.json`
and a `.plan.txt` beside it (every copy and delete, one per line, with sizes). The
plan holds `copies` (src, dst, size, mtime, role), `deletes` (path, size, mtime,
category), `repoint`, `blockers`, `warnings`. `execute` refuses a plan with blockers,
and refuses (before copying or deleting anything) a plan whose project folder fails
the guards above or that names a delete outside that folder or a copy outside its
destinations: a plan edited by hand never runs. It re-checks every file's size and
time before deleting it (changed files are skipped).

## Exit codes

0 ok, 1 blocked (the JSON on stdout lists why) or a copy failed (nothing deleted),
2 usage / `--yes` missing, 4 a setting is unset.
