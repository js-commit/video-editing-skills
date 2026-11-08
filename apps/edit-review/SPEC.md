# EditReview file formats

The contract between EditReview, the `edit-review-notes` skill and anything
else that reads or writes review data. Code against this file; the README is
the user guide.

## Conventions (all files)

- **Seconds are the unit.** Every time is a float number of seconds from the
  first frame of the rendered file ("file seconds"). Timecode is for display
  and Resolve import only.
- **Timecode** is DaVinci Resolve's non-drop `HH:MM:SS:FF` at the file's real
  frame rate: 23.976 / 29.97 / 59.94 are counted at 24 / 30 / 60 frames per
  timecode-second (what Resolve's non-drop ruler shows). A file time `t` is
  frame `floor(t * fps + 1e-6)`.
- **Where files live:** next to the reviewed render, in a folder named after
  it: `export.mp4` -> `export.review/`. The transcript sidecar sits beside the
  render itself (`export.transcript.json`, written by `tools/transcribe.py`,
  format in `docs/transcription.md`).
- **Encoding:** UTF-8 JSON, written atomically (write a temp file, rename).
  Readers must ignore keys they do not know. Writers may add keys.
- **Schema strings** carry a major version (`edit-review/4`). A reader
  accepts its own major version; a breaking change bumps it.

```
export.mp4
export.transcript.json        word-level transcript (tools/transcribe.py)
export.review/
  notes.json                  the reviewer's notes (EditReview, import_notes.py)
  cuts.json                   where each clip starts and ends in this file
  changes.json                what changed since the previous render
  review.jsonl                export_review.py output
  markers.edl                 export_review.py output
  notes_map.json              the edit-review-notes skill's worksheet
  versions/                   transcripts of earlier cuts, parked with their notes
```

## notes.json (schema `edit-review/4`)

Written by EditReview after every change (and by
`.claude/skills/edit-review-notes/scripts/import_notes.py`). Downstream tools
read **only `notes`**.

```json
{
  "schema": "edit-review/4",
  "video": "export.mp4",
  "frame_rate": 29.97,
  "start_timecode": "00:00:00:00",
  "video_duration": 612.48,
  "video_bytes": 734003200,
  "notes": [
    { "id": "6F1C2A9E-3B7D-4C1A-9E0F-2D5B8A7C4E11", "seconds": 277.51,
      "text": "jump cut here", "created_at": "2025-01-01T12:00:00Z" }
  ],
  "archived": [
    { "id": "…", "seconds": 12.0, "text": "too loud", "created_at": "…",
      "archived_at": "2025-01-01T12:30:00Z" }
  ],
  "versions": [
    { "id": "20250101-120000", "superseded_at": "2025-01-01T12:00:00Z",
      "video_duration": 615.2, "video_bytes": 735112000,
      "transcript": "20250101-120000.transcript.json",
      "notes": [ { "id": "…", "seconds": 40.2, "text": "…", "created_at": "…" } ] }
  ]
}
```

| key | type | meaning |
|---|---|---|
| `schema` | string | `"edit-review/4"` |
| `video` | string | the render's file name (no folder) |
| `frame_rate` | number | the file's real frame rate (29.97, not 30000/1001) |
| `start_timecode` | string | `HH:MM:SS:FF` of the file's first frame (from its timecode track, else `00:00:00:00`) |
| `video_duration` | number? | the file's length in seconds when the notes were last saved |
| `video_bytes` | int? | the file's size then |
| `notes` | array | **the live notes**, the only list anything downstream reads |
| `archived` | array? | notes the reviewer marked as dealt with **on this cut** |
| `versions` | array? | notes of earlier cuts of this file name, newest first |

A note:

| key | type | meaning |
|---|---|---|
| `id` | string | unique (EditReview uses an upper-case UUID) |
| `seconds` | number | the playhead when the note was stamped (file seconds) |
| `text` | string | the note, as typed or dictated (may contain line breaks) |
| `created_at` | string | ISO 8601 UTC |
| `archived_at` | string? | set while the note is archived (dealt with) |
| `archived_reason` | string? | optional free text: why it was archived |

Rules:

- Stamps are **late and fuzzy** by design: the reviewer pauses a beat after
  the moment, and arrow-key nudges move in 2 s steps. Consumers look about
  14 s back and 10 s forward and pick the word the note is about.
- Re-exporting the **same cut** (same length within 0.1 s, different
  bytes) keeps every note. Opening a file of the same name whose
  length changed moves the live notes **and** the archived ones into a new
  `versions[0]` entry (the times no longer line up); `notes` and `archived`
  start empty. The old transcript is moved to
  `versions/<version id>.transcript.json` (the newest three are kept).
- A note in a version may carry `archived_at` (it was dealt with before the
  cut changed).
- An unreadable notes.json is never overwritten: EditReview renames it
  `notes.unreadable-<timestamp>.json` and starts fresh.

## cuts.json (schema `edit-review-cuts/1`)

Where the picture changes in the file. Written by
`apps/edit-review/scripts/export_cuts.py` (from the Resolve timeline, or from a
segment list for ffmpeg renders), by the talking-head-ffmpeg recipe renderer,
and at the end of every edit-review-notes round. EditReview only reads it.

```json
{
  "schema": "edit-review-cuts/1",
  "video": "export.mp4",
  "project": "my-project",
  "timeline": "main edit v3",
  "frame_rate": 29.97003,
  "timeline_start_frame": 108000,
  "render_in_frame": 108000,
  "render_out_frame": 126353,
  "duration_s": 612.479,
  "written_at": "2025-01-01T12:00:00Z",
  "cuts": [
    { "index": 1, "start_s": 0.0, "end_s": 3.5035, "start_frame": 0, "end_frame": 105,
      "kind": "clip", "track": 1, "name": "take-03.mov", "source": "/abs/path/take-03.mov",
      "source_start_frame": 412 },
    { "index": 2, "start_s": 3.5035, "end_s": 4.004, "start_frame": 105, "end_frame": 120,
      "kind": "gap", "track": 0, "name": "(gap)" }
  ],
  "overlays": [
    { "track": 3, "start_s": 12.0, "end_s": 15.5, "name": "Text+",
      "why": "no media (title / generator / Fusion / adjustment)" }
  ]
}
```

| key | type | meaning |
|---|---|---|
| `schema` | string | `"edit-review-cuts/1"` (required) |
| `video` | string | the render's file name |
| `project`, `timeline` | string | where it came from; `""` for a segment list unless given |
| `frame_rate` | number | exact rate (29.97003 for 30000/1001) |
| `timeline_start_frame` | int | the timeline's first frame in Resolve (0 for ffmpeg renders) |
| `render_in_frame`, `render_out_frame` | int | the rendered range in timeline frames, out **inclusive** |
| `duration_s` | number | the file's length (required). Readers ignore the sidecar when it differs from the file by more than **0.2 s** |
| `cuts` | array | required, non-empty |
| `overlays` | array | layers that never make a cut (informational) |

A cut: `index` (1-based, time order), `start_s`, `end_s` (file seconds),
`start_frame`, `end_frame` (file frames, end **exclusive**), `kind` (`clip` or
`gap`), `track` (video track of the clip on screen, 0 for a gap), `name`,
and for clips `source` (absolute path or null) and `source_start_frame` (the
source frame on screen at `start_s`, or null). Required for EditReview:
`index`, `start_s`, `end_s`, `track`, `name`, `kind`.

`cuts` is the **flattened picture**: between two edit points, the topmost
full-frame clip; contiguous from 0 to the end, holes as `gap`. Titles,
generators, Fusion comps, picture-in-picture clips (zoom < 0.95) and
semi-transparent clips are listed under `overlays`, never as cuts.
Transitions are invisible to Resolve's scripting API: a dissolve's cut sits
at the clip boundary under it. A cuts.json stops being true the moment the
timeline is edited; it describes THAT render.

## changes.json (schema `edit-review-changes/1`)

What the editor changed since the previous render, so a notes round is
reviewed by its changes instead of watching everything again. Written by
whoever made this render from the last one's notes (the edit-review-notes
skill: `write_changes.py`, or talking-head-ffmpeg's `review.py changes`). It
goes in the **new** render's `.review/` folder and its times are on the
**new** render's clock. EditReview only reads it.

```json
{
  "schema": "edit-review-changes/1",
  "video": "export-v4.mp4",
  "round": "v4",
  "previous": "v3",
  "summary": "Your 7 notes on v3, nothing else.",
  "duration_s": 598.2,
  "written_at": "2025-01-01T12:00:00Z",
  "changes": [
    { "id": "c1", "start_s": 41.2, "end_s": 41.2, "kind": "removed",
      "title": "Repeated sentence removed",
      "what": "Cut the first of the two takes of the price line (3.1 s).",
      "watch": "Does the join sound natural?",
      "note": "I said that twice" },
    { "id": "c2", "start_s": 88.0, "end_s": 93.5, "kind": "added",
      "title": "B-roll of the unboxing" }
  ]
}
```

| key | type | meaning |
|---|---|---|
| `schema` | string | `"edit-review-changes/1"` (required) |
| `video` | string | the new render's file name |
| `round` | string? | this render's name in the review (shown as `previous → round`) |
| `previous` | string? | the render the notes were taken on |
| `summary` | string? | one line for the top of the What changed pane |
| `duration_s` | number | the new render's length (required); ignored when off by more than 0.2 s |
| `changes` | array | required, non-empty |

A change: `id` (unique string), `start_s`, `end_s`, `title` (required);
`what` (what was done, a sentence or two), `watch` (what to look at while it
plays), `note` (the reviewer's note this answers, verbatim), `kind`
(`changed`, `added`, `removed`, `audio`, `music` or `answer`; display only).
`start_s == end_s` is a point: something was removed at that join. The app
sorts by `start_s` and numbers the changes in that order; a jump to a change
starts 1 s before it so the cut into it plays too. A note stamped inside a
change, or up to 2 s after it ends, is attributed to that change.

Every notes round ends with **both** files in the new render's folder:
`changes.json` (what changed) and `cuts.json` (the new edit points).

## review.jsonl (written by `scripts/export_review.py`)

One object per live note, time order:

```json
{"timecode": "00:04:37:12", "seconds": 277.51, "frame_rate": 23.976, "text": "jump cut"}
```

`timecode` includes `start_timecode`, so it matches the Resolve ruler of a
timeline that starts where the render starts.

## markers.edl (written by `scripts/export_review.py`)

One marker per note in the EDL format Resolve writes from
*File > Export > Timeline Markers to EDL*, for *Timeline > Import > Timeline
Markers from EDL*:

```
TITLE: export
FCM: NON-DROP FRAME

001  001      V     C        00:04:37:12 00:04:37:13 00:04:37:12 00:04:37:13
 |C:ResolveColorRed |M:jump cut |D:1
```

The EDL is experimental; `export_review.py --to-resolve` is the dependable
route: it adds the same markers through the scripting API (tagged
`customData` `edit-review:<seconds>`).

## Copy Notes as JSON (clipboard, ⌘⇧C)

```json
{ "video": "/abs/path/export.mp4", "frame_rate": 29.97, "start_timecode": "00:00:00:00",
  "timeline": "my-project / main edit v3", "changes_round": "v4",
  "notes": [ { "time": "4:37.5", "timecode": "00:04:37:15", "seconds": 277.5, "text": "jump cut",
               "cut": 42, "clip": "take-03.mov", "clip_offset_s": 1.25,
               "change": "c2", "change_title": "B-roll of the unboxing" } ] }
```

`timeline`, `changes_round`, `cut`, `clip`, `clip_offset_s`, `change` and
`change_title` are null when there is no cuts.json / changes.json or no match.
Seconds are rounded to 0.1 s here; notes.json keeps full precision.

## shortcuts.json (optional, per user)

`~/Library/Application Support/EditReview/shortcuts.json`, read once at
launch, overrides the default review keys in `Sources/Shortcuts.swift`:

```json
{ "_comment": "anything starting with _ is ignored",
  "playPause": "ctrl+space", "zoomIn": ["ctrl+e", "cmd+="], "goToEnd": [] }
```

Keys are action names (see `ReviewAction` in Shortcuts.swift and the README
table); a value is a key string or a list of them, `[]` unbinds. Key string:
modifiers `cmd`, `ctrl`, `opt`/`alt`, `shift` joined by `+` in front of one key:
`space tab left right up down home end pageup pagedown delete forwarddelete`,
or a single character. Refused (reported in the legend, defaults kept): plain
characters, Return and Esc without cmd/ctrl/opt, unknown names, a key already
bound to an earlier action.
