# The research paper: state and handoff

Written 2026-09-29, at master 2914563 plus the owner's .gitignore commit f57bdc7. Read this
before touching `paper/`. It says what the paper is, where each part comes from, what's
done, what's left and what would make it better.

## What it is

`paper/Tesseract-research-paper.docx` (and a PDF beside it): an 18-page research paper on
SIH26158, about 7,700 words, 12 figures, 8 tables, 23 references, written for the SIH
judges and technical reviewers.

The owner was asked which report to write, because the template in the repo at the time
("Report Template - Grand challenge 1.docx") is the Techfest GC-1 BVLOS swarm challenge,
a different competition. The answer was a SIH26158 research paper in our own structure.
That template and the GC-1 scenario pptx have since left the repo folder.

The brief was to present the model as working for any input, with the demo clip as the
example. The paper does that honestly: Tesseract is described as one pipeline for any
clip (the admission screen decides), results are given for six inputs, `SIH DEMO.mp4` is
the worked example in section 7, and nothing that wasn't measured is claimed.

## How to rebuild

```
cd paper && npm install          # once: docx 9.8.1, image-size 1.2.1
python paper/figures.py          # needs out/runs/night-b1-final, out/runs/demo-prior,
                                 # out/evidence/quality-2026-09-25, web/data/sheet.jpg
python paper/charts.py           # numbers are typed in, no runs needed
node paper/build_paper.js        # writes paper/Tesseract-research-paper.docx
```

PDF: LibreOffice isn't installed and the docx skill's `soffice.py` fails on Windows
(no AF_UNIX). Word works through COM from PowerShell:

```
$w = New-Object -ComObject Word.Application; $d = $w.Documents.Open("<docx>", $false, $true)
$d.SaveAs([ref]"<pdf>", [ref]17); $d.Close($false); $w.Quit()
```

The docx, the PDF, `fig/` and `node_modules/` are gitignored (`paper/.gitignore`). The
figures carry frames of the third-party demo clip, and research/09 keeps those out of
git, the same rule as `web/data/`. Only the three scripts, the npm files and this note
are committed. Copies of the scripts in any session scratchpad are stale; these are the
real ones.

## Structure and where each number comes from

All prose and every number sits in `build_paper.js`. Figure and table numbers follow the
order of the `figure()` and `table()` calls, and the text cites them by number, so moving
one means renumbering the prose. References are numbered by list position.

| Section | Content | Source |
|---|---|---|
| Abstract, 1 | problem, contributions; Figure 1 pipeline diagram (charts.py) | README, docs/00 |
| 2 | Table 1 targets and weights | README (from docs/SIH26158.pdf) |
| 3 | related work: COLMAP, GLOMAP, OpenMVS, ODM, DUSt3R, MASt3R, VGGT (licence), MapAnything, Waechter, TSDF | docs/11, README finding 1 |
| 4.1 | straight-line degeneracy, Figure 2 | research/exp09-results.txt |
| 4.2 | consumer GNSS floor, Figure 3 | research/exp05-results.txt |
| 4.3 | focal length against depth, Table 2, gimbal pitch fix | research/11 section 9 |
| 4.4 | scale without GPS (Kolu 5.3-5.8x, MapAnything 40x) | exp14, audit/night-7of10/RUNLOG.md |
| 4.5, 4.6 | completeness ceiling; DST 2021, geoid, UTM | exp08; README findings 5, 6 |
| 5 | method S0-S8, every setting | research/09, 10, 11, 12, 13; codemap |
| 6 | hardware, Table 3 inputs, metrics | research/09 section 2, research/11 section 1 |
| 7 | worked example on B1: Figure 4 keyframes, Table 4 and Figure 5 pose fix, Table 5 texture, Figures 6-8 model, Table 6 and Figure 9 depth prior, 7.6 time | research/10, 12, 13; out/runs/night-b1-final and demo-prior manifests and local_gpu_result.json |
| 8 | Table 7 all inputs, 8.1 accuracy, 8.2 speed with Figure 10, 8.3 Nicosia, Kolu, Village with Figures 11-12, 8.4 exports | research/11, 12; RUNLOG; docs/05 sections 8-9; manifests of codex-b2-v2, night-b3-final, codex-b5v-v3 |
| 9 | Table 8 status of each target | S8 verdicts, docs/14 claims ledger |
| 10, 11 | limitations, conclusion | research/11 section 12, 12 section 7, 13 section 8 |
| Appendix A | reproduce commands | README |

Figures made by `figures.py`: 4 keyframes, 5 pose fix (out/evidence side views), 6 photo
against render for keyframes 40 and 100, 7 a new viewpoint behind keyframe 60, 8 the map
sheet (web/data/sheet.jpg), 9 the houses (textured, OpenMVS mesh shaded, prior mesh
shaded, from behind keyframe 160), 12 Kolu (research/run-evidence). Made by `charts.py`:
1, 2, 3, 10, 11.

## Done

- Asked and settled the report type (SIH26158 paper, not GC-1).
- Collected the data from research/, docs/, audit/night-7of10 and the run manifests.
- New renders of the demo model: against its own keyframes, from a new viewpoint, and a
  shaded comparison with the depth prior.
- Charts checked with the dataviz palette validator (six hues pass; three are under 3:1
  contrast, so every chart has a legend or labels and a table beside it).
- Paper written under the humanizer rules: no em or en dashes, none of the banned words,
  first person plural, sentence-case headings.
- Every figure checked against its source, including four corrections found on review:
  Kolu's 3.5 mm is model units (1.9 cm calibrated), Village's heights are model units, the
  "77% in densification" belonged to a different Kolu run, and an unrecorded SSIM was
  marked n/r instead of guessed.
- Section 7.5 and Table 6 updated with the Poisson and gap-fill result from 8d97f9d.
- docx validated (the skill's validate.py passes) and exported to PDF through Word, all
  18 pages looked at.
- Commits cd5f77f, ea3a9b9, 785d191, 2914563 with codemap entries. Nothing pushed.

## Left, and what only the owner can settle

1. **Team names.** The title block reads "Team Tesseract [add member names]".
2. **Rights to the demo clip.** It's third-party footage with a StrudwickDroneService
   watermark, and the paper prints its frames. Confirm it may be published, or swap
   figures 4 to 9 for B3 renders.
3. **Where Kolu and Village came from.** No credit is given for them because the repo
   doesn't record the source. Nicosia is credited (CC BY 3.0).
4. **Submission format.** If SIH wants a fixed template, page limit or PDF only, the
   content has to be moved into it. The paper is A4, Times New Roman 10.5 pt, single column.
5. **Team section.** No roles or contributions section, since nobody's roles are known.

## What would make it better

In order of how much each would change the paper:

1. **One real single-pass clip with GPS, ideally RTK or PPK, and surveyed ground** (LiDAR
   or a multi-pass survey). Accuracy is 30% of the score and every sub-metre figure is
   synthetic today. With it, R-O3 and R-O4 move from synthetic or partly to measured.
2. **A real ten-minute 30 fps clip**, run clean. R-O2 then rests on a run, not the
   615-700 s prediction.
3. **A DJI SRT with gimbal pitch** from a real flight, to show the focal correction on
   real footage. None of the 20 fixtures has one.
4. **The Poisson and gap-fill prior in the pipeline** (handoff item 1 in memory), then a
   clean demo-prior run inside 900 s. Update Table 6, section 7.6, Figure 9 and the
   limitation bullet from that run.
5. **Rerun B1 with SIH_ASSIMP set** so the example run itself writes all six formats (it
   wrote five; section 8.4 says so), and **rerun B5v** so Table 7 and Figure 10 use one run:
   the final night-b5v-final (547.1 s) folder was deleted, so the stage breakdown and
   reprojection come from codex-b5v-v3 (502.2 s), noted in the captions.
6. **Three or more B2 builds** to report coverage as a mean with a spread; it varies
   61-71% between identical runs.
7. **A baseline on the same clip**: MapAnything alone, and COLMAP incremental plus
   OpenMVS without our changes, scored by the same held-out check. Section 3 argues
   against both but there's no side-by-side table.
8. **An ablation table on B1**: bridging off, old pose path, fusion filter 2, sharpness
   0.5, no fill, no levelling, one row each, same held-out check. Most rows exist in
   research/10-12 but on different code states.
9. **A figure of the web workspace** measuring on the model (R-O6 and the 5% UI score have
   no picture).
10. **Check references**: the MapAnything arXiv id (2509.13414) and the SIH problem
    statement's exact title are from memory, not checked against a source.
11. **Run the prose through ZeroGPT** as the humanizer skill targets (under 10%). It
    hasn't been scored.
