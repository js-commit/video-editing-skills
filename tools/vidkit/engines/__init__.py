"""Speech-to-text engines behind tools/transcribe.py. Every engine returns the
same raw shape, {"words": [{"start", "end", "word"}], "language", "model"},
and vidkit.transcript turns that into the sidecar, so nothing downstream
cares which engine ran.

Two engines, chosen for word-level timing that holds up when a cut lands on
a word:
  elevenlabs  ElevenLabs Scribe through their API. Keeps nearly every "um"
              and "uh" and times words precisely: the engine for anything
              that cuts or shows words. Needs an ElevenLabs account (there is
              a free tier; beyond it, billed per minute).
  voz         Desert Ant Labs' Voz + Align on an Apple silicon Mac (macOS
              26+): offline, free, seconds per take. Keeps fewer fillers, so
              it is the engine for sorting footage, home videos and b-roll
              context, and the fallback for cutting when audio must not leave
              the computer.

Whisper-family models are deliberately not offered: they tend to invent text
on noise and drop fillers, which breaks word-precise cutting.

Adding an engine: a module with NAME, KIND ("cloud"/"local"), available() ->
(bool, reason) and transcribe(src, workdir, language, duration, log) -> raw
dict; then list it in ENGINE_ORDER and TRADEOFFS.
"""
from __future__ import annotations

import json
from pathlib import Path

from vidkit import media, settings

ENGINE_ORDER = ["elevenlabs", "voz"]

# Engines whose transcripts are fine for sorting and context but less so for
# cutting or on-screen text. When a cutting-grade engine is asked for explicitly
# (--engine elevenlabs), an offline sidecar is moved aside and the file is
# transcribed again instead of reusing it.
OFFLINE_ENGINES = ("voz",)

TRADEOFFS = {
    "elevenlabs": {
        "where": "cloud (the audio is uploaded to ElevenLabs)",
        "cost": "ElevenLabs account: free tier, then billed per minute of audio",
        "quality": "best: keeps nearly every um/uh, precise word times (the engine for cutting)",
        "speed": "fast (much faster than real time, plus the upload)",
        "setup": "an ElevenLabs API key in the ELEVENLABS_API_KEY environment variable",
    },
    "voz": {
        "where": "this Mac (the audio stays local)",
        "cost": "free",
        "quality": "good words, sharp word times; keeps about half the fillers, so a-roll cuts need a little more hand-trimming",
        "speed": "very fast on Apple silicon (a 16-minute take in a few seconds)",
        "setup": "Apple silicon Mac with macOS 26 or newer; the model (about 470 MB) downloads on first use",
    },
}


def get(name: str):
    if name == "elevenlabs":
        from vidkit.engines import elevenlabs
        return elevenlabs
    if name == "voz":
        from vidkit.engines import voz
        return voz
    raise ValueError(f"unknown engine '{name}'; choose one of {', '.join(ENGINE_ORDER)}")


def recommend(avail: dict) -> tuple:
    """(engine or None, one-line reason) from {name: available?}."""
    if avail.get("elevenlabs"):
        return "elevenlabs", ("an ElevenLabs key is set: best filler and word-time accuracy, which "
                              "is what aroll-draft cuts on (free tier, then per minute; audio leaves the computer)")
    if avail.get("voz"):
        return "voz", ("voz is ready: free, offline and fast; it keeps fewer um/uh than ElevenLabs, so "
                       "aroll-draft's cuts need a little more hand-trimming. Add an ElevenLabs key later "
                       "and make it the default (or ask for it per take) for cutting-grade transcripts")
    return None, ("no engine is ready. Best for cutting: an ElevenLabs account and API key (free tier, "
                  "then per minute). Offline on an Apple silicon Mac with macOS 26+: voz, no setup. "
                  "See docs/transcription.md")


def check() -> dict:
    """What can run on this machine. Makes no network calls."""
    rows, avail = [], {}
    for name in ENGINE_ORDER:
        try:
            ok, why = get(name).available()
        except Exception as e:  # a broken engine must not break the check
            ok, why = False, f"check failed: {e}"
        avail[name] = ok
        rows.append({"engine": name, "available": ok, "why_not": None if ok else why,
                     **TRADEOFFS.get(name, {})})
    rec, reason = recommend(avail)
    try:
        configured = settings.get("transcription.engine")
    except Exception:
        configured = None
    return {
        "configured_engine": configured,
        "configured_engine_available": avail.get(configured) if configured else None,
        "ffmpeg": bool(media.which("ffmpeg")),
        "engines": rows,
        "recommendation": rec,
        "recommendation_reason": reason,
        "set_command": "python3 tools/vidkit/settings.py set transcription.engine <engine>",
    }


def import_transcript(path, log) -> dict:
    """An existing transcript file -> raw words. Understands: ElevenLabs API
    JSON (and saved copies of it), voz-engine JSON, and segments-with-words
    JSON (this repo's own sidecars and the common `{"segments": [{"words":
    [...]}]}` shape other transcription apps save)."""
    p = Path(path).expanduser()
    try:
        data = json.loads(p.read_bytes().decode("utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        from vidkit.transcript import TranscriptionError
        raise TranscriptionError(f"cannot read {p}: {e}")
    from vidkit.transcript import TranscriptionError, normalize_language, sidecar_engine

    if isinstance(data, list):
        data = {"segments": data}
    if not isinstance(data, dict):
        raise TranscriptionError(f"{p.name}: not a transcript JSON object")

    if isinstance(data.get("transcripts"), list):   # ElevenLabs multichannel response
        data = {"words": sorted((w for t in data["transcripts"] for w in (t.get("words") or [])),
                                key=lambda w: w.get("start") or 0),
                "language_code": (data["transcripts"][0] or {}).get("language_code")}
    if isinstance(data.get("words"), list) and not data.get("segments"):
        if str(data.get("engine", "")).startswith("voz"):
            words = [{"start": w["start"], "end": w["end"], "word": (w.get("text") or "").strip()}
                     for w in data["words"] if (w.get("text") or "").strip()]
            log(f"importing voz-engine JSON: {len(words)} words")
            return {"words": words, "language": data.get("language"), "engine": "voz",
                    "model": data.get("model")}
        from vidkit.engines import elevenlabs
        words = elevenlabs.parse_response(data)
        log(f"importing ElevenLabs JSON: {len(words)} words")
        return {"words": words, "language": data.get("language_code"),
                "engine": "elevenlabs", "model": data.get("model_id")}

    if isinstance(data.get("segments"), list):
        words, interpolated = [], 0
        for seg in data["segments"]:
            if not isinstance(seg, dict):
                continue
            seg_words = seg.get("words")
            if seg_words:
                for w in seg_words:
                    words.append({"start": w.get("start"), "end": w.get("end"),
                                  "word": w.get("word", w.get("text", "")),
                                  "score": w.get("probability")})
            elif (seg.get("text") or "").strip() and seg.get("start") is not None:
                interpolated += 1
                words.append({"start": seg["start"], "end": seg.get("end", seg["start"]),
                              "word": seg["text"]})   # split by length in clean_words
        lang = data.get("language") or data.get("detected_language")
        res = {"words": words, "language": normalize_language(lang),
               "engine": sidecar_engine(data) or "imported", "model": (data.get("_meta") or {}).get("model")}
        if interpolated:
            log(f"warning: {interpolated} segment(s) had no word timestamps; their word times are "
                f"estimated from the text length (not precise enough for cutting on words)")
            res["word_timing"] = "partly estimated"
        log(f"importing segments-with-words JSON: {len(words)} words")
        return res

    raise TranscriptionError(f"{p.name}: unrecognised transcript format (expected ElevenLabs, "
                             f"voz-engine or segments-with-words JSON)")
