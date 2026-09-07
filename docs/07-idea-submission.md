# Idea submission — SIH26158

What the portal actually asks for, what the evaluation actually rewards, and the text to
paste into each field. Sources are the official artefacts, not summaries of them:
`SIH2026-IDEA-Presentation-Format.pptx` and `SIH2026-Guidelines-College-SPOC.pdf`, both
pulled from sih.gov.in, plus the live PS listing.

---

## 1. Live state of this problem statement (checked 2026-09-07)

| | |
|---|---|
| PS | **SIH26158** · Software · **Robotics and Drones** |
| Organisation | National Technical Research Organisation (NTRO) |
| Ideas submitted | **0 / 500** |
| Portal deadline shown against the PS | **30 September 2026** |
| Whole portal so far | 296 ideas across 233 problem statements; the busiest PS has 13 |

Two things follow from that counter.

**The field has not started yet.** Nothing is lost by spending another week on quality.

**But a PS freezes the moment it reaches 500 ideas** and no further submission is accepted
for it — that rule is on p.16 of the SPOC guidelines. A drone/3D PS from NTRO is a
headline-looking statement; it will not stay at zero. Submit with a week in hand, not on
the 29th.

The real timing risk is not the cap, it is the **chain**: internal hackathon → SPOC
nominates the team → team leader receives portal credentials → team leader submits. Only
the SPOC can start that, so it is the one part of this that cannot be done from a laptop.

> **Deadline discrepancy, flagged deliberately.** The official SPOC guidelines PDF gives
> *two different* last dates on the same page (p.16): "till 15th Sept 2026" in one
> paragraph and "till 30th Aug 2026" in the next. The live PS listing shows
> **30 September 2026**. Confirm the operative date with the SPOC rather than trusting any
> one of the three.

---

## 2. The rules that are actually enforced

From the template's own instruction slide, which is slide 7 of the official .pptx:

- **Maximum six slides, including the title slide.**
- **Avoid paragraphs.** Points, diagrams, infographics, pictures.
- **Use the provided template without changing the idea-detail pointers.**
- **Upload PDF. No PPT, no Word, no other format will be supported.**
- Delete the instructions slide before uploading.

From the SPOC guidelines:

- One team may submit against **at most 2 problem statements**.
- **4–5 teams per PS** may be shortlisted for the Grand Finale — and the PS-creating
  organisation is *not obliged to select anyone* if the proposals do not meet its
  expectations. NTRO can return an empty shortlist for its own PS.
- Official idea-selection criteria: *novelty, complexity, **clarity and details in the
  prescribed format**, feasibility, practicability, sustainability, scale of impact, user
  experience, potential for future work progression.*
- The team leader enters **ten** fields, of which only the last is the deck: idea title,
  idea description, idea presentation (PDF). The other seven are verifications of
  pre-entered team data.
- Ideas "must be new and must not have been present in any previous event/program of any
  sort."
- IP in a winning idea is **split equally** with the organisation that posted the PS.

Note that "clarity and details in the prescribed format" is itself a scored criterion.
Template compliance is not bureaucratic overhead here; it is marks.

> **No video field exists** in the official ten-field list. Several guides state that the
> SPOC uploads "idea PPT and video demonstration". That claim is not in the authoritative
> document. Confirm with the SPOC before building a video on spec — though a 60–90 s
> screen recording of the viewer is cheap insurance and useful at the internal hackathon
> regardless.

---

## 3. What first-hand accounts say, minus the platitudes

Filtered to advice that is specific enough to act on, from people who went through it.

**Mirror the problem statement's own words.** Winners report that high-submission PSs may
be pre-sorted mechanically before a human reads them, so the PS vocabulary should appear
verbatim. Independently of whether that is true, it is the cheapest possible demonstration
of problem understanding. Our deck uses *single-pass, georeferenced, metrically accurate,
textured mesh or point cloud, facades and rooftops, vegetation and obstacles*, and names
all six required export formats.

**Show completion honestly, and show it as a number.** Teams that stated a level of
completion did well. Ours is on slide 2: four of the six desired-output targets met and
measured, two named as open.

**A flowchart is expected.** Several accounts single out the missing architecture diagram
as a rejection cause. Slide 3 is built around one.

**Nobody is scoring your typography.** Two decks in the public winners' collection are
tech-logo walls with spelling errors in the stack list, and one left the template's
literal "IDEA TITLE" placeholder in the heading. The bar for polish is low. That is not
licence to be sloppy — it means design effort has a low ceiling of return, and the
marginal hour is better spent on evidence.

**One piece of widely-repeated advice we are deliberately not following.** A popular
write-up recommends inflating the completion percentage "but keep it realistic too". That
is advice to lie to the organisation that wrote the problem statement and knows what these
numbers should look like. Our two unmet targets are stated on slide 4 with the work that
closes them.

---

## 4. Portal free-text fields — ready to paste

### Field 8 — Idea title

```
Measured, not interpolated: accurate 3D from a single drone pass
```

### Field 9 — Idea description

```
We convert one monocular drone pass — video, GPS and flight metadata — into a
metrically scaled, textured 3D mesh and dense point cloud, exportable as OBJ, PLY,
LAS, GeoTIFF, glB/glTF and FBX, and inspectable in a browser viewer built for
measurement rather than display.

The idea rests on a finding we measured rather than assumed. Modern feed-forward 3D
models are the reason a single pass is tractable at all: they recover camera pose and
metric scale from one flight line, where classical structure-from-motion needs overlap
it does not have. But their geometry has a hard ceiling. We measured a model sampling
at 2.2 cm while carrying information only at 30-50 cm, set by its patch-14 vision
backbone and its interpolating depth head. We confirmed this three ways and tested the
competing explanation, which failed. No downstream tuning can recover detail the patch
grid never carried, which is why single-pass AI reconstructions look convincing from
altitude and fall apart on inspection.

So we use the feed-forward model strictly as a pose and metric-scale prior, refine it
with global bundle adjustment, and take every delivered surface point from
full-resolution per-pixel photometric multi-view stereo. Measured across two unrelated
real clips: reprojection error 1.73 to 0.37 px, surface detail 1.8-3.6x finer and
resolving to 1.9 mm, vertical structure ceiling lifted from 2.33 m to 3.58 m, and
135% of the baseline's ground coverage on the survey clip. The whole pipeline is
containerised and runs on commodity CPU with no GPU dependency.

Two of the six desired-output targets are not yet met and we say so. Processing takes
33 minutes for 45 keyframes on 8 vCPU against a 15-minute budget; GPU multi-view stereo
and keyframe budgeting close that, and CPU fan-out is already measured at 1.42x as the
fallback. Absolute accuracy against the 1 m target is unvalidated because neither test
clip carries GNSS, so the digital surface model is written with a real geotransform in
metres and deliberately no coordinate reference system rather than a plausible-looking
wrong one; validation needs an RTK-tagged dataset with surveyed check points.

Model selection was made against licence terms as well as accuracy: VGGT's acceptable-use
policy bars military and espionage applications, which this problem statement explicitly
lists, so we use MapAnything's Apache-2.0 checkpoint. All processing is pinned to an
Indian region, as India's geospatial guidelines require for data finer than 1 m.
```

### Field 9, short variant (~850 characters)

The portal's character limit for this field is not documented anywhere we could find.
Paste the long version first; if it is rejected, use this rather than editing prose inside
a web form at the deadline.

```
We turn one monocular drone pass - video, GPS and flight metadata - into a metrically
scaled, textured 3D mesh and dense point cloud, exported as OBJ, PLY, LAS, GeoTIFF,
glB/glTF and FBX with a browser viewer for measurement.

The idea comes from a measurement. Feed-forward 3D models make a single pass tractable
because they recover camera pose and metric scale where classical structure-from-motion
lacks the overlap to. But their geometry is capped by a patch grid: we measured one
sampling at 2.2 cm while carrying information only at 30-50 cm. So we use the model
strictly as a pose and scale prior, refine it with global bundle adjustment, and take
every delivered surface point from full-resolution per-pixel photometric multi-view
stereo. Across two real clips: reprojection error 1.73 to 0.37 px, detail 1.8-3.6x
finer, vertical structure ceiling 2.33 m to 3.58 m.

Two of the six targets are open and stated: 15-minute processing is not met on CPU, and
absolute accuracy is unvalidated because neither test clip has GNSS.
```

---

## 5. Fields the team must fill — do not let these be invented

| Where | Field | Status |
|---|---|---|
| Slide 1 | Team ID | **«TEAM ID»** — from the portal after SPOC nomination |
| Slide 1 | Team Name (registered on portal) | **«TEAM NAME»** — must be unique and **must not contain the institute name** (guidelines p.14) |
| Slides 2-6 | Oval badge, top-left | **«TEAM NAME»** — same value, five places |

`TEAM_NAME` and `TEAM_ID` are constants at the top of `tools/build_sih_ppt.py`. Set them
once and rebuild; every occurrence updates and the PDF is re-exported.

---

## 6. Build and reproduce

```bash
python tools/make_ppt_figs.py      # figures, from the run outputs
python tools/build_sih_ppt.py      # deck + PDF, on the official template
```

Outputs land in `out/ppt/`. While `TEAM_NAME` / `TEAM_ID` are still placeholders the PDF
is named `SIH26158_IdeaSubmission_DRAFT.pdf` **on purpose** — a file named for submission
that says «TEAM NAME» six times is an accident waiting to happen. Set the two constants
and rebuild; the draft suffix disappears and the file is uploadable. PDF export goes
through PowerPoint COM, because python-pptx cannot write PDF and the portal accepts
nothing else.

The charts and every headline number are read at build time from `mvs_result.json`,
`export_manifest.json` and `out/ppt/measure_*.json`, and the build **fails** if those are
missing rather than falling back to a stale constant. Regenerate the measurement files
with:

```bash
python src/analysis/compare_mvs.py --baseline out/kolu3d/points_fused.npy \
    --mvs out/kolu_mvs/scene_dense.ply --json out/ppt/measure_kolu.json
python src/analysis/compare_mvs.py --baseline out/ytd3d/points_fused.npy \
    --mvs out/ytd_mvs/scene_dense.ply --json out/ppt/measure_short.json
```

### Two things worth knowing about the numbers on the slides

**Wall clock reads 34m 38s, not the 32m 43s in `docs/05`.** The deck uses
`total_seconds` from the run's own `mvs_result.json` (2078.7 s, and its stage timings sum
to 2061.8 s). The 1963 s figure in `docs/05` §9 and `docs/06` is on a different basis and
the two have not been reconciled. The deck takes the slower, self-consistent one — it is
measured by the same run that produced every other number on the slides, and it errs in
the conservative direction. Neither figure is anywhere near the 15-minute budget, so no
conclusion moves.

**FBX now actually exists, so the format count is a verified 6 of 6.** It had been 5 of 6
locally, with FBX only claimed for the container. `write_fbx` now falls back to Blender
when the assimp CLI is absent; both clips have a real `model.fbx` with a `Kaydara FBX
Binary` header. Counting is against the PS's own six-item list, where glB and glTF are one
line item — counting them separately would have flattered a 5/6 into a 6/7.
