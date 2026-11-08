# Planning the b-roll (the judgement step)

Read `edited_transcript.md` start to finish, every a-roll sheet and every b-roll sheet (the images, not just the
catalog). Then write `recipe_v1.json` = v0 + `broll` + `needs`. Take your time here: the bricks are the edit.

## Where b-roll comes from, in order

1. **The project's own clips**: `sheets.py broll` sheets everything in the footage folder that is not a take.
2. **The user's b-roll library** (optional, when `paths.broll_library_dir` is set):
   `python3 .claude/skills/broll-library/scripts/search.py "<what the words need>" --limit 10 --json`
   returns `{path, start, end, description, tags, source_project}`. Descriptions are search keys, not proof: sheet a hit
   before placing it (`sheets.py broll <recipe> --files "<path>@<start>-<end>"`). Library clips stay where they are (the
   recipe points at them); never copy them into the project.
3. **Other projects' footage or a take's own demo**: a feature the speaker demonstrated on camera in another video is
   usable picture (muted: b-roll never carries sound). Grep that take's `.transcript.json` for the feature's words to find
   the seconds, then sheet the window.
4. **Stills** (a screenshot, a chart the user made): `still_clip.py` turns one into a short clip with a slow push-in.
5. **Motion graphics** for an idea no footage shows (a comparison, a number, a process): the `motion-graphics` skill.

Before planning, list what the speech needs that the project's clips lack (a feature named, a settings screen, a
competitor compared against). That list drives steps 2-5 and becomes `needs` when nothing fits.

A local file the edit uses that sits outside the project (Downloads, Desktop, a phone dump) should be moved into the
project's footage folder first, with the user's yes: archiving keeps what is inside the project. Library and other
projects' clips are linked in place.

## Rules (defaults: the user's preferences override them)

- **Open on the speaker.** No brick in the first 3 s: viewers decide whether to stay by looking at a face.
- **Leave the demos.** Where the a-roll shows the speaker holding the product to the lens, pressing a button, or showing
  a screen, the audience must see it: no brick there. The a-roll sheets are how you know.
- **The brick shows what the words are about.** A clip of a different product goes only over speech about that product.
  If nothing fits, place nothing and add a `needs` entry. A wrong brick is worse than a gap.
- **3-15 s per brick**, cut on calm motion inside one shot. Each source range is used once. A slow-motion brick
  (`speed` 0.4 on a 60 fps clip) reads `dur x speed` seconds of its clip.
- **Edges near jump cuts.** A brick edge 0.1-0.6 s off a jump cut leaves a flash of face; put the edge ON the cut (or let
  `recipe.py lint --fix` stretch it there). A brick that covers a jump cut hides it: that is the classic use of a
  cutaway.
- **Saturate where it is honest**: design talk, specs, prices, comparisons, setup steps. 15-35 % coverage is normal for a
  review with demos; a list-style explainer can go higher.
- **Every brick gets a `why`**: `'<the words>' - <what it shows>`. Notes rounds and the review worksheet read it.
- **Frame rates.** A brick plays its clip in real time unless `speed` is set: a 25 or 30 fps stock clip plays at speed 1
  in a 24 fps edit (size its range as the record duration). Clips at 48 fps or more (`hfr` in the catalog) are
  slow-motion candidates.
- **Portrait clips** (phone screen recordings): `fit: cover` with a `zoom` focus on the content, or `fit: blur`.

## A second opinion (optional, long videos)

For a long edit, spawn one general-purpose subagent per ~10 bricks with this job: "For each brick, read the b-roll
sheet tiles inside `[in_s, in_s + dur x speed]` and the words under `[record_s, record_s + dur]` in
`edited_transcript.md`; answer pass / veto (why) / better sub-range, with the tile times as evidence." Apply the vetoes,
then lint. Skip it for short videos; it costs tokens.
