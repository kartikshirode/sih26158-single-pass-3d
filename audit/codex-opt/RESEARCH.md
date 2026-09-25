# Options for the local GPU path

Checked 2026-09-26. This laptop has an RTX 4060 with 8 GiB VRAM, 24 GiB RAM,
COLMAP 4.2 with CPU-only Ceres and OpenMVS 2.4 CUDA. Gains below are predictions
unless a local run is named. They are not claims about the finale clip.

## Keyframes and crop

| Option | Likely gain and cost on this machine | Licence, risk and source | Test |
|---|---|---|---|
| Full frames with sky masks | May recover B1's smeared far field. The B1 horizon crop removes 37% of height, so full-frame depth has much more work and may spill 8 GiB VRAM. | COLMAP's `ImageReader.mask_path` is in this build. OpenMVS mask wiring needs proof in this version. COLMAP is BSD, OpenMVS AGPL. [COLMAP CLI](https://colmap.github.io/cli.html), [OpenMVS mask discussion](https://github.com/cdcseacave/openMVS/issues/144). | Same B1 timestamps, sky masked full images. Compare far-field render, held-out scores, coverage, peak VRAM and time. |
| Fewer keyframes | B1 has 177 views in 18.9 s and B2 has 289 in 40 s. This may cut mapper work, but a simple linear estimate is unsafe. | No new licence. Gaps can split a model or stack ground sheets, as research/10 showed. | A gap-bounded 2:1 subset on B1, then B2 and B3. Require all geometry and held-out gates. |
| Baseline-aware spacing | Could remove redundant views while retaining weak stretches. Optical flow is image displacement, not a true camera baseline. | No new licence. Discarding grazing views could make the far field worse. | Compare selected frame gaps, sparse tracks and held-out views on all clips. |

## Camera and poses

Keep the fixed MapAnything camera as the reference. COLMAP's [global SfM
guide](https://github.com/colmap/colmap/blob/main/doc/cli.rst) says the global
mapper needs a good focal prior. Earlier free-focal tests bent B1 into a bowl.

| Option | Likely gain and cost on this machine | Licence, risk and source | Test |
|---|---|---|---|
| Tune global mapper iterations and tracks | B1's mapper took 90.65 s; B2 took 329.32 s. Lower iteration limits may help, but could weaken the far field. | COLMAP BSD. B1's log shows CPU fallback because Ceres lacks CUDA and cuDSS in this binary. [COLMAP FAQ](https://github.com/colmap/colmap/blob/main/doc/faq.rst). | One option at a time, starting B1. Compare all-view registration, reprojection, shape, held-out scores and mapper time. |
| Try the BA backend exposed by this build | `global_mapper -h` lists `ba_backend`; whether another backend works on this Windows binary is unproven. | COLMAP BSD. Do not apply speed claims from another build. [COLMAP 4.2 release](https://github.com/colmap/colmap/releases). | First check that the binary accepts a backend and logs it. Then run B1 against the current best. |
| MapAnything positions as priors | Might help a long, weak clip. Its older stitched pose windows scaled by 0.69, 0.61, 0.49 and 0.50, so tight priors can impose the wrong shape. | Same Apache checkpoint and BSD COLMAP. `pose_prior_mapper` is incremental with position constraints, not a direct global initializer. [COLMAP pose prior FAQ](https://github.com/colmap/colmap/blob/main/doc/faq.rst). | Align windows first, use loose covariance, then check B1 and B2 shape and held-out images. |
| Split long models with overlap | Bounds BA size around 600 views, but the final merge may bring back window drift. | No new licence. Earlier window poses made stacked ground. | Time two overlapping long-clip halves and compare a joined model with one global mapper. |
| ALIKED with LightGlue | Could help low-texture matches. Matching is only 7.2 s on B1, so speed upside is small unless mapper convergence also changes. | This build lists ALIKED. COLMAP and [ALIKED ONNX](https://github.com/colmap/ALIKED-ONNX) are BSD; [LightGlue](https://github.com/cvg/LightGlue) is Apache. Check actual weight cards before use. | Compare verified tracks and S3b on a copied B1 database before any default change. |

## Dense cloud

| Option | Likely gain and cost on this machine | Licence, risk and source | Test |
|---|---|---|---|
| Resolution level 0 | More detail and perhaps fewer grazing holes. It could cost two to four times B1's 52.11 s dense stage and spill VRAM. | OpenMVS AGPL, still a separate process. [OpenMVS modules](https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Modules.md). | B1 peak VRAM, held-out score, coverage and far-field render. |
| Neighbour and fusion counts | More support may help thin surfaces, with more depth and fusion work. Current values are 5 neighbours and 3 views to fuse. Fusion filter 2 already failed here. | OpenMVS AGPL. Too much consistency filtering can erase the field. [OpenMVS usage](https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Usage.md). | One count at a time on B1; inspect depth support and shape. |
| Geometric passes and depth gate | Could remove grazing strips and raise covered-pixel PSNR, but may reduce coverage. | OpenMVS AGPL. Coverage must remain a separate guard. [OpenMVS modules](https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Modules.md). | Same held-out frames, both image scores and coverage, plus layered cells. |
| MapAnything depth seeds | Its point maps could fill a PatchMatch gap. OpenMVS accepts precomputed DMAP depth in its usage guide. | Apache checkpoint with AGPL process. An incorrect camera or scale could add layers. [OpenMVS usage](https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Usage.md). | Round-trip one depth map and project it into the camera before trying fusion. |

## Mesh and texture

| Option | Likely gain and cost on this machine | Licence, risk and source | Test |
|---|---|---|---|
| RefineMesh | May sharpen roofs and edges, but adds a full stage to runs already far over the short-clip budget. | OpenMVS AGPL. This Windows build's GPU support needs checking. [OpenMVS usage](https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Usage.md). | Refine B1's fixed mesh once, retexture it, compare held-out images and wall time. |
| Mesh spacing and texture decimation | Fewer triangles can save B1's 62.87 s mesh and 55.91 s texture. Current 10% texture decimation leaves about 207k faces. | OpenMVS AGPL. More decimation may lose small structures. | Change one value at a time and compare the same held-out views. |
| Atlas size and seam levelling | A larger atlas costs RAM. Levelling previously blackened 73% of B1 faces, so another blind toggle would repeat a failed experiment. | OpenMVS AGPL. Check image format, gamma and atlas texels first. [OpenMVS texture design](https://github.com/cdcseacave/openMVS/blob/develop/libs/MVS/README.md). | Reproduce one black patch from its source images, then test a specific cause. |
| Uncovered faces | B1 still shows orange holes. More suitable views may reduce them; painting a filler color only hides them. | No new licence. | Count unobserved faces and held-out coverage before and after. |

## Models

| Candidate | Fit, licence and source | Test |
|---|---|---|
| MapAnything Apache | Current [Apache checkpoint](https://huggingface.co/facebook/map-anything-apache). The weights use about 4.6 GiB and B1 peaked at 6.66 GiB. | Keep its intrinsics fit as the floor for another model. |
| Depth Anything 3 Small | [Apache 2.0 checkpoint](https://huggingface.co/depth-anything/DA3-SMALL), 0.08B parameters, depth and pose output. Its camera fit here is unknown. | Run the same 60 B1 views, check intrinsics and held-out depth reprojection. |
| Depth Anything 3 Base | Plausible only with MapAnything unloaded. Verify its own weight card licence and size before download. [Project source](https://github.com/ByteDance-Seed/Depth-Anything-3). | Same test as Small if the licence and 8 GiB limit clear. |
| VGGT, MASt3R, DUSt3R, UniDepth, Pi3 and non-Apache MapAnything | Barred from a product build by CONTEXT.md section 6. | Comparison in prose only. |

## Throughput

B1 loaded MapAnything weights in 16.2 s. Keeping them warm across clips could
remove that fixed cost, but it cannot close a roughly 294 s gap to B1's 28 s
scaled budget. CPU meshing and texturing might overlap independent GPU work
from another chunk once poses are final. The present subprocess chain depends
on each preceding artifact, so overlap needs a chunked design and a consistency
check. S1 was only 4.17 s on B1 and 51.51 s on the 600 s loop. The 600-view
sparse stress run spent 246.55 s in CPU global_mapper and failed registration
at 553/600 views. Its GPU was idle in 52 of 68 samples. More GPU capacity by
itself would leave that mapper cost and the registration failure untouched.

## Missing outputs

| Addition | Judged value and effort | Risk and test |
|---|---|---|
| Feed SRT GPS into S5 | High value: accuracy is 30% of judging and B3 has a sidecar. Medium to high effort. S1 parses it today, but S5 skips real video. | GPS errors, altitude datum and timestamp offset can make false metre claims. Use B3 truth and refuse unsupported altitude. |
| Levelled textured OBJ, GLB and FBX in `export/` | Medium value: R-O5 is 3 of 6. Medium effort. OpenMVS can write OBJ and GLB in its [usage guide](https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Usage.md). | A plain copy leaves the mesh in F4 while PLY is F5. Compare transformed vertices and atlas paths; FBX uses the existing assimp route. |

## Ranked experiments

1. Full frames with a sky mask on B1. Check far-field pixels, held-out views,
   coverage, VRAM and time.
2. Dense resolution level 0 on B1, with the same image and shape checks.
3. RefineMesh on B1, then retexture and score.
4. Fewer gap-bounded keyframes, then B2 and B3 if B1 survives.
5. Global mapper BA options and backend, with its actual log as evidence.
6. Mesh spacing or texture decimation, one value at a time.
7. SRT into S5 on B3, after the core geometry is stable.
8. Textured OBJ, GLB and FBX in the levelled export frame.
9. DA3 Small as a separate candidate after weight and licence checks.

B2's hidden cut and the 600-view registration failure are gates ahead of all
ranked tuning. A candidate stays only under the gates in PROMPT.md.
