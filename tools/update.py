#!/usr/bin/env python3
"""Is there a newer version of this toolkit? And get it, keeping the user's own changes.

    update.py check              the session-start look (tools/first_run.py runs it): at most once a day, a few
                                 seconds at most, silent when offline or switched off. Prints one line for Claude
                                 when a newer version is out.
    update.py status             look now: JSON with what is new and whether it can go in as it is
    update.py apply [--convert]  get it (JSON). Only ever a fast-forward: a file the user changed is never
                                 overwritten, and user/ is never touched.

How a copy knows its version ("kind" in the JSON):
  git       a git clone: its HEAD against the branch it follows (git ls-remote; `check` fetches nothing)
  download  a copy downloaded without git: tools/version-stamp.txt holds the commit it was made from (GitHub
            fills it in on download: .gitattributes export-subst), compared with the latest commit of UPSTREAM
  unknown   neither: nothing to compare, and `check` stays silent

`apply` on a download copy needs --convert: the folder becomes a git clone at the commit it was made from (git
init, fetch, the index set to that commit; no file in the folder is changed), so the user's own edits show up as
local changes and the update is the same fast-forward.

"blocked" in the JSON (exit 3) says why an update cannot go in as it is:
  not-a-git-copy  a download copy: ask the user, then apply --convert
  overlap         the user changed files the update changes too ("overlap" lists them)
  diverged        this copy has commits the other side does not ("ahead"): the user's own, or the toolkit's
                  history was rebuilt

What leaves the computer: one request for the latest commit id, to where the copy came from (GitHub). Nothing
about the user, the computer or their files is sent. The daily look is switched off with
`settings.py set updates.check false`.

Exit codes: 0 ok, 1 failed, 2 usage, 3 blocked, 5 git is needed and is not installed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "tools" / "version-stamp.txt"
UPSTREAM = os.environ.get("VES_UPDATE_UPSTREAM") or "https://github.com/js-commit/video-editing-skills"
AGENT = "video-editing-skills-update-check"     # names the toolkit, never the user
DAY, RETRY = 24 * 3600, 3600                      # look once a day; after a failed look, again in an hour
SHA = re.compile(r"[0-9a-f]{40}")


class Blocked(Exception):
    pass


def settings_file() -> Path:
    env = os.environ.get("VES_SETTINGS")
    return Path(env).expanduser() if env else ROOT / "user" / "settings.json"


def state_file() -> Path:
    return settings_file().parent / "update-check.json"


def enabled() -> bool:
    v = os.environ.get("VES_UPDATES_CHECK")
    if not v:
        try:
            v = json.loads(settings_file().read_text(encoding="utf-8")).get("updates", {}).get("check", True)
        except Exception:
            v = True
    return str(v).strip().lower() not in ("false", "0", "no", "off")


def read_state() -> dict:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(**kw) -> None:
    try:
        f = state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(kw, indent=1), encoding="utf-8")
    except OSError:
        pass


def have_git() -> bool:
    return not os.environ.get("VES_UPDATE_NO_GIT") and bool(shutil.which("git"))


def git(*args, timeout=60):
    """git in the toolkit folder; never asks for a password, never waits longer than `timeout`."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=5")
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=timeout, env=env)
    except (subprocess.TimeoutExpired, OSError) as e:
        return subprocess.CompletedProcess(args, 124, "", str(e))


def out(*args, timeout=60) -> str:
    r = git(*args, timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else ""


def kind() -> str:
    if have_git():
        top = out("rev-parse", "--show-toplevel")
        try:
            if top and os.path.samefile(top, ROOT):
                return "git"
        except OSError:
            pass
    return "download" if stamp() else "unknown"


def stamp() -> str:
    try:
        s = STAMP.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return s if SHA.fullmatch(s) else ""


def follows():
    """(remote, ref) a git clone gets its updates from: the current branch's upstream, else origin's default."""
    b = out("symbolic-ref", "--short", "-q", "HEAD")
    remote, merge = (out("config", f"branch.{b}.remote"), out("config", f"branch.{b}.merge")) if b else ("", "")
    return (remote, merge) if remote and merge else ("origin", "HEAD")


def ls_remote(where, ref, timeout) -> str:
    line = out("ls-remote", where, ref, timeout=timeout).split("\n")[0]
    return line.split()[0] if SHA.match(line) else ""


def github_repo() -> str:
    m = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", UPSTREAM)
    return m.group(1) if m else ""


def api(path, accept, timeout):
    req = urllib.request.Request(f"https://api.github.com/repos/{github_repo()}/{path}",
                                 headers={"Accept": accept, "User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def look(timeout=4.0):
    """{"kind", "local", "remote", "available", "from"}, or None when the other side did not answer in time."""
    k = kind()
    info = {"kind": k, "local": "", "remote": "", "available": False, "from": UPSTREAM}
    if k == "unknown":
        return info
    if k == "git":
        remote, ref = follows()
        info["from"] = out("remote", "get-url", remote) or remote
        info["local"] = out("rev-parse", "HEAD")
        info["remote"] = ls_remote(remote, ref, timeout)
    else:
        info["local"] = stamp()
        if have_git():
            info["remote"] = ls_remote(UPSTREAM, "HEAD", timeout)
        elif github_repo():
            try:
                info["remote"] = api("commits/HEAD", "application/vnd.github.sha", timeout).strip()
            except Exception:
                info["remote"] = ""
    if not SHA.fullmatch(info["remote"]) or not info["local"]:
        return None
    if info["remote"] != info["local"]:
        # a clone that already holds the other side's commit (it is ahead, or level) has nothing to get
        holds = k == "git" and git("merge-base", "--is-ancestor", info["remote"], "HEAD").returncode == 0
        info["available"] = not holds
    return info


def cmd_check() -> int:
    """The session-start look. Never raises, never blocks for long, prints only when there is something newer."""
    try:
        if not enabled():
            return 0
        now = time.time()
        nxt = read_state().get("next_check", 0)
        if now < nxt <= now + DAY:          # a time further off than a day is a changed clock: look again
            return 0
        info = look()
        if info is None:
            write_state(next_check=now + RETRY, failed=True)
            return 0
        write_state(next_check=now + DAY, **info)
        if info["available"]:
            print(f"UPDATE AVAILABLE: a newer version of this video-editing toolkit is out (this copy "
                  f"{info['local'][:7]}, latest {info['remote'][:7]}). When the user first writes, tell them in one "
                  "line and offer to update with the `update-toolkit` skill. Never update without their yes. "
                  "This look runs once a day; `python3 tools/vidkit/settings.py set updates.check false` stops it.")
    except BaseException:
        pass
    return 0


def changed_here():
    """Paths with local changes: modified, staged, deleted or untracked (ignored files are not listed)."""
    raw = git("status", "--porcelain", "-z", "--untracked-files=all").stdout
    paths, parts, i = [], raw.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        paths.append(e[3:])
        if e[0] in "RC":                    # a rename or copy carries its old path as the next field
            if i < len(parts) and parts[i]:
                paths.append(parts[i])
            i += 1
    return sorted(set(paths))


def status(timeout=20.0) -> dict:
    info = look(timeout)
    if info is None:
        sys.exit("could not reach the place this copy gets its updates from (offline, or it did not answer). "
                 "Nothing was changed.")
    info.update(behind=None, commits=[], ahead=0, local_changes=[], overlap=[], blocked=None, git_installed=have_git())
    if info["kind"] == "unknown":
        info["note"] = ("this copy carries no version: it is neither a git clone nor a download with "
                        "tools/version-stamp.txt filled in, so there is nothing to compare")
        return info
    if info["kind"] == "download":
        if info["available"]:
            info["blocked"] = "not-a-git-copy"
            try:    # best effort: what is new, from GitHub's compare (the answer to "what would I get")
                j = json.loads(api(f"compare/{info['local']}...{info['remote']}", "application/vnd.github+json", timeout))
                info["behind"] = j.get("ahead_by")
                info["commits"] = [{"id": c["sha"][:7], "subject": c["commit"]["message"].split("\n")[0]}
                                   for c in j.get("commits", [])][-50:]
            except Exception:
                pass
        return info
    if not info["available"]:
        info["behind"] = 0
        return info
    remote, ref = follows()
    r = git("fetch", "--quiet", remote, ref, timeout=300)
    if r.returncode or git("cat-file", "-e", info["remote"] + "^{commit}").returncode:
        sys.exit(f"git fetch {remote} failed: {r.stderr.strip()[-300:] or 'the new commit did not arrive'}. "
                 "Nothing was changed.")
    log = out("log", "--format=%h%x09%s", f"HEAD..{info['remote']}")
    info["commits"] = [dict(zip(("id", "subject"), l.split("\t", 1))) for l in log.splitlines() if l][:50]
    info["behind"] = len(log.splitlines())
    info["ahead"] = int(out("rev-list", "--count", f"{info['remote']}..HEAD") or 0)
    theirs = out("diff", "--name-only", f"HEAD...{info['remote']}") or out("diff", "--name-only", "HEAD", info["remote"])
    info["local_changes"] = changed_here()
    info["overlap"] = sorted(set(info["local_changes"]) & set(theirs.splitlines()))
    info["blocked"] = "diverged" if info["ahead"] else "overlap" if info["overlap"] else None
    return info


def convert(sha) -> None:
    """A download copy -> a git clone at the commit it was made from. No file in the folder changes; on any failure
    the .git folder this made is removed again, so the copy is as it was."""
    if (ROOT / ".git").exists():
        raise Blocked(f"{ROOT / '.git'} already exists")
    if git("rev-parse", "--is-inside-work-tree").returncode == 0:
        raise Blocked(f"{ROOT} sits inside another git repository; move the toolkit out of it first")

    def must(*args, timeout=300):
        r = git(*args, timeout=timeout)
        if r.returncode:
            raise Blocked(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[-300:]}")
        return r.stdout.strip()
    try:
        must("init", "-q")
        must("remote", "add", "origin", UPSTREAM)
        must("fetch", "-q", "origin")
        if git("cat-file", "-e", sha + "^{commit}").returncode:
            git("fetch", "-q", "origin", sha, timeout=300)      # a commit no branch holds any more
        if git("cat-file", "-e", sha + "^{commit}").returncode:
            raise Blocked(f"the commit this copy was made from ({sha[:7]}) is no longer available from {UPSTREAM}")
        m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD", out("ls-remote", "--symref", "origin", "HEAD"), re.M)
        branch = m.group(1) if m else "main"
        must("symbolic-ref", "HEAD", f"refs/heads/{branch}")
        must("update-ref", f"refs/heads/{branch}", sha)
        must("reset", "-q")                                  # the index becomes that commit; the files stay as they are
        must("checkout", "-q", "--", "tools/version-stamp.txt")   # the one file the download itself rewrote
        git("branch", "-q", "--set-upstream-to", f"origin/{branch}")
    except BaseException:
        shutil.rmtree(ROOT / ".git", ignore_errors=True)
        raise


def after(changed) -> list:
    notes = []
    if any(p.startswith(".claude/") for p in changed):
        notes.append("skills, agents or hooks changed: they load in a new Claude session")
    if any(p.startswith(".claude/agents/") for p in changed):
        notes.append("agents changed: if the user is on Claude Max, run `python3 tools/agent_models.py apply` again")
    apps = sorted({p.split("/")[1] for p in changed if re.match(r"apps/[^/]+/(prebuilt|Sources)/", p)})
    if apps:
        notes.append(f"app(s) changed ({', '.join(apps)}): a copy installed in Applications is still the old one; "
                     "`apps/install_apps.sh` installs the new one (ask first)")
    return notes


def cmd_apply(do_convert) -> int:
    info = status()
    if info["kind"] == "unknown" or not info["available"]:
        print(json.dumps(dict(info, updated=False), indent=1))
        return 0
    if info["kind"] == "download":
        if not do_convert:
            print(json.dumps(dict(info, updated=False), indent=1))
            return 3
        if not have_git():
            print(json.dumps(dict(info, updated=False, blocked="git-missing"), indent=1))
            print("git is needed to update a downloaded copy and is not installed. macOS: xcode-select --install; "
                  "Windows: winget install Git.Git; Linux: the distribution's git package. Ask the user first.",
                  file=sys.stderr)
            return 5
        try:
            convert(info["local"])
        except Blocked as e:
            print(json.dumps(dict(info, updated=False, blocked="convert-failed", why=str(e)), indent=1))
            return 1
        info = dict(status(), converted=True)
    if info["blocked"]:
        print(json.dumps(dict(info, updated=False), indent=1))
        return 3
    before = info["local"]
    r = git("merge", "--ff-only", "--quiet", info["remote"], timeout=300)
    if r.returncode:
        print(json.dumps(dict(info, updated=False, why=r.stderr.strip()[-400:]), indent=1))
        return 1
    changed = out("diff", "--name-only", before, info["remote"]).splitlines()
    write_state(next_check=time.time() + DAY, kind="git", local=info["remote"], remote=info["remote"], available=False)
    print(json.dumps(dict(info, updated=True, blocked=None, **{"from": before, "to": info["remote"]}, changed=changed,
                          after=after(changed), undo=f"git -C {ROOT} reset --keep {before}"), indent=1))
    return 0


def main(argv) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "check" and len(argv) == 1:
        return cmd_check()
    if cmd == "status" and len(argv) == 1:
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "apply" and set(argv[1:]) <= {"--convert"}:
        return cmd_apply("--convert" in argv)
    print(__doc__, file=sys.stderr)
    return 0 if cmd in ("-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
