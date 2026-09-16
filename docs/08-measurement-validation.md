# Measurement validation — is the metre a metre?

Version 1.0 — 2026-09-16. Experiment EXP-14. Reproduce with
`python src/experiments/exp14_scale_audit.py` (writes `research/exp14-results.txt`).

---

## 1. The finding

**The Kolu reconstruction is 5.3–5.8× too small (central 5.5×).** Every absolute length it
reports — on the demo, in the gallery, in the exported files, in the deck and in `docs/05` —
is short by that factor. The shape is right; the ruler is wrong.

Two rulers that do not depend on the model agree:

| Ruler | In the model | Published | Factor |
|---|---:|---:|---:|
| Lane width, edge line to dashed centre line | **0.650** model m (0.64 and 0.66 either side) | 3.50–3.75 m | **5.38–5.77** |
| Ecoduct waist, barrier crest to barrier crest | **3.95** model m (plateau median; min 3.70) | 21–22 m | **5.32–5.57** |

And three consequences land where reality says they should:

| Quantity | In the model | × 5.3–5.8 | Plausible? |
|---|---:|---:|---|
| Deck surface above the road | 1.40 m | 7.4–8.1 m | Yes — a highway overpass needs ≥ ~5 m clearance plus the deck |
| Camera above ground | 10.59 m | 56–61 m | Yes — the frame holds a four-lane highway, the ecoduct and both verges |
| Scene extent | 19.1 × 24.1 m | ~106 × 133 m | Yes |
| DSM cell, declared 0.10 m | — | 0.53–0.58 m on the ground | The shipped GeoTIFF geotransform is wrong by the same factor |

**The user's report was right about the direction, and a ×2 correction would still be wrong.**
Applied to Kolu, ×2 leaves every measurement 2.7–2.9× short. The ×2 has therefore *not* been
applied; see §7.

---

## 2. Why this went unnoticed

`docs/05` §2 said it plainly: the metre labels came from MapAnything's
`metric_scaling_factor`, and the only check was a **plausibility band** — implied camera
speeds of 1.6–3.0 m/s, altitudes of 6.4–11.4 m. The document even warned that a 30% error
would pass.

The band passed a **450% error**. It is the defect, and it belongs in the same class as the
`sky_fraction` metric that could never exceed 0.60 (`docs/04` §4.6): a check whose output
looked like validation and measured nothing.

It fails for a structural reason. A camera 10.6 m up with a 67° horizontal field of view
(f = 1450.5 px on a 1920 px frame, from `out/kolu_mvs/mvs_result.json`) sees about 14 m of
ground. The keyframes show a four-lane highway with a median, a parallel road, the ecoduct and
its verges. **The band compared the model with itself, never with the picture.** An altitude
that sounded reasonable in isolation was physically incompatible with what the camera was
looking at, and nothing in the pipeline put those two facts side by side.

> **Lesson, written as a rule.** A metric claim is validated only by a length whose value
> comes from outside the model: GNSS, a surveyed check point, or an object of published size.
> A self-consistency check is a smoke test. Never label it validation.

---

## 3. Method

### 3.1 Frame

Measured in the **export frame**: points from `out/kolumvs3d/points_fused.npy`, rotated by
the gravity vector recorded in `export/export_manifest.json`, centroid origin, axes
`[e1, e2, up]`. The transform is exactly `export_formats.export_all`, so the factor applies
to every shipped file and to both viewer pages, which read the same geometry.

### 3.2 Why Kolu carries rulers

The clip is a CC0 Wikimedia Commons video of the **Kolu ecoduct**, Estonia's first wildlife
overpass (2013), over national road 2 (Tallinn–Tartu). Two published dimensions:

- **Lane width.** The four-lane sections were designed on **3.5 m** lanes (the Swedish-style
  cross-section; ERR 650086, and ERR news 1608116446 for Kärevere–Kardla). The ministry's
  stated minimum for a 2+2 section is **3.75 m**. The bracket uses both.
- **Ecoduct waist.** Estonian Wikipedia, *Ökodukt*: *"ehitati Kolu sild selle kitsaimas
  kohas 22 meetri laiuseks"*. 21 m is also reported. The bracket uses both.

### 3.3 Lane width, by paint profile

1. Take the right-hand carriageway below the deck (`e ∈ [3.5, 9.5]`, `n ∈ [−6.5, 0.5]`,
   height < −0.3).
2. Find the road direction as the angle that makes the grass strips sharpest in an
   across-road profile: **−24.6°**.
3. Profile the fraction of *paint* points (top-8% luminance, low saturation, not green)
   across the road, at 2 cm bins.
4. A carriageway reads **solid | dashed | solid**, and a dashed line has a *lower* paint
   fraction than a solid one. Take the most symmetric triple whose middle peak is the weakest.

Peaks across the road:

| Position (model m) | Paint fraction | Reading |
|---:|---:|---|
| −3.27 | 0.22 | far edge of the parallel lane, beyond the sign strip (not used) |
| −1.21 | 0.24 | pale asphalt-to-grass edge of the shoulder (not used) |
| **−0.73** | **0.65** | **solid edge line** |
| **−0.09** | **0.17** | **dashed centre line** — the lowest fill of the triple |
| **+0.57** | **0.28** | **solid edge line, median side** |
| +1.85, +2.43, +2.87 | 0.36–0.42 | sunlit far carriageway saturating the paint mask (not used) |
| +4.15 | 0.18 | beyond the far carriageway (not used) |

Checked against the source frame (`out/kf_kolu/kf_020_f01122.jpg`): the carriageway carrying
the white car reads median-side solid line, lane, dashed line, lane, bright solid edge line,
narrow shoulder, grass strip with the brown tourist sign. The −1.21 peak is the pale
asphalt-to-grass edge of that shoulder. The diagonal "hatching" on the next lane over is
**fence shadow**, not paint, and the method correctly does not use it.

The two lanes measure **0.64 and 0.66** — symmetric to 1.5%, which is the evidence that the
triple was read correctly.

### 3.4 Ecoduct waist, by barrier crests

1. Slice the deck every 0.25 model m along its axis (across the road).
2. In each slice, walk outward from the deck centre to the drop — road level, or a 0.3 m
   gap where the drop was never observed — and take the highest point within 0.8 m inside
   it as the barrier crest.
3. Keep only slices where **both** crests stand ≥ 0.3 m clear of the deck's median height
   (otherwise the "wall" is a point on the embankment).
4. The waist is a plateau, not a slice: take every slice within 10% of the narrowest.

19 slices qualify. They trace the hourglass — 6.1 m, narrowing through 4.7 and 4.0 to
**3.70–4.05**, and widening again to 6.8 — which is the evidence that the dimension measured
is the one the published figure describes. Plateau median **3.95**.

### 3.5 What would falsify this

- A lane standard other than 3.5–3.75 m on this 2013 section. Anything in the European range
  (3.25–3.75 m) still gives ≥ 5.0×.
- A waist figure that is not the crossing width. The hourglass shape makes that unlikely, and
  a ±10% allowance for crest-to-crest versus clear width still gives 4.8–6.1×.
- A frame error. Both rulers are horizontal lengths in the same frame; a tilted vertical
  would shorten them by cos(tilt), and the recorded ground correction is 0.64°.

No plausible reading of either ruler brings the factor near 2.

---

## 4. What moves, and what does not

### 4.1 Unaffected — scale-free

These survive intact, and they are the load-bearing results of the project:

- The **14× sampling-to-information ratio** (`docs/05` §1–2). It was always stated as the
  scale-free result, and it is.
- **MVS vs feed-forward: 1.8–3.6× finer** at matched radius. Both clouds share one frame, so
  the ratio holds; only the radius *labels* move (§4.2).
- The growth-per-doubling columns, the self-affine signature, the 1 m agreement between the
  two reconstructions.
- **Reprojection error in pixels** (1.730 → 0.366 px), registration (45/45), point and
  triangle counts, timings, every percentage, coverage *ratios* (135–136%).
- The EXP-01/05/08/09/13 results. They are simulations with their own ground truth.

### 4.2 Affected — absolute lengths on Kolu

| Where | Stated | Corrected (×5.3–5.8) |
|---|---|---|
| Demo, "scene extent" | 24.5 m | ~130–142 m — and the readout carries a separate **+2.4% bug**: `demo_template.html` computes `D.scale*2*32767/32000` where the extent is exactly `2*D.scale` |
| `demo/README.md`, DSM coverage | 19.3 × 24.3 m at 0.1 m GSD | ~102–141 m across; cell 0.53–0.58 m |
| `docs/05` §2, Kolu patch | 51.2 cm effective resolution | **2.7–3.0 m** |
| `docs/05` §2, Kolu GSD | 3.66 cm/px | ~19–21 cm/px |
| `docs/05` §9, finest detail | 3.5 mm at 3 cm radius | ~1.8–2.0 cm at ~16–17 cm radius |
| Deck + Q&A, relief ceiling | 2.33 m → 3.58 m | ~12–14 m → ~19–21 m |
| `measure_kolu.json`, relief thresholds | "above 1.0 / 1.5 / 2.5 m" | above ~5.5 / 8.3 / 14 m |
| Export manifest, camera height | 10.59 m | 56–61 m |
| Shipped `dem.tif` geotransform | 0.10 m/px | wrong by the factor |
| Shipped `cloud.las`, `model.*` coordinates | "metres" | model units × 1/5.5 |
| Viewer measurement, both pages | metres | short by the factor |

### 4.3 The one that changes a conclusion

`docs/05` said the feed-forward stage resolves 30–50 cm, "with no margin" against the 1 m
target. **On Kolu the corrected figure is 2.7–3.0 m.** Feed-forward geometry alone does not
meet the ≤ 1 m target on this clip even in relative terms. That strengthens the case for the
MVS stage rather than weakening it: the MVS surface keeps resolving at ~2 cm corrected, well
inside the target.

### 4.4 Unknown — the other clips

The factor is a **per-run model output**. It says nothing about the Village clips (`ytd`,
`yt`), whose figures include the deck's "1.9 mm finest detail" and "3.6× finer at 6 cm".
Their absolute scale is now *known to be untrustworthy by construction* and *not yet
measured*. EXP-14b (`docs/12` R1) gives them a ruler. Until then, treat every absolute Village
length as unvalidated, and do not carry the Kolu factor across.

---

## 5. Why the model got it wrong — hypotheses, not findings

None of these is tested. They are listed so the research program can test them in order.

| # | Hypothesis | Test |
|---|---|---|
| H1 | The metric head is weak far from its training distribution. Most training scenes are ground-level; ~58 m of altitude over a highway is not. | Run the same checkpoint on footage with SRT altitude at 10, 30, 60 and 100 m. Plot the factor against true altitude. |
| H2 | The Apache checkpoint (6 datasets) is weaker on scale than the CC-BY-NC one (13). | EXP-02, restricted to scale, on clips with a ruler. The NC checkpoint is for internal ablation only. |
| H3 | The crop/resize to 518 × 294 changes the effective focal length the scale head sees. | Feed the model the true intrinsics as a prior (`intrinsics=`, `is_metric_scale`) and compare. |
| H4 | Scale is fine per view but diluted by joint inference over 45 views. | Per-view `metric_scaling_factor` spread, from the saved outputs. |

H3 is the cheapest, and it matters for the design either way: MapAnything **accepts
intrinsics and metric priors** (`docs/02` §2). The pipeline has never passed them.

---

## 6. Remediation plan

Ordered by dependency. Owners and dates are in `docs/18`.

| # | Change | Why | Status |
|---|---|---|---|
| **S1** | Per-run `scale_calibration.json`: `{run, factor, bracket, method, references, measured_by, date}`, produced by EXP-14-style audits and read by every builder | One named, evidenced number per run. Never a global constant. | Designed |
| **S2** | Apply S1 **at export**: scale points and mesh before writing, and record `scale_correction` in `export_manifest.json` | The files are the product. A viewer fix alone would leave the viewer and the files disagreeing. | Designed |
| **S3** | Apply S1 in the viewers to **measurement and labels only** — `M_PER_UNIT` on `/`, the distance line on `/gallery/` — never to `mpu`/`uScale`, which drives rendering. In the same change, fix the scene-extent readout to `2*D.scale*factor` (it is 2.4% high today) | Scaling the renderer would double-apply the factor | Designed |
| **S4** | A "scale: unvalidated / calibrated (method) / GNSS" badge on every metric readout | The page should say which kind of metre it is showing | Designed |
| **S5** | Replace the plausibility band with a **footprint check**: implied ground footprint from the intrinsics and camera height, versus the detected content (lane pitch, vehicle length) | Would have caught this automatically | Research (`docs/12` R1) |
| **S6** | Pass true intrinsics and any SRT altitude to MapAnything as priors (H3) | Cheapest possible fix at the source | Research (`docs/12` R1) |
| **S7** | Re-label `docs/05`, the Q&A page and the deck from S1, so every absolute number is either corrected or flagged | The build's figure re-grep will catch any number that no longer appears in its source | Blocked on S1 |
| **S8** | "Calibrate from a known length" tool in the viewer: click two points, type the true distance, and write S1 | Makes S1 an operator action, not a developer one | Designed |

---

## 7. The ×2 request

A ×2 correction was requested on the evidence that a 1.4 m distance should read 2.8 m. It
has **not** been applied, for two reasons.

1. **On Kolu, the measured factor is 5.3–5.8.** ×2 would move every number towards the truth
   and leave all of them wrong.
2. **A single constant is wrong in principle.** The scale is a per-run model output, so the
   factor that is right for one clip is not evidence for any other.

**Open question to the requester, which decides whether §1 is complete:** *which two points
were measured, and what is the 2.8 m distance known from?* One possibility fits exactly:
2.8 m is the **median separating strip** in Estonia's newer 2+2 design (ERR 1608116446). If
that is the reference, there are two measurements to reconcile rather than one to override.
The 2013 Kolu section may use a different median width, and EXP-14 does not measure the
median: the far carriageway is sunlit and saturates the paint mask, so its edge line is not
cleanly resolved. Measuring it is a one-line extension once the reference is confirmed.

---

## 8. Reproduce

```bash
python src/experiments/exp14_scale_audit.py
```

Needs `out/kolumvs3d/points_fused.npy`, `colors_fused.npy` and `export/export_manifest.json`.
CPU only, about a minute. The output is `research/exp14-results.txt`; the method constants
(analysis region, paint thresholds, crest clearance) are at the top of each function, with
the reason for each value next to it.
