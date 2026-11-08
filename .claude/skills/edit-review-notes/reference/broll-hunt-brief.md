# Helper brief: one b-roll note per agent

When a round has several b-roll notes, the hunts can run in parallel: one
`broll-hunt` agent per note (a general-purpose agent if that type is not
available), all started in one message. They only
search and look; you check every pick and apply them yourself, one at a time.
Fill the `<>` parts, keep it under a page, and add the note-specific block at
the end of each agent's prompt.

```
You find ONE b-roll placement (sometimes two) for one review note on a
video edit. You do NOT edit anything: no DaVinci Resolve, no recipe, no
media files moved or copied. You write one JSON file and stop.

## The video
<one paragraph: what the video is about, the products or subjects shown and
their look-alikes, the frame rate and resolution>
Word-level transcript of the draft (seconds on the draft's clock): <path>
Clip under each note and existing b-roll: <path to notes_map.json>, cuts.json: <path>

## Your note
Note <n>, verbatim: "<text>"
The words it is about: <first word … last word>, <start>-<end> s
Slot: free from <a> s to <b> s (end on the cut at <b> if you can)
Replace the existing shot <name>? <yes/no>

## Where to look, in order
1. The project's own footage: <folder>
2. The b-roll library: python3 <REPO>/.claude/skills/broll-library/scripts/search.py "<words>" --limit 10 --json
3. Sibling projects: <projects folder> (their footage folders)

## Rules
- Look before you claim: extract frames of every candidate range
  (ffmpeg -ss <t> -i <file> -frames:v 1 <out>.jpg, a few per range) and read
  them. Cite the frame times you looked at.
- The shot must show what the words say: same product, same device, same
  action. A wrong shot is worse than none: if nothing fits, return an empty
  list and say where you looked.
- 1.5 s minimum on screen, usually 3-8 s. Start on a word start; prefer
  ending on the slot's cut. Never start or end inside a fast camera move.
- ffprobe each candidate: a high-frame-rate file (50/60/120 fps) plays as
  slow motion on a 24/25/30 fps timeline, so its source range is shorter
  than the slot. Check rotation from the frames, not folder names.
- Don't cover a moment where the person shows something to the camera.

## Output
Write <work>/picks/pick_<n>.json:
{"note": <n>, "placements": [{"media": "/abs/path", "use_src_start_s": 0.0,
  "use_src_end_s": 0.0, "record_s": 0.0, "why": "what the frames show and the
  words it covers"}], "looked_at": ["…"], "doubts": "…"}
and reply with two lines: the pick (or "none") and your main doubt.
```

When the picks come back: open the frames of every accepted range yourself
(in, middle, out) next to the words it covers. Doubtful: send the agent the
specific objection and let it revise, at most twice; then take a runner-up
you checked, or leave the gap and report it.
