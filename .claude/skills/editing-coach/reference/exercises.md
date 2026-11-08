# Practice exercises

Each one takes 10-30 minutes with the user's own footage (or any clip). Give
the goal, the steps, and what "good" looks like; offer feedback afterwards
(contact sheet + loudness check).

## Beginner

**1. The clean cut** (Edit page)
- Goal: remove every um and retake from 2 minutes of talking.
- Steps: J/K/L to play, ⌘B to cut, ⇧⌫ to ripple delete; ↑/↓ to jump
  between cuts to check each one.
- Good: no clicks or chopped words at cuts, a small breath between
  sentences, nothing important lost. Compare with an aroll-draft first cut.

**2. Keyboard only**
- Goal: edit one minute without touching the mouse for playback and cuts.
- Steps: Space, J/K/L, ←/→ frames, I/O, ⌘B, ⇧⌫, ⌘⇧[ and ⌘⇧].
- Good: it gets faster by the end. Note which keys you'd remap.

**3. Punch-ins**
- Goal: make jump cuts feel intentional.
- Steps: after a jump cut, select the next clip, Inspector > Transform >
  Zoom 1.15-1.25, reposition so the eyes stay about a third from the top.
- Good: alternating framing, never the same size twice in a row at a cut.

**4. Loudness**
- Goal: a finished mix at about -14 LUFS with peaks under -1 dBTP.
- Steps: normalize the dialogue, set music 15-25 dB under the voice, render,
  measure with loudness.py.
- Good: within 1 dB of the target; voice clear on phone speakers.

## Intermediate

**5. J- and L-cuts**
- Goal: three b-roll transitions where sound leads or trails the picture.
- Steps: unlink or ⌥-click to select only the audio or video part of a clip
  (or toggle linked selection ⌘⇧L), then trim the audio and video edges
  separately in Trim mode (T).
- Good: the cut is felt, not heard.

**6. B-roll on the word**
- Goal: cover 60 seconds of talking with b-roll that starts on the word it
  shows.
- Steps: markers (M) on the key words while listening, then lay clips on V2
  starting at each marker.
- Good: every shot illustrates the sentence under it; no shot shorter than
  about a second.

**7. The 30-second hook**
- Goal: re-edit the first 30 seconds of a finished video so it opens with the
  payoff.
- Good: someone who sees only those 30 seconds knows what they'll get and
  wants it.

**8. Primary correction**
- Goal: correct three shots so they match.
- Steps: scopes on, waveform for exposure, parade for white balance,
  vectorscope skin line, grab a still (⌥⌘G) and wipe-compare.
- Good: you can't tell where the shots change from the color.

## Stop motion

**9. The bouncing ball** (the classic first animation)
- Goal: 2 seconds of a ball bouncing, shot on twos (24 photos, 12 per second).
- Steps: lock camera and exposure, small moves near the top of the bounce,
  bigger near the floor, assemble with the ffmpeg command in stop-motion.md.
- Good: no flicker, the ball slows at the top and speeds into the floor.

## Advanced

**10. Pacing pass**
- Goal: shorten a finished 10-minute edit by 15% without losing content.
- Steps: watch at 1x, mark slow spots; tighten pauses, cut repeated points,
  merge intros.
- Good: a viewer test (someone else watching) shows no confusion.

**11. Custom keyboard preset**
- Goal: a saved Resolve preset with your 5-10 most-used commands on the keys
  you like.
- Steps: Keyboard Customization (⌥⌘K), search the command, assign, save as
  a new preset, export it as a backup.
