#!/usr/bin/env python3
"""The one place every skill reads the user's setup from.

Settings live in <repo>/user/settings.json (created by the `setup` skill, never
committed). Any value can be left unset (null): skills ask for it the first
time they need it and save the answer, so onboarding can be skipped.

Python:
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tools"))
    from vidkit import settings
    projects = settings.get_path("paths.projects_dir", required=True)

    A required value that is unset raises SettingMissing; call
    settings.exit_missing(e) (or let main() wrappers do it) to print a clear
    message and exit with code 4.

Shell (from a SKILL.md):
    python3 "${CLAUDE_SKILL_DIR}/../../../tools/vidkit/settings.py" get paths.projects_dir
    python3 .../settings.py set paths.projects_dir "~/Movies/VideoProjects"
    python3 .../settings.py show | missing | path | init
    python3 .../settings.py step-done <step> | step-skip <step>

Exit codes: 0 ok, 4 a required setting is unset (ask the user, `set` it, re-run),
2 usage error.

Environment overrides: VES_SETTINGS=<file> points at another settings file;
VES_<DOTTED_KEY> (dots -> underscores, upper case, e.g. VES_PATHS_PROJECTS_DIR)
overrides one value for a single run.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_DIR = REPO_ROOT / "user"
EXAMPLE_PATH = USER_DIR / "settings.example.json"
PREFERENCES_PATH = USER_DIR / "preferences.md"
EXIT_MISSING = 4


class SettingMissing(Exception):
    def __init__(self, key: str, hint: str | None = None):
        self.key = key
        self.hint = hint
        super().__init__(key)


def settings_path() -> Path:
    env = os.environ.get("VES_SETTINGS")
    return Path(env).expanduser() if env else USER_DIR / "settings.json"


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        sys.exit(f"{path} is not valid JSON ({e}). Fix it by hand or delete it and run the setup skill again.")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def defaults() -> dict:
    return _read_json(EXAMPLE_PATH)


def exists() -> bool:
    return settings_path().is_file()


def load() -> dict:
    """Example defaults merged with the user's file (new keys get defaults)."""
    return _merge(defaults(), _read_json(settings_path()))


def _env_key(key: str) -> str:
    return "VES_" + key.replace(".", "_").replace("-", "_").upper()


def get(key: str, required: bool = False, default=None, hint: str | None = None):
    env = os.environ.get(_env_key(key))
    if env:  # an empty override (VES_X=) means "not overridden"
        try:
            return json.loads(env)
        except json.JSONDecodeError:
            return env
    node = load()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            node = None
            break
        node = node[part]
    if node in (None, "", []):
        if required:
            raise SettingMissing(key, hint)
        return default
    return node


def get_path(key: str, required: bool = False, must_exist: bool = False, hint: str | None = None) -> Path | None:
    v = get(key, required=required, hint=hint)
    if v is None:
        return None
    p = Path(os.path.expandvars(str(v))).expanduser()
    if must_exist and not p.exists():
        sys.exit(f"{key} = {p} does not exist (unplugged drive or unmounted NAS?). "
                 f"Connect it, or change it with: settings.py set {key} <path>")
    return p


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def set_value(key: str, value) -> None:
    path = settings_path()
    data = _read_json(path) or defaults()
    node = data
    parts = key.split(".")
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
    _atomic_write(path, data)


def init() -> Path:
    """Create user/settings.json from the example if it does not exist yet."""
    path = settings_path()
    if not path.exists():
        _atomic_write(path, defaults())
    return path


def mark_step(step: str, done: bool) -> None:
    data = load()
    ob = data.setdefault("onboarding", {})
    completed = [s for s in ob.get("completed_steps", []) if s != step]
    skipped = [s for s in ob.get("skipped_steps", []) if s != step]
    (completed if done else skipped).append(step)
    set_value("onboarding.completed_steps", completed)
    set_value("onboarding.skipped_steps", skipped)
    set_value("onboarding.last_run", _dt.date.today().isoformat())


def unset_keys(node=None, prefix="") -> list:
    """Dotted keys whose value is null/empty (onboarding's to-do list)."""
    node = load() if node is None else node
    out = []
    for k, v in node.items():
        key = f"{prefix}{k}"
        if key.startswith("onboarding"):
            continue
        if isinstance(v, dict):
            out += unset_keys(v, key + ".")
        elif v in (None, "", []):
            out.append(key)
    return out


# ---- project helpers -------------------------------------------------------

def layout(name: str) -> str:
    """Relative folder for a project part: footage, audio, graphics, drafts, finals, work."""
    return get(f"project_layout.{name}", default=name)


def project_dir(name_or_path: str, required: bool = True) -> Path:
    """A project folder from a name (under paths.projects_dir) or a path."""
    p = Path(name_or_path).expanduser()
    if p.is_absolute() or p.exists():
        return Path(os.path.abspath(str(p)))
    root = get_path("paths.projects_dir", required=required,
                    hint="the folder where your video projects live")
    return (root / name_or_path) if root else p


def find_project_root(path: str | Path) -> Path | None:
    """The project folder containing `path`: the nearest ancestor that sits
    directly inside paths.projects_dir, else the nearest ancestor holding the
    layout's footage folder. None when the file is not inside a project.
    Symlinks are not followed first (a linked clip belongs where the link is),
    then the resolved location is tried."""
    raw = Path(os.path.abspath(os.path.expanduser(str(path))))
    candidates = [raw] + ([raw.resolve()] if raw.resolve() != raw else [])
    root = get_path("paths.projects_dir")
    roots = []
    if root:
        roots = [Path(os.path.abspath(str(root)))]
        if root.resolve() != roots[0]:
            roots.append(root.resolve())
    foot = layout("footage")
    for p in candidates:
        for a in [p] + list(p.parents):
            if a.parent in roots:
                return a
        for a in list(p.parents):
            if (a / foot).is_dir():
                return a
    return None


def drafts_dir(for_media: str | Path) -> Path:
    """Where draft renders for a media file go: <project>/<drafts> when the
    file is inside a project, else a `drafts/` folder next to it."""
    proj = find_project_root(for_media)
    base = (proj / layout("drafts")) if proj else Path(os.path.abspath(os.path.expanduser(str(for_media)))).parent / "drafts"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir(sub: str = "") -> Path:
    base = get_path("paths.cache_dir") or (USER_DIR / "cache")
    d = base / sub if sub else base
    d.mkdir(parents=True, exist_ok=True)
    return d


def exit_missing(e: SettingMissing) -> None:
    hint = f" ({e.hint})" if e.hint else ""
    print(f"SETTING NOT SET: {e.key}{hint}.\n"
          f"Ask the user, then save it with:\n"
          f"  python3 {Path(__file__).resolve()} set {e.key} <value>\n"
          f"and re-run. (Or run the setup skill to answer everything at once.)", file=sys.stderr)
    sys.exit(EXIT_MISSING)


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "get" and len(args) == 1:
            v = get(args[0], required=True)
            print(v if isinstance(v, str) else json.dumps(v))
        elif cmd == "get-optional" and len(args) == 1:
            v = get(args[0])
            print("" if v is None else (v if isinstance(v, str) else json.dumps(v)))
        elif cmd == "set" and len(args) == 2:
            set_value(args[0], _parse_value(args[1]))
            print(f"{args[0]} = {json.dumps(get(args[0]))}")
        elif cmd == "unset" and len(args) == 1:
            set_value(args[0], None)
        elif cmd == "show":
            print(json.dumps(load(), indent=2, ensure_ascii=False))
        elif cmd == "path":
            print(settings_path())
        elif cmd == "exists":
            return 0 if exists() else 1
        elif cmd == "init":
            print(init())
        elif cmd == "missing":
            print("\n".join(unset_keys()))
        elif cmd == "step-done" and len(args) == 1:
            mark_step(args[0], True)
        elif cmd == "step-skip" and len(args) == 1:
            mark_step(args[0], False)
        elif cmd == "project-dir" and len(args) == 1:
            print(project_dir(args[0]))
        elif cmd == "drafts-dir" and len(args) == 1:
            print(drafts_dir(args[0]))
        elif cmd == "cache-dir":
            print(cache_dir(args[0] if args else ""))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except SettingMissing as e:
        exit_missing(e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
