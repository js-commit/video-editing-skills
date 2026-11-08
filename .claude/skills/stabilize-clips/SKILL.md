---
name: stabilize-clips
description: Smooth shaky handheld clips with ffmpeg's vid.stab (two passes) inside a small crop budget, measure whether it actually helped, and keep the original when it did not. Works on whole clips, one stretch of a clip, or the shots of a home-video montage marked as shaky. Use when asked to "stabilize this", "this clip is shaky", "smooth out the footage", "which of these clips are shaky?", "deshake", or when a montage note says a shot is shaky.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *), Read
---

# Stabilize clips

Stabilizing (removing camera shake after the fact) works by measuring how the frame moved,
smoothing that path, and shifting each frame back onto the smooth path. Shifting needs spare
picture at the edges, so the shot is zoomed in a little: **the crop is the price**.

```
S=${CLAUDE_SKILL_DIR}/scripts/stabilize.py
python3 $S --check                                   # does this ffmpeg have vid.stab?
python3 $S --analyze clip1.mp4 clip2.mov              # shake score per clip, renders nothing
python3 $S clip.mp4 -o clip_stab.mp4                  # whole clip
python3 $S clip.mp4 -o shot.mp4 --range 12.0 17.5     # one stretch (+0.5 s handles)
```

## Before you start

- Read `user/preferences.md` (`## stabilize-clips` and `## general`); the user's preferences win.
- `--check` first. No vid.stab in this ffmpeg: the script prints which builds have it (macOS:
  Homebrew's `ffmpeg-full`; Windows: a "full" GPL build; Linux: most distro packages). **Ask before
  installing anything.** Meanwhile `--engine deshake` uses ffmpeg's built-in deshake: weaker and
  unmeasured.

## Steps

1. **Triage** with `--analyze`. `already smooth` means leave it: the phone's own stabilization did
   the job and a second pass only costs crop. `untrackable` (water, fog, darkness, a subject
   filling the frame) means leave it too.
2. **Stabilize** the clips the user wants smoothed. Each result line ends `kept` (jitter before ->
   after, zoom), `reverted` (the render did not reduce the jitter by 15 %, so it was deleted and the
   original stands) or `skip`. Every number is in `<out>.stab.json`. `--force` stabilizes a clip
   the score calls smooth (the user saw shake the score missed: slow lurches, walking bob).
3. **Watch it, side by side, in motion.** Stabilization is judged by watching movement, never by
   stills: a still frame cannot show jitter, wobble or a floating horizon. Make a comparison
   (both at the same rate):
   `ffmpeg -i in.mp4 -i out.mp4 -filter_complex "[0:v]fps=30,scale=-2:540[a];[1:v]fps=30,scale=-2:540[b];[a][b]hstack" -an compare.mp4`
   and ask the user to play it (or open it in EditReview). Report per clip: shake before -> after,
   gain, zoom, verdict; call out every revert with its reason.
4. In a home-video montage, mark the shot `"stabilize": true` in `work/picks.json` instead:
   make_draft.py stabilizes just that stretch and swaps it in.

## Tradeoffs (teach these when it matters)

- **Crop vs smoothness.** More smoothing (`--smooth-s`, default 0.5 s each side) needs more spare
  picture. The default budget is 8 % (`--max-zoom`); 12 is a sane ceiling. A big crop loses more of
  the shot than the smoothing gives back: if 8 % is not enough, use a calmer stretch or another clip.
- **Never stack stabilizers.** A clip the phone, the camera or Resolve already stabilized gains
  nothing from a second pass and loses framing.
- **What pixels cannot fix:** rolling-shutter wobble ("jello") and motion blur baked into a frame.
  Locking the position while the wobble stays makes a shot look *warped*. If the user calls a
  result warpy, keep the original and trim to the calmest stretch.
- **Trust the gate.** A revert means the measurements disagree about what the camera did; the
  honest output is the original. `--keep-all` keeps it anyway, for a side-by-side look only.
- In DaVinci Resolve the same tool lives on the Color page (Tracker palette > Stabilizer). Gyro data
  (action cameras that record their motion sensors) is better handled by Gyroflow, a
  separate free app: offer it, never install it unasked.

## Hard rules

- Sources are never touched: outputs go to `-o`, `--out-dir`, or `<clip dir>/stabilized/`.
- Install nothing without the user's yes.

## What the user can customize

Default crop budget, smoothing window, the shake threshold for "already smooth" and the gain gate
(flags above; save lasting choices under `## stabilize-clips` in `user/preferences.md`). How it
works and why the defaults are what they are: `reference/method.md`.
