"""ElevenLabs Scribe (cloud speech-to-text): the most accurate engine here.
Keeps filler words (um, uh) and times every word well, which is what the
a-roll drafter cuts on. Needs an ElevenLabs account: there is a free tier,
beyond it minutes of audio are billed to the account. The audio leaves the
computer.

The API key comes from the environment variable ELEVENLABS_API_KEY. It is
never read from or written to this repo, and never printed.
"""
from __future__ import annotations

import json
import mimetypes
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from vidkit import media, settings
from vidkit.engines import _audio
from vidkit.transcript import TranscriptionError

NAME = "elevenlabs"
KIND = "cloud"
API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
KEY_VARS = ("ELEVENLABS_API_KEY",)
DEFAULT_MODEL = "scribe_v2"
# Long recordings are sent in pieces of at most this length, cut in a pause, so
# one upload stays small (~22 MB) and one failure does not lose the whole job.
MAX_CHUNK_S = 45 * 60
RETRY_WAITS_S = (5, 20, 60)


def api_key() -> str | None:
    for var in KEY_VARS:
        v = os.environ.get(var)
        if v and v.strip():
            return v.strip()
    return None


def available():
    if not api_key():
        return False, ("no API key: set the environment variable ELEVENLABS_API_KEY "
                       "(see docs/transcription.md)")
    if not media.which("ffmpeg"):
        return False, "ffmpeg is not installed (needed to extract the audio)"
    return True, None


def _multipart(fields: dict, file_field: str, file_path: Path):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
             f"filename=\"{file_path.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    body += file_path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def request(audio: Path, key: str, language: str | None, model: str, log) -> dict:
    """One upload; the API's JSON response. Retries rate limits, server errors
    and network drops; raises TranscriptionError otherwise."""
    fields = {"model_id": model, "timestamps_granularity": "word",
              "tag_audio_events": "false", "diarize": "false", "num_speakers": "1"}
    if language:
        fields["language_code"] = language
    body, ctype = _multipart(fields, "file", audio)
    for attempt in range(len(RETRY_WAITS_S) + 1):
        req = urllib.request.Request(API_URL, data=body, method="POST",
                                     headers={"xi-api-key": key, "Content-Type": ctype,
                                              "Accept": "application/json"})
        try:
            log(f"uploading {len(body) / 1e6:.1f} MB to ElevenLabs...")
            with urllib.request.urlopen(req, timeout=1800) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:400]
            if e.code in (401, 403):
                raise TranscriptionError(f"ElevenLabs refused the API key (HTTP {e.code}). "
                                         f"Check ELEVENLABS_API_KEY. {detail}")
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == len(RETRY_WAITS_S):
                raise TranscriptionError(f"ElevenLabs API error {e.code}: {detail}")
            why = f"HTTP {e.code}"
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            if attempt == len(RETRY_WAITS_S):
                raise TranscriptionError(f"could not reach ElevenLabs: {e}")
            why = str(e)
        wait = RETRY_WAITS_S[attempt]
        log(f"ElevenLabs: {why}; retrying in {wait}s")
        time.sleep(wait)
    raise TranscriptionError("unreachable")


def parse_response(data: dict, offset: float = 0.0) -> list:
    """API (or saved API) JSON -> raw words. Spacing and audio-event tokens are
    dropped; filler words are kept as they are."""
    out = []
    for t in data.get("words") or []:
        if t.get("type", "word") != "word":
            continue
        text = (t.get("text") or "").strip()
        if not text or t.get("start") is None:
            continue
        w = {"start": float(t["start"]) + offset,
             "end": float(t.get("end", t["start"])) + offset, "word": text}
        out.append(w)
    return out


def plan_chunks(src: Path, duration: float | None, log) -> list:
    """[(start, length-or-None)] pieces no longer than MAX_CHUNK_S, each cut in
    the pause closest to the limit, so no word is split between two uploads."""
    if not duration or duration <= MAX_CHUNK_S:
        return [(0.0, None)]
    log(f"long recording: finding pauses to split it into pieces of <= {MAX_CHUNK_S // 60} min...")
    mids = [(a + b) / 2 for a, b in _audio.silences(src)]
    cuts, start = [], 0.0
    while duration - start > MAX_CHUNK_S:
        target = start + MAX_CHUNK_S
        near = [m for m in mids if start + MAX_CHUNK_S * 0.5 < m <= target]
        cut = max(near) if near else target
        cuts.append((start, cut - start))
        start = cut
    cuts.append((start, None))
    return cuts


def transcribe(src: Path, workdir: Path, language, duration, log) -> dict:
    key = api_key()
    if not key:
        raise TranscriptionError(available()[1])
    model = settings.get("transcription.elevenlabs_model", default=DEFAULT_MODEL)
    minutes = (duration or 0) / 60
    log(f"ElevenLabs Scribe: sending {minutes:.1f} min of audio; past the free tier these minutes "
        f"are billed to the account that owns the API key.")
    words, lang = [], None
    pieces = plan_chunks(src, duration, log)
    for k, (start, length) in enumerate(pieces):
        audio = _audio.compressed16k(src, workdir / f"upload{k}", start or None, length)
        if len(pieces) > 1:
            log(f"piece {k + 1}/{len(pieces)} from {start / 60:.1f} min")
        data = request(audio, key, language, model, log)
        words += parse_response(data, offset=start)
        lang = lang or data.get("language_code")
        try:
            audio.unlink()
        except OSError:
            pass
    return {"words": words, "language": lang or language, "model": model}
