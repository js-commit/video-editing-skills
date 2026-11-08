"""Pure logic for the multicam angle pass (no Resolve, no ffmpeg).

Shared by timeline_transcript.py and resolve_angle.py, and unit-tested in
tests/test_angles.py:

- the angle vocabulary (ids a / b / pip, display names from the job JSON)
- job loading and validation
- merging per-batch agent decisions, applying corrections
- angle runs and the minimum-run smoothing (anti-flicker)
- PiP geometry (where the camera-A inset lands, for both PiP styles)
- reading the user's preferences for this skill

Angle ids are fixed; only their names and descriptions change per setup:

    a    camera A full frame (the main angle, usually the speaker's face)
    b    camera B full frame (the second angle: overhead, wide, side...)
    pip  camera B full frame with a small camera-A inset (picture-in-picture)
"""
from __future__ import annotations

import json
import re
import sys
from fractions import Fraction
from pathlib import Path

ANGLE_IDS = ("a", "b", "pip")

DEFAULT_ANGLES = {
    "a": {"name": "A",
          "describe": "camera A full frame: the main angle, the speaker "
                      "talking to the viewer"},
    "b": {"name": "B",
          "describe": "camera B full frame: the second angle (overhead on "
                      "the hands and the object, a wide shot, a side view)"},
    "pip": {"name": "PiP",
            "describe": "camera B full frame with a small camera-A inset in "
                        "a corner: what is shown AND the speaker's reaction"},
}

MIN_RUN_S = 2.0      # hard floor: shorter angle runs read as a flicker
TARGET_RUN_S = 4.0   # what the agents aim for; runs under it get a second look

# PiP look and placement. Coordinates are fractions of the frame, origin
# TOP-LEFT (like an image): face_box = [x0, y0, x1, y1] of the speaker's face
# in camera A's frame; inset_width = how much of the frame width the inset
# takes; margin = [x, y] gap from the chosen corner's edges.
PIP_DEFAULTS = {
    "style": "fusion",            # "fusion" (rounded + shadow) or "inspector"
    "corner": "top-right",        # top-right | top-left | bottom-right | bottom-left
    "face_box": [0.3385, 0.0, 0.6615, 0.49],
    "inset_width": 0.23,
    "margin": [0.02, 0.03],
    "corner_radius": 0.12,        # Fusion RectangleMask CornerRadius
    "shadow_offset": [0.0, -0.012],  # relative to the inset, +y = up
    "shadow_softness": 0.05,
    "shadow_alpha": 0.7,
    "outline_px": 0,              # 0 = no outline (a soft shadow is enough)
    "outline_rgb": [1.0, 1.0, 1.0],
    "outline_alpha": 0.0,
}
CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")


def log(*a):
    print(*a, file=sys.stderr)


def parse_fps(s) -> Fraction:
    """'23.976' -> 24000/1001 (same rule as vidkit.resolve.parse_fps)."""
    f = float(s)
    for whole, num in ((24, 24000), (30, 30000), (60, 60000)):
        if abs(f - whole * 1000 / 1001) < 0.01:
            return Fraction(num, 1001)
    return Fraction(str(s))


def tc(frames, fps) -> str:
    """Resolve timecode: integer base (24 for 23.976), non-drop."""
    base = round(float(fps))
    s, f = divmod(int(frames), base)
    return "%02d:%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60, f)


# ---- job ------------------------------------------------------------------

def load_job(path, need_offset: bool = True) -> dict:
    """Read job.json (aroll-draft writes angle_job.json). need_offset=False
    for subcommands that only touch the timeline (transform, backup...)."""
    try:
        job = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read job file {path}: {e}")
    for key in ("project", "timeline"):
        if not job.get(key):
            sys.exit(f"{path}: missing {key!r}")
    if need_offset and "offset_s" not in job:
        sys.exit(f"{path}: missing offset_s. Measure it from the AUDIO "
                 "(aroll-draft's sync step), never from file timestamps or "
                 "creation_time: camera clocks drift and lie. Write "
                 "\"offset_s\": 0.0 only if both cameras truly started together.")
    job.setdefault("never_touch", [])
    return job


def vocab(job: dict | None) -> dict:
    """Angle id -> {name, describe}, the job's "angles" block over defaults."""
    out = {k: dict(v) for k, v in DEFAULT_ANGLES.items()}
    for k, v in ((job or {}).get("angles") or {}).items():
        k = k.lower()
        if k in out and isinstance(v, dict):
            out[k].update({kk: vv for kk, vv in v.items() if vv})
        elif k in out and isinstance(v, str):
            out[k]["name"] = v
    return out


def allowed(job: dict | None) -> tuple:
    """The angles this job may use (e.g. ["a", "b"] when no PiP is wanted)."""
    al = (job or {}).get("allowed_angles") or list(ANGLE_IDS)
    al = tuple(a.lower() for a in al if a.lower() in ANGLE_IDS)
    if "a" not in al:
        al = ("a",) + al
    return al


def min_run_s(job: dict | None) -> float:
    return float((job or {}).get("min_run_s", MIN_RUN_S))


def target_run_s(job: dict | None) -> float:
    return float((job or {}).get("target_run_s", TARGET_RUN_S))


def normalize(value, voc: dict) -> str | None:
    """Map an agent's angle string to an id: accepts the id itself, the
    configured name, or 'camera a' / 'cam b' style spellings."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ANGLE_IDS:
        return v
    for k, d in voc.items():
        if v == str(d.get("name", "")).strip().lower():
            return k
    v = re.sub(r"^(camera|cam)[\s_-]*", "", v)
    if v in ANGLE_IDS:
        return v
    if v in ("picture-in-picture", "picture in picture", "inset"):
        return "pip"
    return None


# ---- decisions --------------------------------------------------------------

def extract_json(text: str):
    """Parse an agent's JSON answer, tolerating ``` fences around it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def validate_batch(decs, ids, voc, allow, label="batch"):
    """Check one batch's decisions. Returns (by_id, problems): every id in
    `ids` must get exactly one decision with an allowed angle."""
    ids = set(ids)
    by_id, problems, seen = {}, [], set()
    if not isinstance(decs, list):
        return {}, [f"{label}: expected a JSON array"]
    for d in decs:
        if not isinstance(d, dict):
            problems.append(f"{label}: entry is not an object: {d!r}")
            continue
        i = d.get("id")
        if i not in ids:
            problems.append(f"{label}: id {i} is not in this batch")
            continue
        ang = normalize(d.get("angle"), voc)
        if ang is None or ang not in allow:
            problems.append(f"{label}: id {i} has angle {d.get('angle')!r} "
                            f"(allowed: {', '.join(allow)})")
            continue
        if i in seen:
            problems.append(f"{label}: id {i} decided twice")
            continue
        seen.add(i)
        conf = str(d.get("confidence", "high")).lower()
        by_id[i] = {"id": i, "angle": ang,
                    "confidence": "low" if conf == "low" else "high",
                    "why": d.get("why", "")}
    for i in sorted(ids - seen):
        problems.append(f"{label}: id {i} has no decision")
    return by_id, problems


def apply_corrections(dec: dict, corrections, voc, allow, source="overpass"):
    """Apply [{"id", "angle", "why"}] to dec (id -> decision) in place.
    A correction also clears the low-confidence flag (confirming counts)."""
    applied, skipped = [], []
    for c in corrections or []:
        i = c.get("id") if isinstance(c, dict) else None
        ang = normalize(c.get("angle"), voc) if isinstance(c, dict) else None
        if i in dec and ang in allow:
            changed = dec[i]["angle"] != ang
            dec[i]["angle"] = ang
            dec[i]["confidence"] = "high"
            dec[i]["why"] = f"{source}: {c.get('why', '')}".strip()
            applied.append({"id": i, "angle": ang, "changed": changed})
        else:
            skipped.append(c)
    return applied, skipped


# ---- runs and smoothing ------------------------------------------------------

def runs(segs, tol=0):
    """Group consecutive same-angle segments into runs.

    segs: [{"start", "dur", "angle", ...}] sorted by start (any unit, frames
    or seconds). A gap larger than `tol` between two segments ends a run
    even when the angle stays the same."""
    out = []
    for s in segs:
        end = s["start"] + s["dur"]
        if out and out[-1]["angle"] == s["angle"] and \
                abs(s["start"] - out[-1]["end"]) <= tol:
            out[-1]["segs"].append(s)
            out[-1]["dur"] += s["dur"]
            out[-1]["end"] = end
        else:
            out.append({"angle": s["angle"], "start": s["start"],
                        "end": end, "dur": s["dur"], "segs": [s]})
    return out


def smooth(segs, min_dur, tol=0):
    """Anti-flicker: absorb every run shorter than min_dur into a neighbour.

    Repeatedly takes the shortest short run and gives it the angle of its
    longer touching neighbour (the earlier one on a tie). A run with no
    touching neighbour (isolated by gaps) is left alone. Mutates the
    segments' "angle" and returns the flips [{"start", "dur", "from", "to"}].
    """
    flips, stuck = [], set()
    while True:
        rs = runs(segs, tol)
        if len(rs) <= 1:
            break
        short = [(r["dur"], k) for k, r in enumerate(rs)
                 if r["dur"] < min_dur and r["start"] not in stuck]
        if not short:
            break
        _, k = min(short)
        r = rs[k]
        nbrs = []
        if k > 0 and abs(r["start"] - rs[k - 1]["end"]) <= tol:
            nbrs.append(rs[k - 1])
        if k + 1 < len(rs) and abs(rs[k + 1]["start"] - r["end"]) <= tol:
            nbrs.append(rs[k + 1])
        if not nbrs:
            stuck.add(r["start"])
            continue
        target = max(nbrs, key=lambda n: n["dur"])["angle"]  # max keeps first on tie
        for s in r["segs"]:
            flips.append({"start": s["start"], "dur": s["dur"],
                          "from": s["angle"], "to": target})
            s["angle"] = target
    return flips


def decision_segments(segments, dec):
    """Transcript segments + decisions -> smoothing input in record frames."""
    out = []
    for s in sorted(segments, key=lambda s: s["record_in"]):
        d = dec.get(s["id"])
        if d is None:
            continue
        out.append({"id": s["id"], "start": s["record_in"],
                    "dur": s["record_out"] - s["record_in"],
                    "angle": d["angle"]})
    return out


def smooth_decisions(segments, dec, fps, min_s):
    """Smooth the decisions (id -> decision) in place; returns the flips with
    segment ids. Works on all three angles: a B <-> PiP switch is a visible
    change too (the inset pops in or out)."""
    segs = decision_segments(segments, dec)
    flips = smooth(segs, float(min_s) * float(fps), tol=1)
    by_start = {s["start"]: s for s in segs}
    out = []
    for f in flips:
        sid = by_start[f["start"]]["id"]
        d = dec[sid]
        d["angle"] = f["to"]
        d["why"] = (f"smoothed ({f['from']} run under {min_s:g} s): "
                    f"{d.get('why', '')}").strip()
        out.append({"id": sid, "from": f["from"], "to": f["to"],
                    "dur_s": round(f["dur"] / float(fps), 2)})
    return out


def run_stats(segments, dec, fps):
    """Seconds per angle, run count and shortest run (seconds)."""
    segs = decision_segments(segments, dec)
    rs = runs(segs, tol=1)
    per = {k: 0.0 for k in ANGLE_IDS}
    for s in segs:
        per[s["angle"]] = per.get(s["angle"], 0.0) + s["dur"] / float(fps)
    return {"seconds_per_angle": {k: round(v, 1) for k, v in per.items()},
            "runs": len(rs),
            "shortest_run_s": round(min((r["dur"] for r in rs), default=0)
                                    / float(fps), 2)}


def build_jobs(segments, dec):
    """Decisions -> Resolve job lists (record start frames).

    enable_v2: segments that show camera B (b and pip: PiP sits on B).
    pip_v3:    segments that get the camera-A inset on V3.
    low:       segments still marked low confidence (to sample frames)."""
    by_id = {s["id"]: s for s in segments}
    enable, pip, low = [], [], []
    for i in sorted(dec):
        s = by_id.get(i)
        if s is None:
            continue
        d = dec[i]
        if d["angle"] in ("b", "pip"):
            enable.append(s["record_in"])
        if d["angle"] == "pip":
            pip.append(s["record_in"])
        if d.get("confidence") == "low":
            low.append(s["record_in"])
    missing = sorted(set(by_id) - set(dec))
    return {"enable_v2": enable, "pip_v3": pip, "low": low, "missing": missing}


# ---- PiP geometry -------------------------------------------------------------

def pip_params(*layers) -> dict:
    """PIP_DEFAULTS overlaid with each given dict (job's "pip", pip.json...)."""
    p = dict(PIP_DEFAULTS)
    for layer in layers:
        for k, v in (layer or {}).items():
            if v is not None:
                p[k] = v
    if p["corner"] not in CORNERS:
        sys.exit(f"pip corner {p['corner']!r}: use one of {', '.join(CORNERS)}")
    return p


def pip_geometry(p, src_w=3840, src_h=2160, tl_w=3840, tl_h=2160):
    """Where the camera-A inset lands.

    Returns:
      scale        zoom applied to the cropped face box
      box          the inset on screen, [x0, y0, x1, y1] top-left origin
      fusion       Fusion values (origin BOTTOM-LEFT, normalised): the
                   RectangleMask centre/size and the Transform centre/size
      inspector    TimelineItem properties for the "inspector" style: crop
                   in SOURCE pixels, ZoomX/Y, Pan/Tilt in timeline pixels.
                   Positive Tilt moves the image UP; positive Pan moves it
                   right. Calibrate against a rendered frame (verify): the
                   scripting API does not document the units.
    """
    x0, y0, x1, y1 = (float(v) for v in p["face_box"])
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        sys.exit(f"pip face_box {p['face_box']} must be [x0, y0, x1, y1] "
                 "fractions with x0 < x1 and y0 < y1")
    fw, fh = x1 - x0, y1 - y0
    s = float(p["inset_width"]) / fw
    mx, my = (float(v) for v in p["margin"])
    w, h = fw * s, fh * s
    corner = p["corner"]
    # on-screen inset, top-left origin
    ix0 = 1.0 - mx - w if corner.endswith("right") else mx
    iy0 = my if corner.startswith("top") else 1.0 - my - h
    box = [ix0, iy0, ix0 + w, iy0 + h]
    # face centre in bottom-left origin (Fusion / Resolve Tilt convention)
    cx, cy = (x0 + x1) / 2, 1.0 - (y0 + y1) / 2
    want_cx, want_cy = ix0 + w / 2, 1.0 - (iy0 + h / 2)
    # scaling about the frame centre moves the face centre to:
    scx, scy = 0.5 + (cx - 0.5) * s, 0.5 + (cy - 0.5) * s
    dx, dy = want_cx - scx, want_cy - scy
    return {
        "scale": round(s, 4),
        "box": [round(v, 4) for v in box],
        "fusion": {"mask_center": [cx, cy], "mask_size": [fw, fh],
                   "transform_center": [0.5 + dx, 0.5 + dy],
                   "transform_size": s},
        "inspector": {
            "CropLeft": round(x0 * src_w, 1),
            "CropRight": round((1 - x1) * src_w, 1),
            "CropTop": round(y0 * src_h, 1),
            "CropBottom": round((1 - y1) * src_h, 1),
            "ZoomX": round(s, 4), "ZoomY": round(s, 4),
            "Pan": round(dx * tl_w, 1), "Tilt": round(dy * tl_h, 1),
        },
    }


# ---- preferences --------------------------------------------------------------

def read_preferences(skill="multicam-angles", path=None) -> str:
    """The `## general` and `## <skill>` sections of user/preferences.md,
    as markdown ("" when the file or the sections are missing)."""
    if path is None:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
            from vidkit import settings
            path = settings.PREFERENCES_PATH
        except Exception:
            return ""
    try:
        text = Path(path).read_text()
    except OSError:
        return ""
    keep, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1).strip().lower()
            if cur in ("general", skill):
                keep.append(line)
            continue
        if cur in ("general", skill):
            keep.append(line)
    return "\n".join(keep).strip()
