#!/usr/bin/env python3
"""Cut an unboxing / install sequence from long takes into separate, ordered beats.

A sequence is a run of SEPARATE clips, one per beat, numbered in order;
dropping them on a timeline back to back rebuilds the paced sequence. This
script plans the beats and renders the assembled preview (exactly those clips
back to back) for pace review; export_clips.py cuts the beats as library clips
once the pace is agreed.

The moments file says WHAT is worth keeping (read off overview.py's sheets):
each moment is a rough source range plus its kind. This script decides HOW
MUCH of each to keep, from the sound and a pace profile (../paces.json):

  establish  the sealed box shown before anything happens: keep the head, up to establish.max
  sound      an action you watch for its sound (knife on tape, tearing a seal, shrink
             wrap, peeling film, a lid sliding off): keep the first-to-last sound event
             plus pre / post buffers, at most sound.max (the busiest window when longer)
  action     a visual action (lifting the phone out, unfolding it): the same rule on
             its sound events, or the head of the range when it makes no sound
  hold       the product held up and turned, an accessory shown: keep the head, up to hold.max
             (hold.hero_max for a moment marked "hero": the reveal, the side-to-side turn)

Sound events are 20 ms frames where the 3-10 kHz band (crinkles, peels, the knife)
rises 9 dB over the source's quiet floor, or the full band 12 dB over its floor
(a card tab tearing is mostly low-mid), merged across gaps under 0.25 s, minus
anything inside a transcript word.
Every cut then moves (by at most pace.snap) to the quietest 20 ms near it, so
no cut lands in the middle of a sound, and a cut that would split a spoken
word moves to the word's edge (sources with a transcript). Back-to-back
moments from one take merge into one beat. Every beat's audio fades in and out
over pace.fade (10 ms: no click where two clips meet); picture cuts hard,
frame-exact.

    sequence.py MOMENTS.json --pace steady -o OUT.mp4 [--res 1080|2160] [--plan-only]

Writes OUT.mp4 (the assembled preview), OUT.plan.json (every beat: source
frames, position in the sequence, section) and OUT.review/cuts.json
(edit-review-cuts/1, so EditReview names the beat under each note). Picture:
H.264 through vidkit.media (hardware encoder where there is one); 2160 renders
at the library's final quality, 1080 as a review draft.
"""
import argparse, json, math, os, subprocess, sys, tempfile
from datetime import datetime, timezone

try:
    import numpy as np
except ImportError:
    sys.exit("this script needs numpy scipy: python3 -m pip install numpy scipy")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "tools"))
from vidkit import media  # noqa: E402

WORD_MAX_S = 1.2


def transcript_words(doc, offset=0.0, max_s=WORD_MAX_S):
    """[(word, [(start, end), ...])] from a transcript sidecar ({"segments": [{"words": [...]}]}), shifted by
    `offset`. A word up to `max_s` long keeps its span. A longer one absorbed a silence on one side, and the
    transcript cannot say which, so it gets both ends (`max_s` each) as the places it may have been said: muting
    both silences the word wherever it is, and the silence between stays free for sounds and cuts."""
    out = []
    for seg in (doc or {}).get("segments", []) or []:
        for w in seg.get("words", []) or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            s, e = float(w["start"]) + offset, float(w["end"]) + offset
            spans = [(s, e)] if e - s <= max_s else [(s, s + max_s), (e - max_s, e)]
            out.append((w.get("word") or "", spans))
    return out

SR = 48000
HOP = 0.02
EVENT_DB = 9.0          # over the quiet floor of the 3-10 kHz band
EVENT_FULL_DB = 12.0    # over the quiet floor of the full band
EVENT_GAP = 0.25        # events closer than this are one event
EVENT_MIN = 0.06


def probe(path):
    out = json.loads(subprocess.run(
        [media.which("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate,width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout)
    s = out["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return {"fps": int(n) / int(d), "width": s["width"], "height": s["height"],
            "duration": float(out["format"]["duration"])}


def pcm(path, start, dur, channels):
    """float32 [n, channels] at SR from start (zero-padded before 0)."""
    pad = max(0.0, -start)
    cmd = [media.ffmpeg(), "-v", "error", "-ss", f"{max(0.0, start):.6f}", "-t", f"{dur - pad:.6f}", "-i", path,
           "-vn", "-ac", str(channels), "-ar", str(SR), "-f", "f32le", "-"]
    x = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32)
    x = x.reshape(-1, channels)
    if pad:
        x = np.concatenate([np.zeros((int(round(pad * SR)), channels), np.float32), x])
    want = int(round(dur * SR))
    if len(x) < want:
        x = np.concatenate([x, np.zeros((want - len(x), channels), np.float32)])
    return x[:want]


def envelopes(mono):
    from scipy.signal import butter, sosfilt
    hi = sosfilt(butter(4, [3000, 10000], btype="band", fs=SR, output="sos"), mono)
    n = int(HOP * SR)
    k = len(mono) // n

    def db(x):
        return 20 * np.log10(np.sqrt(np.mean(x[:k * n].reshape(k, n) ** 2, axis=1) + 1e-12) + 1e-9)
    return db(mono), db(hi)


class Source:
    def __init__(self, key, spec):
        spec = {"path": spec} if isinstance(spec, str) else spec
        self.key, self.path = key, spec["path"]
        self.flip = bool(spec.get("flip"))                  # rig mounted upside down: rotate 180
        self.speech = spec.get("speech", "keep")            # "mute": words silenced, the sounds between kept
        self.meta = probe(self.path)
        self.fps = self.meta["fps"]
        self.words = []
        if spec.get("transcript"):                         # transcript_offset: this camera's time - the transcript's
            t, off = json.load(open(spec["transcript"])), float(spec.get("transcript_offset", 0.0))
            # a word stretched over a silence counts at both ends, not across it (transcript_words)
            self.words = [sp for _, spans in transcript_words(t, off) for sp in spans]
        self.mute = mute_spans(self.words) if self.speech == "mute" else []
        self.env = {}          # moment index -> (t0, full, high)
        self.floor_hi = self.floor_full = None

    def load_env(self, i, a, b):
        t0 = a - 1.0
        x = pcm(self.path, t0, (b + 1.0) - t0, 1)[:, 0]
        self.env[i] = (t0,) + envelopes(x)


def runs(mask, gap, min_len):
    """[(s, e)] in hop units of True runs, merging gaps < gap and dropping runs < min_len (seconds)."""
    out = []
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if out and (i - out[-1][1]) * HOP < gap:
                out[-1] = (out[-1][0], j)
            else:
                out.append((i, j))
            i = j
        else:
            i += 1
    return [(s, e) for s, e in out if (e - s) * HOP >= min_len]


def plan(moments, sources, pace):
    beats = []
    for i, m in enumerate(moments):
        src = sources[m["src"]]
        kind, a, b = m["kind"], float(m["a"]), float(m["b"])
        rule = pace[kind]
        cap = float(m.get("max", rule["hero_max"] if m.get("hero") and "hero_max" in rule else rule["max"]))
        t0, full, high = src.env[i]
        idx = lambda t: int(round((t - t0) / HOP))     # noqa: E731
        events = []
        if kind in ("sound", "action"):
            seg, segf = high[idx(a):idx(b)], full[idx(a):idx(b)]
            mask = (seg > src.floor_hi + EVENT_DB) | (segf > src.floor_full + EVENT_FULL_DB)
            for ws, we in src.words:   # a narrated take: only the sound BETWEEN the words is an event
                if we > a and ws < b:
                    mask[max(0, int((ws - a) / HOP)):max(0, int((we - a) / HOP) + 1)] = False
            events = [(a + s * HOP, a + e * HOP, float(np.sum(10 ** (seg[s:e] / 10))))
                      for s, e in runs(mask, EVENT_GAP, EVENT_MIN)]
            if src.words:   # an event that is all speech is not a sound beat
                events = [ev for ev in events
                          if not any(ws <= ev[0] and ev[1] <= we + 0.05 for ws, we in src.words)]
        if m.get("keep") == "all":
            tin, tout = a, b
        elif events:
            pre, post = rule["pre"], rule["post"]
            tin, tout = max(a, events[0][0] - pre), min(b, events[-1][1] + post)
            if tout - tin > cap:                       # busiest window of length cap
                best = None
                for ev in events:
                    st = max(a, ev[0] - pre)
                    en = min(b, st + cap)
                    score = sum(min(en, e2) - max(st, s2) for s2, e2, _ in events if e2 > st and s2 < en)
                    if best is None or score > best[0] + 1e-6:
                        best = (score, st, en)
                tin, tout = best[1], best[2]
        else:
            tin, tout = a, min(b, a + cap)

        snap = pace["snap"]

        def quiet(t, lo, hi):
            i0, i1 = max(0, idx(lo)), min(len(full), idx(hi) + 1)
            if i1 <= i0:
                return t
            k = int(np.argmin(full[i0:i1]))
            return t0 + (i0 + k) * HOP + HOP / 2
        if m.get("keep") != "all":
            sin = quiet(tin, max(a - snap / 2, tin - snap), tin + snap / 2)
            sout = quiet(tout, tout - snap / 2, min(b + snap / 2, tout + snap))
            if sout - sin > cap + 0.5 / src.fps:       # the snap may not grow a beat past its cap: snap inward only
                sin, sout = quiet(tin, tin, tin + snap), quiet(tout, tout - snap, tout)
            tin, tout = sin, sout
        for ws, we in (src.words if src.speech != "mute" else ()):   # never split a spoken word (a muted one is silent)
            if ws < tin < we:
                tin = we + 0.03 if we + 0.03 < tout - pace["min_beat"] else ws - 0.03
            if ws < tout < we:
                tout = ws - 0.03 if ws - 0.03 > tin + pace["min_beat"] else we + 0.03
        if tout - tin < pace["min_beat"] and kind not in ("establish", "hold"):
            # a beat the moments file named is never dropped: grow it to min_beat inside the moment
            tout = min(b, tin + pace["min_beat"])
            tin = max(a, tout - pace["min_beat"])
        last = int(src.meta["duration"] * src.fps + 1e-6)   # frames in the take: no beat runs past its end
        f_in, f_out = max(0, int(round(tin * src.fps))), min(last, int(round(tout * src.fps)))
        speech = [w for w in src.words if w[1] > tin and w[0] < tout]
        beats.append({"src": m["src"], "path": src.path, "kind": kind, "hero": bool(m.get("hero")),
                      "label": m.get("label", ""), "description": m.get("description", ""),
                      "section": m.get("section", ""), "f_in": f_in, "f_out": f_out,
                      "in": round(f_in / src.fps, 3), "out": round(f_out / src.fps, 3),
                      "moment": [a, b], "events": len(events), "speech_words": len(speech)})
    merged = []                                        # back-to-back in one take: one beat
    for bt in beats:
        p = merged[-1] if merged else None
        if p and p["src"] == bt["src"] and p["f_in"] < bt["f_in"] < p["f_out"]:
            bt["f_in"], bt["in"] = p["f_out"], round(p["f_out"] / sources[bt["src"]].fps, 3)   # never a frame twice
        if p and p["src"] == bt["src"] and 0 <= bt["f_in"] - p["f_out"] <= 1:
            p["f_out"], p["out"] = bt["f_out"], bt["out"]
            p["label"] = f'{p["label"]} + {bt["label"]}'
            continue
        merged.append(dict(bt))
    t = 0.0
    for bt in merged:
        fps = sources[bt["src"]].fps
        bt["start_s"] = round(t, 6)
        t += (bt["f_out"] - bt["f_in"]) / fps
        bt["end_s"] = round(t, 6)
    return merged


MUTE_GAIN = 0.0         # a muted word is silent: at -40 dB speech recognition still read the words,
                        # and a library's talking-head check runs exactly that on b-roll clips
MUTE_RAMP = 0.03
MUTE_PAD = 0.08         # transcript word times run ~0.1 s off the audio: word edges slipped past the mute
MUTE_BRIDGE = 0.25      # and a gap this short between two words held only a speech fragment, never a sound


def mute_spans(words):
    """Word spans padded by MUTE_PAD and bridged across gaps under MUTE_BRIDGE: what speech: mute silences.
    Without the pad and bridge, a transcriber still read 'All right' / 'Oh' out of the fragments."""
    out = []
    for ws, we in sorted(words):
        ws, we = ws - MUTE_PAD, we + MUTE_PAD
        if out and ws - out[-1][1] < MUTE_BRIDGE:
            out[-1] = (out[-1][0], max(out[-1][1], we))
        else:
            out.append((ws, we))
    return out


def room_tone(seg, g, n, seed):
    """n samples of the beat's own room sound, to fill under muted words so the beat doesn't drop to
    digital silence: the quietest 40 ms chunks from outside the words, overlap-added at random with
    sqrt-Hann windows (constant power). Seeded by the beat, so the preview and the clip match."""
    L = 2048
    hop = L // 2
    starts = [i for i in range(0, len(seg) - L, hop) if g[i:i + L].min() >= 0.999]
    if len(starts) < 4:
        return np.zeros((n, 2), np.float32)
    rms = np.array([np.sqrt(np.mean(seg[i:i + L] ** 2)) for i in starts])
    quiet = [starts[k] for k in np.argsort(rms)[:max(4, len(starts) // 3)]]
    win = np.sqrt(np.hanning(L)).astype(np.float32)[:, None]
    rng = np.random.default_rng(seed)
    out = np.zeros((n + L, 2), np.float32)
    for i in range(0, n, hop):
        c = quiet[rng.integers(len(quiet))]
        out[i:i + L] += seg[c:c + L] * win
    return out[:n]


def beat_audio(src, b, x, span0, fade):
    """One beat's stereo audio cut from x (which starts at span0 s in the source), as its clip carries it:
    words replaced by the beat's own room tone when the source says speech: mute, faded in and out
    over `fade`."""
    s0 = int(round((b["f_in"] / src.fps - span0) * SR))
    n = int(round((b["f_out"] - b["f_in"]) / src.fps * SR))
    seg = x[s0:s0 + n].copy()
    seg = np.concatenate([seg, np.zeros((n - len(seg), 2), np.float32)])
    if src.speech == "mute" and src.words:
        t = b["f_in"] / src.fps + np.arange(n) / SR
        orig = seg.copy()
        g = np.ones(n, np.float32)
        for ws, we in src.mute:
            if we < t[0] - MUTE_RAMP or ws > t[-1] + MUTE_RAMP:
                continue
            # 1 outside, MUTE_GAIN inside [ws, we], linear ramps of MUTE_RAMP on both sides
            d = np.maximum(ws - t, t - we)                 # >0 outside the word, distance to it
            w = np.clip(d / MUTE_RAMP, 0, 1) * (1 - MUTE_GAIN) + MUTE_GAIN
            g = np.minimum(g, w.astype(np.float32))
        seg = seg * g[:, None] + room_tone(orig, g, n, b["f_in"]) * (1 - g)[:, None]
    nf = max(1, int(round(fade * SR)))
    seg[:nf] *= np.linspace(0, 1, nf, dtype=np.float32)[:, None]
    seg[-nf:] *= np.linspace(1, 0, nf, dtype=np.float32)[:, None]
    return seg


def render(beats, sources, out, res, fade):
    groups = []
    for bt in beats:
        g = groups[-1] if groups else None
        if g and g[0]["src"] == bt["src"] and bt["f_in"] >= g[-1]["f_out"]:
            g.append(bt)
        else:
            groups.append([bt])
    fps = sources[beats[0]["src"]].fps
    w, h = (3840, 2160) if res == 2160 else (1920, 1080)
    cmd, chains = [media.ffmpeg(), "-hide_banner", "-v", "error", "-y"], []
    for gi, g in enumerate(groups):
        src = sources[g[0]["src"]]
        S = math.floor(max(0.0, g[0]["f_in"] / src.fps - 1.0) * 1000) / 1000
        T = (g[-1]["f_out"] + 2) / src.fps - S        # read no further than the group's last beat
        cmd += ["-ss", f"{S:.3f}", "-t", f"{T:.3f}", "-i", src.path]
        sel = "+".join(f"between(t,{(b['f_in'] - 0.5) / src.fps - S:.5f},{(b['f_out'] - 0.5) / src.fps - S:.5f})"
                       for b in g)
        chain = f"[{gi}:v]select='{sel}',setpts=N/FRAME_RATE/TB"
        if src.flip:
            chain += ",hflip,vflip"
        chain += f",scale={w}:{h}"
        chains.append(chain + f"[v{gi}]")
    graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(len(groups))) + \
        f"concat=n={len(groups)}:v=1:a=0[v]"
    enc = media.h264_args("final" if res == 2160 else "draft", height=h) + ["-pix_fmt", "yuv420p"]
    tmp = tempfile.mkdtemp(prefix="unboxing-cut-")
    vid = os.path.join(tmp, "v.mp4")
    media.run(cmd + ["-filter_complex", graph, "-map", "[v]", "-an", "-r", f"{fps:.6f}"] + enc + [vid],
              check=True)

    # audio: each beat as its own clip carries it (beat_audio)
    parts = []
    for g in groups:
        src = sources[g[0]["src"]]
        span0 = g[0]["f_in"] / src.fps
        x = pcm(src.path, span0, g[-1]["f_out"] / src.fps - span0, 2)
        parts += [beat_audio(src, b, x, span0, fade) for b in g]
    acc = np.concatenate(parts)
    raw = os.path.join(tmp, "a.f32")
    acc.astype(np.float32).tofile(raw)
    subprocess.run([media.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", vid, "-f", "f32le", "-ar", str(SR),
                    "-ac", "2", "-i", raw, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-movflags", "+faststart", out], check=True)
    for f in (vid, raw):
        os.remove(f)
    os.rmdir(tmp)


def sidecar(beats, sources, out):
    fps = sources[beats[0]["src"]].fps
    cuts, f = [], 0
    for i, b in enumerate(beats, 1):
        n = b["f_out"] - b["f_in"]
        cuts.append({"index": i, "start_s": round(f / fps, 6), "end_s": round((f + n) / fps, 6),
                     "start_frame": f, "end_frame": f + n, "kind": "clip", "track": 1,
                     "name": f'{b["section"]}: {b["label"]}' if b["section"] else b["label"],
                     "source": b["path"], "source_start_frame": b["f_in"]})
        f += n
    d = os.path.splitext(out)[0] + ".review"
    os.makedirs(d, exist_ok=True)
    json.dump({"schema": "edit-review-cuts/1", "video": os.path.basename(out), "project": "unboxing-cut",
               "timeline": os.path.splitext(os.path.basename(out))[0], "frame_rate": round(fps, 6),
               "timeline_start_frame": 0, "render_in_frame": 0, "render_out_frame": f,
               "duration_s": round(f / fps, 6), "cuts": cuts, "overlays": [],
               "written": datetime.now(timezone.utc).isoformat(timespec="seconds")},
              open(os.path.join(d, "cuts.json"), "w"), indent=1)


def sections(beats):
    out = []
    for b in beats:
        if out and out[-1]["section"] == b["section"]:
            out[-1]["end_s"] = b["end_s"]
        else:
            out.append({"section": b["section"], "start_s": b["start_s"], "end_s": b["end_s"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("moments")
    ap.add_argument("--pace", default="steady")
    ap.add_argument("--paces", default=os.path.join(HERE, "..", "paces.json"))
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--res", type=int, choices=(1080, 2160), default=1080)
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(a.moments))
    pace = json.load(open(a.paces))[a.pace]
    sources = {k: Source(k, v) for k, v in spec["sources"].items()}
    for i, m in enumerate(spec["moments"]):
        sources[m["src"]].load_env(i, float(m["a"]), float(m["b"]))
    for src in sources.values():
        his = [h for t0, f, h in src.env.values()]
        fulls = [f for t0, f, h in src.env.values()]
        src.floor_hi = float(np.percentile(np.concatenate(his), 10)) if his else -90.0
        src.floor_full = float(np.percentile(np.concatenate(fulls), 10)) if fulls else -90.0
    beats = plan(spec["moments"], sources, pace)
    total = beats[-1]["end_s"]
    plan_path = os.path.splitext(a.out)[0] + ".plan.json"
    json.dump({"schema": "unboxing-cut/plan-1", "name": spec.get("name"), "product": spec.get("product"),
               "pace": a.pace, "pace_profile": pace, "moments_file": os.path.abspath(a.moments),
               "duration_s": round(total, 3), "sections": sections(beats), "beats": beats},
              open(plan_path, "w"), indent=1)
    for b in beats:
        print(f'{b["start_s"]:7.2f}  {b["end_s"] - b["start_s"]:5.2f}s  {b["kind"]:9s} {b["section"]:10s} '
              f'{b["label"][:60]}  [{b["src"]} {b["in"]:.2f}-{b["out"]:.2f}, {b["events"]} ev'
              f'{", %d words" % b["speech_words"] if b["speech_words"] else ""}]')
    print(f"{len(beats)} beats, {total:.1f}s  -> {plan_path}")
    if a.plan_only:
        return
    render(beats, sources, a.out, a.res, pace["fade"])
    sidecar(beats, sources, a.out)
    print(a.out)


if __name__ == "__main__":
    main()
