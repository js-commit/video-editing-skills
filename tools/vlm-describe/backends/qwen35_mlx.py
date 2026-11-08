"""Qwen3.5-9B 4-bit via mlx-vlm (Apple silicon, Metal). The default backend.

About 1 s per 512 px frame and ~1.5 s per 4-frame clip call on a recent M-series
chip, ~7 GB of memory while loaded; a 16 GB Mac can run it with other apps
closed. The weights (about 5.6 GB) download from Hugging Face on the first run
and are pinned to one revision, so results stay reproducible; after that the
model loads from the local cache (offline is fine).

Install, in a virtual environment of its own (then point settings
`vision.python` at that environment's python3):

    python3 -m venv ~/.venvs/local-vision
    ~/.venvs/local-vision/bin/python3 -m pip install mlx-vlm pillow
"""
import os
from pathlib import Path

MODEL = "mlx-community/Qwen3.5-9B-4bit"
REVISION = "8b2b98c00a6b4d291155e4890773ca8f769aee53"
INSTALL = "python3 -m venv ~/.venvs/local-vision && ~/.venvs/local-vision/bin/python3 -m pip install mlx-vlm pillow"
# 100 tokens fits a one-sentence description. A prompt that asks for more (a
# JSON scan, several phrases) needs more: VLM_MAX_TOKENS=360.
MAX_TOKENS = int(os.environ.get("VLM_MAX_TOKENS") or 100)

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def _cached() -> bool:
    hub = Path(os.environ.get("HF_HUB_CACHE") or os.environ.get("HF_HOME", "~/.cache/huggingface") + "/hub").expanduser()
    return (hub / ("models--" + MODEL.replace("/", "--")) / "snapshots" / REVISION).is_dir()


def check():
    """Raise ImportError unless this interpreter can run the backend."""
    import mlx.core  # noqa: F401
    import mlx_vlm  # noqa: F401
    import PIL  # noqa: F401


def load():
    import mlx.core as mx
    from mlx_vlm import load as _load
    from mlx_vlm.utils import load_config
    if _cached():  # never phone home once the pinned weights are here
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    else:
        print(f"downloading {MODEL} (about 5.6 GB, once) ...", flush=True, file=__import__("sys").stderr)
    mx.reset_peak_memory()
    model, processor = _load(MODEL, revision=REVISION)
    config = load_config(MODEL, revision=REVISION)
    return {"model": model, "processor": processor, "config": config}


def describe(h, image_paths, prompt):
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template
    fp = apply_chat_template(h["processor"], h["config"], prompt,
                             num_images=len(image_paths), enable_thinking=False)
    r = generate(h["model"], h["processor"], fp, image=list(image_paths),
                 max_tokens=MAX_TOKENS, temperature=0.0, verbose=False)
    return r.text.strip()


def stats():
    import mlx.core as mx
    return {"peak_memory_gb": round(mx.get_peak_memory() / 1e9, 2)}


def unload(h):
    import gc
    import mlx.core as mx
    h.clear()
    gc.collect()
    mx.clear_cache()


def info():
    import mlx.core as mx
    import mlx_vlm
    return {"backend": "qwen35-mlx", "model": MODEL, "revision": REVISION,
            "engine": f"mlx-vlm {mlx_vlm.__version__} / mlx {mx.__version__}"}
