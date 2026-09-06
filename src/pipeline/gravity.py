"""
Recover the vertical, and say how much to trust it.

Docs 05 section 6 reported "no reliable gravity vector", on the evidence that the
cloud's thin principal axis and the scene-centroid-to-camera direction disagree by
40-57 degrees. **That framing was wrong and is corrected here.** Those are not two
estimates of the same thing: the centroid direction is not a vertical at all for an
oblique pass, where the drone sits beside the scene rather than above it, and
`upright_frame` only ever used it to disambiguate a SIGN. The direction it ships - the
thin principal axis - turns out to be good.

What was genuinely missing was any way to CHECK it. There is one, and it is independent
of the point cloud: a gimballed drone camera holds roll near zero, so every camera's
image-right axis is horizontal. Measured on three runs, residual roll about the
recovered vertical is 0.21-0.68 deg median. That is a real constraint, not an assumption.

It is not sufficient on its own. Roll fixes gravity only up to one degree of freedom -
it says gravity is perpendicular to the camera's right axis - and a pass flown on a
near-constant heading makes every right axis point the same way, so the family is never
pinned down. The camera-X singular spectrum shows it directly: [1, 0.0086, 0.0044] on
Kolu, meaning those axes span one direction, not a plane. Taking the smallest singular
vector there returns an arbitrary member of the family, which is what produced a
spurious 40 deg disagreement in the first pass at this.

So: use the ground plane for the direction, and the roll constraint to CHECK and correct
it. On all three runs the correction is 1.7-2.5 deg, which is the mutual validation -
two independent physical facts agreeing to about two degrees.
"""
from __future__ import annotations

import numpy as np

DEGENERATE = 0.03      # camera-X spread below this: heading is near-constant


def estimate(cams: np.ndarray, points: np.ndarray, log=print) -> dict:
    """
    Return the world-space up vector plus the evidence for it.

    `cams` is (N,4,4) cam2world; `points` is the reconstruction. Never trust the
    returned vector without reading `residual_roll_deg` and `ground_correction_deg` -
    they are the two numbers that say whether the scene supported an answer.
    """
    cams = np.asarray(cams, float)
    P = np.asarray(points, float)
    cen = cams[:, :3, 3]

    # 1. the roll constraint: image-right is horizontal on a gimballed camera
    Xw = np.stack([c[:3, :3] @ np.array([1.0, 0, 0]) for c in cams])
    S = np.linalg.svd(Xw, full_matrices=False)[1]
    Vt = np.linalg.svd(Xw, full_matrices=False)[2]
    heading_spread = float(S[1] / S[0])
    x_axis = Vt[0]                       # the one well-determined right-direction

    # 2. the ground plane gives the direction
    q = P[:: max(1, len(P) // 200_000)]
    n_ground = np.linalg.svd(q - q.mean(0), full_matrices=False)[2][-1]

    # 3. project the ground normal onto the plane perpendicular to the right axis,
    #    so the result satisfies roll = 0 exactly while staying as close to the
    #    terrain normal as that allows
    up = n_ground - np.dot(n_ground, x_axis) * x_axis
    up /= np.linalg.norm(up)
    correction = float(np.degrees(np.arccos(np.clip(abs(n_ground @ up), 0, 1))))

    # 4. sign: the drone was above the ground. This is the one thing known for certain.
    if np.median(cen @ up) < np.median(P @ up):
        up = -up

    roll = np.degrees(np.arcsin(np.clip(np.abs(Xw @ up), 0, 1)))
    alt = cen @ up
    horiz = cen - np.outer(alt, up)
    track = float(np.linalg.norm(np.diff(horiz, axis=0), axis=1).sum())

    out = {
        "up": up,
        "heading_spread": heading_spread,
        "heading_degenerate": heading_spread < DEGENERATE,
        "ground_correction_deg": round(correction, 2),
        "residual_roll_deg": round(float(np.median(roll)), 2),
        "residual_roll_max_deg": round(float(roll.max()), 2),
        "camera_above_ground_m": round(float(np.median(alt) - np.median(P @ up)), 2),
        "horiz_track_m": round(track, 1),
        "altitude_spread_m": round(float(np.ptp(alt)), 2),
    }
    log(f"  gravity: correction {out['ground_correction_deg']} deg, residual roll "
        f"{out['residual_roll_deg']} deg (max {out['residual_roll_max_deg']}), "
        f"camera {out['camera_above_ground_m']} m above ground"
        + ("  [heading near-constant: roll check is weak]"
           if out["heading_degenerate"] else ""))
    if out["ground_correction_deg"] > 15.0:
        log("  WARNING gravity: ground normal and roll constraint disagree by more "
            "than 15 deg - the scene is probably sloped or not ground-dominated; "
            "treat plan views, relief and any DEM as unreliable.")
    return out


def frame(up: np.ndarray) -> np.ndarray:
    """Orthonormal basis with `up` as the second row, matching render_views."""
    a = np.asarray(up, float)
    a = a / np.linalg.norm(a)
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(a, t); e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    return np.stack([e1, a, e2])
