# Scoring a draft against a hand edit

Use when the user wants to know how the automatic cut compares with their own
edit of the same take (or a Video Haircut / TimeBolt cut, or an earlier draft).

```
python3 S/compare_cutlists.py <benchmark> <candidate> \
    --transcript <video folder>/<stem>.transcript.json --wav WORK/audio_16k.wav --divergence 12
```

- `<benchmark>`: their cut. A TimeBolt / Video Haircut `.json` op list, or a
  Resolve timeline exported as FCP7 XML (File > Export > Timeline..., format
  "FCP 7 XML"). Only clips of the take on video track 1 count; pass
  `--source <file name>` if several takes share the track.
- `<candidate>`: `<stem>.aroll.tb.json`.
- `--media <video>` instead of `--wav` extracts the audio itself.

Reading it:

- **bleeds / clipped** are the objective part: a fragment of a removed word left
  audible, or a kept word chopped at a cut. Aim for 0 / 0. One caveat: a kept
  word whose transcript time is stretched over a pause (common at sentence
  ends) counts as a "bleed" when the seam trim removes the silent stretch;
  check such hits with `--detail` before calling them defects.
- **agreement** is context. Two good editors disagree; around 90 % is normal.
  Under ~85 %, read the divergence before judging.
- **divergence** lists the biggest stretches only one side kept, with their
  words. Sub-0.3 s differences are padding. Longer ones are editorial: an
  abandoned take or doubled restart the draft removed is good; a real sentence
  lost with no surviving retake is bad (tell the user, and consider a
  preference bullet).
- **energy** (dBFS at each cut) is diagnostic: quieter is cleaner.

`--record results.jsonl --label "<name>"` appends a one-line summary, handy
for tracking how preference changes move the numbers over several videos.
