# How stabilize.py works, and why the defaults

## The two passes

1. **Detect** (`vidstabdetect`): for every frame, vid.stab finds contrasty patches and how far each
   moved since the previous frame. It writes them to a motion file (`.trf`). On sources wider than
   `--detect-width` (1920) the detection runs on a scaled copy and the motion file is scaled back up
   to full size before pass 2 (vectors, positions and patch sizes are pixels). This keeps 4K fast;
   measured on a synthetic shaky clip, detecting at half size kept the result (84 % less jitter
   versus 77 % at full size).
2. **Transform** (`vidstabtransform`): the camera path is smoothed with a Gaussian over
   `--smooth-s` seconds each side (`optalgo=gauss`), and each frame is shifted and rotated onto
   the smooth path. The frame is zoomed by the crop budget (`zoom=8`, `optzoom=0`: a fixed zoom,
   never the "optimal" one, which can pick 50-70 % on a wandering handheld shot). Shifts are capped
   at 75 % of what the zoom hides on the short side (`maxshift`) and rotation at what the remaining
   margin allows at the corners (`maxangle`), so no black edge can appear. A light unsharp mask
   offsets the softening of the zoom.

## The shake score

The camera's motion per frame is the median of all patch motions. Shake is that motion minus its
own moving average over 1/6 s, so a pan or a walk (slow, intended movement) does not count, only
the frame-to-frame jitter. The score is the 90th percentile of one-second averages ("the worst
second"), in pixels per frame at 960 px wide, so a clip with one bad stretch still counts as shaky.

- `--min-shake 0.8`: below this a clip is "already smooth". The 0.7-1.0 range is a grey zone;
  people watching on a big screen notice walking bob the score under-reads, which is why `--force`
  exists and why the final judge is a person watching the result move.
- `--min-gain 0.15`: after rendering, the output is measured the same way (divided by the zoom,
  which magnifies whatever motion is left). Less than 15 % improvement = reverted.

## Known limits

- Rolling-shutter wobble, motion blur and parallax (near and far things moving differently) are
  not fixable from pixels with a rigid shift-and-rotate.
- A subject that fills a dark frame, water, fog and night skies fool the estimator: expect
  `untrackable` or `reverted`.
- Moving elements in the frame (crowds, waves, screens) can be read as camera motion. On synthetic
  test patterns with animated parts the stabilized result measured worse and the gate reverted it,
  which is the intended outcome.
- Variable frame rate phone clips keep their timing (`-fps_mode passthrough`), so sound stays in
  sync.
- 120/240 fps clips are measured at their recorded rate: played as slow motion, shake looks slower.
