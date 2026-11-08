#!/usr/bin/env python3
"""Step 6: the review page. One HTML file the user opens in a browser: every
proposed move with its contact sheets, files, reason and confidence, grouped by
destination, plus the units that need their decision.

  build_review.py --plan W/plan.json --inventory W/inventory.json [-o W/review.html]

Each card has a dropdown (keep the plan, another destination, leave in place)
and a feedback box. "Copy decisions" puts the changes on the clipboard as JSON
for the user to paste into the chat (apply_decisions.py reads it). Nothing on
the page moves files. Clip names open the original in the browser's player.

stdout: the page path.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#e3e3e0;--accent:#2563eb;
--warn:#b45309;--warnbg:#fff7ed;--ok:#15803d;--chip:#eef2ff}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--card:#1f1f22;--fg:#ececee;--muted:#9a9aa0;
--line:#333338;--accent:#60a5fa;--warn:#fbbf24;--warnbg:#2a2113;--ok:#4ade80;--chip:#25283a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 80px}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.muted{color:var(--muted)}.note{background:var(--warnbg);border:1px solid var(--line);border-radius:8px;
padding:10px 12px;margin:14px 0}table{border-collapse:collapse;width:100%}td,th{text-align:left;
padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}
.card.undecided{border-color:var(--warn)}.head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.key{font-weight:600}.chip{background:var(--chip);border-radius:20px;padding:1px 9px;font-size:13px}
.conf-high{color:var(--ok)}.conf-medium{color:var(--accent)}.conf-low{color:var(--warn)}
.path{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;word-break:break-all;cursor:copy}
.sheets{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.sheets figure{margin:0;width:260px}
.sheets img{width:260px;border-radius:6px;display:block;background:#0003}
.sheets figcaption{font-size:12px;color:var(--muted);word-break:break-all}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}select,textarea,button{font:inherit;
color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
textarea{flex:1;min-width:240px;height:38px}button{cursor:pointer}.primary{background:var(--accent);
color:#fff;border-color:var(--accent)}#out{width:100%;height:120px;display:none;margin-top:8px}
.bar{position:sticky;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;
display:flex;gap:10px;align-items:center;justify-content:center;flex-wrap:wrap}
a{color:var(--accent)}@media (max-width:600px){.sheets figure,.sheets img{width:100%}}
"""

JS = """
function collect(){const d={};document.querySelectorAll('.card').forEach(c=>{const k=c.dataset.key;
const s=c.querySelector('select').value;const f=c.querySelector('textarea').value.trim();
if(s!=='keep'||f){d[k]={choice:s};if(f)d[k].feedback=f;}});return d;}
function copyDecisions(){const d=collect();const txt=Object.keys(d).length?JSON.stringify(d,null,1):'approved';
const out=document.getElementById('out');out.value=txt;out.style.display='block';out.select();
(navigator.clipboard?navigator.clipboard.writeText(txt):Promise.reject()).then(()=>{
document.getElementById('msg').textContent='Copied. Paste it into the chat with Claude.';},()=>{
document.execCommand&&document.execCommand('copy');document.getElementById('msg').textContent=
'Select the text below and copy it (Cmd+C / Ctrl+C), then paste it into the chat.';});}
document.addEventListener('click',e=>{if(e.target.classList.contains('path')){
navigator.clipboard&&navigator.clipboard.writeText(e.target.textContent);e.target.title='copied';}});
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def fmt_dur(s) -> str:
    if not s:
        return ""
    s = float(s)
    return f"{int(s // 60)}:{int(s % 60):02d}" if s >= 60 else f"{s:.1f}s"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    plan, inv = C.load_json(a.plan), C.load_json(a.inventory)
    work = Path(inv["work_dir"])
    out = Path(a.out) if a.out else work / "review.html"
    mpath = work / "sheets" / "manifest.json"
    manifest = C.load_json(mpath) if mpath.exists() else {}
    files = {f["path"]: f for u in inv["units"] for f in u["files"]}
    units = {u["id"]: u for u in inv["units"]}
    content = plan.get("content", {})
    projects = [p["name"] for p in inv["projects"]]

    def options(current_label):
        opts = [("keep", f"Keep: {current_label}")]
        opts += [(f"project:{p}", f"Project: {p}") for p in projects]
        opts += [("project:new", "A new project (name it in the feedback box)"), ("home-videos", "Home videos"),
                 ("broll-library", "B-roll library"), ("trash", "Trash (_trash folder)"),
                 ("skip", "Leave it where it is")]
        return "".join(f'<option value="{esc(v)}">{esc(t)}</option>' for v, t in opts)

    def card(item, kind):
        u = units[item["unit_id"]]
        fl = [files[p] for p in item["files"] if p in files]
        if kind == "move":
            label = f"{item['destination']}" + (f" / {item['project']}" if item.get("project") else "")
            head = (f'<span class="chip">{esc(label)}{" (new)" if item.get("new_project") else ""}</span>'
                    f'<span class="conf-{esc(item["confidence"])}">{esc(item["confidence"])} confidence</span>')
            where = f'<div class="path" title="click to copy">{esc(item["dest_dir"])}</div>'
            why = esc(item.get("reason"))
        else:
            label = "undecided" + (f" (suggested: {item['suggestion']})" if item.get("suggestion") else "")
            head = f'<span class="chip">{esc(label)}</span>'
            where = ""
            why = esc(item.get("notes"))
        sheets = []
        for f in fl[:24]:
            m = manifest.get(f["id"])
            img = (f'<img loading="lazy" src="{esc(Path(m["sheet"]).relative_to(work).as_posix())}" alt="">'
                   if m and Path(m["sheet"]).is_relative_to(work) else "") if m else ""
            cap = (f'<a href="file://{quote(f["path"])}" target="_blank">{esc(f["rel"])}</a> '
                   f'{esc(fmt_dur(f.get("duration")))} {esc(f["capture_time"][:16].replace("T", " "))}'
                   + (f'<br>{esc(content[f["path"]])}' if f["path"] in content else ""))
            sheets.append(f"<figure>{img}<figcaption>{cap}</figcaption></figure>")
        more = f'<div class="muted">+ {len(fl) - 24} more files</div>' if len(fl) > 24 else ""
        return (f'<div class="card {"undecided" if kind != "move" else ""}" data-key="{esc(item["key"])}">'
                f'<div class="head"><span class="key">{esc(item["key"])}</span>{head}'
                f'<span class="muted">{esc(u["device"])} &middot; {esc(u["first"][:16].replace("T", " "))} &middot; '
                f'{len(fl)} files &middot; {esc(C.human_bytes(item["bytes"]))}</span></div>{where}'
                f'<div>{why}</div><div class="sheets">{"".join(sheets)}</div>{more}'
                f'<div class="controls"><select>{options(label)}</select>'
                f'<textarea placeholder="Feedback for Claude (optional): rename, split, re-check...">'
                f'</textarea></div></div>')

    by_dest = {}
    for m in plan["moves"]:
        by_dest.setdefault(m["destination"], []).append(m)
    summary_rows = "".join(
        f"<tr><td>{esc(d)}</td><td>{len(ms)}</td><td>{sum(len(m['files']) for m in ms)}</td>"
        f"<td>{esc(C.human_bytes(sum(m['bytes'] for m in ms)))}</td></tr>" for d, ms in by_dest.items())
    undecided = plan["needs_decision"] + plan.get("unclassified", [])
    longest = sorted((f for f in files.values() if f.get("duration")), key=lambda f: -f["duration"])[:10]
    long_rows = "".join(f"<tr><td>{esc(f['rel'])}</td><td>{esc(fmt_dur(f['duration']))}</td>"
                        f"<td>{esc(f['device'])}</td></tr>" for f in longest)
    problems = "".join(f"<li>{esc(p)}</li>" for p in plan.get("problems", []))
    sections = []
    if undecided:
        sections.append(f"<h2>Needs your decision ({len(undecided)})</h2>" + "".join(card(x, "undecided") for x in undecided))
    for d in ("project", "home-videos", "broll-library", "trash"):
        if d in by_dest:
            sections.append(f"<h2>{esc(d)} ({len(by_dest[d])})</h2>" + "".join(card(m, "move") for m in by_dest[d]))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Footage triage review</title>
<style>{CSS}</style></head><body><main>
<h1>Footage triage review</h1>
<div class="muted">From <span class="path">{esc(plan['input_dir'])}</span> &middot; {inv['totals']['files']} files,
{esc(C.human_bytes(inv['totals']['bytes']))}</div>
<div class="note">Nothing has moved yet. Check each card; change a destination with its dropdown or write
feedback, then press <b>Copy decisions</b> and paste the result into the chat (or just tell Claude
"approved"). Claude shows the final move list and asks once more before moving anything. Nothing is
deleted: "trash" moves files to <span class="path">{esc(plan['trash_dir'])}</span>, which you empty yourself.</div>
{f'<div class="note"><b>Problems to fix first:</b><ul>{problems}</ul></div>' if problems else ''}
<h2>Summary</h2><table><tr><th>Destination</th><th>Moves</th><th>Files</th><th>Size</th></tr>{summary_rows}
<tr><td>needs your decision</td><td>{len(undecided)}</td><td>{sum(len(x['files']) for x in undecided)}</td>
<td>{esc(C.human_bytes(sum(x['bytes'] for x in undecided)))}</td></tr></table>
<h2>Longest clips</h2><p class="muted">A long clip is usually a talking-head take, sometimes a camera
left running: worth a glance.</p><table>{long_rows}</table>
{''.join(sections)}
</main><div class="bar"><button class="primary" onclick="copyDecisions()">Copy decisions</button>
<span id="msg" class="muted"></span><textarea id="out" readonly></textarea></div>
<script>{JS}</script></body></html>"""
    out.write_text(page, encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
