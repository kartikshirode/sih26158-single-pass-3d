# Audit of the submission deck (Google Slides, 22 September 2026)

Deck: `docs.google.com/presentation/d/19nvsNP285fBRD14kn_PcaTyq0_sc82mQ`, exported as PDF and
PPTX on 2026-09-22: 8 pages, 31 embedded images. It replaces the deck `tools/build_sih_ppt.py`
generated on 17 September. Every claim below was checked against the run evidence in this
repository, the licence table in `docs/16` and `research/01`, and the primary source online.

## Verdict

Every number the deck takes from our own runs is right. It should not go in as it stands,
for five reasons: one figure is captioned as a pipeline result that no code in this
repository produced, three named components carry licences that exclude this customer, the
real result on slides 3 and 4 is captioned in a way that implies GPS scale it does not have,
live 3D is claimed in a comparison against shipping products, and several unbuilt stages are
described in the present tense. Each has a one-line fix below.

## Must change before submission

### 1. Slide 5: "The results of the stages (synthetic test scene)"

The first panel (`ppt/media/image23.png`) shows four frames labelled "BLURRY: SKIPPED" and
"moving car: masked". No code in `src/` or `tools/` draws those labels or the `GPS+IMU`
timestamps, the synthetic scene in `src/simscene` contains no vehicles, and vehicle masking
is not built (`docs/12` EXP-06, queued). The third panel, "Labelled 3D model", shows
per-class labels, and the pipeline does not label real data. Where the point cloud in the
middle panel came from is not recorded here.

A picture captioned as a result is read as evidence. Either caption the row "Illustration of
stages 2, 3 and 9 (synthetic scene, not pipeline output)", or replace it with real outputs:
eight of the 45 selected Kolu keyframes (`research/run-evidence/kolu-keyframes.png`, trucks
on the carriageway included), the Kolu dense cloud, and the textured mesh from the console.

### 2. Three named components are barred for NTRO

| Where | Component | Licence, as read on 2026-09-22 |
|---|---|---|
| Slide 6 "Technical", ref [1] | VGGT | VGGT AUP: commercial use "with the exception of military applications" (`research/01`) |
| Slide 6 "Technical", slide 5 "streaming SLAM", ref [3] | MASt3R-SLAM | CC BY-NC-SA 4.0 (`rmurai0610/MASt3R-SLAM` LICENSE). The MASt3R weights under it are CC BY-NC-SA 4.0 too |
| Slide 6 "Technical", ref [6] | 2D Gaussian Splatting reference code | Inria / MPII research-only licence (`hbb1/2d-gaussian-splatting` LICENSE) |

`docs/16` L-10 bars all three from any product build. Citing them as prior art is fine.
Slide 6 says "Each component is an extension of published works: VGGT, MapAnything,
MASt3R-SLAM, 2D Gaussian Splatting", which reads as the stack we build on, and a defence
evaluator who opens the VGGT licence finds the military exclusion in its first clause.

Suggested text: "We build on licence-clean components: MapAnything (Apache-2.0), COLMAP
(BSD) and OpenMVS (AGPL-3.0, run unmodified as a separate program) today; SAM 2 and gsplat
(both Apache-2.0; gsplat implements 2D Gaussian splatting) are the planned choices for
masking and splats. VGGT and MASt3R-SLAM are cited as prior art; their licences exclude
military or commercial use." SAM 2 and gsplat are named as planned because neither runs in
the pipeline yet (item 5). Leave the streaming SLAM on slide 5 unnamed until one is chosen
that passes the same check.

### 3. Slides 3 and 4: the caption next to "0 GCPs"

"Real result from our pipeline, on a clip with no GPS data and no ground control points"
sits beside "0 GCPs: GPS/IMU fusion gives real-world scale". The pictured model's metres come
from two objects of known size in the scene (lane width and the ecoduct's 21 to 22 m waist,
factor x5.54, `docs/08`), not from GPS. MapAnything's own metric scale on the same clip was
about 5.5 times too small, which also contradicts slide 5 step 6, "MapAnything gives metric
poses". GPS scale has run only on synthetic data: consumer GNSS 2.260 m absolute, RTK/PPK
0.098 m, against the problem statement's 1 m (`README.md`, end-to-end table).

Suggested text:

- Caption: "Real result from our pipeline on a clip with no GPS and no GCPs. Its scale comes
  from two objects of known size in the scene, not from the drone."
- "0 GCPs" line: "No GCPs with RTK/PPK (0.10 m on our synthetic test). Consumer GPS alone
  measured 2.26 m, so we add one or two checkpoints."
- Slide 5 step 6: "MapAnything gives camera poses and dense depth for all keyframes. Scale
  comes from GNSS, RTK or objects of known size."

### 4. Live 3D is claimed as a capability

Slide 8's comparison table gives the product "3D during flight: Yes, rough model on the edge
box" in a row against Pix4D, DJI Terra and OpenDroneMap. Slides 3 and 4 list "Live 3D" as one
of three headline numbers, and slide 2 says "The rough model appears on an edge computer as
the drone continues to fly". None of it exists: no edge box, no streaming SLAM, no
progressive output (build plan Phase 3, B-31). The measured full run on 8 vCPU with no GPU
is 2,078.7 s for 45 views without texturing (`docs/11`), and texturing the full mesh added
1,078 s more (`docs/12` EXP-20), so "The complete model is ready right after landing" is
also untimed.

Suggested text: table cell "Planned: rough model on an edge box". Slide 2: "Planned: a rough
model on an edge computer while the drone flies, and the full model after landing (target
under 15 minutes for a 10-minute video; not yet timed on a GPU)."

### 5. Unbuilt stages in the present tense

Running today: video ingest with blur and parallax keyframing; DJI SRT parsing and alignment
to keyframes (not yet used for georeferencing); MapAnything poses; bundle adjustment;
OpenMVS dense cloud; textured mesh; export to PLY, OBJ, glTF/GLB, LAS, GeoTIFF DSM and FBX;
a browser viewer with measurement.

Described as running, not built: masking of cars, people and animals (slides 2 to 4 and 6);
terrain, building, road and tree labels (slides 2 to 5); true ortho (slides 2 to 5); 3D Tiles
(slide 5); surfaces marked measured or inferred (slide 5 step 9, and the slide 8 figure);
planar priors on roofs and walls (slide 6); the GNSS/IMU/baro factor graph (slide 5 step 7).

One legend fixes this on slide 5: mark each of the ten stages "running" or "planned".
Stages 2 and 6 run today. 1 runs, without telemetry fusion. 7 runs as bundle adjustment
without the GNSS factor graph. 8 runs as MVS to textured mesh and DSM; splats and ortho are
planned. 10 runs except LAZ and 3D Tiles. 3, 4, 5 and 9 are planned.

## Should change

- Slides 2, 3 and 4 are three versions of "Proposed Solution", all footed "2". Keep one.
  Slide 3 has the real input and output side by side and is the strongest, with the caption
  fix from item 3.
- One product name. Slides 2 to 4 say SinglePass3D, slides 7 and 8 say Single Pass 3D, and
  slide 8's table says OnePass3D.
- Slide 1: Team ID is blank.
- Submit it as a PDF. The official template's instruction slide asks for PDF (`docs/07`).
- Slide 6 "Prototype": say what was tested. "Tested end to end on a 52 s public drone clip
  (Kolu, CC0): video in; textured mesh, point cloud and six export formats out. Not yet run
  with real GPS telemetry."
- Slide 7, "38,575 drones are registered in India (PIB, Feb 2026)": the only PIB link on
  slide 8 (PRID 2244931) is the SVAMITVA release, which carries the 3.29 lakh villages figure
  and not the drone count. Link the drone release or drop the number.
- Reference [8], DroneSplat: add the first author (Tang et al., arXiv 2503.16964, March 2025).

## Checked and correct

| Claim | Source | |
|---|---|---|
| 1,562 frames in, 45 kept (2.9%), 1,517 rejected, 787 on blur | `research/run-evidence/kolu-ingest.json` | Correct |
| Kolu clip 52 s | 1,562 frames at 29.97 fps is 52.1 s | Correct |
| 45 of 45 keyframes registered; 1.730 to 0.366 px, 4.7x | `out/kolu_mvs/mvs_result.json` | Correct |
| 3.45M points | 3,445,735 dense points | Correct |
| Before and after imagery | Kolu (CC0). No frame from the withdrawn Village clip | Correct |
| Textured mesh | Kolu textured mesh served on the console since 2026-09-22 (`docs/12` EXP-20) | Correct as of today |
| MapAnything, 3DV 2026 | arXiv 2509.13414 comments field | Correct |
| MASt3R-SLAM, 15 FPS on an RTX 4090 | arXiv 2412.12392: "a single NVIDIA GeForce RTX 4090", "operating at 15 FPS" | Correct |
| GeoFF3D, about 2,000 UAV images in about 5 minutes, metric | arXiv 2608.28288 abstract, 28 August 2026, via the arXiv API | Correct |
| Wu et al.: works for sparse aerial sets, does not replace SfM/MVS | arXiv 2507.14798 abstract | Correct |
| SVAMITVA drone survey in 3.29 lakh villages | PIB, 25 March 2026, PRID 2244931 | Correct |
| Pix4D 75% / 60% overlap | `docs/11` §1 | Correct |
| OpenDroneMap takes video with an SRT GPS file | `docs/11` §2, incumbents table | Correct |
| Pix4D: video "not advised" | Pix4D support, "How to use Videos for Processing" (article 205294735): "For accurate mapping it is not advised to use videos" | Correct |
| DJI Terra takes video since July 2026 | DJI Terra 5.3.0, released 27 July 2026 (DJI enterprise blog; DroneDJ, 27 July 2026) | Correct, but it is limited to the Mavic 3 Enterprise, Mavic 3 Thermal and Matrice 4 series. "Needs GPS metadata" is not what the sources say; name the supported aircraft instead |

## Not verified here

PIX4Dreact being 2D only; DJI Terra's 80/70% overlap, and 3D during flight only on the
Phantom 4 RTK (this cell is a differentiator, so it needs a source most of all);
OpenDroneMap's "60% nadir plus 70 to 80% oblique cross grid"; 3.5 to 5.7 h for 1,039 images
(Gbagir et al., Geographies 2023); 38,575 registered drones; VGGT's CVPR 2025 best-paper
award. None contradicts anything in this repository. Each needs its own source before
submission, because the comparison table on slide 8 is where an evaluator from the field
will look first.
