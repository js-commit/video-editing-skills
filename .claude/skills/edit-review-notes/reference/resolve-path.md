# Resolve path (DaVinci Resolve Studio)

The draft was rendered from a Resolve timeline. Everything here goes through
Resolve's scripting API, which needs **DaVinci Resolve Studio** running with
the project open (Preferences > System > General > External scripting using:
Local). With the free version, do steps 1-2, then hand the user the plan as a
list of timecodes and actions to do by hand.

Paths: `S` = this skill's `scripts/`, `BB` =
`REPO/.claude/skills/broll-brick-layer/scripts`, `APP` =
`REPO/apps/edit-review/scripts`. Edits made through the API are **not** in
Resolve's undo history (Cmd/Ctrl+Z won't take them back): the backup is the
undo.

## 0. Is the timeline still the draft?

The notes are on the draft's clock. If the user edited after rendering, the
seconds no longer point at the same words. Compare the draft's length with
the timeline's (`python3 $BB/inventory.py --project P --aroll T -o inv.json`
reads the whole timeline, read-only). A different length: locate each note
by its words in the timeline instead of by seconds, and say so.

## 1. Restore point and fingerprint

```
python3 $BB/backup.py create --project P --timeline "T" -m "before review notes"   # .drp + "T backup <time>"
python3 $S/resolve_notes.py fingerprint --project P --timeline "T" -o <review>/aroll-before.json
```

(`resolve_notes.py backup --timeline T` makes just the timeline copy if
`backup.py` is not available.) The fingerprint is the a-roll's item list
(track 1 by default; `--tracks 1,2` for a two-camera edit).

## 2. Phase 1: additive

- **Replace / move** an existing b-roll shot: remove it first,
  `python3 $S/resolve_notes.py remove-layer --timeline T --track N --at S`
  (dry run; add `--apply`), then lay the new piece in the freed slot.
- **B-roll**: write the picks as a placement plan (broll-brick-layer's
  `reference/formats.md`: `media`, `use_src_start_s`, `use_src_end_s`,
  `record_s`, `why`), then
  ```
  python3 $BB/check_plan.py plan.json       # flashes, overlaps, short pieces
  python3 $BB/apply_plan.py plan.json --dry-run
  python3 $BB/apply_plan.py plan.json
  ```
  `record_s` is seconds from the timeline start, which is the draft's clock
  when the draft is a render of the whole timeline.
- **Screenshot card**: `python3 $S/make_card.py shot IMAGE -o <project graphics>/card-name.mp4 --size <timeline WxH> --fps <timeline fps> --dur <slot length + 1>`,
  then place it like b-roll (it replaces the picture under it).
- **Text card**: `python3 $S/make_card.py text "Big line" "detail" -o <graphics>/text-name.mov --size … --fps … --dur … --align right`
  (ProRes 4444 with transparency), placed with a second plan whose
  `"track_name": "Text"` puts it on its own track above the b-roll.
- **Gaps**: no honest shot found -> a red marker
  `NEED BROLL: <subject>` with the note and where you looked
  (`resolve_notes.py markers` with `"color": "Red"`).

Phase-1 gate, all three:

```
python3 $S/resolve_notes.py verify --timeline "T" --against <review>/aroll-before.json   # must be identical
python3 $BB/flicker_audit.py --project P --timeline "T" --aroll-tracks 1                 # 0 findings
python3 $BB/inventory.py --project P --aroll "T" -o <review>/inv-phase1.json
```

`verify` passing here is the last moment the a-roll should equal the draft;
phase 2 changes it on purpose.

## 3. Phase 2: structural, latest first

For each note, highest `seconds` first, re-reading the timeline after each:

- **Cut / trim / repeat / drop a section**: find the a-roll items that make
  up the span (inventory). If the span's edges fall on item edges:
  ```
  python3 $S/resolve_notes.py ripple-delete --timeline T --start A --end B          # dry run: lists items
  python3 $S/resolve_notes.py ripple-delete --timeline T --start A --end B --apply
  ```
  A ripple delete in Resolve moves every later item on every track and the
  markers along, shortens a b-roll piece that straddles the range and drops
  one inside it. When an edge falls inside an item, the script refuses:
  split it first. Ask the user to put the playhead on the edge (in a pause)
  and press **Cmd+B** (Windows/Linux: **Ctrl+B**, Split Clip) on the a-roll
  clip, or with many trims rebuild the a-roll from a fresh cut list
  (aroll-draft) instead of repeated ripples.
- **Restore a pause**: `python3 $BB/seam_audit.py --project P --timeline T --plan seams.json`
  names the seams and how many frames each side can give back; keep only the
  seam the note is about in a copy of that file, then
  `python3 $BB/ripple_extend.py --project P --timeline T --plan one-seam.json`
  (check each script's `--help`: they are broll-brick-layer's).
- **Re-record / add a section**: a red marker `RE-RECORD: <note>` /
  `ADD: <note>` at the spot; cut the old span only if the note says so.

Phase-2 gate: `inventory.py` again and diff its V1/A1 items against
`inv-phase1.json`: the only differences must be the spans the notes removed
(and the frames a restore added). Then `flicker_audit.py` again (0
findings), and check that no b-roll or text piece now runs onto words it
was not laid for.

## 4. Markers for the user (optional)

A blue marker per applied note makes "what did you do with my note" easy to
answer inside Resolve. Build the list from the FINAL positions (inventory),
never by arithmetic on the draft's seconds:
`[{"seconds": 41.2, "name": "NOTE 3: <note>", "note": "applied: <what>", "color": "Blue"}]`,
then `python3 $S/resolve_notes.py markers --timeline T --file markers.json`.
`resolve_notes.py clear-markers --timeline T` removes them again.

## 5. Render, cuts.json, changes.json

Render with the `resolve-export-draft` skill to a new draft file (it writes
cuts.json when it can). Otherwise `python3 $APP/export_cuts.py NEW_DRAFT`
while the timeline is open. changes.json positions come from the final
inventory (`record_s` of the pieces you laid, the join where a span was
removed), then `write_changes.py` (SKILL.md step 4).
