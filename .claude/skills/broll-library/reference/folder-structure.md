# Organizing footage so a b-roll library works

## The library folder

Pick one folder for the library (settings `paths.broll_library_dir`), ideally on
the biggest drive you have or a NAS. The scripts fill it like this:

```
B-roll Library/
  clips/                 clips cut out of finished projects
    my-blender-review/     one folder per project harvested
    my-blender-review-salvage/   good footage the edit never used
  footage/               whole folders of raw b-roll moved in (indexed in place)
    city-timelapses/
  catalog/
    catalog.json         every clip: file, time range, description, tags
    sheets/              one contact sheet (frame grid) per clip
    removed.jsonl        what was taken out, and when
  _trash/                clips removed from the library; empty it yourself
```

You can browse `catalog/sheets/` in Finder or Explorer to flip through the
library visually; the catalog keeps the description and tags.

Raw folders can also stay where they are (an archive drive, the NAS): indexing
records their absolute path. If such a folder moves, index it again at its new
place and run `catalog.py check --apply` to drop the stale entries.

## Project folders

The skills expect every video project in its own folder under
`paths.projects_dir`, laid out by `project_layout` (the `new-project` skill makes
it). The default:

```
Projects/
  my-blender-review/
    footage/            camera originals
      aroll/            the talking-head takes
      broll/            everything you cut away to
    audio/  graphics/  output/  work/
```

What helps the library most:

- **Keep a-roll and b-roll apart** (folders whose name contains `aroll`/`a-roll`
  vs `broll`). Indexing skips a-roll folders, and salvage treats them as
  talking-head angles.
- **Keep camera originals.** The library cuts from originals, never from proxies
  or renders. Archive the project only after harvest and salvage.
- **Stock footage and screen recordings in their own folder**, so a harvest can
  leave them out (`--exclude-under`).
- **Name the project folder after the subject** ("blender-review", not
  "video-12"): the folder name becomes `source_project`, which search also
  matches.

## When to run what

| Moment | Run |
|---|---|
| A video is published | harvest the edit (.drp or `--resolve`), describe |
| Before archiving / deleting its footage | salvage, describe |
| A card full of b-roll with no project | footage-triage routes it to the library, then index + describe |
| A pile of old footage on a drive | index the folder in place, describe |
| Looking for a shot | search |
