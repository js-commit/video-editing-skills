# File formats

All times are seconds. `record_s` counts from the timeline START (the same
clock as a full-timeline render and review notes on it). Source times
(`start_s`, `use_src_*`) are seconds into the media file, real time, even
for a clip slowed down (conformed) in Resolve.

## Annotation (one per b-roll clip, `annotations.py put`)

```json
{
  "duration_s": 23.5,
  "brief": "one line: the video's topic the annotator was given",
  "annotator": "agent",
  "segments": [
    {
      "start_s": 0.0,
      "end_s": 9.5,
      "description": "close-up: hands unfold the laptop stand and set the laptop on it on a wooden desk, logo visible",
      "subject": "stand-model-b",
      "device": "laptop",
      "tags": ["setup", "close-up", "desk"],
      "quality": "good",
      "shaky": false,
      "on_screen_text": "",
      "director_note": ""
    }
  ]
}
```

- Segments cover the whole clip, in order, without overlaps; split on a
  change of subject, action or place, and always at the scene cuts from
  `profile_clip.py`. A continuous shot is one segment.
- `description` is what the matcher searches: name the subject with the
  brief's vocabulary, the action, the place and the shot type, one dense
  sentence.
- `subject`: a slug from the brief, `none` or `unsure`. Required when the
  video covers look-alike things. `unsure` beats a guess: a wrong label puts
  the wrong picture over the words, the worst failure there is.
- `device`: what is held or shown (phone, tablet, laptop, none, unsure),
  when it matters to the words.
- `quality`: `good` (use as is), `usable` (flawed but placeable), `poor`
  (blurred, aborted, shaky; avoid).
- `shaky`: motion blur or whip moves, often a clip's first and last seconds.
- `on_screen_text`: readable screen or label text, if any (helps search).
- `"annotator": "human"`: the user labelled this clip. Agents may only fill
  an EMPTY `description`; `put` enforces it.
- `director_note`: the user's placement order ("use when I talk about the
  height adjustment"). Agents never write or edit it.
- Add your own fields freely; the scripts ignore what they do not know.

## Plan (`plan.json`, read by check_plan.py and apply_plan.py)

```json
{
  "project": "Resolve project name",
  "aroll_timeline": "timeline name",
  "track_name": "B-roll bricks",
  "never_touch": ["final v1"],
  "placements": [
    {"id": 1, "media": "/abs/path/clip.mov",
     "use_src_start_s": 3.3, "use_src_end_s": 8.4, "record_s": 20.9,
     "why": "hands set up the stand while they say 'it sets up in seconds'"},
    {"id": 2, "broll_timeline": "broll supply", "broll_track": 1, "file_hint": "clip_0042",
     "use_src_start_s": 12.0, "use_src_end_s": 17.5, "record_s": 41.0,
     "rotation": 180, "zoom": 1.2, "props": {"Tilt": -120.0},
     "why": "..."}
  ]
}
```

- `media`: a file (imported into a "B-roll (brick layer)" bin when needed).
- `broll_timeline` + `file_hint` (a substring of the clip's path or name):
  cut the range out of a supply timeline, so what is used shows as a gap.
  A timeline whose name says b-roll ("broll supply", "B-roll") is supply;
  any other one only when the user agreed and the plan lists it in
  `"supply_timelines": ["old cut"]` (check_plan.py and apply_plan.py refuse
  it otherwise, and always refuse the a-roll timeline itself).
- Optional: `rotation` (degrees, for an upside-down camera mount), `zoom`,
  `props` (any Resolve TimelineItem property), `clip_duration_s`.

## Needs (`needs.json`, read by add_markers.py)

```json
{"project": "P", "timeline": "T",
 "needs": [{"record_s": 88.5, "end_s": 96.0, "note": "what the words are about; what was looked at"}]}
```

## Verifier verdicts (written by broll-verifier)

```json
[{"id": 12, "verdict": "pass", "evidence": "f000031.00-f000036.50 show the arm locking in place while they say 'it locks at any height'"},
 {"id": 15, "verdict": "veto", "evidence": "frames show model A, the words are about model B"},
 {"id": 19, "verdict": "better", "use_src_start_s": 41.0, "use_src_end_s": 47.5, "evidence": "the screen wakes at 42.0"}]
```

## Hunt pick (written by broll-hunt, one per slot)

```json
{"slot": "02:15 height-lock close-up", "words": "verbatim words the brick covers",
 "placements": [{"media": "/abs/path.mov", "use_src_start_s": 4.0, "use_src_end_s": 9.0, "record_s": 135.2,
                 "rotation": 0, "why": "what is seen + the words it covers",
                 "evidence": ["f000004.50.jpg shows ..."], "source": "project | library | other-project | web",
                 "licence": null, "credit": null}],
 "optional_placements": [],
 "notes_for_orchestrator": "fps, rotation, spans avoided, runner-ups, caveats"}
```

`placements` merge straight into `plan.json`. An empty list means nothing
honest was found; say where you looked.
