# Ingestion, export and georeferencing — verified findings

Second research pass, 2026-09-04/05. Licences read from each project's own LICENSE or
`gh api .../license`. Items that could not be confirmed are listed under "Unverified" and must not
be relied on.

---

## 1. REGULATORY — this constrains the architecture, not just the paperwork

**India, Guidelines for acquiring and producing Geospatial Data and Geospatial Data Services
(Department of Science and Technology, 15 February 2021).** Independently confirmed.

- Threshold: **1 m horizontal (planimetry) / 3 m vertical (elevation)**.
- Data **finer than the threshold** "can only be created and owned by **Indian entities**" and
  must be **"stored and processed in India"** — explicitly, "on a domestic cloud or on servers
  physically located in India."

**SIH26158 targets ≤ 1 m spatial accuracy, i.e. at or finer than the threshold.** Assume the rule
binds.

| Consequence | Effect on this project |
|---|---|
| Processing must occur on Indian infrastructure | **asia-south1 (Mumbai) / asia-south2 (Delhi) only** |
| The `asia-southeast1` (Singapore) Cloud Run GPU fallback is **not usable** | Removes the one region where Cloud Run L4 was available to us |
| No foreign SaaS photogrammetry API | Rules out hosted commercial pipelines |
| Compliance is by self-certification | State it explicitly in the submission |

This makes the GPU-quota problem sharper rather than softer: Cloud Run L4 does **not** exist in
`asia-south1`, so an India-resident GPU means Compute Engine L4 (or H100 in `asia-south1-c`) —
exactly the quota that is currently denied. **The Baramati cluster, being physically in India,
is compliant.** For an intelligence customer this is a feature to state, not a limitation to hide.

---

## 2. Two traps that would silently destroy the ≤ 1 m budget

### 2.1 The geoid — a 24 to 98 m error, and PROJ will not warn you

GNSS reports **ellipsoidal height h**; maps want **orthometric H**, with `H = h − N`.

Geoid separation **N** measured across India with PROJ 9.5.1 and the real EGM grids:

| Place | N (EGM2008) | N (EGM96) | Δ between models |
|---|---|---|---|
| Leh | −24.32 m | −23.65 m | 0.67 m |
| **Amritsar** | −47.59 m | −45.90 m | **1.68 m** |
| Delhi | −52.54 m | −52.59 m | 0.05 m |
| Mumbai | −67.68 m | −68.53 m | 0.85 m |
| Chennai | −92.03 m | −92.25 m | 0.22 m |
| Kanyakumari | −98.24 m | −98.53 m | 0.29 m |

Two separate failure modes:
1. **Ignoring N entirely** is a 24–98 m blunder (India sits on the Indian Ocean Geoid Low, the
   largest on Earth).
2. **Choosing the wrong model blows the budget on its own** — EGM96 vs EGM2008 differ by
   **1.68 m at Amritsar**, against a 1 m requirement.

The *gradient* is gentle (~1.8 cm across a 580 m site), so one constant N per site is fine. It is
the absolute offset that kills.

> **Two silent failures, both reproduced.** With the grid missing, PROJ **returns z unchanged and
> raises nothing**, self-describing as a *"ballpark vertical transformation."* And calling
> `transform(lon, lat)` **without z** returns a 2-tuple and applies no shift at all.

**Correct usage** (EPSG:9518 = WGS 84 + EGM2008 height; EPSG:9707 = WGS 84 + EGM96 height):

```python
t = Transformer.from_crs("EPSG:4979", "EPSG:9518",
                         always_xy=True, allow_ballpark=False)   # raises instead of lying
lon, lat, H = t.transform(lon, lat, h)                            # z IS REQUIRED
```

Defend it three ways: `allow_ballpark=False`, assert `"ballpark" not in t.description`, and check
`TransformerGroup(...).best_available` at startup — it names the missing grid and its CDN URL.
Ship `us_nga_egm08_25.tif` (80.6 MB) inside the image for the offline demo (R-NF6).

**No public Indian national geoid model is downloadable** — Survey of India's is a partial-coverage
status map. **EGM2008 is the defensible choice**, and PROJ has zero India-specific grids.

**Note:** ODM applies **no geoid correction at all** — `opendm/location.py` `convert_to_utm()`
returns `[x, y, alt]` with altitude untouched.

### 2.2 UTM scale error — 0.6 m per km, i.e. the whole budget

UTM is a *conformal projection*, not a metric frame. Measured in zone 43N: **−400 ppm** on the
central meridian to **+981.5 ppm** at the zone edge; with the elevation factor, **−644 to
+564 ppm ≈ 0.6 m per kilometre** across India.

**Therefore: fit the similarity transform in a local ENU frame and project to UTM last.** Fitting
in UTM bakes projection scale error into the reconstruction. Build ENU with
`Transformer.from_pipeline` (`CRS.from_proj4("+proj=topocentric …")` fails on mismatched units).
Select the zone at runtime from mean longitude — `zone = int((lon+180)//6)+1`, EPSG:326xx — never
hardcode, because the flight location is unknown until the event.

> **Correction to an earlier assumption:** EPSG:7755–7787 is **not** a UTM block. It is a
> **per-state ISRO set** (NNRMS TR 122:2005) — 7755 "WGS 84 / India NSF LCC", 7756 Andhra Pradesh
> … 7787 West Bengal; 7755–7776 Lambert Conformal Conic, 7777–7787 Transverse Mercator. India's
> UTM zones are **42N–47N = EPSG:32642–32647**.

Also: IMU gravity fixes roll and pitch only, leaving **5 DOF** (yaw + translation + scale) — not 4.
A full similarity is 7.

---

## 3. DJI metadata — what the sidecar actually contains

Modern per-frame block (Mavic 3+):

```
[iso: 100] [shutter: 1/800.0] [fnum: 4.5] [ev: 0.7] [focal_len: 24.00]
[latitude: 55.366533] [longitude: 10.430244]
[rel_alt: 1.371 abs_alt: 62.354] [gb_yaw: -9.6 gb_pitch: 3.8 gb_roll: 0.0]
```

> ### `abs_alt` is NOT a GNSS observation
> Across 11 SRT files and 7+ airframes, `abs_alt − rel_alt` is constant **to the millimetre**
> (std = 0.00000 over 12,318 Mavic 3 frames). So `abs_alt = rel_alt + takeoff_constant` — it is a
> **barometric** channel. **It must never be fed to bundle adjustment as an independent height
> observation.** Doing so would inject a fake, perfectly-correlated constraint into exactly the
> axis (vertical) that already governs our error budget.

**Parser traps, all from real files.** Unit encoding flips between generations and fails
*silently*: `fnum: 280` = f/2.8 (×100) vs `fnum: 3.2` literal; `focal_len: 240` = 24 mm (×10) vs
`24.00`; `dzoom_ratio: 10000` vs `1.00`. The counter is `FrameCnt` **or** `SrtCnt`. Mavic 2 spells
it **`longtitude`**. Legacy P4/Mavic Pro carry no `rel_alt`/`abs_alt` and no gimbal; **M300 gives
GPS + BAROMETER only**. Some files have no `-->` timing line; CRLF and BOMs occur.

**Robustness answer for an unknown drone:** newer models also write a **protobuf telemetry track
inside the MP4** (`djmd` box), written *regardless of the "Video Subtitles" toggle*.
`telemetry-parser` (MIT OR Apache-2.0, AdrianEddy/telemetry-parser) decodes it **and** yields
`focal_length` + `distortion_coeffs`. Probe order: sidecar `.SRT` → embedded `djmd` →
`mov_text` stream → exiftool XMP.

---

## 4. Intrinsics when unknown

`f_px = (f_mm / sensor_width_mm) × image_width_px`; OpenSfM/ODM store a **normalized** focal
(`focal = f_px / max(W,H)`), which for landscape collapses to `f_mm / sensor_width_mm` and is
resolution-invariant.

| Source | Licence | Coverage |
|---|---|---|
| OpenSfM `sensor_data.json` | BSD-2 | **3709 models**, but **only 14 DJI entries, all legacy** |
| ODM `sensor_data.sqlite` | BSD-2 (fork) | **7523 rows**, 38 `dji %` + 21 `hasselblad%` |

> **Lookup gotcha:** the Mavic 3's camera is filed under **`"Hasselblad L2D-20c"`** — a
> `"DJI " + model` lookup misses it entirely.

> ### The highest-leverage bug found in this pass
> ODM's `video2dataset.py:234-235` stamps every extracted frame `Model: "Unknown"`. The database
> key becomes `"dji unknown"`, misses, and falls back to a generic `focal_ratio = 0.85`.
> **Every ODM video frame therefore reconstructs from a generic focal prior regardless of which
> drone shot it.** Fix by writing the true Make/Model into the frames, or passing
> `--cameras cameras.json`.

COLMAP's fallback is `f = 1.2·max(W,H)` (≈45° HFOV) — **poor for a ~84° DJI lens, where ≈0.55 is
closer**. Prefer EXIF/SRT + sensor DB, then **fix** intrinsics rather than self-calibrate: on a
near-planar nadir pass, `k1` and focal are nearly linearly dependent and the surface **domes**
(James & Robson 2014, DOI 10.1002/esp.3609). DJI also writes `DewarpData` and
`CalibratedFocalLength` XMP tags that **ODM reads neither of** — free accuracy available.

---

## 5. Export — the FBX question is resolved

> **Correction to `01-SRS` R-O5.** The earlier note said FBX had no permissive writer. **That is
> wrong. assimp (BSD-3) CAN write FBX** — `Exporter.cpp` registers `"fbx"` (binary) and `"fbxa"`
> (ascii), `EXPORT_VERSION_INT = 7500` (FBX 2016+), enabled by default. Driven from Python via
> `pyassimp` (ISC). **R-O5 is fully satisfiable with permissive licences only.**

| Library | Licence | Writes |
|---|---|---|
| **assimp** | **BSD-3** | **OBJ, PLY, glTF/GLB, FBX** — one library covers four of the six |
| laspy | BSD-3-style | LAS 1.4 (`point_format=6`, `add_crs`), built-in `laspy.copc` |
| GDAL / rasterio | MIT-style / BSD-3 | GeoTIFF + **COG driver** |
| Open3D | MIT | ply/stl/obj/off/gltf/glb — **reads FBX, cannot write it**; no LAS |
| trimesh | MIT | obj/ply/glb/gltf — **no FBX** |

**Two decoys avoided:** *FBX2glTF* is BSD-3 but wraps the account-gated Autodesk SDK **and
converts the wrong direction**; *ufbx* (MIT, popular) is **import-only**. Shelling out to Blender
is legally fine (GPL *MereAggregation*) **but a published `bpy` glue script is itself GPL**.

---

## 6. Decode, viewers, and one library to avoid

**FFmpeg licensing, settled from source:** LGPL-2.1+ by default; the native H.264/HEVC **decoders
are LGPL**, and libx264/libx265 are **encoders only**. **A decode-only pipeline never needs GPL.**

| Tool | Licence | Verdict |
|---|---|---|
| **PyAV** | BSD-3 | **Healthiest** — HEAD 2026-09-02, 8 open issues |
| torchcodec | BSD-3 | CUDA wheels, Linux x86/aarch64 |
| NVIDIA DALI | Apache-2.0 | GPU decode in CUDA containers |
| **decord** | Apache-2.0 | **AVOID — HEAD 2022-07-19, 221 open issues** (its `pushed_at` misleads) |

**Viewers.** Ship **COPC** (one range-readable compressed LAZ file, no tiling step) to
**Potree 1.8.2** (BSD-2), which reads COPC directly and does octree LOD + HTTP range — the right
answer for multi-hundred-MB clouds. The same file opens in **QGIS ≥ 3.26 with no PDAL build
required**, and imports into CloudCompare. Add **three.js + GLTFLoader** (MIT) for the mesh.
CesiumJS has zero COPC/LAS support; deck.gl's `PointCloudLayer` loads everything into memory.

**Blur metric provenance, corrected:** do **not** write "Tenenbaum 1970 introduced Tenengrad" —
Pertuz's own `fmeasure.m` reads `case 'TENG' % Tenengrad (Krotkov86)`. Survey: Pertuz, Puig &
Garcia, *Pattern Recognition* 46(5):1415–1432, 2013. And `cv2.Laplacian` needs a **signed/float**
depth so negative responses survive. **Never hardcode a sharpness threshold** — select by
percentile within the clip, since thresholds are dataset-dependent.

---

## 7. Unverified — do not rely on these

1. SRT layout for **Air 3, Mini 4 Pro, Avata 2, DJI FPV** — only fabricated samples found.
   (⚠ `CallMarcus/dji-drone-metadata-embedder`'s samples mix real captures with hand-written
   fixtures — its Air 3 / Mini 4 Pro / Avata 2 clips are **synthetic**.)
2. "Video Subtitles OFF ⇒ no SRT" — in DJI manuals but never stated as a consequence.
3. NVDEC / DALI 4K decode throughput — no primary NVIDIA figure.
4. Whether Pech-Pacheco 2000 **originates** variance-of-Laplacian or merely benchmarks it.
5. **Consumer-drone `abs_alt` datum** — undocumented by DJI. For **RTK models** DJI does state it
   is ellipsoidal ("not based on the commonly used EGM96/2008 elevation benchmark").
6. Whether DJI SRT `focal_len` is physical mm or 35 mm-equivalent.
7. No independent non-PROJ cross-check of the geoid N values; GeoTIFF geokey behaviour is
   doc-only (no GDAL on this box).
8. Licence ambiguities: DJI_SRT_Parser LICENSE says MIT while `package.json` says ISC;
   exiftool's GPL *version* within its dual Artistic-or-GPL grant.
