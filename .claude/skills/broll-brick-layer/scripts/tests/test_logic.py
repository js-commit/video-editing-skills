"""Pure-logic tests on synthetic data: seam math, sliver rule, flicker
detection, plan checking/snapping, ripple + brick snapping against fakes.
Run: python3 -B tests/test_logic.py  (no Resolve, no numpy, no media)."""
from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_resolve as fr  # noqa: E402
from fake_resolve import MPI, Item, Timeline, MediaPool  # noqa: E402

import _brick as B  # noqa: E402
import seam_audit as SA  # noqa: E402
import flicker_audit as FA  # noqa: E402
import check_plan as CP  # noqa: E402
import ripple_extend as RE  # noqa: E402
import add_markers as AM  # noqa: E402
import close_gaps as CG  # noqa: E402
import edited_transcript as ET  # noqa: E402
import inventory as INV  # noqa: E402
import frames as FR  # noqa: E402

FPS = 24.0


def seam_args(**kw):
    a = SA.build_parser().parse_args(["--project", "p", "--timeline", "t"])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def env_from(spans, total_s, loud=-20.0, quiet=-70.0):
    """Envelope (10 ms hops) loud inside the given (start, end) seconds."""
    n = int(total_s / SA.HOP)
    return SA.Env([loud if any(s <= k * SA.HOP < e for s, e in spans) else quiet for k in range(n)])


def test_percentile_and_envelope():
    assert SA.percentile([1, 2, 3, 4, 5], 50) == 3
    assert abs(SA.percentile([0, 10], 5) - 0.5) < 1e-9
    from array import array
    sr = 16000
    sig = array("h", [0] * sr + [16384 if (i // 20) % 2 else -16384 for i in range(sr)])  # 1 s silence, 1 s square
    db = SA.envelope_db(sig, sr)
    assert len(db) == (len(sig) - 400) // 160
    assert db[10] < -150 and abs(db[-10] - 20 * __import__("math").log10(0.5)) < 0.01, (db[10], db[-10])


def test_seam_clean_hard_and_sliver():
    a = seam_args()
    # source: speech 0.5-1.5, quiet 1.5-3.5, speech 3.5-5.0, speech 5.0-6.2 (no pause), speech 6.6-8
    env = env_from([(0.5, 1.5), (3.5, 6.2), (6.6, 8.0)], 10.0)
    f = lambda s: int(round(s * FPS))  # noqa: E731
    items = [
        {"start": 0, "end": f(2.0), "left": 0, "media": "m"},                           # keeps 0-2.0
        {"start": f(2.0), "end": f(5.0), "left": f(3.0), "media": "m"},                # keeps 3.0-6.0 (cut lands in speech)
        {"start": f(5.0), "end": f(6.4), "left": f(6.5), "media": "m"},                # keeps 6.5-7.9
    ]
    seams = SA.audit(items, items, env, FPS, [], a)
    assert len(seams) == 2, seams
    clean, hard = seams
    assert not clean["hard"] and not clean["abrupt"] and clean["kind"] == "none", clean
    assert hard["hard"], hard
    # removed 6.0-6.5 (0.5 s <= max-restore): the loud out point walks to the 6.2 pause -> restore or partial
    assert hard["kind"] in ("restore", "partial") and hard["tail_f"] > 0, hard
    plan = SA.plan_entries(seams)
    assert [p["F"] for p in plan] == [hard["F"]]
    # sliver: a 10-frame keep between two seams gets its shorter neighbour restored
    env2 = env_from([], 20.0)
    items2 = [
        {"start": 0, "end": 48, "left": 0, "media": "m"},
        {"start": 48, "end": 58, "left": 60, "media": "m"},     # removed 12 frames before
        {"start": 58, "end": 200, "left": 100, "media": "m"},   # removed 30 frames after
    ]
    s2 = SA.audit(items2, items2, env2, FPS, [], seam_args(target_gap=0.0))
    by_f = {s["F"]: s for s in s2}
    assert by_f[48]["kind"] == "restore" and by_f[48]["tail_f"] == 12 and "sliver" in by_f[48], by_f[48]
    assert by_f[58]["kind"] == "none", by_f[58]


def test_merge_continuous():
    m = SA.merge_continuous([{"start": 0, "end": 10, "left": 0, "media": "a"},
                             {"start": 10, "end": 20, "left": 10, "media": "a"},
                             {"start": 20, "end": 30, "left": 50, "media": "a"}])
    assert [(x["start"], x["end"]) for x in m] == [(0, 20), (20, 30)]


def it(name, s, e, src=0, media=None, enabled=True):
    return {"name": name, "start": s, "end": e, "enabled": enabled, "src_in": src, "still": False,
            "media": media or name}


def test_flicker():
    aroll = FA.merge_track([it("a1", 0, 100, 0, "cam"), it("a2", 100, 300, 150, "cam"),
                            it("a3", 300, 400, 450, "cam"), it("a4", 400, 500, 550, "cam")])
    assert len(aroll) == 3  # a3+a4 are source-continuous: one shot
    bricks = [it("b1", 105, 200), it("b2", 210, 290)]
    tracks = {1: aroll, 2: bricks}
    found = FA.find_flicker(tracks, 500, FPS, int(0.6 * FPS), [1], 2)
    kinds = sorted({(f["kind"], f["start_f"]) for f in found})
    assert ("brick-near-cut", 100) in kinds, kinds          # starts 5 frames after the cut at 100
    assert ("visible-micro-run", 100) in kinds, kinds        # the viewer sees a2 for 5 frames
    assert ("visible-micro-run", 200) in kinds, kinds        # 10-frame gap between bricks
    assert ("brick-near-cut", 290) in kinds, kinds           # ends 10 frames before the cut at 300
    clean = FA.find_flicker({1: aroll, 2: [it("b1", 100, 300)]}, 500, FPS, 14, [1], 2)
    assert clean == [], clean
    gap = FA.find_flicker({1: [it("x", 0, 100), it("y", 110, 500)]}, 500, FPS, 14, [1], None)
    assert {f["kind"] for f in gap} == {"aroll-gap", "visible-micro-run"}, gap
    assert FA.auto_aroll_tracks({1: aroll, 2: bricks, 3: [it("t", 0, 30)]}, 500, None) == [1]
    px = FA.pixel_findings([1.0, 1.3, 5.0], FPS, 0.6)
    assert len(px) == 1 and px[0]["kind"] == "pixel-flicker"


def inventory(t0=86400, end=2400):
    """Synthetic inventory: one camera, cuts at 240, 480 (+ continuous piece), bricks track V2."""
    def item(name, s, e, src, path="/v/cam.mov"):
        return {"name": name, "file_path": path, "enabled": True, "record_frame": t0 + s, "record_end_frame": t0 + e,
                "record_s": s / FPS, "record_end_s": e / FPS, "duration_frames": e - s, "src_start_frame": src,
                "src_end_frame": src + e - s, "clip_fps": FPS, "src_start_s": src / FPS, "src_end_s": (src + e - s) / FPS}
    return {"project": "p", "broll": [], "skipped": [], "aroll": {
        "name": "cut", "fps": FPS, "start_frame": t0, "end_frame": t0 + end, "brick_track": 2,
        "aroll_video_tracks": [1], "first_overlay_track": 2,
        "video_tracks": [
            {"index": 1, "name": "V1", "items": [item("c1", 0, 240, 0), item("c2", 240, 480, 300),
                                                  item("c3", 480, 2400, 700)]},
            {"index": 2, "name": B.BRICK_TRACK, "items": [item("old", 1200, 1400, 0, "/b/old.mov")]}],
        "audio_tracks": []}}


def test_check_plan_snaps_and_errors():
    inv = inventory()
    plan = {"project": "p", "aroll_timeline": "cut", "placements": [
        {"id": 1, "media": "/b/one.mov", "clip_duration_s": 30, "use_src_start_s": 5.0, "use_src_end_s": 11.0,
         "record_s": 250 / FPS},                       # starts 10 frames after the cut at 240
        {"id": 2, "media": "/b/two.mov", "clip_duration_s": 30, "use_src_start_s": 2.0, "use_src_end_s": 9.5,
         "record_s": 800 / FPS},                       # ends at 980; nothing near
    ]}
    out, rep = CP.check(plan, inv, probe=False)
    assert not rep["errors"], rep
    p1 = out["placements"][0]
    assert round(p1["record_s"] * FPS) == 240 and round(p1["use_src_start_s"] * FPS) == 5 * 24 - 10, p1
    # brick 1 now covers 240..394: its end is far from the cut at 480, no flash
    assert rep["flashes"] == [], rep["flashes"]
    # end-snap: a brick ending 6 frames before the cut at 480
    plan2 = {"project": "p", "aroll_timeline": "cut", "placements": [
        {"id": 3, "media": "/b/three.mov", "clip_duration_s": 30, "use_src_start_s": 1.0,
         "use_src_end_s": 1.0 + 200 / FPS, "record_s": 274 / FPS}]}
    out2, rep2 = CP.check(plan2, inv, probe=False)
    p3 = out2["placements"][0]
    assert round((p3["record_s"] + p3["use_src_end_s"] - p3["use_src_start_s"]) * FPS) == 480, (p3, rep2)
    # errors: overlap with the existing brick, reuse of a source range, protected timeline, past the end
    bad = {"project": "p", "aroll_timeline": "cut backup", "placements": [
        {"id": 4, "media": "/b/x.mov", "use_src_start_s": 0, "use_src_end_s": 8, "record_s": 1300 / FPS},
        {"id": 5, "media": "/b/y.mov", "use_src_start_s": 0, "use_src_end_s": 5, "record_s": 1500 / FPS},
        {"id": 6, "media": "/b/y.mov", "use_src_start_s": 4, "use_src_end_s": 9, "record_s": 1700 / FPS},
        {"id": 7, "media": "/b/z.mov", "use_src_start_s": 0, "use_src_end_s": 9, "record_s": 2300 / FPS}]}
    _, rep3 = CP.check(bad, inv, probe=False)
    text = " | ".join(rep3["errors"])
    for needle in ("backup", "overlaps the brick already", "same source range", "past the end"):
        assert needle in text, (needle, text)
    # a flash that snapping cannot fix (no room either way) is reported
    tight = {"project": "p", "aroll_timeline": "cut", "placements": [
        {"id": 8, "media": "/b/q.mov", "clip_duration_s": 4.0, "use_src_start_s": 0.0, "use_src_end_s": 4.0,
         "record_s": 380 / FPS}]}  # 380..476, clip has no tail: end cannot reach 480
    _, rep4 = CP.check(tight, inv, probe=False)
    assert rep4["flashes"] or any("no room" in w for w in rep4["warnings"]), rep4
    # deictic warning
    words = [{"word": "look", "start": 33.0, "end": 33.2}, {"word": "at", "start": 33.2, "end": 33.3},
             {"word": "this", "start": 33.3, "end": 33.5}]
    _, rep5 = CP.check({"project": "p", "aroll_timeline": "cut", "placements": [
        {"id": 9, "media": "/b/w.mov", "clip_duration_s": 20, "use_src_start_s": 0, "use_src_end_s": 6,
         "record_s": 32.0}]}, inv, words=words, probe=False)
    assert any("look at this" in w for w in rep5["warnings"]), rep5


def test_supply_opt_in():
    def plan(src, **kw):
        return dict({"project": "p", "aroll_timeline": "cut", "placements": [
            {"id": 1, "broll_timeline": src, "file_hint": "clip", "use_src_start_s": 0, "use_src_end_s": 4,
             "record_s": 30.0}]}, **kw)
    assert B.supply_refusals(plan("broll supply")) == [] and B.supply_refusals(plan("B-Roll day 2")) == []
    assert "supply_timelines" in B.supply_refusals(plan("rough cut v1"))[0]
    assert B.supply_refusals(plan("rough cut v1", supply_timelines=["rough cut v1"])) == []
    assert "a-roll timeline itself" in B.supply_refusals(plan("cut", supply_timelines=["cut"]))[0]
    _, rep = CP.check(plan("rough cut v1"), inventory(), probe=False)
    assert any("not named as a b-roll supply" in e for e in rep["errors"]), rep


def ripple_timeline():
    t0 = 86400
    face, brick = MPI("face", frames=5000), MPI("b1", frames=1000)
    return Timeline({
        ("video", 1): [Item("P", t0, 400, face, src_in=0), Item("S", t0 + 400, 100, face, src_in=460),
                       Item("T", t0 + 500, 300, face, src_in=600)],
        ("audio", 1): [Item("P", t0, 400, face, src_in=0), Item("S", t0 + 400, 100, face, src_in=460),
                       Item("T", t0 + 500, 300, face, src_in=600)],
        ("video", 2): [Item("brick", t0 + 505, 100, brick, src_in=50)],
    }, t0=t0, fps="24", names={("video", 2): B.BRICK_TRACK},
        markers={300: {"color": "Red", "name": "before", "note": "", "duration": 1, "customData": ""},
                 450: {"color": "Blue", "name": "after", "note": "n", "duration": 1, "customData": ""}})


def run_ripple(tl, extra):
    mp = MediaPool(tl, tl_fps=24.0)
    fr.patch(tl, mp)
    d = tempfile.mkdtemp()
    sys.argv = ["ripple_extend.py", "--project", "p", "--timeline", "cut", "--comp-dir", os.path.join(d, "c")] + extra
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        RE.main()
    return mp, d, out.getvalue()


def test_ripple_bridge_and_snap():
    tl = ripple_timeline()
    mp, d, out = run_ripple(tl, ["--bridge", "400", "--dry-run"])
    s = json.loads(out[out.index("{"):])
    assert s["bridges"] == [[400, 60, 0]] and s["markers_moved"] == 1 and not mp.calls, s
    tl = ripple_timeline()
    mp, d, out = run_ripple(tl, ["--bridge", "400", "--snap-top-track"])
    assert glob.glob(os.path.join(d, "c", "restore_*.json"))
    assert tl.ops.index("del_clips") < tl.ops.index("del_marker")
    assert [m[0] for m in tl.added_markers] == [510], tl.added_markers
    v1 = sorted((i.GetStart() - 86400, i.GetEnd() - 86400, i.GetLeftOffset()) for i in tl.GetItemListInTrack("video", 1))
    assert v1 == [(0, 400, 0), (400, 460, 400), (460, 560, 460), (560, 860, 600)], v1
    # the brick was 5 frames after the cut at 500 -> after the 60-frame shift it is snapped onto 560
    v2 = [(i.GetStart() - 86400, i.GetEnd() - 86400, i.GetLeftOffset()) for i in tl.GetItemListInTrack("video", 2)]
    assert v2 == [(560, 665, 45)], v2


def test_snap_bricks_pure():
    bricks = [{"name": "b", "new_start": 105, "dur": 50, "src_in": 20, "ctype": "", "cframes": 0, "cfps": 24.0}]
    snaps = RE.snap_bricks(bricks, {0, 100, 300}, 24, 24.0)
    assert bricks[0]["new_start"] == 100 and bricks[0]["src_in"] == 15 and bricks[0]["dur"] == 55, bricks
    assert snaps and snaps[0][2] == 5
    assert RE.merged_bounds([(0, 10, "u", 0, True), (10, 20, "u", 10, True), (20, 30, "u", 99, True)]) == {0, 20, 30}


def test_small_helpers():
    assert AM.subtract(0, 10, [(2, 3), (5, 12)]) == [(0, 2), (3, 5)]
    assert CG.gap_action(100, 200, 50, 10) == "extend-tail"
    assert CG.gap_action(195, 200, 50, 10) == "extend-head"
    assert CG.gap_action(195, 200, 5, 10) == "slide"
    words = ET.project_words([{"src_start_s": 10.0, "src_end_s": 12.0, "record_s": 0.0}],
                             lambda i: [{"word": "a", "start": 9.0, "end": 9.5}, {"word": "b.", "start": 10.5, "end": 11.0}])
    assert words == [{"word": "b.", "start": 0.5, "end": 1.0}], words
    assert len(ET.segment(words)) == 1
    old = inventory()
    new = json.loads(json.dumps(old))
    new["aroll"]["video_tracks"][1]["items"][0]["record_frame"] += 24
    ch = INV.brick_changes(old, new, B.BRICK_TRACK)
    assert ch and ch[0]["change"] == "moved/trimmed", ch
    frames = [f"/x/f{t:09.2f}.jpg" for t in (0, 2.5, 5, 7.5)]
    kept, dropped = FR.dedup_sigs(frames, [b"\x00" * 4, b"\x01" * 4, b"\xff" * 4, b"\xff" * 4], 6, 30)
    assert kept == [frames[0], frames[2], frames[3]] and dropped == [frames[1]], (kept, dropped)
    assert B.tc(86400 + 25, 23.976) == "01:00:01:01"
    assert B.is_protected("cut backup 2") and not B.is_protected("cut v2")
    assert B.is_protected("final", extra=["final"])


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"{len(tests)} tests passed")
