# Audits and repairs

Three read-only audits and three repair tools. The audits are also used by
aroll-draft and multicam-angles on timelines with no bricks yet; their
command lines are a contract, keep them stable.

## flicker_audit.py: what the viewer sees

```
python3 S/flicker_audit.py --project P --timeline T [--min-run-s 0.6] [--aroll-tracks auto|1,2]
        [--track-name "B-roll bricks"] [--render WORK/audit.mp4] [-o WORK/flicker.json]
```

Rebuilds, frame by frame, the top-most enabled clip across every video
track, after merging pieces that continue the same source (an invisible
seam is not a cut). Finding kinds:

| kind | meaning | usual fix |
|---|---|---|
| `visible-micro-run` | a shot (or black) on screen < 0.6 s | depends on the cause below |
| `brick-near-cut` | a brick starts a few frames after, or ends a few frames before, an a-roll cut | `ripple_extend.py --snap-top-track` |
| `short-item` | a clip under 0.6 s on any track (a silence-cut sliver) | seam plan + ripple, or delete it |
| `aroll-gap` | empty frames between a-roll clips | close it in Resolve, or bridge |
| `pixel-flicker` | (`--render`) two picture changes < 0.6 s apart in a real render | find it at the timecode; overlays and effects show up only here |

0.6 s is the line: about 13 frames reads as a flash, 16 does not. The
a-roll tracks are found automatically (tracks covering 80 % of the
timeline); with text or graphics on an extra full-length track, pass
`--aroll-tracks` explicitly. `--render` uses the Deliver page's current
format and adds only its own render job.

Gate: 0 findings, counted fresh after every change. Comparing against an
earlier audit ("no new findings") lets old flashes live forever.

## seam_audit.py: what the viewer hears

```
python3 S/seam_audit.py --project P --timeline T --audio-track 1 [--aroll-track 1]
        [--transcript <stem>.transcript.json --transcript-offset 0.0] [--target-gap 0.30]
        [--plan WORK/seams.json] [-o WORK/seam_audit.json]
```

Measures the loudness envelope of the heard source file at every seam
(two consecutive pieces of the same source with frames removed between
them). `hard` = a word is cut into (boundary loudness well above the noise
floor); `abrupt` = less than 0.1 s of quiet across the seam. `--plan`
writes, per seam, how many frames to restore on each side (`tail_f` after
the outgoing clip, `head_f` before the incoming one) so the boundaries sit
in quiet and the pause reaches `--target-gap`; a one-word sliver shorter
than `--min-keep` gets its shorter neighbouring gap restored. Seams that
cannot be fixed by padding are `flag`ged: usually a broken sentence, a
decision for the user. Pure Python; the 16 kHz WAV is extracted next to
the report on first run.

The report's `items` (`F`, `tail_f`, `head_f`) are also read by
aroll-draft's sequence rebuild, which is cheaper than a ripple when the
timeline has no bricks yet.

## check_plan.py: before anything lands

See its `--help`. Run it after every plan change; it is the cheapest place
to remove flashes.

## Repairs

`ripple_extend.py` (the API has no trim or insert, so it rebuilds the tail):

```
python3 S/ripple_extend.py --project P --timeline T --plan WORK/seams.json [--snap-top-track] [--dry-run]
python3 S/ripple_extend.py --project P --timeline T --bridge <frame> [--bridge <frame> ...]
python3 S/ripple_extend.py --project P --timeline T --snap-top-track
```

- Always `--dry-run` first and read the summary (items moved, markers moved).
- It refuses (before changing anything) when the rippled range holds a
  title, generator, solid or adjustment clip: scripts cannot re-create
  those. Move them out of the way first.
- It writes `restore_*.json` (every item and marker it deleted) before
  deleting, plus the automatic `.drp` backup.
- After any ripple, compare `inventory.py --compare <before>`: a brick that
  got shorter does not show up in the flicker audit.

`close_gaps.py --project P --timeline T` closes gaps under 1.1 s between
bricks by extending a neighbour (never the a-roll).

`add_markers.py --needs WORK/needs.json --clear-first` refreshes the red
NEED BROLL markers; spans the user has since covered by hand stay quiet.

## Frame math worth knowing (for anyone editing these scripts)

- `recordFrame` is absolute: read `GetStartFrame()` from the live timeline
  (many start at 01:00:00:00 = frame 86400 at 24 fps).
- `AppendToTimeline` start/end frames are in the CLIP's own frame rate;
  item lengths and `GetLeftOffset()` are timeline frames. Scale, read the
  placed length back, nudge (`ripple_extend.append_snapshot` does this).
- An append only fills free frames; a still is clipped by whatever follows
  it and otherwise gets the default still length.
- `DeleteClips` only works while the Edit page is showing
  (`vidkit.resolve.delete_clips_checked` switches and switches back).
- The save is the verification boundary: re-read the track after
  `SaveProject()`, an errored append can vanish on save.
