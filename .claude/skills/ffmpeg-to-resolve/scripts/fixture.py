#!/usr/bin/env python3
"""A synthetic talking-head-ffmpeg project that uses every recipe feature once: the converter's regression test.

    fixture.py [DIR] [--force]      # default DIR: <cache folder>/ffmpeg-to-resolve-fixture

Writes DIR as a project folder (the footage and work folders of the user's layout, a recipe_v1.json) with generated
media: test patterns that move every frame and carry the clip's name and frame number, noise for sound (a
cross-correlation peak is one sample wide). The recipe has jump cuts, a separately recorded mic (take_audio: offset +
drift), a voice-over keep with gain_db, bricks at 23.976 / 25 / 30 / 59.94 / 60 fps, a 59.94p slow-mo at speed 0.4, a
half-speed brick, a small clip, a portrait clip (cover and blur), a full-range clip, zooms, a push-in ("to"), a grade,
an alpha .mov overlay, a PNG overlay with a fade, a need and a fade_out. Two library-style clips start their picture a
frame after the file does, the take and one brick carry a time-of-day timecode track, and on a Mac the mic recording
is Apple AAC (its stream starts 0.044 s in). Two clips are never used, so the unused bins have something in them.

Run it after a Resolve update, then render / plan / bake / build / verify the fixture (SKILL.md): a call whose
behaviour moved shows up here, on frames you can read, before it reaches a real video. 1920x1080, a minute or two.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "talking-head-ffmpeg" / "scripts"))
import _common as C  # noqa: E402

FPS = Fraction(24000, 1001)
TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]


def enc():
    return C.media.h264_args("final", height=1080) + TAGS


def ff(*args):
    r = subprocess.run([C.ffmpeg(), "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffmpeg failed: {' '.join(args)[-300:]}\n{r.stderr[-600:]}")


def pattern(name, size, rate, hue, soft=False):
    """A moving test pattern, with the clip's name and frame number burned in when a font is found. soft: low contrast
    and saturation, like footage - colour bars sit on the edge of the RGB gamut, and a grade pushes them out of it."""
    w, h = map(int, size.split("x"))
    font = next((f for f in FONTS if os.path.exists(f)), None)
    text = ""
    if font:
        fnt = font.replace("\\", "/").replace(":", "\\:")
        text = (f",drawtext=fontfile='{fnt}':text='{name} %{{n}}':fontsize={max(min(w, h) // 9, 24)}:fontcolor=white:"
                f"box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h*0.62")
    return f"testsrc2=size={size}:rate={rate},hue=h={hue}{',eq=contrast=0.55:saturation=0.45' if soft else ''}{text}"


def video(path, name, size, rate, dur, hue, audio_seed=None, tc=None, extra=(), soft=False):
    """tc: a start timecode, as a camera writes the time of day (";" before the frames = drop-frame)."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    a = (["-f", "lavfi", "-i", f"anoisesrc=color=pink:seed={audio_seed}:sample_rate=48000:amplitude=0.25",
          "-ac", "2", "-c:a", "pcm_s16le"] if audio_seed is not None else [])
    ff("-f", "lavfi", "-i", pattern(name, size, rate, hue, soft), *a, "-t", str(dur), *enc(), *extra,
       *(["-timecode", tc] if tc else []), str(path))


def f2s(f):
    return round(float(f / FPS), 6)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--force", action="store_true", help="regenerate media that already exists")
    a = ap.parse_args()
    P = Path(a.dir).expanduser().resolve() if a.dir else C.settings.cache_dir("ffmpeg-to-resolve-fixture")
    if a.force and P.exists():
        shutil.rmtree(P)
    F = P / C.settings.layout("footage")
    W = P / C.settings.layout("work") / "talking-head"
    take = F / "aroll-1-desk" / "take.mov"
    mic = F / "aroll-1-desk" / "mic-recording.m4a"
    vo = W / "vo" / "vo.mov"
    b24, b24u = F / "broll-1-product" / "b24.mp4", F / "broll-1-product" / "b24_unused.mp4"
    lib_v, lib_va = F / "broll-1-product" / "lib_v.mp4", F / "broll-1-product" / "lib_va.mp4"
    soft = F / "broll-1-product" / "soft.mp4"
    b60, b60u = F / "broll-2-slowmo" / "b60.mp4", F / "broll-2-slowmo" / "b60_unused.mp4"
    b30, b25, b60s = F / "broll-3-web" / "b30.mp4", F / "broll-3-web" / "b25.mp4", F / "broll-3-web" / "b60s.mp4"
    b5994 = F / "broll-3-web" / "b5994_rt.mp4"
    small, portrait, fullr = F / "broll-4-odd" / "small.mp4", F / "broll-4-odd" / "portrait.mp4", F / "broll-4-odd" / "fullrange.mp4"
    ov = W / "motion" / "out" / "ov.mov"
    tag = W / "graphics" / "tag.png"

    video(take, "TAKE", "1920x1080", "24000/1001", 40, 0, audio_seed=1, tc="10:24:24:00")   # camera sound, never heard
    if not mic.exists():      # the separately recorded mic. On a Mac: Apple's AAC encoder, whose 2112 priming samples
        # become a 0.044 s stream start that ffmpeg skips and Resolve counts (measured: 44 ms late until plan.py adds it)
        mic.parent.mkdir(parents=True, exist_ok=True)
        noise = ["-f", "lavfi", "-i", "anoisesrc=color=pink:seed=7:sample_rate=48000:amplitude=0.25", "-t", "45", "-ac", "1"]
        if shutil.which("afconvert"):
            wav = mic.with_suffix(".tmp.wav")
            ff(*noise, "-c:a", "pcm_s16le", str(wav))
            subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "192000", str(wav), str(mic)], check=True)
            wav.unlink()
        else:
            ff(*noise, "-c:a", "aac", "-b:a", "192k", str(mic))
    if not vo.exists():       # a voice-over carrier: black picture, its own sound
        vo.parent.mkdir(parents=True, exist_ok=True)
        ff("-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=24000/1001", "-f", "lavfi",
           "-i", "anoisesrc=color=pink:seed=9:sample_rate=48000:amplitude=0.2", "-t", "8", "-ac", "2", *enc(), "-c:a", "pcm_s24le", str(vo))
    video(b24, "B24", "1920x1080", "24000/1001", 12, 60)
    video(b24u, "B24-UNUSED", "1920x1080", "24000/1001", 4, 75)
    video(soft, "SOFT", "1920x1080", "24000/1001", 6, 90, soft=True)      # the graded brick: in-gamut colours
    # library-style clips: the picture starts one frame after the container does - one with no sound (the container
    # starts with the picture) and one whose sound starts at 0 (it does not)
    video(lib_v, "LIBV", "1920x1080", "24000/1001", 4, 20, extra=["-video_track_timescale", "24000", "-output_ts_offset", "0.041708"])
    if not lib_va.exists():
        tmp = lib_va.with_suffix(".tmp.mp4")
        ff("-f", "lavfi", "-i", pattern("LIBVA", "1920x1080", "24000/1001", 40), "-f", "lavfi", "-i", "anoisesrc=sample_rate=48000:amplitude=0.1",
           "-t", "4", *enc(), "-video_track_timescale", "24000", "-c:a", "aac", str(tmp))
        ff("-itsoffset", "0.041708", "-i", str(tmp), "-i", str(tmp), "-map", "0:v", "-map", "1:a", "-c", "copy", str(lib_va))
        tmp.unlink()
    video(b60, "B60", "1920x1080", "60000/1001", 6, 120, audio_seed=3)
    video(b60u, "B60-UNUSED", "1920x1080", "60000/1001", 3, 135)
    video(b30, "B30", "1920x1080", "30", 6, 180)
    video(b25, "B25", "1920x1080", "25", 6, 210)
    video(b60s, "B60S", "1920x1080", "60", 6, 240)
    video(b5994, "B5994RT", "1920x1080", "60000/1001", 6, 255, tc="10:20:52;08")     # a camera's 59.94p at real time
    video(small, "SMALL", "960x540", "24000/1001", 6, 270)
    video(portrait, "PORTRAIT", "1080x1920", "30", 6, 300)
    if not fullr.exists():    # a phone screen recording: full range, bt470bg
        fullr.parent.mkdir(parents=True, exist_ok=True)
        ff("-f", "lavfi", "-i", pattern("FULLRANGE", "1920x1080", "30", 330), "-t", "6", "-vf", "scale=out_range=pc:out_color_matrix=bt470bg",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuvj420p", "-color_range", "pc", "-colorspace", "bt470bg", str(fullr))
    if not ov.exists():       # a motion-graphics panel: half-size ProRes 4444 with alpha, moving
        ov.parent.mkdir(parents=True, exist_ok=True)
        ff("-f", "lavfi", "-i", "color=c=black@0.0:s=960x540:r=24000/1001,format=rgba", "-f", "lavfi",
           "-i", "color=c=0x1565C0@0.85:s=300x110:r=24000/1001,format=rgba", "-filter_complex",
           "[0][1]overlay=x='60+50*t':y=60:format=auto,format=yuva444p10le", "-t", "4", "-c:v", "prores_ks", "-profile:v", "4444",
           "-pix_fmt", "yuva444p10le", str(ov))
    if not tag.exists():      # a frame-sized RGBA price tag
        tag.parent.mkdir(parents=True, exist_ok=True)
        ff("-f", "lavfi", "-i", "color=c=black@0.0:s=1920x1080,format=rgba", "-f", "lavfi", "-i", "color=c=0xF9A825@0.9:s=520x160,format=rgba",
           "-filter_complex", "[0][1]overlay=x=1300:y=120:format=auto,format=rgba", "-frames:v", "1", str(tag))

    S = str

    def k(f, a_, b_, **x):
        return {"file": S(f), "in_s": f2s(a_), "out_s": f2s(b_), **x}
    # keeps in source frames; the record clock in frames is their running sum (0, 96, 204, 216, 384, 480, 696)
    aroll = [k(take, 48, 144), k(take, 180, 288), k(take, 312, 324), k(take, 360, 528), k(vo, 12, 108, gain_db=1.1), k(take, 576, 792)]

    def b(rec, n, f, in_s, why, **x):
        return {"record_s": f2s(rec), "dur": f2s(n), "file": S(f), "in_s": in_s, "speed": x.pop("speed", 1.0), "why": why, **x}
    broll = [
        b(24, 48, b24, 1.0, "plain 23.976 brick"),
        b(112, 60, b60, 0.5, "59.94p slow-mo, frame for frame", speed=0.4),
        b(172, 44, b24, 9.5, "half speed on a 23.976 clip (the item's Speed, not a conform)", speed=0.5),
        b(244, 44, b30, 0.7, "30 fps at real time"),
        b(288, 38, b25, 1.2, "25 fps at real time, back to back"),
        b(326, 30, b60s, 0.5, "60 fps screen recording, punched in", zoom={"z": 1.5, "cx": 0.667, "cy": 0.5}),
        b(356, 28, b5994, 0.6, "59.94p with a drop-frame time-of-day timecode, at real time"),
        b(384, 32, small, 0.5, "a 960x540 clip scaled up (over the voice-over)"),
        b(416, 32, portrait, 0.4, "portrait, cover about its top", fit="cover", zoom={"z": 1.0, "cx": 0.5, "cy": 0.3}),
        b(448, 32, portrait, 2.6, "portrait over a blurred copy", fit="blur"),
        b(480, 28, lib_va, 0.25, "library clip: picture starts a frame after its sound"),
        b(508, 36, fullr, 1.0, "full-range bt470bg source"),
        b(544, 28, lib_v, 0.25, "library clip: picture only, starting a frame after zero"),
        b(572, 30, soft, 2.0, "graded", grade={"gamma": 1.4, "gain": 1.08, "sat": 1.1}),
        b(602, 30, b24, 8.0, "2x punch-in off centre", zoom={"z": 2.0, "cx": 0.75, "cy": 0.38}),
        b(660, 36, b24, 3.2, "slow push-in to the end", zoom={"z": 1.0, "to": 1.14, "cx": 0.5, "cy": 0.42}),
    ]
    recipe = {
        "name": "fixture", "project": S(P), "fps": "24000/1001", "width": 1920, "height": 1080, "lufs": -14,
        "aroll": aroll, "broll": broll,
        "take_audio": {S(take): {"file": S(mic), "offset_s": -1.720335, "rate": 1.000027684}},
        "overlays": [{"record_s": f2s(8), "dur": f2s(72), "file": S(ov), "fade": 0, "why": "alpha panel over a-roll and a brick"},
                     {"record_s": f2s(512), "dur": f2s(60), "file": S(tag), "fade": 0.2, "why": "PNG tag with a fade"}],
        "needs": [{"record_s": f2s(540), "end_s": f2s(560), "note": "fixture need - no shot of this"}],
        "fade_out": 1.2,
    }
    W.mkdir(parents=True, exist_ok=True)
    rp = W / "recipe_v1.json"
    C.write_json(rp, recipe)
    print(json.dumps({"project": str(P), "recipe": str(rp), "frames": 696, "keeps": len(aroll), "bricks": len(broll)}))


if __name__ == "__main__":
    main()
