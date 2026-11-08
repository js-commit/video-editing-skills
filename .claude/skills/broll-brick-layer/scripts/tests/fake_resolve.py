"""Small stand-ins for the Resolve objects the scripts touch, so the timeline
logic can be tested without DaVinci Resolve."""
from __future__ import annotations

import os
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)


class MPI:
    def __init__(self, uid, ctype="Video", fps="24", path=None, frames=0):
        self._p = {"Type": ctype, "FPS": fps, "File Path": path or f"/media/{uid}.mov", "Frames": str(frames)}
        self.uid = uid

    def GetUniqueId(self):
        return self.uid

    def GetClipProperty(self, k):
        return self._p.get(k)


class Item:
    def __init__(self, name, start, dur, mpi, src_in=0, enabled=True, color="", props=None, comps=None):
        self.name, self._s, self._d, self._mpi, self._li = name, start, dur, mpi, src_in
        self._en, self._col = enabled, color
        self._props = dict(props or {})
        self._comps = list(comps or [])
        self.set_props, self.imported = {}, []

    def GetName(self): return self.name
    def GetStart(self): return self._s
    def GetEnd(self): return self._s + self._d
    def GetMediaPoolItem(self): return self._mpi
    def GetLeftOffset(self): return self._li
    def GetClipEnabled(self): return self._en
    def GetClipColor(self): return self._col
    def GetProperty(self, p): return self._props.get(p)
    def GetFusionCompNameList(self): return list(self._comps)

    def ExportFusionComp(self, path):
        with open(path, "w") as f:
            f.write("comp")
        return True

    def SetProperty(self, p, v):
        self.set_props[p] = v
        return True

    def SetClipEnabled(self, v):
        self._en = v
        return True

    def SetClipColor(self, c):
        self._col = c
        return True

    def ImportFusionComp(self, p):
        self.imported.append(p)
        return True

    def GetFusionCompCount(self): return len(self.imported)


class Timeline:
    def __init__(self, tracks, t0=0, names=None, markers=None, fps="24"):
        self.tracks = {k: list(v) for k, v in tracks.items()}
        self.t0, self.fps = t0, fps
        self.names = names or {}
        self.markers = dict(markers or {})
        self.added_markers, self.deleted_markers, self.deleted_clips = [], [], []
        self.ops = []
        self.fail_delete = False

    def GetStartFrame(self): return self.t0
    def GetSetting(self, k): return self.fps
    def GetName(self): return "test timeline"
    def GetTrackCount(self, kind): return max([i for (k, i) in self.tracks if k == kind] or [0])
    def GetTrackName(self, kind, idx): return self.names.get((kind, idx), f"{kind[0].upper()}{idx}")
    def GetItemListInTrack(self, kind, idx): return list(self.tracks.get((kind, idx), []))
    def GetMarkers(self): return dict(self.markers)

    def DeleteMarkerAtFrame(self, f):
        self.ops.append("del_marker")
        self.deleted_markers.append(f)
        self.markers.pop(f, None)
        return True

    def AddMarker(self, f, color, name, note, dur, custom=""):
        self.added_markers.append((f, color, name, note, dur, custom))
        return True

    def DeleteClips(self, items, ripple=False):
        self.ops.append("del_clips")
        if self.fail_delete:
            return False
        for it in items:
            for lst in self.tracks.values():
                if it in lst:
                    lst.remove(it)
        self.deleted_clips += list(items)
        return True

    def place(self, kind, idx, it):
        self.tracks.setdefault((kind, idx), []).append(it)


class MediaPool:
    """Records AppendToTimeline calls and places items like Resolve: no
    mediaType = video on V<n> AND audio on A<n>; clip frames are scaled to
    timeline frames (floored); a still is clipped by the next item."""

    def __init__(self, tl, tl_fps=24.0):
        self.tl, self.tl_fps, self.calls = tl, tl_fps, []

    def AppendToTimeline(self, infos):
        out = []
        for info in infos:
            self.calls.append(dict(info, mediaPoolItem=info["mediaPoolItem"].uid))
            mt, trk = info.get("mediaType"), info["trackIndex"]
            mpi, sf, ef, rec = info["mediaPoolItem"], info["startFrame"], info["endFrame"], info["recordFrame"]
            dur, li = ef - sf, sf
            cf = float(mpi.GetClipProperty("FPS") or 0)
            if cf and abs(cf - self.tl_fps) > 0.01:
                dur = int(ef * self.tl_fps / cf) - int(sf * self.tl_fps / cf)
                li = int(sf * self.tl_fps / cf)
            if mpi.GetClipProperty("Type") == "Still":
                nxt = min([x.GetStart() for x in self.tl.GetItemListInTrack("video", trk) if x.GetStart() > rec]
                          + [rec + 120])
                dur = min(120, nxt - rec)
            v = Item(mpi.uid, rec, dur, mpi, src_in=li)
            if mt == 2:
                self.tl.place("audio", trk, v)
            else:
                self.tl.place("video", trk, v)
                if mt is None:
                    self.tl.place("audio", trk, Item(mpi.uid + "-a", rec, dur, mpi, src_in=li))
            out.append(v)
        return out


class Project:
    def __init__(self, tl, mp, name="test project"):
        self._tl, self._mp, self._name = tl, mp, name

    def GetName(self): return self._name
    def SetCurrentTimeline(self, tl): return True
    def GetMediaPool(self): return self._mp


class PM:
    def __init__(self):
        self.saved = 0

    def SaveProject(self):
        self.saved += 1
        return True


def patch(tl, mp):
    """Point the scripts' Resolve entry points at the fakes."""
    import _brick as B
    import backup
    pm, proj = PM(), Project(tl, mp)
    B.open_project = lambda name=None: (pm, proj)
    B.timeline_by_name = lambda p, n: tl
    B.delete_clips = lambda t, items: (not items) or t.DeleteClips(items, False)
    backup.export_drp = lambda pm_, proj_, note="": "/dev/null"
    return pm, proj
