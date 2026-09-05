"""
S2 -> S3 bridge: hand MapAnything's poses to a classical MVS stage.

The feed-forward model predicts geometry per DINOv2 patch (14 px) and interpolates
below it, so its point maps carry no detail finer than one patch - measured, see
docs/05-quality-analysis.md. Its POSES, though, are exactly what classical MVS is
bad at getting: a globally consistent pose graph and metric scale out of a short
single-pass video with no GNSS and no matching failures.

So the model becomes the initialiser and MVS becomes the geometry stage. This module
is the join: it turns `cameras.npy` + `points.npy` into a COLMAP text model that
`point_triangulator` and then OpenMVS can consume.

Two things have to be recovered on the way, because the container did not save them
for the runs we already paid for:

  intrinsics   fitted from the point map itself (see derive_intrinsics). Verified by
               reprojection residual, which lands at ~0.2 px median.
  the crop     MapAnything does NOT squash the frame to its grid. It scales uniformly
               and centre-crops. Established two ways: the fitted fx and fy agree to
               0.08% (a non-uniform squash would put them 14% apart on this footage),
               and image edges correlate with depth edges at r=0.133 under scale+crop
               versus r=0.090 under a squash, on every view tested.
"""
from __future__ import annotations

import os
import sqlite3

import numpy as np


def _fit_axis(a: np.ndarray, u: np.ndarray, iters=3, keep=3.0):
    """
    Robust 1-D fit of u = f*a + c.

    Plain least squares is not usable here. The point map contains sky and other
    regions the model declines to commit to; those sit at degenerate depths and a
    single outlier decade in X/Z drags f by hundreds of pixels. Measured on the Kolu
    clip: an unmasked lstsq returned fy = 258 +/- 102 against a true ~394, with an
    18.9 px residual, while the same data fitted robustly lands sub-pixel.
    """
    m = np.ones(a.size, bool)
    f = c = 0.0
    for _ in range(iters):
        f, c = np.linalg.lstsq(np.c_[a[m], np.ones(m.sum())], u[m], rcond=None)[0]
        r = np.abs(f * a + c - u)
        mad = np.median(r[m])
        m = r <= max(keep * mad, 0.5)
        if m.sum() < 100:
            break
    return float(f), float(c), float(np.median(np.abs(f * a[m] + c - u[m])))


def derive_intrinsics(points: np.ndarray, cams: np.ndarray, H: int, W: int,
                      mask: np.ndarray | None = None):
    """
    Fit a pinhole K per view from the point map and the pose.

    The model emits `intrinsics` directly, but the container discarded it on the runs
    already computed, and re-running inference costs ~12 min per clip. The point map
    is a dense set of (pixel -> 3D) correspondences with a known pose, so K falls out
    of a linear least squares - and unlike a guessed focal prior, the fit reports its
    own error.

    Returns (N,4) of fx, fy, cx, cy in GRID pixels, plus the median reprojection
    residual so the caller can refuse a bad fit.
    """
    n = H * W
    jj, ii = np.meshgrid(np.arange(W), np.arange(H))
    out, resid = [], []
    for v in range(len(cams)):
        g = points[v * n:(v + 1) * n].reshape(H, W, 3).astype(np.float64)
        R, t = cams[v][:3, :3], cams[v][:3, 3]
        # cam2world -> camera frame. (g - t) @ R is R^T (g - t) in column convention.
        pc = (g - t) @ R
        X, Y, Z = pc[..., 0], pc[..., 1], pc[..., 2]
        ok = np.isfinite(Z) & (Z > 1e-6)
        if mask is not None:
            # Sky and the model's own "declines to commit" regions. Without this the
            # fit is dominated by degenerate depths - see _fit_axis.
            ok &= mask[v * n:(v + 1) * n].reshape(H, W)
        if ok.sum() < 1000:
            continue
        a, b = (X / Z)[ok], (Y / Z)[ok]
        u, w = jj[ok] + 0.5, ii[ok] + 0.5      # pixel centres
        fx, cx, ru = _fit_axis(a, u)
        fy, cy, rv = _fit_axis(b, w)
        out.append([fx, fy, cx, cy])
        resid.append(max(ru, rv))
    if not out:
        raise SystemExit("no view had enough valid points to fit intrinsics")
    return np.array(out), float(np.median(resid))


def full_frame_camera(K: np.ndarray, H: int, W: int, h0: int, w0: int, log=print):
    """
    Move the fitted K from the model's cropped grid onto the FULL keyframe.

    MVS runs on the original pixels, not the model's grid - that is the whole point of
    the exercise - so the intrinsics have to be un-cropped and un-scaled.

    Cover-crop semantics: scale uniformly by whichever factor makes the frame cover
    the grid in BOTH axes, then centre-crop the surplus. Which axis is limiting
    depends on the footage - it was the height for 9:16 portrait (518/1250 vs
    392/1080) and, only just, the height again for 16:9 landscape (294/1080 = 0.2722
    vs 518/1920 = 0.2698). Assuming one of them is what this used to do, and it
    happened to be right twice; the general form costs nothing and does not depend on
    that luck holding.
    """
    s = max(H / h0, W / w0)
    x0 = (w0 * s - W) / 2.0                        # crop offsets, in scaled pixels
    y0 = (h0 * s - H) / 2.0
    # MEDIAN across views, never the mean. All 45 Kolu views share one physical
    # camera, but a handful contain enough sky that rays near the horizon reach
    # |Y/Z| ~ 2.8 (about 55 deg, well outside the real 41 deg vertical FOV) and drag
    # their own fit down - one view collapsed to fy = 39.8. Those three views moved
    # the mean fy to 378 +/- 71 while the median stayed at 394.84, which agrees with
    # the median fx of 394.91 to 0.02% - exactly the square pixels a real camera has.
    f = float(np.median(K[:, :2]) / s)
    cx = float(np.median(K[:, 2]) + x0) / s
    cy = float(np.median(K[:, 3]) + y0) / s
    # The principal point of a real camera sits near the frame centre. If the crop
    # geometry above is wrong, it lands far off - which is worth catching here, in a
    # second, rather than as a wrecked surface 15 minutes into densification.
    off = max(abs(cx - w0 / 2) / w0, abs(cy - h0 / 2) / h0)
    log(f"  principal point {cx:.1f},{cy:.1f} vs frame centre {w0/2:.1f},{h0/2:.1f} "
        f"-> {off:.1%} of frame size off centre")
    if off > 0.08:
        raise SystemExit(
            f"principal point is {off:.1%} off centre - the assumed resize/crop is "
            f"probably wrong for this aspect ratio; refusing to build on it")
    return {"f": f, "cx": cx, "cy": cy, "w": w0, "h": h0,
            "scale": s, "crop_x0_full": x0 / s, "crop_y0_full": y0 / s,
            "crop_span_full": [x0 / s, (x0 + W) / s]}


def qvec_from_R(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> COLMAP quaternion order (w, x, y, z)."""
    from scipy.spatial.transform import Rotation
    x, y, z, w = Rotation.from_matrix(R).as_quat()
    return np.array([w, x, y, z])


def db_image_ids(db_path: str) -> dict:
    """
    Read COLMAP's own image ids and camera ids out of the database.

    They must agree with what images.txt says, and COLMAP assigns them itself during
    feature extraction. Writing our own ids and hoping they line up is the classic way
    to get a silently empty triangulation, so read them back instead of assuming.
    """
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT image_id, name, camera_id FROM images").fetchall()
    con.close()
    return {name: (int(iid), int(cid)) for iid, name, cid in rows}


def write_model(outdir: str, cams: np.ndarray, names: list, cam: dict,
                db_path: str, log=print):
    """
    Write cameras.txt / images.txt / points3D.txt for `colmap point_triangulator`.

    Poses are world-to-camera; MapAnything hands back cam2world, so both R and t
    invert. The camera model is SIMPLE_RADIAL rather than PINHOLE so that bundle
    adjustment has a distortion term to absorb the ~0.2 px by which the model's rays
    depart from an exact pinhole.
    """
    os.makedirs(outdir, exist_ok=True)
    ids = db_image_ids(db_path)
    missing = [n for n in names if n not in ids]
    if missing:
        raise SystemExit(f"not in COLMAP database: {missing[:5]} ({len(missing)} total)")
    cam_ids = {c for _, c in ids.values()}
    if len(cam_ids) != 1:
        raise SystemExit(f"expected one shared camera, database has {len(cam_ids)}")
    cid = cam_ids.pop()

    with open(f"{outdir}/cameras.txt", "w") as f:
        f.write("# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        f.write(f"{cid} SIMPLE_RADIAL {cam['w']} {cam['h']} "
                f"{cam['f']:.6f} {cam['cx']:.6f} {cam['cy']:.6f} 0.0\n")

    with open(f"{outdir}/images.txt", "w") as f:
        f.write("# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        for i, nm in enumerate(names):
            R_c2w, t_c2w = cams[i][:3, :3], cams[i][:3, 3]
            R = R_c2w.T
            t = -R @ t_c2w
            q = qvec_from_R(R)
            iid, _ = ids[nm]
            f.write(f"{iid} {q[0]:.9f} {q[1]:.9f} {q[2]:.9f} {q[3]:.9f} "
                    f"{t[0]:.9f} {t[1]:.9f} {t[2]:.9f} {cid} {nm}\n\n")  # blank POINTS2D

    open(f"{outdir}/points3D.txt", "w").write(
        "# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
    log(f"  wrote COLMAP model: {len(names)} images, camera {cid}, "
        f"f={cam['f']:.1f} cx={cam['cx']:.1f} cy={cam['cy']:.1f} "
        f"({cam['w']}x{cam['h']})")
