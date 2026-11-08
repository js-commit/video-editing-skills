# BulkCut file formats

Two JSON files connect BulkCut to the skills. Both sit in the folder BulkCut
opens. Everything else the app keeps (sessions, caches, the debug log) is its
own business and may change.

| File | Written by | Read by |
|---|---|---|
| `bulkcut.json` (the manifest) | a skill (`scripts/bulkcut.py stage`) | BulkCut |
| `bulkcut-review.json` (the review) | BulkCut, after every change, in review mode | the skill (`scripts/bulkcut.py read`) |

Times are seconds into the file. Paths in `files` are relative to the folder
(a subfolder's file is `"sub/clip.mov"`; a plain file name also matches).

## `bulkcut.json`

```json
{
  "schema": "bulkcut/1",
  "staged_by": "bulkcut.py stage",
  "id": "20260101-120000",
  "title": "Salvage picks: my-blender-review",
  "mode": "review",
  "legend": {"pick": "salvage pick", "beat": "sequence clip", "mine": "yours", "library": "already used"},
  "send": {
    "label": "Save picks",
    "command": ["/usr/bin/python3", "/abs/path/salvage_review.py", "collect", "/abs/work"],
    "steps": ["Writes your ranges back as the picks.", "Then tell Claude you are done."]
  },
  "files": {
    "clip_a.mp4": {
      "source": "/abs/path/to/the/original/clip_a.mp4",
      "kept": true,
      "description": "Close-up of the lamp switching on.",
      "by": "frame-describer",
      "tags": ["close-up", "lamp"],
      "why": "the only steady shot of the switch",
      "privacy": "a phone screen with messages at 0:04",
      "context": "what was said over it in the edit",
      "origin": "cut from A001.mov 1:02.0-1:09.5",
      "speed": 0.5,
      "proposals": [
        {"start": 3.0, "end": 6.0, "kind": "pick", "text": "Lamp switching on, warm light.", "by": "salvage picker"},
        {"start": 8.0, "end": 9.5, "kind": "beat", "label": "beat 2: lid off", "sequence": "lamp-unboxing",
         "text": "Hands lift the lid.", "by": "sequence agent"}
      ],
      "library": [{"start": 0.0, "end": 2.0, "text": "", "by": "", "clip": "used by the edit"}],
      "segments": [{"start": 0, "end": 4.2, "description": "wide of the desk", "tags": [], "quality": "good",
                    "shaky": false, "note": null}]
    }
  },
  "sequences": [
    {"name": "lamp-unboxing", "kind": "unboxing", "beats": [{"file": "clip_a.mp4", "in": 8.0, "out": 9.5}]}
  ]
}
```

Every field is optional except `files`.

- `id`: the proposals are staged once per id. The first time BulkCut opens the
  folder with a new id, each listed file's staged edits are replaced by its
  proposals (`bulkcut.py stage` sets a fresh timestamp, so restaging proposes
  again). Same id: the user's work is kept.
- `mode`: `"review"` makes a review folder (below). Anything else, or none:
  a normal folder; the notes show and the proposals are staged as ordinary
  keep ranges, which the user's Apply would crop to (after the review sheet).
- `send`: in review mode, the toolbar button's label and the command it runs
  after saving (argv, first item an absolute path; it runs with the user's
  environment plus `/opt/homebrew/bin` and `/usr/local/bin` on `PATH`; its
  output streams into the sheet). `steps` are shown before it runs. Without
  `send`, the button is "Done" and only saves.
- `legend`: what the colours are called in this folder.
- Per file:
  - `kept: false` starts the file "not kept" (staged for delete; in review
    mode nothing is ever deleted) unless it has proposals.
  - `proposals`: staged as keep ranges. `kind` `"pick"` is purple, `"beat"`
    teal (a clip of the sequence named by `sequence`), anything else yellow
    (an ordinary range). `text` and `by` feed the description box. `label` is
    drawn on the range.
  - `library`: stretches a library already holds, drawn orange and read
    only; sections-only playback still plays them.
  - `description`, `by`, `tags`, `why`, `privacy`, `context`, `origin`,
    `speed`, `segments`: shown in the notes panel (⌘I) and the clip list
    (`privacy` as an orange flag). Read only.
- `sequences`: for the focus filter (F) and the review sheet. A beat's `file`
  is a name in `files`.

## Review mode

- Files may be symbolic links to the originals (`bulkcut.py stage` makes
  links; `--copy` copies). Outside review mode, links to files are skipped.
- Nothing is trashed, trimmed, rotated or re-encoded. ⌫ marks a file "not
  kept". The user's ranges, turns and zooms are only recorded.
- `bulkcut-review.json` is written when the folder first opens with a new
  manifest id, and after every change (about 0.4 s after it).

## `bulkcut-review.json`

```json
{
  "schema": "bulkcut-review/1",
  "manifest_id": "20260101-120000",
  "saved": "2026-01-01T12:05:00Z",
  "folder": "/abs/path/to/the/review/folder",
  "files": {
    "clip_a.mp4": {
      "kind": "video",
      "source": "/abs/path/to/the/original/clip_a.mp4",
      "deleted": false,
      "ranges": [
        {"start": 3.0, "end": 6.5, "kind": "pick", "note": "Typed by the user"},
        {"start": 10.0, "end": 12.0, "kind": null}
      ],
      "turns": 0,
      "zoom": null
    }
  }
}
```

- One entry per video and photo in the folder, edited or not.
- `deleted`: the user marked the file not kept (then `ranges` is empty).
- `ranges`: what is kept, sorted, overlaps merged, slivers dropped. `kind` is
  the proposal's kind it came from (`"pick"`, `"beat"`) or `null` for one the
  user drew. A range the user joined to another of a different kind becomes
  `null`. `note`: the description the user typed (replaces the proposal's
  `text`); `label` and `sequence` are carried over.
- No ranges and not deleted: nothing kept, unless the file had no
  proposals and the tool treats untouched files as kept (its choice).
- `turns`: quarter turns clockwise (0-3). `zoom`: the part of the picture to
  keep, as fractions of the turned frame (`x`, `y`, `w`, `h` from the top
  left), or null.
- `manifest_id` differing from the manifest's `id` means the folder was
  restaged after this review (`bulkcut.py read` reports `"stale": true`).

## `bulkcut.py`

```
python3 apps/bulk-cut/scripts/bulkcut.py stage SPEC.json -o DIR [--copy] [--id ID]
python3 apps/bulk-cut/scripts/bulkcut.py open DIR
python3 apps/bulk-cut/scripts/bulkcut.py read DIR      # exit 3: never opened
python3 apps/bulk-cut/scripts/bulkcut.py where         # exit 2: app missing
```

`SPEC.json` is a manifest whose `files` is a **list** of entries, each with an
absolute `source` and an optional `name`; `stage` links them into `DIR`, keys
the manifest by name, maps sequence beats given by source path to names and
skips formats BulkCut cannot open (listed under `skipped`). `read` prints one
row per file: `name`, `source`, `deleted`, `kept` (has ranges and not
deleted), `ranges`, `turns`, `zoom` and the original `proposed` ranges, to
compare.

## Recipe: shots to check

For a skill that wants a yes / no (and maybe a trim) on a few shots, e.g. the
home-video skill's held shots with a stranger in them:

```json
{
  "title": "Held shots: your call",
  "legend": {"pick": "held shot"},
  "files": [
    {"source": "/abs/IMG_0412.MOV", "why": "a man fills the foreground",
     "proposals": [{"start": 12.0, "end": 15.0, "kind": "pick",
                    "text": "Kids on the pier at sunset", "by": "home-video"}]}
  ]
}
```

`bulkcut.py stage spec.json -o <project>/work/bulkcut-check`, then `open`.
Tell the user: leave the purple range to keep the shot (drag its edges to
trim), ⌃⌫ to drop it; the toolbar's Done when finished. Then `read`: a range
still there is a yes with its (maybe new) in and out; none, or `deleted`, is a
no.

## Recipe: salvage picks

`scripts/salvage_review.py stage <work>` / `collect <work>` wraps this for the
broll-library skill's salvage pass: picks in purple, what the edit and the
library already used in orange, and Send writes the reviewed ranges back as
the picks files. See the broll-library skill.
