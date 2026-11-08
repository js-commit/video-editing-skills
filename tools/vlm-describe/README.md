# vlm-describe

Describe images and video with a vision model running **on this computer**.
Nothing is uploaded; no frame reaches Claude or any cloud service. It is the
private alternative to the cloud `frame-describer` agents, used by:

- `home-video` in privacy mode `local` (the model describes every clip; Claude
  picks from the text and the survey numbers, never from a frame);
- `footage-triage --local` (the classifier agents get descriptions, not sheets);
- `broll-library describe.py local` (library descriptions and tags).

```sh
python3 tools/vlm-describe/vlm_describe.py --check            # ready? how to install?
python3 tools/vlm-describe/vlm_describe.py clip.mov photo.jpg
python3 tools/vlm-describe/vlm_describe.py ~/footage/ --per both --frames 6
python3 tools/vlm-describe/vlm_describe.py --batch work.json -o results.jsonl
```

## Setup (Apple silicon Mac)

The default backend is **Qwen3.5-9B 4-bit through mlx-vlm**: about 5.6 GB of
weights (downloaded once from Hugging Face, pinned to one revision), ~7 GB of
memory while it runs, 1-2 s per clip on a recent M-series chip. A 16 GB Mac
runs it with other heavy apps closed.

1. Make it its own Python environment and install the packages:
   ```sh
   python3 -m venv ~/.venvs/local-vision
   ~/.venvs/local-vision/bin/python3 -m pip install mlx-vlm pillow
   ```
2. Tell the tools where it is:
   ```sh
   python3 tools/vidkit/settings.py set vision.python ~/.venvs/local-vision/bin/python3
   ```
3. `--check` should now say `"available": true`. The first real run downloads
   the model; after that it works offline.

Windows and Linux: no backend is shipped yet (mlx is Apple-only). Adding one
is a file in `backends/` with `check() / load() / describe()`; see
`backends/__init__.py`. Until then those systems use the cloud agents or the
no-frames modes.

## How it sees video

A video is sampled into stills with ffmpeg (4 frames under 15 s, 6 under 2 min,
12 under 8 min, else 16; `sampling.py`) and the model is shown those. `--per
clip` (default) gives one description of the whole clip; `--per frame` one per
frame; `--per both` gives both. `--frames N` or `--at 0.3,5,12` override the
sampling for a run; a batch entry can set `frames` for itself.

## Output

JSON Lines: one object per input, then `{"_meta": ...}`. A caller can
checkpoint as lines arrive. `--json` buffers one object instead; `-o FILE`
writes there.

```json
{"id": "clip.mov", "kind": "video", "frames": [{"t": 0.3, "text": "..."}], "clip": "...", "seconds": 1.4}
```

## Batch input

`--batch FILE` (or `-`): a JSON list or `{"inputs": [...]}`:

```json
[{"id": "clip-1", "path": "/footage/clip-1.mov", "per": "both"},
 {"id": "sheet-7", "images": [{"path": "/work/sheets/7.jpg"}], "clip_prompt": "..."}]
```

`images` means the caller already has stills (a contact sheet, cropped tiles),
so nothing is extracted. Extra keys on an entry come back untouched, so a
caller keeps its own schema. One bad input is reported as `{"error": ...}` and
does not stop the run.

## One at a time

Pass many inputs to **one** invocation rather than calling it in a loop (one
model load). Only one model is in memory at a time: a second run waits for the
first (`--lock-timeout`, default 600 s) or exits 3 with `--no-wait`. Do not run
it beside a DaVinci Resolve render or a big transcription batch.
