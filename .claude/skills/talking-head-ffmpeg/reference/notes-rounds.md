# Notes rounds and special inserts

## A round, step by step

1. The user reviews `<name>-draft-vN.mp4` in EditReview (Space plays/pauses, type a note and press Return, Tab changes
   speed, arrows seek; see `apps/edit-review/`), or sends timestamps in chat.
2. `python3 $K/review.py notes <draft-vN.mp4> --recipe <work>/recipe_vN.json` prints a worksheet: per note, the brick or
   keep under it, the words around it, what is nearby. Notes are stamped a beat late: look a few seconds either side.
3. Copy `recipe_vN.json` to `recipe_v(N+1).json` and make every change in it **with times still on vN's clock** (the
   clock the notes were taken on):
   - move / trim / swap / drop a brick: edit its `record_s`, `dur`, `in_s`, `file`;
   - restore a cut word: widen the keep's `in_s` / `out_s`; cut something: drop or split a keep;
   - a missing shot: add a `needs` entry and tell the user.
4. If any a-roll keep changed: `python3 $K/recipe.py carry <recipe_vN> <recipe_v(N+1)>`. It moves every brick, overlay
   and need onto the new clock **through the source frame** (vN record frame -> take + source frame -> new record frame),
   never by adding float seconds. Anything whose moment was cut is dropped and listed: re-place it.
5. `recipe.py lint <recipe_v(N+1)> --fix`, then `render_recipe.py`. Unchanged pieces are reused from the segment cache,
   so a round re-encodes only what changed.
6. Write the round's `changes.json` (one row per note, on the NEW render's clock) with `review.py changes`, so the user
   can jump straight to each change in EditReview. `cuts.json` is already written by the render.
7. **Generalise every note.** One "this brick covers my demo" means re-checking every brick against the a-roll sheets;
   one "too long" on an insert means checking the others. If the note is a lasting preference, add a bullet under
   `## talking-head-ffmpeg` in `user/preferences.md` and say so in one line.

## Inserts that carry their own sound

A phone clip of a live test (its own sound), a voice-over over a chart: these are a-roll keeps, not bricks. Enter their
ranges in `aroll` after the keep that ends on the sentence before, with `gain_db` to level them to the takes (measure
both with `ffmpeg -i X -af ebur128 -f null -` and set the difference). The loudness pass then covers them. Keep a voice-
over insert short: two or three sentences, about 10 s.

A recording with no picture (a voice-over `.m4a`): wrap it in a black frame-sized clip first (ffmpeg `color` source plus
the audio, the recipe's fps), run aroll-draft on that clip if it needs cutting, enter its keeps in `aroll`, and cover
every second of it with bricks back to back (the lint shows any gap, which would show black). Under a long insert, a
quiet bed of the room's own tone sounds more natural than digital silence.

## Stills, screenshots, prices

- A screenshot or chart becomes a clip with `still_clip.py` (push-in toward the part being talked about). Crop out
  anything private first: order numbers, addresses, notifications, serial numbers, other people's names.
- A price tag or one-line correction is a frame-sized RGBA PNG in `overlays`, on the side of the frame away from the
  speaker's face (check a frame of that moment). An overlay never covers the face.
- Give a still clip 0.5 s more than its slot, so `lint --fix` can stretch it onto a nearby jump cut.

## Speed-ups and silences

- "Long pause here" on a voice-over: shorten silences of 0.45 s or more to about half (keep at least 0.22 s) by
  narrowing the keeps around them. Find silences on the audio, not from transcript word gaps: transcripts often omit soft
  filler words, and cutting by word times chops into them.
- A sped-up stretch (a long process at 2x) is a separate clip made with ffmpeg (`setpts=PTS/2`, `atempo=2`, a "2x"
  badge), entered as an a-roll insert.
