# Audit command log

Branch `codex-7of10`, 2026-09-27 to 2026-09-28. Commands ran from the repository root. All saved-output analysis was CPU only. Scratch is under `out/codex/7of10/`.

| Command or script | Why | Result | Output |
|---|---|---|---|
| `Get-PSDrive C`, `nvidia-smi --query-compute-apps`, HTTP GET port 8765 | Machine preflight | 106.13 GiB free; PID 2456 appears in GPU process list but process and memory are hidden by permissions; port 8765 did not answer | Phase 0 in `FINDINGS.md` |
| All 12 test commands in CONTEXT section 7 | Baseline gate | All pass: Tesseract 99 pass, 1 skip before the S5 change; JS 17 pass | Terminal output; summary in `FINDINGS.md` |
| `python out/codex/7of10/audit_saved.py` | Verify four manifests, focal decisions, export formats, atlas bytes, mesh/cloud transforms, UV seams, orange faces | Four runs checked; initial seam classification used UV IDs and gave no interior sample, so it was corrected to compare UV coordinates | `out/codex/7of10/audit_saved.json` |
| `python out/codex/7of10/audit_saved.py` | Repeat after correcting UV seam identity | B1 seam/interior step ratio 4.397; B3 3.096; B1 has 3.35% orange faces | `out/codex/7of10/audit_saved.json` |
| `python out/codex/7of10/audit_saved.py` | Repeat after adding orange-face count | B1 3.35%, B2 0.16%, B3 0.91%, B5v 1.10% face-centroid orange | `out/codex/7of10/audit_saved.json` |
| `python out/codex/7of10/recheck_truth.py out/runs/codex-b3-v2` | Recompute synthetic truth without changing saved run | 0.393 m cloud median, 95.28% within 1 m; mesh sampling makes the last digit vary | `out/codex/7of10/codex-b3-v2-truth.json` |
| `python out/codex/7of10/recheck_truth.py out/runs/codex-b5v-v3` | Same on long clip | 0.346 m cloud median, 98.55% within 1 m | `out/codex/7of10/codex-b5v-v3-truth.json` |
| `python out/codex/7of10/replay_no_pitch.py out/runs/codex-b3-v2` | Remove `gb_pitch` and replay S5 only | Correction skipped as intended | `out/codex/7of10/replay-no-pitch-codex-b3-v2/` |
| `python out/codex/7of10/recheck_truth.py out/codex/7of10/replay-no-pitch-codex-b3-v2` | Score the no-pitch S5 replay | 12.559 m cloud median, 1.14% within 1 m | `out/codex/7of10/replay-no-pitch-codex-b3-v2-truth.json` |
| `python out/codex/7of10/replay_no_pitch.py out/runs/codex-b5v-v3` | Remove `gb_pitch` and replay S5 only | Correction skipped as intended | `out/codex/7of10/replay-no-pitch-codex-b5v-v3/` |
| `python out/codex/7of10/recheck_truth.py out/codex/7of10/replay-no-pitch-codex-b5v-v3` | Score the no-pitch S5 replay | 1.368 m cloud median, 10.39% within 1 m | `out/codex/7of10/replay-no-pitch-codex-b5v-v3-truth.json` |
| `python tools/geometry_check.py out/runs/codex-b1-v2/geometry --out out/codex/7of10/b1-geometry` | Recheck B1 shape | Sparse on plane 0.78, layered cells 0.056, step ratio 2.2 | `out/codex/7of10/b1-geometry*` |
| `python tools/geometry_check.py out/runs/codex-b2-v2/geometry --out out/codex/7of10/b2-geometry` | Recheck B2 shape | Sparse on plane 0.795, layered cells 0, step ratio 2.3 | `out/codex/7of10/b2-geometry*` |
| `python out/codex/7of10/distance_bins.py` | Relate point density, triangle area and view angle to distance | B1 at 8-16 model units: 0.36% of sampled cloud, median angle 78 degrees | `out/codex/7of10/distance_bins.json` |
| `python src/tesseract/test_tesseract.py` after the new mixed-pitch test | Establish regression before fix | 99 pass, 1 fail, 1 skip; S5 applied k 1.253 to a fixed-attitude camera with inconsistent SRT | Terminal output; finding C1 in `FINDINGS.md` |
| `python src/tesseract/test_tesseract.py` after S5 guard | Verify fix | 100 pass, 0 fail, 1 skip | Terminal output; commit `a5b2468` |
| `python out/codex/7of10/replay_focal.py out/runs/codex-b3-v2 1222.0` | Test a naive 24 mm SRT to 35 mm equivalent focal conversion | Approximate depth stretch 0.8640, pitch omitted | `out/codex/7of10/replay-focal-1222-codex-b3-v2/` |
| `python out/codex/7of10/recheck_truth.py out/codex/7of10/replay-focal-1222-codex-b3-v2` | Score the focal replay | 6.806 m median, 1.10% within 1 m | `out/codex/7of10/replay-focal-1222-codex-b3-v2-truth.json` |
| `python out/codex/7of10/replay_focal.py out/runs/codex-b5v-v3 1222.0` | Same focal test on long clip | Approximate depth stretch 1.1201, pitch omitted | `out/codex/7of10/replay-focal-1222-codex-b5v-v3/` |
| `python out/codex/7of10/recheck_truth.py out/codex/7of10/replay-focal-1222-codex-b5v-v3` | Score the focal replay | 7.017 m median, 1.08% within 1 m | `out/codex/7of10/replay-focal-1222-codex-b5v-v3-truth.json` |
| Read-only `python -c` NumPy altitude probes of B3/B5v original and no-pitch replay `points_geo.npy`, plus camera transform | Check whether `rel_alt` alone names a ground plane | Camera z about 110 m, corrected cloud lower 5% around -5 m; no-pitch B3 lower 5% -17.96 m, B5v -6.22 m | Terminal output, interpreted in `FINDINGS.md` |

The read-only `python -c` probes inspected JSON keys, scores, texture histogram and source files. One histogram probe over the full atlas consumed too much memory and produced no result; a 1-in-16 pixel sample then located the orange atlas colour near RGB (240, 112, 32). A failed one-line copy of `b3_truth.py` had a quoting error; it made no output. Neither probe changed a saved run.
