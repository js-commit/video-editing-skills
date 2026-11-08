"""No-model backend: reports the images it was handed instead of describing them.

For testing the CLI's plumbing (frame extraction, batching, JSON Lines output,
--backend selection) without loading gigabytes of weights. Runs anywhere.
"""
from pathlib import Path

NEEDS_LOCK = False  # no model in memory, so nothing for the one-model lock to guard


def check():
    pass


def load():
    return {}


def describe(h, image_paths, prompt):
    names = ", ".join(Path(p).name for p in image_paths)
    return f"[echo] {len(image_paths)} image(s): {names} | prompt: {prompt[:60]}"


def info():
    return {"backend": "echo", "model": None}
