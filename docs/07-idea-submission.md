# Idea submission — SIH26158

What the portal actually asks for, what the evaluation actually rewards, and the text to
paste into each field. Sources are the official artefacts, not summaries of them:
`SIH2026-IDEA-Presentation-Format.pptx` and `SIH2026-Guidelines-College-SPOC.pdf`, both
pulled from sih.gov.in, plus the live PS listing.

> **Superseded deck, 2026-09-22.** The submission deck is now the team's Google Slides file, audited in `research/05-deck-audit.md`. `tools/build_sih_ppt.py` and `out/ppt/` describe the 17 September deck; do not rebuild it for submission. It still reads the withdrawn Village run and still says per-vertex colour.

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
completion did well. Ours is on slide 4, against both of NTRO's own tables: four of the
six desired outputs met and two open, and a measured standing on each of the six
weighted evaluation criteria.

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
metrically calibrated, textured 3D mesh and dense point cloud, exportable as OBJ, PLY,
LAS, GeoTIFF, glB/glTF and FBX, and inspectable in a browser viewer built for
measurement rather than display.

The idea rests on a finding we measured rather than assumed. Modern feed-forward 3D
models are the reason a single pass is tractable at all: they recover camera pose and
metric scale from one flight line, where classical structure-from-motion needs overlap
it does not have. But their geometry has a hard ceiling. We measured a model sampling
depth per pixel while carrying information only per 14-pixel patch - about 2.8 m on
the ground on our survey clip - set by its vision backbone and its interpolating depth
head. We confirmed this three ways and tested the
competing explanation, which failed. No downstream tuning can recover detail the patch
grid never carried, which is why single-pass AI reconstructions look convincing from
altitude and fall apart on inspection.

Its metric scale failed the same test: checked against lane markings and a structure
of published size, it was 5.3-5.8x too small from the air. So we use the feed-forward
model strictly as a pose prior, take scale from GNSS or from objects of known size in
the scene, refine with global bundle adjustment, and take every delivered surface point
from full-resolution per-pixel photometric multi-view stereo. Measured across two
unrelated real clips: reprojection error 1.73 to 0.37 px, surface detail 1.8-3.6x finer,
and on the calibrated survey clip a vertical structure ceiling lifted from 12.9 m to
19.8 m and 136% of the baseline's ground coverage. The whole pipeline is
containerised and runs on commodity CPU with no GPU dependency.

Two of the six desired-output targets are not yet met and we say so. Processing takes
34 minutes for 45 keyframes on 8 vCPU against a 15-minute budget; GPU multi-view stereo
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
because they recover camera pose where classical structure-from-motion lacks the
overlap to. But their geometry is capped by a patch grid - about 2.8 m on our survey
clip - and their scale was 5.3-5.8x too small from the air. So we use the model strictly
as a pose prior, take scale from GNSS or objects of known size, and take every delivered
surface point from full-resolution per-pixel photometric multi-view stereo. Across two
real clips: reprojection error 1.73 to 0.37 px, detail 1.8-3.6x finer.

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

Both read `tools/deck_theme.py`, which holds the entire visual system — palette, type
scale, the 12-column grid and each figure's placed size. It exists because the slides
and the charts had drifted into two different greys, two different blues and two
different typefaces, so every chart read as pasted in from another document.

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

**Two of the six PS targets are stated as unmet, on purpose.** See §3 — the deck says
34m 38s against a 15-minute budget, and unvalidated absolute accuracy, each beside the
work that closes it.

**FBX now actually exists, so the format count is a verified 6 of 6.** It had been 5 of 6
locally, with FBX only claimed for the container. `write_fbx` now falls back to Blender
when the assimp CLI is absent; both clips have a real `model.fbx` with a `Kaydara FBX
Binary` header. Counting is against the PS's own six-item list, where glB and glTF are one
line item — counting them separately would have flattered a 5/6 into a 6/7.

---

## 7. How the deck is designed, and why

Nobody scores typography (§3), so the design brief here is narrow: make a dense
technical argument legible in the seconds a screening reader gives it, and make it look
like it belongs to the mandated template rather than sitting on top of it.

**The navy is not ours.** `#1F497D` is the official template's own theme colour `dk2` —
what its title and every prescribed section heading are already set in. Adopting it as
our accent makes our content native to the chrome.

**Two hues, and no third.** Navy is ours: our pipeline, our result, a target met. Rust
is the other thing: the feed-forward baseline, a target still open, the cost not yet
paid down. Those are the same axis, so no green tick and no amber warning exist
anywhere in the deck. Everything else is grey.

**Rules and whitespace, not boxes.** The previous version put every group in a rounded
rectangle with a hairline border. When everything is a card, nothing is emphasis. Rows
are separated by hairlines, status by a short keyline, and grouping mostly by space.

**Measured numbers are set in Consolas.** They are instrument output, not marketing
figures, and monospaced digits line up down a column where a proportional face will
not.

**Figures are authored at the size they are placed at.** `fig_beforeafter` used to be
drawn 9.2 in wide and placed at 5.9, so every label in it was silently scaled to 64%
and the chart read as imported from somewhere else. `deck_theme.FIG` now fixes each
figure's size and both modules read it.

**The template's own content pointers are kept, not deleted.** Each slide carries its
prescribed pointers verbatim, set small at the top right, so an evaluator reads the
question and our answer to it on one line. "Clarity and details in the prescribed
format" is a scored criterion, and this is that argument made typographically.

Two things were tried and removed, both recorded in the code: a drawn stem-and-branch
tree on slide 2, which at that size read as stray marks at the margin (the grammar now
does the job), and filled rust discs for a "no" in the slide 6 matrix, which read as
emphatically *present* next to the filled navy "yes". Ink density there now falls
monotonically — solid navy, pale navy, empty rust ring — so the matrix survives the
greyscale printout a screening table works from.

Fonts are Segoe UI, Segoe UI Semibold and Consolas, all embedded by the PowerPoint COM
export. **The PDF is the canonical artifact.** Any Google Slides copy substitutes those
faces and will drift.

> **Keep Field 9 and the deck in step.** The deck reads its numbers from the run
> outputs; the Field 9 text above is hand-written. Two had already drifted apart —
> coverage (135 vs 136%) and wall clock (33 vs 34 min) — and are now reconciled to the
> measured values. Re-check them after any re-run: an evaluator reads both.

---

## 8. The rebuild against the problem statement itself

The first version of this deck was designed well and grounded badly. Re-reading the PS
line by line, and the linked PDF as rendered images, turned up four things.

**The PDF carries a weighted scoring function, and the deck never mentioned it.**

| Criterion | Weight |
|---|---|
| Reconstruction Accuracy | **30%** |
| Model Completeness | **20%** |
| Processing Speed | **20%** |
| Innovation | 15% |
| Scalability | 10% |
| User Interface | 5% |

Verified against the page-38 image, not just the SRS transcription of it; the six rows
sum to 100. Accuracy + Completeness + Speed is 70% and all three are objectively
measurable. Slide 4 now reports a measured standing on every row, including the two we
miss, and says that 70% figure out loud.

**The PS names eight key challenges, and the SRS already traced all eight as testable
requirements (R-C1–R-C8) — but the deck listed four generic "other risks".** Slide 4's
left column is now those eight, by roman numeral, in the PS's own words, each with the
strategy that answers it. Two are marked open in rust: (vi) near-real-time processing
and (viii) metric accuracy without GCPs.

**Slide 2 inverted the template.** The shipped file makes "Proposed Solution (Describe
your Idea/Solution/Prototype)" the dominant element and its three pointers the skeleton
of the answer. The deck had a tagline in the IDEA TITLE slot and both the heading and
the pointers shrunk to 6.8 pt grey corner text — which is precisely "changing the idea
detail pointers". The full idea title is now in the title slot, the section heading is
visible in navy, and each of the three pointers is a block heading with our answer under
it. `retext()` gained a size override because the master sets that placeholder for the
two words "IDEA TITLE" and a real 63-character title climbed off the top of the slide.

**A factual error, now removed.** Slide 5 shaded three applications as "the three NTRO
named first" and picked the wrong three: the PS order is (i) Border and strategic area
mapping, (ii) Disaster damage assessment, (iii) Urban planning and smart cities, and
Military reconnaissance is **(viii), last**. All eight are now listed in the PS's own
order with its own numbering, and the claim is gone rather than corrected — position in
a list is not priority.

Smaller corrections in the same pass: slide 3's ingest stage now names the PS's
mandatory and optional input lists verbatim; the statement lines quote the PS's own
deliverable phrase (*visualisation, measurement and analysis*) and its own four benefits;
and slide 5 states plainly that **near real-time situational awareness** is the PS's
fifth benefit and the one we cannot claim yet.

On illumination, challenge (iii): the deck claims only what exists — keyframe scoring
that survives exposure ramps, and per-vertex colour, so there is no texture atlas and no
seams. It does not claim shadow-invariant matching. Photometric MVS is genuinely
illumination-sensitive, and the credibility of the two OPEN rows depends on not
overclaiming anywhere else.
