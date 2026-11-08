---
name: aroll-benchmark
description: Dev harness. Scores the autonomous aroll-draft skill against a hand-made cut of the same take (your own edit from Video Haircut / TimeBolt JSON or a DaVinci Resolve XML export), and records the result to a scoreboard. Use when asked to "benchmark the a-roll draft", "score the auto cut against my edit", or after changing aroll-draft's prompts or snapping to check nothing regressed.
argument-hint: <source-video> [hand-cut json or xml]
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/../aroll-draft/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffprobe *), Bash(ls *), Bash(mkdir *), Bash(mv *), Bash(cp *), Read, Write, Skill, Agent
---

# A-roll benchmark (dev only)

Answers one question: **does the autonomous cut leave boundary artifacts a human edit
wouldn't?** Runs `aroll-draft` fresh on a source whose hand-made cut already exists, scores
both against the same word-level transcript, appends a row to the scoreboard.

Not a pass/fail on matching the hand cut: the two are *expected* to differ. A silence-based
editor pads a fixed margin around speech; the skill snaps to the waveform. Judge artifacts
and defensibility, not frame agreement.

`A=${CLAUDE_SKILL_DIR}/../aroll-draft/scripts`. The scoreboard lives in
`user/benchmarks/` (git-ignored with the rest of `user/`): `results.jsonl` and `RESULTS.md`.

## Steps

1. **Resolve inputs.** `$0` is the source video. `$1`, if given, is the hand cut: a Video
   Haircut / TimeBolt op-list `.json` or a Resolve timeline exported as FCP7 `.xml`.
   Otherwise look next to the source (`<stem>*.json` op lists, `<stem>*.xml`), newest first,
   and **say which file you picked**. Stop and ask if none is found.

2. **Force a fresh cut.** The work folder aroll-draft uses (its `prepare.py` docstring) is
   `<project>/<work>/aroll-draft/<stem>/` when the take is inside a project, else
   `<media-dir>/<stem>_aroll_draft/`. If it exists, move
   everything except `audio_16k.wav` into a sibling `_archive_<stem>_<n>/`, along with any prior
   `<stem>.aroll.*`, `<stem>_fps*.xml|.edl` next to the source, but NEVER the transcript sidecar
   (`<stem>.transcript.json`), which stays next to the source forever. (`audio_16k.wav` survives
   because the scorer needs the lossless wav and it is slow to re-extract from a network source.)

3. **Spawn an `aroll-runner` agent** (Opus, xhigh, `run_in_background: false`) with nothing
   but the source path:

   > Source video: `<abs path>` — run the aroll-draft skill on it.

   **Never run the cut in the main thread.** You have seen the hand cut's path, and in later
   runs its numbers; an editor sharing that context is no longer blind. The runner gets the
   video and nothing else. Keep its reported retry and reviser-round counts: they are
   quality signal.

4. **Score.**

   ```sh
   mkdir -p user/benchmarks
   python3 $A/compare_cutlists.py "<hand cut>" "<media-dir>/<stem>.aroll.tb.json" \
     --transcript "<media-dir>/<stem>.transcript.json" --wav "<work>/audio_16k.wav" \
     --divergence 12 --record user/benchmarks/results.jsonl --label "<project> / <stem>"
   python3 $A/results_table.py user/benchmarks/results.jsonl -o user/benchmarks/RESULTS.md
   ```

5. **Judge, then write it up.** Read the `--divergence` output before forming a verdict: the
   numbers say whether the cut is clean, the divergence says whether it is *right*. Write
   `user/benchmarks/<stem>-<date>.md` covering: pipeline health (chunk retries, reviser
   rounds, dip-fallback share), the results table, agreement both directions, and a
   defensibility section quoting actual divergent lines.

## Running a series

One runner at a time: transcription and the editor agents are the expensive steps, and two
runs on one machine fight for them. Start the next runner only once the previous has
reported. Sources on a NAS work as-is; the audio extraction streams the whole file first, and for a
take outside a project `aroll-draft` writes its work dir next to the source (tens of MB over
the network, fine but slow). A finished project's compressed `<stem>_audio.mp3` is *not* a substitute for
`audio_16k.wav`: lossy audio shifts the measured noise floor the boundary snapper depends on.

## Reading the result

- **Bleeds and clips are the metric.** Target is 0 / 0. A bleed is a fragment of a removed
  word left audible, a clip is a kept word chopped at a boundary. Any non-zero count on the
  skill's side is a real regression: find the boundary and say why it happened.
- **Agreement is context, not a target.** ~90 % against a silence-based hand cut is normal.
  Below ~85 %, read the divergence before calling it bad: the skill removing false starts
  the hand cut kept will *lower* agreement while improving the cut.
- **Boundary energy** median/p90 is diagnostic only. The skill runs a few dB louder at p90
  because it places more boundaries in dense speech, where it falls back to a local minimum
  rather than true silence; fine as long as bleeds and clips stay at zero.
- **Divergence reading.** Sub-0.3 s slivers are just the padding difference. Regions over
  ~1 s are editorial: check whether the skill dropped an abandoned take, a doubled restart or
  a stutter (good), or a real sentence with no surviving retake (bad).

## Notes

- Scoring is apples-to-apples only because both cut lists are measured against **one**
  transcript: always pass the `<stem>.transcript.json` sidecar next to the source.
- `--keep-thresh` (default 0.75) sets where a partly-surviving word stops being "kept but
  clipped" and becomes "dropped but bleeding". Leave it alone unless comparing to a
  historical number.
- Metric definitions: `compare_cutlists.py`'s docstring.
