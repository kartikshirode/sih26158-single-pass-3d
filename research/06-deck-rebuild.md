# Deck rebuild brief, 2026-09-22

Two inputs: a past SIH finalist's read of the current deck, and the official template's own
instruction slide. They agree. This file says what to change and why. It gives decisions and
fragments, not finished copy, because the finalist's main complaint is that the deck reads
machine-made and a brief full of polished sentences makes that worse.

The finalist, verbatim: too clean, looks AI generated; keep it short, judges have no time;
technical approach has too much information and should be explained a different way;
feasibility looks AI-made and should cover all points of view; impact is decent but needs a
more natural layout; follow the template instructions and keep the slide count.

## Two rule violations, fix these first

Both are checkable against `out/ppt/SIH2026-IDEA-Presentation-Format.pptx`, slide 7.

**1. Eight slides against a hard limit of six.** The instruction reads: "Kindly keep the
maximum slides limit up to six (6). (Including the title slide)". Delete two of the three
Proposed Solution slides. The deck then matches the template one for one, and the footers,
which already read 1 to 6, come out right without touching them. Keep whichever of the
current slides 3 or 4 the team prefers; the shared link opens on 4.

**2. Three mandated pointers are truncated.** The instruction: use the template "without
changing the idea details pointers". `docs/07` §9 already records that shrinking or altering
a pointer counts as changing it. Restore the parentheses verbatim:

| Deck now | Template |
|---|---|
| Proposed Solution | Proposed Solution (Describe your Idea/Solution/Prototype) |
| Methodology and process for implementation | Methodology and process for implementation (Flow Charts/Images/ working prototype) |
| Benefits of the solution | Benefits of the solution (social, economic, environmental, etc.) |

The Methodology pointer asks for working-prototype images. That is the instruction to put the
real Kolu evidence on the Technical Approach slide, in place of the synthetic panels.

Also from the same slide: avoid paragraphs, upload PDF, delete the instructions slide. Three
paragraphs are still in: the solution summary, the landslide scenario, and "What's different".

## Why it reads machine-made, in specifics

Naming the tells is more useful than "make it look human".

- One module repeats about twenty-two times across the deck: coloured circle icon, bold
  heading, two or three lines. Every idea in the deck is dressed identically, so nothing is
  emphasised.
- No slide has empty space. Density is the same corner to corner on all eight.
- Perfect grids. Four across, then two by two, always aligned.
- Body text blocks are all close to the same length, which means text was written to fill a
  box rather than to say a thing.
- Stat tiles for things that are not stats: "1 pass", "0 GCPs", "Live 3D".
- Two accent colours applied with total consistency.
- Phrases: "AI and classical geometry, together"; "Each component is an extension of
  published works".

What reads as human: one large real artefact per slide, uneven density, icons on almost
nothing, numbers in running text rather than in designed tiles, and screenshots that look
like screenshots.

## Two limits that do the cutting

Give the team these instead of a list of edits. They force the volume down mechanically.

- **12 pt floor for body text.** It is 7.5 to 9 pt now, and 8.5 pt across the whole of the
  slide 8 table. Anything that does not fit at 12 pt is cut.
- **At most three points under each template pointer.** The pointers are prescribed; the
  amount under them is not.

## Slide by slide

Scope stays. The criteria score novelty, complexity and potential for future work, so the
planned architecture is part of the idea being judged. Cut repetition, not reach: mark what
runs today and what is planned, and keep a one-line answer to every PS challenge.

### 1. Title

Team ID is blank. One product name, not three (SinglePass3D, Single Pass 3D, OnePass3D).

### 2. Proposed Solution (Describe your Idea/Solution/Prototype)

Delete two duplicates. On the survivor: the input/output pair goes full width across the top
and carries the slide. Cut the four numbered step cards, which repeat the Technical Approach
slide. Three points per pointer under it.

Two claims to fix here, from `research/05-deck-audit.md` items 3 and 4: the scale in the
pictured model comes from objects of known size, not from GPS, and live 3D is planned rather
than running.

### 3. Technical Approach

The finalist's sharpest note. Ten numbered boxes, a six-row technology table and three result
panels is around forty separate elements.

Replace the boxes with one flow diagram, two states: solid outline for what runs today,
dashed for planned. Running today: ingest with blur and parallax keyframing, SRT parsing,
MapAnything poses, bundle adjustment, dense cloud, textured mesh, six export formats, the
browser viewer with measurement. Planned: masking, labels, streaming SLAM, live preview,
true ortho, 3D Tiles, measured/inferred marking. One legend replaces seven hedges in the text.

The technology table becomes one line. The three synthetic panels go; the Methodology pointer
asks for working-prototype images and there are real ones (see Images below). This also
retires audit item 1, because the invented "BLURRY: SKIPPED" and "moving car masked" overlays
leave with the panel.

### 4. Feasibility and Viability

"All points of view" means five, and the deck has three. Add the two that are missing, one
line each:

- Technical, operational, cost: already there, shorten.
- **Legal and licensing.** Every component is clean for a defence customer: MapAnything
  Apache-2.0, COLMAP BSD, OpenMVS AGPL-3.0 run unmodified as a separate program. This is the
  slide where audit item 2 turns from a liability into an argument no other team will make.
  VGGT, MASt3R-SLAM and 2DGS move to Research and References as prior art, with a line
  saying their licences exclude military or commercial use, which is why they are not in the
  build.
- **Security.** On-premise, air-gapped, imagery never leaves the network.

The six-row risk table goes to three rows. Keep the real Kolu evidence strip; it is the
strongest thing on the slide.

### 5. Impact and Benefits

The finalist calls this decent and wants the layout changed. The four-quadrant
social/economic/environmental/security block is prescribed by the pointer, so keep the
categories and drop the icon chips: four short lines, no cards.

Delete one of the two comparison tables. There are two, on consecutive slides: "Usual
photogrammetry vs Single Pass 3D" here, and "Compared with existing tools" on the last slide.
Keep the second, which names Pix4D, DJI Terra and OpenDroneMap, and cite it once.

The landslide scenario becomes points. "Once, a drone flies down the valley" needs rewriting
whatever happens to the layout.

### 6. Research and References

Nearest to right already. Three changes: add the first author to reference 8 (Tang et al.),
either source the 38,575 drones figure or drop it, and either source "3D during flight only
on Phantom 4 RTK" or soften it, since that cell is the differentiator in the table.

The measured/inferred figure stays. It is the best thing in the deck: green roofs, orange
facades, which is EXP-08 drawn as a picture. Two words are missing, that the scene is
synthetic and the marking is planned. Recolour it or the slide 3 labels panel, because orange
currently means buildings on one slide and inferred on another.

## Images to make

Real screenshots are the strongest evidence a human built this, and the team does not have
these yet.

1. **A fresh `kolu_tex` render** at the input frame's angle and brightness. The picture in the
   deck now is the mesh from before texturing: its carriageway has no lane markings, while the
   atlas the pipeline produced has painted dashes, chevrons and a red car in its charts. The
   caption "3D mesh, 3.45M points" is also the dense cloud's point count.
2. **The real keyframe strip**, `research/run-evidence/kolu-keyframes.png`. Real footage with
   trucks on the carriageway, in place of the synthetic frames.
3. **A console measure-tool screenshot**, optional. If used, the caption must say the scale
   comes from two objects of known size in the scene.

## Before it goes out

- [ ] Six slides, including the title.
- [ ] Three pointers restored verbatim.
- [ ] Team ID filled.
- [ ] One product name.
- [ ] One comparison table.
- [ ] Body text 12 pt or larger.
- [ ] Slide 5 panel 1 replaced with real keyframes (audit item 1).
- [ ] VGGT, MASt3R-SLAM and 2DGS cited as prior art only (audit item 2).
- [ ] Scale caption says objects of known size (audit item 3).
- [ ] Live 3D marked planned (audit item 4).
- [ ] Unbuilt stages marked planned in the flow diagram (audit item 5).
- [ ] Exported as PDF, instructions slide deleted.
