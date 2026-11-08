# Salvage brief: {{PROJECT}}

The edit of this project is finished. The library already has what the edit
used. Your job: find the good b-roll that was shot but never used, so a future
video can reuse it. This may be the last look anyone takes at this footage.

## What this project is about

<!-- Claude fills this in before spawning the pickers: what the video was about,
the main subjects/products and how to tell them apart on camera (shape, colour,
logo, packaging), and anything the user asked to keep or skip. Delete this
comment. -->

## Your files

Each file in your batch has an `info.json`:
- `file` - the camera original (absolute path), `duration`, `fps`
- `aroll` - true when the file is a talking-head take or an angle of one. Keep
  only clear visual moments from it (a held product shot, a decisive action),
  never the presenter talking or explaining with their hands.
- `used_ranges` - seconds the edit or the library already took. Never overlap
  them (stay 0.5 s clear). A different shot right next to one is fine.
- `free_ranges` - the unused seconds. Every pick must sit inside one.
- `sheets` - contact sheets of the free stretches: a 4-wide grid in reading
  order, each tile's time in `tile_times` (seconds into the file; the time is
  usually also printed in the tile's corner).

## Keep

- The subject clearly shown: hero shots, slow camera moves (slide, arc, push-in),
  detail close-ups, the decisive moment of an action (not the whole fiddle),
  size comparisons, screens that are readable.
- Use in a real setting when the subject is clearly the point.
- A person in frame is fine when they are silently using the subject and it is
  what the shot is about.
- High-frame-rate files (fps 50 and up) are slow-motion material: smooth moves
  are the prize, and 2-5 s of source is plenty.

## Skip

- Talking to the camera; shots where a face is the subject.
- Junk: out of focus or focus hunting, motion smear, exposure changing, dark or
  empty frames, the subject out of frame, camera / light / tripod adjustments,
  hands reaching in, dead stretches.
- Near-duplicates: when a move was shot several times, keep the best take only.
- Privacy: readable personal messages, emails, notifications, addresses, or a
  bystander's face as the main content. Skip or pick around it and say so in
  `privacy_note`.

## Length and budget

- 2-12 s of source per pick (1.5-6 s for high-frame-rate files). Start once a
  move has settled or the action begins; end before a hand leaves half-way, the
  camera jolts or focus hunts.
- Be selective: as a guide, at most about a third of a file's unused time, much
  less for long single takes. Never leave a distinct good shot behind.

## Pin the in and out points

Check each boundary with single frames (one ffmpeg at a time):

    ffmpeg -v error -ss <seconds> -i "<file>" -frames:v 1 -vf scale=640:-2 -y "{{WORK}}/frames/x_<seconds>.jpg"

## Picks file (write it after EVERY file, so a stopped run loses little)

```json
{
  "batch": "b1",
  "picks": [
    {"file": "<file from info.json>", "source_in": 12.4, "source_out": 18.9,
     "description": "One or two specific sentences: framing, subject, action, setting.",
     "tags": ["close-up", "hands", "desk", "slow-motion"],
     "quality": "good", "privacy_note": ""}
  ],
  "files": [
    {"file": "<file>", "picks": 1, "verdict": "one line: what you kept, what you left and why"}
  ]
}
```

- `quality`: `good` (drop straight onto a timeline) or `usable` (only when the
  moment is unique).
- `tags`: 5-10 lowercase words or hyphenated words.
- Every file in the batch gets a `files` entry, also when you picked nothing.
