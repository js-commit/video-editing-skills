# Two cameras, rebuilds, and the seam gate (DaVinci Resolve Studio)

Everything here drives Resolve through its scripting API, so it needs
DaVinci Resolve Studio running with Preferences > System > General > External
scripting using = Local. Ask the user to open Resolve and the project; never
launch or quit it yourself.

## Multicam variant: two or more cameras, one take, same audio

Run the normal pipeline on ONE camera, then build a synced timeline.

1. **Pick the cut source.** If one camera already has a transcript sidecar,
   use it (transcribe once). Otherwise use the camera with the better mic:
   cleaner audio helps the waveform snap. Call it the cut camera.
2. **Measure the offset from the audio**, never from camera clocks or file
   dates (they drift and lie):
   `python3 S/sync_offset.py <cameraA> <cameraB>` (videos or 16 kHz wavs; needs
   numpy). `offset_s` = how much later camera B started than camera A;
   `peak_to_rms` in the hundreds means a confident match, under ~20 distrust it.
   Camera A is the one that should sit on V1 (usually the face camera).
3. **If the cut was made on camera B**, shift it onto camera A's clock:
   `python3 S/translate_cuts.py <B>.aroll.tb.json <A>.aroll.tb.json <offset_s> <cameraA_duration_s>`.
4. **Build**: write a job JSON (format in `resolve_timeline.py --help`:
   project, timeline, never_touch, cuts_json, cameras with offset_s / name /
   enabled / audio_muted) next to the work folder and run
   `python3 S/resolve_timeline.py multicam job.json --report WORK/report.json`.
   Camera N's video lands on V N and its audio on A N, cut identically.
   Camera B's video is disabled per clip when `"enabled": false`, so the
   timeline plays as camera A; switching a segment's angle = enabling the clip
   above it, or select V1+V2 and use Convert to Multicam in the UI later.
5. **Keep every camera's audio.** Different cameras carry different mics;
   dropping one can lose the good mic. Mute (`audio_muted`) every camera except
   the one with the best mic (ask the user which; it is often not camera A).
6. **Camera B geometry.** A camera filming from above or opposite the speaker
   may be upside down relative to them: set `"secondary_rotate180": true` in
   the job, and rotate/zoom the whole V2 track once with the multicam-angles
   skill's `resolve_angle.py transform angle_job.json 2 props.json` after the
   build (props.json e.g. `{"RotationAngle": 180.0, "ZoomX": 1.15, "ZoomY": 1.15}`). Check one
   rotated frame first (extract it with ffmpeg) to choose the zoom.
7. **Hand-off.** The build writes `angle_job.json` next to the job. The user
   reviews and edits the timeline first; picking which camera plays where is
   the multicam-angles skill, run after that review, never before.

Verify after a build: per-track item counts are equal (audio included), the
summary shows no skipped segments other than "not rolling yet" at the very
start, and the first V1/V2 clips' source offsets differ by offset_s.

## Rebuilding a cut from a sequence (second-pass edits)

When a review changes many cuts at once (silences trimmed, stumbles restored,
pickup takes inserted), do not chain dozens of ripple edits. Write the whole
timeline as an ordered list of source slices and rebuild it in one call:
`python3 S/resolve_sequence.py job.json [report.json]`
(job: project, timeline, never_touch, fps, track_name, sequence[{media,
src_in_s, src_out_s, txt, marker?}]). Then run the seam audit (below), fold
its plan into the job with
`python3 S/seam_plan_apply.py job.json seam_audit.json job2.json`, and rebuild
from `job2.json`. Two rounds normally take a timeline to zero hard seams.

Place hand-picked boundaries from an ffmpeg silence map
(`ffmpeg -i take.mp4 -af silencedetect=noise=-36dB:d=0.12 -f null -`) rather
than from word timestamps: on fast speech, transcripts glue words together and
can drift by seconds. If a stretch drifts, re-transcribe it in 10-30 s pieces
whose edges sit in silence (words in a piece's last 2-3 s are the least
reliable).

## Seam and flicker gate on a built timeline

After a Resolve build, and again after every later pass that touches the
timeline (angles, b-roll, inserts):

```
python3 REPO/.claude/skills/broll-brick-layer/scripts/seam_audit.py --project P --timeline T \
    --audio-track <the heard A track> [--transcript <sidecar> --transcript-offset <s>] -o WORK/seam_audit.json
python3 REPO/.claude/skills/broll-brick-layer/scripts/flicker_audit.py --project P --timeline T
```

Both must report 0 (no hard seams, no visible run under 0.6 s). Fix rather than
accept a baseline: `seam_audit.py ... --plan plan.json` then
`ripple_extend.py --project P --timeline T --plan plan.json --snap-top-track`
restores the removed pauses and fillers and snaps b-roll onto the new cuts in
one ripple. "No new findings" is not a pass: old ones still play.
