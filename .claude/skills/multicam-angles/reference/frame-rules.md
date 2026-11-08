# Judging the angle from sampled frames

Used only for the segments the transcript could not settle (marked
`"confidence": "low"` by the angle-selector). Each tile of a contact sheet is
one sample: camera A on the LEFT, camera B on the RIGHT (already rotated
upright). A segment has two or more samples; never judge from one instant.

- **Judge the eyes, not the head.** A face raised mid-sentence with the eyes
  down is reading or working, not talking to the viewer. A only wins when
  the gaze is at camera A's lens.
- **Hands actively on the thing in camera B's view** (pointing, turning,
  pressing, writing, opening) outweigh a raised face: what is being done is
  the focus even during narration -> PiP.
- **Reading or working while narrating -> PiP**, not A. Only truly idle
  ambiguity (nothing happening in B, unclear gaze) defaults to A.
- **Holding the thing UP to camera A** (raised to chest or face height,
  B's pane shows an empty desk) -> **A**: camera A is the product shot.
- **Reveals and payoffs are PiP, never B alone.** Look for visible
  excitement in camera A's pane at the moment the thing first appears.
- **B full frame** only when B's pane carries the whole story for several
  seconds (a detail the viewer must see, a laid-out comparison, a silent
  demo) and A's pane adds nothing (face down, no reaction).
- When samples within one segment disagree, go with the majority and the
  hands-on rule, not with the single best-looking face.
- B's pane looks wrong (blurred, someone's back, an empty frame, camera B
  not rolling yet)? Then -> A, and say so in `why`.

If PiP is not an allowed angle for this job, use B wherever these rules say
PiP. Write one verdict per listed segment, confirmations included.
