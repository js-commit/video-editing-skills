#!/usr/bin/env python3
"""Read the timelines of a DaVinci Resolve project export (.drp), offline.

In Resolve: Project Manager (File > Project Manager, Shift+1 opens it on some
setups), right-click the project > Export Project... writes a .drp. Resolve does
not need to be running for this module, and nothing is ever written back.

A .drp is a zip of XML files:
  MediaPool/**/MpFolder.xml   declares every timeline: name, sequence id, frame
                              rate, start timecode (MediaExtents)
  SeqContainer/<uuid>.xml     one timeline's tracks; each clip is an
                              <Sm2TiVideoClip> with these plain-text fields:
      Start, Duration   timeline frames (absolute: a 01:00:00:00 timeline at 24 fps
                        starts at 86400); "n|hex" carries a sub-frame fraction as
                        a little-endian double
      In                source in-point in frames at the clip's DECLARED rate
      MediaFilePath     absolute media path at export time
      MediaFrameRate    declared fps (hex little-endian double)
      MediaRef          media-pool item; for a nested timeline (compound clip)
                        MediaFilePath is empty and this points at the timeline

High-frame-rate footage conformed to the timeline rate in Clip Attributes (the
usual way to make slow motion) shows up as a declared rate lower than the
file's real rate; conform() turns that into speed = declared / real so the
extracted clip keeps its slow motion. A retime made with Resolve's speed tools
lives in a binary blob this module does not read: such a clip comes out at 1x.
Rotation / zoom set in the Inspector is not read either (clips are full frame).

    python3 drp.py PROJECT.drp            # list the timelines and their clip counts
"""
from __future__ import annotations

import os
import re
import struct
import sys
import zipfile

MAX_NEST_DEPTH = 8
CONFORM_TOLERANCE = 0.02


def _hex_double(h):
    if not h or len(h) < 16:
        return None
    try:
        return struct.unpack("<d", bytes.fromhex(h[:16]))[0]
    except ValueError:
        return None


def _frames(raw):
    if raw is None or raw == "":
        return None
    if "|" in raw:
        whole, frac = raw.split("|", 1)
        return int(whole) + (_hex_double(frac) or 0.0)
    try:
        return float(int(raw))
    except ValueError:
        return None


def _text(block, tag):
    m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), block, re.S)
    return m.group(1) if m else None


def is_backup_timeline(name, folder=""):
    """Timelines people keep as backups or parking lots, skipped by default."""
    n, f = (name or "").lower(), (folder or "").lower()
    return "backup" in n or "(bak" in n or n.endswith(" bak") or "backup" in f or n.startswith("old ")


class Timeline:
    def __init__(self, name, seq_id, fps, start_s, length_s, folder, tl_clip_id):
        self.name, self.seq_id, self.fps = name, seq_id, fps
        self.start_s, self.length_s = start_s or 0.0, length_s or 0.0
        self.folder, self.tl_clip_id = folder, tl_clip_id

    def __repr__(self):
        return f"<Timeline {self.name!r} {self.fps:.3f}fps>"


class Project:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._tls, self._by_tl_clip, self._containers = [], {}, {}
        with zipfile.ZipFile(self.path) as z:
            names = z.namelist()
            for n in sorted(n for n in names if n.endswith("MpFolder.xml")):
                self._read_folder(z.read(n).decode("utf-8", "replace"))
            for n in names:
                if n.startswith("SeqContainer/") and n.endswith(".xml"):
                    text = z.read(n).decode("utf-8", "replace")
                    sid = _text(text, "Sequence")
                    if sid:
                        self._containers[sid] = text

    def _read_folder(self, text):
        folder = _text(text, "Name") or ""
        for blk in re.findall(r"<Sm2Timeline DbId=.*?</Sm2Timeline>", text, re.S):
            m = re.search(r'<Sm2Sequence DbId="([^"]+)"', blk)
            if not m:
                continue
            ext = _text(blk, "MediaExtents") or ""
            tl = Timeline(_text(blk, "Name") or "", m.group(1), _hex_double(_text(blk, "FrameRate")) or 0.0,
                          _hex_double(ext[:16]) if len(ext) >= 32 else 0.0,
                          _hex_double(ext[16:32]) if len(ext) >= 32 else 0.0,
                          folder, _text(blk, "MpTimelineClip"))
            self._tls.append(tl)
            if tl.tl_clip_id:
                self._by_tl_clip[tl.tl_clip_id] = tl

    def timelines(self, include_backups=False):
        return [t for t in self._tls if t.seq_id in self._containers
                and (include_backups or not is_backup_timeline(t.name, t.folder))]

    def timeline_named(self, name):
        return next((t for t in self._tls if t.name == name), None)

    def _video_tracks(self, tl):
        text = self._containers.get(tl.seq_id) or ""
        m = re.search(r"<VideoTrackVec>(.*?)</VideoTrackVec>", text, re.S)
        if not m:
            return []
        out = []
        for i, trk in enumerate(re.findall(r"<Sm2TiTrack DbId=.*?</Sm2TiTrack>", m.group(1), re.S), start=1):
            out.append((i, re.findall(r"<Sm2TiVideoClip DbId=.*?</Sm2TiVideoClip>", trk, re.S)))
        return out

    def cuts(self, tl, depth=0, window=None, offset=0.0, track_override=None):
        """Every video clip of a timeline, nested timelines flattened:
        [{track, timeline_start, timeline_end, source_in, source_out, declared_fps,
          file_path, name}] in seconds from the timeline's own zero. source_in/out
        are in the clip's declared time base; conform() fixes HFR clips."""
        if depth > MAX_NEST_DEPTH:
            return []
        fps = tl.fps or 24.0
        start_frames = tl.start_s * fps
        out = []
        for track, clips in self._video_tracks(tl):
            trk = track_override or track
            for blk in clips:
                start, dur = _frames(_text(blk, "Start")), _frames(_text(blk, "Duration"))
                if start is None or not dur or dur <= 0:
                    continue
                t0 = (start - start_frames) / fps
                t1 = t0 + dur / fps
                k0, k1 = t0, t1
                if window is not None:
                    k0, k1 = max(k0, window[0]), min(k1, window[1])
                    if k1 <= k0:
                        continue
                path = _text(blk, "MediaFilePath") or None
                media_fps = _hex_double(_text(blk, "MediaFrameRate")) or fps
                in_frames = _frames(_text(blk, "In")) or 0.0
                lead = k0 - t0
                if not path:
                    nested = self._by_tl_clip.get(_text(blk, "MediaRef") or "")
                    if nested is not None and nested.seq_id in self._containers:
                        c0 = in_frames / (nested.fps or fps) + lead
                        out += self.cuts(nested, depth + 1, (c0, c0 + (k1 - k0)), offset + k0 - c0, trk)
                    continue
                src_in = in_frames / media_fps + lead
                out.append({"track": trk, "timeline_start": offset + k0, "timeline_end": offset + k1,
                            "source_in": src_in, "source_out": src_in + (k1 - k0), "speed": 1.0,
                            "declared_fps": media_fps, "file_path": path, "name": _text(blk, "Name") or ""})
        out.sort(key=lambda c: (c["track"], c["timeline_start"]))
        return out


def conform(cuts, real_fps_of):
    """Rewrite conformed high-frame-rate clips into real-file seconds + a baked
    speed. real_fps_of(path) -> fps or None. Mutates cuts; returns how many."""
    changed = 0
    for c in cuts:
        real, declared = real_fps_of(c["file_path"]), c.get("declared_fps")
        if not real or not declared or abs(declared / real - 1.0) <= CONFORM_TOLERANCE:
            continue
        f = declared / real
        c["source_in"] *= f
        c["source_out"] *= f
        c["speed"] *= f
        changed += 1
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 else 2)
    p = Project(sys.argv[1])
    for t in p.timelines(include_backups=True):
        cs = p.cuts(t)
        tracks = sorted({c["track"] for c in cs})
        flag = " (backup, skipped by default)" if is_backup_timeline(t.name, t.folder) else ""
        print(f"{t.name!r}: {len(cs)} clips on video tracks {tracks}, {t.fps:.3f} fps{flag}")
