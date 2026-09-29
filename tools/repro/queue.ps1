# Every run behind the paper's tables, one after another on one GPU (README.md here).
# Each job logs to out/exp/q-<name>.log and adds one line to out/exp/queue.log.
# It stops before a job when C: has under 101.5 GB free.
#
#   powershell -File tools/repro/queue.ps1 [first job index]
#
# Tool paths: set SIH_COLMAP, SIH_OPENMVS and SIH_ASSIMP first, or edit the three lines below.
param([int]$from = 0)
$ErrorActionPreference = "Continue"
if (-not $env:SIH_COLMAP) { $env:SIH_COLMAP = "C:\Users\Kartik\gpu-tools\colmap\bin\colmap.exe" }
if (-not $env:SIH_OPENMVS) { $env:SIH_OPENMVS = "C:\Users\Kartik\gpu-tools\openmvs_cuda" }
if (-not $env:SIH_ASSIMP) { $env:SIH_ASSIMP = "C:\Users\Kartik\gpu-tools\assimp\Release" }
$env:HF_HUB_OFFLINE = "1"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
New-Item -ItemType Directory -Force out/exp | Out-Null
$S = "tools/repro"
$jobs = @(
  # Section 7 and the site's b1 model: the demonstration clip, plain and with the depth prior.
  @("b1", "python tesseract.py run 'SIH DEMO.mp4' --geometry local --horizon crop --name night-b1-final --no-resume; python tesseract.py verify out/runs/night-b1-final; python tools/view_check.py out/runs/night-b1-final --build --scale 1"),
  @("b1-prior", "python tesseract.py run 'SIH DEMO.mp4' --geometry local --horizon crop --name demo-prior2 --config tools/repro/prior.json --no-resume; python tesseract.py verify out/runs/demo-prior2"),
  # Section 8: the synthetic flights with truth, then the Nicosia pan three times.
  @("b3", "python tesseract.py run data/test_flight.mp4 --telemetry data/test_flight.SRT --geometry local --name night-b3-final --no-resume; python tesseract.py verify out/runs/night-b3-final; python tools/b5v_truth.py out/runs/night-b3-final --frames 600"),
  @("b5v", "if (-not (Test-Path out/codex/b5v.mp4)) { python src/ingest/make_test_video.py out/codex/b5v.mp4 --seconds 600 --fps 1 }; python tesseract.py run out/codex/b5v.mp4 --telemetry out/codex/b5v.SRT --geometry local --name night-b5v-2 --no-resume; python tesseract.py verify out/runs/night-b5v-2; python tools/b5v_truth.py out/runs/night-b5v-2"),
  @("b2-rep1", "python tesseract.py run data/nicosia_1080p.mp4 --geometry local --horizon crop --name b2-rep1 --no-resume; python tools/view_check.py out/runs/b2-rep1 --build --scale 1"),
  @("b2-rep2", "python tesseract.py run data/nicosia_1080p.mp4 --geometry local --horizon crop --name b2-rep2 --no-resume; python tools/view_check.py out/runs/b2-rep2 --build --scale 1"),
  @("b2-rep3", "python tesseract.py run data/nicosia_1080p.mp4 --geometry local --horizon crop --name b2-rep3 --no-resume; python tools/view_check.py out/runs/b2-rep3 --build --scale 1"),
  # Table 7, the baselines. All of these read night-b1-final's keyframes and poses.
  @("cl-sparse", "python $S/classical.py sparse"),
  @("cl-def", "python $S/classical.py dense cl-def defaults"),
  @("cl-defns", "python $S/classical.py dense cl-defns defaults_ns"),
  @("cl-ours", "python $S/classical.py dense cl-ours ours"),
  @("ma-alone", "python $S/ma_alone.py ma"),
  # Table 8, the ablation: the control, then one option changed per row.
  @("ab-control", "python $S/ablate.py control"),
  @("ab-prior", "python $S/ablate.py prior geometry_prior=1"),
  @("ab-fusion2", "python $S/ablate.py fusion2 dense_fusion_filter=2"),
  @("ab-sharp05", "python $S/ablate.py sharp05 texture_sharpness=0.5"),
  @("ab-smooth01", "python $S/ablate.py smooth01 texture_smoothness=0.1"),
  @("ab-nofill", "python $S/ablate.py nofill texture_fill=0"),
  @("ab-nolevel", "python $S/ablate.py nolevel texture_level=0"),
  @("ab-mapanything", "python $S/ablate.py mapanything --solve pose_method=mapanything"),
  @("ab-nobridge", "python $S/ablate.py keyframes-nobridge; python $S/ablate.py nobridge --solve --kf out/exp/kf-nobridge")
)
for ($i = $from; $i -lt $jobs.Count; $i++) {
  $name, $cmd = $jobs[$i]
  $free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
  if ($free -lt 101.5) { "$(Get-Date -Format s) STOP before $name, C: $free GB free" | Add-Content out/exp/queue.log; break }
  $t = Get-Date
  Invoke-Expression "& { $cmd } *> out/exp/q-$name.log"
  $s = [math]::Round(((Get-Date) - $t).TotalSeconds, 1)
  "$(Get-Date -Format s) [$i] $name $s s, C: $free GB before" | Add-Content out/exp/queue.log
}
"$(Get-Date -Format s) queue done" | Add-Content out/exp/queue.log
