# GCP deployment and the GPU question

Surveyed 2026-09-05 across every authed account. Short version: **there is exactly one
GPU path on this account, it is in the wrong jurisdiction, and it has the wrong billing
model for batch work.** The CPU pipeline stays the deployment; the Baramati cluster is
the answer for scale.

## 1. What was surveyed

Three credentials are authed locally: `roboticsblack@gmail.com`,
`mandarwagh90@gmail.com`, and a Firebase service account.

| account | projects | billing enabled |
|---|---:|---:|
| roboticsblack@gmail.com | 8 | **5** |
| mandarwagh90@gmail.com | 18 | **0** |

**The entire `mandarwagh90` account is unbilled**, and GPUs require billing, so all 18 of
its projects are out before quota is even considered. The five billed projects
(`agentbillboard`, `lore-brain-0618796`, `morph-0619-25202`, `powerhouse-0619`,
`project-6ee36aac-…`) all sit on **one** billing account, `01A2A6-9BB9D9-FFA99E`
("Black Robotics", under `organizations/495841369448`). They carry byte-identical quota,
because it is the untouched default allocation. Spinning up a sixth project changes
nothing.

## 2. GPU quota, by service

Checked through the Service Usage API rather than the console, so the numbers are the
effective limits the scheduler actually enforces.

| service | GPU quota | verdict |
|---|---|---|
| Compute Engine | `GPUS_ALL_REGIONS = 0`, every accelerator metric 0 | closed |
| Cloud Run | all four L4 / RTX Pro metrics 0 | closed |
| Vertex **training** | preemptible A100/V100/T4/P100/P4 = **1** per region | see below |
| Vertex **serving** | V100 / P100 / P4 / K80 = **1** per region | the only live path |

### Vertex training looks open and is not

The GPU quota is real — preemptible T4 in nine regions including **asia-south1**, A100 in
three. But every training job is refused before it starts:

```
The following quota metrics exceed quota limits:
aiplatform.googleapis.com/custom_model_training_preemptible_cpus
```

`custom_model_training_preemptible_cpus = 1` in every region. Vertex's smallest
GPU-capable machine is `n1-standard-4` (4 vCPU) — `n1-standard-1` is rejected outright as
"not supported". So the CPU quota is one quarter of the minimum viable shape.

Tested and confirmed refused: T4 spot in asia-south1 at 4 vCPU, the same at 1 vCPU
(machine type rejected), and A100 spot in all three of its regions. The `A2 CPU types`
and `G2 CPU types` quotas read `-1` (unlimited), which is misleading: `preemptible_cpus`
is a separate metric and binds first regardless of machine family.

Non-preemptible training GPU quota is 0 everywhere, so there is no way around it.

### Vertex serving is the one path where the numbers match

`Custom model serving CPUs = 8` — enough for `n1-standard-4` — and GPU quota is 1:

| accelerator | regions with quota |
|---|---|
| V100 | us-central1, us-west1, europe-west4 |
| P100 | us-central1, us-east1, us-west1, asia-east1, europe-west1 |
| P4 | us-central1, us-east4, us-west2, asia-southeast1, europe-west4, … |
| K80 | us-central1, us-east1, asia-east1, europe-west1 |

**There is no GPU quota of any kind in asia-south1.** Serving CPU quota exists there
(8), but no accelerator does.

## 3. Two reasons this path is still wrong for us

**Jurisdiction.** R-NF8 in the SRS: under the DST Geospatial Data Guidelines, data finer
than 1 m horizontal must be stored and processed in India. This PS targets 1 m. The
nearest GPU is asia-east1 (Taiwan) or asia-southeast1 (Singapore) — both outside India.
A GPU deployment on this account cannot be used for real NTRO data. It would be fine for
development on public footage, which is what the two clips here are.

**Billing model.** A Vertex prediction endpoint bills for every hour it is *deployed*,
not per request. An `n1-standard-4` + V100 in us-central1 is roughly **$2.67/hour**, so
about $1,900/month if left up. Our workload is intermittent batch reconstruction, which
is the shape a Cloud Run Job serves and an always-on endpoint serves badly. Deploy →
run → undeploy would work but adds minutes of endpoint churn to every job.

## 4. Quota increases are auto-blocked, and not only for GPUs

Every relevant quota reports the same ineligibility through the Cloud Quotas API:

```
CustomModelTrainingPreemptibleCPUsPerProjectPerRegion
  ineligibilityReason: NOT_ENOUGH_USAGE_HISTORY
CustomModelTrainingPreemptibleT4GPUsPerProjectPerRegion
  ineligibilityReason: NOT_ENOUGH_USAGE_HISTORY
CustomModelServingPreemptibleCPUsPerProjectPerRegion
  ineligibilityReason: NOT_ENOUGH_USAGE_HISTORY
```

This is worth recording precisely because it is broader than previously believed: it is
not a GPU-specific block. The **CPU** quota that actually stops us carries the same
reason, so there is no clever request that routes around it. Submitting one would be
auto-denied; the unlock is accumulated paid usage on the billing account over time, not
an argument in a request form.

## 5. Does the CPU pipeline actually meet the requirement?

Not at full scale, and this is the honest gap.

| | views | wall clock |
|---|---:|---:|
| Short | 42 | 18 min 03 s |
| Kolu | 45 | 32 min 43 s |

The PS budget is **15 minutes for a 10-minute video**. A 10-minute pass yields roughly
600 keyframes (the figure EXP-13 was designed around), which is ~13x Kolu's view count.
Densification dominates and scales close to linearly with views, so a full-length clip is
hours on 8 vCPU, not minutes. Cloud Run Jobs cap at 8 vCPU, so scaling up within Cloud
Run is not available either.

So: the CPU pipeline is the right *reproducible* deployment and it is what produced every
result in `docs/05-quality-analysis.md`, but it does not meet the speed criterion (20 of
100 marks) on a full-length input.

## 6. Recommendation

1. **Keep Cloud Run Jobs (asia-south1, 8 vCPU, CPU-only) as the deployment.** It is
   compliant, reproducible, costs nothing at rest, and is what the current results came
   from. `sih26158-mvs` and `kolu-ma` are already configured there.
2. **Use the Baramati HPC cluster for scaled runs.** It has real GPUs, it is inside
   India so R-NF8 is satisfied, and it is the only route that can meet the 15-minute
   budget on a 10-minute video. See the cluster's own `CONTEXT.md` — campus network
   only, and only the `torch-gpu` conda env runs on its cards.
3. **Do not spend effort on GCP GPU quota.** Requests are auto-denied at the API, the
   block covers CPU as well as GPU metrics, and the only reachable accelerator is outside
   India.
4. If a GPU is wanted purely for *development* speed on public footage, the cheapest
   honest option is a Vertex serving endpoint with a **P4** (roughly $0.60/hour plus the
   machine) in asia-southeast1, deployed and torn down per session — not left running.

## Reproduce

`deploy/vertex_gputest.yaml` and `deploy/vertex_a100test.yaml` are the probe configs that
produced the refusals in section 2. Quota reads:

```
gcloud auth print-access-token
curl -H "Authorization: Bearer $TOK" \
  "https://serviceusage.googleapis.com/v1beta1/projects/<P>/services/<SVC>/consumerQuotaMetrics?pageSize=500"
curl -H "Authorization: Bearer $TOK" \
  "https://cloudquotas.googleapis.com/v1/projects/<P>/locations/global/services/aiplatform.googleapis.com/quotaInfos?pageSize=500"
```

---

## 7. Sharding across Cloud Run tasks — measured, and it did not work as hoped

Built and ran (2026-09-05, Kolu, 45 views). **Result: 7% slower than the single task
it was meant to beat.** Recording it in full because the diagnosis is more useful than
the idea was.

| stage | shape | wall clock |
|---|---|---:|
| prep (SfM + global BA) | 1 task x 8 vCPU | 452 s |
| densify | 5 tasks x 4 vCPU | 1472 s |
| fuse | 1 task x 8 vCPU | 174 s |
| **total** | | **2098 s** |
| single-task baseline | 1 task x 8 vCPU | **1963 s** |

### Why 2.5x the cores bought 1.10x the speed

Per-shard densification: **990, 1454, 1243, 901, 719 s**. Three compounding problems.

1. **Redundancy.** Windows of 13-17 views with an overlap of 4 turn 45 views into
   **77 view-slots — 1.71x the work.** Overlap of 1 would give 53 slots (1.18x).
2. **Half the cores each.** 5 x 4 vCPU is 20 vCPU nominal, but OpenMVS scales well
   inside a task, so a 4 vCPU task is roughly 1.8x slower per view than an 8 vCPU one.
   Splitting into more, thinner tasks gives most of the nominal gain back.
3. **Load imbalance.** 719 s to 1454 s is a 2x spread, and a parallel stage costs what
   its *slowest* shard costs, not the average (1061 s). Equal view counts do not mean
   equal work: scene complexity varies along the pass.

### The geometry did hold, which validates the design

The claim that shards concatenate because one global bundle adjustment puts every
window in the same metric frame **is confirmed**: relief above local ground comes out
at max 3.33 m sharded against 3.31 m single-task, and the footprint matches. The frames
align. No stitching was needed and none was done.

But precision drops, because a view at a window edge has fewer neighbours to be
constrained against:

| radius | single task | sharded | |
|---:|---:|---:|---|
| 6 cm | **0.756 cm** | 0.913 cm | 21% worse |
| 12 cm | **1.487 cm** | 1.805 cm | 21% worse |
| 25 cm | **2.787 cm** | 3.143 cm | 13% worse |

So the sharded cloud is denser (4.01 M vs 3.45 M points) and *less* accurate — the extra
points are largely duplicated overlap that the voxel dedupe, sized at the native 0.97 cm
spacing, was too fine to merge.

### What would actually help

- **Fewer, fatter tasks.** 2 x 8 vCPU with overlap 2 gives 49 view-slots (1.09x) and
  ~885 s for the stage — a realistic **1.8x**, against the 1.10x measured here.
- **Balance by predicted cost, not view count**, or use more windows than tasks and let
  them queue, so a slow window does not idle four workers.
- **Dedupe at a coarser voxel** than the native spacing, or prefer the shard whose view
  is most central rather than averaging across the seam.

### The honest ceiling

Even done well this does not reach the PS budget. With the full five-project fan-out —
about 96 vCPU, so 12 tasks of 8 vCPU — a 600-view clip splits into 50-view windows at
~35 s/view, which is **~29 minutes**. The budget is 15. Only `--resolution-level 1`
(half resolution, ~4x faster) gets under it, and that trades away exactly the detail
section 3 of `docs/05-quality-analysis.md` was written to recover.

**Conclusion: horizontal CPU sharding is worth roughly 2x and is not a substitute for a
GPU.** It is useful for turnaround during development. For the actual speed criterion,
Baramati remains the answer.

### Parity note

The fuse stage meshes with screened Poisson (depth 11) rather than OpenMVS
`ReconstructMesh`, because after concatenation there is a point cloud and no `.mvs`
scene. That produced 18.9 M triangles against the single-task 1.95 M — not comparable,
and it should be brought to parity before these meshes are compared to anything.
