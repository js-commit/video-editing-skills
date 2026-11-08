#!/usr/bin/env python3
"""Match the subagents' model and effort to the user's Claude plan.

    python3 tools/agent_models.py show              # each tiered agent: now, pro, max (JSON)
    python3 tools/agent_models.py apply [pro|max]   # rewrite .claude/agents/*.md frontmatter
                                                    # (no tier given: settings claude.plan)

Tiers:
  pro  Claude Pro. Opus wherever it decides the cut (a-roll editing and
       revision, multicam angles, b-roll verification); Sonnet or a lower effort
       for the batch work that reads many frames, so a long project fits the
       plan's usage limits. This is what the repo ships with.
  max  Claude Max. Opus at full effort for the frame judges and planners too.

The a-roll editor and reviser run on Opus at the highest effort on both tiers.
Only the agents in TIERS are touched; every other agent, and anything outside
the model/effort lines, is left as it is.
Exit 4 = no tier given and settings claude.plan is unset.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / ".claude" / "agents"
sys.path.insert(0, str(REPO / "tools"))

# agent: {tier: (model, effort)}
TIERS = {
    "angle-frame-judge":       {"pro": ("sonnet", "high"),   "max": ("opus", "xhigh")},
    "broll-annotator":         {"pro": ("sonnet", "high"),   "max": ("opus", "high")},
    "broll-hunt":              {"pro": ("opus", "high"),     "max": ("opus", "xhigh")},
    "footage-classifier":      {"pro": ("sonnet", "high"),   "max": ("opus", "high")},
    "frame-describer":         {"pro": ("sonnet", "medium"), "max": ("sonnet", "high")},
    "shorts-framing-director": {"pro": ("sonnet", "high"),   "max": ("opus", "xhigh")},
    "shorts-scout":            {"pro": ("opus", "high"),     "max": ("opus", "xhigh")},
}
PLANS = ("pro", "max")


def frontmatter_span(text: str):
    m = re.match(r"---\n(.*?\n)---\n", text, re.S)
    return (m.start(1), m.end(1)) if m else None


def current(name: str):
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    span = frontmatter_span(text)
    fm = text[span[0]:span[1]] if span else ""
    model = re.search(r"^model:\s*(\S+)", fm, re.M)
    effort = re.search(r"^effort:\s*(\S+)", fm, re.M)
    return (model.group(1) if model else None, effort.group(1) if effort else None)


def set_line(fm: str, key: str, value: str) -> str:
    if re.search(rf"^{key}:.*$", fm, re.M):
        return re.sub(rf"^{key}:.*$", f"{key}: {value}", fm, count=1, flags=re.M)
    return fm + f"{key}: {value}\n"


def apply(plan: str) -> list:
    changed = []
    for name, tiers in TIERS.items():
        path = AGENTS / f"{name}.md"
        if not path.is_file():
            continue
        model, effort = tiers[plan]
        if current(name) == (model, effort):
            continue
        text = path.read_text(encoding="utf-8")
        span = frontmatter_span(text)
        if not span:
            continue
        fm = set_line(set_line(text[span[0]:span[1]], "model", model), "effort", effort)
        path.write_text(text[:span[0]] + fm + text[span[1]:], encoding="utf-8")
        changed.append({"agent": name, "model": model, "effort": effort})
    return changed


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "show":
        out = {n: {"now": "/".join(map(str, current(n))),
                   **{p: "/".join(t[p]) for p in PLANS}}
               for n, t in TIERS.items() if (AGENTS / f"{n}.md").is_file()}
        print(json.dumps(out, indent=1))
        return 0
    if cmd == "apply":
        plan = rest[0] if rest else None
        if plan is None:
            from vidkit import settings
            plan = settings.get("claude.plan")
            if not plan:
                print("SETTING NOT SET: claude.plan. Ask the user which Claude plan they are on "
                      "(Claude Pro or Claude Max), save it with\n"
                      f"  python3 {REPO / 'tools/vidkit/settings.py'} set claude.plan pro|max\n"
                      "and re-run.", file=sys.stderr)
                return 4
        if plan not in PLANS:
            print(f"unknown plan {plan!r}: use pro or max", file=sys.stderr)
            return 2
        changed = apply(plan)
        print(json.dumps({"plan": plan, "changed": changed}, indent=1))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
