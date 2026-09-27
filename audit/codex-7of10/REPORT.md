# Audit result: route from 5/10 toward 7/10

This audit used saved outputs and CPU-only replays. **No new reconstruction or GPU benchmark was run.** The measured picture still supports the owner's 5/10 assessment. [FINDINGS.md](FINDINGS.md) has definitions and evidence; [RESEARCH.md](RESEARCH.md) compares technologies; [NEXTRUN.md](NEXTRUN.md) is the eight-hour instruction set.

| 7/10 scorecard | Now | Bar |
|---|---|---|
| B1 appearance | Patchwork; seam ratio 4.397, 3.35% orange face centroids, far houses shredded in saved view | No visible patchwork, large holes or shreds |
| B1 held out | 22.822 dB, SSIM 0.647, coverage 98.79% (prior full-size FINAL-B1) | >=23.3 dB, >=0.66, >=98% |
| No-pitch metric | B3 12.559 m median, 1.14% within 1 m; B5v 1.368 m, 10.39% (S5 replays) | Both <=1 m and >=75% within 1 m |
| Pitch metric | B3 0.394 m, B5v 0.346 m saved synthetic truth | Both <=0.5 m |
| Real focal | No independent check; real SRT fixtures generally lack gimbal pitch | Within 5% or flag disagreement |
| Speed | B1 264.49 s; B5v 502.23 s for 600 s source, R 0.837 | B1 <=300 s; B5v R <=1.0, no ladder step-down |
| Completeness | Six formats; B2 held-out coverage 72.40% | Six formats; B2 >=80% |
| Robustness | New S2 mixed-pitch error fixed; F19/F20 still open at S3 | No S1/S2, F19/F20 closed, SRT fixtures clean |
| Innovation | Pitch-based correction works on synthetic clips, not yet general on real SRT | One capability a judge sees quickly |

Three findings drive the next work:

1. **A silent scale error was real and is fixed.** Mixed gimbal pitches on a fixed-attitude clip made S5 choose `k=1.25326` when the test model needed 1.12. Commit `a5b2468` refuses inconsistent per-view corrections; its regression failed before and passes after. Without pitch, B3 still misses truth by 12.559 m despite about 0.126 m GNSS camera RMS.
2. **The visible defects have different mechanisms.** B1's seam colour step is 4.397 times its within-patch step. Constant-light B3 also has seams (3.096), so exposure alone is insufficient. B1's orange gaps are mainly textured faces with no assigned image (3.35% of face centroids); only 176 topology boundary edges were found. Far-field cloud density drops to 0.36% of sampled points at 8-16 model units, with a 78 degree median view angle. The horizon crop removes about 400 of 1080 top rows from every analyzed B1 view.
3. **A simple focal shortcut fails.** Removing pitch gives B3/B5v 12.559/1.368 m cloud median error. Converting the synthetic SRT's 24 mm to 1222 px as a naive full-frame 35 mm equivalent leaves 6.806/7.017 m in approximate offline replays. B2's 72.40% coverage concentrates misses at the ends of a distant pan; restoring the old 97% by reverting to the wrong focal would restore the wrong shape.

| Next experiment, in priority order | Predicted gain, not measured | Night slot |
|---|---|---:|
| 1. Correct RGB offsets per atlas patch, B1 full-size holdout | Seam ratio 4.397 toward <=2.5; B1 +0.1 to +0.5 dB possible | 1.5 h |
| 2. AnyCalib independent focal check, then gated B3/B5v trial | Flag >5% disagreement; no-pitch <=1 m remains unproven | 1.17 h |
| 3. Fixed-pose full-frame dense input with sky mask on B1 | More far-house support; +0.1 to +0.4 dB possible | 1.17 h |
| 4. Classify B2 misses, add dense sources only where parallax exists | 0-8 coverage points possible; 80% may be unreachable | 1.17 h |
| 5. Isolate OpenMVS seam solvers with atlas and convergence diagnostics | Identify black-atlas cause; no gain assumed until fixed | 0.67 h |

The owner needs to approve, for the **next run**, deletion of eight named regenerable superseded `out/runs/` folders (estimated 12.8 GB) and the 1,282,571,813-byte Apache-2.0 AnyCalib ONNX asset plus any required runtime (capped at 1 GB). The plan gives exact targets, SHA, licence, size caps and undo. No deletion, install or download happened in this audit. Its first step is a fresh held-out baseline; its last step is four clean runs, truth checks with and without pitch, fixed-camera screenshots and a before/after scorecard. A 7/10 claim waits for those numbers and the owner's visual comparison.
