# ffmpeg path (talking-head-ffmpeg recipes)

The draft was rendered from a talking-head-ffmpeg recipe
(`<work>/recipe_vN.json`): the whole edit as JSON, rendered by ffmpeg. No
NLE involved, so this path works on any computer. The recipe format and its
tools belong to the `talking-head-ffmpeg` skill (its
`reference/recipe-schema.md`); read that first. Paths: `TH` =
`REPO/.claude/skills/talking-head-ffmpeg/scripts`, `S` = this skill's
`scripts/`.

The render plays the recipe's record clock 1:1, so a note's `seconds` IS a
record time in recipe_vN.

## 1. Worksheet

`python3 $TH/review.py notes DRAFT.mp4 --recipe <work>/recipe_vN.json` prints,
per note, the piece under it (a b-roll brick and its `why`, or the a-roll keep
with its take and source second) and the words around it. Use it alongside
`notes_worksheet.py` (which writes notes_map.json); class every note there.

## 2. Copy, then edit on the OLD clock

Copy `recipe_vN.json` to `recipe_vN+1.json` (the old one is the restore
point; never edit it). Make **every** edit in the copy with times still on
vN's clock (the clock the notes were taken on):

- **Phase 1 (additive)**: add, move or replace b-roll bricks; screenshot
  cards (`python3 $TH/still_clip.py IMAGE --recipe <work>/recipe_vN+1.json`
  makes a brick clip with a slow push-in, or `make_card.py shot`); text
  cards as overlays (`python3 $S/make_card.py text "Big line" "detail" -o <work>/overlays/name.png --size <canvas WxH> --align right`,
  or an animated one from the `motion-graphics` skill); a `NEED BROLL`
  entry when nothing honest exists.
- **Phase 2 (structural)**: remove or shorten a-roll keeps for cuts and
  trims (edges in the pauses), widen a keep to restore a pause, leave a need
  for a re-record. Work latest-first so you can re-read positions as you go.

Then re-place everything on the new clock through the source, not by adding
seconds:

```
python3 $TH/recipe.py carry <work>/recipe_vN.json <work>/recipe_vN+1.json
python3 $TH/recipe.py lint  <work>/recipe_vN+1.json        # --fix stretches a neighbour onto a cut
```

`carry` drops (and lists) any brick whose start or end moment was cut: re-plan
those. `lint` must pass (no a-roll flash under 0.6 s, no overlaps, no missing
files).

The phase-1 gate here is simple: before touching any keep, confirm the
copy's a-roll section is identical to vN's (diff the two recipes' a-roll
entries, or compare the a-roll pieces in `recipe.py show` of both).

## 3. Render and the two files

```
python3 $TH/render_recipe.py <work>/recipe_vN+1.json     # draft -> <name>-draft-vN+1.mp4, writes cuts.json
python3 $TH/recipe.py show <work>/recipe_vN+1.json       # every piece on the NEW clock
python3 $TH/review.py changes NEW_DRAFT.mp4 --list changes.in.json --round vN+1 --previous vN --summary "…"
```

`render_recipe.py` writes `<new draft>.review/cuts.json` itself and runs its
QC. Take the changes' positions from `recipe.py show` on vN+1 (where each new
brick or overlay starts and ends, the join where a keep was removed), never
from the old seconds. `write_changes.py` from this skill writes the same
file if you prefer it.
