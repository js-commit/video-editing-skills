# Mapping one take into moments

You turn one long overhead take (an unboxing, a screen-protector or case install) into a
**moments file**: the ordered list of beats worth keeping. `sequence.py` then decides how
much of each beat to keep (the pace) from the sound, and every beat becomes its own library
clip. Laid back to back, in order, the clips play as a paced YouTube-style unboxing.

## What the sequence should be

- Show the box first.
- Then the opening, for its **sound**: the knife on the tape, tearing a seal, taking off the
  shrink wrap, peeling a film, a lid sliding off. It's an ASMR kind of thing, fast paced but
  not too rapid: a balance.
- **Pause on every product.** When a product comes out (the phone, a cable, the case, a
  screen protector), hold it. If the hands turn it side to side, keep that motion for a bit.
- **Cut the dead time:** moving stuff out of the way, an empty frame, nothing happening,
  reaching off screen, fiddling with instructions.
- Make it watchable on its own, like ASMR, with a good steady pace. The pace is already
  chosen (`../paces.json`). You choose WHAT is kept, never how long a beat runs.

## Never keep

- Dead time: the hands moving things aside, an empty or static desk with nothing new on it,
  setup, re-arranging.
- The presenter's head, face or hair in frame (leaning over the overhead camera), and
  talking to the camera.
- Readable private information: account names, addresses, notifications, another device's
  screen showing anything personal. Instruction videos playing on a phone or tablet beside
  the work count as fiddling.
- Blur, focus hunts and camera bumps.

## The moments file

Write it where your task says (normally `<project>/<work>/unboxing/<name>.moments.json`).
A sequence may span several takes: one source letter per take, moments in filmed order.

```json
{
  "schema": "unboxing-cut/moments-1",
  "name": "brand-case-unboxing",
  "product": "Brand Model case for the Phone X",
  "kind": "unboxing",                       // or "install"
  "device": "phone",
  "tags": ["brand-case", "phone-x", "unboxing", "asmr"],
  "sources": {
    "A": {"path": "/abs/path/take_01.MP4", "flip": true}
  },
  "moments": [
    {"src": "A", "a": 2.4, "b": 5.0, "kind": "establish", "section": "box",
     "label": "sealed box on the desk",
     "description": "Locked-off overhead of the sealed white case box on the desk - the unboxing opener."}
  ]
}
```

A source is a path string, or an object with:

- `flip: true`: the rig was mounted upside down. The clips get rotated 180°.
- `transcript`: the take's `<stem>.transcript.json` sidecar.
- `transcript_offset`: this camera's time minus the transcript's time.
- `speech: "mute"`: silence the spoken words and keep the sounds between them.

Your task names any of these that apply.

Moments are in **playback order** (normally the order filmed). Each moment has:

| field | meaning |
|---|---|
| `a`, `b` | source seconds: the stretch the beat may use. |
| `kind` | One of the four kinds below. |
| `hero` | `true` on the one or two moments that ARE the video: the main product revealed, the side-to-side turn. A hero hold may run longer. |
| `section` | A short group name: box, open, reveal, items, product. For an install, its steps: clean, align, apply, squeegee, peel, result. |
| `label` | A few words naming the beat. Unique within the file. |
| `description` | ONE dense sentence for the b-roll library: shot type (overhead / close-up), subject, product by name, action, setting. Write what the frames show, nothing guessed. |
| `max` | Optional cap in seconds that overrides the pace. Use it only for an install step that doesn't read in 2.5 s (laying a film down, one squeegee pass), and say why in your reply. |

The four kinds:

- **`establish`**: a still opener (the sealed box). The script keeps its head. `a` = the first
  clean frame, with no hand in it.
- **`sound`**: an action you watch for its sound. Make `a`..`b` generous around it; the script
  trims to the sound events plus buffers.
- **`action`**: a visual move (lid lifted, product lifted out). The same trim on its sound, or
  its head when it makes none.
- **`hold`**: a product shown or turned. The script keeps from `a` on, so `a` must be the first
  SETTLED frame, with the product in view and no hand leaving.

Two moments from the same take that touch become one clip. That's fine for "lid off"
straight into "the phone in its tray".

## How to work

`S=<repo>/.claude/skills/unboxing-cut/scripts`. Run one ffmpeg-based command at a time,
never in parallel. When your task names a shared lock file (other agents working at the
same time), wrap every ffmpeg-based command in it: `lockf -k <lock file> <command>` on
macOS, `flock <lock file> <command>` on Linux.

1. **Overview.** Sheets of the whole range your task names:
   `python3 $S/overview.py VIDEO --step 3 [--start S --end E] [--flip] -o <scratch>/ov`.
   Read every page in one message. Each tile is the frame at its time label, with that
   tile's seconds of sound under it: grey for the full band, orange for 3-10 kHz, where
   tears and crinkles live.
2. **Detail.** For each stretch with something happening, make 1 s sheets (`--step 1 --start
   --end`). Make 0.25-0.5 s sheets (`--cols 4 --rows 3 --width 320`) for a head or tail that
   matters: a hold's first settled frame, a hand leaving.
3. **Write the moments file.**
4. **Preview:** `python3 $S/sequence.py MOMENTS --pace steady -o <project drafts
   folder>/unboxing/<name>-steady.mp4`. The script prints every beat; check the order and
   lengths.
5. **QC:** `python3 $S/qc_sheet.py <that preview> -o <scratch>/qc` prints each beat's first,
   middle and last frame. READ every page. A beat fails if it opens on a hand leaving or an
   empty frame, ends mid-move in a way that looks broken, is a hold where the product isn't
   in view, shows a face or private screen, or isn't what its label says. Fix the moments
   and re-run 4-5 until every beat passes.
6. **Reply** with these lines:
   - the moments file path;
   - the beat count and total seconds;
   - one line per beat: label and seconds;
   - what you left out and why, in one line each;
   - any `max` overrides.

Don't run `export_clips.py`, don't edit the scripts or `paces.json`. If a script misbehaves,
report it rather than working around it.
