#!/usr/bin/env python3
"""Archive a finished video project, or clean the regenerable cruft out of it.

Every command except `execute` is read-only: it writes a plan (JSON) and a
plain-text list of every file that would be copied and deleted. `execute`
carries out exactly that plan, and only with --yes (the user approved the list).

  scan    PROJECT
          Report: cruft per category with sizes, what the references protect,
          finals, thumbnails, recipes, Resolve exports. Changes nothing.

  clean   PROJECT [--category NAME ...] [--skip NAME ...]
          Plan to delete the cruft (the categories marked default in rules.json,
          or exactly the --category ones). The project stays where it is.

  archive PROJECT [--mode lean|keep|recipe] [--final FILE ...] [--recipe FILE ...]
          [--broll done|skip] [--no-drp] [--dest DIR] [--checksum]
          lean   (settings archive.default_mode, default): finals + thumbnails
                 (+ the rules.json "extras") go to paths.finals_dir/<project>/,
                 then the whole project folder is deleted.
          keep   the cleaned project folder (no cruft) is copied to
                 paths.archive_dir/<project>/, its JSON recipes repointed there,
                 finals + thumbnails also go to finals_dir, then the local folder
                 is deleted.
          recipe for ffmpeg-built videos: finals + thumbnails to finals_dir, and
                 to archive_dir/<project>/ the recipe(s), every file they use
                 (camera originals, music, graphics, with their sidecars) and
                 the project's small text files; recipes repointed there. Then
                 the local folder is deleted.

  execute PLAN.json --yes [--checksum]
          Copy, verify every copy (size, and SHA-256 with --checksum), repoint
          recipes, write ARCHIVE-MANIFEST.json and the archive log, and only
          then delete the planned files (each re-checked: a file that changed
          since the plan is skipped). Never deletes outside the project folder:
          a plan whose project folder fails the dry run's guards (a drive, a home
          folder, a folder holding your projects...) or that names a file outside
          it is refused before anything is copied or deleted.

Output: the human report on stderr, a JSON summary on stdout.
Exit codes: 0 ok, 1 blocked (the plan lists why), 2 usage, 4 a setting is unset.
"""
from __future__ import annotations

import argparse
import binascii
import datetime as dt
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE.parents[3] / "tools"))
from vidkit import settings  # noqa: E402

RULES_PATH = SKILL_DIR / "rules.json"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
JSON_SCAN_LIMIT = 20 * 1024 * 1024     # JSON files bigger than this are not read for references
TEXT_KEEP_LIMIT = 5 * 1024 * 1024       # recipe mode keeps text files up to this size
MODES = ("lean", "keep", "recipe")


# ---- small helpers -----------------------------------------------------------

def log(*a):
    print(*a, file=sys.stderr, flush=True)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def load_rules() -> dict:
    with open(RULES_PATH, encoding="utf-8") as f:
        rules = json.load(f)
    for k in ("video_exts", "audio_exts", "image_exts", "text_exts"):
        rules[k] = {e.lower() for e in rules.get(k, [])}
    return rules


def placeholders() -> dict:
    return {k: settings.layout(k).strip("/").replace("\\", "/")
            for k in ("footage", "audio", "graphics", "drafts", "finals", "work")}


def subst(pattern: str, ph: dict) -> str:
    for k, v in ph.items():
        pattern = pattern.replace("{" + k + "}", v)
    return pattern


def match_any(text: str, patterns) -> bool:
    t = text.lower()
    return any(fnmatch.fnmatchcase(t, p.lower()) for p in patterns or ())


def kind_of(name: str, rules: dict) -> str:
    ext = os.path.splitext(name)[1].lower()
    for k in ("video", "audio", "image", "text"):
        if ext in rules[k + "_exts"]:
            return k
    return "other"


def kind_ok(kind: str, only) -> bool:
    if not only:
        return True
    allowed = {"media": {"video", "audio", "image"}}.get(only, set(only.split("+")))
    return kind in allowed


def is_under(path: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(os.path.abspath(root))
        return True
    except ValueError:
        return False


def real_under(path: Path, root: Path) -> bool:
    """True when `path` (not following a final symlink) sits inside `root` for real."""
    parent = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    r = os.path.realpath(root)
    return parent == r or parent.startswith(r.rstrip(os.sep) + os.sep)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- walking and classifying ------------------------------------------------

def walk(project: Path) -> list:
    """[{rel, size, mtime, link}] for every file (symlinks are listed, never followed)."""
    out = []
    for root, dnames, fnames in os.walk(project):
        dnames.sort()
        links = [d for d in dnames if os.path.islink(os.path.join(root, d))]
        dnames[:] = [d for d in dnames if d not in links]
        for fn in sorted(fnames + links):
            p = Path(root) / fn
            try:
                st = os.lstat(p)
            except OSError:
                continue
            out.append({"rel": p.relative_to(project).as_posix(), "size": st.st_size,
                        "mtime": st.st_mtime, "link": os.path.islink(p)})
    return out


def _stem_regex(pattern: str):
    """'*_proxy.*' -> regex whose group 1 is the original's stem."""
    parts = pattern.lower().split("*")
    rx = "(.+)".join([re.escape(parts[0]), re.escape(parts[1])]) if len(parts) > 1 else re.escape(parts[0])
    if len(parts) > 2:
        rx += ".*".join([""] + [re.escape(p) for p in parts[2:]])
    return re.compile("^" + rx + "$")


def classify(f: dict, rules: dict, ph: dict, media_stems: set, referenced) -> tuple:
    """(category, why) for a file, or (None, None) when no cruft rule matches."""
    rel = f["rel"]
    parts = rel.split("/")
    name = parts[-1]
    kind = kind_of(name, rules)
    for c in rules["cruft"]:
        if c.get("keep_exts") == "text" and kind == "text":
            continue
        if not kind_ok(kind, c.get("only")):
            continue
        if c.get("not_paths") and match_any(rel, [subst(p, ph) for p in c["not_paths"]]):
            continue
        hit = False
        if c.get("files") and match_any(name, c["files"]):
            hit = True
        if not hit and c.get("dirs") and any(match_any(d, c["dirs"]) for d in parts[:-1]):
            hit = True
        if not hit and c.get("paths") and match_any(rel, [subst(p, ph) for p in c["paths"]]):
            hit = True
        if not hit and c.get("files_with_original"):
            for pat in c["files_with_original"]:
                m = _stem_regex(pat).match(name.lower())
                if m and m.group(1) in media_stems:
                    hit = True
                    break
        if not hit and c.get("unreferenced") and referenced is not None and not referenced(rel):
            hit = True
        if hit:
            return c["name"], c.get("why", "")
    return None, None


def select(files: list, spec: dict, rules: dict, ph: dict) -> list:
    if not spec or not spec.get("include"):
        return []
    inc = [subst(p, ph) for p in spec["include"]]
    exc = [subst(p, ph) for p in spec.get("exclude", [])]
    out = []
    for f in files:
        if f["link"] or not kind_ok(kind_of(f["rel"], rules), spec.get("only")):
            continue
        if match_any(f["rel"], inc) and not match_any(f["rel"], exc):
            out.append(f)
    return out


# ---- references: what a Resolve export or a recipe still points at --------------

def _zstd(payload: bytes):
    try:
        import zstandard  # type: ignore
        return zstandard.ZstdDecompressor().decompressobj().decompress(payload)
    except ImportError:
        pass
    exe = shutil.which("zstd")
    if not exe:
        return None
    return subprocess.run([exe, "-d", "-c", "--no-check"], input=payload, capture_output=True).stdout


class Refs:
    """Project files that an editor file (a .drp export or a JSON recipe) points at."""

    def __init__(self, project: Path, files: list):
        self.project = project
        self.name = project.name
        self.rels = {f["rel"] for f in files}
        self.rel_lower = {r.lower(): r for r in self.rels}
        self.dirs = set()
        for r in self.rels:
            p = r.rsplit("/", 1)[0] if "/" in r else ""
            while p and p not in self.dirs:
                self.dirs.add(p)
                p = p.rsplit("/", 1)[0] if "/" in p else ""
        self.by = {}            # rel (file or dir) -> set of editor files
        self.external = {}      # abs path outside the project -> set of editor files
        self.missing = {}       # abs path inside the project that no longer exists -> editor files
        self.sources = []       # editor files read
        self.warnings = []
        self.roots = {os.path.abspath(project), os.path.realpath(project)}

    def _add(self, rel: str, src: str):
        self.by.setdefault(rel, set()).add(src)

    def holders(self, rel: str) -> set:
        out = set(self.by.get(rel, ()))
        p = rel
        while "/" in p:
            p = p.rsplit("/", 1)[0]
            out |= self.by.get(p, set())
        return out

    def referenced(self, rel: str) -> bool:
        return bool(self.holders(rel))

    # a path-ish string from any editor file
    def take(self, s: str, src: str, base_dir: Path | None = None, external: bool = True):
        s = s.strip()
        if not s or len(s) > 1000 or ("/" not in s and "\\" not in s):
            return
        if s.startswith("file://"):
            s = s[7:]
        s = s.replace("\\", "/")
        if s.startswith("~"):
            s = os.path.expanduser(s)
        absolute = s.startswith("/") or re.match(r"^[A-Za-z]:/", s) is not None
        if absolute:
            for root in self.roots:
                r = root.replace("\\", "/").rstrip("/") + "/"
                if s.startswith(r):
                    if not self._take_rel(s[len(r):], src) and os.path.splitext(s)[1]:
                        self.missing.setdefault(s, set()).add(src)
                    return
            marker = "/" + self.name + "/"
            if marker in s and self._take_rel(s.split(marker, 1)[1], src):
                return
            if external and os.path.splitext(s)[1]:
                self.external.setdefault(s, set()).add(src)
            return
        for b in ([base_dir] if base_dir else []) + [self.project]:
            cand = os.path.normpath(os.path.join(str(b), s))
            if is_under(Path(cand), self.project):
                if self._take_rel(Path(cand).relative_to(self.project).as_posix(), src):
                    return

    def _take_rel(self, rel: str, src: str) -> bool:
        rel = rel.strip("/")
        hit = self.rel_lower.get(rel.lower()) or (rel if rel in self.dirs else None)
        if hit:
            self._add(hit, src)
            return True
        return False

    def read_json(self, path: Path):
        src = path.relative_to(self.project).as_posix()
        try:
            if path.stat().st_size > JSON_SCAN_LIMIT:
                return
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return
        n0 = sum(len(v) for v in self.by.values())

        def walk_json(x):
            if isinstance(x, dict):
                for v in x.values():
                    walk_json(v)
            elif isinstance(x, list):
                for v in x:
                    walk_json(v)
            elif isinstance(x, str):
                self.take(x, src, base_dir=path.parent)
        walk_json(data)
        if sum(len(v) for v in self.by.values()) > n0 or any(src in v for v in self.external.values()):
            self.sources.append(src)

    def read_drp(self, path: Path):
        """A Resolve .drp export: a zip of XML; media paths sit in plain text and in
        hex-encoded, zstd-compressed field blobs."""
        src = path.relative_to(self.project).as_posix()
        try:
            zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError):
            self.warnings.append(f"{src}: not a readable .drp (zip) file")
            return
        self.sources.append(src)
        blobs = []
        with zf:
            for n in zf.namelist():
                if n.lower().endswith(".xml"):
                    data = zf.read(n)
                    blobs.append(data)
                    for m in re.finditer(rb"<FieldsBlob[^>]*>([0-9a-fA-F]+)</FieldsBlob>", data):
                        try:
                            raw = binascii.unhexlify(m.group(1))
                        except binascii.Error:
                            continue
                        i = raw.find(ZSTD_MAGIC)
                        if i < 0:
                            blobs.append(raw)
                            continue
                        out = _zstd(raw[i:])
                        if out is None:
                            msg = ("zstd is not available, so the compressed parts of .drp files "
                                   "were not read (install it with your package manager, e.g. "
                                   "`brew install zstd`, or `python3 -m pip install zstandard`); "
                                   "files they reference may be missed by the reference gate")
                            if msg not in self.warnings:
                                self.warnings.append(msg)
                            continue
                        blobs.append(out)
        rx = re.compile(re.escape(self.name.encode("utf-8")) + rb"[/\\]([^\x00-\x1f\"<>|*?]{1,400})")
        for blob in blobs:
            for m in rx.finditer(blob):
                tail = m.group(1).decode("utf-8", "replace").replace("\\", "/")
                for i in range(len(tail), 0, -1):          # longest project path it starts with
                    if self._take_rel(tail[:i], src):
                        break


def build_refs(project: Path, files: list) -> Refs:
    refs = Refs(project, files)
    for f in files:
        rel = f["rel"]
        if f["link"]:
            continue
        low = rel.lower()
        if low.endswith(".drp"):
            refs.read_drp(project / rel)
        elif low.endswith(".json") and not low.endswith(".transcript.json") and "/.review/" not in "/" + low:
            refs.read_json(project / rel)
    return refs


def find_recipes(project: Path, files: list, ph: dict, explicit=None) -> list:
    """Newest version of each recipe family: JSON files named *recipe* (or with a
    'schema'/'kind' containing 'recipe'), e.g. work/talking-head/recipe_v3.json, and
    home-video's cut lists (schema home-video-cut/1: work/cut_v3.json, cut_final.json wins)."""
    if explicit:
        out = []
        for r in explicit:
            p = Path(r).expanduser()
            p = p if p.is_absolute() else (project / r)
            if not p.is_file():
                sys.exit(f"recipe not found: {p}")
            out.append(p.resolve().relative_to(project.resolve()).as_posix())
        return out
    fams = {}
    for f in files:
        rel = f["rel"]
        low = rel.lower()
        if not low.endswith(".json") or "/.review/" in "/" + low or low.endswith(".transcript.json"):
            continue
        is_recipe = "recipe" in low.rsplit("/", 1)[-1]
        if not is_recipe and f["size"] < 2 * 1024 * 1024:
            try:
                head = json.loads((project / rel).read_text(encoding="utf-8"))
                tag = str(head.get("schema", "")) + str(head.get("kind", "")) if isinstance(head, dict) else ""
                is_recipe = "recipe" in tag.lower() or tag.lower().startswith("home-video-cut/")
            except (OSError, ValueError, UnicodeDecodeError):
                pass
        if not is_recipe:
            continue
        m = re.match(r"^(.*?)[_.-]?(?:v(\d+)|final)\.json$", rel, re.I)
        fam, n = (m.group(1), int(m.group(2)) if m.group(2) else float("inf")) if m else (rel, 0)
        if fam not in fams or n > fams[fam][0]:
            fams[fam] = (n, rel)
    return sorted(v[1] for v in fams.values())


# ---- destinations: local folder, external drive, NAS ------------------------------

MOUNT_PARENTS = {"/Volumes", "/media", "/mnt", "/run/media"}


def mount_hint() -> str:
    s = platform.system()
    if s == "Darwin":
        return ("Mount it: in Finder press Cmd+K (Go > Connect to Server), type "
                "smb://<your-nas-name>/<share>, sign in (let the Keychain remember the "
                "password: never put it in this repo), then re-run.")
    if s == "Windows":
        return ("Mount it: File Explorer > This PC > Map network drive, pick the NAS share, "
                "tick 'Reconnect at sign-in', then re-run.")
    return ("Mount it: your file manager's 'Other Locations' > Connect to Server "
            "(smb://<your-nas-name>/<share>), or `gio mount smb://<your-nas-name>/<share>`, then re-run.")


def check_destination(dest: Path, role: str, need_bytes: int, blockers: list, warnings: list,
                      project: Path):
    nas_on = settings.get("nas.enabled", default=False)
    mount = settings.get_path("nas.mount_path")
    if nas_on and mount and is_under(dest, mount):
        ok = mount.is_dir() and (os.path.ismount(str(mount)) or any(mount.iterdir()))
        if not ok:
            blockers.append(f"{role}: the NAS is not mounted at {mount}. {mount_hint()}")
            return
    anchor = Path(os.path.abspath(dest))
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    missing_volume = (anchor != Path(os.path.abspath(dest)) and
                      (str(anchor) in MOUNT_PARENTS or anchor == anchor.parent or
                       str(anchor.parent) in MOUNT_PARENTS and not os.path.ismount(str(anchor))))
    if missing_volume:
        blockers.append(f"{role}: {dest} is not reachable (drive unplugged or share not mounted?). "
                        f"Connect it and re-run. {mount_hint() if nas_on else ''}".strip())
        return
    if not os.access(anchor, os.W_OK):
        blockers.append(f"{role}: no permission to write in {anchor}")
        return
    free = shutil.disk_usage(anchor).free
    if need_bytes > free * 0.98:
        blockers.append(f"{role}: needs {human(need_bytes)} but {anchor} has {human(free)} free")
    try:
        if os.stat(anchor).st_dev == os.stat(project).st_dev:
            warnings.append(f"{role}: {dest} is on the same drive as the project. That is fine for "
                            f"tidying up, but this drive is then the only copy: back it up to another "
                            f"drive or the cloud too (the 3-2-1 rule).")
    except OSError:
        pass


# ---- the plan ---------------------------------------------------------------

HOME_FOLDERS = {"desktop", "documents", "downloads", "movies", "music", "pictures", "videos", "public", "library"}
SETTINGS_ROOTS = ("paths.projects_dir", "paths.inbox_dir", "paths.archive_dir", "paths.finals_dir",
                  "paths.broll_library_dir", "paths.home_videos_dir", "paths.music_dir")


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def project_guard(p: Path):
    """Why the (resolved) folder `p` must never be treated as one project folder, or None.
    Archiving deletes the folder it is given, so a drive, the home folder, a standard
    home folder or a folder holding the projects / archive / library is refused."""
    home = Path.home().resolve()
    if p == Path(p.anchor) or len(p.parts) < 3:
        return "it is a drive or a top-level folder"
    if _same(p, home) or _same(p, home.parent) or _same(p.parent, home.parent):
        return "it is a home folder"
    if _same(p.parent, home) and p.name.lower() in HOME_FOLDERS:
        return f"it is your {p.name} folder"
    if (str(p.parent) in MOUNT_PARENTS or str(p.parent.parent) in ("/media", "/run/media")
            or os.path.ismount(str(p))):
        return "it is a whole drive (a mount point)"
    for key in SETTINGS_ROOTS:
        r = settings.get_path(key)
        if r and is_under(r.resolve(), p):
            return f"it is or holds your {key} folder ({r})"
    return None


def resolve_project(arg: str) -> Path:
    p = settings.project_dir(arg)
    if not p.is_dir():
        sys.exit(f"not a folder: {p}")
    if p.is_symlink():
        sys.exit(f"{p} is a symbolic link: pass the real folder")
    p = p.resolve()
    why = project_guard(p)
    if why:
        sys.exit(f"refusing to treat {p} as a project folder: {why}. Pass the one project's own folder.")
    return p


def scan_project(project: Path, rules: dict) -> dict:
    ph = placeholders()
    files = walk(project)
    refs = build_refs(project, files)
    have_refs = bool(refs.sources)
    media_stems = set()
    for f in files:
        if kind_of(f["rel"], rules) in ("video", "audio"):
            stem = f["rel"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
            media_stems.add(stem)
    rows = []
    for f in files:
        cat, why = classify(f, rules, ph, media_stems, refs.referenced if have_refs else None)
        # a proxy-named file is not its own original
        holders = sorted(refs.holders(f["rel"]))
        rows.append(dict(f, category=cat, held_by=holders))
    return {"files": rows, "refs": refs, "have_refs": have_refs, "ph": ph}


def category_table(rows: list, rules: dict, chosen: set) -> list:
    table = []
    for c in rules["cruft"]:
        hit = [r for r in rows if r["category"] == c["name"]]
        if not hit:
            continue
        gone = [r for r in hit if not r["held_by"]]
        table.append({"category": c["name"], "default": bool(c.get("default")), "chosen": c["name"] in chosen,
                      "files": len(gone), "bytes": sum(r["size"] for r in gone),
                      "kept_referenced": len(hit) - len(gone), "why": c.get("why", "")})
    return table


def drp_present(rows: list) -> list:
    return [r["rel"] for r in rows if r["rel"].lower().endswith(".drp")]


def nle() -> str:
    return settings.get("editor.nle", default="") or ""


def plan_path(project: Path, action: str) -> Path:
    d = settings.cache_dir("archive-project")
    return d / f"{project.name}-{action}-{stamp()}.plan.json"


def write_plan(plan: dict) -> Path:
    path = plan_path(Path(plan["project"]), plan["action"])
    plan["plan_file"] = str(path)
    plan["list_file"] = str(path.with_suffix(".txt"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    with open(plan["list_file"], "w", encoding="utf-8") as f:
        f.write(f"# {plan['action'].upper()} plan for {plan['project']}\n")
        f.write(f"# Nothing happens until: archive_project.py execute {path} --yes\n\n")
        if plan["copies"]:
            f.write(f"## COPY ({len(plan['copies'])} files, {human(sum(c['size'] for c in plan['copies']))})\n")
            for c in plan["copies"]:
                f.write(f"{human(c['size']):>10}  {c['src']}  ->  {c['dst']}\n")
            f.write("\n")
        f.write(f"## DELETE ({len(plan['deletes'])} files, {human(sum(d['size'] for d in plan['deletes']))})\n")
        for d in plan["deletes"]:
            f.write(f"{human(d['size']):>10}  {d['path']}   [{d['category']}]\n")
    return path


def cmd_scan(a, rules):
    project = resolve_project(a.project)
    s = scan_project(project, rules)
    rows, refs = s["files"], s["refs"]
    chosen = {c["name"] for c in rules["cruft"] if c.get("default")}
    table = category_table(rows, rules, chosen)
    finals = select(rows, rules["keep"]["finals"], rules, s["ph"])
    thumbs = select(rows, rules["keep"]["thumbnails"], rules, s["ph"])
    recipes = find_recipes(project, rows, s["ph"])
    total = sum(r["size"] for r in rows)
    log(f"\nProject: {project}  ({len(rows)} files, {human(total)})")
    report_refs(refs, rows, project)
    log("\nCruft (regenerable; [x] = deleted by a default clean):")
    if not table:
        log("  none found")
    for t in table:
        mark = "x" if t["chosen"] else " "
        extra = f", {t['kept_referenced']} kept (referenced)" if t["kept_referenced"] else ""
        log(f"  [{mark}] {t['category']:<20} {t['files']:>5} files {human(t['bytes']):>10}{extra}  - {t['why']}")
    if not s["have_refs"]:
        log("  (unused-media is not offered: no Resolve export or recipe was found to tell used from unused)")
    log(f"\nFinals ({len(finals)}): " + (", ".join(f["rel"] for f in finals) or "none found"))
    log(f"Thumbnails ({len(thumbs)}): " + (", ".join(f["rel"] for f in thumbs[:8]) or "none found")
        + (" ..." if len(thumbs) > 8 else ""))
    log(f"Recipes: " + (", ".join(recipes) or "none"))
    log(f"Resolve exports (.drp): " + (", ".join(drp_present(rows)) or "none"))
    if nle().startswith("resolve") and not drp_present(rows):
        log("  ! No .drp export in the folder: the reference gate cannot see what your Resolve "
            "project uses. Export it first (export_drp.py, or Project Manager > right-click > Export Project).")
    out = {"project": str(project), "files": len(rows), "bytes": total, "cruft": table,
           "finals": [f["rel"] for f in finals], "thumbnails": len(thumbs), "recipes": recipes,
           "drp": drp_present(rows), "reference_sources": refs.sources,
           "external_references": sorted(refs.external), "warnings": refs.warnings}
    print(json.dumps(out, indent=2))
    return 0


def report_refs(refs: Refs, rows: list, project: Path):
    log(f"Reference sources: " + (", ".join(refs.sources) or "none (no .drp export, no recipe)"))
    for w in refs.warnings:
        log(f"  ! {w}")
    held = [r for r in rows if r["held_by"] and r["category"]]
    if held:
        log(f"Kept although a cruft rule matched, because something still uses them ({len(held)}):")
        for r in held[:15]:
            log(f"  {r['rel']}  <- {', '.join(r['held_by'])}")
        if len(held) > 15:
            log(f"  ... and {len(held) - 15} more (see the plan JSON)")
    ext = sorted(refs.external)
    if ext:
        log(f"References outside the project ({len(ext)}):")
        for e in ext[:10]:
            log(f"  {'ok     ' if os.path.exists(e) else 'MISSING'} {e}")


def cmd_clean(a, rules):
    project = resolve_project(a.project)
    s = scan_project(project, rules)
    rows = s["files"]
    names = [c["name"] for c in rules["cruft"]]
    for n in (a.category or []) + (a.skip or []):
        if n not in names:
            sys.exit(f"unknown category {n!r}; known: {', '.join(names)}")
    chosen = set(a.category) if a.category else {c["name"] for c in rules["cruft"] if c.get("default")}
    chosen -= set(a.skip or [])
    blockers, warnings = [], list(s["refs"].warnings)
    if "unused-media" in chosen and not s["have_refs"]:
        blockers.append("unused-media needs a Resolve export (.drp) or a recipe in the project to tell "
                        "used files from unused ones; none was found")
    if "unused-media" in chosen and nle().startswith("resolve") and not drp_present(rows):
        blockers.append("unused-media: export the Resolve project as .drp into the folder first, or "
                        "files only Resolve uses would count as unused")
    if "unused-media" in chosen and any("zstd" in w for w in s["refs"].warnings):
        blockers.append("unused-media: the .drp could not be fully read without zstd, so clips Resolve "
                        "uses might count as unused. Install zstd first (ask the user)")
    deletes = [{"path": str(project / r["rel"]), "rel": r["rel"], "size": r["size"], "mtime": r["mtime"],
                "category": r["category"]}
               for r in rows if r["category"] in chosen and not r["held_by"]]
    table = category_table(rows, rules, chosen)
    log(f"\nCLEAN {project} (dry run)")
    report_refs(s["refs"], rows, project)
    for t in table:
        mark = "x" if t["chosen"] else " "
        log(f"  [{mark}] {t['category']:<20} {t['files']:>5} files {human(t['bytes']):>10}  - {t['why']}")
    plan = {"schema": "archive-plan/1", "created": dt.datetime.now().isoformat(timespec="seconds"),
            "action": "clean", "project": str(project), "project_name": project.name,
            "categories": sorted(chosen), "copies": [], "repoint": [], "deletes": deletes,
            "delete_project_folder": False, "blockers": blockers, "warnings": warnings,
            "kept_referenced": [{"rel": r["rel"], "held_by": r["held_by"]} for r in rows
                                if r["category"] and r["held_by"]],
            "checksum": False}
    return finish_plan(plan)


def finish_plan(plan: dict) -> int:
    path = write_plan(plan)
    nd, bd = len(plan["deletes"]), sum(d["size"] for d in plan["deletes"])
    nc, bc = len(plan["copies"]), sum(c["size"] for c in plan["copies"])
    for w in plan["warnings"]:
        log(f"  ! {w}")
    if plan.get("delete_project_folder"):
        tops = {}
        for d in plan["deletes"]:
            top = d["rel"].split("/", 1)[0] if "/" in d["rel"] else "(top level files)"
            tops.setdefault(top, [0, 0])
            tops[top][0] += 1
            tops[top][1] += d["size"]
        log("  deleted afterwards, by folder:")
        for top, (n, b) in sorted(tops.items(), key=lambda x: -x[1][1]):
            log(f"    {top + '/':<28} {n:>5} files {human(b):>10}")
    if plan["copies"]:
        log(f"\nWould copy {nc} files ({human(bc)}), verify each, then delete {nd} files ({human(bd)}).")
    else:
        log(f"\nWould delete {nd} files ({human(bd)}).")
    if plan["blockers"]:
        log("\nBLOCKED - fix these first, then dry-run again:")
        for b in plan["blockers"]:
            log(f"  - {b}")
    log(f"\nEvery file, one per line: {plan['list_file']}")
    log(f"After the user approves that exact list: archive_project.py execute {path} --yes")
    print(json.dumps({"plan": str(path), "list": plan["list_file"], "action": plan["action"],
                      "copy_files": nc, "copy_bytes": bc, "delete_files": nd, "delete_bytes": bd,
                      "blockers": plan["blockers"], "warnings": plan["warnings"]}, indent=2))
    return 1 if plan["blockers"] else 0


def durable_roots(rules) -> list:
    out = []
    for key in rules.get("durable_roots", []):
        p = settings.get_path(key)
        if p:
            out.append(p)
    return out


def finals_root(blockers: list) -> Path | None:
    f = settings.get_path("paths.finals_dir")
    if f:
        return f
    a = settings.get_path("paths.archive_dir")
    if a:
        return a / "final-videos"
    try:
        settings.get("paths.finals_dir", required=True,
                     hint="where finished videos are kept, e.g. a folder on a backup drive or NAS; "
                          "or set paths.archive_dir and finals go to <archive_dir>/final-videos")
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    return None


def with_sidecars(project: Path, rel: str, all_rels: set) -> list:
    """The file plus every `<stem>.*` sibling (transcripts, subtitles, notes)."""
    d, name = (rel.rsplit("/", 1) if "/" in rel else ("", rel))
    stem = name.rsplit(".", 1)[0]
    out = [rel]
    for r in all_rels:
        rd, rn = (r.rsplit("/", 1) if "/" in r else ("", r))
        if rd == d and r != rel and rn.lower().startswith(stem.lower() + "."):
            out.append(r)
    return out


def cmd_archive(a, rules):
    project = resolve_project(a.project)
    mode = a.mode or settings.get("archive.default_mode", default="lean")
    if mode not in MODES:
        sys.exit(f"unknown mode {mode!r}: use lean, keep or recipe")
    s = scan_project(project, rules)
    rows, refs, ph = s["files"], s["refs"], s["ph"]
    by_rel = {r["rel"]: r for r in rows}
    all_rels = set(by_rel)
    blockers, warnings, notes = [], list(refs.warnings), []
    checksum = bool(a.checksum or settings.get("archive.checksum", default=False))

    fin_root = finals_root(blockers)
    dest_finals = fin_root / project.name
    arch_root = None
    if mode in ("keep", "recipe"):
        arch_root = Path(a.dest).expanduser() if a.dest else settings.get_path(
            "paths.archive_dir", hint="where archived projects go: a folder on another drive or a NAS share")
        if arch_root is None:
            try:
                settings.get("paths.archive_dir", required=True,
                             hint="where archived projects go: a folder on another drive or a NAS share")
            except settings.SettingMissing as e:
                settings.exit_missing(e)
    dest_project = (arch_root / project.name) if arch_root else None
    for d in [fin_root] + ([arch_root] if arch_root else []):
        if is_under(d, project):
            blockers.append(f"the destination {d} is inside the project folder")
        if is_under(project, d):
            blockers.append(f"the project is already inside the archive ({d}); to slim it there, use clean")

    copies = []

    def add_copy(rel_or_abs, dst: Path, role: str):
        src = Path(rel_or_abs) if os.path.isabs(str(rel_or_abs)) else project / rel_or_abs
        try:
            st = src.stat()
        except OSError:
            blockers.append(f"missing: {src}")
            return
        if any(c["dst"] == str(dst) for c in copies):
            return
        copies.append({"src": str(src), "dst": str(dst), "size": st.st_size, "mtime": st.st_mtime, "role": role})

    # finals (+ sidecars) and thumbnails always go to finals_dir/<project>/
    finals_rel = [f["rel"] for f in select(rows, rules["keep"]["finals"], rules, ph)]
    explicit = []
    for f in a.final or []:
        p = Path(f).expanduser()
        p = (p if p.is_absolute() else project / f).resolve()
        if not p.is_file():
            blockers.append(f"--final not found: {p}")
            continue
        if is_under(p, project):
            finals_rel.append(p.relative_to(project).as_posix())
        else:
            explicit.append(p)
    finals_rel = sorted(set(finals_rel))
    fin_prefix = ph["finals"].rstrip("/") + "/"
    for rel in finals_rel:
        for side in with_sidecars(project, rel, all_rels):
            sub = side[len(fin_prefix):] if side.lower().startswith(fin_prefix.lower()) else side
            add_copy(side, dest_finals / sub, "final" if side == rel else "final-sidecar")
    for p in explicit:
        if is_under(p, fin_root):
            notes.append(f"final already in the finals folder: {p}")
        else:
            add_copy(str(p), dest_finals / p.name, "final")
    if not finals_rel and not explicit:
        blockers.append(f"no final video found in {project / ph['finals']} (rules.json keep.finals). "
                        f"Render the final first, or name it with --final FILE")
    for rel in finals_rel:
        ok, why = playable(project / rel)
        if not ok:
            blockers.append(f"final does not play: {project / rel} ({why})")

    thumbs = [f["rel"] for f in select(rows, rules["keep"]["thumbnails"], rules, ph)]
    used_names = {}
    for rel in thumbs:
        name = rel.rsplit("/", 1)[-1]
        if name.lower() in used_names:
            name = rel.replace("/", "__")
        used_names[name.lower()] = rel
        add_copy(rel, dest_finals / "thumbnails" / name, "thumbnail")
    if not thumbs:
        notes.append("no thumbnails found (rules.json keep.thumbnails)")
    for f in select(rows, rules["keep"].get("extras", {}), rules, ph):
        add_copy(f["rel"], dest_finals / "extras" / f["rel"], "extra")

    # b-roll: harvest reusable shots before the footage goes (broll-library skill)
    lib = settings.get_path("paths.broll_library_dir")
    if mode in ("lean", "recipe"):
        if lib and not a.broll:
            blockers.append("b-roll: offer the broll-library skill's harvest of this project's reusable shots "
                            "first (.claude/skills/broll-library/scripts/harvest_project.py for what the edit "
                            "used, salvage.py prep/apply for good unused footage), then pass --broll done "
                            "(or --broll skip if the user declines)")
        elif not lib:
            notes.append("no b-roll library is set up (paths.broll_library_dir), so no b-roll harvest; "
                         "the broll-library skill can set one up")

    repoint = []
    if mode == "keep":
        # the cleaned folder: everything except the default cruft (references keep a file)
        chosen = {c["name"] for c in rules["cruft"] if c.get("default")}
        for r in rows:
            if r["link"]:
                warnings.append(f"symbolic link not copied: {r['rel']}")
                continue
            if r["category"] in chosen and not r["held_by"]:
                continue
            add_copy(r["rel"], dest_project / r["rel"], "project")
        bundled = bundle_external(refs, dest_project, durable_roots(rules), add_copy, warnings,
                                  only_from=lambda src: src.lower().endswith(".json"))
        for r in rows:
            if r["rel"].lower().endswith(".json") and not r["rel"].lower().endswith(".transcript.json"):
                repoint.append({"file": str(dest_project / r["rel"]), "bundled": bundled})
        drps = drp_present(rows)
        if not drps:
            if nle().startswith("resolve") and not a.no_drp:
                blockers.append("no Resolve project export (.drp) in the folder. Studio: run "
                                "scripts/export_drp.py --project \"<Resolve project name>\" --out "
                                f"\"{project / 'resolve'}\"; Free: Project Manager (Shift+1) > right-click the "
                                "project > Export Project, save it into the folder. Or pass --no-drp if this "
                                "video was not edited in Resolve")
            else:
                notes.append("no .drp in the folder (fine if this video was not edited in Resolve)")
        drp_ext = [e for e, srcs in refs.external.items() if any(x.lower().endswith(".drp") for x in srcs)]
        if drp_ext:
            warnings.append(f"the Resolve export uses {len(drp_ext)} files outside the project; they stay where "
                            f"they are (relink in Resolve if they move): " + ", ".join(sorted(drp_ext)[:5]))
    elif mode == "recipe":
        recipes = find_recipes(project, rows, ph, a.recipe)
        if not recipes:
            blockers.append("no recipe found (a JSON named *recipe*); name it with --recipe FILE, "
                            "or use --mode keep / lean")
        rrefs = Refs(project, rows)
        for rel in recipes:
            rrefs.read_json(project / rel)
        needed = set()
        for rel in rrefs.by:
            if rel in all_rels:
                needed |= set(with_sidecars(project, rel, all_rels))
            else:   # a referenced folder: everything under it
                needed |= {r for r in all_rels if r.startswith(rel + "/")}
        for rel in sorted(needed):
            add_copy(rel, dest_project / rel, "recipe-media")
        for r in rows:
            if (not r["link"] and kind_of(r["rel"], rules) == "text" and r["size"] <= TEXT_KEEP_LIMIT
                    and not match_any(r["rel"].rsplit("/", 1)[-1], [".DS_Store", "._*"])):
                add_copy(r["rel"], dest_project / r["rel"], "recipe" if r["rel"] in recipes else "text")
        missing = [e for e in rrefs.external if not os.path.exists(e)] + list(rrefs.missing)
        if missing and not a.allow_missing:
            blockers.append("the recipe points at files that do not exist, so it could not rebuild the video: "
                            + ", ".join(sorted(missing)[:8]) + " (find them, or pass --allow-missing)")
        bundled = bundle_external(rrefs, dest_project, durable_roots(rules), add_copy, warnings)
        for rel in recipes:
            repoint.append({"file": str(dest_project / rel), "bundled": bundled,
                            "also_to": str(dest_finals / rel.rsplit("/", 1)[-1])})
        copied = {c["dst"] for c in copies}
        for r in rows:
            if (r["rel"].lower().endswith(".json") and r["rel"] not in recipes
                    and str(dest_project / r["rel"]) in copied):
                repoint.append({"file": str(dest_project / r["rel"]), "bundled": {}})
        notes.append("recipes: " + (", ".join(recipes) or "none"))

    # what goes: lean/keep/recipe delete the whole folder once every copy verifies
    deletes = [{"path": str(project / r["rel"]), "rel": r["rel"], "size": r["size"], "mtime": r["mtime"],
                "category": r["category"] or "project"} for r in rows]

    need_f = sum(c["size"] for c in copies if is_under(Path(c["dst"]), fin_root) and not same_file_quick(c))
    check_destination(fin_root, "finals folder", need_f, blockers, warnings, project)
    if arch_root:
        need_a = sum(c["size"] for c in copies if is_under(Path(c["dst"]), arch_root)
                     and not is_under(Path(c["dst"]), fin_root) and not same_file_quick(c))
        check_destination(arch_root, "archive folder", need_a, blockers, warnings, project)
    for c in copies:
        d = Path(c["dst"])
        if d.exists() and not same_file_quick(c):
            if c["role"] in ("thumbnail", "extra", "final-sidecar"):
                c["dst"] = str(d.with_name(f"{d.stem}.{stamp()}{d.suffix}"))
                notes.append(f"a different file already exists at {d}; this copy is saved beside it")
            else:
                blockers.append(f"a different file already exists at {d} (an earlier archive of the same name?)")

    banner = {"lean": f"LEAN: keep the finals and thumbnails in {dest_finals}, delete the project folder",
              "keep": f"KEEP: move the cleaned project to {dest_project} (finals also in {dest_finals}), "
                      f"then delete the local folder",
              "recipe": f"RECIPE: master + recipe in {dest_finals}, the recipe's media in {dest_project}, "
                        f"then delete the local folder"}[mode]
    log(f"\n{banner}  (dry run)")
    report_refs(refs, rows, project)
    roles = {}
    for c in copies:
        roles.setdefault(c["role"], [0, 0])
        roles[c["role"]][0] += 1
        roles[c["role"]][1] += c["size"]
    for role, (n, b) in sorted(roles.items()):
        log(f"  copy {role:<14} {n:>5} files {human(b):>10}")
    for rel in finals_rel:
        log(f"  final: {project / rel}")
    for n_ in notes:
        log(f"  - {n_}")
    plan = {"schema": "archive-plan/1", "created": dt.datetime.now().isoformat(timespec="seconds"),
            "action": mode, "project": str(project), "project_name": project.name,
            "dest": {"finals": str(dest_finals), "archive": str(dest_project) if dest_project else None,
                     "log": str((arch_root or settings.get_path("paths.archive_dir") or fin_root)
                                / "archive-log.jsonl")},
            "copies": copies, "repoint": repoint, "deletes": deletes, "delete_project_folder": True,
            "broll": a.broll, "blockers": blockers, "warnings": warnings, "notes": notes,
            "kept_referenced": [], "checksum": checksum,
            "external_references": sorted(refs.external)}
    return finish_plan(plan)


def same_file_quick(c: dict) -> bool:
    try:
        return Path(c["dst"]).stat().st_size == c["size"]
    except OSError:
        return False


def bundle_external(refs: Refs, dest_project: Path, durable: list, add_copy, warnings: list,
                    only_from=None) -> dict:
    """Files outside the project that a recipe plays: kept as references when they live in
    a durable place (archive, finals, b-roll library, home videos, music); otherwise copied
    into <archive>/<project>/external/ so the archive is self-contained."""
    bundled = {}
    for ext, srcs in sorted(refs.external.items()):
        if only_from and not any(only_from(s) for s in srcs):
            continue
        p = Path(ext)
        if not p.is_file():
            continue
        if any(is_under(p, d) for d in durable):
            continue
        rel = f"{p.parent.name}/{p.name}" if p.parent.name else p.name   # e.g. external/stock/skyline.mp4
        dst = dest_project / "external" / rel
        n = 2
        while str(dst) in bundled.values():
            dst = dest_project / "external" / f"{p.parent.name}-{n}" / p.name
            n += 1
        add_copy(str(p), dst, "external")
        bundled[ext] = str(dst)
    if bundled:
        warnings.append(f"{len(bundled)} files outside the project that a recipe uses are copied into "
                        f"{dest_project / 'external'} and the recipe is repointed at them")
    return bundled


def playable(path: Path):
    """(ok, why) - a final must have a video stream and a duration."""
    try:
        from vidkit import media
        exe = media.which("ffprobe")
    except Exception:
        exe = shutil.which("ffprobe")
    if not exe:
        return True, "ffprobe not installed, not checked"
    r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "format=duration:stream=codec_type", "-of", "json", str(path)],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout or "{}")
        dur = float(d.get("format", {}).get("duration") or 0)
        has_v = any(s.get("codec_type") == "video" for s in d.get("streams", []))
    except (ValueError, TypeError):
        return False, "ffprobe could not read it"
    if r.returncode or not has_v or dur <= 0:
        return False, (r.stderr.strip() or "no video stream")[:200]
    return True, f"{dur:.1f} s"


# ---- execute -------------------------------------------------------------------

def copy_verified(src: Path, dst: Path, checksum: bool) -> str:
    """Copy to <dst>.part, verify, rename. Returns 'copied' or 'already'; raises on failure.
    A file already at dst counts as this one only when its SHA-256 matches (same size is not enough)."""
    if dst.exists():
        if dst.stat().st_size == src.stat().st_size and sha256(src) == sha256(dst):
            return "already"
        raise RuntimeError(f"a different file is already at {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    h = hashlib.sha256() if checksum else None
    with open(src, "rb") as fi, open(part, "wb") as fo:
        for chunk in iter(lambda: fi.read(8 << 20), b""):
            fo.write(chunk)
            if h:
                h.update(chunk)
        fo.flush()
        os.fsync(fo.fileno())
    shutil.copystat(src, part)
    if part.stat().st_size != src.stat().st_size:
        part.unlink()
        raise RuntimeError(f"size mismatch copying {src}")
    if h and sha256(part) != h.hexdigest():
        part.unlink()
        raise RuntimeError(f"checksum mismatch copying {src}")
    os.replace(part, dst)
    return "copied"


def repoint_file(path: Path, old_roots: list, new_root: str, bundled: dict, name: str | None = None) -> int:
    """Rewrite every path string in a JSON file that points into the old project folder
    (or at a bundled external file) so it points at the archived copy. A path spelled
    another way (through a symlink, an old drive name) is caught by the project folder's
    name: '.../<name>/<rest>' is repointed when <new_root>/<rest> exists."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return 0
    olds = sorted({r.replace("\\", "/").rstrip("/") + "/" for r in old_roots}, key=len, reverse=True)
    n = [0]

    def fix(s: str) -> str:
        t = s.replace("\\", "/")
        if t in bundled:
            n[0] += 1
            return bundled[t]
        if s in bundled:
            n[0] += 1
            return bundled[s]
        for o in olds:
            if t.startswith(o) or t == o[:-1]:
                n[0] += 1
                return new_root.rstrip("/") + "/" + t[len(o):] if t != o[:-1] else new_root
        marker = "/" + (name or "") + "/"
        if name and marker in t and (t.startswith("/") or re.match(r"^[A-Za-z]:/", t)):
            rest = t.split(marker, 1)[1]
            cand = new_root.rstrip("/") + "/" + rest
            if not t.startswith(new_root.rstrip("/") + "/") and os.path.exists(cand):
                n[0] += 1
                return cand
        return s

    def walk_json(x):
        if isinstance(x, dict):
            return {k: walk_json(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk_json(v) for v in x]
        if isinstance(x, str):
            return fix(x)
        return x
    new = walk_json(data)
    if n[0]:
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    return n[0]


def append_log(path: Path, record: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log(f"  ! could not write the archive log {path}: {e}")


def prune_parents(paths: list, root: Path):
    """Remove folders that the deletes left empty (never pre-existing empty ones elsewhere)."""
    for d in sorted({Path(x).parent for x in paths}, key=lambda x: -len(x.parts)):
        while d != root and is_under(d, root):
            try:
                d.rmdir()          # only succeeds when empty
            except OSError:
                break
            d = d.parent


def prune_empty_dirs(root: Path):
    for d, dn, fn in os.walk(root, topdown=False):
        p = Path(d)
        try:
            if p != root and not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass


def plan_problems(plan: dict, project: Path) -> list:
    """Why a plan must not run: the same project-folder guards as the dry run, and every
    delete inside that folder, every copy / repoint inside its destinations. A plan that was
    edited by hand or has gone stale fails here before anything is copied or deleted."""
    probs = []
    if project.is_symlink():
        probs.append(f"{project} is a symbolic link")
    real = project.resolve()
    if str(real) != plan["project"]:
        probs.append(f"the plan's project {plan['project']} is not that folder's real path ({real})")
    why = project_guard(real)
    if why:
        probs.append(f"refusing to treat {real} as a project folder: {why}")
    if plan.get("project_name") != real.name:
        probs.append(f"the plan's project_name {plan.get('project_name')!r} is not the folder's name {real.name!r}")
    outside = [d["path"] for d in plan["deletes"]
               if Path(d["path"]) == real or not is_under(Path(d["path"]), real)
               or not real_under(Path(d["path"]), real)
               or os.path.normpath(str(real / d.get("rel", ""))) != os.path.normpath(d["path"])]
    if outside:
        probs.append(f"{len(outside)} planned deletes are not inside {real}: " + ", ".join(outside[:5]))
    dest = plan.get("dest") or {}
    roots = [Path(x) for x in (dest.get("finals"), dest.get("archive")) if x]
    for r in roots:
        if is_under(r, real):
            probs.append(f"the destination {r} is inside the project folder")
    stray = [c["dst"] for c in plan["copies"] if not any(is_under(Path(c["dst"]), r) for r in roots)]
    stray += [x for rp in plan.get("repoint", []) for x in (rp["file"], rp.get("also_to")) if x
              and not any(is_under(Path(x), r) for r in roots)]
    if stray:
        probs.append(f"{len(stray)} planned copies are not inside the plan's destinations: " + ", ".join(stray[:5]))
    if dest.get("log") and Path(dest["log"]).name != "archive-log.jsonl":
        probs.append(f"the archive log {dest['log']} is not an archive-log.jsonl")
    return probs


def cmd_execute(a, rules):
    plan_file = Path(a.plan).expanduser()
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if plan.get("schema") != "archive-plan/1":
        sys.exit("not an archive plan")
    project = Path(plan["project"])
    if plan["blockers"]:
        log("This plan is blocked:")
        for b in plan["blockers"]:
            log(f"  - {b}")
        log("Fix them and make a new plan (dry run).")
        return 1
    if not a.yes:
        log(f"Not executed: pass --yes once the user has approved the exact list in {plan.get('list_file')}")
        return 2
    if not project.is_dir():
        sys.exit(f"the project folder is gone: {project}")
    probs = plan_problems(plan, project)
    if probs:
        log("REFUSED - this plan cannot run safely, nothing was copied or deleted:")
        for p_ in probs:
            log(f"  - {p_}")
        log("Make a new plan with a dry run (archive / clean) and never edit a plan by hand.")
        return 1
    checksum = bool(a.checksum or plan.get("checksum"))
    action = plan["action"]
    # destinations still there? (a NAS can drop between the dry run and now)
    blockers = []
    for key in ("finals", "archive"):
        d = (plan.get("dest") or {}).get(key)
        if d:
            check_destination(Path(d).parent, key, 0, blockers, [], project)
    if blockers:
        for b in blockers:
            log(f"  - {b}")
        return 1

    result = {"action": action, "project": str(project), "copied": 0, "already": 0, "copy_failed": [],
              "repointed": {}, "deleted": 0, "deleted_bytes": 0, "skipped_changed": [], "left_behind": [],
              "checksum": checksum}
    # 1. copy + verify
    for i, c in enumerate(plan["copies"], 1):
        src, dst = Path(c["src"]), Path(c["dst"])
        try:
            st = src.stat()
            if st.st_size != c["size"]:
                raise RuntimeError(f"{src} changed since the plan (size)")
            how = copy_verified(src, dst, checksum)
            result["copied" if how == "copied" else "already"] += 1
        except (OSError, RuntimeError) as e:
            result["copy_failed"].append(f"{src}: {e}")
        if i % 50 == 0 or c["size"] > 500 * 1024 * 1024:
            log(f"  [{i}/{len(plan['copies'])}] {dst.name}")
    if result["copy_failed"]:
        log("Copy/verify FAILED - nothing was deleted:")
        for f in result["copy_failed"]:
            log(f"  - {f}")
        print(json.dumps(result, indent=2))
        return 1
    log(f"Copied {result['copied']} files, {result['already']} already there"
        + (", every copy SHA-256 verified" if checksum else ", every copy size-verified"))

    # 2. repoint recipes in the archived copy
    arch = (plan.get("dest") or {}).get("archive")
    if arch:
        old_roots = [str(project), os.path.realpath(project)]
        for r in plan.get("repoint", []):
            f = Path(r["file"])
            if f.is_file():
                n = repoint_file(f, old_roots, arch, r.get("bundled") or {}, plan["project_name"])
                if n:
                    result["repointed"][str(f)] = n
                if r.get("also_to"):
                    to = Path(r["also_to"])
                    to.parent.mkdir(parents=True, exist_ok=True)
                    if to.exists():              # never overwrite: an earlier archive's recipe stays
                        to = to.with_name(f"{to.stem}.{stamp()}{to.suffix}")
                        log(f"  a recipe is already at {r['also_to']}; this one is saved beside it as {to.name}")
                    shutil.copy2(f, to)
        if result["repointed"]:
            log(f"Repointed {sum(result['repointed'].values())} paths in {len(result['repointed'])} JSON files")

    # 3. manifest + log, before anything is deleted
    record = {"when": dt.datetime.now().isoformat(timespec="seconds"), "action": action,
              "project_name": plan["project_name"], "from": str(project),
              "finals": [c["dst"] for c in plan["copies"] if c["role"] == "final"],
              "thumbnails": sum(1 for c in plan["copies"] if c["role"] == "thumbnail"),
              "archive": arch, "broll": plan.get("broll"), "checksum": checksum,
              "deleted_files": len(plan["deletes"]), "deleted_bytes": sum(d["size"] for d in plan["deletes"]),
              "external_references": plan.get("external_references", [])}
    if action in MODES:
        for d in {plan["dest"]["finals"], arch} - {None}:
            Path(d).mkdir(parents=True, exist_ok=True)
            with open(Path(d) / "ARCHIVE-MANIFEST.json", "w", encoding="utf-8") as f:
                json.dump(dict(record, how_to_rebuild=rebuild_note(action)), f, indent=2, ensure_ascii=False)
        append_log(Path(plan["dest"]["log"]), record)

    # 4. delete exactly the planned files, each re-checked
    for d in plan["deletes"]:
        p = Path(d["path"])
        if not is_under(p, project) or not real_under(p, project) or p == project:
            result["left_behind"].append(f"{p} (outside the project: never deleted)")
            continue
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            continue
        if not os.path.islink(p) and (st.st_size != d["size"] or abs(st.st_mtime - d["mtime"]) > 2):
            result["skipped_changed"].append(str(p))
            continue
        try:
            os.unlink(p)
            result["deleted"] += 1
            result["deleted_bytes"] += d["size"]
        except OSError as e:
            result["left_behind"].append(f"{p} ({e})")
    if plan.get("delete_project_folder"):
        prune_empty_dirs(project)
    else:
        prune_parents([d["path"] for d in plan["deletes"]], project)
    if plan.get("delete_project_folder"):
        try:
            project.rmdir()
        except OSError:
            rest = [f["rel"] for f in walk(project)]
            result["left_behind"] += [str(project / r) for r in rest]
    logf = settings.cache_dir("archive-project") / f"{plan['project_name']}-{action}-{stamp()}.done.json"
    with open(logf, "w", encoding="utf-8") as f:
        json.dump(dict(result, plan=str(plan_file)), f, indent=2)
    result["log"] = str(logf)
    try:
        anchor = project if project.exists() else project.parent
        result["free_after"] = shutil.disk_usage(anchor).free
    except OSError:
        pass
    log(f"Deleted {result['deleted']} files ({human(result['deleted_bytes'])})."
        + (f" Skipped {len(result['skipped_changed'])} that changed since the plan." if result["skipped_changed"] else "")
        + (f" Left {len(result['left_behind'])} in place (new since the plan, or not removable)."
           if result["left_behind"] else ""))
    print(json.dumps(result, indent=2))
    return 0


def rebuild_note(action: str) -> str:
    return {
        "lean": "Only the finals and thumbnails were kept; the project cannot be rebuilt.",
        "keep": "Copy this folder back to your projects drive (or open it in place). Resolve: import the "
                ".drp (Project Manager > right-click > Import Project) and relink the media "
                "(Media Pool > select clips > right-click > Relink Selected Clips). ffmpeg recipes in "
                "here already point at this folder.",
        "recipe": "The recipe(s) in this folder point at the archived media beside them. Re-render with "
                  "the skill that built the video (talking-head-ffmpeg or home-video), giving it the "
                  "recipe path. Paths are absolute: if this folder moves, run archive_project.py "
                  "repoint <folder> to point them at the new place.",
    }[action]


def cmd_repoint(a, rules):
    """Point an archived folder's JSON recipes at where the folder is now (after a move)."""
    folder = Path(a.folder).expanduser().resolve()
    old = a.old_root
    if not old:
        man = folder / "ARCHIVE-MANIFEST.json"
        old = json.loads(man.read_text())["archive"] if man.is_file() else None
    if not old:
        sys.exit("pass --old-root (the path the recipes point at now)")
    total = 0
    for f in folder.rglob("*.json"):
        if f.name != "ARCHIVE-MANIFEST.json":
            n = repoint_file(f, [old], str(folder), {}, Path(old).name)
            if n:
                total += n
                log(f"  {f}: {n} paths")
    print(json.dumps({"folder": str(folder), "old_root": old, "repointed": total}))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("scan", help="read-only report")
    s.add_argument("project")
    c = sub.add_parser("clean", help="plan deleting the cruft (dry run)")
    c.add_argument("project")
    c.add_argument("--category", action="append", help="only these categories (repeat)")
    c.add_argument("--skip", action="append", help="leave this category out (repeat)")
    ar = sub.add_parser("archive", help="plan an archive (dry run)")
    ar.add_argument("project")
    ar.add_argument("--mode", choices=MODES, help="default: settings archive.default_mode (lean)")
    ar.add_argument("--final", action="append", help="a final render (repeat); default: the finals folder")
    ar.add_argument("--recipe", action="append", help="recipe mode: the recipe JSON (repeat); default: newest *recipe*.json")
    ar.add_argument("--broll", choices=("done", "skip"), help="the b-roll harvest was done or declined")
    ar.add_argument("--no-drp", action="store_true", help="keep mode: no Resolve export needed")
    ar.add_argument("--allow-missing", action="store_true", help="recipe mode: archive although the recipe names missing files")
    ar.add_argument("--dest", help="keep/recipe: archive folder (default: settings paths.archive_dir)")
    ar.add_argument("--checksum", action="store_true", help="verify copies with SHA-256 too (slower)")
    e = sub.add_parser("execute", help="carry out a plan")
    e.add_argument("plan")
    e.add_argument("--yes", action="store_true", help="the user approved this exact list")
    e.add_argument("--checksum", action="store_true")
    r = sub.add_parser("repoint", help="re-aim an archived folder's recipes after moving it")
    r.add_argument("folder")
    r.add_argument("--old-root")
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    rules = load_rules()
    try:
        return {"scan": cmd_scan, "clean": cmd_clean, "archive": cmd_archive,
                "execute": cmd_execute, "repoint": cmd_repoint}[a.cmd](a, rules)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
        return 4


if __name__ == "__main__":
    sys.exit(main())
