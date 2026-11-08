"""Tests on synthetic media made with ffmpeg (no camera files, no Resolve):
frames + contact sheets, scene/motion profile, the annotation store, and the
seam envelope from a real WAV. Run: python3 -B tests/test_media.py [scratch_dir]"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
import _brick as B  # noqa: E402
import seam_audit as SA  # noqa: E402

PY = sys.executable


def sh(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode:
        raise AssertionError(f"{args[:3]} failed ({r.returncode}): {r.stderr[-800:]}")
    return r


def make_clip(d):
    """12 s: 4 s red, 4 s moving test pattern, 4 s blue = two hard scene cuts."""
    out = os.path.join(d, "clip.mp4")
    ff = B.media.ffmpeg()
    sh([ff, "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=640x360:r=24:d=4",
        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=4",
        "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=24:d=4",
        "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-pix_fmt", "yuv420p", out])
    return out


def make_wav(d):
    """Tone bursts (speech stand-in) with pauses, 16 kHz mono."""
    out = os.path.join(d, "voice.wav")
    sh([B.media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
        "sine=f=220:r=16000:d=6,volume='if(between(t,0.5,1.5)+between(t,3,4.5),1,0.001)':eval=frame",
        "-ac", "1", "-c:a", "pcm_s16le", out])
    return out


def main(root):
    clip = make_clip(root)
    # frames + sheets
    fdir = os.path.join(root, "frames")
    r = sh([PY, "-B", os.path.join(SCRIPTS, "frames.py"), clip, fdir, "--interval", "1", "--candidates", "3", "--sheet"])
    assert r.stdout.strip() == fdir, r.stdout
    frames = sorted(f for f in os.listdir(fdir) if f.startswith("f"))
    assert 3 <= len(frames) <= 12, frames  # static red/blue seconds dedup away
    sheets = json.load(open(os.path.join(fdir, "sheets.json")))
    assert sheets and os.path.getsize(sheets[0]["sheet"]) > 1000, sheets
    assert sum(len(s["tiles"]) for s in sheets) == len(frames)
    print("PASS frames:", len(frames), "frames,", len(sheets), "sheet(s), labels", sheets[0]["labels_burned_in"])
    # profile
    prof = os.path.join(root, "profile.json")
    sh([PY, "-B", os.path.join(SCRIPTS, "profile_clip.py"), clip, "-o", prof])
    p = json.load(open(prof))
    assert len(p["cuts"]) >= 2 and abs(p["cuts"][0] - 4.0) < 0.2, p["cuts"]
    assert p["motion"] and p["calm"], p
    print("PASS profile: cuts", p["cuts"], "calm spans", len(p["calm"]))
    # annotation store
    store = os.path.join(root, "store")
    ann = os.path.join(root, "a.json")
    doc = {"duration_s": 12.0, "segments": [
        {"start_s": 0, "end_s": 4, "description": "flat red frame", "quality": "poor"},
        {"start_s": 4, "end_s": 8, "description": "", "quality": "good"},
        {"start_s": 8, "end_s": 12, "description": "flat blue frame", "quality": "poor"}], "annotator": "human"}
    json.dump(doc, open(ann, "w"))
    A = [PY, "-B", os.path.join(SCRIPTS, "annotations.py")]
    sh(A + ["put", clip, ann, "--store", store])
    agent = dict(doc, annotator="agent")
    agent["segments"] = [dict(s, description=s["description"] or "moving colour test pattern", quality="usable")
                         for s in doc["segments"]]
    json.dump(agent, open(ann, "w"))
    sh(A + ["put", clip, ann, "--store", store])
    got = json.loads(sh(A + ["get", clip, "--store", store]).stdout)
    assert got["annotator"] == "human" and got["segments"][1]["description"] == "moving colour test pattern"
    assert got["segments"][1]["quality"] == "good", got  # the human label survives
    st = sh(A + ["status", clip, "--store", store]).stdout
    assert st.startswith("annotated"), st
    json.dump({"segments": [{"start_s": 0, "end_s": 2}]}, open(ann, "w"))
    r = subprocess.run(A + ["put", clip, ann, "--store", store], capture_output=True, text=True)
    assert r.returncode == 3 and "description" in r.stderr, r.stderr
    print("PASS annotations: human labels kept, empty description filled, invalid doc rejected")
    # seam envelope from a real wav: bursts loud, pauses at the floor
    env = SA.Env.from_wav(make_wav(root))
    assert env.at(1.0) > env.floor + 30 and env.at(2.2) < env.floor + 3, (env.at(1.0), env.at(2.2), env.floor)
    print("PASS seam envelope: burst", round(env.at(1.0), 1), "dB, pause", round(env.at(2.2), 1), "dB")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        os.makedirs(sys.argv[1], exist_ok=True)
        main(sys.argv[1])
    else:
        with tempfile.TemporaryDirectory() as d:
            main(d)
