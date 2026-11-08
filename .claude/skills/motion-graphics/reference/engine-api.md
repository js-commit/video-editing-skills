# Writing a clip

A clip is a small HTML fragment in `<motion>/clips/NN-name.html` (`<motion>` = `<project>/<work>/talking-head/motion`). `build.py` wraps it with the engine
(`engine/motion.js`), the page shell (`engine/base.css`) and a cursor into one self-contained page where `seek(t)` draws
the frame at clip time `t`. Every style is a pure function of `t`: no CSS transitions, no timers, no `requestAnimationFrame`,
no state carried between frames. That is what lets `render.py` render any frame on its own, four times per frame for
motion blur.

Read `examples/01-pill-to-chart.html` (full-frame cutaway), `examples/02-side-panel.html` (transparent panel) and
`examples/03-lower-third.html` (name card) before the first clip of a session: they are the quality bar and the starting
points.

## Fragment skeleton

```html
<title>04 Setup steps</title>
<style>/* clip-specific CSS: classes for this clip's text and parts */</style>

<div data-slot="world">  <!-- optional: elements beside the shape (a drop target, a folder tab) --> </div><!--/world-->
<div data-slot="shape">
  <!-- one layer per state; .L layers are anchored inside the shape -->
  <div class="L" id="Lnotes"> … </div>
  <div class="L" id="Ldoc"> … </div>
</div><!--/shape-->
<div data-slot="over">   <!-- optional: drawn above the shape, unscaled by it (a stamp, a flying key, a callout) --> </div><!--/over-->

<script>
const $=id=>document.getElementById(id), C=M.C;
const DOC=5.1, DRAG=[6.9,7.8];                 // cues: clip-local seconds from `cues.py <recipe> --in <clip in>`
M.scene({
  W:1920, H:1080, T:10.5,          // the recipe's frame size; T = the slot + 0.5 s (lint --fix stretches into it)
  bg:C.bg,                         // canvas colour; null = transparent (a panel -> .mov with alpha)
  center:[960,540],                // the screen point the camera centres on (a panel: the empty part of the frame)
  intro:0.15,                      // the shape pops in at this time; null = already on screen
  outro:9.6,                       // optional: shrinks + fades out from here, gone ~0.2 s later (a panel whose slot
                                   //   ends mid-sentence; a cutaway just holds and needs none)
  SH:{                             // the states the one shape morphs through
    notes:{w:780,h:560,r:36,bg:C.card,cam:1.3},
    doc:{w:600,h:720,r:28,bg:C.card,cam:1.2},
  },
  start:'notes', SEQ:[[DOC,'doc']],               // [clip time, state] - each on its word
  layers:[
    {el:'Lnotes', tin:0.15, tout:DOC, anchor:'t'}, // anchor 'c' centre (default), 't' top-centre, 'l' left-centre
    {el:'Ldoc', tin:DOC, tout:null, anchor:'t', update:(t,g)=>{ /* per-frame content, e.g. typing */ }},
  ],
  cursor:{size:44, clicks:[2.3], drags:[DRAG], keys:[[0,760,460],[1.2,760,460],[1.9,330,250]]},
  geom:(t,g)=>g,     // optional: change geometry (follow the cursor while dragged, g.fx/g.fy camera focus)
  extra:(t,g)=>{},   // optional: per-frame work outside layers (world elements, indicators)
});
</script>
```

**Coordinates are world pixels.** The shape is centred at world (0,0) unless `geom` moves it (`g.cx`, `g.cy`). The
camera draws world -> screen as `center + cam x (world - focus)`. Pick `cam` per state so the state fills its part of the
frame: about 1.1-1.6 for cards, 1.5-2.2 for pills in a cutaway; 1 for a panel (size it in screen pixels instead). The
cursor keeps a constant size on screen.

Layer content is placed relative to its anchor: `left:-330px; top:40px` inside an `anchor:'t'` layer is 330 px left of
centre, 40 px below the shape's top edge, and rides the top edge as the shape grows. **A world point inside a top-anchored
layer is `(left, top - h/2)`** for a shape of height `h` centred at the origin: cursor keys that should land on a row in
the layer use that (the 01 example's hover on bar B: layer top 426, card h 540 -> world y 156).

Centre a one-line chip on its anchor with `class="row" style="left:0;top:0;transform:translate(-50%,-50%)"` (the row's own
transform is free; `M.apply` only transforms the `.L` layer).

Each slot's `</div><!--/name-->` closing marker is how `build.py` finds it: a slot without one is an error.

## Engine API (`window.M`)

| Call | What it does |
|---|---|
| `M.C` | The palette: `bg` #22252b, `card`, `pill`, `grid`, `ink` white, `ink2`, `muted`, `accent` (= `blue` unless themed), `blue`, `orange`, `aqua`, `yellow`, `red`, `ring` #FFD400 (highlight rings), `light` (a light shape on dark footage). The user's theme (preferences `## motion-graphics`) overrides these: use `C.accent`, `C.bg`, `C.card`… in the script and the same names as CSS variables in `<style>` (`color:var(--muted)`, `background:var(--card)`), never hex codes, so a restyle reaches every clip. |
| `M.track(v0, [[t, value, spring?], …])` | A value that changes target many times: the sum of one closed-form spring per change. Returns `t => value`. |
| `M.ctrack('#hex', [[t,'#hex'], …])` | The same for colours. Returns `t => 'rgb(...)'`. Colours must be `#rrggbb`. |
| `M.MORPH`, `M.FAST`, `M.SLOW`, `M.SOFT`, `M.CAM`, `M.INSTANT` | Spring presets `[stiffness w, damping z]`. FAST/SLOW for leading/trailing edges; INSTANT for invisible resets. |
| `M.vis(t, tin, tout, {din, lin, lout})` | Content swap: the exit blurs out fast, the enter waits `din` then blurs in over `lin`. Returns `{o, blur, s, a, b}`. |
| `M.apply(el, v)` | Applies a `vis` result to an element (opacity, blur, scale). |
| `M.path([[t,x,y], …])` | Cursor or any point path, eased between keys with a slight human arc. |
| `M.crossTimes(f, t0, t1, thresholds)` | When a rising value first crosses each threshold: trigger springs from a dragged value. |
| `M.count(t, t0, d, a, b, decimals)` | A number counting from a to b over [t0, t0+d], eased, as a string. Only real figures go in (SKILL.md). |
| `M.BRAND` | The `brand:` line of the user's theme (empty when unset), for a chapter card or lower third. |
| `M.icon(name, size, colour, strokeW?)` | Icon from `M.IC`, stroke normalised so all icons match. |
| `M.setText(el, s)` | Set text only when it changed (cheap per frame). |
| `M.eo`, `M.eio`, `M.clamp`, `M.lerp`, `M.S` | Easing and spring helpers. |

Icons in `M.IC`: arrow, check, x, plus, folder, terminal, file, pencil, coin, clock, chip, sparkle, search, battery, star,
user. Add more as 24-grid stroke paths (Lucide's are ISC) to `engine/motion.js`, so every clip shares them.

**Images** (a screenshot, an app icon, a product photo): `<img src="/abs/path/in/the/project.png">` - `build.py`
inlines it as a data URI. A screenshot inside a morphing card with a camera push-in is a good way to show an app or a
web page. Never reference a web URL: a render must not depend on the network (`build.py` warns). A logo is an SVG or
PNG the user supplies, saved in the project; an SVG drawn with `fill="currentColor"` renders black in an `<img>`, so
put `color="#ffffff"` on its root `<svg>`.

## Patterns

| Pattern | How | Where |
|---|---|---|
| Pill -> card -> control | `SH` states + layers with `tin`/`tout` on the words | 01 |
| Bars on the words that name them | per-bar `M.track(0, [[cue, width, spring]])`, label/value `M.vis` on the same cue, value from `M.count` | 01 |
| Tooltip / ring landing on the winner | `M.vis` with a short `lin`, a translate or pad that settles as `v.a` reaches 1 | 01 |
| Typing | `TEXT.slice(0, n)` with `n` from time, and a caret that stops blinking once the line is done | 02 |
| Lower third | a dot that stretches into a name card, the role line swapping in on a word, `outro` to leave | 03 |
| Counter | `M.count` on the word that says the number | 02 |
| Transparent panel | `bg:null`, `center` on the empty part of the frame, `cam:1`, ends as a small chip (it leaves the way it came in); `outro` takes the chip off before the slot ends | 02 |
| Liquid indicator | two `M.track`s for the left/right edges; the edge moving forward rides `M.FAST`, the trailing one `M.SLOW` | - |
| Direct manipulation | while the cursor is held the value follows its position; on release it springs from where it was | - |
| Drag and drop | `geom` sets `g.cx/cy` from the cursor while held; a world-slot drop target; `g.fx` moves the camera focus | - |

## Interaction vocabulary

Map what the speaker says onto one of these:
- primary action (pill + click)
- progress (loader, bars, lanes)
- confirmation (check, toast)
- live status (island)
- detail card with a drag
- slider with rubber band
- toggle
- tabs
- chart with tooltip
- search and filter list
- file -> drag -> drop target
- terminal typing
- side-by-side comparison
- counter / big stat
- chapter card

## Gotchas

- Never put `will-change` on anything the camera scales: text renders blurry.
- Text swapping inside a morphing container needs its own enter and exit timing (`M.vis` din/lin/lout), or the old and new
  text overlap.
- `mix-blend-mode: difference` labels must sit in a layer that has the blend mode itself. A filtered parent isolates them.
- Items that slide under a highlight need `M.FAST` springs, or the highlight row sits empty for a moment.
- Keep the cursor inside the frame at every camera zoom, including mid-morph. A panel usually has no cursor.
- Size a chip to its text plus 2 x 60 px; a chip sized to the text alone clips it. The stills sheet is where that shows.
- `M.ctrack` needs `#rrggbb`: no `rgba()`, no names. Shape fills stay opaque; use the palette.
- `ui-monospace` does not resolve in headless Chromium (it falls back to a serif): use `.mono` (the theme's mono font,
  then SF Mono / Menlo / Consolas / DejaVu Sans Mono).
- A font that is not installed falls back silently to the system font: check a stills sheet after changing `font:`.
- A clip ends by holding its last state, so T can run past the slot; the recipe plays exactly the slot.
- `M.count` has no thousands separator: `Math.round(+M.count(t,t0,d,0,3741)).toLocaleString('en-US')` -> "3,741".
- A CSS `-webkit-line-clamp: 2` block trims a long real description to two lines with an ellipsis and keeps its words
  verbatim.
