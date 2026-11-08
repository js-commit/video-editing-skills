"""Local vision-model backends for vlm-describe.

One interface, so swapping the model is one new file + one BACKENDS entry:

    check()                                    -> raise ImportError if unusable
    load()                                     -> handle
    describe(handle, image_paths, prompt)      -> str
    unload(handle)                             -> None          (optional)
    info() / stats()                           -> dict of _meta (optional)
    NEEDS_LOCK = False                         -> skip the one-model lock (optional;
                                                  a backend that holds no weights)
    INSTALL = "python3 -m pip install ..."     -> shown when check() fails (optional)

Backends run inside the local-vision Python (settings `vision.python`, or
$LOCAL_VLM_PYTHON); vlm_describe.py re-execs itself there when the current
interpreter fails check(), so a backend may import whatever that venv holds.
"""
import importlib

BACKENDS = {
    "qwen35-mlx": "backends.qwen35_mlx",
    "echo": "backends.echo",
}


def get(name):
    if name not in BACKENDS:
        raise SystemExit(f"unknown backend {name!r}; known: {', '.join(sorted(BACKENDS))}")
    return importlib.import_module(BACKENDS[name])
