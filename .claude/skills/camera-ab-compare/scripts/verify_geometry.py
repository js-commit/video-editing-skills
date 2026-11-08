#!/usr/bin/env python3
"""Re-measure Resolve's Crop/Pan/Tilt geometry and check it still holds.

build_ab_project.window_transform() depends on behaviour that is not in any
Resolve documentation and could change with a Resolve update. If side-by-side
segments ever come out shifted, spilling across the centre seam, or cropped
on the wrong edge, run this FIRST - it says whether the model is still valid
before you go hunting through the job JSON.

Method: crop a clip down to a thin sliver, then find that sliver in a grabbed
still by looking for the non-black rows/columns. That measures the applied
shift exactly, with no eyeballing and no reference image.

The model it asserts (measured on Resolve 21):

  Crop*  timeline px of the scale-to-fit image, applied BEFORE Zoom
  Zoom   scales about the FRAME centre
  Pan    +1 px/unit * (fitted_w / frame_w)   positive -> right
  Tilt   -1 px/unit * (fitted_h / frame_h)   positive -> up
  A rotation-90 phone clip SWAPS its horizontal crop edges: CropLeft trims
  the display-right edge and vice versa. Vertical edges are unaffected.

The primitive cases pin each behaviour in isolation; a final e2e case takes
its props from build_ab_project.window_transform() itself, so the probe also
certifies the shared code path and not just this hand-written model.

Usage:
  verify_geometry.py LANDSCAPE_CLIP PORTRAIT_CLIP [--keep]

Needs Resolve running. Creates and deletes a project named ab-geomcheck.
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

try:
    import cv2
    import numpy as np
except ImportError:
    sys.exit("this script needs numpy opencv-python: python3 -m pip install numpy opencv-python")

from build_ab_project import connect, window_transform

PROJECT = "ab-geomcheck"
FW, FH, FPS = 3840, 2160, 30
SEG = 1.0
TOL = 3.0        # px; still grabs are exact, so this is generous


def extent(png, axis):
    """First/last/centre of the lit band along `axis`, in timeline px.

    The cutoff is a fraction of the profile's own peak, not an absolute:
    a sliver cropped on the OTHER axis lights only a small share of each
    column (a 360 px band of a 2160 px frame peaks at 0.17), so any fixed
    threshold near 0.25 reads the whole still as black.
    """
    img = cv2.imread(png, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    prof = (img > 12).mean(axis=0 if axis == "x" else 1)
    peak = prof.max()
    if peak < 0.02:
        return None
    idx = np.nonzero(prof > 0.5 * peak)[0]
    if len(idx) == 0:
        return None
    return float(idx[0]), float(idx[-1]), float((idx[0] + idx[-1]) / 2)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("landscape")
    ap.add_argument("portrait")
    ap.add_argument("--keep", action="store_true", help="keep the still dump")
    a = ap.parse_args()

    resolve = connect()
    pm = resolve.GetProjectManager()
    # Remember what was open so the probe can hand the session back. Without
    # this the user is left staring at a 10 s timeline of test slivers and
    # wondering where their edit went.
    was_open = pm.GetCurrentProject()
    was_open = was_open.GetName() if was_open else None
    if was_open == PROJECT:
        was_open = None
    if PROJECT in (pm.GetProjectListInCurrentFolder() or []):
        cur = pm.GetCurrentProject()
        if cur and cur.GetName() == PROJECT:
            pm.CloseProject(cur)
        pm.DeleteProject(PROJECT)
    proj = pm.CreateProject(PROJECT)
    for k, v in (("timelineResolutionWidth", str(FW)),
                 ("timelineResolutionHeight", str(FH)),
                 ("timelineFrameRate", str(FPS))):
        proj.SetSetting(k, v)
    mp = proj.GetMediaPool()
    items = mp.ImportMedia([a.landscape, a.portrait])
    by = {i.GetClipProperty("File Path"): i for i in items}
    land, port = by[a.landscape], by[a.portrait]
    lres, pres = land.GetClipProperty("Resolution"), port.GetClipProperty("Resolution")
    print(f"landscape {os.path.basename(a.landscape)} res={lres}")
    print(f"portrait  {os.path.basename(a.portrait)} res={pres}")
    lw, lh = (int(x) for x in lres.split("x"))
    pw, ph = (int(x) for x in pres.split("x"))
    if lw < lh or pw > ph:
        sys.exit("first clip must be landscape, second portrait (by DISPLAY res)")
    pfit = min(FW / pw, FH / ph)
    pw0 = pw * pfit                        # fitted width of the portrait clip

    # label, clip, (cropL, cropR, cropT, cropB), zoom, pan, tilt, axis, expect
    cases = [
        ("land.cropLR", land, (1900, 1900, 0, 0), 1.0, 0, 0, "x",
         ("centre", FW / 2)),
        ("land.pan500", land, (1900, 1900, 0, 0), 1.0, 500, 0, "x",
         ("centre", FW / 2 + 500)),
        ("land.tilt500", land, (0, 0, 1060, 1060), 1.0, 0, 500, "y",
         ("centre", FH / 2 - 500)),
        # the ordering check: crop to 960x1080 in SOURCE space, then zoom 2x.
        # If crop ran after the zoom this would be nowhere near 1920 wide.
        ("land.crop2x", land, (1440, 1440, 540, 540), 2.0, -960, 0, "x",
         ("span", 1920.0)),
        ("port.cropL", port, (400, 0, 0, 0), 1.0, 0, 0, "x",
         ("last", (FW + pw0) / 2 - 400)),      # CropLeft trims display-RIGHT
        ("port.cropR", port, (0, 400, 0, 0), 1.0, 0, 0, "x",
         ("first", (FW - pw0) / 2 + 400)),     # CropRight trims display-LEFT
        ("port.cropT", port, (0, 0, 400, 0), 1.0, 0, 0, "y", ("first", 400.0)),
        ("port.cropB", port, (0, 0, 0, 400), 1.0, 0, 0, "y",
         ("last", FH - 400 - 1)),
        ("port.pan500", port, (0, 0, 900, 900), 1.0, 500, 0, "x",
         ("centre", FW / 2 + 500 * pw0 / FW)),
        ("port.tilt500", port, (0, 0, 900, 900), 1.0, 0, 500, "y",
         ("centre", FH / 2 - 500)),
    ]

    # End-to-end: one case whose props come from window_transform() ITSELF,
    # so the probe certifies the shared code path and not just a hand-copied
    # model. A horizontal band placed with mode="fit" lands its centre
    # exactly on the target centre, so the expected value is FH/2 whatever
    # the clip resolution - and it exercises crop, zoom, pan and tilt at
    # once (band at 0.2*H: zoom 0.5, tilt -270, pan -960 on a 16:9 source).
    band = [0, round(0.2 * lh), lw, round(0.1 * lh)]
    ez, ep, et, ecr = window_transform(land, FW, FH, band, FW / 4, FH / 2,
                                       FW / 2, FH, "fit")
    cases.append(("e2e.window", land,
                  (ecr["CropLeft"], ecr["CropRight"], ecr["CropTop"],
                   ecr["CropBottom"]), ez, ep, et, "y", ("centre", FH / 2)))

    tl = mp.CreateEmptyTimeline("geomcheck")
    proj.SetCurrentTimeline(tl)
    base, cursor = tl.GetStartFrame(), 0
    for label, mpi, (cl, cr, ct, cb), zoom, pan, tilt, _ax, _exp in cases:
        sfps = float(mpi.GetClipProperty("FPS"))
        it = mp.AppendToTimeline([{
            "mediaPoolItem": mpi, "trackIndex": 1, "mediaType": 1,
            "startFrame": round(3 * sfps),
            "endFrame": round(3 * sfps) + round(SEG * sfps) - 1,
            "recordFrame": base + cursor}])[0]
        for prop, val in (("CropLeft", cl), ("CropRight", cr), ("CropTop", ct),
                          ("CropBottom", cb), ("ZoomX", zoom), ("ZoomY", zoom),
                          ("Pan", pan), ("Tilt", tilt)):
            if not it.SetProperty(prop, val):
                print(f"  {label}: SetProperty({prop}) REFUSED", file=sys.stderr)
        cursor += int(SEG * FPS)
    pm.SaveProject()

    outdir = tempfile.mkdtemp(prefix="abgeom-")

    def grab_case(label, f):
        """Park the playhead and write the rendered frame straight to disk
        with ExportCurrentFrameAsStill - no Gallery involved (the old
        GrabStill/ExportStills path could silently write nothing right
        after a timeline rebuild). Verify the file actually landed so a
        transient hiccup can't read as the transform model changing."""
        h, rem = divmod(f, FPS * 3600)
        m, rem = divmod(rem, FPS * 60)
        s, fr = divmod(rem, FPS)
        stem = label.replace(".", "_")
        path = os.path.join(outdir, f"{stem}_frame.png")
        tc = f"{h:02d}:{m:02d}:{s:02d}:{fr:02d}"
        for _ in range(3):
            tl.SetCurrentTimecode(tc)
            # The export reflects what the viewer currently SHOWS, which
            # lags the park - poll the readback, then let it render, or
            # the previous case's frame gets measured.
            for _p in range(20):
                if tl.GetCurrentTimecode() == tc:
                    break
                time.sleep(0.25)
            time.sleep(1.5)
            if (proj.ExportCurrentFrameAsStill(path)
                    and os.path.exists(path) and os.path.getsize(path) > 0):
                return True
        return False

    # ExportCurrentFrameAsStill only works on the edit page (returns False
    # on deliver - measured); switch for the grabs, restore after.
    prev_page = resolve.GetCurrentPage()
    if prev_page != "edit" and not resolve.OpenPage("edit"):
        sys.exit("OpenPage(edit) refused - stills need the edit page")
    no_still = set()
    try:
        for i, (label, *_r) in enumerate(cases):
            if not grab_case(label, base + int((i + 0.5) * SEG * FPS)):
                no_still.add(label)
    finally:
        if prev_page != "edit":
            resolve.OpenPage(prev_page)

    files = os.listdir(outdir)
    fails = 0
    print(f"\n{'case':14s} {'measure':7s} {'got':>9s} {'want':>9s}  result")
    for label, _c, _cr, _z, _p, _t, axis, (kind, want) in cases:
        stem = label.replace(".", "_")
        match = [f for f in files if f.startswith(stem + "_") and f.endswith(".png")]
        if not match:
            print(f"{label:14s} {'-':7s} {'no still':>9s}  (export hiccup)")
            continue
        e = extent(os.path.join(outdir, match[0]), axis)
        if e is None:
            print(f"{label:14s} {kind:7s} {'all black':>9s}")
            fails += 1
            continue
        got = {"first": e[0], "last": e[1], "centre": e[2],
               "span": e[1] - e[0] + 1}[kind]
        ok = abs(got - want) <= TOL
        fails += not ok
        print(f"{label:14s} {kind:7s} {got:9.1f} {want:9.1f}  "
              f"{'ok' if ok else 'FAIL'}")

    if not a.keep:
        shutil.rmtree(outdir, ignore_errors=True)
        # DeleteProject silently no-ops on the project that is still open, so
        # leave it first — restoring whatever the session was on beforehand.
        if not (was_open and pm.LoadProject(was_open) is not None):
            cur = pm.GetCurrentProject()
            if cur and cur.GetName() == PROJECT:
                pm.CloseProject(cur)
        if not pm.DeleteProject(PROJECT):
            print(f"\nWARNING: could not delete {PROJECT} — remove it by hand "
                  f"in the Project Manager", file=sys.stderr)
        elif was_open:
            print(f"\nreturned Resolve to {was_open!r}")
    else:
        print(f"\nstills kept in {outdir}; project {PROJECT} left in place — "
              f"reopen your own project before editing")

    if fails:
        print(f"\n{fails} check(s) FAILED - Resolve's transform model has "
              f"changed. Re-derive it before trusting window_transform().")
        return 1
    if no_still:
        print(f"\n{len(no_still)} still(s) never exported (transient export "
              f"hiccup, not a model failure) - rerun the probe: {sorted(no_still)}")
        return 1
    print("\nall checks passed - window_transform()'s model still holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
