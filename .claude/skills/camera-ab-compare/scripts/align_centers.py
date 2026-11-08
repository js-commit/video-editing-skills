#!/usr/bin/env python3
"""Aim both halves of a pair at the SAME physical point in the scene.

Detecting the subject separately on each side is not accurate enough. The
two cameras are never in identical positions, so two independent detections
disagree by tens of pixels - and at a 2x punch-in that disagreement is
doubled on screen, which is enough to put the two halves on different parts
of the subject. (Seen for real on a studio shoot: the top-down
punch-ins showed different corners of the flat lay until this was added.)

Instead: pick the anchor in the LEFT frame, then map it into the RIGHT frame
with a similarity transform estimated from ORB matches + RANSAC.

The reported right/left scale is also the cheapest sanity check that a pair
is really a pair: on genuine matched takes it lands within a few percent of
1.0. A scale far from 1.0, or an inlier count in the low tens, means the two
clips are not showing the same thing - re-pair them before going further.

Do NOT use the scale to equalise the two sides. Both must stay at the same
native magnification or the comparison stops showing each camera's real
detail and starts showing resampling.

Usage:
  align_centers.py LEFT_FRAME RIGHT_FRAME --anchor X Y
  align_centers.py --pairs pairs.json --centers centers.json --out aligned.json

pairs.json:   {"key": {"left_frame": "...png", "right_frame": "...png"}, ...}
centers.json: {"key": {"left": [x, y]}, ...}          # right is computed
"""
import argparse
import json
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    sys.exit("this script needs numpy opencv-python: python3 -m pip install numpy opencv-python")

MIN_INLIERS = 40      # below this the fit is not trustworthy
SCALE_TOL = 0.15      # |scale-1| above this means these are not a pair
NFEATURES = 20000     # MIN_INLIERS is calibrated against this many


def similarity(img_l, img_r):
    """Estimate the left -> right similarity transform (2x3) and inlier count."""
    orb = cv2.ORB_create(nfeatures=NFEATURES)
    kl, dl = orb.detectAndCompute(cv2.cvtColor(img_l, cv2.COLOR_BGR2GRAY), None)
    kr, dr = orb.detectAndCompute(cv2.cvtColor(img_r, cv2.COLOR_BGR2GRAY), None)
    if dl is None or dr is None:
        return None, 0
    raw = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(dl, dr, k=2)
    good = [m for m, n in (p for p in raw if len(p) == 2)
            if m.distance < 0.75 * n.distance]
    if len(good) < 12:
        return None, len(good)
    src = np.float32([kl[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kr[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M, inl = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=6.0,
        maxIters=8000, confidence=0.995)
    return M, int(inl.sum()) if inl is not None else 0


def map_point(left_png, right_png, anchor):
    il, ir = cv2.imread(left_png), cv2.imread(right_png)
    if il is None or ir is None:
        sys.exit(f"cannot read {left_png} / {right_png}")
    M, n = similarity(il, ir)
    if M is None:
        return None, n, float("nan")
    v = np.array([anchor[0], anchor[1], 1.0])
    h, w = ir.shape[:2]
    mapped = [min(max(float(M[0] @ v), 0), w - 1),
              min(max(float(M[1] @ v), 0), h - 1)]
    return mapped, n, float(np.hypot(M[0, 0], M[0, 1]))


def warn(key, n, scale):
    if n < MIN_INLIERS:
        print(f"  WARNING {key}: only {n} inliers - fit not trustworthy, "
              f"check these two frames really show the same scene",
              file=sys.stderr)
    if scale == scale and abs(scale - 1.0) > SCALE_TOL:
        print(f"  WARNING {key}: right/left scale {scale:.3f} is far from 1.0 "
              f"- are these actually a matched pair?", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames", nargs="*", help="LEFT_FRAME RIGHT_FRAME")
    ap.add_argument("--anchor", nargs=2, type=float)
    ap.add_argument("--pairs")
    ap.add_argument("--centers")
    ap.add_argument("--out")
    a = ap.parse_args()

    if a.pairs:
        pairs = json.load(open(a.pairs))
        centers = json.load(open(a.centers))
        out = {}
        for key, p in pairs.items():
            anchor = centers[key]["left"]
            mapped, n, scale = map_point(p["left_frame"], p["right_frame"], anchor)
            if mapped is None:
                print(f"{key}: NO TRANSFORM ({n} matches)", file=sys.stderr)
                mapped = centers[key].get("right", anchor)
            out[key] = {"left": [round(anchor[0]), round(anchor[1])],
                        "right": [round(mapped[0]), round(mapped[1])]}
            print(f"{key:10s} L={[round(x) for x in anchor]} -> "
                  f"R={[round(x) for x in mapped]}  "
                  f"{n} inliers, scale {scale:.3f}")
            warn(key, n, scale)
        if a.out:
            json.dump(out, open(a.out, "w"), indent=2)
            print(f"\n-> {a.out}")
        return 0

    if len(a.frames) != 2 or not a.anchor:
        ap.error("give LEFT_FRAME RIGHT_FRAME --anchor X Y, or --pairs/--centers")
    mapped, n, scale = map_point(a.frames[0], a.frames[1], a.anchor)
    print(f"anchor {a.anchor} -> {mapped}   {n} inliers, scale {scale:.3f}")
    warn("pair", n, scale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
