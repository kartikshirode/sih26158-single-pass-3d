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


def derive_intrinsics(points: np.ndarray, cams: np.ndarray, H: int, W: int):
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
        a, b = (X / Z)[ok], (Y / Z)[ok]
        u, w = jj[ok] + 0.5, ii[ok] + 0.5      # pixel centres
        fx, cx = np.linalg.lstsq(np.c_[a, np.ones(a.size)], u, rcond=None)[0]
        fy, cy = np.linalg.lstsq(np.c_[b, np.ones(b.size)], w, rcond=None)[0]
        out.append([fx, fy, cx, cy])
        resid.append(max(np.median(np.abs(fx * a + cx - u)),
                         np.median(np.abs(fy * b + cy - w))))
    return np.array(out), float(np.median(resid))


def full_frame_camera(K: np.ndarray, H: int, W: int, h0: int, w0: int):
    """
    Move the fitted K from the model's cropped grid onto the FULL keyframe.

    MVS runs on the original pixels, not the model's 392x518 grid - that is the whole
    point of the exercise - so the intrinsics have to be un-cropped and un-scaled.
    Uniform scale s = H/h0 (height is the limiting dimension), then a centred width
    crop, so only cx picks up an offset.
    """
    s = H / h0
    w_scaled = int(round(w0 * s))
    x0 = (w_scaled - W) // 2                       # crop offset, in scaled pixels
    f = float(K[:, :2].mean() / s)
    cx = float(K[:, 2].mean() + x0) / s
    cy = float(K[:, 3].mean()) / s
    return {"f": f, "cx": cx, "cy": cy, "w": w0, "h": h0,
            "scale": s, "crop_x0_full": x0 / s,
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
