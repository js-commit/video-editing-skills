---
name: motion-graphics
description: Animated motion graphics for a talking-head video, timed to the speaker's words - full-frame cutaways (a chart, a comparison, a process), transparent panels beside the speaker (a stat, a command, a short list) and lower thirds, in one consistent style (one shape that morphs, springs, an optional cursor) that the user can restyle with their colours, font and brand. Written as small HTML pages, rendered headless with a Chromium-family browser already installed (Chrome, Edge, Brave, Chromium; nothing installed, the user's browser profile untouched), encoded with ffmpeg and placed into a talking-head-ffmpeg recipe. Use when asked for "motion graphics", "animated overlays", "an animated chart / stat / callout", "a lower third", "a cutaway that explains X", "graphics for this video", or for notes on clips this skill made.
argument-hint: "<project or recipe_vN.json> -- which lines want graphics, any real figures to show"
allowed-tools: Read, Write, Edit, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *)
---

# Motion graphics

**What it makes:** short animated clips that explain what the speaker is saying, placed into a
**talking-head-ffmpeg** recipe: full-frame cutaways go in as b-roll bricks, transparent panels and lower thirds as
overlays, and the recipe renders the draft. It is the last layer of an edit: after the a-roll cut and the b-roll,
before the final render.

**When motion graphics help** (tell the user this if they are new): when the words describe something you cannot film
(a number, a comparison, a process, a list of steps, a command), when a chapter changes, or to name the speaker (a
lower third: a name card in the bottom third of the frame). They hurt when they cover a demo, an emotional or personal
moment, or arrive so often that the face is never on screen. Less is more: a few well-timed graphics beat one every
line.

The house style, the default every clip starts from:
- **One shape that never cuts.** A pill becomes a card becomes a chart: it morphs size, corners and colour between
  states, and its content swaps with a short blur. No hard cuts or wipes between separate cards.
- **Springs**, with at most a tiny overshoot; leading and trailing edges on different springs so things stretch.
- **A cursor** that clicks and drags where an interaction helps explain (optional; panels usually have none).
- **Every change lands on a spoken word** (word times from the transcript).

```
M=${CLAUDE_SKILL_DIR}/scripts                          # python3, stdlib + ffmpeg + a Chromium-family browser
K=${CLAUDE_SKILL_DIR}/../talking-head-ffmpeg/scripts    # the recipe, lint and renderer
W=<project>/<work>/talking-head                       # the recipes (talking-head-ffmpeg's timeline.py prints it)
MO=$W/motion                                           # plan.json  clips/  dist/  out/  sheets/
```

`clips/` and `plan.json` are the source of truth; `dist/` and `out/` are rebuilt from them.

## Before you start

- Read `user/preferences.md`: `## general` and `## motion-graphics`. The theme lines there (`- accent: #ff6a00`,
  `- background:`, `- card:`, `- pill:`, `- text:`, `- muted:`, `- accent2:`, `- highlight:`, `- font:`,
  `- mono font:`, `- brand:`) are applied by `build.py` to every clip; `build.py --show-theme` prints what it found.
  No theme = the dark default palette and the system font. Other bullets there are style preferences for you to follow.
  When the user describes their brand ("orange and black, Inter font"), offer to save it as these lines.
- `python3 $M/browser.py check` finds the browser and test-renders a page (headless, temporary profile, nothing touched).
  None found: tell the user which browsers work; the path can be set with `settings.py set motion_graphics.browser <path>`.
- A talking-head-ffmpeg recipe must exist (`recipe_vN.json`, the one the user last reviewed).

## 1. Read the edit

```
python3 $M/cues.py $W/recipe_vN.json                 # the words on THIS recipe's clock, jump cuts, bricks, overlays
python3 $K/sheets.py aroll $W/recipe_vN.json         # a-roll tiles every 6 s
```

Read the whole transcript and every a-roll sheet. Know where the speaker demos, where the bricks already are, and where
the frame has empty space (often above the shoulder on the side they are not facing; check per take). Ask only what you
cannot see, in one question round: density (default medium), the real figures for any number they say but do not show,
lines they want left on their face.

## 2. Plan, and get a go before writing any clip

Show a table, one row per clip: `# | in-out (record) | the words | what the shape does, on which words | full / panel | why`.

**How much of the frame a clip takes is the key call: give the reason per clip.**
- **Full-frame cutaway** (becomes a brick): the line describes something to see. 3-10 s, then give the face back. Never
  in the first seconds, never over a demo or a personal line. Leave at least 2 s of face between cutaways and bricks.
- **Panel** (becomes an overlay): a transparent card in the empty part of the frame while the speaker stays on screen:
  a stat, a label, a short list, a command. It can run 15 s+ as one continuous morph. It must stay clear of the face
  and hands at every moment (step 4 proves it) and ends as a chip, the way it came in.
- **Lower third**: a panel in the bottom-left or bottom-right third (`examples/03-lower-third.html`), usually once, early.
- **Nothing**: the line is about the speaker, or it sits too close to another clip.

**Density:** light 2-4 clips per minute, medium 4-7, heavy most lines with short gaps of face. Count the existing
bricks: graphics plus b-roll should still leave the speaker on screen most of the time.

**Content:** never invent a number, price, quote or result. Use the user's own figures (name the source in the plan),
relative bars without numbers, or labels taken from their words; list what is illustrative. One idea per clip, about
one change per spoken beat (0.4-1.2 s apart). Map each idea to the interaction vocabulary in `reference/engine-api.md`.

Write `$MO/plan.json`:

```json
{"recipe": "recipe_v3.json",
 "clips": [{"id": "01", "name": "build-times", "kind": "full", "in": 32.40, "out": 39.20,
            "line": "the words it covers", "why": "'twice as fast' - the two times as bars",
            "illustrative": "none: the user's measured times"}]}
```

`recipe` is the recipe (in `$W`) whose clock `in`/`out` are on.

## 3. Build

One fragment per clip in `$MO/clips/NN-name.html`: start from the closest example in `${CLAUDE_SKILL_DIR}/examples/`
and follow `reference/engine-api.md`. Cues per clip: `python3 $M/cues.py $W/recipe_vN.json --in <clip in> --to <clip out>`
(clip-local word starts and ends): a change goes on a word's start, a landing on its end. Set `T` = the slot + 0.5 s.
Stage `W`/`H` = 1920x1080 for a 16:9 recipe (render `--scale` covers bigger canvases). Use palette names (`C.accent`,
`C.card`), never hex codes, so the user's theme reaches every clip.

```
python3 $M/build.py $MO/clips/*.html                 # -> $MO/dist/NN-name.html (open one in a browser to watch it loop)
```

## 4. Check stills on the key words

```
python3 $M/render.py stills $MO/dist/NN-name.html $MO/sheets/NN.jpg 0.4 1.2 2.1 ... [--recipe $W/recipe_vN.json --at <clip in>]
```

Pick each state's settled moment plus a couple of mid-morph frames. With `--recipe --at`, a panel is drawn over the real
picture at those record times: that is how you prove it never covers the face or a hand. Look at every sheet yourself;
small text needs `--tile 960 --cols 2` or `--crop w:h:x:y`. Fix anything clipped, cramped, unreadable, off-word, or a
cursor leaving the frame, then sheet again.

## 5. Render

```
python3 $M/render.py clip $MO/dist/NN-name.html --recipe $W/recipe_vN.json
```

- Opaque clip -> `out/NN-name.mp4` (H.264); panel -> `out/NN-name.mov` (ProRes 4444 with alpha) or `--webm` (VP9 with
  alpha, smaller). At the recipe's fps, frame count checked.
- `--sub 4` (default) averages 4 screenshots per frame into motion blur, about 2-4 s of rendering per second of clip;
  `--sub 1` for a quick look.
- **Drafts** are fine at `--scale 1` (1920x1080). Before the **final**, re-render every clip at the recipe's size:
  `--scale <recipe width / 1920>` (2 for 4K). The same layout comes out sharp; the final render warns about any clip
  still too small.
- Real footage inside a clip: the browser cannot seek a `<video>` frame-exactly, so leave a hole in the page and lay the
  footage in afterwards with an ffmpeg `overlay`.

## 6. Place, lint, draft

```
python3 $M/place.py $MO/plan.json $W/recipe_vN.json $W/recipe_vM.json      # M = N + 1
python3 $K/recipe.py lint $W/recipe_vM.json --fix
python3 $K/render_recipe.py $W/recipe_vM.json
```

Cutaways become `broll` bricks (the flicker rules apply; `--fix` can use a clip's 0.5 s tail to reach a jump cut),
panels become `overlays` with `fade: 0`. Earlier motion entries are replaced, so re-running is safe. A cutaway over an
existing brick is an error unless the plan decided it and you pass `--yield-broll`.

**Hand-over:** the draft (absolute path) and its recipe, every clip as `time -> full/panel -> words -> what it shows`,
what is illustrative, and which real figures you still need from the user.

## 7. Notes rounds

1. Find the clip from its `why` (`motion NN: ...`) in the recipe or `review.py notes`.
2. Edit its fragment, `build.py`, re-render only that clip, `place.py` from the same plan into the next recipe.
3. Generalise: one "too small to read" means re-checking every clip's text size. Lasting taste -> a bullet under
   `## motion-graphics`.
4. **The a-roll changed under the graphics?** Run `place.py` from the old plan into the new recipe: it carries each
   in/out through the source frame. ERROR = a clip's in or out point was cut (re-plan it); WARN = the words under it
   changed (re-time its cues with `cues.py --in <new in>`, re-render). Then update `plan.json`.

## Style defaults (restyle via preferences)

- **Colour:** dark canvas `#22252b`, cards `#2c3038`, pills `#3a3f4b`, white text, muted `#9a9ca3`; one accent per idea
  (blue `#3987e5`, then orange / aqua / yellow for a second or third series); highlight rings `#FFD400`. A panel uses a
  dark card so it reads over a bright room. The theme lines replace any of these.
- **Type:** the system UI font (or the theme's `font:`), a monospace font for commands, file names and terminals. One
  icon set, one stroke weight (`M.icon`).
- **Minimum sizes at 1080p:** text never under 34 px after the camera zoom; titles 44-58 px, labels 34-40 px, a big
  stat 96 px+. Phones show YouTube small.
- **Avoid:** bouncy easing, particles, glows, gradients on UI chrome, mixed icon strokes, dead time, stock-template moves
  (a bar sliding in from the edge, word-by-word kinetic type, wipes between separate cards), made-up data.

## Scripts

| script | does |
|---|---|
| `browser.py` | finds Chrome / Chromium / Edge / Brave / Vivaldi on macOS, Windows, Linux; headless DevTools client |
| `cues.py` | the words on a recipe's clock; `--in` gives a clip's clip-local cues |
| `build.py` | fragment -> self-contained page (engine, theme, cursor, local images inlined) |
| `render.py clip` | page -> .mp4 (opaque) or .mov / .webm with alpha, motion blur, frame-count checked |
| `render.py stills` | labelled contact sheet; `--recipe --at` draws a panel over the real picture |
| `place.py` | plan.json -> the recipe's bricks and overlays, re-anchored through the source when the a-roll changed |

`engine/motion.js` (springs, morphing scene, cursor, palette) and `engine/base.css` are shared by every clip: a fix there
fixes all. Credits: `NOTICE.md` (MIT engine, Lucide icons).

## Hard rules

- Never invent figures, prices, quotes or results. Placeholders are marked and listed in the hand-over.
- Never cover the speaker's face or a demo. Prove it with a stills sheet over the real picture.
- Never write clips before the user approves the plan.
- The browser runs headless with a temporary profile only; never open, script or read the user's own browser session.
  Never reference web URLs in a clip: renders are offline.
- Drafts are local: no upload, no `--final` until the user asks.

## What the user can customize

The theme (colours, fonts, brand) via preferences; density; whether a cursor appears; minimum text size; the style
rules above (say "from now on..." and the bullet is saved). New interaction patterns or icons go into
`engine/motion.js` or a new example via the `customize` skill.
