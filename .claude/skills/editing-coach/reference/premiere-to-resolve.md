# Coming from Premiere Pro: keyboard cheat sheet

Default keys on macOS (Windows/Linux: ⌘ = Ctrl, ⌥ = Alt). Both apps change
defaults between versions, and anyone may have customized theirs: confirm a
key in Resolve's menus (each item shows its shortcut) or in Keyboard
Customization's search.

## Two ways to migrate

1. **Resolve's Premiere preset**: DaVinci Resolve > Keyboard Customization
   (⌥⌘K) > preset menu (top right) > Adobe Premiere Pro. Quick, but it is
   modeled on an older Premiere layout, so some keys differ from current
   Premiere (check the trim keys Q/W, razor/add edit, and track targeting).
2. **Resolve defaults + a few remaps** (recommended for most): learn Resolve's
   own keys, and remap only the handful your fingers keep reaching for
   (often Q/W ripple trims, C razor, V selection). Save it as your own preset.

Concepts that differ:
- **Track targeting** in Premiere ≈ **Auto Track Selector** in Resolve (the
  small arrow-box button on each track header). It decides which tracks a
  razor, ripple delete or trim-to-playhead affects.
- **Source patching** ≈ Resolve's **destination controls** (V1/A1 buttons
  left of the track headers).
- **Sequence** = **timeline**. **Program monitor** = **timeline viewer**.
  **Bin** = **bin** in the Media Pool. **Effect Controls** = **Inspector**.
- **Lumetri** ≈ the **Color page**; **Essential Sound / audio track mixer** ≈
  the **Fairlight page**; **Export (Media Encoder)** ≈ the **Deliver page**.
- Ripple and roll trims in Resolve: switch to **Trim mode (T)**, then drag
  an edit point (ripple) or its center (roll); drag the middle of a clip to
  slip/slide.

## Key map

| Action | Premiere Pro (default) | DaVinci Resolve (default) |
|---|---|---|
| Play / stop | Space | Space |
| Shuttle back / stop / forward | J / K / L | J / K / L |
| Mark in / out | I / O | I / O |
| Clear in and out | ⌥X (Windows: Ctrl+Shift+X) | ⌥X |
| Previous / next edit point | ↑ / ↓ | ↑ / ↓ |
| Selection tool | V | A |
| Razor/blade tool | C | B |
| Cut at playhead (targeted tracks) | ⌘K | ⌘B |
| Cut at playhead (all tracks) | ⇧⌘K | ⌘B with every track's auto select on |
| Ripple trim previous edit to playhead | Q | ⌘⇧[ (Ripple Start to Playhead) |
| Ripple trim next edit to playhead | W | ⌘⇧] (Ripple End to Playhead) |
| Trim (no ripple) to playhead | ⌥Q / ⌥W | ⇧[ / ⇧] |
| Ripple delete | ⇧⌦ / ⌥⌫ on Mac (Shift+Delete on Windows) | ⇧⌫ or ⌦ |
| Delete (leave gap) | ⌫ | ⌫ |
| Ripple edit / rolling edit tool | B / N | Trim mode T (then drag edit / center) |
| Slip / slide tool | Y / U | Trim mode T (drag clip middle) |
| Rate stretch / speed | R / ⌘R | Retime controls ⌘R (speed change dialog: R) |
| Snapping | S | N |
| Link / unlink | ⌘L | ⌥⌘L (link clips); linked selection ⌘⇧L |
| Enable / disable clip | ⇧E | D |
| Add marker | M | M |
| Next / previous marker | ⇧M / ⇧⌘M | ⇧↓ / ⇧↑ |
| Insert / overwrite | , / . | F9 / F10 |
| Match frame | F | F |
| Extend edit to playhead | E | E |
| Default transition (video+audio / video / audio) | ⇧D / ⌘D / ⇧⌘D | ⌘T / ⌥T / ⇧T |
| Zoom timeline in / out | = / - | ⌘= / ⌘- |
| Zoom to fit | \ | ⇧Z |
| Nudge clip one frame | ⌘← / ⌘→ (Windows: Alt+← / →) | , / . |
| Export | ⌘M | Deliver page (⇧8 in many versions) |
| Import | ⌘I | ⌘I |
| New sequence / timeline | ⌘N | ⌘N |
| Undo / redo | ⌘Z / ⇧⌘Z | ⌘Z / ⇧⌘Z |

## Habits to unlearn (and their Resolve versions)

- "Nest" ≈ **compound clip** (right-click > New Compound Clip).
- "Adjustment layer" ≈ **adjustment clip** (Effects > Toolbox > Effects >
  Adjustment Clip on the Edit page).
- "Render in to out" for smooth playback ≈ **render cache** (Playback >
  Render Cache > Smart) or **proxies**.
- "Replace with After Effects composition" ≈ open the clip on the **Fusion**
  page.
- Premiere projects (.prproj) can't be opened by Resolve directly: export an
  XML from Premiere (File > Export > Final Cut Pro XML) and import it into
  Resolve (File > Import > Timeline). Effects and some transitions won't carry
  over; cuts, clips and basic transforms do.

## Rows to double-check

The Premiere column has the most version-to-version drift in: clear in/out,
ripple delete on Mac keyboards, and nudge keys. When the user says a key
"doesn't work", look it up in their app's keyboard settings rather than
insisting.
