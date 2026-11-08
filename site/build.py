#!/usr/bin/env python3
"""Build the project page's skill list from the skills themselves.

  python3 site/build.py            refresh the generated parts of site/index.html in place
  python3 site/build.py --check    exit 1 if site/index.html is out of date (nothing written)
  python3 site/build.py --out DIR  write the publishable site to DIR (the Pages workflow runs this)

Every folder in .claude/skills/ with a SKILL.md becomes a card, so the page lists exactly what
`/skills` lists. site/cards.json gives a card its group, a one-line summary, a "just say" example and
an optional badge; a skill missing from it still shows up, under "More", with the first sentence of
its own description. Generated parts of index.html sit between <!-- gen:NAME --> and
<!-- /gen:NAME --> markers: skills, terminal, n-skills, n-agents.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
REPO = SITE.parent
SKILLS = REPO / ".claude" / "skills"
AGENTS = REPO / ".claude" / "agents"
PAGE = SITE / "index.html"
SHIP = ("index.html", "favicon.svg", "og.png", "img")   # what --out publishes


def frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    out = {}
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def first_sentence(text: str, limit: int = 170) -> str:
    s = re.split(r"(?<=[.!?])\s|\s-\s", text, maxsplit=1)[0].strip()
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def first_quote(text: str) -> str:
    m = re.search(r'"([^"]{3,60})"', text)
    return m.group(1) if m else ""


def skills() -> list:
    out = []
    for d in sorted(SKILLS.iterdir()):
        f = d / "SKILL.md"
        if d.is_dir() and f.is_file():
            fm = frontmatter(f)
            out.append({"name": fm.get("name") or d.name, "description": fm.get("description", "")})
    return out


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_cards(found: list, data: dict) -> str:
    cards, groups = data["cards"], list(data["groups"])
    by_group = {g["id"]: [] for g in groups}
    for s in found:
        c = cards.get(s["name"])
        if c is None or c.get("group") not in by_group:
            if "more" not in by_group:
                groups.append({"id": "more", "title": "More", "blurb": "New skills land here first."})
                by_group["more"] = []
            c = {"group": "more", "line": first_sentence(s["description"]), "say": first_quote(s["description"])}
        by_group[c["group"]].append((s["name"], c))
    order = {name: i for i, name in enumerate(cards)}
    parts = []
    for g in groups:
        items = sorted(by_group[g["id"]], key=lambda t: order.get(t[0], len(order)))
        if not items:
            continue
        parts.append(f'<div class="group" id="g-{esc(g["id"])}">\n'
                     f'  <div class="group-head"><h3>{esc(g["title"])}</h3><p>{esc(g["blurb"])}</p></div>\n'
                     f'  <div class="cards">')
        for name, c in items:
            badge = f'<span class="badge">{esc(c["needs"])}</span>' if c.get("needs") else ""
            star = " star" if c.get("star") else ""
            say = (f'\n      <p class="say"><span>Just say</span> &ldquo;{esc(c["say"])}&rdquo;</p>'
                   if c.get("say") else "")
            parts.append(f'    <article class="card{star}" id="skill-{esc(name)}">\n'
                         f'      <div class="card-top"><code>{esc(name)}</code>{badge}</div>\n'
                         f'      <p>{esc(c["line"])}</p>{say}\n'
                         f'    </article>')
        parts.append("  </div>\n</div>")
    return "\n".join(parts)


def render_terminal(found: list, data: dict) -> str:
    width = max(len(s["name"]) for s in found)
    rows = []
    for s in found:
        c = data["cards"].get(s["name"], {})
        blurb = c.get("line") or first_sentence(s["description"])
        blurb = blurb if len(blurb) <= 58 else blurb[:57].rsplit(" ", 1)[0] + "…"
        rows.append(f'<span class="t-row"><b>/{esc(s["name"])}</b>{" " * (width - len(s["name"]) + 2)}'
                    f'<i>{esc(blurb)}</i></span>')
    return "\n".join(rows)


def build(page: str) -> str:
    found = skills()
    data = json.loads((SITE / "cards.json").read_text(encoding="utf-8"))
    n_agents = len([p for p in AGENTS.glob("*.md")]) if AGENTS.is_dir() else 0
    gen = {"skills": render_cards(found, data), "terminal": render_terminal(found, data),
           "n-skills": str(len(found)), "n-agents": str(n_agents)}
    for key, body in gen.items():
        pat = re.compile(r"(<!-- gen:%s -->)(.*?)(<!-- /gen:%s -->)" % (re.escape(key), re.escape(key)), re.S)
        if not pat.search(page):
            sys.exit(f"build.py: index.html has no <!-- gen:{key} --> marker")
        inline = "\n" not in body
        page = pat.sub(lambda m: m.group(1) + (body if inline else "\n" + body + "\n") + m.group(3), page)
    return page


def main(argv: list) -> int:
    page = PAGE.read_text(encoding="utf-8")
    new = build(page)
    if "--check" in argv:
        if new != page:
            print("site/index.html is out of date: run python3 site/build.py", file=sys.stderr)
            return 1
        return 0
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1]).resolve()
        if out == SITE or SITE in out.parents or out == REPO:
            sys.exit("build.py: --out must be a folder outside site/ and not the repo root")
        if out.exists() and any(out.iterdir()):
            if not (out / ".nojekyll").is_file():   # only ever replace a folder this script wrote
                sys.exit(f"build.py: {out} exists and isn't an earlier build: pick an empty or new folder")
            shutil.rmtree(out)
        out.mkdir(parents=True)
        for name in SHIP:
            src = SITE / name
            if src.is_dir():
                shutil.copytree(src, out / name)
            elif src.is_file():
                shutil.copy2(src, out / name)
        (out / "index.html").write_text(new, encoding="utf-8")
        (out / ".nojekyll").write_text("")
        print(f"site written to {out}")
        return 0
    if new != page:
        PAGE.write_text(new, encoding="utf-8")
        print("site/index.html updated")
    else:
        print("site/index.html already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
