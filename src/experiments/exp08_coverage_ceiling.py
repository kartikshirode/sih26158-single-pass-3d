"""
EXP-08 - What can a SINGLE pass physically observe?

Model Completeness is 20% of the SIH26158 score, and R-F2 explicitly requires
"Building facades AND rooftops". But a single nadir pass looks straight down. This
experiment measures, analytically and before any reconstruction model exists, the
COMPLETENESS CEILING - the fraction of scene surface any algorithm could possibly
recover from measurement, because a surface never observed can only be inferred.

Run:  python src/experiments/exp08_coverage_ceiling.py
"""
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from simscene.scene import build_scene, SceneSpec, single_pass, Camera  # noqa: E402
from simscene.visibility import coverage                                # noqa: E402

N_QUERY = 30_000
N_OCCLUDER = 400_000
N_FRAMES = 600
STRIDE = 10           # evaluate every 10th frame -> 60 cameras
ALT = 110.0

print("=" * 86)
print("EXP-08  Completeness ceiling of a single pass  (R-O4 20%, R-F2)")
print("=" * 86)

scene = build_scene(SceneSpec(seed=7))
cam = Camera()
print(f"\nscene: {len(scene.mesh.faces)} faces, {scene.parts['n_buildings']} buildings, "
      f"{scene.spec.extent*2:.0f} x {scene.spec.extent*2:.0f} m")

rng = np.random.default_rng(0)
pts, fidx = trimesh.sample.sample_surface(scene.mesh, N_QUERY, seed=0)
pts = np.asarray(pts)
labels = scene.labels[fidx]
normals = scene.mesh.face_normals[fidx]

occ, _ = trimesh.sample.sample_surface(scene.mesh, N_OCCLUDER, seed=1)
occ = np.asarray(occ)

# Split building faces into roof vs facade by normal direction - this is the crux of R-F2
is_bld = labels == 1
vert = np.abs(normals[:, 2])
roof = is_bld & (vert > 0.7)
facade = is_bld & (vert <= 0.3)

# Facades split by orientation RELATIVE TO THE FLIGHT LINE (which runs along +X).
# This is the distinction that explains the whole result: forward tilt can only ever
# help facades that face along-track. Cross-track facades depend on field of view.
along_track = facade & (np.abs(normals[:, 0]) > 0.7)   # faces +/-X, i.e. toward/away from flight
cross_track = facade & (np.abs(normals[:, 1]) > 0.7)   # faces +/-Y, i.e. sideways

groups = {
    "terrain": labels == 0,
    "road": labels == 2,
    "vegetation": labels == 3,
    "building ROOF": roof,
    "FACADE along-trk": along_track,
    "FACADE cross-trk": cross_track,
}

print(f"cameras: {N_FRAMES // STRIDE} of {N_FRAMES} frames, altitude {ALT:.0f} m, "
      f"HFOV {cam.hfov_deg:.0f} deg\n")

configs = [
    ("nadir  (90 deg)", 90.0),
    ("oblique(60 deg)", 60.0),
    ("oblique(45 deg)", 45.0),
]

# The flight is one straight line along X, so it only ever overflies a corridor. A
# nadir swath is 2*alt*tan(hfov/2) wide; over an 800 m scene that is ~25% of the area
# no matter how good the algorithm is. Scoring against the WHOLE scene therefore
# measures our choice of scene size, not our reconstruction. The meaningful number is
# coverage WITHIN the corridor actually overflown, so we report both.
swath = 2.0 * ALT * np.tan(np.radians(cam.hfov_deg) / 2.0)
corridor = np.abs(pts[:, 1]) < swath / 2.0
print(f"nadir ground swath = {swath:.0f} m over a {scene.spec.extent*2:.0f} m scene "
      f"-> a single pass can reach at most {corridor.mean():.1%} of the total area\n")
print("Coverage is reported WITHIN THE OVERFLOWN CORRIDOR (the honest denominator).\n")

results = {}
hdr = f"{'flight':<17}" + "".join(f"{g:>17}" for g in groups) + f"{'CORRIDOR':>10}{'  whole scene':>14}"
print(hdr)
print("-" * len(hdr))

for name, pitch in configs:
    pos, R = single_pass(scene, n_frames=N_FRAMES, alt=ALT, pitch_deg=pitch)
    cov = coverage(pts, normals, pos, R, cam.K, cam.width, cam.height, occ,
                   stride=STRIDE, min_views=2)
    rec = cov["reconstructable"]
    row = f"{name:<17}"
    per = {}
    for g, m in groups.items():
        mm = m & corridor
        val = float(rec[mm].mean()) if mm.any() else float("nan")
        per[g] = val
        row += f"{val:>16.1%} "
    per["CORRIDOR"] = float(rec[corridor].mean())
    per["WHOLE"] = float(rec.mean())
    results[name] = per
    print(row + f"{per['CORRIDOR']:>9.1%}{per['WHOLE']:>13.1%}")

# A two-pass comparison, purely to quantify what the "single pass" constraint costs.
pos1, R1 = single_pass(scene, n_frames=N_FRAMES // 2, alt=ALT, pitch_deg=60.0,
                       heading_deg=0.0)
pos2, R2 = single_pass(scene, n_frames=N_FRAMES // 2, alt=ALT, pitch_deg=60.0,
                       heading_deg=90.0)
cov2 = coverage(pts, normals, np.vstack([pos1, pos2]), np.vstack([R1, R2]),
                cam.K, cam.width, cam.height, occ, stride=STRIDE // 2, min_views=2)
rec2 = cov2["reconstructable"]
row = f"{'[2 passes, 60deg]':<17}"
for g, m in groups.items():
    mm = m & corridor
    row += f"{float(rec2[mm].mean()):>16.1%} "
print(row + f"{float(rec2[corridor].mean()):>9.1%}{rec2.mean():>13.1%}")

print(f"""
{'-' * 86}
FINDINGS
{'-' * 86}
1. TERRAIN AND ROOFTOPS ARE EASY; FACADES ARE WHERE COMPLETENESS IS LOST (R-F2).
   Within the overflown corridor, terrain reaches ~99-100% even at nadir. Facades are
   the binding constraint, exactly as the physics predicts.

2. ALONG-TRACK vs CROSS-TRACK IS THE REAL DISTINCTION - and it explains everything.
   nadir   : along-track {results['nadir  (90 deg)']['FACADE along-trk']:.1%}, cross-track {results['nadir  (90 deg)']['FACADE cross-trk']:.1%}
   60 deg  : along-track {results['oblique(60 deg)']['FACADE along-trk']:.1%}, cross-track {results['oblique(60 deg)']['FACADE cross-trk']:.1%}
   45 deg  : along-track {results['oblique(45 deg)']['FACADE along-trk']:.1%}, cross-track {results['oblique(45 deg)']['FACADE cross-trk']:.1%}

   Forward gimbal tilt can only help facades that FACE ALONG THE FLIGHT LINE. Once the
   tilt is enough to see them at all, tilting further adds nothing - which is why 60
   and 45 deg score almost identically. Cross-track facades (the sides of buildings)
   are never helped by forward tilt; they are visible only through the edges of a wide
   field of view, where a 84 deg HFOV gives up to ~42 deg of oblique look angle.

   PRACTICAL CONSEQUENCE: if we can influence capture, a SIDEWAYS-tilted gimbal or a
   wider lens buys more completeness than any amount of forward tilt. This is a
   capture-side variable, not an algorithm one, and it is worth more than model choice.

3. ONE PASS SEES ONE SIDE. THIS IS PHYSICS, NOT A SOFTWARE DEFECT.
   Two crossed passes reach {float(rec2[facade & corridor].mean()):.1%} facade coverage against
   {results['oblique(60 deg)']['FACADE along-trk']:.1%}/{results['oblique(60 deg)']['FACADE cross-trk']:.1%} for one. The gap is precisely the
   territory R-C7 (occluded-surface reconstruction) must cover by INFERENCE - and it is
   why inferred geometry must be LABELLED rather than silently blended with measured
   geometry. A judge who measures a wall we invented should be able to see that we
   invented it.

4. CONSEQUENCE FOR THE DESIGN.
   Report completeness against what is OBSERVABLE, and separately against the whole
   scene. Claiming high completeness while silently inventing facades would be
   dishonest; reporting low completeness without explaining the geometry would be
   self-defeating. The system therefore tags every face observed / inferred, and the
   viewer can show or hide inferred geometry.
{'=' * 86}""")
