#!/usr/bin/env python3
"""Tests for tools/update.py. No network: the "other side" is a bare git repository in a temporary folder.

    python3 -B tools/tests/test_update.py

Builds a small toolkit (this update.py, the version stamp, .gitattributes) with two versions, then checks a git
clone and a downloaded copy (git archive, which fills in the stamp the way GitHub's download does) through check,
status and apply: the notice, the once-a-day limit, the off switch, silence when offline, a fast-forward that keeps
the user's own edits, the refusals (overlap, a copy that is ahead, a download without --convert), and --convert.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("VES_", "GIT_"))}
ENV.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
failed = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failed.append(what)


def sh(*cmd, cwd=None, env=None):
    r = subprocess.run(cmd, cwd=cwd, env=dict(ENV, **(env or {})), capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{' '.join(map(str, cmd))} failed:\n{r.stderr}")
    return r.stdout.strip()


def up(copy, *args, env=None):
    """Run a copy's own update.py -> (exit code, stdout, parsed JSON or None)."""
    r = subprocess.run([sys.executable, "-B", str(copy / "tools" / "update.py"), *args],
                       env=dict(ENV, **(env or {})), capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
    except ValueError:
        j = None
    return r.returncode, r.stdout.strip(), j


def hook(copy, env=None):
    r = subprocess.run([sys.executable, "-B", str(copy / "tools" / "first_run.py")],
                       env=dict(ENV, **(env or {})), capture_output=True, text=True)
    return r.returncode, r.stdout


def due(copy):
    (copy / "user" / "update-check.json").unlink(missing_ok=True)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="update-test-"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(failed)} failed" if failed else "\nall passed")
    return 1 if failed else 0


def run(tmp):
    bare, work = tmp / "upstream.git", tmp / "work"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh("git", "clone", "-q", str(bare), str(work))
    (work / "tools").mkdir()
    (work / "user").mkdir()
    for f in ("update.py", "first_run.py", "version-stamp.txt"):
        shutil.copy(REPO / "tools" / f, work / "tools" / f)
    (work / ".gitattributes").write_text("tools/version-stamp.txt export-subst\n")
    (work / ".gitignore").write_text("user/*\n!user/README.md\n__pycache__/\n")
    (work / "user" / "README.md").write_text("yours\n")
    (work / "skill.md").write_text("step one\n")
    (work / "other.md").write_text("other\n")
    sh("git", "checkout", "-q", "-b", "main", cwd=work)
    sh("git", "add", "-A", cwd=work)
    sh("git", "commit", "-q", "-m", "version one", cwd=work)
    sh("git", "push", "-q", "origin", "main", cwd=work)
    one = sh("git", "rev-parse", "HEAD", cwd=work)

    clone = tmp / "clone"
    sh("git", "clone", "-q", str(bare), str(clone))
    dl = tmp / "download"
    dl.mkdir()
    sh("git", "archive", "-o", str(tmp / "one.tar"), "HEAD", cwd=work)
    with tarfile.open(tmp / "one.tar") as t:
        try:
            t.extractall(dl, filter="data")
        except TypeError:               # a Python older than the filter argument
            t.extractall(dl)
    check((dl / "tools" / "version-stamp.txt").read_text().strip() == one, "a download carries the commit it was made from")
    check((clone / "tools" / "version-stamp.txt").read_text().strip() == "$Format:%H$", "a clone's stamp stays a template")
    U = {"VES_UPDATE_UPSTREAM": str(bare)}

    # ---- level with the other side: silence
    rc, text, _ = up(clone, "check")
    check(rc == 0 and text == "", "clone, nothing new: check is silent")
    rc, text, _ = up(dl, "check", env=U)
    check(rc == 0 and text == "", "download, nothing new: check is silent")
    rc, _, j = up(clone, "status")
    check(rc == 0 and j["kind"] == "git" and not j["available"] and j["behind"] == 0, "clone status: up to date")

    # ---- version two arrives
    (work / "skill.md").write_text("step one\nstep two\n")
    (work / "new.md").write_text("new\n")
    sh("git", "commit", "-q", "-am", "skill: step two", cwd=work)
    sh("git", "add", "-A", cwd=work)
    sh("git", "commit", "-q", "-m", "a new file", cwd=work)
    sh("git", "push", "-q", "origin", "main", cwd=work)
    two = sh("git", "rev-parse", "HEAD", cwd=work)

    rc, text, _ = up(clone, "check")
    check(text == "", "the look is not repeated within a day")
    due(clone)
    rc, text, _ = up(clone, "check", env={"VES_UPDATES_CHECK": "false"})
    check(text == "" and not (clone / "user" / "update-check.json").exists(), "updates.check false: no look at all")
    (clone / "user" / "settings.json").write_text('{"updates": {"check": false}}')
    rc, text, _ = up(clone, "check")
    check(text == "", "the settings file switches it off too")
    (clone / "user" / "settings.json").unlink()
    rc, text, _ = up(clone, "check")
    check("UPDATE AVAILABLE" in text and one[:7] in text and two[:7] in text, "clone behind: one line for Claude")
    due(clone)
    rc, text = hook(clone)
    check(rc == 0 and "FIRST RUN" in text and "UPDATE AVAILABLE" in text, "the session-start hook carries it")
    rc, text = hook(clone)
    check(rc == 0 and "FIRST RUN" in text and "UPDATE" not in text, "and says it once a day")

    # ---- offline: silent, and it tries again within the hour rather than the day
    off = tmp / "offline"
    sh("git", "clone", "-q", str(bare), str(off))
    sh("git", "remote", "set-url", "origin", str(tmp / "gone.git"), cwd=off)
    rc, text, _ = up(off, "check")
    st = json.loads((off / "user" / "update-check.json").read_text())
    check(rc == 0 and text == "" and st.get("failed"), "the other side unreachable: silent")
    rc, text = hook(off)
    check(rc == 0 and "FIRST RUN" in text, "the hook still reports the setup state when the look fails")

    # ---- clone: the user's edit elsewhere rides along; an edit to an updated file blocks
    (clone / "other.md").write_text("other, changed by the user\n")
    (clone / "user" / "settings.json").write_text("{}")
    rc, _, j = up(clone, "status")
    check(j["available"] and j["behind"] == 2 and [c["subject"] for c in j["commits"]] == ["a new file", "skill: step two"]
          and j["local_changes"] == ["other.md"] and j["blocked"] is None, "status lists what is new and the user's own changes")
    (clone / "skill.md").write_text("step one, my way\n")
    rc, _, j = up(clone, "apply")
    check(rc == 3 and j["blocked"] == "overlap" and j["overlap"] == ["skill.md"] and not j["updated"]
          and sh("git", "rev-parse", "HEAD", cwd=clone) == one, "an edit to a file the update changes: blocked, nothing moved")
    (clone / "new.md").write_text("mine, untracked\n")
    sh("git", "checkout", "-q", "--", "skill.md", cwd=clone)
    rc, _, j = up(clone, "apply")
    check(rc == 3 and j["overlap"] == ["new.md"], "an untracked file the update would add: blocked too")
    (clone / "new.md").unlink()
    rc, _, j = up(clone, "apply")
    undo = (j or {}).get("undo", "")
    check(rc == 0 and j["updated"] and j["to"] == two and sorted(j["changed"]) == ["new.md", "skill.md"]
          and (clone / "skill.md").read_text() == "step one\nstep two\n"
          and (clone / "other.md").read_text() == "other, changed by the user\n"
          and (clone / "user" / "settings.json").read_text() == "{}", "apply: fast-forward, the user's edit and user/ kept")
    rc, _, j = up(clone, "apply")
    check(rc == 0 and not j["updated"] and not j["available"], "apply again: nothing to do")
    sh(*shlex.split(undo))
    check(sh("git", "rev-parse", "HEAD", cwd=clone) == one and "changed by the user" in (clone / "other.md").read_text(),
          "the printed undo goes back and keeps the user's edit")

    # ---- a clone with its own commit
    sh("git", "commit", "-q", "-am", "my own change", cwd=clone)
    rc, _, j = up(clone, "apply")
    check(rc == 3 and j["blocked"] == "diverged" and j["ahead"] == 1, "a copy with its own commits: blocked as diverged")
    sh("git", "merge", "-q", "--no-edit", two, cwd=clone)
    due(clone)
    rc, text, _ = up(clone, "check")
    check(text == "", "a clone that already holds the latest commit is up to date, though ahead")

    # ---- download copy
    due(dl)
    rc, text, _ = up(dl, "check", env=U)
    check("UPDATE AVAILABLE" in text, "download behind: one line for Claude")
    (dl / "other.md").write_text("other, changed by the user\n")
    (dl / "user" / "preferences.md").write_text("- mine\n")
    rc, _, j = up(dl, "apply", env=U)
    check(rc == 3 and j["blocked"] == "not-a-git-copy" and not (dl / ".git").exists(), "download: apply waits for --convert")
    rc, _, j = up(dl, "apply", "--convert", env=dict(U, VES_UPDATE_NO_GIT="1"))
    check(rc == 1 and j is None and not (dl / ".git").exists(),
          "no git and the other side is not GitHub: it cannot look, and says so; nothing changed")
    gone = dict(U, VES_UPDATE_UPSTREAM=str(tmp / "gone.git"))
    rc, _, _ = up(dl, "apply", "--convert", env=gone)
    check(rc != 0 and not (dl / ".git").exists(), "the other side unreachable: nothing changed")
    rc, _, j = up(dl, "apply", "--convert", env=U)
    check(rc == 0 and j["updated"] and j.get("converted") and j["from"] == one and j["to"] == two
          and (dl / "skill.md").read_text() == "step one\nstep two\n" and (dl / "new.md").is_file()
          and (dl / "other.md").read_text() == "other, changed by the user\n"
          and (dl / "user" / "preferences.md").read_text() == "- mine\n",
          "download: --convert makes it a clone and updates it; the user's edit and user/ kept")
    check(sh("git", "status", "--porcelain", cwd=dl) == "M other.md"
          and (dl / "tools" / "version-stamp.txt").read_text().strip() == "$Format:%H$"
          and sh("git", "rev-parse", "--abbrev-ref", "@{upstream}", cwd=dl) == "origin/main",
          "afterwards it is an ordinary clone: only the user's edit is a local change")
    rc, _, j = up(dl, "status")
    check(rc == 0 and j["kind"] == "git" and not j["available"], "and it is up to date")

    # ---- a download whose commit is gone, and a copy with no version at all
    lost = tmp / "lost"
    shutil.copytree(work, lost, ignore=shutil.ignore_patterns(".git"))
    (lost / "tools" / "version-stamp.txt").write_text("0" * 40 + "\n")
    rc, _, j = up(lost, "apply", "--convert", env=U)
    check(rc == 1 and j["blocked"] == "convert-failed" and not (lost / ".git").exists(),
          "a download whose commit no longer exists: refused, the folder left as it was")
    (lost / "tools" / "version-stamp.txt").write_text("$Format:%H$\n")
    rc, text, _ = up(lost, "check", env=U)
    rc2, _, j = up(lost, "status", env=U)
    check(text == "" and rc2 == 0 and j["kind"] == "unknown" and not j["available"], "a copy with no version: silent, and status says so")


if __name__ == "__main__":
    sys.exit(main())
