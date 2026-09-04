"""
Reconstruction accuracy / completeness metrics for SIH26158.

Implements the Tanks-and-Temples style precision / recall / F-score at a distance
threshold, plus distance statistics, and reports them TWICE:

  * ABSOLUTE  - no alignment at all. This is the georeferencing-truthful number and
                the one that R-O3 ("spatial accuracy <= 1 m") actually demands.
  * ALIGNED   - after a best-fit rigid / similarity alignment. This is pure shape
                fidelity, with georeferencing error removed.

Reporting only the aligned number is the standard way to appear to pass this
requirement while being tens of metres out of place. We always report both, and we
report the alignment translation magnitude, which IS the georeferencing offset.

CPU-only by design: numpy + scipy only. No GPU, no Open3D (which has no Python 3.13
wheels), no CloudCompare dependency.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, asdict, field
from scipy.spatial import cKDTree


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------

@dataclass
class DistanceStats:
    """One-directional nearest-neighbour distance statistics, in metres."""
    mean: float
    median: float
    rmse: float
    p90: float
    p95: float
    max: float
    n: int

    @staticmethod
    def from_distances(d: np.ndarray) -> "DistanceStats":
        d = np.asarray(d, dtype=np.float64).ravel()
        if d.size == 0:
            z = float("nan")
            return DistanceStats(z, z, z, z, z, z, 0)
        return DistanceStats(
            mean=float(np.mean(d)),
            median=float(np.median(d)),
            rmse=float(np.sqrt(np.mean(d ** 2))),
            p90=float(np.percentile(d, 90)),
            p95=float(np.percentile(d, 95)),
            max=float(np.max(d)),
            n=int(d.size),
        )


@dataclass
class ScoreAtThreshold:
    """Precision / recall / F-score at one distance threshold tau (metres)."""
    tau: float
    precision: float   # fraction of RECONSTRUCTION points within tau of GT  -> accuracy
    recall: float      # fraction of GT points within tau of RECONSTRUCTION  -> completeness
    fscore: float


@dataclass
class EvalResult:
    """Full evaluation, both absolute and aligned."""
    mode: str                       # "absolute" or "aligned"
    accuracy: DistanceStats         # recon -> GT   (how wrong is what we built)
    completeness: DistanceStats     # GT -> recon   (how much did we miss)
    scores: list[ScoreAtThreshold] = field(default_factory=list)
    # Only populated for mode == "aligned":
    alignment_translation_m: float | None = None
    alignment_scale: float | None = None
    alignment_rotation_deg: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scores"] = [asdict(s) for s in self.scores]
        return d


# --------------------------------------------------------------------------------------
# Core distance computation
# --------------------------------------------------------------------------------------

def nn_distances(query: np.ndarray, reference: np.ndarray,
                 workers: int = -1) -> np.ndarray:
    """Nearest-neighbour distance from every point in `query` to `reference`."""
    if query.size == 0 or reference.size == 0:
        return np.empty((0,), dtype=np.float64)
    tree = cKDTree(np.asarray(reference, dtype=np.float64))
    d, _ = tree.query(np.asarray(query, dtype=np.float64), k=1, workers=workers)
    return np.asarray(d, dtype=np.float64)


def prf_at_tau(d_recon_to_gt: np.ndarray, d_gt_to_recon: np.ndarray,
               tau: float) -> ScoreAtThreshold:
    """
    Tanks-and-Temples style scoring at threshold tau.

    precision = |{r in R : dist(r, G) < tau}| / |R|     (accuracy)
    recall    = |{g in G : dist(g, R) < tau}| / |G|     (completeness)
    F         = 2PR / (P + R)
    """
    p = float(np.mean(d_recon_to_gt < tau)) if d_recon_to_gt.size else 0.0
    r = float(np.mean(d_gt_to_recon < tau)) if d_gt_to_recon.size else 0.0
    f = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
    return ScoreAtThreshold(tau=float(tau), precision=p, recall=r, fscore=f)


# --------------------------------------------------------------------------------------
# Alignment (Umeyama / Horn similarity transform, then optional ICP refinement)
# --------------------------------------------------------------------------------------

def umeyama(src: np.ndarray, dst: np.ndarray, with_scale: bool = True):
    """
    Least-squares similarity transform mapping src -> dst.
    Umeyama (1991). Returns (R, t, s) with dst ~= s * R @ src + t.

    Requires CORRESPONDING points (src[i] matches dst[i]).
    """
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    assert src.shape == dst.shape and src.shape[1] == 3

    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    sc, dc = src - mu_s, dst - mu_d

    cov = (dc.T @ sc) / src.shape[0]
    U, D, Vt = np.linalg.svd(cov)

    # Reflection guard - without this a mirrored solution can win on noisy data.
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1.0

    R = U @ S @ Vt
    if with_scale:
        var_s = (sc ** 2).sum() / src.shape[0]
        s = float(np.trace(np.diag(D) @ S) / var_s) if var_s > 0 else 1.0
    else:
        s = 1.0
    t = mu_d - s * (R @ mu_s)
    return R, t, s


def icp(src: np.ndarray, dst: np.ndarray, *, with_scale: bool = False,
        max_iter: int = 50, tol: float = 1e-6, sample: int = 200_000,
        trim: float = 0.8, rng: np.random.Generator | None = None):
    """
    Trimmed ICP aligning src onto dst.

    `trim` keeps only the closest fraction of correspondences each iteration, which
    stops non-overlapping regions (very common when a reconstruction covers less
    ground than the ground truth) from dragging the fit.

    Returns (R, t, s, rmse).
    """
    rng = rng or np.random.default_rng(0)
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)

    work = src
    if src.shape[0] > sample:
        work = src[rng.choice(src.shape[0], sample, replace=False)]

    tree = cKDTree(dst)
    R_tot, t_tot, s_tot = np.eye(3), np.zeros(3), 1.0
    cur = work.copy()
    prev = np.inf
    rmse = np.inf

    for _ in range(max_iter):
        d, idx = tree.query(cur, k=1, workers=-1)
        if trim < 1.0:
            keep = np.argsort(d)[: max(3, int(len(d) * trim))]
        else:
            keep = np.arange(len(d))

        R, t, s = umeyama(cur[keep], dst[idx[keep]], with_scale=with_scale)
        cur = (s * (R @ cur.T).T) + t

        # accumulate
        R_tot = R @ R_tot
        t_tot = s * (R @ t_tot) + t
        s_tot = s * s_tot

        rmse = float(np.sqrt(np.mean(d[keep] ** 2)))
        if abs(prev - rmse) < tol:
            break
        prev = rmse

    return R_tot, t_tot, s_tot, rmse


def apply_transform(pts: np.ndarray, R: np.ndarray, t: np.ndarray, s: float) -> np.ndarray:
    return (s * (R @ np.asarray(pts, dtype=np.float64).T).T) + t


def rotation_angle_deg(R: np.ndarray) -> float:
    """Geodesic angle of a rotation matrix, in degrees."""
    c = (np.trace(R) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


# --------------------------------------------------------------------------------------
# Top-level evaluation
# --------------------------------------------------------------------------------------

DEFAULT_TAUS = (0.25, 0.5, 1.0, 2.0)   # 1.0 m is the R-O3 requirement threshold


def evaluate(recon_pts: np.ndarray, gt_pts: np.ndarray, *,
             taus=DEFAULT_TAUS, align: bool = True,
             align_with_scale: bool = False) -> dict[str, EvalResult]:
    """
    Evaluate a reconstruction against ground truth.

    Both inputs are (N, 3) arrays in the SAME coordinate system and the same units
    (metres). For georeferenced output that means e.g. UTM easting/northing/height.

    Returns {"absolute": EvalResult, "aligned": EvalResult}. The absolute result is
    the one that answers R-O3.
    """
    recon_pts = np.asarray(recon_pts, dtype=np.float64).reshape(-1, 3)
    gt_pts = np.asarray(gt_pts, dtype=np.float64).reshape(-1, 3)

    out: dict[str, EvalResult] = {}

    # ---- ABSOLUTE: no alignment. This is the honest georeferenced number. ----
    d_rg = nn_distances(recon_pts, gt_pts)
    d_gr = nn_distances(gt_pts, recon_pts)
    out["absolute"] = EvalResult(
        mode="absolute",
        accuracy=DistanceStats.from_distances(d_rg),
        completeness=DistanceStats.from_distances(d_gr),
        scores=[prf_at_tau(d_rg, d_gr, t) for t in taus],
    )

    # ---- ALIGNED: shape fidelity with georeferencing error removed. ----
    if align:
        R, t, s, _ = icp(recon_pts, gt_pts, with_scale=align_with_scale)
        moved = apply_transform(recon_pts, R, t, s)
        d_rg_a = nn_distances(moved, gt_pts)
        d_gr_a = nn_distances(gt_pts, moved)
        out["aligned"] = EvalResult(
            mode="aligned",
            accuracy=DistanceStats.from_distances(d_rg_a),
            completeness=DistanceStats.from_distances(d_gr_a),
            scores=[prf_at_tau(d_rg_a, d_gr_a, tt) for tt in taus],
            alignment_translation_m=float(np.linalg.norm(t)),
            alignment_scale=float(s),
            alignment_rotation_deg=rotation_angle_deg(R),
        )

    return out


def summarise(results: dict[str, EvalResult], *, tau: float = 1.0) -> str:
    """Human-readable report keyed to the R-O3 threshold."""
    lines = []
    lines.append("=" * 74)
    lines.append("RECONSTRUCTION EVALUATION  (SIH26158 / R-O3, R-O4)")
    lines.append("=" * 74)

    for mode in ("absolute", "aligned"):
        r = results.get(mode)
        if r is None:
            continue
        label = ("ABSOLUTE  (georeferenced - this is what R-O3 requires)"
                 if mode == "absolute" else
                 "ALIGNED   (shape only - georeferencing error removed)")
        lines.append("")
        lines.append(f"-- {label}")
        if mode == "aligned":
            lines.append(f"   alignment moved the model by "
                         f"{r.alignment_translation_m:.3f} m  "
                         f"(rot {r.alignment_rotation_deg:.3f} deg, "
                         f"scale {r.alignment_scale:.6f})")
            lines.append("   ^ that translation IS the georeferencing offset")
        a, c = r.accuracy, r.completeness
        lines.append(f"   accuracy      (recon->GT): mean {a.mean:7.3f}  "
                     f"median {a.median:7.3f}  RMSE {a.rmse:7.3f}  p95 {a.p95:7.3f} m")
        lines.append(f"   completeness  (GT->recon): mean {c.mean:7.3f}  "
                     f"median {c.median:7.3f}  RMSE {c.rmse:7.3f}  p95 {c.p95:7.3f} m")
        for s in r.scores:
            marker = "  <-- R-O3 threshold" if abs(s.tau - tau) < 1e-9 else ""
            lines.append(f"   tau={s.tau:5.2f} m : precision {s.precision:6.3f}   "
                         f"recall {s.recall:6.3f}   F {s.fscore:6.3f}{marker}")

    # Verdict against the requirement
    ab = results.get("absolute")
    if ab is not None:
        lines.append("")
        lines.append("-" * 74)
        passed = ab.accuracy.rmse <= tau
        lines.append(f"R-O3 (spatial accuracy <= {tau:g} m, absolute RMSE): "
                     f"{'PASS' if passed else 'FAIL'}  "
                     f"[measured {ab.accuracy.rmse:.3f} m]")
        lines.append("-" * 74)
    return "\n".join(lines)
