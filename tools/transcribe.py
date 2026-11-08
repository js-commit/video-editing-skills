#!/usr/bin/env python3
"""Word-level transcript for a video or audio file, made once and reused.

    python3 tools/transcribe.py <media> [--engine E] [--language L] [--force]
    python3 tools/transcribe.py <media> --import other-transcript.json
    python3 tools/transcribe.py --check

Creates (or reuses) <media-dir>/<stem>.transcript.json and prints its absolute
path on stdout, one line. Progress goes to stderr. A valid transcript is
returned instantly; one whose media file changed is moved aside (never
deleted) and redone. If the media folder is read-only, the transcript goes to
the cache folder instead (the printed path says where).

Engines (--engine, default: settings transcription.engine):
  elevenlabs  ElevenLabs Scribe (cloud; account with a free tier, then per minute):
              best, keeps um/uh, precise word times - the engine for cutting
  voz         offline on an Apple silicon Mac (macOS 26+): free, seconds per take,
              keeps fewer um/uh - the engine for sorting footage and home videos
  auto        the configured engine
A voz transcript is reused for voz requests; an elevenlabs request moves it
aside and transcribes again (cutting needs the fillers). See docs/transcription.md.

--import FILE turns an existing transcript into the sidecar without
transcribing: ElevenLabs API JSON, voz-engine JSON, or segments-with-words
JSON (e.g. a <stem>_transcription.json saved by another app).

--check prints, as JSON, which engines can run here, why not, and a
recommendation. It makes no network calls.

Exit codes: 0 ok · 1 transcription failed · 2 usage / bad input ·
4 no engine configured (ask the user, then `settings.py set transcription.engine <name>`) ·
5 the engine cannot run here · 6 no speech found (nothing written).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vidkit import engines, settings  # noqa: E402
from vidkit import transcript as tr  # noqa: E402


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def explain_choice() -> None:
    """Exit-4 message: what can run here and what each choice costs."""
    info = engines.check()
    log("No transcription engine is set. What this computer can use:")
    for row in info["engines"]:
        mark = "ready" if row["available"] else f"not available ({row['why_not']})"
        log(f"  - {row['engine']}: {mark}\n      {row['where']}; {row['cost']}; {row['quality']}")
    if info["recommendation"]:
        log(f"Suggestion: {info['recommendation']} ({info['recommendation_reason']})")
    else:
        log(info["recommendation_reason"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                epilog=__doc__.split("\n\n", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("media", nargs="?", help="video or audio file")
    p.add_argument("--engine", choices=["auto"] + engines.ENGINE_ORDER, default=None,
                   help="speech-to-text engine (default: settings transcription.engine)")
    p.add_argument("--language", default=None,
                   help="spoken language code, e.g. en, es (default: settings, else auto-detect)")
    p.add_argument("--force", action="store_true",
                   help="transcribe again even if a valid transcript exists (the old one is moved aside)")
    p.add_argument("--check", action="store_true", help="print which engines can run here (JSON)")
    p.add_argument("--import", dest="import_file", metavar="FILE",
                   help="build the transcript from an existing transcript file instead")
    a = p.parse_args(argv)

    if a.check:
        print(json.dumps(engines.check(), indent=2))
        return 0
    if not a.media:
        p.print_usage(sys.stderr)
        log("error: give a media file (or --check)")
        return 2
    media_path = Path(a.media).expanduser()
    if not media_path.is_file():
        log(f"error: media file not found: {media_path}")
        return 2
    if a.import_file and not Path(a.import_file).expanduser().is_file():
        log(f"error: transcript to import not found: {a.import_file}")
        return 2

    try:
        out = tr.ensure_transcript(media_path, engine=a.engine, language=a.language,
                                   force=a.force, import_file=a.import_file, log=log)
    except settings.SettingMissing as e:
        explain_choice()
        settings.exit_missing(e)
    except tr.EngineUnavailable as e:
        log(f"error: {e}\n(run `python3 tools/transcribe.py --check` to see what can run here)")
        return 5
    except tr.NoSpeech as e:
        log(str(e))
        return 6
    except tr.TranscriptionError as e:
        log(f"error: {e}")
        return 1
    except (ValueError, FileNotFoundError) as e:
        log(f"error: {e}")
        return 2
    print(Path(out).resolve() if not Path(out).is_absolute() else out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
