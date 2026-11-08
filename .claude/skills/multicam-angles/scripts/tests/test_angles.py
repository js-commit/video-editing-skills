"""Tests for the pure logic of the multicam angle pass (no Resolve needed).

    python3 -B .claude/skills/multicam-angles/scripts/tests/test_angles.py

Synthetic data only. The CLI test runs timeline_transcript.py end to end on
a fake timeline dump and transcript in a temporary folder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import angles as A  # noqa: E402

VOC = A.vocab({"angles": {"a": {"name": "face"}, "b": {"name": "overhead"}}})
ALL = A.ANGLE_IDS


def segs(*spec, start=0):
    """segs(("a", 48), ("b", 24)) -> contiguous segments in frames."""
    out, t = [], start
    for ang, dur in spec:
        out.append({"start": t, "dur": dur, "angle": ang})
        t += dur
    return out


class Vocabulary(unittest.TestCase):
    def test_names_and_ids(self):
        self.assertEqual(A.normalize("pip", VOC), "pip")
        self.assertEqual(A.normalize("Face", VOC), "a")
        self.assertEqual(A.normalize("overhead", VOC), "b")
        self.assertEqual(A.normalize("camera B", VOC), "b")
        self.assertEqual(A.normalize("picture-in-picture", VOC), "pip")
        self.assertIsNone(A.normalize("wide", VOC))
        self.assertIsNone(A.normalize(3, VOC))

    def test_allowed_always_has_a(self):
        self.assertEqual(A.allowed({"allowed_angles": ["b"]}), ("a", "b"))
        self.assertEqual(A.allowed({}), ALL)


class Merge(unittest.TestCase):
    def test_clean_batch(self):
        decs = [{"id": 1, "angle": "face", "why": "intro"},
                {"id": 2, "angle": "pip", "confidence": "low"}]
        by_id, probs = A.validate_batch(decs, [1, 2], VOC, ALL)
        self.assertEqual(probs, [])
        self.assertEqual(by_id[1]["angle"], "a")
        self.assertEqual(by_id[1]["confidence"], "high")
        self.assertEqual(by_id[2]["confidence"], "low")

    def test_problems(self):
        decs = [{"id": 1, "angle": "a"}, {"id": 1, "angle": "b"},
                {"id": 9, "angle": "a"}, {"id": 3, "angle": "zoom"}, "junk"]
        by_id, probs = A.validate_batch(decs, [1, 2, 3], VOC, ALL, "batch 4")
        text = "\n".join(probs)
        self.assertIn("id 1 decided twice", text)
        self.assertIn("id 9 is not in this batch", text)
        self.assertIn("id 3 has angle 'zoom'", text)
        self.assertIn("id 2 has no decision", text)
        self.assertIn("not an object", text)
        self.assertEqual(by_id[1]["angle"], "a")   # first one wins

    def test_disallowed_pip(self):
        _, probs = A.validate_batch([{"id": 1, "angle": "pip"}], [1], VOC, ("a", "b"))
        self.assertTrue(probs)

    def test_not_a_list(self):
        _, probs = A.validate_batch({"id": 1}, [1], VOC, ALL)
        self.assertTrue(probs)

    def test_fenced_json(self):
        self.assertEqual(A.extract_json('```json\n[{"id": 1}]\n```'), [{"id": 1}])

    def test_corrections(self):
        dec = {1: {"id": 1, "angle": "a", "confidence": "low", "why": ""},
               2: {"id": 2, "angle": "b", "confidence": "high", "why": ""}}
        applied, skipped = A.apply_corrections(
            dec, [{"id": 1, "angle": "a", "why": "eyes on lens"},
                  {"id": 2, "angle": "overhead"},
                  {"id": 7, "angle": "a"}, {"id": 2, "angle": "bogus"}], VOC, ALL, "frames")
        self.assertEqual(dec[1]["confidence"], "high")      # confirmation clears low
        self.assertEqual(applied[0], {"id": 1, "angle": "a", "changed": False})
        self.assertEqual(dec[2]["angle"], "b")
        self.assertTrue(dec[1]["why"].startswith("frames:"))
        self.assertEqual(len(skipped), 2)


class Runs(unittest.TestCase):
    def test_runs_merge_and_gaps(self):
        s = segs(("a", 10), ("a", 10), ("b", 5))
        self.assertEqual([(r["angle"], r["dur"]) for r in A.runs(s)], [("a", 20), ("b", 5)])
        s[1]["start"] += 3   # a gap splits same-angle runs
        s[1]["dur"] -= 3
        self.assertEqual(len(A.runs(s)), 3)
        self.assertEqual(len(A.runs(s, tol=3)), 2)


class Smooth(unittest.TestCase):
    def test_short_run_joins_longer_neighbour(self):
        s = segs(("a", 100), ("b", 10), ("pip", 60))
        flips = A.smooth(s, 48)
        self.assertEqual([x["angle"] for x in s], ["a", "a", "pip"])
        self.assertEqual(flips, [{"start": 100, "dur": 10, "from": "b", "to": "a"}])

    def test_tie_goes_to_earlier(self):
        s = segs(("a", 60), ("b", 10), ("pip", 60))
        A.smooth(s, 48)
        self.assertEqual(s[1]["angle"], "a")

    def test_sandwich_fuses(self):
        s = segs(("a", 60), ("b", 6), ("a", 60))
        A.smooth(s, 48)
        self.assertEqual({x["angle"] for x in s}, {"a"})

    def test_edges(self):
        s = segs(("b", 10), ("a", 100), ("b", 12))
        A.smooth(s, 48)
        self.assertEqual({x["angle"] for x in s}, {"a"})

    def test_alternating_flicker_collapses(self):
        s = segs(*[("a" if k % 2 else "b", 12) for k in range(10)])
        A.smooth(s, 48)
        rs = A.runs(s)
        self.assertTrue(all(r["dur"] >= 48 for r in rs) or len(rs) == 1)

    def test_short_runs_merge_together(self):
        # two short runs side by side: the shortest goes first and the
        # combined run reaches the minimum
        s = segs(("a", 100), ("b", 20), ("pip", 30), ("a", 100))
        A.smooth(s, 48)
        rs = A.runs(s)
        self.assertTrue(all(r["dur"] >= 48 for r in rs))

    def test_isolated_run_left_alone(self):
        s = [{"start": 0, "dur": 100, "angle": "a"},
             {"start": 200, "dur": 10, "angle": "b"},
             {"start": 300, "dur": 100, "angle": "a"}]
        self.assertEqual(A.smooth(s, 48), [])
        self.assertEqual(s[1]["angle"], "b")

    def test_already_clean_and_single(self):
        self.assertEqual(A.smooth(segs(("a", 100), ("b", 100)), 48), [])
        self.assertEqual(A.smooth(segs(("b", 5)), 48), [])
        self.assertEqual(A.smooth([], 48), [])

    def test_minimum_holds_after_smoothing(self):
        import random
        rnd = random.Random(7)
        for _ in range(200):
            s = segs(*[(rnd.choice(ALL), rnd.randint(4, 90)) for _ in range(rnd.randint(1, 40))])
            total = sum(x["dur"] for x in s)
            A.smooth(s, 48)
            rs = A.runs(s)
            if total >= 48:
                self.assertTrue(all(r["dur"] >= 48 for r in rs) or len(rs) == 1, rs)


class DecisionLevel(unittest.TestCase):
    def setUp(self):
        # 24 fps, segment durations in frames
        durs = [96, 24, 120, 30, 30, 200]
        self.segments, t = [], 86400
        for i, d in enumerate(durs):
            self.segments.append({"id": i, "record_in": t, "record_out": t + d})
            t += d
        angs = ["a", "b", "pip", "a", "pip", "pip"]
        self.dec = {i: {"id": i, "angle": a, "confidence": "high", "why": "w"}
                    for i, a in enumerate(angs)}

    def test_smooth_decisions(self):
        flips = A.smooth_decisions(self.segments, self.dec, 24, 2.0)
        angs = [self.dec[i]["angle"] for i in range(6)]
        # the 1 s B run joins the longer PiP neighbour, the 1.25 s A run too
        self.assertEqual(angs, ["a", "pip", "pip", "pip", "pip", "pip"])
        self.assertEqual({f["id"] for f in flips}, {1, 3})
        self.assertTrue(self.dec[1]["why"].startswith("smoothed"))
        st = A.run_stats(self.segments, self.dec, 24)
        self.assertEqual(st["runs"], 2)
        self.assertGreaterEqual(st["shortest_run_s"], 2.0)

    def test_build_jobs(self):
        self.dec[4]["confidence"] = "low"
        del self.dec[5]
        j = A.build_jobs(self.segments, self.dec)
        starts = [s["record_in"] for s in self.segments]
        self.assertEqual(j["enable_v2"], [starts[1], starts[2], starts[4]])
        self.assertEqual(j["pip_v3"], [starts[2], starts[4]])
        self.assertEqual(j["low"], [starts[4]])
        self.assertEqual(j["missing"], [5])


class PipGeometry(unittest.TestCase):
    def test_defaults_top_right(self):
        p = A.pip_params()
        g = A.pip_geometry(p)
        x0, y0, x1, y1 = g["box"]
        self.assertAlmostEqual(x1, 1 - 0.02, places=3)
        self.assertAlmostEqual(y0, 0.03, places=3)
        self.assertAlmostEqual(x1 - x0, 0.23, places=3)
        ins = g["inspector"]
        # a centred face in the top half of a 4K frame
        self.assertAlmostEqual(ins["CropLeft"], 1300, delta=2)
        self.assertAlmostEqual(ins["CropRight"], 1300, delta=2)
        self.assertEqual(ins["CropTop"], 0)
        self.assertAlmostEqual(ins["CropBottom"], 1101.6, delta=1)
        self.assertGreater(ins["Pan"], 0)       # moved right
        f = g["fusion"]
        # where the face centre lands after scale + translate == the box centre
        s = f["transform_size"]
        cx, cy = f["mask_center"]
        tx, ty = f["transform_center"]
        self.assertAlmostEqual(0.5 + (cx - 0.5) * s + tx - 0.5, (x0 + x1) / 2, places=3)
        self.assertAlmostEqual(0.5 + (cy - 0.5) * s + ty - 0.5, 1 - (y0 + y1) / 2, places=3)

    def test_corners(self):
        for corner in A.CORNERS:
            g = A.pip_geometry(A.pip_params({"corner": corner, "margin": [0.05, 0.05]}))
            x0, y0, x1, y1 = g["box"]
            self.assertAlmostEqual(x0 if corner.endswith("left") else 1 - x1, 0.05, places=6)
            self.assertAlmostEqual(y0 if corner.startswith("top") else 1 - y1, 0.05, places=6)
            tilt = g["inspector"]["Tilt"]
            # positive Tilt moves the image up: top corners tilt up
            if corner.startswith("bottom"):
                self.assertLess(tilt, 0)

    def test_bad_corner_and_box(self):
        with self.assertRaises(SystemExit):
            A.pip_params({"corner": "middle"})
        with self.assertRaises(SystemExit):
            A.pip_geometry(A.pip_params({"face_box": [0.6, 0.0, 0.4, 0.5]}))


class Preferences(unittest.TestCase):
    def test_sections(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "preferences.md")
            p.write_text("# Prefs\n\n## general\n- experienced editor\n\n"
                         "## aroll-draft\n- keep jokes\n\n## multicam-angles\n"
                         "- camera B is a side view\n- PiP bottom-left\n")
            out = A.read_preferences(path=p)
            self.assertIn("experienced editor", out)
            self.assertIn("side view", out)
            self.assertNotIn("keep jokes", out)
            self.assertEqual(A.read_preferences(path=Path(d, "missing.md")), "")


class CliEndToEnd(unittest.TestCase):
    def run_tt(self, *args, ok=(0,)):
        r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "timeline_transcript.py"), *args],
                           capture_output=True, text=True)
        self.assertIn(r.returncode, ok, r.stderr + r.stdout)
        return r

    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            media = d / "camA.mov"
            # transcript: one word per second, "w0".."w59"
            words = [{"start": k + 0.1, "end": k + 0.6, "word": f" w{k}"} for k in range(60)]
            (d / "camA.transcript.json").write_text(json.dumps(
                {"segments": [{"start": 0, "end": 60, "text": "", "words": words}],
                 "_meta": {"source_name": "camA.mov"}}))
            # live dump: 6 clips of 10 s source each, 5 s kept from each, 24 fps
            v1, v2, rec = [], [], 86400
            for i in range(6):
                c = {"record_in": rec, "record_out": rec + 120, "duration": 120,
                     "left_offset": i * 240, "enabled": True, "name": "camA.mov",
                     "path": str(media)}
                v1.append(c)
                v2.append({**c, "enabled": False, "name": "camB.mov"})
                rec += 120
            (d / "dump.json").write_text(json.dumps(
                {"timeline": "t", "fps": "24", "v1": v1, "v2": v2}))
            job = d / "job.json"
            job.write_text(json.dumps({"project": "p", "timeline": "t", "offset_s": 0.5,
                                       "fps": "24", "angles": {"b": {"name": "side"}},
                                       "pip": {"corner": "bottom-left"}}))
            tt = d / "tt.json"
            r = self.run_tt("map", str(d / "dump.json"), "-o", str(tt), "--job", str(job))
            info = json.loads(r.stdout)
            self.assertEqual(info["segments"], 6)
            self.assertEqual(info["words"], 30)
            seg1 = json.loads(tt.read_text())["segments"][1]
            self.assertTrue(seg1["text"].startswith("w10"))
            self.assertAlmostEqual(seg1["words"][0]["t"], 3600 + 5 + 0.1, places=2)

            bdir = d / "batches"
            r = self.run_tt("batches", str(tt), str(bdir), "--minutes", "0.25",
                            "--job", str(job))
            plan = json.loads((bdir / "plan.json").read_text())["batches"]
            self.assertEqual(len(plan), 2)
            prompt = Path(plan[0]["prompt"]).read_text()
            self.assertIn('"side"', prompt)
            self.assertIn("## Rules", prompt)
            # agents answer; batch 2 forgets one id first
            Path(plan[0]["decisions"]).write_text(json.dumps(
                [{"id": 0, "angle": "a"}, {"id": 1, "angle": "side"},
                 {"id": 2, "angle": "pip", "confidence": "low"}]))
            Path(plan[1]["decisions"]).write_text("```json\n" + json.dumps(
                [{"id": 3, "angle": "pip"}, {"id": 4, "angle": "a"}]) + "\n```")
            dec = d / "dec.json"
            r = self.run_tt("merge", str(bdir), "-o", str(dec), "--job", str(job), ok=(3,))
            self.assertIn("id 5 has no decision", r.stdout)
            Path(plan[1]["decisions"]).write_text(json.dumps(
                [{"id": 3, "angle": "pip"}, {"id": 4, "angle": "a"}, {"id": 5, "angle": "a"}]))
            r = self.run_tt("merge", str(bdir), "-o", str(dec), "--job", str(job))
            self.assertEqual(json.loads(r.stdout)["low_confidence"], [2])

            self.run_tt("review", str(dec), str(tt), "-o", str(d / "review.md"),
                        "--out", str(d / "corr.json"), "--plan", str(bdir / "plan.json"),
                        "--job", str(job))
            review = (d / "review.md").read_text()
            self.assertIn("---- batch seam ----", review)
            self.assertIn("flicker candidates", review)

            (d / "corr.json").write_text(json.dumps([{"id": 1, "angle": "a", "why": "seam"}]))
            r = self.run_tt("apply", str(dec), str(d / "corr.json"), "--job", str(job))
            self.assertEqual(json.loads(r.stdout)["changed"], [1])

            r = self.run_tt("smooth", str(dec), str(tt), "--job", str(job),
                            "--min-run-s", "6")
            out = json.loads(r.stdout)
            self.assertGreaterEqual(out["shortest_run_s"], 6)

            # frame-judge brief from a fake frames index
            fdir = d / "frames"
            fdir.mkdir()
            (fdir / "index.json").write_text(json.dumps(
                [{"i": 0, "k": k, "record_in": v1[2]["record_in"], "sheet": "psheet_01.jpg",
                  "row": 1, "col": k + 1, "cols": 2} for k in range(2)]))
            self.run_tt("brief", str(fdir), str(dec), str(tt), "-o", str(d / "brief.md"),
                        "--out", str(d / "fj.json"), "--job", str(job))
            self.assertIn("segment id 2", (d / "brief.md").read_text())

            jdir = d / "jobs"
            r = self.run_tt("jobs", str(dec), str(tt), str(jdir), "--job", str(job))
            pip = json.loads((jdir / "pip.json").read_text())
            self.assertEqual(pip["corner"], "bottom-left")
            enable = json.loads((jdir / "decisions.json").read_text())["enable_v2"]
            self.assertTrue(set(pip["pip_v3"]) <= set(enable))


if __name__ == "__main__":
    unittest.main(verbosity=1)
