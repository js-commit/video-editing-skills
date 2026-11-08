# Tuning the cut to the user's taste

The defaults suit a casual talking-head video. When the user states a taste
(or `## aroll-draft` in `user/preferences.md` holds one), map it here. Prompt
taste needs nothing from you: the preference bullets are injected into the
editor and reviser prompts by `chunks.py prompt` / `review.py pack`. Flag taste
has to be passed to `smooth_cuts.py` at step 5; write the flags into the
preference bullet so the next run uses them too, e.g.
"- Tighter seams (smooth_cuts --air-scale 0.7 --silence-thresh 0.45)".

## Common requests

| The user says | Do |
|---|---|
| "tighter", "faster pacing", "less air" | `--air-scale 0.7 --silence-thresh 0.45` |
| "more air between sentences", "it feels rushed" | `--air-scale 1.5` (heard gap ~0.45 s instead of ~0.3 s); add `--min-remove 0.25` to also keep more natural pauses |
| "fewer jump cuts" | `--silence-thresh 0.9 --min-keep 1.5` |
| "keep my tangents / jokes / asides" | preference bullet only (prompt guidance) |
| "cut every um / uh" | preference bullet; note that fillers glued inside a sentence are restored by the smoother on purpose (cutting them clips the next word) |
| "never cut X" / "always cut my intro mic check" | preference bullet |
| "keep the long silent demo parts" | a silence *between* transcript words longer than `--silence-thresh` is cut as dead air; only quiet runs *inside* a kept span are kept and listed. Ask for the demo's times and flip that span to `keep` in the cut list, or re-run step 5 with a larger `--silence-thresh` |
| "the gaps still sound breathy" (a gated or denoised mic) | `--floor-db -60` (or measure: the floor in the smooth_cuts log should sit just under the room tone) |

## smooth_cuts.py knobs

| Flag | Default | Meaning |
|---|---|---|
| `--silence-thresh` | 0.6 s | a gap between kept words this long always becomes a cut |
| `--min-cut-gap` | 0.4 s | a gap holding removed words this long becomes a cut |
| `--min-remove` | 0.15 s | a cut that snaps smaller than this is dropped and the pause kept |
| `--min-keep` | 1.0 s | no clip shorter than this: a sliver absorbs the shorter neighbouring pause (<= `--max-absorb`); boxed-in ones are reported |
| `--max-absorb` | 1.5 s | longest removed span a sliver or a hard seam may restore |
| `--margin-db` | 10 dB | quiet = noise floor + this |
| `--floor-db` | measured | force the noise floor (gated / denoised tracks) |
| `--max-extend` | 1.2 s | how far a boundary may travel to find silence |
| `--air-scale` | 1.0 | scales the pre-roll, tail and seam caps together |
| `--pause-min` | 1.5 s | report quiet runs inside keeps at least this long (0 = off) |
| `--no-motion` | off | skip the per-pause motion score (no video decode) |

What the defaults encode (general lessons, keep them unless the user asks):

- A clip under about a second reads as a flicker (two jump cuts in a blink).
- A cut that lands on speech energy clips a word; restoring a short removed
  span (a stutter coming back) is less audible than the clipped word.
- At every seam keep at most ~0.25 s before the voice starts and ~0.30 s after
  it stops, measured on the voice, not on word times: transcripts often stretch
  a sentence's first word back over the pause before it.
- More than 2.5 s of air, or a long pause inside a keep, is never cut
  automatically: dead air and a silent product shot are indistinguishable to a
  script. They are review points.

`render_draft.py --height N` sets the preview's short side (default settings
`render.draft_height`).
