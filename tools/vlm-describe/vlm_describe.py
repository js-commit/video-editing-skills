#!/usr/bin/env python3
"""vlm-describe: describe images and video with a vision model running on THIS
computer. Nothing is uploaded; no frame of the footage reaches Claude or any
cloud service. The private alternative to the cloud frame-describer agents.

  python3 tools/vlm-describe/vlm_describe.py clip.mov photo.jpg
  python3 tools/vlm-describe/vlm_describe.py ~/footage/ --per both --frames 6
  python3 tools/vlm-describe/vlm_describe.py shot.mov --prompt "Is a face visible? Answer yes or no."
  python3 tools/vlm-describe/vlm_describe.py --batch work.json -o results.jsonl
  python3 tools/vlm-describe/vlm_describe.py --check

Videos are sampled into stills with ffmpeg (4-16 frames by length, see
sampling.py); the model sees those. Output is JSON Lines on stdout: one object
per input, then a {"_meta": ...} line:

  {"id": "clip.mov", "kind": "video", "frames": [{"t": 0.3, "text": "..."}],
   "clip": "...", "seconds": 1.4}

--per clip (default) gives one description per input from all its frames;
--per frame one per frame; --per both gives both. Pass many inputs to ONE call
(one model load), never call it in a loop. A second run on the same computer
waits for the first (--lock-timeout) or exits 3 (--no-wait): one model in
memory at a time.

Batch (--batch FILE, '-' for stdin): a JSON list or {"inputs": [...]} of
  {"id": "...", "path": "clip.mov"}                        extract frames from this file
  {"id": "...", "images": [{"path": "tile0.jpg", "t": 0.3}]}  the caller already has stills
Entries may carry any extra keys (they come back untouched) and may set
"per", "frames", "frame_prompt", "clip_prompt" for themselves.

The model runs in its own Python environment (settings vision.python, or
$LOCAL_VLM_PYTHON); this script re-runs itself there. --check says whether it
is ready and how to install it.

Exit codes: 0 done, 1 every input failed, 2 setup (environment, backend, args),
3 another run holds the model.
"""
from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import contextlib
import glob
import itertools
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sampling import frame_count, frame_times  # noqa: E402

TOOLS = HERE.parent
DEFAULT_BACKEND = "qwen35-mlx"
LOCK_PATH = os.environ.get("VLM_DESCRIBE_LOCK", str(Path.home() / ".cache" / "vlm-describe.lock"))
LOCK_WAIT_NOTE_S = 20
LOCK_TIMEOUT_S = 600
# Frames spread at least this far apart may stop at the keyframe before their
# time (a much cheaper seek on long 4K clips); closer ones are seeked exactly.
APPROX_SEEK_SPACING_S = 10
QUIET = False

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".insv",
             ".webm", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif",
             ".tiff", ".bmp", ".gif", ".dng"}

FRAME_PROMPT = (
    "Describe what this video frame shows in one sentence: the objects, any "
    "product, any animal or person, the setting, and whether the frame is "
    "blurry, dark, sideways or empty. Do not guess brand names.")
CLIP_PROMPT = (
    "These {n} frames were sampled in order from one video clip. In one or two "
    "sentences, describe what the clip shows: the main subject, what happens, "
    "the setting, the camera framing and movement, and anything notable about "
    "the image quality. Do not guess brand names or people's names.")
IMAGE_PROMPT = (
    "Describe this photo in one or two sentences: the subject, the setting, "
    "and anything notable about the image quality. Do not guess brand names "
    "or people's names.")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def progress(msg):
    if not QUIET:
        log(msg)


# ---- environment ------------------------------------------------------------

def vision_python() -> str | None:
    """The Python that has the vision packages: $LOCAL_VLM_PYTHON, else settings
    vision.python, else None (= try the current interpreter only)."""
    env = os.environ.get("LOCAL_VLM_PYTHON")
    if env:
        return str(Path(env).expanduser())
    try:
        sys.path.insert(0, str(TOOLS))
        from vidkit import settings
        v = settings.get("vision.python")
        return str(Path(os.path.expandvars(str(v))).expanduser()) if v else None
    except Exception:
        return None


def backend_name(arg: str | None) -> str:
    if arg:
        return arg
    if os.environ.get("VLM_BACKEND"):
        return os.environ["VLM_BACKEND"]
    try:
        sys.path.insert(0, str(TOOLS))
        from vidkit import settings
        return settings.get("vision.backend", default=DEFAULT_BACKEND) or DEFAULT_BACKEND
    except Exception:
        return DEFAULT_BACKEND


def ffmpeg(name="ffmpeg") -> str:
    p = shutil.which(name)
    if not p:
        log(f"error: {name} is not installed (needed to read frames out of videos)")
        sys.exit(2)
    return p


def reexec_if_needed(name: str):
    """Re-run this script under the vision Python if the backend needs it."""
    import backends
    try:
        backends.get(name).check()
        return
    except ImportError:
        pass
    if os.environ.get("VLM_DESCRIBE_REEXEC"):
        be = backends.get(name)
        log(f"error: backend {name!r} is not importable in {sys.executable}."
            + (f"\n  install: {be.INSTALL}" if getattr(be, "INSTALL", None) else ""))
        sys.exit(2)
    py = vision_python()
    if not py or not Path(py).is_file():
        be = backends.get(name)
        log(f"error: no Python environment with the vision packages. Set settings vision.python "
            f"(python3 tools/vidkit/settings.py set vision.python <path>) or $LOCAL_VLM_PYTHON."
            + (f"\n  install: {be.INSTALL}" if getattr(be, "INSTALL", None) else ""))
        sys.exit(2)
    env = dict(os.environ, VLM_DESCRIBE_REEXEC="1")
    os.execve(py, [py, __file__] + sys.argv[1:], env)


def check(name: str) -> dict:
    """What --check prints: can this computer describe frames locally?"""
    import platform
    import backends
    be = backends.get(name)
    out = {"backend": name, "available": False, "python": None, "model_cached": None,
           "install": getattr(be, "INSTALL", None), "why_not": None,
           "set_python": "python3 tools/vidkit/settings.py set vision.python <path to that venv's python3>"}
    if name != "echo" and (platform.system() != "Darwin" or platform.machine() != "arm64"):
        out["why_not"] = "the default backend runs on Apple silicon Macs only (mlx)"
        return out
    candidates = [sys.executable]
    py = vision_python()
    if py:
        candidates.insert(0, py)
    probe = ("import importlib,json,sys; sys.path.insert(0, %r); import backends; b=backends.get(%r)\n"
             "try:\n b.check(); ok=True\nexcept ImportError as e: ok=False\n"
             "print(json.dumps({'ok': ok, 'cached': getattr(b, '_cached', lambda: None)()}))") % (str(HERE), name)
    for cand in candidates:
        if not Path(cand).is_file():
            continue
        try:
            r = subprocess.run([cand, "-c", probe], capture_output=True, text=True, timeout=60)
            info = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
        except Exception:
            info = {}
        if info.get("ok"):
            out.update(available=True, python=cand, model_cached=info.get("cached"))
            return out
    out["why_not"] = ("the vision packages are not installed"
                      + (f" in {py}" if py else " (no vision.python set)"))
    return out


# ---- the one-model lock -----------------------------------------------------

def acquire_lock(timeout_s, n_inputs):
    """Hold the one-model-at-a-time lock for this process's lifetime. flock is
    released by the kernel when the holder exits, however it exits."""
    import fcntl
    Path(LOCK_PATH).parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_PATH, "a+")
    t0, last_note = time.time(), None
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            pass
        waited = time.time() - t0
        if waited >= timeout_s:
            log(f"error: another vlm-describe holds the model ({_lock_holder()}); gave up after "
                f"{int(waited)} s. One model in memory at a time: wait for it, raise --lock-timeout, "
                "or batch your inputs into that run.")
            sys.exit(3)
        if last_note is None or waited - last_note >= LOCK_WAIT_NOTE_S:
            log(f"waiting: another vlm-describe holds the model ({_lock_holder()}), {int(waited)} s so far")
            last_note = waited
        time.sleep(1)
    fd.seek(0)
    fd.truncate()
    fd.write(json.dumps({"pid": os.getpid(), "started": int(time.time()), "inputs": n_inputs}) + "\n")
    fd.flush()
    return fd


def _lock_holder():
    try:
        h = json.loads(Path(LOCK_PATH).read_text() or "{}")
        return f"pid {h.get('pid')}, {h.get('inputs')} input(s), {int(time.time() - h.get('started', time.time()))} s ago"
    except (OSError, ValueError):
        return "holder unknown"


def release_lock(fd):
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
    except OSError:
        pass


# ---- inputs and frames ------------------------------------------------------

def duration_of(path):
    try:
        r = subprocess.run([ffmpeg("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
        return float(r.stdout.strip())
    except (OSError, ValueError):
        return None


def extract_frames(path, times, out_dir, width, exact=True):
    """Pull the given timestamps out of a video as JPEGs: one ffmpeg call with N
    input seeks. exact=False lets every seek but the first stop at the keyframe
    before its time (much cheaper on long 4K clips); the first stays exact so
    the lead-in skip still skips the fade-in."""
    stem = "".join(c if c.isalnum() or c in "._-" else "-" for c in Path(path).stem)
    cmd = [ffmpeg(), "-v", "error", "-y"]
    for i, t in enumerate(times):
        if not exact and i > 0:
            cmd.append("-noaccurate_seek")
        cmd += ["-ss", str(t), "-i", str(path)]
    parts, outs = [], []
    for i, t in enumerate(times):
        parts.append(f"[{i}:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale={width}:-2[t{i}]")
        outs.append(out_dir / f"{stem}__{i}.jpg")
    cmd += ["-filter_complex", ";".join(parts)]
    for i, p in enumerate(outs):
        cmd += ["-map", f"[t{i}]", "-frames:v", "1", "-q:v", "3", str(p)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    got = [(t, p) for t, p in zip(times, outs) if p.exists()]
    if not got:
        raise RuntimeError(f"ffmpeg extracted no frames: {r.stderr.strip()[:200]}")
    return got


def extract_photo(path, out_dir, width):
    p = out_dir / (Path(path).stem + ".jpg")
    r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(path), "-vf", f"scale={width}:-2",
                        "-frames:v", "1", "-q:v", "3", str(p)], capture_output=True, text=True)
    if not p.exists():
        raise RuntimeError(f"ffmpeg could not read photo: {r.stderr.strip()[:200]}")
    return p


def kind_of(path):
    ext = Path(path).suffix.lower()
    return "video" if ext in VIDEO_EXT else "photo" if ext in PHOTO_EXT else None


def expand_inputs(paths, recursive):
    """Files, directories and globs -> a flat list of media files."""
    out = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            it = sorted(p.rglob("*") if recursive else p.glob("*"))
            out += [q for q in it if q.is_file() and kind_of(q)]
        elif p.exists():
            out.append(p)
        else:
            hits = sorted(Path(h) for h in glob.glob(str(p)))
            if not hits:
                log(f"warning: no such file: {raw}")
            out += [q for q in hits if q.is_file()]
    return out


def load_batch(spec):
    data = json.load(sys.stdin if spec == "-" else open(spec))
    if isinstance(data, dict):
        data = data.get("inputs") or data.get("entries") or []
    if not isinstance(data, list):
        raise SystemExit("--batch must hold a JSON list, or an object with an 'inputs' list")
    return data


def entry_images(entry, work_dir, width, args):
    """One batch entry -> [(record dict, image path)]. 'images' means the caller
    already has stills; a bare path means extract."""
    if entry.get("images"):
        out = []
        for im in entry["images"]:
            if isinstance(im, str):
                out.append(({}, str(Path(im).expanduser())))
            else:
                path = im.get("path") or im.get("file")
                out.append(({k: v for k, v in im.items() if k not in ("path", "file")},
                            str(Path(path).expanduser())))
        return out
    src = Path(str(entry.get("path") or entry.get("file") or entry.get("id"))).expanduser()
    kind = entry.get("kind") or kind_of(src) or "photo"
    if kind == "video":
        if args.at:
            times, exact = [float(t) for t in args.at.split(",")], True
        else:
            dur = entry.get("duration_s") or duration_of(src)
            times = frame_times(dur, entry.get("frames") or args.frames or frame_count(dur))
            exact = not dur or dur / max(len(times), 1) < APPROX_SEEK_SPACING_S
        return [({"t": t}, str(p)) for t, p in extract_frames(src, times, work_dir, width, exact)]
    return [({}, str(extract_photo(src, work_dir, width)))]


def describe_entry(be, h, entry, images, per, args):
    out = {k: v for k, v in entry.items() if k not in ("images", "per", "frame_prompt", "clip_prompt", "kind")}
    out.setdefault("id", entry.get("id") or entry.get("path") or entry.get("file"))
    out["kind"] = entry.get("kind") or "photo"
    paths = [p for _, p in images]
    frame_prompt = entry.get("frame_prompt") or args.frame_prompt
    clip_prompt = entry.get("clip_prompt") or (
        args.clip_prompt if len(paths) > 1 or args.clip_prompt_given else args.image_prompt)
    if per in ("frame", "both"):
        out["frames"] = []
        for rec, p in images:
            r = dict(rec)
            r["text"] = be.describe(h, [p], frame_prompt)
            out["frames"].append(r)
    if per in ("clip", "both"):
        out["clip"] = be.describe(h, paths, clip_prompt.replace("{n}", str(len(paths))))
    return out


class Results:
    """Where finished inputs go: JSON Lines (or one object with --json), the
    counts and the progress line."""

    def __init__(self, args, sink, total):
        self.args, self.sink, self.total = args, sink, total
        self.done = self.failed = 0
        self.rows = []

    def add(self, out):
        if "error" in out:
            self.failed += 1
        else:
            self.done += 1
        if self.args.json:
            self.rows.append(out)
        else:
            self.sink.write(json.dumps(out, ensure_ascii=False) + "\n")
            self.sink.flush()
        progress(f"[{self.done + self.failed}/{self.total}] {out.get('seconds', 0):5.1f}s  "
                 f"{Path(str(out.get('id'))).name}  | {str(out.get('clip') or out.get('error') or '')[:90]}")

    def finish(self, meta, run_s):
        n = self.done + self.failed
        meta.update({"described": self.done, "failed": self.failed, "run_s": round(run_s, 1),
                     "s_per_input": round(run_s / max(n, 1), 2), "per": self.args.per})
        if self.args.json:
            json.dump({"results": self.rows, "_meta": meta}, self.sink, indent=1, ensure_ascii=False)
            self.sink.write("\n")
        else:
            self.sink.write(json.dumps({"_meta": meta}) + "\n")
        self.sink.flush()
        progress(f"done: {self.done} described, {self.failed} failed, {meta['s_per_input']} s/input"
                 + (f", peak {meta['peak_memory_gb']} GB" if meta.get("peak_memory_gb") else ""))
        return 1 if self.failed and not self.done else 0


@contextlib.contextmanager
def _sink(args):
    if not args.output:
        yield sys.stdout
        return
    with open(args.output, "w", encoding="utf-8") as f:
        yield f


def _prefetched(entries, prepare):
    """Yield (entry, future of prepare(entry)), getting the NEXT input's stills
    ready on one worker while the model is busy with this one."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        it = iter(entries)
        cur = next(it, None)
        fut = pool.submit(prepare, cur) if cur is not None else None
        while cur is not None:
            nxt = next(it, None)
            nxt_fut = pool.submit(prepare, nxt) if nxt is not None else None
            yield cur, fut
            cur, fut = nxt, nxt_fut


def _exit_on_signal(signum, _frame):
    sys.exit(128 + signum)


def main():
    global QUIET
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _exit_on_signal)
    ap = argparse.ArgumentParser(prog="vlm-describe", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", metavar="FILE", help="images, videos, directories or globs")
    ap.add_argument("--batch", metavar="JSON", help="JSON file of input entries, '-' for stdin")
    ap.add_argument("--backend", default=None, help=f"model backend (default: settings vision.backend, else {DEFAULT_BACKEND})")
    ap.add_argument("--per", choices=("clip", "frame", "both"), default="clip")
    ap.add_argument("--frames", type=int, help="frames per video (default: by length, 4-16)")
    ap.add_argument("--at", help="explicit timestamps, e.g. 0.3,5,12")
    ap.add_argument("--width", type=int, default=480, help="extracted frame width (default 480)")
    ap.add_argument("--recursive", action="store_true", help="recurse into directory arguments")
    ap.add_argument("--prompt", help="one prompt for every call")
    ap.add_argument("--frame-prompt", default=FRAME_PROMPT)
    ap.add_argument("--clip-prompt", help="{n} expands to the frame count")
    ap.add_argument("--image-prompt", default=IMAGE_PROMPT, help="for a single-still input instead of --clip-prompt")
    ap.add_argument("--frames-dir", help="keep extracted frames here (default: a temp dir, removed)")
    ap.add_argument("--json", action="store_true", help="one JSON object at exit instead of JSON Lines")
    ap.add_argument("-o", "--output", help="write there instead of stdout")
    ap.add_argument("--quiet", action="store_true", help="no per-input progress on stderr")
    ap.add_argument("--lock-timeout", type=float, default=LOCK_TIMEOUT_S, metavar="S",
                    help=f"seconds to wait for another run to finish before exiting 3 (default {LOCK_TIMEOUT_S})")
    ap.add_argument("--no-wait", action="store_true", help="exit 3 at once if another run holds the model")
    ap.add_argument("--check", action="store_true", help="print (JSON) whether local description can run here")
    args = ap.parse_args()
    QUIET = args.quiet
    name = backend_name(args.backend)

    if args.check:
        print(json.dumps(check(name), indent=2))
        return 0
    if not args.files and not args.batch:
        ap.error("nothing to describe: pass files or --batch (or --check)")

    args.clip_prompt_given = bool(args.clip_prompt or args.prompt)
    args.clip_prompt = args.clip_prompt or CLIP_PROMPT
    if args.prompt:
        args.frame_prompt = args.clip_prompt = args.image_prompt = args.prompt

    entries = load_batch(args.batch) if args.batch else []
    for p in expand_inputs(args.files, args.recursive):
        entries.append({"id": str(p), "path": str(p), "kind": kind_of(p) or "photo"})
    if not entries:
        ap.error("no media files matched")

    reexec_if_needed(name)
    import backends
    be = backends.get(name)
    lock = acquire_lock(0 if args.no_wait else args.lock_timeout, len(entries)) if getattr(be, "NEEDS_LOCK", True) else None

    tmp = None
    if args.frames_dir:
        work_dir = Path(args.frames_dir).expanduser()
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.mkdtemp(prefix="vlm-describe-")
        work_dir = Path(tmp)
        atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    counter = itertools.count()

    def prepare(entry):
        d = work_dir / f"{next(counter):06d}" if tmp else work_dir
        d.mkdir(exist_ok=True)
        return d, entry_images(entry, d, args.width, args)

    with _sink(args) as sink:
        t0 = time.time()
        h = be.load()
        meta = {"backend": name, "load_s": round(time.time() - t0, 1)}
        progress(f"{len(entries)} input(s), backend {name}, loaded in {meta['load_s']}s")
        res, t_run = Results(args, sink, len(entries)), time.time()
        for entry, fut in _prefetched(entries, prepare):
            t1 = time.time()
            try:
                d, images = fut.result()
                per = entry.get("per") or args.per
                if len(images) < 2 and per == "both":
                    per = "clip"
                out = describe_entry(be, h, entry, images, per, args)
                out["seconds"] = round(time.time() - t1, 2)
                if tmp:
                    shutil.rmtree(d, ignore_errors=True)
            except Exception as e:  # one bad input must not stop the run
                out = {"id": entry.get("id") or entry.get("path") or entry.get("file"),
                       "error": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t1, 2)}
            res.add(out)
        for fn in ("info", "stats"):
            try:
                meta.update(getattr(be, fn)())
            except Exception:
                pass
        try:
            be.unload(h)
        except Exception:
            pass
        if lock is not None:
            release_lock(lock)
        rc = res.finish(meta, time.time() - t_run)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
