#!/usr/bin/env python3
"""picks.json -> a frame-exact cut list on the music's beat grid (work/cut_vN.json).

  beat_walk.py PROJECT [--version N] [--picks work/picks.json]

make_draft.py runs this for you; run it alone to check lengths before rendering.

picks.json (Claude or the picker agents write it; every key but clip/in_s/dur is optional):
{
  "music_lufs": -20,          level of every cue under the master (montage-music: quieter moods a few LU lower)
  "bed_db": 0,                default level offset of the clips' own sound
  "sections": [               one per chapter (a day, an event, the teaser), in story order
    {"title": "Teaser",
     "music": "Song.mp3",     a file in the project's audio folder or settings paths.music_dir, or a full path.
                              Neighbouring sections naming the same file play it as ONE continuous cue.
     "in_s": 6.0,             where the cue starts in the track (snapped to the nearest beat unless "snap_in": false)
     "end_at": 71.5,          instead of in_s: end the cue at this track second (the track's own ending
                              lands on the last shot: a natural ending instead of a fade)
     "lufs": -19, "fade_in": 0, "fade_out": 1.2, "tail": 0.3 (overlap under the next cue),
     "grid": "auto" | "beats" | "grid"   detected beats, or the uniform grid (auto: grid when irregular)
     "cuts": [
       {"clip": "<id from clips.json>", "in_s": 3.2, "dur": 2.5, "note": "what it shows [tags]",
        "beats": 5,           exact length in beats instead of dur
        "zoom": {"z": 1.2, "cx": 0.5, "cy": 0.4},   punch in about a point (0-1 of the frame)
        "fit": "cover" | "blur" | "pad"             portrait / odd-aspect shots: blur-fill by default
        "bed": false, "bed_db": -6,                 the clip's own sound: off (rare), or lower / louder
        "j": 0.5, "l": 0.5,   J-cut: hear this shot's sound 0.5 s before you see it; L-cut: let it run on
        "stabilize": true,    run stabilize-clips on this shot (the user called it shaky)
        "moment": {"in_s": 4.0, "out_s": 5.6, "duck": true, "speech": true, "gain_db": 0, "note": "'look!'"}},
       {"photo": "<id>", "dur": 3.0, "note": "..."}   a still as a slow push-in (last resort)
     ]}]}

Rules the walk applies: every cut starts on a beat; its length is a whole number of beats
(min 2) nearest its dur; the very last shot is held for its dur (not snapped) while the music
ends. A cut that would run past the end of its clip starts a little earlier, else loses a beat.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hv  # noqa: E402
from hv import media, settings  # noqa: E402

ANALYZE = hv.SKILLS / "montage-music" / "scripts" / "analyze.py"
HOLD_MAX = 4.0


def find_music(p: Path, name: str) -> str:
    q = Path(name).expanduser()
    if q.is_absolute():
        if q.is_file():
            return str(q)
        hv.die(f"music file not found: {q}")
    cands = [p / settings.layout("audio") / name, p / name]
    mdir = settings.get_path("paths.music_dir")
    if mdir:
        cands.append(mdir / name)
    for c in cands:
        if c.is_file():
            return str(c.resolve())
    if mdir and mdir.is_dir():
        hits = [f for f in mdir.rglob(Path(name).name) if f.is_file()]
        if hits:
            return str(hits[0].resolve())
    hv.die(f"music {name!r} not found in {', '.join(str(c.parent) for c in cands)}"
           + ("" if mdir else " (settings paths.music_dir is unset)"))


def analysis(p: Path, track: str) -> dict:
    out = hv.work(p) / "music" / f"{Path(track).stem}.beats.json"
    if not out.exists() or out.stat().st_mtime < Path(track).stat().st_mtime:
        hv.log(f"analysing {Path(track).name} (montage-music)")
        r = subprocess.run([sys.executable, "-B", str(ANALYZE), track, "--out", str(out)], capture_output=True, text=True)
        if r.returncode:
            hv.die(f"music analysis failed for {track}:\n{r.stderr[-600:]}")
    return hv.load_json(out)


def merged_cues(sections: list) -> list:
    """Neighbouring sections with the same music become one cue (2-3 songs for a whole video)."""
    cues = []
    for s in sections:
        if cues and cues[-1]["music"] == s["music"] and not s.get("new_cue"):
            c = cues[-1]
            c["sections"].append(s)
            for k in ("end_at", "fade_out", "tail"):
                if k in s:
                    c[k] = s[k]
        else:
            cues.append({**{k: v for k, v in s.items() if k != "cuts"}, "sections": [s]})
    return cues


def source_dur(p: Path, c: dict, cache: dict) -> float:
    f = c["_file"]
    if f not in cache:
        cache[f] = 1e9 if c.get("photo") else media.duration(f)
    return cache[f]


def build(p: Path, picks: dict, version: int) -> tuple:
    cfg = hv.project_cfg(p)
    W, H = hv.canvas(cfg)
    fps = int(cfg.get("fps", 30))
    warn = []
    durs = {}
    secs = picks.get("sections") or hv.die("picks.json has no sections")
    for s in secs:
        if not s.get("cuts"):
            hv.die(f"section {s.get('title')!r} has no cuts")
        if not s.get("music"):
            hv.die(f"section {s.get('title')!r} has no music: every chapter gets its cue before a draft")
        for c in s["cuts"]:
            c["_section"] = s.get("title", "")
            if c.get("photo"):
                c["_file"] = hv.clip_path(p, c["photo"])
            elif c.get("file"):
                c["_file"] = str(Path(c["file"]).expanduser().resolve())
            else:
                c["_file"] = hv.clip_path(p, c["clip"])
            if "dur" not in c and "beats" not in c:
                hv.die(f"cut {c.get('note') or c.get('clip')!r}: needs dur or beats")
    cues = merged_cues(secs)
    all_cuts = [c for s in secs for c in s["cuts"]]
    last_cut = all_cuts[-1]
    t = 0.0
    out_cuts, out_cues = [], []
    for ci, cue in enumerate(cues):
        track = find_music(p, cue["music"])
        A = analysis(p, track)
        mode = cue.get("grid", "auto")
        grid = A["beats"] if mode == "beats" or (mode == "auto" and A["interval_cv"] <= 0.06) else A["grid"]
        if len(grid) < 8:
            hv.die(f"{Path(track).name}: only {len(grid)} beats found - pick a track with a pulse, or set \"grid\": \"grid\"")
        period = A.get("period") or (grid[-1] - grid[0]) / (len(grid) - 1)
        cuts = [c for s in cue["sections"] for c in s["cuts"]]
        last = ci == len(cues) - 1
        hold = cuts[-1] if last and cuts[-1] is last_cut else None
        walk = cuts[:-1] if hold else cuts

        def nb(c):
            return int(c["beats"]) if c.get("beats") else max(2, round(float(c["dur"]) / period))
        hold_s = min(HOLD_MAX, float(hold.get("dur", picks.get("hold_last_s", 2.5)))) if hold else 0.0
        total_beats = sum(nb(c) for c in walk)
        if cue.get("end_at") is not None:
            end_at = float(cue["end_at"])
            i0 = min(range(len(grid)), key=lambda i: abs(grid[i] - (end_at - total_beats * period - hold_s)))
            for _ in range(4):                       # re-measure on the real grid until it holds
                if i0 + total_beats >= len(grid):
                    break
                want = end_at - (grid[i0 + total_beats] - grid[i0]) - hold_s
                j = min(range(len(grid)), key=lambda i: abs(grid[i] - want))
                if j == i0:
                    break
                i0 = j
            in_s = grid[i0]
        else:
            in_s = float(cue.get("in_s", 0.0))
            if cue.get("snap_in", True):
                in_s = min(grid, key=lambda b: abs(b - in_s))
            i0 = next((i for i, b in enumerate(grid) if b >= in_s - 1e-6), None)
            if i0 is None:
                hv.die(f"{Path(track).name}: in_s {in_s} is past the last beat")
        t0 = t
        i = i0
        for k, c in enumerate(walk):
            n = nb(c)
            if i + n >= len(grid):
                hv.die(f"{Path(track).name} runs out of beats at cut {c.get('note')!r} ({len(walk) - k} cuts left): "
                       "start the cue earlier (in_s), use a longer track, or move cuts to the next cue")
            a = t0 + (grid[i] - in_s) if k else t0
            b = t0 + (grid[i + n] - in_s)
            L = b - a
            src_in = float(c.get("in_s", 0.0))
            sd = source_dur(p, c, durs)
            while src_in + L > sd - 0.05:
                over = src_in + L - (sd - 0.05)
                if over <= 0.6 and src_in - over >= 0:
                    src_in = round(src_in - over, 3)
                    warn.append(f"cut {c.get('note', '')[:40]!r}: started {over:.2f}s earlier to fit the beat")
                    break
                if n <= 1:
                    hv.die(f"cut {c.get('note')!r}: {src_in}+{L:.2f}s is longer than its clip ({sd:.2f}s)")
                n -= 1
                b = t0 + (grid[i + n] - in_s)
                L = b - a
                warn.append(f"cut {c.get('note', '')[:40]!r}: one beat shorter, the clip ends")
            out_cuts.append(cut_entry(c, src_in, L, a))
            i += n
        sec_end = t0 + (grid[i] - in_s)
        if hold:
            src_in = float(hold.get("in_s", 0.0))
            sd = source_dur(p, hold, durs)
            hold_s = min(hold_s, sd - 0.05 - src_in)
            out_cuts.append(cut_entry(hold, src_in, hold_s, sec_end))
            sec_end += hold_s
        tail = 0.0 if last else float(cue.get("tail", 0.3))
        play = sec_end - t0
        fade_out = float(cue.get("fade_out", (0.6 if cue.get("end_at") is not None else 3.0) if last else 1.2))
        out_cues.append({"file": track, "title": " + ".join(s.get("title", "") for s in cue["sections"]),
                         "record_s": round(t0, 3), "in_s": round(in_s, 3),
                         "out_s": round(min(A["duration"], in_s + play + tail), 3),
                         "fade_in": float(cue.get("fade_in", 0.0)), "fade_out": fade_out,
                         "target_lufs": float(cue.get("lufs", picks.get("music_lufs", -20))),
                         "tempo": A["tempo"], "grid": "beats" if grid is A["beats"] else "uniform"})
        if in_s + play > A["duration"] + 0.05:
            warn.append(f"cue {Path(track).name}: the section is {play:.1f}s but only {A['duration'] - in_s:.1f}s of track "
                        "remain after in_s - silence at the end")
        t = sec_end
    end = round(t, 3)
    for k, c in enumerate(out_cuts):
        c["i"] = k
    bed, moments = [], []
    default_bed = float(picks.get("bed_db", 0.0))
    for k, c in enumerate(out_cuts):
        play = (out_cuts[k + 1]["record_s"] if k + 1 < len(out_cuts) else end) - c["record_s"]
        if c.get("bed", True) is not False and not c.get("photo"):
            j, l = float(c.get("j", 0.0)), float(c.get("l", 0.0))
            j = min(j, c["in_s"], c["record_s"])
            sd = durs.get(c["file"], 1e9)
            l = max(0.0, min(l, sd - (c["in_s"] + play)))
            bed.append({"file": c["file"], "in_s": round(c["in_s"] - j, 3), "out_s": round(c["in_s"] + play + l, 3),
                        "record_s": round(c["record_s"] - j, 3), "gain_db": float(c.get("bed_db", default_bed)),
                        "fade_in": 0.3 if j else 0.12, "fade_out": 0.3 if l else 0.12, "cut": k})
        m = c.pop("moment", None)
        if m:
            mi, mo = float(m["in_s"]), float(m["out_s"])
            if mi < c["in_s"] - 0.05 or mo > c["in_s"] + play + 0.3:
                warn.append(f"cut {k}: moment {mi}-{mo} lies outside the shot ({c['in_s']}-{c['in_s'] + play:.2f}): left out")
            else:
                moments.append({"file": c["file"], "in_s": mi, "out_s": mo, "record_s": round(c["record_s"] + mi - c["in_s"], 3),
                                "duck": bool(m.get("duck", False)), "speech": bool(m.get("speech", False)),
                                "gain_db": float(m.get("gain_db", 0.0)), "note": m.get("note", ""), "cut": k})
    job = {"schema": "home-video-cut/1", "project": cfg.get("name", p.name), "version": version,
           "width": W, "height": H, "fps": fps, "end_s": end, "privacy": cfg.get("privacy"),
           "cuts": out_cuts, "cues": out_cues, "bed": bed, "moments": moments}
    return job, warn


def cut_entry(c: dict, src_in: float, L: float, rec: float) -> dict:
    d = {"clip": c.get("clip") or c.get("photo") or Path(c["_file"]).stem, "file": c["_file"],
         "in_s": round(src_in, 3), "out_s": round(src_in + L, 3), "record_s": round(rec, 3),
         "note": c.get("note", ""), "section": c["_section"]}
    for k in ("zoom", "fit", "bed", "bed_db", "j", "l", "stabilize", "moment", "photo"):
        if k in c:
            d[k] = c[k]
    if c.get("photo"):
        d["photo"] = True
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--version", type=int, default=0, help="version number to write (default: print only)")
    ap.add_argument("--picks", help="default work/picks.json")
    a = ap.parse_args()
    try:
        p = hv.project_root(a.project)
        picks = hv.load_json(Path(a.picks) if a.picks else hv.work(p) / "picks.json")
        job, warn = build(p, picks, a.version)
    except settings.SettingMissing as e:
        settings.exit_missing(e)
    for w in warn:
        hv.log("WARN " + w)
    for c in job["cues"]:
        hv.log(f"cue {hv.tc(c['record_s'])} {Path(c['file']).name}: track {c['in_s']:.2f}-{c['out_s']:.2f}s, "
               f"{c['tempo']} BPM ({c['grid']}), {c['title']}")
    hv.log(f"{len(job['cuts'])} cuts, {hv.tc(job['end_s'])}")
    if a.version:
        out = hv.work(p) / f"cut_v{a.version}.json"
        hv.save_json(out, job)
        print(out)
    else:
        print(json.dumps({"cuts": len(job["cuts"]), "end_s": job["end_s"], "cues": len(job["cues"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
