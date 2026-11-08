#!/usr/bin/env python3
"""The talking-head recipe: load, snap to frames, flatten into picture pieces, lint, carry over a re-cut.

    recipe.py lint  <work>/recipe_vN.json [--fix]
    recipe.py carry <work>/recipe_vN.json <work>/recipe_vM.json [--out FILE]
    recipe.py show  <work>/recipe_vN.json            # every piece on the record clock

A recipe is the whole edit as JSON (schema: reference/recipe-schema.md). Record time is the finished video's clock:
the a-roll keeps laid end to end. The picture at any record frame is the b-roll brick covering it, else the a-roll;
the sound is always the a-roll (b-roll is picture only). Every time is snapped to the frame grid here, once, and the
renderer and the lint both use flatten(), so what the lint passes is exactly what renders. Overlays sit on top of
whatever plays and never change the pieces the lint judges.

lint (exit 1 on any ERROR):
  ERROR  a flash of talking head: a visible a-roll run under 0.6 s beside a brick edge (a brick starting or ending
         just off a jump cut), or under 1.1 s between two bricks - both read as flicker;
  ERROR  overlapping bricks, a brick outside the timeline or reading past its clip's end, a missing file, an overlay
         that is too short for its fades, an animated overlay at the wrong fps or shape, synced mic audio that does
         not cover a keep;
  WARN   a brick under 1.5 s, two bricks reusing the same source range, a brick whose shape differs from the frame left
         on fit "contain" (it renders with bars), a file outside the project folder (move it in, so archiving keeps it).
  --fix  stretches the neighbouring brick onto the cut (tail first, then head) when its clip has the room, frame-exact,
         writes the recipe back and re-lints.

carry: a notes round copies vN to vM and edits it with every time still on vN's clock (the clock the notes were
taken on): bricks, overlays and needs moved, added or dropped, a-roll keeps widened or removed. carry then re-places
vM's bricks, overlays and needs on vM's own a-roll clock through the SOURCE: vN record frame -> (take, source frame)
-> vM record frame. Never by adding float seconds:
summed keep lengths drift a frame or two over dozens of keeps, and that drift shows up as flashes. A brick whose start
or end moment was cut is dropped and listed (re-plan it). Writes vM in place unless --out.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from fractions import Fraction
from functools import lru_cache

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

FLASH_S, GAP_S, SHORT_BRICK_S = 0.6, 1.1, 1.5
STILL_EXT = (".png", ".jpg", ".jpeg", ".webp")


def fps_of(recipe):
    return Fraction(str(recipe.get("fps", "30")))


def size_of(recipe):
    return int(recipe.get("width", 1920)), int(recipe.get("height", 1080))


@lru_cache(None)
def probe(path):
    """(duration_s, fps Fraction, width, height) of a video, rotation applied. The duration is the VIDEO stream's when
    it has one: a phone clip's container often runs past its last frame with audio, and a brick reading into that tail
    renders frozen frames."""
    out = subprocess.run([C.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,duration:stream_side_data=rotation:format=duration",
                          "-of", "json", path], capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"ffprobe failed on {path}: {out.stderr.strip()[-300:]}")
    j = json.loads(out.stdout or "{}")
    if not j.get("streams"):
        sys.exit(f"{path}: no video stream")
    s = j["streams"][0]
    rot = next((int(d["rotation"]) for d in s.get("side_data_list") or [] if "rotation" in d), 0)
    w, h = (s["height"], s["width"]) if rot % 180 else (s["width"], s["height"])
    dur = float(j.get("format", {}).get("duration") or 0)
    if s.get("duration") not in (None, "N/A"):
        dur = min(dur, float(s["duration"])) if dur else float(s["duration"])
    return dur, Fraction(s["r_frame_rate"]), int(w), int(h)


@lru_cache(None)
def audio_duration(path):
    return float(subprocess.check_output([C.ffprobe(), "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", path]).decode().strip())


def keep_sound(recipe, k):
    """(file, source seconds) where a keep's sound starts: the take's own track, or a separately recorded mic synced to
    it by sync_audio.py ("take_audio": {take: {"file", "offset_s", "rate"}}, audio_s = offset_s + rate * take_s)."""
    t = (recipe.get("take_audio") or {}).get(k["file"])
    return (t["file"], t["offset_s"] + t["rate"] * k["in_s"]) if t else (k["file"], k["in_s"])


def aroll_frames(recipe):
    """The a-roll keeps on the record clock: [{file, in_s (frame-snapped), rec_f, n, gain_db}] on the recipe fps."""
    fps, out, rec = fps_of(recipe), [], 0
    for k in recipe["aroll"]:
        in_f, out_f = round(k["in_s"] * fps), round(k["out_s"] * fps)
        if out_f <= in_f:
            continue
        out.append({"file": k["file"], "in_s": float(in_f / fps), "rec_f": rec, "n": out_f - in_f,
                    "gain_db": float(k.get("gain_db", 0.0))})
        rec += out_f - in_f
    return out


def total_frames(recipe):
    ks = aroll_frames(recipe)
    return ks[-1]["rec_f"] + ks[-1]["n"] if ks else 0


def brick_frames(recipe):
    fps = fps_of(recipe)
    out = []
    for i, b in enumerate(recipe.get("broll", [])):
        out.append({**b, "i": i, "rec_f": round(b["record_s"] * fps), "n": round(b["dur"] * fps),
                    "speed": float(b.get("speed", 1.0))})
    return sorted(out, key=lambda b: b["rec_f"])


def flatten(recipe):
    """Picture pieces covering [0, total): {rec_f, n, file, in_s, speed, zoom, fit, kind: aroll|broll, brick: i|None}."""
    fps, keeps, bricks, F = fps_of(recipe), aroll_frames(recipe), brick_frames(recipe), total_frames(recipe)
    pieces, f = [], 0

    def aroll_span(a, b):   # a-roll pieces for record frames [a, b), split at keep boundaries
        for k in keeps:
            lo, hi = max(a, k["rec_f"]), min(b, k["rec_f"] + k["n"])
            if hi > lo:
                pieces.append({"rec_f": lo, "n": hi - lo, "file": k["file"],
                               "in_s": k["in_s"] + float((lo - k["rec_f"]) / fps),
                               "speed": 1.0, "zoom": None, "fit": None, "kind": "aroll", "brick": None})
    for b in bricks:
        s, e = max(b["rec_f"], f), min(b["rec_f"] + b["n"], F)
        if e <= s:
            continue
        aroll_span(f, s)
        pieces.append({"rec_f": s, "n": e - s, "file": b["file"],
                       "in_s": b["in_s"] + float((s - b["rec_f"]) / fps) * b["speed"],
                       "speed": b["speed"], "zoom": b.get("zoom"), "fit": b.get("fit"), "kind": "broll", "brick": b["i"]})
        f = e
    aroll_span(f, F)
    return pieces


def is_still(path):
    """An overlay file that is one picture (held for its slot), not a clip (played frame for frame from its start)."""
    return os.path.splitext(path)[1].lower() in STILL_EXT


def overlay_frames(recipe):
    fps = fps_of(recipe)
    return sorted(({**o, "i": i, "rec_f": round(o["record_s"] * fps), "n": round(o["dur"] * fps),
                    "fade_s": float(o.get("fade", 0.2))}
                   for i, o in enumerate(recipe.get("overlays", []))), key=lambda o: o["rec_f"])


def with_overlays(recipe, pieces):
    """flatten()'s pieces split at every overlay edge; each gets "ov": [(file, frame offset into the overlay, overlay
    frames, fade s)]. The renderer's view only: an overlay edge never reads as a jump cut to the lint."""
    ovs, fps = overlay_frames(recipe), fps_of(recipe)
    edges = sorted({e for o in ovs for e in (o["rec_f"], o["rec_f"] + o["n"])})
    out = []
    for p in pieces:
        a, end = p["rec_f"], p["rec_f"] + p["n"]
        for b in [e for e in edges if a < e < end] + [end]:
            out.append({**p, "rec_f": a, "n": b - a, "in_s": p["in_s"] + float((a - p["rec_f"]) / fps) * p["speed"],
                        "ov": [(o["file"], a - o["rec_f"], o["n"], o["fade_s"]) for o in ovs
                               if o["rec_f"] <= a < o["rec_f"] + o["n"]]})
            a = b
    return out


def cuts(recipe):
    """Record frames where the a-roll jumps (keep boundaries)."""
    return {k["rec_f"] for k in aroll_frames(recipe)[1:]}


def record_words(r):
    """The spoken words on THIS recipe's record clock, from each take's transcript sidecar:
    -> ([{w, s, e, k}] (k = keep index), [(rec_s, file)] for keeps with no sidecar). A word belongs to the keep
    holding its midpoint."""
    fps, out, bare, cache = fps_of(r), [], [], {}
    for i, k in enumerate(aroll_frames(r)):
        k0, k1, r0 = k["in_s"], k["in_s"] + float(k["n"] / fps), float(k["rec_f"] / fps)
        if k["file"] not in cache:
            cache[k["file"]] = C.words_of(k["file"])
        ws = cache[k["file"]]
        if ws is None:
            bare.append((r0, k["file"]))
            continue
        for w in ws:
            if k0 <= (w["start"] + w["end"]) / 2 < k1:
                out.append({"w": w["word"].strip(), "s": round(r0 + max(w["start"], k0) - k0, 3),
                            "e": round(r0 + min(w["end"], k1) - k0, 3), "k": i})
    return out, bare


# ---- source anchoring (notes rounds that change the a-roll) ----------------------------------------------------------

def frame_src(r, f):
    """record frame -> (take file, source frame on the recipe's grid), or None past the end."""
    fps = fps_of(r)
    for k in aroll_frames(r):
        if k["rec_f"] <= f < k["rec_f"] + k["n"]:
            return k["file"], round(k["in_s"] * fps) + f - k["rec_f"]
    return None


def src_frame(r, src):
    """(take file, source frame) -> record frame on r, or None when that frame is in no keep."""
    file, sf = src
    fps = fps_of(r)
    for k in aroll_frames(r):
        k0 = round(k["in_s"] * fps)
        if k["file"] == file and k0 <= sf < k0 + k["n"]:
            return k["rec_f"] + sf - k0
    return None


def map_span(old, new, f0, f1):
    """Record frames [f0, f1) on `old` -> [n0, n1) on `new` through the source, or None when an edge was cut."""
    s0, s1 = frame_src(old, f0), frame_src(old, f1 - 1)
    n0 = src_frame(new, s0) if s0 else None
    n1 = src_frame(new, s1) if s1 else None
    if n0 is None or n1 is None or n1 < n0:
        return None
    return n0, n1 + 1


def carry(old, new):
    """new's broll/overlays/needs, still timed on old's record clock, re-placed on new's own a-roll.
    -> (moved, dropped messages)."""
    fps = fps_of(new)
    frame = 1 / float(fps)
    dropped, moved = [], 0

    def place(items, key_end):
        nonlocal moved
        out = []
        for it in items:
            f0 = round(it["record_s"] * fps_of(old))
            f1 = round((it["record_s"] + it["dur"]) * fps_of(old)) if key_end == "dur" else round(it["end_s"] * fps_of(old))
            m = map_span(old, new, f0, max(f1, f0 + 1))
            if m is None:
                dropped.append(f"{C.tc(it['record_s'])} {it.get('why') or it.get('note') or os.path.basename(it.get('file', ''))}")
                continue
            n0, n1 = m
            it = dict(it)
            it["record_s"] = round(n0 * frame, 4)
            if key_end == "dur":
                it["dur"] = round((n1 - n0) * frame, 4)
            else:
                it["end_s"] = round(n1 * frame, 4)
            moved += 1
            out.append(it)
        return out
    new["broll"] = place(new.get("broll", []), "dur")
    new["overlays"] = place(new.get("overlays", []), "dur")
    new["needs"] = place(new.get("needs", []), "end")
    return moved, dropped


# ---- lint ------------------------------------------------------------------------------------------------------------

def lint(recipe, fix=False):
    """-> (errors, warnings, changed). With fix, stretches bricks in place (recipe['broll'] edited)."""
    fps = fps_of(recipe)
    fw, fh = size_of(recipe)
    errs, warns, changed = [], [], False
    F = total_frames(recipe)
    if not F:
        return ["the recipe has no a-roll keeps"], [], False

    def tc(f):
        return C.tc(float(f / fps))

    homes = [p for p in (recipe.get("project"), C.settings.get("paths.broll_library_dir"),
                         C.settings.get("nas.mount_path")) if p]
    homes = [os.path.realpath(os.path.expanduser(str(p))) for p in homes]
    for _ in range(20):   # fix loop: stretch, re-flatten, until no fixable flash is left
        errs, warns = [], []
        files = sorted({x["file"] for k in ("aroll", "broll", "overlays") for x in recipe.get(k, [])}
                       | {t["file"] for t in (recipe.get("take_audio") or {}).values()})
        for f in files:
            if not os.path.exists(f):
                continue
            if recipe.get("project") and not any(os.path.realpath(f).startswith(h + os.sep) for h in homes):
                warns.append(f"{f}: outside the project folder - move it into the project so archiving keeps it, "
                             "then re-point the recipe")
        for k in recipe["aroll"]:
            if not os.path.exists(k["file"]):
                errs.append(f"a-roll: missing file {k['file']}")
        if errs:
            break
        for k in aroll_frames(recipe):
            f, s0 = keep_sound(recipe, k)
            if f == k["file"]:
                continue
            if not os.path.exists(f):
                errs.append(f"take audio: missing file {f}")
                break
            s1 = s0 + float(k["n"] / fps) * recipe["take_audio"][k["file"]]["rate"]
            if s0 < 0 or s1 > audio_duration(f) + 0.02:
                errs.append(f"keep @ {tc(k['rec_f'])}: its sound reads {s0:.2f}-{s1:.2f}s of {os.path.basename(f)} "
                            f"({audio_duration(f):.2f}s) - the separate recorder was not running; trim the keep")
        bricks = brick_frames(recipe)
        for b in bricks:
            if not os.path.exists(b["file"]):
                errs.append(f"brick {b['i']}: missing file {b['file']}")
                continue
            dur, _, sw, sh = probe(b["file"])
            need = b["in_s"] + float(b["n"] / fps) * b["speed"]
            if b["in_s"] < 0 or need > dur + 0.02:
                errs.append(f"brick {b['i']} @ {tc(b['rec_f'])}: reads {b['in_s']:.2f}-{need:.2f}s of a {dur:.2f}s clip "
                            f"({os.path.basename(b['file'])})")
            if b["rec_f"] < 0 or b["rec_f"] + b["n"] > F:
                errs.append(f"brick {b['i']} @ {tc(b['rec_f'])}: outside the {tc(F)} timeline")
            zoomed = float((b.get("zoom") or {}).get("z", 1.0)) > 1.001
            if abs(sw / sh - fw / fh) > 0.02 and (b.get("fit") or ("cover" if zoomed else "contain")) == "contain":
                warns.append(f"brick {b['i']} @ {tc(b['rec_f'])}: {sw}x{sh} source renders with bars - "
                             "set fit cover (with a zoom focus) or blur")
            if b["n"] < SHORT_BRICK_S * fps:
                warns.append(f"brick {b['i']} @ {tc(b['rec_f'])}: only {float(b['n'] / fps):.2f}s")
        for a, b in zip(bricks, bricks[1:]):
            if b["rec_f"] < a["rec_f"] + a["n"]:
                errs.append(f"bricks {a['i']} and {b['i']} overlap at {tc(b['rec_f'])}")
        for o in overlay_frames(recipe):
            if not os.path.exists(o["file"]):
                errs.append(f"overlay {o['i']}: missing file {o['file']}")
                continue
            if o["rec_f"] < 0 or o["rec_f"] + o["n"] > F:
                errs.append(f"overlay {o['i']} @ {tc(o['rec_f'])}: outside the {tc(F)} timeline")
            if o["n"] < 2 * o["fade_s"] * fps:
                errs.append(f"overlay {o['i']} @ {tc(o['rec_f'])}: shorter than its fade in + out")
            if is_still(o["file"]):
                continue
            odur, ofps, ow, oh = probe(o["file"])
            if ofps != fps:
                errs.append(f"overlay {o['i']} @ {tc(o['rec_f'])}: {os.path.basename(o['file'])} is {float(ofps):.3f} fps, "
                            f"the recipe {float(fps):.3f} - render it at the recipe's fps")
            elif odur + 0.02 < float(o["n"] / fps):
                errs.append(f"overlay {o['i']} @ {tc(o['rec_f'])}: {odur:.2f}s clip in a {float(o['n'] / fps):.2f}s slot")
            if abs(ow / oh - fw / fh) > 0.01:
                errs.append(f"overlay {o['i']}: {ow}x{oh} is not frame-shaped")
        for nd in recipe.get("needs", []):
            if nd["record_s"] > float(F / fps):
                warns.append(f"need @ {C.tc(nd['record_s'])}: past the end of the timeline")
        by_file = {}
        for b in bricks:
            by_file.setdefault(b["file"], []).append((b["in_s"], b["in_s"] + float(b["n"] / fps) * b["speed"], b["i"]))
        for f, rs in by_file.items():
            rs.sort()
            for (s1, e1, i1), (s2, e2, i2) in zip(rs, rs[1:]):
                if s2 < e1 - 0.05:
                    warns.append(f"bricks {i1} and {i2} reuse {os.path.basename(f)} {s2:.1f}-{min(e1, e2):.1f}s")
        if errs:
            break
        pieces = flatten(recipe)
        flashes = []
        for j, p in enumerate(pieces):
            if p["kind"] != "aroll" or (j and pieces[j - 1]["kind"] == "aroll"):
                continue
            k = j       # the visible a-roll run: consecutive a-roll pieces (a jump cut inside it is still talking head)
            while k + 1 < len(pieces) and pieces[k + 1]["kind"] == "aroll":
                k += 1
            run = sum(q["n"] for q in pieces[j:k + 1])
            prev_b = pieces[j - 1]["brick"] if j else None
            next_b = pieces[k + 1]["brick"] if k + 1 < len(pieces) else None
            if prev_b is not None and next_b is not None and run < GAP_S * fps:
                flashes.append((pieces[j]["rec_f"], run, prev_b, next_b, "gap"))
            else:
                for q in pieces[j:k + 1]:       # each keep piece of the run is its own shot between jump cuts
                    edge_prev = q is pieces[j] and prev_b is not None
                    edge_next = q is pieces[k] and next_b is not None
                    if (edge_prev or edge_next) and q["n"] < FLASH_S * fps:
                        flashes.append((q["rec_f"], q["n"], prev_b if edge_prev else None,
                                        next_b if edge_next else None, "edge"))
        if not flashes:
            break
        progressed = False
        for f0, n, pb, nb, why in flashes:
            if fix and pb is not None and stretch(recipe, pb, n, tail=True):
                progressed = changed = True
                break
            if fix and nb is not None and stretch(recipe, nb, n, tail=False):
                progressed = changed = True
                break
        if not progressed:
            for f0, n, pb, nb, why in flashes:
                errs.append(f"flicker @ {tc(f0)}: {float(n / fps):.2f}s of talking head "
                            + (f"between bricks {pb} and {nb}" if why == "gap"
                               else f"next to brick {pb if pb is not None else nb}")
                            + " - stretch a brick onto the cut, or leave a longer run")
            break
    return errs, warns, changed


def stretch(recipe, i, frames, tail):
    """Grow brick i by `frames` at its tail (or head) if its clip has the room. True when done."""
    fps, b = fps_of(recipe), recipe["broll"][i]
    sp, d = float(b.get("speed", 1.0)), float(frames / fps)
    dur = probe(b["file"])[0]
    if tail:
        if b["in_s"] + (b["dur"] + d) * sp > dur - 0.02:
            return False
        b["dur"] = round(b["dur"] + d, 4)
    else:
        if b["in_s"] - d * sp < 0:
            return False
        b["in_s"] = round(b["in_s"] - d * sp, 4)
        b["record_s"] = round(b["record_s"] - d, 4)
        b["dur"] = round(b["dur"] + d, 4)
    return True


def summary(r):
    fps, F, pieces = fps_of(r), total_frames(r), flatten(r)
    cov = sum(p["n"] for p in pieces if p["kind"] == "broll")
    return {"bricks": len(r.get("broll", [])), "timeline_s": round(float(F / fps), 2),
            "broll_coverage": round(cov / F, 3) if F else 0, "pieces": len(pieces),
            "needs": len(r.get("needs", [])), "overlays": len(r.get("overlays", []))}


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["lint", "carry", "show"])
    ap.add_argument("recipe")
    ap.add_argument("new", nargs="?", help="carry: the recipe with the changed a-roll")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = C.read_json(a.recipe)
    if a.cmd == "show":
        fps = fps_of(r)
        for p in with_overlays(r, flatten(r)):
            what = (f"brick {p['brick']}: " + (r['broll'][p['brick']].get('why') or '')) if p["kind"] == "broll" else "a-roll"
            ov = f"  + overlay x{len(p['ov'])}" if p["ov"] else ""
            print(f"{C.tc(float(p['rec_f'] / fps))} +{float(p['n'] / fps):6.2f}s  {os.path.basename(p['file'])} "
                  f"@{p['in_s']:.2f}  {what[:70]}{ov}")
        print(json.dumps(summary(r)))
        return 0
    if a.cmd == "carry":
        if not a.new:
            ap.error("carry needs OLD and NEW recipes")
        new = C.read_json(a.new)
        moved, dropped = carry(r, new)
        out = a.out or a.new
        C.write_json(out, new)
        for d in dropped:
            print("DROPPED (its moment was cut - re-plan it):", d)
        print(json.dumps({"recipe": out, "carried": moved, "dropped": len(dropped)}))
        errs, warns, _ = lint(new)
        for w in warns:
            print("WARN ", w)
        for e in errs:
            print("ERROR", e)
        return 1 if errs else 0
    errs, warns, changed = lint(r, fix=a.fix)
    if changed:
        C.write_json(a.recipe, r)
        print(f"fixed: stretched bricks to close flicker runs; wrote {a.recipe}")
    for w in warns:
        print("WARN ", w)
    for e in errs:
        print("ERROR", e)
    print(json.dumps({"errors": len(errs), "warnings": len(warns), **summary(r)}))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
