"""Shared repair for agent output. The aroll-editor and aroll-reviser are told to
reply with a raw JSON array but sometimes wrap it in a code fence or prose.
Every script that parses agent output tolerates that the same way: add new
tolerances here, not in the callers.
"""
from __future__ import annotations

import re


def extract_json_array(text: str) -> str:
    """Best JSON-array candidate substring of text (text itself if none found).

    A fenced ```json array wins: a greedy bare-bracket match would mis-span when
    prose outside the fence also contains brackets."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        return m.group(0)
    return text
