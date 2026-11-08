#!/usr/bin/env python3
"""Transcript sidecars: one word-level transcript per media file, made once
and reused by every skill.

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tools"))
    from vidkit.transcript import ensure_transcript, load_transcript, words

    sc = ensure_transcript("/path/clip.mp4")   # creates or reuses /path/clip.transcript.json
    doc = load_transcript(sc)                  # the sidecar as a dict
    for w in words(doc):
        print(w["start"], w["end"], w["word"])

Sidecar (`<media-dir>/<stem>.transcript.json`, times in seconds):

    {"segments": [{"start": 1.2, "end": 3.4, "text": "Um, so here it is.",
                   "words": [{"start": 1.2, "end": 1.5, "word": "Um,"}, ...]}],
     "language": "en",
     "_meta": {"schema": "transcript-sidecar/1", "engine": "elevenlabs",
               "model": "...", "source_name": "clip.mp4", "source_bytes": 123,
               "source_duration_s": 61.3, "source_hash": "md5h4t4s:...",
               "created": "2026-01-01T12:00:00+00:00"}}

Guarantees every reader can rely on, whatever engine made the file:
  - segments are sentences (split at . ! ? or a pause >= 2.5 s);
  - `segment["text"].split()` maps 1:1 onto `segment["words"]` (punctuation is
    glued to its word, multi-word tokens are split);
  - word times never go backwards, never overlap, and are never zero-length;
  - filler words (um, uh) are kept exactly as the engine heard them.

If the media folder is not writable, the sidecar goes to the cache folder
(settings `paths.cache_dir`, default <repo>/user/cache) under transcripts/.
A sidecar whose source file changed (size or content) is "stale": it is moved
aside as `<stem>.transcript.stale-<time>.json`, never deleted, and the file is
transcribed again.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vidkit import settings  # noqa: E402

SCHEMA = "transcript-sidecar/1"
SUFFIX = ".transcript.json"
HASH_PREFIX = "md5h4t4s:"   # md5(first 4 MB + last 4 MB + str(size)): survives renames, changes on re-encode
PAUSE_SPLIT_S = 2.5         # a pause this long starts a new segment
SOFT_MAX_WORDS = 50         # unpunctuated speech: break at the next small pause after this many words
HARD_MAX_WORDS = 90         # ... and unconditionally here
MIN_WORD_S = 0.02           # shortest word duration written
# Old engine names found in sidecars made by other tools -> today's engine names.
LEGACY_ENGINES = {"scribe": "elevenlabs", "voz+align": "voz"}


class TranscriptionError(RuntimeError):
    """The engine ran but failed (API error, crash, unreadable output)."""


class EngineUnavailable(TranscriptionError):
    """The chosen engine cannot run on this machine (not installed, no key)."""


class NoSpeech(TranscriptionError):
    """The engine finished but heard no words. Nothing is written."""


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---- paths -------------------------------------------------------------------

def _abs(media) -> Path:
    # abspath, not resolve(): a symlinked clip gets its sidecar next to the link.
    return Path(os.path.abspath(os.path.expanduser(str(media))))


def sidecar_path(media) -> Path:
    """Where the sidecar for `media` lives: <media-dir>/<stem>.transcript.json."""
    src = _abs(media)
    return src.with_name(src.stem + SUFFIX)


def _cache_root() -> Path:
    base = settings.get_path("paths.cache_dir") or (settings.USER_DIR / "cache")
    return base / "transcripts"


def cache_sidecar_path(media) -> Path:
    """The fallback location when the media folder is read-only. Keyed by the
    content hash, so two clips with the same name in different folders do not
    collide and a moved clip still finds its transcript."""
    src = _abs(media)
    key = source_hash(src)[len(HASH_PREFIX):][:12]
    return _cache_root() / f"{src.stem}.{key}{SUFFIX}"


def find_sidecar(media) -> Path | None:
    """The existing sidecar for `media` (next to it, else in the cache), or None.
    Does not check staleness: ensure_transcript does."""
    for p in (sidecar_path(media), cache_sidecar_path(media)):
        if p.is_file():
            return p
    return None


def source_hash(path) -> str:
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.md5()
    with open(p, "rb") as f:
        h.update(f.read(4 * 1024 * 1024))
        if size > 8 * 1024 * 1024:
            f.seek(-4 * 1024 * 1024, 2)
            h.update(f.read())
    h.update(str(size).encode())
    return HASH_PREFIX + h.hexdigest()


def _dir_writable(d: Path) -> bool:
    """Really try: os.access() lies on some network shares and read-only mounts."""
    try:
        with tempfile.NamedTemporaryFile(dir=str(d), prefix=".write-test-"):
            pass
        return True
    except OSError:
        return False


# ---- reading -----------------------------------------------------------------

_ISO3_TO_ISO1 = {
    "eng": "en", "spa": "es", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "ita": "it",
    "por": "pt", "nld": "nl", "dut": "nl", "pol": "pl", "rus": "ru", "ukr": "uk", "tur": "tr",
    "ara": "ar", "hin": "hi", "jpn": "ja", "kor": "ko", "zho": "zh", "chi": "zh", "cmn": "zh",
    "swe": "sv", "nor": "no", "nob": "no", "dan": "da", "fin": "fi", "ces": "cs", "cze": "cs",
    "ell": "el", "gre": "el", "heb": "he", "hun": "hu", "ron": "ro", "rum": "ro", "vie": "vi",
    "tha": "th", "ind": "id", "msa": "ms", "fil": "tl", "tgl": "tl", "cat": "ca", "bul": "bg",
}


def normalize_language(code) -> str | None:
    """'eng' / 'English' / 'en-US' -> 'en' where we know it; otherwise as given."""
    if not code:
        return None
    c = str(code).strip()
    low = c.lower()
    if low in _ISO3_TO_ISO1:
        return _ISO3_TO_ISO1[low]
    if low == "english":
        return "en"
    if len(low) >= 2 and (len(low) == 2 or low[2] in "-_"):
        return low[:2]
    return c


def load_transcript(path) -> dict:
    """Load a sidecar. `path` may be the sidecar itself or the media file it
    belongs to. Older sidecars are adapted on the fly ("detected_language" ->
    "language")."""
    p = _abs(path)
    if not p.name.endswith(".json"):
        found = find_sidecar(p)
        if not found:
            raise FileNotFoundError(f"no transcript for {p}; run tools/transcribe.py on it first")
        p = found
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict) or not isinstance(doc.get("segments"), list):
        raise ValueError(f"{p} is not a transcript sidecar (no segments)")
    if not doc.get("language"):
        doc["language"] = normalize_language(doc.get("detected_language"))
    return doc


def words(transcript) -> list:
    """Every word in order, as the sidecar's own dicts ({"start","end","word"}).
    Accepts a loaded dict or a path."""
    doc = transcript if isinstance(transcript, dict) else load_transcript(transcript)
    out = []
    for seg in doc.get("segments") or []:
        if isinstance(seg, dict):
            out.extend(w for w in (seg.get("words") or []) if isinstance(w, dict))
    return out


def word_count(doc: dict) -> int:
    return len(words(doc))


def sidecar_engine(doc: dict) -> str | None:
    """The engine that made a sidecar (from _meta.engine, or the '(name)' in an
    older _meta.tool string). None when unknown."""
    meta = doc.get("_meta") if isinstance(doc, dict) else None
    if not isinstance(meta, dict):
        return None
    eng = meta.get("engine")
    if not eng:
        m = re.search(r"\(([\w.-]+)\)\s*$", str(meta.get("tool") or ""))
        eng = m.group(1) if m else None
    return LEGACY_ENGINES.get(eng, eng) if eng else None


# ---- staleness -----------------------------------------------------------------

def _probe_duration(src: Path) -> float | None:
    from vidkit import media
    try:
        return media.probe(src).get("duration")
    except SystemExit:
        return None


def sidecar_status(media, sidecar, log=_stderr) -> str:
    """'valid' | 'stale' | 'invalid' | 'absent'."""
    src, sc = _abs(media), Path(sidecar)
    if not sc.is_file():
        return "absent"
    try:
        with open(sc, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        log(f"sidecar is unreadable: {sc}")
        return "invalid"
    if not isinstance(doc, dict) or word_count(doc) < 1:
        log(f"sidecar holds no words: {sc}")
        return "invalid"
    meta = doc.get("_meta")
    if not isinstance(meta, dict):
        log(f"sidecar has no _meta (made by another tool); reusing it as is: {sc}")
        return "valid"
    size = src.stat().st_size
    if meta.get("source_bytes") not in (None, size):
        log(f"the media file's size changed since it was transcribed (re-exported?): {sc.name} is stale")
        return "stale"
    expected = meta.get("source_hash")
    if expected:
        if expected != source_hash(src):
            log(f"the media file's content changed since it was transcribed: {sc.name} is stale")
            return "stale"
        return "valid"
    # No content hash: fall back to the duration, when both are known.
    was = meta.get("source_duration_s")
    if isinstance(was, (int, float)) and was > 0:
        now = _probe_duration(src)
        if now and abs(now - was) > max(0.5, 0.002 * was):
            log(f"the media file's duration changed ({was:.1f}s -> {now:.1f}s): {sc.name} is stale")
            return "stale"
    return "valid"


def move_aside(sidecar, log=_stderr) -> Path | None:
    """Rename a sidecar (and its .transcript.original.json sibling, if any) to
    *.stale-<time>.json. Never deletes data; an empty 0-byte stub left by a
    failed write is not data and is removed."""
    sc = Path(sidecar)
    ts = time.strftime("%Y%m%d-%H%M%S")
    moved = None
    for p in (sc, sc.with_name(sc.name[: -len(SUFFIX)] + ".transcript.original.json")):
        if not p.exists():
            continue
        try:
            if p.stat().st_size == 0:
                p.unlink()
                log(f"removed empty stub {p}")
                continue
            dest = p.with_name(p.name[: -len(".json")] + f".stale-{ts}.json")
            p.rename(dest)
            log(f"moved the old transcript aside -> {dest}")
            moved = moved or dest
        except OSError as e:
            log(f"could not move {p} aside ({e}); leaving it in place")
    return moved


def write_json_atomic(path, doc: dict, retries: int = 4, log=_stderr) -> Path:
    """Temp file + os.replace, retried: network shares throw transient errors,
    and the final name must only ever appear complete."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    last = None
    for attempt in range(1, retries + 1):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return path
        except OSError as e:
            last = e
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            if attempt < retries:
                log(f"write attempt {attempt}/{retries} failed for {path.name}: {e}; retrying")
                time.sleep(0.5 * attempt)
    raise last


# ---- normalization (shared by every engine and importer) ------------------------

def purify_word(text: str) -> str:
    """Collapse hyphenated stutters ("I-I'm" -> "I'm", "th-the" -> "the",
    "N-" -> "N"), keeping attached punctuation. Every part before the last must
    be a prefix of the last; real hyphenated words stay ("14-inch", "no-brainer")."""
    if "-" not in text:
        return text
    parts = [p for p in text.split("-") if p]
    if not parts:
        return text
    if len(text) == 2 and text.endswith("-"):
        return text[0]
    if len(parts) == 1:          # a cut-off word ("seven-")
        return parts[0]
    core = [re.sub(r"[^\w']+", "", p).lower() for p in parts]
    last = core[-1]
    if last and all(c and last.startswith(c) for c in core[:-1]):
        return parts[-1]
    return text


_TRAILING_PUNCT = re.compile(r"^[.,!?;:…\"'”’)\]}\-–—]+$")
_LEADING_PUNCT = re.compile(r"^[\"'“‘(\[{¿¡]+$")


def _drop_annotations(ws: list) -> list:
    """Some engines write non-speech as bracketed text ("[BLANK_AUDIO]", "(music)",
    "♪"). Drop such runs (at most 5 tokens) so they never read as words."""
    out, i = [], 0
    while i < len(ws):
        t = ws[i]["word"]
        if set(t) <= set("♪♫♬♭* "):
            i += 1
            continue
        if t[:1] in "[(":
            close = "]" if t[0] == "[" else ")"
            j = i
            while j < len(ws) and j < i + 5 and not ws[j]["word"].rstrip(".,!?").endswith(close):
                j += 1
            if j < len(ws) and j < i + 5:
                i = j + 1
                continue
        out.append(ws[i])
        i += 1
    return out


def _fill_missing_times(ws: list) -> list:
    """Words with no time (some aligners skip numerals) get times spread over
    the gap between their timed neighbours."""
    def timed(w):
        return w.get("start") is not None and w.get("end") is not None

    n_timed = sum(1 for w in ws if timed(w))
    if not n_timed:
        raise TranscriptionError("the transcript has no word timestamps")
    if n_timed == len(ws):
        return ws
    i = 0
    while i < len(ws):
        if timed(ws[i]):
            i += 1
            continue
        j = i
        while j < len(ws) and not timed(ws[j]):
            j += 1
        before = ws[i - 1]["end"] if i > 0 else None
        after = ws[j]["start"] if j < len(ws) else None
        lo = before if before is not None else after
        hi = after if after is not None else before
        hi = max(hi, lo)
        step = (hi - lo) / (j - i)
        for k in range(i, j):
            ws[k]["start"] = lo + step * (k - i)
            ws[k]["end"] = lo + step * (k - i + 1)
        i = j
    return ws


def _clamp_times(ws: list) -> list:
    """Starts never go backwards; words sharing a start are spread out; a word
    ends no later than the next one starts; nothing is shorter than MIN_WORD_S
    (unless the next word leaves no room)."""
    n = len(ws)
    for w in ws:
        w["start"], w["end"] = float(w["start"]), float(w["end"])
        if w["start"] < 0:
            w["start"] = 0.0
        if w["end"] < w["start"]:
            w["end"] = w["start"]
    for i in range(1, n):
        if ws[i]["start"] < ws[i - 1]["start"]:
            ws[i]["start"] = ws[i - 1]["start"]
            ws[i]["end"] = max(ws[i]["end"], ws[i]["start"])
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ws[j + 1]["start"] == ws[i]["start"]:
            j += 1
        if j > i:
            count = j - i + 1
            lo = ws[i]["start"]
            hi = max(max(w["end"] for w in ws[i:j + 1]), lo + MIN_WORD_S * count)
            if j + 1 < n:
                hi = min(hi, ws[j + 1]["start"])
            step = (hi - lo) / count
            for k in range(count):
                ws[i + k]["start"] = lo + step * k
                ws[i + k]["end"] = lo + step * (k + 1)
        i = j + 1
    for i, w in enumerate(ws):
        nxt = ws[i + 1]["start"] if i + 1 < n else float("inf")
        if w["end"] > nxt:
            w["end"] = nxt
        if w["end"] - w["start"] < MIN_WORD_S:
            w["end"] = min(w["start"] + MIN_WORD_S, nxt) if nxt > w["start"] else w["start"]
    for w in ws:
        w["start"], w["end"] = round(w["start"], 3), round(w["end"], 3)
    return ws


def clean_words(raw: list, purify: bool = True, drop_annotations: bool = True) -> list:
    """Raw engine tokens [{"start","end","word"(,"score")}] -> sidecar words.

    Leading/trailing spaces go, punctuation-only tokens are glued to their
    neighbour, tokens holding several words are split (time shared by length),
    stutters are collapsed, then the times are fixed up (see _clamp_times)."""
    ws = []
    pending_prefix = ""
    for r in raw:
        text = str(r.get("word", r.get("text", "")) or "").strip()
        if not text:
            continue
        start, end = r.get("start"), r.get("end")
        start = None if start is None else float(start)
        end = None if end is None else float(end)
        score = r.get("score", r.get("probability"))
        if _TRAILING_PUNCT.match(text) and ws:
            ws[-1]["word"] += text
            continue
        if _LEADING_PUNCT.match(text):
            pending_prefix += text
            continue
        parts = text.split()
        if len(parts) > 1 and start is not None and end is not None:
            total = sum(len(p) for p in parts) or len(parts)
            cursor = start
            for k, p in enumerate(parts):
                w_end = end if k == len(parts) - 1 else cursor + (end - start) * len(p) / total
                ws.append({"start": cursor, "end": w_end, "word": p})
                cursor = w_end
        else:
            for p in parts:
                ws.append({"start": start, "end": end, "word": p})
        if pending_prefix:
            ws[-len(parts)]["word"] = pending_prefix + ws[-len(parts)]["word"]
            pending_prefix = ""
        if score is not None:
            for w in ws[-len(parts):]:
                try:
                    w["score"] = round(float(score), 3)
                except (TypeError, ValueError):
                    pass
    if purify:
        for w in ws:
            w["word"] = purify_word(w["word"])
        ws = [w for w in ws if w["word"].strip()]
    if drop_annotations:
        ws = _drop_annotations(ws)
    if not ws:
        return ws
    return _clamp_times(_fill_missing_times(ws))


def group_sentences(ws: list) -> list:
    """Sentence segments: break after . ! ? or before a pause >= PAUSE_SPLIT_S.
    Unpunctuated speech (some imported transcripts) is also broken at a small pause
    after SOFT_MAX_WORDS words, and always at HARD_MAX_WORDS."""
    segments, current = [], []
    for i, w in enumerate(ws):
        current.append(w)
        last = i == len(ws) - 1
        gap = None if last else ws[i + 1]["start"] - w["end"]
        if (last or w["word"].rstrip("\"'”’)").endswith((".", "!", "?"))
                or gap >= PAUSE_SPLIT_S
                or (len(current) >= SOFT_MAX_WORDS and gap >= 0.3)
                or len(current) >= HARD_MAX_WORDS):
            segments.append({"start": current[0]["start"], "end": current[-1]["end"],
                             "text": " ".join(x["word"] for x in current), "words": current})
            current = []
    return segments


def build_document(raw_words: list, language=None, purify: bool = True) -> dict:
    """Raw engine output -> {"segments": [...], "language": ...} (no _meta)."""
    ws = clean_words(raw_words, purify=purify)
    return {"segments": group_sentences(ws), "language": normalize_language(language)}


def build_meta(src: Path, engine: str, model: str | None, duration: float | None, **extra) -> dict:
    meta = {
        "schema": SCHEMA,
        "engine": engine,
        "model": model,
        "source_name": src.name,
        "source_bytes": src.stat().st_size,
        "source_duration_s": round(duration, 3) if duration else None,
        "source_hash": source_hash(src),
        "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    meta.update({k: v for k, v in extra.items() if v is not None})
    return meta


# ---- the main entry point --------------------------------------------------------

def resolve_engine(engine: str | None) -> str:
    """'auto'/None -> settings transcription.engine; raises SettingMissing when unset."""
    from vidkit import engines
    if engine in (None, "", "auto"):
        engine = settings.get("transcription.engine", required=True,
                              hint="which speech-to-text engine to use; see docs/transcription.md")
    engine = LEGACY_ENGINES.get(engine, engine)
    if engine not in engines.ENGINE_ORDER:
        raise ValueError(f"unknown transcription engine '{engine}'. "
                         f"Choose one of: {', '.join(engines.ENGINE_ORDER)}")
    return engine


def _target_for_write(src: Path, log) -> Path:
    if _dir_writable(src.parent):
        return sidecar_path(src)
    target = cache_sidecar_path(src)
    log(f"the media folder is not writable ({src.parent}); "
        f"saving the transcript in the cache instead: {target}")
    return target


def ensure_transcript(path, engine: str | None = None, language: str | None = None,
                      force: bool = False, import_file=None, log=None) -> Path:
    """Return the sidecar path for `path`, transcribing only when there is no
    valid sidecar yet.

    engine: an engine name, or None/'auto' for settings `transcription.engine`.
            Only needed when a transcript must actually be made.
    language: e.g. 'en'; None = settings `transcription.language`, else auto-detect.
    force: transcribe again even if a valid sidecar exists (the old one is moved aside).
    import_file: build the sidecar from an existing transcript file instead of
            running an engine (ElevenLabs, voz-engine or segments-with-words JSON).

    A valid sidecar is reused, with one exception: a transcript made by an
    offline engine (voz) is only triage-grade, so when a cutting-grade engine
    (elevenlabs) is asked for, explicitly or as the configured engine, the
    offline sidecar is moved aside and the file is transcribed again. Asking
    for voz reuses any valid sidecar.

    Raises settings.SettingMissing (no engine configured), EngineUnavailable,
    NoSpeech, TranscriptionError, FileNotFoundError.
    """
    log = log or _stderr
    src = _abs(path)
    if not src.is_file():
        raise FileNotFoundError(f"media file not found: {src}")
    candidates = [sidecar_path(src), cache_sidecar_path(src)]
    replace_offline: list = []

    if import_file is None and not force:
        valid = []
        for sc in candidates:
            status = sidecar_status(src, sc, log)
            if status == "valid":
                valid.append(sc)
            elif status in ("stale", "invalid"):
                move_aside(sc, log)
        # Both exist only if an old one could not be moved out of a read-only
        # folder: the newer one wins.
        if valid:
            sc = max(valid, key=lambda p: p.stat().st_mtime)
            try:
                with open(sc, encoding="utf-8") as f:
                    made_by = sidecar_engine(json.load(f))
            except (OSError, ValueError):
                made_by = None
            if engine not in (None, "", "auto"):
                wanted = LEGACY_ENGINES.get(engine, engine)
            else:
                wanted = settings.get("transcription.engine")   # None when unset: reuse as is
            from vidkit.engines import OFFLINE_ENGINES
            if made_by in OFFLINE_ENGINES and wanted and wanted not in OFFLINE_ENGINES:
                log(f"this transcript was made offline by {made_by} (fine for sorting, not for cutting); "
                    f"{wanted} was asked for, so it is moved aside and the file transcribed again")
                replace_offline = valid   # moved aside once the engine is confirmed to run here
            else:
                if made_by and wanted and made_by != wanted:
                    log(f"note: this transcript was made by {made_by}, not {wanted}; "
                        f"reusing it (pass --force to transcribe again with {wanted})")
                log(f"reusing transcript: {sc}")
                return sc
    else:
        for sc in candidates:
            if sc.is_file():
                move_aside(sc, log)

    from vidkit import engines

    if import_file is not None:
        raw = engines.import_transcript(import_file, log)
        eng_name, model = raw.get("engine") or "imported", raw.get("model")
        duration = _probe_duration(src)
        extra = {"imported_from": Path(import_file).name}
    else:
        eng_name = resolve_engine(engine)
        eng = engines.get(eng_name)
        ok, why = eng.available()
        if not ok:
            raise EngineUnavailable(f"the {eng_name} engine is not available here: {why}")
        for v in replace_offline:
            move_aside(v, log)
        from vidkit import media
        try:
            info = media.probe(src)
        except SystemExit as e:
            raise TranscriptionError(str(e))
        if not info.get("has_audio"):
            raise TranscriptionError(f"{src.name} has no audio track")
        duration = info.get("duration")
        language = language or settings.get("transcription.language")
        log(f"transcribing {src.name} ({(duration or 0) / 60:.1f} min) with {eng_name}...")
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="vidkit-transcribe-") as td:
            raw = eng.transcribe(src, Path(td), language, duration, log)
        log(f"{eng_name} finished in {time.time() - started:.0f}s")
        model = raw.get("model")
        extra = {}

    doc = build_document(raw.get("words") or [], raw.get("language") or language)
    n = word_count(doc)
    if n == 0:
        raise NoSpeech(f"no speech found in {src.name}; nothing written")
    if raw.get("word_timing"):
        extra["word_timing"] = raw["word_timing"]
    doc["_meta"] = build_meta(src, eng_name, model, duration, **extra)
    target = _target_for_write(src, log)
    write_json_atomic(target, doc, log=log)
    log(f"wrote {n} words in {len(doc['segments'])} segments -> {target}")
    return target


if __name__ == "__main__":
    print(__doc__)
