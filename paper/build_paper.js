// Builds the research paper as a .docx from the figures in ./fig.
// Run `python paper/figures.py` and `python paper/charts.py` first, then `node paper/build_paper.js`.
const fs = require("fs");
const path = require("path");
const sizeOf = require("image-size");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, WidthType, ShadingType, BorderStyle, LevelFormat,
  Footer, Header, PageNumber, TabStopType, TableOfContents,
} = require("docx");

const FIG = path.join(__dirname, "fig");
const OUT = process.argv[2] || path.join(__dirname, "Tesseract-research-paper.docx");
const FONT = "Times New Roman";
const TEXT_W = 9026;           // A4 with 1 inch margins, in DXA
const INK = "1A1A1A", MUTED = "555555", RULE = "999999", HEAD_FILL = "E8EEF6";

// ---------- inline markup: **bold**, *italic*, `code`
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), font: "Consolas", size: (base.size || 21) - 2, ...base, }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const P = (text, opts = {}) => new Paragraph({
  children: runs(text), alignment: AlignmentType.JUSTIFIED,
  spacing: { after: 120, line: 276 }, ...opts,
});
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const BUL = (t) => new Paragraph({ numbering: { reference: "bul", level: 0 }, children: runs(t),
  alignment: AlignmentType.JUSTIFIED, spacing: { after: 60, line: 276 } });
const NUM = (t, ref = "num") => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(t),
  alignment: AlignmentType.JUSTIFIED, spacing: { after: 60, line: 276 } });
const CODE = (t) => new Paragraph({ children: [new TextRun({ text: t, font: "Consolas", size: 17 })],
  spacing: { after: 0, line: 240 }, shading: { type: ShadingType.CLEAR, fill: "F3F3F1", color: "auto" },
  indent: { left: 200 } });

let figN = 0, tabN = 0;
function figure(file, caption, widthFrac = 1.0) {
  figN += 1;
  const p = path.join(FIG, file);
  const dim = sizeOf(p);
  const wpx = Math.round(602 * widthFrac);
  const hpx = Math.round(wpx * dim.height / dim.width);
  const ext = path.extname(file).slice(1).replace("jpeg", "jpg");
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
      children: [new ImageRun({ type: ext === "jpg" ? "jpg" : "png", data: fs.readFileSync(p),
        transformation: { width: wpx, height: hpx },
        altText: { title: `Figure ${figN}`, description: caption.replace(/\*/g, ""), name: `fig${figN}` } })] }),
    new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 200, line: 252 },
      children: [new TextRun({ text: `Figure ${figN}. `, bold: true, size: 18 }), ...runs(caption, { size: 18 })] }),
  ];
}

const border = { style: BorderStyle.SINGLE, size: 4, color: RULE };
const borders = { top: border, bottom: border, left: border, right: border };
function table(caption, header, rows, widths, opts = {}) {
  tabN += 1;
  const total = widths.reduce((a, b) => a + b, 0);
  const scale = TEXT_W / total;
  const w = widths.map((x) => Math.round(x * scale));
  w[w.length - 1] += TEXT_W - w.reduce((a, b) => a + b, 0);
  const cell = (text, i, head) => new TableCell({
    borders, width: { size: w[i], type: WidthType.DXA },
    shading: head ? { fill: HEAD_FILL, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new Paragraph({ alignment: (opts.align && opts.align[i]) || AlignmentType.LEFT,
      children: runs(String(text), { size: 17, bold: head || undefined }) })],
  });
  return [
    new Paragraph({ spacing: { before: 160, after: 80 }, keepNext: true,
      children: [new TextRun({ text: `Table ${tabN}. `, bold: true, size: 18 }), ...runs(caption, { size: 18 })] }),
    new Table({ width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: w,
      rows: [new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, i, true)) }),
        ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, i, false)) }))] }),
    new Paragraph({ spacing: { after: 120 }, children: [] }),
  ];
}
const R = AlignmentType.RIGHT;

// ---------- content
const body = [];
const add = (...xs) => xs.forEach((x) => Array.isArray(x) ? body.push(...x) : body.push(x));

// Title block
add(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 120 },
  children: [new TextRun({ text: "Tesseract: georeferenced 3D models from a single-pass monocular drone video", bold: true, size: 34 })] }));
add(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
  children: [new TextRun({ text: "Team Tesseract  [Kartik Shirode, Mandar Wagh, Aditya Shiralkar, Adityaraj Shinde, Jiya Mehta and Sanika Sagavkar]", size: 22 })] }));
add(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
  children: [new TextRun({ text: "Smart India Hackathon 2026, problem statement SIH26158 (National Technical Research Organisation), Software, Drone/Robotics", italics: true, size: 19, color: MUTED })] }));
add(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
  children: [new TextRun({ text: "Research report, 29 September 2026", size: 19, color: MUTED })] }));

// Abstract
add(new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text: "Abstract", bold: true, size: 22 })] }));
add(P("Mapping a site from a drone normally means a planned grid of overlapping passes. After a flood, along a border or on a reconnaissance flight there is often one pass and one video. We present Tesseract, a pipeline that turns one monocular drone video from a single flight pass, plus the drone's GPS log when there is one, into a textured 3D mesh, a point cloud and a surface model in six exchange formats, in metres and on the map when the telemetry allows it. The design follows from measurements of the single-pass setting itself. A straight pass leaves rotation about the flight line unconstrained: an unrestricted similarity fit put the scene 267 to 311 m off whatever the GNSS class, RTK included, and fixing roll and pitch from gravity brought it to 0.041 m. On a straight pass at one attitude the focal length and the depth along the view axis can't be told apart, and we recover the missing number from the gimbal pitch in the flight log. Tesseract fits the camera with MapAnything, solves the poses with COLMAP's global mapper and builds the surface with OpenMVS, with a keyframe selector that never leaves gaps in the flight, repairs to the texture and an optional learned depth prior for buildings. It takes any clip that passes an admission screen, and we report it on six inputs, real and synthetic. On the demonstration clip (18.9 s, 177 keyframes) the model is built in 293 s on a laptop GPU and reproduces held-out frames at 24.6 dB PSNR and SSIM 0.71. With the optional depth prior on, the roofs, walls and the tree take their shape, the run takes 753 s and held-out frames score 24.4 dB with 98.5% coverage. On the same held-out views MapAnything alone scores 20.9 dB, and COLMAP with OpenMVS 18.7 dB after more than 1,200 s. A ten-minute synthetic flight with DJI-style telemetry runs end to end in 548 s against a 900 s budget, and its point cloud lies 0.34 m median from ground truth with 98.5% of it within 1 m. Accuracy on real footage against surveyed ground has not been measured yet, and we say where that leaves each target."));
add(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "Keywords: ", bold: true, size: 20 }),
  new TextRun({ text: "UAV photogrammetry, single-pass reconstruction, structure from motion, multi-view stereo, feed-forward 3D reconstruction, georeferencing, drone video", size: 20, italics: true })] }));

// 1
add(H1("1. Introduction"));
add(P("A textured 3D model of a place is useful long after the flight that made it. Planners measure heights and volumes on it, damage assessors compare it with a model from last year, and mission planners check lines of sight. Commercial photogrammetry gets such models from survey flights: a lawnmower grid at fixed altitude, 70 to 80 percent overlap in both directions, often ground control points. The problem statement behind this work, SIH26158 from the National Technical Research Organisation, asks for the same product from far less [21]. The input is one video from a single flight pass by a monocular drone camera, with the GPS track and flight metadata. The output has to be a georeferenced, metrically accurate, textured model, with 1 m spatial accuracy or better, in under 15 minutes for a 10-minute video, in OBJ, PLY, LAS, GeoTIFF, glTF or FBX, covering the whole visible scene, with a viewer."));
add(P("One pass changes the geometry of the problem. Fewer photos is the smaller part of it. The camera centres lie close to one line, so some directions are never constrained. Every surface is seen from one side and mostly from one angle. The focal length of a camera flying straight at one attitude can't be recovered from the images alone. Consumer GPS carries a bias that doesn't average out over a ten-minute flight. We measured each of these before building anything, and the measurements decided the design."));
add(P("Tesseract is the result. It accepts any drone clip, screens it for admissibility before spending GPU time, and then runs a staged pipeline under a time budget, stepping down a ladder of cheaper settings instead of failing when a stage overruns or breaks. Every run writes a manifest that says what it may claim: a length is called a metre only when GPS or a known object supports it, and each target is judged as met, not met or not measurable. This report describes the method and uses the clip supplied for the demonstration as a worked example from start to finish."));
add(P("Our contributions are these:"));
add(BUL("A measured account of what a single pass can and can't give: the straight-line degeneracy and its gravity fix, the consumer GNSS floor, the focal-length and depth ambiguity with a correction from the gimbal pitch, and the completeness ceiling (Section 4)."));
add(BUL("An input-agnostic pipeline that runs on one laptop GPU: learned camera intrinsics with global structure from motion, dense MVS, texture repair and an optional learned depth prior, with admission screening, content-addressed resume, a degradation ladder and three-valued verdicts (Section 5)."));
add(BUL("Two fixes that turned a layered, drifting model into a single ground surface: a keyframe selector that bridges stretches the quality gates reject, and poses from a global mapper with the MapAnything camera held fixed (Sections 5.2 and 7.3)."));
add(BUL("An evaluation on six inputs with held-out view rendering, ground truth where it exists, and timing against the 900 s budget, including a ten-minute clip end to end, with two baselines and an ablation on the demonstration clip (Sections 6 to 8)."));

add(figure("fig_pipeline.png", "The Tesseract pipeline. S3 runs locally on one GPU with MapAnything, COLMAP and OpenMVS. Stages S4 to S5b decide units and frame, and S8 turns the run's facts into verdicts on the six targets.", 1.0));

// 2
add(H1("2. Problem and targets"));
add(P("The binding targets appear only in the PDF linked from the portal listing. Table 1 gives them with the evaluation weights. Accuracy, completeness and speed make up 70% of the score and all three can be measured, so we built and unit-tested the evaluation harness before the pipeline it judges."));
add(table("Targets and evaluation weights from the SIH26158 problem statement [21].",
  ["ID", "Target", "Value", "Criterion", "Weight"],
  [["R-O1", "Reconstruction", "3D mesh or point cloud", "Reconstruction accuracy", "30%"],
   ["R-O2", "Processing time", "under 15 min for a 10-min video", "Model completeness", "20%"],
   ["R-O3", "Spatial accuracy", "1 m or better", "Processing speed", "20%"],
   ["R-O4", "Coverage", "entire visible scene", "Innovation", "15%"],
   ["R-O5", "Formats", "OBJ, PLY, LAS, GeoTIFF, glTF, FBX", "Scalability", "10%"],
   ["R-O6", "Visualisation", "web or desktop viewer", "User interface", "5%"]],
  [8, 16, 28, 22, 10], { align: [null, null, null, null, R] }));
add(P("The inputs are the video (mandatory), GPS (mandatory) and flight metadata; the IMU is listed as optional. No dataset had been released when this report was written, so every input used here is either public footage, a clip supplied for the demonstration, or a synthetic flight with known truth."));

// 3
add(H1("3. Related work"));
add(P("**Classical photogrammetry.** COLMAP's incremental structure from motion and its PatchMatch stereo are the reference open pipeline [1, 2], and OpenDroneMap wraps similar tools for survey imagery [15]. OpenMVS provides densification, meshing, mesh refinement and texturing on top of any calibrated reconstruction [4]. Global structure from motion solves all rotations and positions at once instead of adding images one at a time, and GLOMAP showed it can match incremental accuracy at a fraction of the time; COLMAP 4 ships it as the global mapper [3]. These tools expect overlapping survey imagery. On a forward-moving single pass the incremental mapper drifts and self-calibration of the focal length fails, which we observed directly (Sections 7.3 and 7.7)."));
add(P("**Feed-forward reconstruction.** DUSt3R and MASt3R regress point maps from image pairs [7, 8]. VGGT predicts cameras, depth and point maps for many views in one forward pass [6], but its licence forbids military, warfare and espionage uses, which rules it out for a technical intelligence customer. MapAnything takes images plus optional intrinsics, poses and depth, predicts metric geometry and is released under Apache 2.0 [5]. Its backbone is DINOv2 [20]. These models are fast and fill textureless ground smoothly, but on our clips the fine surface was a smooth interpolant and poses drifted between inference windows (Sections 7.3 and 8.4). We use MapAnything where it is strong, the camera intrinsics and a shape prior, and classical tools for poses and the surface."));
add(P("**Aerial feed-forward work and products.** Wu et al. ran DUSt3R, MASt3R and VGGT on photogrammetric aerial blocks and found them strongest on sparse, low-resolution sets, with completeness up to 50% above COLMAP, and weaker as resolution and block size grow; they read these models as a complement to SfM and MVS, not a replacement [25], which is how we use MapAnything. UAVFF3D is a benchmark of more than 170 thousand real UAV images for such models [26], and GeoFF3D anchors a feed-forward model to georeferenced camera positions, taking about five minutes for 2,000 images [27]. Both work on survey blocks, not on one video pass under a time budget. Video input on its own is no longer unusual. OpenDroneMap has read video with a DJI SRT file since 2023 [15], and DJI Terra added keyframe extraction from video and a rolling-shutter correction in July 2026 [28]. The accuracy these products state is for survey flights, 1 to 2 GSD horizontally with RTK [29]; we found no published figure from any of them for a single oblique pass."));
add(P("**Texturing and fusion.** Waechter, Moehrle and Goesele select one view per face and remove seams with a global colour adjustment [9]; OpenMVS implements a variant, and we re-implemented the levelling step because it fails in the build we use. Volumetric fusion of depth maps into a truncated signed distance field goes back to Curless and Levoy [10]; we use Open3D's implementation [11]."));
add(P("**Georeferencing.** Aligning a reconstruction to GNSS positions is a similarity fit [13], usually made outlier-tolerant with RANSAC [14]. Near-collinear camera centres make that fit degenerate [23]. Heights need a geoid model; EGM2008 is the current standard [12]."));

// 4
add(H1("4. What one pass can and can't give"));
add(P("We ran a set of controlled experiments on synthetic single-pass flights with known truth before building the pipeline. They are small, and each one changed the design."));
add(H2("4.1 The straight-line degeneracy"));
add(P("Collinear camera centres don't constrain rotation about their own line. A 7-degree-of-freedom similarity fit from the reconstructed cameras to the GPS track can therefore match the trajectory closely and still swing the scene about the flight line. In EXP-09 the full fit placed the trajectory within 0.042 m using RTK positions while the scene was 267 m off, and the error grew with distance from the flight line, from 216 m within 25 m of it to 725 m at 300 to 500 m. Better GPS didn't help. That is what a degeneracy looks like, since noise would have shrunk with better positioning (Figure 2). Roll and pitch aren't unknown in the real world: gravity fixes them. Restricting the fit to yaw, translation and scale collapsed the scene error to 3.7 m with consumer GNSS and 0.041 m with RTK. A gently curved flight also removed the problem (7.9 m against 367 m), which confirms the cause. So the IMU, listed as optional, isn't optional for a straight pass: a vertical reference has to come from somewhere, and Tesseract takes it from the gimbal attitude or from gravity estimated from the camera track."));
add(figure("chart_degeneracy.png", "Scene RMSE after aligning a straight single pass to GNSS (EXP-09, synthetic, log scale). The full similarity fit leaves the scene hundreds of metres off with any GNSS class; the gravity-constrained 5-DOF fit reaches the 1 m target only with RTK.", 0.82));
add(H2("4.2 The consumer GNSS floor"));
add(P("EXP-05 simulated 40 trials of a 600 s pass per GNSS class, with 2% wild fixes. Consumer GNSS gave 4.1 m 3D RMSE, SBAS 1.9 m and RTK 0.097 m. Vertical error was about 1.7 times the horizontal. More keyframes didn't help: the error stayed near 4 m from 50 to 2400 keyframes, where independent noise would have fallen to 0.6 m (Figure 3). The bias of a consumer receiver is correlated over the flight. Absolute accuracy of 1 m is therefore a question of the positioning hardware, and we report shape accuracy and absolute accuracy as separate numbers. The same experiment showed two reporting traps. A residual against the GPS track itself double-counts the GPS noise, and error after best-fit alignment absorbs the whole georeferencing offset (0.209 m aligned against 2.679 m absolute on the same run)."));
add(figure("chart_gnss.png", "Absolute error with consumer GNSS against the number of keyframes in the fit (EXP-05, synthetic). The measured error is flat; the 1/sqrt(N) curve is what independent noise would give.", 0.82));
add(H2("4.3 Focal length and depth"));
add(P("On a straight pass at one attitude, a camera with focal length f and a scene stretched by a factor k along the view axis reproject identically to focal length k f and the true scene. The GNSS fit can't separate them either, because the camera centres sit on the same track in both cases. What remains is a vertical offset of the whole model, roughly (k - 1) times half the flying height at a 60 degree pitch. Table 2 shows it on two synthetic flights with DJI-style telemetry. Letting bundle adjustment refine the focal length made one case better and the other worse, since nothing in the images constrains it."));
add(table("Focal length against height error on synthetic straight passes (true focal length 1066 px).",
  ["Run", "Focal length used", "Ground offset", "Cloud error, median"],
  [["test flight, MapAnything value held", "1414 px", "-12.7 m", "12.6 m"],
   ["test flight, refined by the mapper", "1179 px", "-5.2 m", "5.2 m"],
   ["ten-minute flight, held", "1091 px", "-1.3 m", "1.4 m"],
   ["ten-minute flight, refined", "1160 px", "-4.6 m", "4.5 m"]],
  [40, 20, 18, 22], { align: [null, R, R, R] }));
add(P("The stretch does change one observable: the angle between each view and the track. With tan(model pitch) = tan(true pitch) / k, a gimbal pitch recorded in the flight log gives k directly. Tesseract stretches the model by 1/k along the mean view axis and fits again (Section 5.6). Replayed on the saved outputs of the four runs in Table 2, the implied focal length came out at 1066.6 to 1067.3 px and the cloud error at 0.34 to 0.40 m. The catch is that none of the 20 real DJI telemetry files we collected records a gimbal pitch, so on most consumer clips accuracy still rests on MapAnything's focal length."));
add(H2("4.4 Scale without GPS"));
add(P("Early runs took metric scale from the learned model. An audit against objects of published size on the Kolu clip (lane width 3.5 to 3.75 m, an ecoduct waist of 21 to 22 m) found that model 5.3 to 5.8 times too small, and the plausibility check that had accepted it only tested internal consistency. On the synthetic flights MapAnything's own scale was about 40 times too small (1.49 and 1.59 m per unit against 63.6 and 64.1 from GNSS). Tesseract therefore has no global scale constant. A run is in metres only with GNSS or a calibration from one known length, and otherwise every length is labelled as model units."));
add(H2("4.5 The completeness ceiling"));
add(P("EXP-08 rendered a synthetic town with 26 buildings from several pass geometries. Inside the overflown corridor, terrain reached 99 to 100% coverage even straight down, but facades facing along the track were 14.3% visible from a nadir camera and 52.0% at 60 or 45 degrees; forward tilt stops helping once those facades are in view. Cross-track facades are seen only through the edges of a wide lens. One pass sees one side of every building. We report completeness against what the flight could observe and separately against the whole scene, and faces no photo saw are marked as filled, not measured."));
add(H2("4.6 Operating constraints"));
add(P("Three constraints outside the maths also shaped the system. The DST geospatial guidelines of 15 February 2021 require finer-than-threshold data to be stored and processed in India [18], so cloud work runs only in the Mumbai region, where no GPU quota was available; the pipeline therefore targets one local GPU. Geoid separation across India runs from -24.3 m to -98.2 m, and EGM96 and EGM2008 differ by 1.68 m at Amritsar, so heights use EGM2008 and the code raises an error if the grid is missing instead of silently returning unchanged heights. UTM has a scale error of about 0.6 m per km across India, so fits are done in local east-north-up coordinates and projected last."));

// 5
add(H1("5. Method"));
add(P("Figure 1 shows the pipeline. Stages S0 to S8 are wrapped by an orchestrator that owns resume, the time budget and the degradation ladder. The same code runs on every input; what changes is what the input allows the run to claim."));
add(H2("5.1 Admission and ingest (S0, S1)"));
add(P("S0 samples about 140 frames and accepts or rejects the clip before any GPU time is spent. It rejects when the horizon shows in over 30% of frames, the median sky fraction is above 0.15, or the longest continuous shot is under 8 s. A clip that shows the horizon can be admitted with the sky cropped off instead. The sky, horizon and overlay tests run below letterbox bars; an early version anchored the sky test on a black bar and accepted a clip with the sky in every frame. Of four candidate public clips screened this way, two were rejected (sky in 19% and 60% of the frame), one was accepted and one was accepted once the horizon crop was allowed."));
add(P("S1 decodes with PyAV, scores about 15 frames a second at quarter scale with OpenCV, and selects keyframes. It keeps the longest shot, crops static overlays such as watermarks, and cuts at edits found by histogram correlation or by a jump in optical flow over six times the median, which caught a hidden cut in the Nicosia clip. Keyframes are placed by a baseline budget on DIS optical flow [16], with sharpness, sky and slate gates. The gates only express a preference. If no frame passes them within 1.5 flow budgets, the sharpest usable frame past one budget is taken anyway, so the flight never has a hole (Section 7.2). On long clips the budget is widened until the keyframe target reaches the end of the shot. DJI SRT telemetry is matched to keyframes by frame counter, then by timestamp, and interpolated between 1 Hz fixes. On a ten-minute 1080p file S1 takes 55 s and peaks at 6.0 GB of memory."));
add(H2("5.2 Camera and poses (S3a)"));
add(P("MapAnything runs on a spread subset of 60 keyframes only to fit one shared pinhole camera; on the demonstration clip its fit residual is 0.16 px. COLMAP then extracts 4096 SIFT features per keyframe [17] with that camera fixed, matches each keyframe with its neighbours (30 for the mapper, plus far pairs at quadratic spacing), and the global mapper solves every pose at once with focal length and principal point held. Its final retriangulation pass is off, since it cost half the mapper's time and moved the cameras further from the true path on a synthetic check (0.66 m against 0.31 m RMS). Points over 4 px of reprojection error are filtered before a gate that requires at least half the views registered and a mean error of at most 1 px."));
add(P("The focal length is refined only when the views turn by at least 30 degrees (measured on each third of the clip), because below that it is unobservable (Section 4.3). A pan through 63 degrees, as in the Nicosia clip, does constrain it: refinement moved it from 751 to 1400 px and turned a thin curved strip into the fan of ground a pan actually sees."));
add(H2("5.3 Dense surface and mesh (S3b, S3c)"));
add(P("OpenMVS densifies at resolution level 1 with a 320 px minimum, 5 neighbour views per depth map and fusion across 3 views. Two defaults had to change. The region-of-interest estimate assumes a Z-up scene and trimmed the far field, so it is off. The default fusion filter kept 160 thousand points out of 52 million depths on the demonstration clip while the depth maps were 90 to 96% valid; the plain filter keeps 7.9 million. ReconstructMesh then builds the surface with a minimum point spacing of 4 px."));
add(H2("5.4 Texture (S3d)"));
add(P("TextureMesh decimates the mesh to 20% and builds one atlas. Its default unsharp mask added contrast the photos never had, and turning it off with a higher smoothness ratio (fewer, larger patches) raised the held-out score by 1.6 dB (Table 5). Faces that no photo saw used to point at a single orange texel; `texture_fill` gives each its own cell painted from the nearest dense points. Seams are then levelled by our own implementation of the global colour adjustment of Waechter et al. [9]: one RGB offset per patch corner, solved so both sides of every border agree and spread smoothly over each patch. OpenMVS's own levelling blackens most of the atlas in the Windows build we use."));
add(H2("5.5 Optional depth prior"));
add(P("From far away and at one angle, photometric depth on buildings is noise, and roofs and walls melt into lumps. With `geometry_prior` on, each keyframe is cut into 3 overlapping tiles of MapAnything's 518 x 434 grid, and MapAnything runs on windows of 8 consecutive views with the solved poses and intrinsics given as inputs. A coarse ratio field (per 48 px cell, the median of MVS depth over network depth) corrects each depth map to the MVS mesh, so the metric shape comes from the photos and the detail from the network. All tiles are fused in a TSDF with Open3D [10, 11], plan-view holes behind buildings are closed with MVS faces, and the fused surface is remeshed with screened Poisson [24] and trimmed back to it, which removes the thin ribbons a TSDF leaves at grazing range. OpenMVS RefineMesh pulls the result back onto the photos. MVS faces then fill any ground the prior left empty, both where nothing of the prior lies above it in plan and where it lies below a crown the prior kept. Network depth is used out to 1.55 times the median depth and only the MVS surface beyond it, and tiles go on every third keyframe. The prior adds about 460 s on the demonstration clip, so it is off by default and switched on for clips short enough to afford it."));
add(H2("5.6 Scale, levelling and georeferencing (S4, S5, S5b)"));
add(P("The scale service decides what a run may call a metre: a GNSS fit, else a known-length calibration listed for that run, else model units. With telemetry, S5 levels the model, fits the SRT fixes to the cameras (keyframe i to camera i) with yaw, translation and scale free and roll and pitch fixed, and writes the result in local east-north-up metres about the first fix, heights above take-off. A full 7-DOF fit is refused. With 8 or more fixes carrying a gimbal pitch between 15 and 75 degrees down and views turning less than 10 degrees, it computes k from the pitch, stretches the model and fits again; it rejects the correction when the spread of per-view focal scale exceeds 5%. Without telemetry S5b levels the model from the camera track's gravity estimate and the run stays in model units."));
add(H2("5.7 Export and viewing (S6)"));
add(P("S6 writes the textured mesh as OBJ, GLB and FBX next to the cloud's PLY and LAS and a GeoTIFF surface model, all through the same transform, and reads each back. The web workspace (Figure 13) opens a run from disk. It moves along the pass like a map, and it measures on the surface by ray casting against the mesh: distance, height, area, cut and fill volume, profile, line of sight and coordinates, exported as GeoJSON and CSV. A detail layer colours the surface by how much ground one photo pixel covers there, so nobody measures the far field as if it were the near field."));
add(H2("5.8 Orchestration and verdicts"));
add(P("Each stage has a content-addressed key over its version, configuration, input hashes and the upstream key, so a re-run reuses exactly what hasn't changed. The orchestrator tracks a 900 s budget. A stage that overruns or fails steps the run down one level of the ladder (L0 full quality to L5 screen only) and restarts from the first stage that the new level changes; a sparse failure is replayed, not recomputed. Every run ends with a manifest and a QA report even when a stage crashes. S8 judges each target as met, not met or not measurable: time is met only for a timed, uncached video of at least 10 minutes, and accuracy is not measurable without ground truth. The pipeline carries 46 contract checks, 21 metric checks and a browser test in continuous integration."));

// 6
add(H1("6. Experimental setup"));
add(P("All local runs used one laptop: Intel i7-13650HX (14 cores), 24 GB RAM and an RTX 4060 Laptop GPU with 8 GB, on Windows 11, with COLMAP 4.2.0 (CUDA), OpenMVS 2.4.0 (CUDA) and the Apache-licensed MapAnything checkpoint in bf16. MapAnything takes 4.62 GiB of the 8 GB for its weights. Two earlier clips ran on the Cloud Run CPU path (8 vCPU, Mumbai) before the local pipeline existed; they are marked as such. Table 3 lists the inputs."));
add(table("The inputs. B1 is the worked example in Section 7.",
  ["ID", "Input", "Length", "Kind", "Telemetry", "Truth", "What it tests"],
  [["B1", "Demonstration clip, construction site", "18.9 s", "real", "none", "none", "the full model; held-out views"],
   ["B2", "Nicosia, long-lens pan over a city (CC BY 3.0)", "40 s", "real", "none", "none", "a pan, a hidden edit, far field"],
   ["B3", "Synthetic test flight with DJI-style SRT", "20 s", "synthetic", "SRT with gimbal pitch", "surface", "georeferencing and accuracy"],
   ["B5v", "Synthetic ten-minute flight, 1 fps, 600-record SRT", "600 s", "synthetic", "SRT with gimbal pitch", "surface", "R-O2 at full length"],
   ["Kolu", "Survey pass over a highway ecoduct", "52.1 s", "real", "none", "objects of known size", "MVS against feed-forward; scale audit"],
   ["Village", "Short cinematic sweep", "57 s", "real", "none", "none", "MVS against feed-forward"]],
  [6, 28, 8, 9, 14, 10, 25], { align: [null, null, R, null, null, null, null] }));
add(P("**Held-out views.** Every tenth keyframe is kept out of densification and texturing but keeps its pose. The textured mesh is rendered into those cameras and scored against the real frame on the pixels it covers (PSNR and SSIM [19]), with coverage of the whole frame reported beside it. Two identical runs on B1 differed by 0.02 dB. **Shape.** On clips without truth: the share of sparse points on one ground plane, the share of ground cells whose dense heights spread over 10% of the flying height (layered cells), and the largest camera step over the median step. **Truth.** On B3 and B5v, camera centres against the true path and the dense cloud against the true surface. **Time.** Wall clock from the manifest, clean runs with no resume."));

// 7
add(H1("7. Worked example: the demonstration clip"));
add(P("The clip supplied for the demonstration is 1920 x 1080 H.264 at 30 fps, 18.9 s and 568 frames. It is one continuous oblique pass over a construction site with houses along its far edge, the camera about 23 degrees down, sky in the top of every frame, a burned-in watermark and 34 black rows above and below the picture (Figure 4). It carries no telemetry, so this model is in model units and not on the map; everything else about the run is what any clip goes through."));
add(figure("fig_keyframes.jpg", "Four of the 177 keyframes selected from the demonstration clip, after the horizon crop to 1920 x 595. The pass runs from a pond and spoil heaps (a) over the graded site (b, c) to the houses at its far end (d).", 1.0));
add(H2("7.1 Admission"));
add(P("S0 flagged the horizon, the sky and the watermark and admitted the clip with remedies instead of refusing it: the horizon is cropped off, leaving frames of 1920 x 595, and the watermark and letterbox bars are cropped. Cropping less would add sky, not houses, since the houses already sit at the top of the kept frame."));
add(H2("7.2 Keyframes without holes"));
add(P("The first model of this clip passed every gate (134 of 134 views registered, 0.44 px after bundle adjustment) and still looked wrong: seen from the side, the ground was three or four tilted sheets. The camera path had two jumps, 25 and 14 times the median step, exactly where the selector had skipped stretches. Frames 82 to 144 failed the sky gate because pale sand and haze scored 0.15 to 0.19 as sky, and frames 240 to 306 failed the blur gate because they were less textured, not blurred. With bridging (Section 5.1) the clip gives 177 keyframes, 42 of them bridged, and the largest gap fell from 66 frames to 6."));
add(H2("7.3 One ground surface"));
add(P("Closing the gaps made the path continuous but left the ground layered in 34% of cells. The old pose step stitched MapAnything's poses window by window, and the stitch scales between windows were 0.69, 0.61, 0.49 and 0.50. Long-range matches existed (150 verified matches between keyframes 30 apart) but triangulation against the drifted poses rejected them, so bundle adjustment only ever saw neighbours agreeing with neighbours. The incremental mapper with a free focal length curled the ground into a bowl (focal 576 px against MapAnything's 1100). The global mapper with the camera held put 82% of sparse points on one plane. Table 4 and Figure 5 compare the old and new pipelines on the same clip."));
add(table("The demonstration clip before and after the keyframe and pose fixes.",
  ["", "Old pipeline", "New pipeline"],
  [["Keyframes", "134", "177"], ["Largest keyframe gap", "66 frames", "6 frames"],
   ["Largest step / median step", "25.1", "2.2"], ["Sparse points on one ground plane", "0.47", "0.77"],
   ["Layered ground cells", "0.35", "0.06"], ["Mean track length", "4.5", "10.8"],
   ["Mean reprojection error", "0.44 px", "0.49 px"], ["Dense points", "931 thousand", "7.0 million"],
   ["Textured mesh", "none", "208 thousand faces"]],
  [46, 27, 27], { align: [null, R, R] }));
add(figure("fig_posefix.jpg", "Side view of the dense cloud with the camera path above it. (a) The old pipeline: holes in the keyframe chain and window-wise poses stack the ground in tilted sheets. (b) Gap-free keyframes and global poses give one continuous ground with the trees standing on it.", 1.0));
add(H2("7.4 Surface and texture"));
add(P("Table 5 traces the held-out score through the texture changes (n/r: not recorded). The largest gain came from turning off TextureMesh's sharpening. This wasn't the check being flattered by blur: the atlas keeps full resolution, and side by side the unsharpened render is the closer match to the held-out photo. The unseen-face fill removed the orange blotches without moving the score, since those faces are rarely in any photo, and seam levelling lowered the colour step across borders from 9.6 to 7.8 levels."));
add(table("Held-out view scores on the demonstration clip as the texture settings changed (every tenth keyframe held out).",
  ["Setting", "PSNR (dB)", "SSIM"],
  [["TextureMesh defaults (sharpness 0.5, smoothness ratio 0.1)", "22.82", "0.647"],
   ["Sharpness 0", "24.21", "0.696"], ["Sharpness 0, smoothness ratio 0.5", "24.42", "0.706"],
   ["+ unseen-face fill", "24.41", "n/r"], ["+ seam levelling", "24.65", "0.710"],
   ["Final clean run, end to end", "24.63", "0.709"]],
  [60, 20, 20], { align: [null, R, R] }));
add(P("The final run registered all 177 views at 0.49 px mean reprojection error with a mean track length of 10.6, produced 7.04 million dense points and a textured mesh of 214,550 faces, of which 3.3% no photo saw. Held-out views are covered at 98.77%. Figure 6 renders the model from the cameras of two keyframes, Figure 7 from a viewpoint no photo was taken from, and Figure 8 shows it in plan with contours from its own heights."));
add(figure("fig_pairs.jpg", "Photo (top) against the finished model rendered from the same camera (bottom), for keyframes 40 (left) and 100 (right). Grey marks ground outside the model.", 1.0));
add(figure("fig_novel.jpg", "The model from a new viewpoint, behind and above the camera at keyframe 60 and pitched further down. Roads, spoil heaps, the pond and the tree line hold their shape off the flight path; the white slivers at the tree edge are surfaces no photo saw.", 0.92));
add(figure("fig_sheet.jpg", "Plan view of the model as a map sheet: the flight path (black), contours drawn from the model's heights, and hatching over the 18% of the site that the photos saw only coarsely (one pixel covering over four times the median ground footprint).", 0.95));
add(H2("7.5 Buildings with the depth prior"));
add(P("The houses sit at the far edge of the pass, where one photo pixel covers 0.1 model units of ground against 0.003 under the flight, about 30 times coarser. There OpenMVS makes lumps. With the depth prior on, roofs come out as planes and walls as upright edges, and the tree near the start stands as a crown instead of a folded sheet (Figure 9). Held-out PSNR can't see this: a lumpy roof with the right texture renders almost the same as a flat one from a view next to the photos. What Table 6 does show is that the prior costs little photo agreement and some coverage, because the TSDF drops grazing surfaces that ReconstructMesh keeps. The first end-to-end run with the prior also showed holes and comb-like stripes where the fused surface breaks into ribbons at grazing range. Remeshing the fused surface with screened Poisson before refinement [24], then adding MVS faces wherever a plan-view cell has none of the prior's or has ground below all of it, removes both. With the settings the pipeline now uses, the experiment script scores 24.43 dB and SSIM 0.687 on the held-out views with 98.53% coverage (last row); through the pipeline itself they give 24.35 dB (Section 7.7)."));
add(table("Held-out scores with and without the depth prior, same poses.",
  ["Model", "PSNR (dB)", "SSIM", "Coverage", "Faces"],
  [["OpenMVS mesh (default)", "24.643", "0.709", "98.72%", ""],
   ["Prior, no far field", "24.441", "0.677", "90.73%", ""],
   ["Prior, far field from MVS, every view", "24.402", "0.680", "97.68%", "285,817"],
   ["Prior, tiles on every second view (option default)", "24.342", "0.678", "97.27%", "277,580"],
   ["Same, Poisson remesh and gap fill (experiment script)", "24.400", "0.687", "98.68%", ""],
   ["As in the pipeline: every third view, Poisson, fill under crowns", "24.429", "0.687", "98.53%", "445,638"]],
  [44, 14, 12, 14, 16], { align: [null, R, R, R, R] }));
add(figure("fig_prior.jpg", "The houses at the end of the pass from a close viewpoint. (a) Textured model. (b) The OpenMVS mesh, shaded without texture: roofs and walls are lumps. (c) With the MapAnything depth prior as the pipeline runs it: planar roofs and straight wall lines.", 0.8));
add(H2("7.6 Time"));
add(P("The clean run took 293.4 s. Screening and ingest took 7.4 s. Inside S3, MapAnything's load and camera fit took 41.9 s, SIFT 5.4 s, matching 7.1 s and the global mapper 56.4 s; densification took 51.4 s, meshing 38.3 s and texturing 52.8 s. Export of the six formats took 8.8 s. The run with the depth prior took 752.7 s, 420.9 s of it in the prior: MapAnything on the tiles 123.6 s, fusion 38.1 s, Poisson 15.2 s and RefineMesh 237.8 s. That fits this clip's budget but not a ten-minute clip's, which is why the prior stays off by default. A clip this short can't meet R-O2 by construction, since the target is written for a ten-minute video; S8 marks it not measurable."));

add(H2("7.7 Against baselines, and one change at a time"));
add(P("Table 7 puts Tesseract beside two baselines on the same keyframes and the same held-out views. We gave each the best settings a careful user would pick, not a strawman. COLMAP ran as its documentation suggests for video: one shared camera it calibrates itself, sequential matching and the incremental mapper. It placed all 177 views, but the mapper alone took 1,062 s, more than the whole budget, and it put the focal length at 592 px against MapAnything's 1,098, the curled ground of Section 7.3. With OpenMVS at its defaults the held-out views scored 8.97 dB, because seam levelling blackens the atlas in the Windows build we use (Section 5.4). With only that switched off they scored 18.68 dB, SSIM 0.329 and 73.2% coverage. Given COLMAP's poses, our own dense and texture stage reached 18.65 dB with 88.1% coverage, so the poses carry most of the 6 dB gap. MapAnything alone used its own stitched poses over four windows of 54 views, the most our 8 GB card holds, with per-view intrinsics fitted to its point maps, its points fused in the same TSDF as the depth prior and the same texturing. It is fast at 166 s and scores 20.86 dB with SSIM 0.354; its windows' stitch scales ran 0.64, 0.54 and 0.45, and the model drifts with them."));
add(table("Baselines on the demonstration clip: same keyframes, same held-out views. The baselines' times leave out screening and ingest.",
  ["Method", "PSNR (dB)", "SSIM", "Coverage", "Time"],
  [["Tesseract", "24.64", "0.709", "98.7%", "293 s end to end"],
   ["Tesseract with the depth prior", "24.43", "0.687", "98.5%", "753 s end to end"],
   ["MapAnything alone", "20.86", "0.354", "87.1%", "166 s"],
   ["COLMAP incremental, then Tesseract's dense stage", "18.65", "0.327", "88.1%", "1,213 s"],
   ["COLMAP incremental, OpenMVS defaults, seam levelling off", "18.68", "0.329", "73.2%", "1,238 s"],
   ["COLMAP incremental, OpenMVS defaults", "8.97", "0.013", "73.2%", "1,244 s"]],
  [46, 12, 10, 12, 20], { align: [null, R, R, R, R] }));
add(P("Table 8 turns off one change at a time, against a control run of the unchanged pipeline through the same script, which landed within 0.03 dB of the held-out figures in Tables 5 and 6. OpenMVS's default fusion filter is the largest single loss: it kept 163,566 points and left 7 of the 17 held-out views empty. The old pose path, MapAnything's windows triangulated and adjusted, costs 1.8 dB and layers the ground in 20% of cells against 6%. Sharpening costs 1.5 dB, the smoothness ratio and seam levelling 0.2 and 0.1 dB, and the unseen-face fill nothing measurable, as expected for faces no photo sees. Bridging surprised us. With the global mapper the ground stays one layer without it, so its part in the fix of Section 7.2 is the camera chain: without it the largest step is 19 times the median, and 38 views are missing where the gates had emptied stretches of the clip. Its held-out score can't be compared with the rest, since all 13 of its held-out frames come from stretches the gates accepted."));
add(table("One change at a time on the demonstration clip, every tenth keyframe held out. Layered is the share of ground cells whose dense heights spread over 10% of the flying height, step the largest camera step over the median one; rows without them reuse the control's poses. The old pose path is scored with its radial term dropped. *Different held-out frames (139 keyframes).",
  ["Change", "PSNR (dB)", "SSIM", "Coverage", "Layered", "Step"],
  [["None (control)", "24.62", "0.708", "98.9%", "0.058", "2.2"],
   ["Fusion filter 2 (OpenMVS default)", "22.33", "0.613", "36.4%", "", ""],
   ["Sharpening 0.5 (OpenMVS default)", "23.13", "0.657", "98.7%", "", ""],
   ["Smoothness ratio 0.1 (OpenMVS default)", "24.44", "0.699", "98.8%", "", ""],
   ["No unseen-face fill", "24.61", "0.709", "98.5%", "", ""],
   ["No seam levelling", "24.48", "0.704", "98.3%", "", ""],
   ["Old pose path (MapAnything windows)", "22.85", "0.546", "99.3%", "0.201", "2.1"],
   ["No keyframe bridging", "24.95*", "0.720*", "98.9%*", "0.060", "19.1"]],
  [40, 12, 10, 12, 12, 10], { align: [null, R, R, R, R, R] }));
add(P("**Repeatability and scale.** The control, rerun the next morning from the committed scripts (Appendix A), scored 24.626 dB against 24.620 and SSIM 0.7087 against 0.7082. The prior's last row in Table 6 came from an experiment script that fixed the median depth and textured separately; through the pipeline's own option the same settings give 24.35 dB, SSIM 0.683 and 98.62% coverage in 589 s. For scale, CityGaussian reports 21.55 to 25.77 dB and SSIM 0.778 to 0.813 on held-out views of the Mill-19 and UrbanScene3D aerial scenes [30]. Those views sit further from the training views than a held-out frame of a video does, so we give it as a range and not as a comparison."));

// 8
add(H1("8. Results across inputs"));
add(P("Table 9 summarises every input with the settings in force at the time of its run. The local runs use one code path and one set of defaults; the two CPU runs predate it."));
add(table("Results on all inputs. PSNR, SSIM and coverage are from held-out views; truth errors are cloud to true surface. B2's held-out scores are the mean of three builds in a row.",
  ["Input", "Keyframes, registered", "Reprojection", "Wall time", "Held-out", "Against truth", "Units"],
  [["B1 demo", "177, all", "0.49 px", "293.4 s", "24.63 dB, 0.709, 98.8%", "no truth", "model units"],
   ["B2 Nicosia", "209, all", "0.34 px", "282.6 s", "27.48 dB, 0.870, 70.2%", "no truth", "model units"],
   ["B3 test flight", "173, all", "0.89 px", "349.0 s", "", "0.391 m median, 95.4% within 1 m", "metres, georeferenced"],
   ["B5v ten minutes", "353, all", "0.80 px", "548.2 s", "", "0.344 m median, 98.5% within 1 m", "metres, georeferenced"],
   ["Kolu (CPU path)", "45, all", "1.73 to 0.37 px", "32 min 43 s", "", "scale audit, x5.54", "metres, calibrated"],
   ["Village (CPU path)", "42, all", "1.53 to 0.41 px", "18 min 03 s", "", "no truth", "model units"]],
  [15, 13, 13, 11, 19, 19, 13], { align: [null, null, R, R, null, null, null] }));
add(H2("8.1 Accuracy with telemetry"));
add(P("On B3 and B5v the whole chain runs as it would on a DJI clip with a gimbal pitch in its log: SRT parsing and interpolation, the gravity-constrained fit, the pitch correction and export in local metres. On the final B5v run the cameras land 0.138 m RMS from the true path and the cloud 0.344 m median from the true surface, with 98.54% of it within 1 m; the run before it gave 0.140 m and 98.56%. At the image centre one pixel covers 0.119 m of ground, so the cameras sit at 1.15 GSD and the cloud's median at 2.9 GSD, with an RMSE of 0.506 m. Pix4D states 1 to 2 GSD horizontally for RTK survey blocks [29], and the ASPRS standard now reports accuracy as RMSE on at least 30 independent checkpoints [31]. Ours is measured against a complete synthetic surface, not checkpoints: it shows the chain works, but it isn't yet evidence of that kind. B3 reaches 0.391 m and 95.35%; its pitch correction found k = 1.325 and an implied focal length of 1067.4 px against the true 1066. On the CPU synthetic harness the gravity-constrained fit gives 0.06 to 0.09 m with RTK over three seeds when handed a tilted and scaled reconstruction. These are synthetic results: they test the georeferencing and the focal correction, not the learned model on real imagery (Section 10)."));
add(H2("8.2 Speed"));
add(P("Figure 10 breaks the local runs into stages. On the short clips a fixed 60 to 100 s goes to loading MapAnything and to each tool's start-up, so they can't reach the target ratio at their own length. The ten-minute clip, B5v, runs in 548.2 s, 61% of the 900 s budget (547.1 s on the run before). A real 30 fps clip decodes 30 times the frames and can give 600 keyframes instead of 353; from the measured per-stage rates we predict about 615 to 700 s for it, and around 900 s for a pan like Nicosia whose tracks run 32 views, where the ladder would step down to L1. That prediction hasn't been run, because no real ten-minute clip was available. Before the local pipeline, the Kolu clip took 32 min 43 s on 8 CPU cores; MapAnything alone ran 6.4 to 8.1 s per view on CPU against 0.12 to 0.25 s on the laptop GPU."));
add(figure("chart_runtime.png", "Wall-clock time by stage for the local runs, clean with no resume. The second bar is the demonstration clip with the depth prior on; its mesh segment holds the prior's tiles, fusion, Poisson remesh and RefineMesh.", 1.0));
add(H2("8.3 Real clips without GPS"));
add(P("**Nicosia (B2)** is a long-lens cinematic pan through 63 degrees with a hidden edit at frame 558. Before the flow-jump cut detection every view registered at 0.47 px and the model was a bent strip across the edit (largest step 112 times the median). With the cut and a refined focal length the pan becomes the fan of ground it really sees, held-out views score 27.48 dB and SSIM 0.870 on average over three builds in a row, whose coverage came to 69.3, 70.4 and 70.9%. Over six builds on the same settings coverage ran from 61.1% to 72.4%, mean 69.2% with a standard deviation of 4.1 points: a far scene seen from one spot has little parallax to densify, and the mapper and densification vary between runs."));
add(P("**Kolu and Village** compare the MVS surface with MapAnything's point map on the same poses. On both, the two agree within 2 to 4% at the largest neighbourhood and separate as the scale shrinks (Figure 11). MapAnything's residual flattens into a floor, the signature of a smooth interpolant, while the MVS surface keeps resolving fine structure, down to 1.9 cm in calibrated units on Kolu. On Village the learned point map had no point more than 1.5 model units above local ground, against structures visibly several times that tall, and MVS put 0.9% of the cloud above that height. Bundle adjustment cut the reprojection error from 1.73 to 0.37 px on Kolu, and the feed-forward poses really did carry error. On coverage, MVS added area on the well-textured Kolu pass (135% of the learned model's footprint) and lost some on Village's shadowed, textureless dirt (83%). MVS declines to invent surface it can't match. Figure 12 shows the Kolu model."));
add(figure("chart_kolu.png", "Median residual of a local plane fit against neighbourhood radius on the Kolu clip, same poses (log scales). The learned point map flattens below about 25 cm; the MVS surface keeps resolving fine structure.", 0.72));
add(figure("fig_kolu.jpg", "The Kolu clip on the earlier CPU path: fused point cloud and mesh from above, obliquely and at a low angle, plan coloured by height, and two cross-sections through the ecoduct.", 0.9));
add(H2("8.4 Exports"));
add(P("With the assimp library available, a local run writes all six formats (OBJ, GLB, FBX, PLY, LAS and GeoTIFF), each read back after writing; the demonstration run with the prior and B5v both did. On georeferenced runs the LAS and GeoTIFF carry an orthographic CRS about the first GPS fix. The demonstration clip's final clean run was started from a shell without the assimp path set and wrote five of six, and S8 said so. Run again with it set, the same clip wrote all six in 291.8 s against 293.4 s, with 214,506 textured faces against 214,550, so a clean run repeats closely."));
add(H2("8.5 Viewing and measuring"));
add(P("Figure 13 is the web workspace on the georeferenced test flight, B3, with a distance, a height and an area measured on the surface. Every tool casts rays against the textured mesh, so a reading is a length on the model and not on the screen, and on a run with GPS it comes out in metres with the latitude and longitude of each point. The same page opens the demonstration model in model units, where one known length sets the scale."));
add(figure("fig_workspace.jpg", "The web workspace on the synthetic test flight (B3), georeferenced: a 98.82 m distance, a 1.08 m height and a 1712 square metre area measured on the reconstructed surface, with the flight path, the camera at 7.0 s and the minimap.", 1.0));

// 9
add(H1("9. Standing against the targets"));
add(P("Table 10 states each target with the evidence behind it and the verdict the pipeline itself assigns. We have kept to the rule the verdict engine enforces: a target is met only where a run measured it."));
add(table("Status of each target. Synthetic evidence is labelled as such.",
  ["Target", "Status", "Evidence"],
  [["R-O1 mesh or point cloud", "met", "every run; textured mesh, dense cloud and DSM"],
   ["R-O2 under 15 min for a 10-min video", "met on a synthetic 10-min clip", "B5v 548.2 s on one laptop GPU; a real 30 fps clip is predicted at 615 to 700 s, not yet run"],
   ["R-O3 1 m spatial accuracy", "met on synthetic clips with gimbal pitch", "0.34 and 0.39 m median, 95 to 99% within 1 m; not measurable on real footage without surveyed ground; consumer GNSS alone limits absolute accuracy to about 4 m"],
   ["R-O4 entire visible scene", "partly", "98.8% of held-out pixels covered on B1 (98.5% with the depth prior), 69-71% on the Nicosia pan (61-72% over six builds); the back of any object is unseen by one pass and marked as filled"],
   ["R-O5 six formats", "met", "OBJ, GLB, FBX, PLY, LAS, GeoTIFF written and read back when assimp is present"],
   ["R-O6 viewer", "met", "web workspace with measurement tools, opens from disk"]],
  [24, 22, 54]));

// 10
add(H1("10. Limitations and future work"));
add(BUL("**No real clip with surveyed ground.** The sub-metre figures come from synthetic flights. They test georeferencing, the pitch correction and the whole chain, not MapAnything on real imagery, whose domain gap to our renderer is large. The next step is one real single-pass clip with RTK or PPK positions and a LiDAR or multi-pass reference."));
add(BUL("**No commercial tool on the same clips, and no rolling-shutter model.** DJI Terra now extracts keyframes from video and corrects rolling shutter [28], and OpenDroneMap takes video with an SRT file [15]. We haven't run either on our inputs. OpenDroneMap densifies with OpenMVS, the same family as our COLMAP baseline, so we expect it near that row of Table 7, but that is an expectation and not a measurement. Our cameras are modelled as global shutter, which fast flight with a consumer sensor will violate."));
add(BUL("**Gimbal pitch is rarely logged.** None of the 20 real DJI telemetry files we have records it, so on most consumer clips the height error is whatever MapAnything's focal length leaves: 2% (1.4 m) on B5v, 33% (12.6 m) on the H.264 encode of the test flight. A short turn or a second attitude during the pass would make the focal length observable."));
add(BUL("**Heights are above take-off.** The SRT gives nothing better. Orthometric heights need a known take-off elevation or a GNSS height with EGM2008, which the export path already supports."));
add(BUL("**Seams and the far field.** Seam levelling reduces colour steps but doesn't remove misregistration, and the far edge of an oblique pass is smeared because the photos there are smeared. The detail layer shows where."));
add(BUL("**The depth prior is slow.** It takes 421 s on the 18.9 s demonstration clip, and its tile inference and refinement grow with the keyframe count, so a ten-minute clip can't afford it inside the budget. Running it only on building regions is the obvious reduction."));
add(BUL("**No real ten-minute 30 fps run.** The timing for that case is a prediction from measured per-stage rates."));

// 11
add(H1("11. Conclusion"));
add(P("A single drone pass is a weaker input than a survey grid in specific, measurable ways, and most of them can be answered once they're named. Gravity removes the straight-line degeneracy. A logged gimbal pitch removes the focal-length ambiguity. Learned models are best used for what they do well, the camera and a shape prior, with photometric stereo kept for the surface. Tesseract takes a clip, decides whether it can be used, builds a textured model on one laptop GPU inside the time budget and states what each number rests on. On the demonstration clip that is a 214 thousand face model in under five minutes; on a ten-minute synthetic flight with telemetry, a georeferenced model in nine minutes with its cloud 0.34 m median from the truth. What it still needs is real footage with surveyed ground to measure itself against."));

// Data credits
add(H1("Acknowledgements and data"));
add(P("The Nicosia footage is from Wikimedia Commons under CC BY 3.0 (The Track Record - BTS) [22]. The demonstration clip was supplied for this work and carries a third-party watermark; its frames appear here only as the worked example. MapAnything is used under Apache 2.0; COLMAP (BSD) and assimp (BSD 3-clause) are used as released; OpenMVS (AGPL 3.0) is run unmodified as a separate process."));

// References
add(H1("References"));
const refs = [
  "J. L. Schönberger and J.-M. Frahm, \"Structure-from-motion revisited,\" in Proc. IEEE CVPR, 2016, pp. 4104-4113.",
  "J. L. Schönberger, E. Zheng, M. Pollefeys and J.-M. Frahm, \"Pixelwise view selection for unstructured multi-view stereo,\" in Proc. ECCV, 2016, pp. 501-518.",
  "L. Pan, D. Baráth, M. Pollefeys and J. L. Schönberger, \"Global structure-from-motion revisited,\" in Proc. ECCV, 2024, pp. 58-77.",
  "D. Cernea, \"OpenMVS: Multi-view stereo reconstruction library,\" 2020. [Online]. Available: https://cdcseacave.github.io/openMVS",
  "N. Keetha et al., \"MapAnything: Universal feed-forward metric 3D reconstruction,\" in Proc. Int. Conf. 3D Vision (3DV), 2026, arXiv:2509.13414.",
  "J. Wang, M. Chen, N. Karaev, A. Vedaldi, C. Rupprecht and D. Novotny, \"VGGT: Visual geometry grounded transformer,\" in Proc. IEEE/CVF CVPR, 2025, pp. 5294-5306.",
  "S. Wang, V. Leroy, Y. Cabon, B. Chidlovskii and J. Revaud, \"DUSt3R: Geometric 3D vision made easy,\" in Proc. IEEE/CVF CVPR, 2024, pp. 20697-20709.",
  "V. Leroy, Y. Cabon and J. Revaud, \"Grounding image matching in 3D with MASt3R,\" in Proc. ECCV, 2024, pp. 71-91.",
  "M. Waechter, N. Moehrle and M. Goesele, \"Let there be color! Large-scale texturing of 3D reconstructions,\" in Proc. ECCV, 2014, pp. 836-850.",
  "B. Curless and M. Levoy, \"A volumetric method for building complex models from range images,\" in Proc. SIGGRAPH, 1996, pp. 303-312.",
  "Q.-Y. Zhou, J. Park and V. Koltun, \"Open3D: A modern library for 3D data processing,\" arXiv:1801.09847, 2018.",
  "N. K. Pavlis, S. A. Holmes, S. C. Kenyon and J. K. Factor, \"The development and evaluation of the Earth Gravitational Model 2008 (EGM2008),\" J. Geophys. Res., vol. 117, B04406, 2012.",
  "S. Umeyama, \"Least-squares estimation of transformation parameters between two point patterns,\" IEEE Trans. Pattern Anal. Mach. Intell., vol. 13, no. 4, pp. 376-380, 1991.",
  "M. A. Fischler and R. C. Bolles, \"Random sample consensus: A paradigm for model fitting with applications to image analysis and automated cartography,\" Commun. ACM, vol. 24, no. 6, pp. 381-395, 1981.",
  "OpenDroneMap Authors, \"ODM: A command line toolkit to generate maps, point clouds, 3D models and DEMs from drone, balloon or kite images,\" 2020. [Online]. Available: https://github.com/OpenDroneMap/ODM",
  "T. Kroeger, R. Timofte, D. Dai and L. Van Gool, \"Fast optical flow using dense inverse search,\" in Proc. ECCV, 2016, pp. 471-488.",
  "D. G. Lowe, \"Distinctive image features from scale-invariant keypoints,\" Int. J. Comput. Vis., vol. 60, no. 2, pp. 91-110, 2004.",
  "Department of Science and Technology, Government of India, \"Guidelines for acquiring and producing geospatial data and geospatial data services including maps,\" 15 Feb. 2021.",
  "Z. Wang, A. C. Bovik, H. R. Sheikh and E. P. Simoncelli, \"Image quality assessment: From error visibility to structural similarity,\" IEEE Trans. Image Process., vol. 13, no. 4, pp. 600-612, 2004.",
  "M. Oquab et al., \"DINOv2: Learning robust visual features without supervision,\" Trans. Mach. Learn. Res., 2024.",
  "Smart India Hackathon 2026, \"Single-pass drone video to accurate 3D model generation system,\" Problem Statement SIH26158, National Technical Research Organisation, 2026.",
  "The Track Record - BTS, \"Central Nicosia drone footage overlooking UN buffer zone,\" Wikimedia Commons, 13 Jan. 2022, CC BY 3.0. [Online]. Available: https://commons.wikimedia.org/wiki/File:Central_Nicosia_drone_footage_overlooking_UN_buffer_zone.webm",
  "R. Hartley and A. Zisserman, Multiple View Geometry in Computer Vision, 2nd ed. Cambridge, U.K.: Cambridge Univ. Press, 2004.",
  "M. Kazhdan and H. Hoppe, \"Screened Poisson surface reconstruction,\" ACM Trans. Graph., vol. 32, no. 3, art. 29, 2013.",
  "X. Wu, S. Landgraf, M. Ulrich and R. Qin, \"An evaluation of DUSt3R/MASt3R/VGGT 3D reconstruction on photogrammetric aerial blocks,\" arXiv:2507.14798, 2025.",
  "X. Yang, Y. Wang, H. Li and Y. Zhang, \"UAVFF3D: A geometry-aware benchmark for feed-forward UAV 3D reconstruction,\" arXiv:2605.17942, 2026.",
  "X. Yang, Y. Wang, Y. Zhang, J. Li, H. Chen and H. Li, \"GeoFF3D: Coordinate-anchored feed-forward reconstruction for large-scale UAV mapping,\" arXiv:2608.28288, 2026.",
  "DJI Enterprise, \"DJI Terra latest update: Thermal 2D reconstruction, rolling shutter correction, and video-based 3D modeling,\" 31 Jul. 2026. [Online]. Available: https://enterprise-insights.dji.com/blog/dji-terra-thermal-rolling-shutter-update-july-2026",
  "Pix4D, \"What is the relative and absolute accuracy of drone mapping?\" Pix4D Support. [Online]. Available: https://support.pix4d.com/hc/en-us/articles/202558889 (accessed 29 Sep. 2026).",
  "Y. Liu, H. Guan, C. Luo, L. Fan, N. Wang, J. Peng and Z. Zhang, \"CityGaussian: Real-time high-quality large-scale scene rendering with Gaussians,\" in Proc. ECCV, 2024.",
  "American Society for Photogrammetry and Remote Sensing, \"ASPRS positional accuracy standards for digital geospatial data,\" Edition 2, Version 1.0, 2023.",
];
const refNums = refs.map((_, i) => i + 1);
refs.forEach((r, i) => add(new Paragraph({ spacing: { after: 60, line: 252 }, indent: { left: 520, hanging: 520 },
  children: [new TextRun({ text: `[${refNums[i]}]`, size: 19 }), new TextRun({ text: "\t", size: 19 }), new TextRun({ text: r, size: 19 })],
  tabStops: [{ type: TabStopType.LEFT, position: 520 }] })));

// Appendix
add(H1("Appendix A. Reproducing the runs"));
add(P("The tools are found through environment variables, and MapAnything runs offline once its weights are cached. The same three commands process any clip; `--horizon crop` admits clips that show the horizon."));
[
  "export SIH_COLMAP=/path/to/colmap SIH_OPENMVS=/path/to/openmvs",
  "export SIH_ASSIMP=/path/to/assimp HF_HUB_OFFLINE=1",
  "python tesseract.py run clip.mp4 --geometry local --horizon crop --name demo",
  "python tesseract.py verify out/runs/demo",
  "python tools/view_check.py out/runs/demo --build --scale 1",
  "python tools/pack_site.py out/runs/demo --id b1 --title \"Demo clip\"",
].forEach((c) => add(CODE(c)));
add(new Paragraph({ spacing: { after: 120 }, children: [] }));
add(P("A clip with a DJI SRT file beside it (same name, `.SRT`) is georeferenced automatically. The depth prior is switched on with the `geometry_prior` option of the local geometry provider. The experiments in Section 4 run from `src/experiments/` (EXP-01, 05, 08, 09), and their recorded output is in `research/`. Tests: `python src/tesseract/test_tesseract.py` and `python src/eval3d/test_metrics.py`."));
add(P("Every run behind Tables 5 to 10 is queued in `tools/repro/queue.ps1`, with the baselines and the ablation in `tools/repro/`. The recorded manifests and scores are under `audit/runs/` and `audit/overnight-2026-09-29/results/`, and `tools/repro/README.md` says what a rerun should match."));

// ---------- document
const doc = new Document({
  creator: "Team Tesseract",
  title: "Tesseract: georeferenced 3D models from a single-pass monocular drone video",
  styles: {
    default: { document: { run: { font: FONT, size: 21, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: FONT }, paragraph: { spacing: { before: 300, after: 120 }, outlineLevel: 0, keepNext: true } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, italics: true, font: FONT }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 1, keepNext: true } },
    ],
  },
  numbering: { config: [
    { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
    { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1300, right: 1440, bottom: 1300, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: "Tesseract: single-pass drone video to a georeferenced 3D model", size: 16, color: MUTED, italics: true })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: MUTED })] })] }) },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, figN, "figures", tabN, "tables"); });
