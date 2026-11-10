# The look

Left alone, every clip comes out the same: a dark card, a pill, one blue accent, content that blurs in. It is the look
of the tool, so it is the look of everyone who uses the tool, and banning it only moves the clips to the next default.
What breaks it is input from outside the tool, settled before the first clip and written as numbers.

A video has **one look**, in `<motion>/look.json`. `build.py` lays it over the user's theme and gives it to every clip,
so a clip never writes a hex or a font name of its own (`reference/engine-api.md`, "The look in a clip").

## Where it comes from

- **The user's theme** (the colour, font and brand lines under `## motion-graphics` in their preferences) is their
  brand. When it exists, its colours and faces are fixed: quote them, never round or replace them. The look then
  decides everything the theme does not say: the medium, the shapes, the shadow, the motion, what is banned.
- For everything else, and for all of it when there is no theme, take the first of these that exists:
  1. **A reference the user gave**: a film, a frame, a brand they like. It gives its grammar, never its content: how
     long a state holds, how things enter and leave, which colour does which job, the scale and weight of the type.
     Pull frames from it with ffmpeg, put them beside your stills, and write down what you measured apart from what
     you guessed.
  2. **The subject's own world.** What the video is about already has a look: a product's packaging and interface,
     the materials it is made of, the room it was filmed in. Take it from the user's footage and from files they give
     you (a screenshot, a brand guide, a logo). A camera review can look like a contact sheet; a keyboard review like
     its keycap legends; a terminal tool like its own terminal.
  3. **The default palette** (dark canvas, white text, blue accent, yellow ring). Say in the plan that it is the
     fallback, and offer to save a theme; never arrive at it by not deciding.

One look per video: graphics the recipe already carries (charts, cards, title images) either match it or get restyled.

## The LOOK line

Write the look as a brief to yourself, a number wherever an adjective would go. It is `line` in `look.json` and goes in
front of the user with the plan table.

```text
SOURCE:  what the look is taken from, and what was measured from it
MEDIUM:  the one medium this is (paper and ink, the product's interface, a spec label, a contact sheet), with its numbers
GROUND:  hex, and its texture if it has one; INK: hex; ACCENT: hex and the one job it may do
TYPE:    display face + weight + px + tracking; body face the same; mono face
SHAPE:   corner radius per kind of state, border px, shadow (offset, blur, opacity) or none
MOTION:  springs as damping ratio; the swap (blur px, or none); how this medium moves
BANNED:  the defaults below that this source does not use, plus what this video must not become
```

| The word | Becomes |
|---|---|
| premium | a material with numbers: matte card stock with a 1 px edge and no shadow; anodised metal as two flat greys |
| modern | a type system: one grotesque at two weights, the stat at 9% of the frame height with -2% tracking |
| clean | a grid and a ration: 96 px margins, the accent on one mark per state |
| techy | the subject's own interface drawn at its real proportions, never a HUD |
| playful | springs at damping 0.45-0.6 on position and size only |

## A look is one medium

A look holds together when it is the rules of one medium, not a palette. A two-colour print look is five rules and
nothing else: paper is one flat colour; ink A carries every word and every structural line; ink B is one accent, one
focus per frame; where the inks overlap a third colour appears; every tint is a halftone, never an opacity.

Motion comes from the same medium. A printed frame is laid down plate by plate, paper is cut and lifted, an interface
responds to a pointer, a label is stamped. So a look sets `blur` (0 when the medium does not blur) and its springs, and
its shapes take the medium's form: a paper slip has 0-4 px corners and no shadow, a product window has that product's
own radius and title bar. The one shape still morphs and never cuts; what it is made of changes.

## Banned by default

Where generated graphics land when nothing is decided. Each is banned unless the look's source uses it, and then only
the way the source does:

- a black or dark navy ground with small elements floating in its middle;
- glow, bloom, neon, lens flares, floating particles; gradients on UI chrome; purple or blue gradients;
- glass cards; pill-shaped chips and buttons as the default container;
- a cream paper ground with a serif display, italic accent words, "01 / 02" labels and small mono caps labels (the
  second default, the one you reach after banning the dark one);
- everything centred; everything arriving at once; every element fading and sliding up;
- text that moves while it is read; a title that keeps drifting or scaling after it lands;
- breathing, floating or pulsing loops standing in for motion; click ripples; bounce on UI;
- corner brackets, frame borders, HUD readouts as decoration;
- three cards in a row, a KPI grid, a dashboard, a pie chart, a title over a dimmed screenshot;
- a logo docked in a corner;
- stock-template moves: a bar sliding in from the edge, word-by-word kinetic type, a wipe or hard cut between separate
  cards; mixed icon strokes; dead time; made-up data.

After the first stills sheet, name every default it used anyway, from this list or not, add each to `banned` in
`look.json`, and fix the clips. The list grows with the video.

## Composition numbers

- The hero of a cutaway fills at least 40% of the frame's height or width. A small object in the middle of an empty
  frame is not a shot: push the camera in (`cam`) or give it a world. A panel is sized to the free space instead.
- A clip is an information card: what it says is on screen within about 2.5 s, then it holds, so any paused frame reads
  as a finished poster.
- One hero move per beat. A secondary move travels 50-70% as far and starts 100-200 ms later; everything else is still.
- Text holds 0.5 s plus 0.3 s a word. Too many words: cut words, never shrink type (SKILL.md's minimum sizes stand).
- An accent at 5% opacity disappears in the encode: 15-25% for a tint, full strength for the one focus.

## Motion by role

- **Springs are named by damping** (the second number of `M.MORPH` and its siblings): 1.0 never overshoots, 0.7-0.85
  reads considered, 0.4-0.6 playful, under 0.3 a cartoon. Size and position may overshoot; opacity and colour never do
  (`M.ctrack` is already critically damped). A look changes the family in `springs`.
- **Arrive slow, leave clean.** A landing takes longer than a leaving: an exit is 40-50% shorter than its entrance
  (`M.vis` defaults: in 0.26 s, out 0.12 s) and is one motion, never slide, stop, then leave.
- **Overlap.** The next element starts when the previous is 30-50% done. Fully sequential looks robotic, all at once
  looks cheap. List items 40-80 ms apart, words 60-120 ms.
- **A landed title is dead still.** The motion moves on to the next element or to the camera.
- **Vary the entrance** between the clips of one video. The same pop-in on every clip is the tell.

## Charts as pictures

- One number at a time, and it is the biggest thing on screen. A count-up runs about 1-1.6 s, ends on the word that
  says the number, then holds. Figures are tabular already (`#stage` sets `tnum`).
- Build in reading order: the frame and axis, a reference line, the data drawing in, then one annotation on the point
  that matters. Annotate on the mark; no legends.
- Highlight one series in the accent and grey the rest (`C.muted`). A chart with one thing to say says it in its title.
- Real data only, rounded the same way everywhere, with a small source line on screen ("median of 5 runs, measured by
  the creator").
- The same object carries across states: the bar that won becomes the stat the next state is about.

## look.json

The values below show the file's shape. A look copied from here is only the next default.

```json
{"source": "the product's box in take 3 and the brand guide the user supplied (measured: ground, ink, accent; guessed: the body face)",
 "line": "MEDIUM spec label. GROUND #f1ece1 uncoated stock. INK #16150f. ACCENT #e8431f on the winning mark only. TYPE ...",
 "banned": ["dark ground", "drop shadows", "pills"],
 "colors": {"bg": "#f1ece1", "card": "#fbf8f1", "pill": "#e2d9c5", "ink": "#16150f", "ink2": "#4a473d",
            "muted": "#a39d8c", "accent": "#e8431f", "ring": "#16150f"},
 "fonts": {"ui": "'Helvetica Neue', Arial, sans-serif", "display": "'Maker Display', 'Helvetica Neue', sans-serif",
           "mono": "Menlo, Consolas, monospace",
           "faces": [{"family": "Maker Display", "src": "assets/fonts/MakerDisplay-Bold.woff2", "weight": 700}]},
 "shadow": "none",
 "springs": {"MORPH": [15, 1]},
 "blur": 0}
```

- `source`, `line`, `banned` are for you and the user; the rest reaches the clips. Every key is optional: what is left
  out keeps the theme, and under that the defaults.
- **`colors`** are roles, each `#rrggbb`: `bg` the cutaway ground, `card` and `pill` the two surfaces, `grid` rules and
  axes, `ink` / `ink2` / `muted` text from strongest to quietest, `accent` the one focus, `ring` the highlight ring,
  `blue` `orange` `aqua` `yellow` `red` for a second or third series, `light` a light shape over dark footage.
  `build.py` refuses a look whose text is under 4.5:1 on `bg`, `card` or `pill`.
- **`fonts`**: `ui`, `display` (`class="display"`) and `mono` (`class="mono"`) are CSS font-family lists. A face that is
  not installed on this computer is a file the user supplies and has the right to use: save it in the project (for
  example `<motion>/assets/fonts/`) and list it in `faces` (`src` absolute, or relative to `look.json`). `build.py`
  inlines it; nothing is installed and nothing is fetched.
- **`shadow`** is the shape's `box-shadow` (`"none"` for a flat medium); **`blur`** the content swap's blur in px;
  **`springs`** replaces `MORPH`, `FAST`, `SLOW`, `SOFT` or `CAM` as `[stiffness, damping]`.
- A change to the look is a change to every clip: rebuild and re-render them all.
- A look the user wants on every video belongs in their preferences as theme lines; offer to save it.
