#!/usr/bin/env python3
"""Steps 1-3 of aroll-draft in one command: probe the take, get its word-level
transcript (made once, kept next to the video), extract the analysis audio and
split the transcript into editor chunks.

Usage:
  python3 prepare.py <video> [--work DIR] [--engine E] [--language L] [--words-per-chunk 1100]

Work folder (every intermediate goes here):
  inside a project -> <project>/<work layout>/aroll-draft/<stem>/
  otherwise        -> <video folder>/<stem>_aroll_draft/

The transcript comes from tools/transcribe.py, which reuses
<video folder>/<stem>.transcript.json when it exists (transcription is the slow,
sometimes paid step: it is done once per file).

Prints JSON: work, source, transcript, wav, fps, duration_s, language, num_chunks.

Exit codes: 0 ok, 2 input problem (no video or audio stream, missing file),
4 no transcription engine is set (ask the user, `settings.py set
transcription.engine <name>`, re-run); 1, 5, 6 are passed through from
tools/transcribe.py (engine failed, engine cannot run here, no speech).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
from vidkit import media, settings  # noqa: E402

HERE = Path(__file__).resolve().parent


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def work_dir(source: Path) -> Path:
    try:
        proj = settings.find_project_root(source)
    except Exception:
        proj = None
    if proj:
        return proj / settings.layout("work") / "aroll-draft" / source.stem
    return source.parent / f"{source.stem}_aroll_draft"


def has_words(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return any(w.get("word", "").strip() for s in doc.get("segments", []) for w in s.get("words") or [])
    except (OSError, ValueError, AttributeError):
        return False


def ensure_transcript(source: Path, engine: str | None, language: str | None) -> Path:
    sidecar = source.with_name(source.stem + ".transcript.json")
    tool = REPO / "tools" / "transcribe.py"
    if not tool.exists():
        if has_words(sidecar):
            print(f"note: {tool} not found; using the existing {sidecar}", file=sys.stderr)
            return sidecar
        die(f"no transcription tool at {tool} and no transcript at {sidecar}")
    cmd = [sys.executable, str(tool), str(source)]
    if engine:
        cmd += ["--engine", engine]
    if language:
        cmd += ["--language", language]
    print("transcribing (reuses the transcript if it already exists)...", file=sys.stderr)
    r = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    if r.returncode != 0:
        # transcribe.py already explained why on stderr: 4 = no engine set (ask the user),
        # 5 = the engine cannot run here, 6 = no speech found, 1 = the engine failed
        sys.exit(r.returncode)
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    path = Path(lines[-1]) if lines else sidecar
    if not has_words(path):
        die(f"the transcript {path} holds no words (no speech in the take?)")
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--work", help="work folder (default: see above)")
    p.add_argument("--engine", help="transcription engine (default: settings transcription.engine)")
    p.add_argument("--language", help="spoken language code, e.g. en, es, de (default: auto)")
    p.add_argument("--words-per-chunk", type=int, default=1100)
    args = p.parse_args()

    source = Path(args.video).expanduser().absolute()
    if not source.exists():
        die(f"not found: {source}")
    info = media.probe(source)
    if not info["has_video"]:
        die("this file has no video stream; aroll-draft cuts videos (the exports and preview need video)")
    if not info["has_audio"]:
        die("this file has no audio stream: there is no speech to cut on")

    work = Path(args.work).expanduser().absolute() if args.work else work_dir(source)
    work.mkdir(parents=True, exist_ok=True)

    sidecar = ensure_transcript(source, args.engine, args.language)
    transcript = work / "transcript.json"
    shutil.copyfile(sidecar, transcript)

    wav = work / "audio_16k.wav"
    if not wav.exists() or wav.stat().st_mtime < source.stat().st_mtime or wav.stat().st_size < 1000:
        print("extracting 16 kHz mono analysis audio...", file=sys.stderr)
        tmp = wav.with_suffix(".tmp.wav")
        r = media.run([media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                       "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)])
        if r.returncode != 0:
            die("ffmpeg could not extract the audio")
        os.replace(tmp, wav)

    plan = subprocess.run([sys.executable, str(HERE / "chunks.py"), "plan", str(transcript), str(work / "edit"),
                           "--words-per-chunk", str(args.words_per_chunk)], stdout=subprocess.PIPE, text=True)
    if plan.returncode != 0:
        die("chunk planning failed")
    plan_info = json.loads(plan.stdout)

    with open(transcript, encoding="utf-8") as f:
        doc = json.load(f)
    out = {"work": str(work), "source": str(source), "transcript": str(transcript),
           "sidecar": str(sidecar), "wav": str(wav), "fps": info["fps"],
           "duration_s": round(info["duration"] or 0, 2),
           "language": doc.get("language") or doc.get("detected_language"),
           "num_chunks": plan_info["num_chunks"], "chunks": plan_info["chunks"]}
    with open(work / "prepare.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
