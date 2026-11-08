#!/usr/bin/env python3
"""End-to-end test of archive_project.py on a synthetic project (needs ffmpeg).

Builds a fake project (footage, proxies, caches, drafts, a recipe, a fake .drp)
in a temporary folder with its own settings file (VES_SETTINGS), then runs a
scan, a clean, and the lean, keep and recipe archives, checking what survives.
Your real settings and projects are never touched.

    python3 selftest.py              # temp folder, removed afterwards
    python3 selftest.py --root DIR   # build in DIR and leave everything there to inspect

Run it after editing rules.json. Exit 0 when every check passes.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "archive_project.py"
FAILS = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def ff(*args):
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit("ffmpeg is needed for the self-test (it makes the fake clips)")
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def make_video(path: Path, seconds=2, size="320x180", color=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    src = f"color=c={color}:s={size}:d={seconds}" if color else f"testsrc2=s={size}:d={seconds}"
    ff("-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"sine=f=440:d={seconds}",
       "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path))


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fake_drp(path: Path, project: Path, plain: str, blob: str):
    """A minimal stand-in for a Resolve export: zip of XML, one path in plain text and one
    in a hex FieldsBlob holding a zstd frame (plain bytes if zstd is not installed)."""
    payload = (b"\x00\x01junk" + str(project / blob).encode() + b"\x00more")
    z = shutil.which("zstd")
    if z:
        payload = b"\x10\x00\x00\x00" + subprocess.run([z, "-q", "-c"], input=payload,
                                                       capture_output=True, check=True).stdout
    xml = (f'<?xml version="1.0"?><SyncData><MediaPoolItem><FilePath>{project / plain}</FilePath>'
           f'<FieldsBlob>{binascii.hexlify(payload).decode()}</FieldsBlob></MediaPoolItem></SyncData>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("project.xml", xml)


def build_project(root: Path, name: str, elsewhere: Path) -> Path:
    p = root / "projects" / name
    make_video(p / "footage" / "clipA.mp4", 3)
    write(p / "footage" / "clipA.transcript.json", json.dumps({"segments": [], "language": "en"}))
    make_video(p / "footage" / "clipB.mp4", 2, color="blue")          # never used anywhere
    make_video(p / "footage" / "clipC.mp4", 2, color="green")         # used by the Resolve export only
    make_video(p / "footage" / "clipA_proxy.mov", 1, size="160x90")   # proxy with its original present
    make_video(p / "footage" / "proxies" / "clipC.mov", 1, size="160x90")      # proxy folder
    make_video(p / "footage" / "proxies" / "clipLinked.mov", 1, size="160x90")  # proxy the .drp still uses
    ff("-f", "lavfi", "-i", "sine=f=220:d=3", str(_mk(p / "audio" / "music.wav")))
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180", "-frames:v", "1", str(_mk(p / "graphics" / "title.png")))
    make_video(p / "output" / "final.mp4", 3)
    write(p / "output" / "final.srt", "1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    ff("-f", "lavfi", "-i", "testsrc2=s=1280x720", "-frames:v", "1",
       str(_mk(p / "output" / "thumbnails" / "thumb-1.jpg")))
    make_video(p / "output" / "drafts" / "final-draft-1.mp4", 2)
    write(p / "output" / "drafts" / "final-draft-1.review" / "notes.json", json.dumps({"notes": []}))
    make_video(p / "work" / "talking-head" / "segments" / "seg001.mp4", 1)
    make_video(p / "work" / "motion" / "out" / "card.mov", 1)          # the recipe plays it
    make_video(p / "footage" / "clipA_aroll_draft" / "preview.mp4", 1)
    ff("-f", "lavfi", "-i", "sine=f=330:d=2", str(_mk(p / "footage" / "clipA_aroll_draft" / "audio_16k.wav")))
    write(p / "footage" / "clipA_aroll_draft" / "edit.md", "cut notes")
    write(p / "footage" / "clipA.aroll.tb.json", json.dumps([{"start": 0, "duration": 3, "operation": "keep"}]))
    (p / "CacheClip").mkdir(parents=True, exist_ok=True)
    (p / "CacheClip" / "render.bin").write_bytes(os.urandom(4096))
    (p / ".DS_Store").write_bytes(b"\0" * 64)
    make_video(elsewhere / "stock" / "skyline.mp4", 1, color="gray")
    old = {"schema": "talking-head-recipe/1", "aroll": str(p / "footage" / "clipA.mp4")}
    write(p / "work" / "talking-head" / "recipe_v1.json", json.dumps(old))
    recipe = {"schema": "talking-head-recipe/1",
              "aroll": [{"src": str(p / "footage" / "clipA.mp4"), "in": 0, "out": 3}],
              "broll": [{"src": str(p / "work" / "motion" / "out" / "card.mov"), "at": 1},
                        {"src": str(elsewhere / "stock" / "skyline.mp4"), "at": 2}],
              "music": "audio/music.wav", "title": str(p / "graphics" / "title.png")}
    write(p / "work" / "talking-head" / "recipe_v2.json", json.dumps(recipe, indent=2))
    fake_drp(p / "resolve" / f"{name}.drp", p, "footage/clipC.mp4", "footage/proxies/clipLinked.mov")
    return p


def _mk(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def tree_hash(p: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(x for x in p.rglob("*") if x.is_file()):
        st = f.stat()
        h.update(f"{f.relative_to(p)}|{st.st_size}|{st.st_mtime}".encode())
    return h.hexdigest()


def run(env, *args, expect=None):
    r = subprocess.run([sys.executable, "-B", str(TOOL), *args], env=env, capture_output=True, text=True)
    if expect is not None and r.returncode != expect:
        print(r.stderr[-3000:])
    try:
        out = json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        out = {"_raw": r.stdout}
    return r.returncode, out, r.stderr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="build here and keep the results")
    a = ap.parse_args()
    root = Path(a.root).resolve() if a.root else Path(tempfile.mkdtemp(prefix="archive-selftest-"))
    if root.exists() and any(root.iterdir()) and a.root:
        sys.exit(f"{root} is not empty; pick an empty folder")
    root.mkdir(parents=True, exist_ok=True)
    elsewhere = root / "elsewhere"
    archive = root / "archive-drive"
    settings_file = root / "settings.json"
    settings_file.write_text(json.dumps({
        "paths": {"projects_dir": str(root / "projects"), "archive_dir": str(archive),
                  "finals_dir": None, "broll_library_dir": None, "cache_dir": str(root / "cache")},
        "editor": {"nle": "resolve-studio"}, "archive": {"default_mode": "lean"},
        "nas": {"enabled": False}}))
    env = {k: v for k, v in os.environ.items() if not k.startswith("VES_")}
    env["VES_SETTINGS"] = str(settings_file)
    print(f"self-test in {root}")

    # 1. scan + clean
    print("\n[scan / clean]")
    p = build_project(root, "demo-review", elsewhere)
    before = tree_hash(p)
    rc, out, err = run(env, "scan", "demo-review", expect=0)
    cats = {c["category"]: c for c in out.get("cruft", [])}
    check(rc == 0, "scan runs")
    for c in ("os-metadata", "render-cache", "proxies", "aroll-draft-work", "drafts", "scratch"):
        check(c in cats, f"scan finds {c}")
    check(out.get("finals") == ["output/final.mp4"], "scan finds the final")
    check("work/talking-head/recipe_v2.json" in out.get("recipes", []), "scan finds the newest recipe")
    check(any(x.endswith("skyline.mp4") for x in out.get("external_references", [])), "scan lists the external reference")
    (p / "notes-empty-folder").mkdir()
    rc, out, err = run(env, "clean", str(p), expect=0)
    plan = json.loads(Path(out["plan"]).read_text())
    gone = {d["rel"] for d in plan["deletes"]}
    check(tree_hash(p) == before, "dry runs change nothing")
    check("footage/clipA_proxy.mov" in gone and "footage/proxies/clipC.mov" in gone, "proxies planned")
    check("footage/proxies/clipLinked.mov" not in gone, "a proxy the .drp still uses is kept (reference gate)")
    check("work/motion/out/card.mov" not in gone, "a work/ file the recipe plays is kept")
    check("work/talking-head/segments/seg001.mp4" in gone, "work/ scratch renders planned")
    check("output/drafts/final-draft-1.mp4" in gone, "draft render planned")
    check("output/drafts/final-draft-1.review/notes.json" not in gone, "review notes kept")
    check("footage/clipA_aroll_draft/edit.md" not in gone and "footage/clipA_aroll_draft/audio_16k.wav" in gone,
          "a-roll draft: audio goes, notes stay")
    check(not any(r.startswith("footage/clip") and r.endswith(".mp4") and "/" not in r[8:] for r in gone),
          "camera originals are never default cruft")
    check(Path(out["list"]).is_file(), "plain-text deletion list written")
    rc, _, _ = run(env, "execute", out["plan"])
    check(rc == 2 and (p / "CacheClip" / "render.bin").exists(), "execute without --yes does nothing")
    (p / "output" / "drafts" / "final-draft-1.mp4").write_bytes(b"changed")   # edited after the plan
    rc, res, err = run(env, "execute", out["plan"], "--yes", expect=0)
    check(rc == 0 and not (p / "CacheClip").exists() and not (p / "footage" / "clipA_proxy.mov").exists(),
          "clean execute deletes the cruft")
    check((p / "output" / "drafts" / "final-draft-1.mp4").exists() and res.get("skipped_changed"),
          "a file changed since the plan is skipped")
    check((p / "footage" / "proxies" / "clipLinked.mov").exists() and (p / "work" / "motion" / "out" / "card.mov").exists(),
          "referenced files survive the clean")
    check((p / "notes-empty-folder").is_dir() and not (p / "work" / "talking-head" / "segments").exists(),
          "clean removes only the folders it emptied")
    rc, out, err = run(env, "clean", str(p), "--category", "unused-media", expect=0)
    gone = {d["rel"] for d in json.loads(Path(out["plan"]).read_text())["deletes"]}
    check("footage/clipB.mp4" in gone, "unused-media (opt-in) finds the unused take")
    check(not gone & {"footage/clipA.mp4", "footage/clipC.mp4", "output/final.mp4",
                      "output/thumbnails/thumb-1.jpg", "graphics/title.png"},
          "unused-media spares recipe/.drp-used clips, finals and thumbnails")
    check("audio/music.wav" not in gone, "audio is never unused-media")

    # 2. lean
    print("\n[lean]")
    lib = root / "broll-library"
    lib.mkdir()
    s = json.loads(settings_file.read_text())
    s["paths"]["broll_library_dir"] = str(lib)
    settings_file.write_text(json.dumps(s))
    rc, out, err = run(env, "archive", "demo-review")
    check(rc == 1 and any("b-roll" in b for b in out.get("blockers", [])), "lean asks for the b-roll harvest first")
    rc, out, err = run(env, "archive", "demo-review", "--broll", "skip", expect=0)
    check(rc == 0, "lean dry run is clean")
    rc, res, err = run(env, "execute", out["plan"], "--yes", expect=0)
    fin = archive / "final-videos" / "demo-review"
    check((fin / "final.mp4").is_file() and (fin / "final.srt").is_file(), "final + its sidecar in final-videos")
    check((fin / "thumbnails" / "thumb-1.jpg").is_file(), "thumbnail kept")
    check((fin / "ARCHIVE-MANIFEST.json").is_file() and (archive / "archive-log.jsonl").is_file(),
          "manifest + archive log written")
    check(not p.exists(), "project folder deleted")
    check((elsewhere / "stock" / "skyline.mp4").is_file(), "nothing outside the project deleted")

    # 3. keep (+ a symlinked folder that points outside the project)
    print("\n[keep]")
    p = build_project(root, "demo-keep", elsewhere)
    (root / "outside-target").mkdir()
    (root / "outside-target" / "precious.txt").write_text("do not delete")
    os.symlink(root / "outside-target", p / "linked-folder")
    rc, out, err = run(env, "archive", "demo-keep", "--mode", "keep", "--checksum", expect=0)
    check(rc == 0, "keep dry run is clean")
    rc, res, err = run(env, "execute", out["plan"], "--yes", expect=0)
    k = archive / "demo-keep"
    check(rc == 0 and (k / "footage" / "clipA.mp4").is_file() and (k / "resolve" / "demo-keep.drp").is_file(),
          "kept project has footage and the .drp")
    check(not (k / "CacheClip").exists() and not (k / "footage" / "clipA_proxy.mov").exists()
          and not (k / "work" / "talking-head" / "segments").exists(), "kept project carries no cruft")
    check((k / "footage" / "proxies" / "clipLinked.mov").is_file(), "referenced proxy travels with it")
    r2 = json.loads((k / "work" / "talking-head" / "recipe_v2.json").read_text())
    srcs = [x["src"] for x in r2["aroll"] + r2["broll"]] + [r2["title"]]
    check(all(x.startswith(str(k)) for x in srcs), "recipe repointed at the archive (external file bundled)")
    check(all(Path(x).is_file() for x in srcs), "every repointed recipe path exists")
    check((archive / "final-videos" / "demo-keep" / "final.mp4").is_file(), "keep also files the final")
    check(not p.exists(), "local folder deleted")
    check((root / "outside-target" / "precious.txt").is_file(), "symlink target outside the project untouched")

    # 4. recipe
    print("\n[recipe]")
    p = build_project(root, "demo-recipe", elsewhere)
    rc, out, err = run(env, "archive", "demo-recipe", "--mode", "recipe", "--broll", "done", expect=0)
    check(rc == 0, "recipe dry run is clean")
    rc, res, err = run(env, "execute", out["plan"], "--yes", expect=0)
    r = archive / "demo-recipe"
    check((r / "footage" / "clipA.mp4").is_file() and (r / "footage" / "clipA.transcript.json").is_file(),
          "camera original + its sidecar archived")
    check(not (r / "footage" / "clipB.mp4").exists() and not (r / "footage" / "clipC.mp4").exists(),
          "footage the recipe does not use is not kept")
    check((r / "audio" / "music.wav").is_file() and (r / "work" / "motion" / "out" / "card.mov").is_file(),
          "music (relative path) and the motion card archived")
    rr = json.loads((r / "work" / "talking-head" / "recipe_v2.json").read_text())
    srcs = [x["src"] for x in rr["aroll"] + rr["broll"]] + [rr["title"]]
    check(all(x.startswith(str(r)) and Path(x).is_file() for x in srcs), "recipe points at the archived media")
    check((archive / "final-videos" / "demo-recipe" / "recipe_v2.json").is_file()
          and (archive / "final-videos" / "demo-recipe" / "final.mp4").is_file(), "master + recipe side by side")
    check(not p.exists(), "local folder deleted")
    moved = root / "moved-archive"
    shutil.copytree(r, moved)
    rc, out, err = run(env, "repoint", str(moved), expect=0)
    rr = json.loads((moved / "work" / "talking-head" / "recipe_v2.json").read_text())
    check(os.path.realpath(rr["aroll"][0]["src"]).startswith(os.path.realpath(moved) + os.sep)
          and Path(rr["aroll"][0]["src"]).is_file(), "repoint re-aims a moved archive")

    # 5. guards
    print("\n[guards]")
    p = build_project(root, "demo-guard", elsewhere)
    s = json.loads(settings_file.read_text())
    s["nas"] = {"enabled": True, "mount_path": str(root / "nas-not-mounted")}
    s["paths"]["archive_dir"] = str(root / "nas-not-mounted" / "archive")
    settings_file.write_text(json.dumps(s))
    rc, out, err = run(env, "archive", "demo-guard", "--broll", "skip")
    check(rc == 1 and any("not mounted" in b for b in out.get("blockers", [])), "an unmounted NAS blocks")
    s["nas"] = {"enabled": False}
    s["paths"]["archive_dir"] = str(archive)
    settings_file.write_text(json.dumps(s))
    rc, out, err = run(env, "archive", "demo-guard", "--mode", "keep")
    check(rc == 0, "keep with a .drp present passes")
    os.remove(p / "resolve" / "demo-guard.drp")
    rc, out, err = run(env, "archive", "demo-guard", "--mode", "keep")
    check(rc == 1 and any(".drp" in b for b in out.get("blockers", [])), "keep without a .drp blocks (Resolve user)")
    shutil.rmtree(p / "output")
    rc, out, err = run(env, "archive", "demo-guard", "--broll", "skip")
    check(rc == 1 and any("no final" in b for b in out.get("blockers", [])), "lean without a final blocks")
    rc, out, err = run(env, "clean", str(p), expect=0)
    plan = json.loads(Path(out["plan"]).read_text())
    plan["deletes"].append({"path": str(elsewhere / "stock" / "skyline.mp4"), "rel": "../x", "size": 0,
                            "mtime": 0, "category": "evil"})
    Path(out["plan"]).write_text(json.dumps(plan))
    rc, res, err = run(env, "execute", out["plan"], "--yes", expect=0)
    check((elsewhere / "stock" / "skyline.mp4").is_file() and res.get("left_behind"),
          "a planned path outside the project is never deleted")

    print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED'}")
    if not a.root:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"results left in {root}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
