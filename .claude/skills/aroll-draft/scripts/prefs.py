"""Read the user's standing a-roll preferences and the transcript language, for
the editor and reviser prompts.

`## aroll-draft` in <repo>/user/preferences.md (bullets the user or Claude wrote:
"leave more air", "never cut my jokes", "keep tangents"). Example bullets that
still start with "(example)" are ignored.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PREFERENCES = REPO / "user" / "preferences.md"
SECTION = "aroll-draft"

LANG_NAMES = {
    "en": "English", "eng": "English", "es": "Spanish", "spa": "Spanish", "fr": "French", "fra": "French",
    "de": "German", "deu": "German", "it": "Italian", "ita": "Italian", "pt": "Portuguese", "por": "Portuguese",
    "nl": "Dutch", "nld": "Dutch", "pl": "Polish", "pol": "Polish", "ru": "Russian", "rus": "Russian",
    "uk": "Ukrainian", "ukr": "Ukrainian", "tr": "Turkish", "tur": "Turkish", "ja": "Japanese", "jpn": "Japanese",
    "ko": "Korean", "kor": "Korean", "zh": "Chinese", "zho": "Chinese", "cmn": "Chinese", "hi": "Hindi",
    "hin": "Hindi", "ar": "Arabic", "ara": "Arabic", "sv": "Swedish", "swe": "Swedish", "da": "Danish",
    "dan": "Danish", "no": "Norwegian", "nor": "Norwegian", "fi": "Finnish", "fin": "Finnish", "cs": "Czech",
    "ces": "Czech", "el": "Greek", "ell": "Greek", "he": "Hebrew", "heb": "Hebrew", "id": "Indonesian",
    "ind": "Indonesian", "vi": "Vietnamese", "vie": "Vietnamese", "th": "Thai", "tha": "Thai",
}


def preference_bullets(path: str | os.PathLike | None = None, section: str = SECTION) -> list:
    """Bullet lines under `## <section>` (without the leading '- ')."""
    p = Path(path) if path else Path(os.environ.get("VES_PREFERENCES") or PREFERENCES)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    out, inside = [], False
    for line in text.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            inside = h.group(1).strip().lower() == section
            continue
        if not inside:
            continue
        m = re.match(r"^\s*[-*]\s+(.*\S)\s*$", line)
        if m and not m.group(1).lower().startswith("(example)"):
            out.append(m.group(1))
    return out


def preferences_block(path=None) -> str:
    bullets = preference_bullets(path)
    if not bullets:
        return ""
    return ("<preferences>\n"
            "The creator of this video has standing preferences for their edits. Follow them where they apply; "
            "they override the default rules above, but never the output format (tildes only, same words):\n"
            + "\n".join(f"- {b}" for b in bullets) + "\n</preferences>\n\n")


def language_of(transcript: dict) -> str | None:
    code = transcript.get("language") or transcript.get("detected_language")
    if not code:
        return None
    code = str(code).strip()
    return LANG_NAMES.get(code.lower(), code)


def language_block(transcript: dict) -> str:
    lang = language_of(transcript)
    if not lang or lang == "English":
        return ""
    return ("<language>\n"
            f"The speech is in {lang}. Apply every rule exactly the same way; the examples are English only "
            f"to show the method. Judge fillers, restarts and stutters as a native {lang} speaker would, and "
            "never translate or normalise any word.\n"
            "</language>\n\n")
