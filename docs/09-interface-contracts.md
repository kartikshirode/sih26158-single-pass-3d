# Interface contracts

Version 1.0 — 2026-09-16. The concrete formats, frames and units at every hop, from video in
to files out. `architecture-prompt.md` §3 item 4 asks for exactly this, and until now it lived
only in code.

A contract here is binding in both directions. A stage may not emit less than its contract,
and it may not read anything its upstream contract does not promise. Where today's code falls
short of a contract, the gap is marked **GAP** and tracked in `docs/18`.

---

## 1. Frame registry

Every array in this system is in exactly one of these frames. **Name the frame in every
variable, file and manifest field that carries coordinates.**

| ID | Name | Axes | Units | Origin | Produced by |
|---|---|---|---|---|---|
| **F0** | Source pixel | x right, y down | px | top-left of the *full* decoded frame (e.g. 1920 × 1080) | S1 decode |
| **F1** | Model pixel | x right, y down | px | top-left of the model's centre-cropped, resized grid (e.g. 518 × 294) | MapAnything `load_images` |
| **F2** | Camera | OpenCV: x right, y down, z forward | model units | camera centre | S3 |
| **F3** | Model world | arbitrary rotation; *not* gravity-aligned; y ≈ first camera's down | **model units** | set by MapAnything | S3 |
| **F4** | Refined world | = F3 gauge (bundle adjustment refines, does not re-frame) | model units | = F3 | S3b (COLMAP) → S4 (OpenMVS) |
| **F5** | Local level frame (**LLF**) | e1, e2 horizontal and **arbitrary in heading**; up = recovered gravity | model units × `scale.factor` | cloud centroid | S6 export |
| **F6** | Local ENU | true East, North, Up | metres | a reference geodetic point | S5 georef, **GNSS only** |
| **F7** | Projected | UTM zone EPSG:32642–32647 (runtime choice) + EGM2008 height (EPSG:9518 for the 3-D transform) | metres | CRS | S5 georef, **GNSS only** |

Transforms, all as 4×4 or Sim(3) with the scale stated separately:

```
F0 ─(crop x0,y0 · scale s)─▶ F1                     mvs_result.json: camera.{scale, crop_x0_full, crop_y0_full}
F1 ─(K_model)────────────────▶ F2                   intrinsics.npy  (per view, F1 pixels)
F2 ─(cameras.npy, cam2world)─▶ F3                   (N,4,4) float, OpenCV convention
F3 ─(BA, same gauge)──────────▶ F4                   COLMAP sparse model
F4 ─(R_up · (p − centroid) · k)▶ F5                  export_manifest.json: gravity.up, scale.factor
F5 ─(track-aligned Sim(3), fit to GNSS in F6)─▶ F6   georef.json   (ADR-026: 6-DOF, never 7)
F6 ─(PROJ pipeline, allow_ballpark=False)─▶ F7      georef.json: epsg, geoid_model
```

### 1.1 Two naming corrections, adopted now

- **F5 is not ENU.** `export_manifest.json` currently calls it "a local gravity-aligned ENU
  frame". Its horizontal axes are an arbitrary orthonormal pair (`gravity.frame()`), not east
  and north. Calling it ENU invites a GIS user to trust a heading that does not exist.
  **Rename to LLF** in the manifest and the DSM tags. (**GAP C-1 — closed 2026-09-17**: the manifest writes `frame: "LLF"`.)
- **"Model units" are not metres** until a scale status says so (§2). Every surface that
  prints "m" must read `scale.status` first. (**GAP C-2** — the viewers and the DSM print
  "m" unconditionally. Closed 2026-09-17 for the viewers and the DSM, which now read the status.)

---

## 2. Scale contract

`docs/08` measured the Kolu model at **5.3–5.8× too small**. So scale is a first-class,
per-run, evidenced value, never an implicit property of the coordinates.

### 2.1 Calibration files — `research/calibration/<clip>.json`

One file per clip, naming every run that shares that clip's frame. It lives under
`research/` rather than `out/` because it is evidence and must be version-controlled;
`tools/scale_cal.py` is the only reader, and every builder goes through it. The live file:

```json
{
  "schema": "sih26158/scale-calibration/1",
  "runs": ["kolumvs3d", "kolu3d"],
  "factor": 5.54,
  "bracket": [5.32, 5.77],
  "status": "calibrated",
  "method": "known-object",
  "summary": "lane width and the ecoduct's published 21-22 m waist",
  "references": [
    {"object": "lane width", "model_m": 0.65, "real_m": [3.5, 3.75], "source": "…"},
    {"object": "ecoduct waist", "model_m": 3.95, "real_m": [21.0, 22.0], "source": "…"}
  ],
  "floor_checks": [
    {"object": "arch crown clearance", "model_m": 1.298, "min_real_m": 5.0,
     "implies_factor_at_least": 3.85, "source": "MKM 106 par. 9"}
  ],
  "measured_by": "src/experiments/exp14_scale_audit.py",
  "date": "2026-09-17"
}
```

A run may appear in at most one file. The feed-forward baseline and its MVS rebuild share a
frame (bundle adjustment refines, it does not re-frame), so they share a file; the gallery
builder refuses to build if they ever disagree.

`status` is one of:

| status | Meaning | May print "m"? |
|---|---|---|
| `unvalidated` | Model-asserted `metric_scaling_factor` only | **No** — print "model units", or "m (unvalidated)" |
| `calibrated` | An external length set the factor; `method` says which | Yes, with the method on hover |
| `gnss` | Scale came from the Sim(3) fit to GNSS in F6 | Yes |
| `gnss+rtk` | As above, with RTK/PPK fixes | Yes |

**Rules.** A run with no calibration file is `unvalidated`. There is no global default factor.
A factor is applied **once**, at export (S6), and the manifest records it; downstream
consumers never re-apply it.

---

## 3. Stage contracts

The stage numbers follow `docs/02` §3, with S3b added for bundle adjustment.

### S0 · Screen (admissibility, R-C9)

| | |
|---|---|
| In | video file (any container PyAV opens) |
| Out | `screen.json`: `{verdict: ACCEPT\|REJECT\|CROP, reasons[], sky_fraction, horizon_frac, shots[], overlay_px_frac}` |
| Must persist | the per-shot boundaries, so S1 can take one shot without re-detecting |
| Budget | ≤ 40 s CPU per clip (measured) |

### S1 · Ingest

| | |
|---|---|
| In | video; optional sidecar (`.SRT`), embedded `djmd` / `mov_text`, CSV, flight log |
| Out | `kf_{i:03d}_f{frame:05d}.jpg` in F0 after crop; `ingest.json` |
| `ingest.json` | `stats{video, resolution, fps, frames_decoded, shots_detected, keyframes_selected, rejected_*, overlay_crop_trbl, blur_threshold_varlap, flow_budget_px, has_gps_sidecar, srt_records}`, `keyframes[]` (source frame indices), `telemetry[]` |
| `telemetry[i]` | `FrameTelemetry{t_us, lat, lon, alt_ellipsoid, alt_rel, alt_baro?, yaw?, pitch?, roll?, focal_mm?, fov?, quality_flags[]}` (`docs/02` §4.2) |
| Must persist | **crop box** (F0 → cropped F0), source frame index per keyframe, telemetry aligned to keyframes |
| **GAP C-3** | `telemetry` is written and aligned (`video_ingest.py`, `telemetry_for_frames`), but no development clip has a sidecar, so every run reports `srt_records 0` (and until 2026-09-22 the parser's longitude pattern matched only the Mavic 2 misspelling `longtitude`, so a modern sidecar would have parsed to nothing; EXP-23). The unfed half is downstream: `VideoSource` has no `world()`, so S5 cannot read what S1 writes (`docs/13` S5) |
| Rule | a stale keyframe from a previous run in the output directory is an error, not a file to ignore (T-ROB-09) |

### S3 · Pose + metric prior (MapAnything)

| | |
|---|---|
| In | keyframes; **priors when available**: intrinsics (F1), `camera_poses` from telemetry, `is_metric_scale` |
| Out, arrays (F3 / F1) | `points.npy (P,3) f32`, `colors.npy (P,3) u8`, `conf.npy (P,) f32`, `mask.npy (P,) bool`, `cameras.npy (N,4,4) f64 cam2world`, `intrinsics.npy (N,3,3)`, `depth_z.npy (P,) f32` |
| Out, `mapanything_result.json` | `n_views, params_B, load_s, inference_s, seconds_per_view_cpu, torch_threads, checkpoint, view_shapes[[H,W]], images[], points, points_finite, bbox_extent, cameras` |
| Must persist | everything above **plus `metric_scaling_factor` per view** and the prior inputs actually passed |
| **GAP C-4** | `metric_scaling_factor` is printed in the prediction keys and **never saved**. It is the one channel the scale audit needs (`docs/08` H4) |
| **GAP C-5** | `model.infer(views, …)` is called with **no priors**. Intrinsics are later *fitted from the point maps* (0.22 px residual) instead of being given |
| Invariant | `len(points) == Σ H·W over view_shapes`; views are row-major in `images[]` order |

### S3b · Bundle adjustment (COLMAP, CPU)

| | |
|---|---|
| In | S3 cameras + intrinsics fit + keyframes at F0 resolution |
| Out | COLMAP sparse model (`cameras/images/points3D`); `mvs_result.json.sparse_after_triangulation`, `.sparse_after_bundle_adjustment` = `{Registered images, Points, Observations, Mean track length, Mean reprojection error}` |
| Gate | registered = N; mean reprojection error after BA ≤ 1.0 px (Kolu: 0.366, Short: 0.414) |
| Rule | intrinsics are aggregated by **median**, never mean (`docs/05` §9) |

### S4 · Dense geometry and surface (OpenMVS, CPU; COLMAP PatchMatch on GPU)

| | |
|---|---|
| In | undistorted images + `scene.mvs` (InterfaceCOLMAP) |
| Out | `scene_dense.ply` (F4, xyz + rgb), `scene_dense_mesh.ply` (F4), `mvs_result.json.stages[] = {stage, seconds, rc}`, `total_seconds`, `resolution_level` |
| Gate | every stage `rc == 0` except `TextureMesh`, which is non-fatal until **GAP C-6** (fails in 0.2 s, rc = 1) is fixed |

### S5 · Georeference (GNSS only)

| | |
|---|---|
| In | F4 cameras; `telemetry[]` |
| Out | `georef.json`: `{epsg, geoid_model: "EGM2008", sim3: {yaw, t, s}, dof: 6, residual_m: {h, v}, gnss_class, ballpark: false}` |
| Rule | **Level first, then 6-DOF**: yaw and the track's slope from the GNSS, roll about the track from gravity, plus t and s (ADR-026, amending ADR-008's 5-DOF). A 7-DOF fit on a single pass is refused (EXP-09) |
| Rule | the fit is done in F6 and projected to F7 last; the PROJ transformer is built with `allow_ballpark=False` and the geoid grid is checked at startup |
| Without GNSS | S5 is skipped, `georeferenced: false`, and **no CRS is written anywhere** |

### S6 · Export

| | |
|---|---|
| In | F4 dense cloud + mesh, gravity estimate, `scale_calibration.json`, optional `georef.json` |
| Out | `model.ply`, `model.obj`, `model.glb`, `model.gltf (+ buffers)`, `model.fbx`, `cloud.las`, `dem.tif`, `export_manifest.json` |
| Frame | **one frame for every file**: F5, or F7 when georeferenced |
| `export_manifest.json` | `formats{ply,obj,glb,gltf,las,geotiff,fbx: bool}`, `dem{width,height,gsd_m,filled_fraction,crs,reason_no_crs}`, `gravity{up, heading_spread, heading_degenerate, ground_correction_deg, residual_roll_deg, residual_roll_max_deg, camera_above_ground_m, horiz_track_m, altitude_spread_m}`, `georeferenced`, `note` |
| Adds (2026-09-17) | `frame: "LLF"`, `units: "metres"\|"model units"`, `scale{factor, status, basis, source}`; gravity lengths are in the files' units (**GAP C-7 closed**) |
| Rule | a format counts only if a **third-party reader** opens it (T-EXPORT-03); the FBX check is the `Kaydara FBX Binary` header |

---

## 4. Run manifest (R-NF3)

One file per run, `run_manifest.json`, written by the orchestrator. It is the single place a
reviewer looks. **GAP C-8**: today this information is spread over four JSON files and the
job logs.

```json
{
  "schema": "sih26158/run-manifest/1",
  "run_id": "kolu-2026-09-05T20:06Z",
  "git_sha": "e109da6",
  "config_sha256": "…",
  "containers": {"mapanything": "sha256:…", "mvs": "sha256:…"},
  "inputs": [{"path": "kolu.webm", "sha256": "…", "bytes": 0}],
  "region": "asia-south1",
  "hardware": {"vcpu": 8, "gpu": null},
  "stages": [{"id": "S1", "seconds": 0.0, "rc": 0, "outputs": ["ingest.json"]}],
  "frame": "LLF",
  "scale": {"status": "calibrated", "factor": 5.5},
  "georeferenced": false,
  "verdicts": {"R-O2": "FAIL", "R-O3": "UNVALIDATED"}
}
```

**Built 2026-09-18.** `src/tesseract/contracts.py` writes this file on every run and
`tesseract verify <rundir>` checks it: schema, ladder level, units against scale status,
frame against the georeferencing claim, and every artefact's checksum against the file on
disk. **GAP C-8 closed.**

---

## 5. Viewer data contract

Both 3-D pages read geometry that the builders lift out of the per-run `viewer.html`.

| Field | Meaning |
|---|---|
| `D.scale` | half-extent of the largest axis, in model units (`build_viewer.py`) |
| packed position | `q = round((A − mid) / scale × 32000)`, int16 |
| shader | reads int16 **normalised by 32767** |
| metres per shader unit | `D.scale × 32767 / 32000` — the exact inverse |

**Render and measure are separate paths, and the scale factor enters only one of them.**

| Page | Rendering | Measurement |
|---|---|---|
| `/` | `aPos` directly | `M_PER_UNIT = D.scale × 32767 / 32000` × **`scale.factor`** |
| `/gallery/` | `uScale = mpu / viewScale`, with `mpu = D.scale × 32767 / 32000` — **do not scale** | distance line × `viewScale` × **`scale.factor`** |

Scaling `mpu` would double-apply the factor on the gallery, because it already drives the
shared metric frame the A/B toggle relies on. **GAP C-9 — closed 2026-09-17** for the
viewers: both pages read `R.scale` / `EX[i].scale` (`factor`, `status`, `label`, `basis`),
print metres only when the status allows it, and print "units" otherwise. A headless-browser
test clicks two points on each page and checks the label against the math, and checks that
`uScale` is unchanged. The exported files do not carry the factor yet (`docs/08` S2).

---

## 6. Admissibility and failure codes

Machine-readable, so a finale operator (`docs/17`) reads a code rather than a traceback.

| Code | Stage | Meaning | Operator action |
|---|---|---|---|
| `ADM-HORIZON` | S0 | horizon in frame | try `horizon_policy="crop"` |
| `ADM-SKY` | S0 | sky fraction > 0.15 after crop | reject, or crop and re-screen |
| `ADM-SHOTS` | S0 | > 1 shot | take the longest shot |
| `ADM-OVERLAY` | S0 | static burned-in overlay | automatic crop; re-screen |
| `ING-NOGNSS` | S1 | no telemetry found by any parser | proceed; result will be LLF and `unvalidated` |
| `ING-SCHEMA` | S1 | telemetry found but unparseable | attach sample to the report; proceed without |
| `GEO-UNREG` | S3b | registered < N | drop unregistered views; warn if < 80% |
| `GEO-REPROJ` | S3b | reprojection error > 1 px after BA | stop; poses unreliable |
| `MVS-RC` | S4 | a stage returned rc ≠ 0 | ladder step down (`docs/13` §5) |
| `REF-BALLPARK` | S5 | PROJ would return a ballpark vertical | stop; geoid grid missing |
| `REF-7DOF` | S5 | a 7-DOF fit was requested on a single pass | refuse |
| `EXP-FORMAT` | S6 | a format failed third-party readback | ship the rest, flag the gap |

---

## 7. Storage layout

```
gs://sih26158-mumbai/                         asia-south1 only (R-NF8)
  mapanything/<run>_input/   kf_*.jpg
  mapanything/<run>_out/     points.npy … mapanything_result.json
  mvs/<run>_out/             scene_dense.ply  scene_dense_mesh.ply  mvs_result.json

out/                                          local, gitignored, regenerable
  kf_<run>/                  kf_*.jpg  ingest.json
  <run>_raw/                 S3 arrays, as above
  <run>_mvs/                 S4 outputs
  <run>mvs3d/                points_fused.npy  mesh_*.npy  viewer.html  viewer_stats.json
    export/                  the seven files + export_manifest.json
  ppt/                       measure_<run>.json (compare_mvs.py)
```

Names are part of the contract: the builders find runs by these paths, and `build_qa.py`
re-greps figures from them.

---

## 8. Compatibility rules

1. Every JSON artefact carries `schema: "sih26158/<name>/<major>"` from its next revision.
   A reader refuses a major version it does not know.
2. Adding a field is a minor change and needs no version bump. Removing or re-meaning one
   is a major change.
3. Arrays are little-endian `.npy`; the dtype is part of the contract (`f32` points, `u8`
   colours, `f64` cameras).
4. A contract change lands in the same commit as the code that implements it and the line
   in this file that describes it.
