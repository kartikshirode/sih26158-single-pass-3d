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
