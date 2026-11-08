# aroll-draft file formats

Every intermediate and output, in pipeline order. Times are seconds (float)
unless stated otherwise. Load this when debugging a stage.

## Work folder

Inside a project: `<project>/<work layout>/aroll-draft/<stem>/`; otherwise
`<video folder>/<stem>_aroll_draft/`. `prepare.json` records the paths.

## transcript.json

A copy of the sidecar `<video folder>/<stem>.transcript.json` made by
`tools/transcribe.py` (segments with words):

```json
{"segments": [{"start": 8.73, "end": 12.84, "text": "So here it is.",
               "words": [{"start": 8.73, "end": 8.93, "word": "So"}]}],
 "language": "en",
 "_meta": {"schema": "transcript-sidecar/1", "engine": "...", "source_name": "...", ...}}
```

Segment `text` is ignored: chunk strings are rebuilt from `words` joined by
single spaces, so whitespace-split tokens map 1:1 onto word times.

## Edit chunks (WORK/edit/)

- `plan.json`: `{transcript, num_segments, num_chunks, chunks: [{index, seg_start, seg_end, words}]}`;
  ~1100 words per chunk, boundaries nudged to sentence ends.
- `chunk_NN.json`: JSON array of segment strings.
- `chunk_NN.prompt.md`: `reference/edit-prompt.md` with its slots filled:
  `{{PREFERENCES}}` (the `## aroll-draft` bullets of user/preferences.md),
  `{{LANGUAGE}}` (non-English speech only), `{{CONTEXT}}` (the last 8 edited
  segments of chunk N-1), `{{TRANSCRIPTION}}` (this chunk).
- `chunk_NN.edited.json`: the editor's answer, the same array with cut words
  wrapped `~like~ ~this~` (punctuation inside the tildes). The validator
  repairs code fences and `~word~.`, then enforces: same segment count, same
  word count per segment, every token identical once tildes are stripped.
  Exit 3 = feed its stderr back to the editor.

## revision.json

The transcript with `"cut": true|false` on every word: exactly Video
Haircut's `*_user_revision.json` format, so it can be opened there for manual
touch-ups. Delivered as `<stem>.aroll.revision.json`.

## review_R.md / corrections_R.json

Pack: optional preference/language header, then one line per segment:
`[012] (  45.10-  51.80) kept words ~cut words~`.
Corrections: `[{"segment": 12, "match": "exact words", "action": "cut"|"keep"}]`;
`match` is a case-insensitive contiguous word sequence of that segment (tildes
ignored). Ambiguous or missing matches are skipped and listed (exit 3).

## Cut list: <stem>.aroll.tb.json (TimeBolt / Video Haircut format)

Ordered, contiguous, gapless ops from 0 to the last keep's end:

```json
[{"start": 0.0, "duration": 8.61, "type": "original", "punched": 1,
  "punchedPosition": "center", "operation": "remove", "id": 0},
 {"start": 8.61, "duration": 7.4, "type": "original", "punched": 1,
  "punchedPosition": "center", "operation": "keep", "id": 1, "txt": "So here it is..."}]
```

6-decimal rounding; `type` / `punched` / `punchedPosition` are TimeBolt
constants. Other skills (talking-head-ffmpeg, multicam-angles, shorts) read
this file: keep the format.

`<cuts>.decisions.json`: noise floor, quiet threshold, every boundary (word
time vs snapped time and why: `onset-silence` / `tail-decay` = clean,
`min-dip` = no silence, cut at the quietest point, `no-room` = pinned by
neighbouring cut speech), `hard_seams`, `slivers`, `tightened` seam edges,
`long_pauses` (with `motion_x_speech`), `word_crossings`.

## retake_flags.json

`{sidecar, min_word_s, flags: [{word, start_s, end_s, duration_s, segment,
kept, output_s, tail_audio_s, suspect}], caveat}`. `suspect` + `kept` = audition.

## Timelines (export_timeline.py)

- `<stem>.aroll.xml`: XMEML (FCP7 XML v4), one video and two audio tracks,
  clips linked, sequence named "<stem> first cut". Source in/out =
  `floor(t * native fps)` frames from the media's first frame; record placement
  spreads rounding Bresenham-style; `<timebase>` is the standard rate (24 for
  23.976) with `<ntsc>TRUE</ntsc>`. The file's embedded start timecode is
  written to the file block.
- `<stem>.aroll.edl`: CMX3600, non-drop, three events per clip (V, AA, NONE +
  `AUD 3 4`); source timecodes include the file's start timecode (Resolve
  matches EDL events to media by timecode).

## report.md / report.json (deliver.py)

Summary (raw and cut length, clips, words cut, outputs) and the review points
`{kind, source, first_cut, source_s, first_cut_s, note}`; `resolve_timeline.py
--report` turns them into timeline markers.

## Preview (render_draft.py)

Per keep: `trim`/`atrim` + `setpts`, 15 ms audio fades, `concat`, scale so the
short side is the draft height, vidkit's H.264 encoder (VideoToolbox / NVENC /
libx264), AAC 192k, `+faststart`. Output duration checked against the cut list.
Written to `settings.drafts_dir(video)` as `<stem>.aroll_draft.mp4`.
