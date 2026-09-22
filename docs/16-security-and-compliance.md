# Security, compliance and data handling

Version 1.0 — 2026-09-16. The customer is India's technical intelligence agency, the data is
regulated geospatial data, and the problem statement names military reconnaissance. This
document treats that as a design input, not a paperwork step. Findings from a check of the
repository on 2026-09-16 are marked **F-n**.

---

## 1. What is being protected

| Asset | Sensitivity | Where it may exist |
|---|---|---|
| **Supplied video + telemetry** | Potentially classified; reveals *where* and *when* a flight happened | Field kit; `asia-south1`; Baramati. Nowhere else |
| **Reconstructions at ≤ 1 m** | Regulated: DST Geospatial Guidelines (15 Feb 2021) — Indian entities, stored and processed in India | Same as above |
| **Area of interest** (coordinates, even without imagery) | Operationally sensitive | Must not reach any third party, including CDNs |
| Model weights, containers | Supply-chain integrity | Pinned, checksummed, baked in |
| Credentials: GCP ADC, Vercel OIDC token (`demo/.env.local`) | Account takeover | Local only; never committed |
| Public demo | Public by design | Vercel; public footage only (Estonian CC0, public web clips) |

---

## 2. Threat model

STRIDE, applied to the three deployment topologies of `docs/13` §4.

| # | Threat | Topology | Today | Mitigation |
|---|---|---|---|---|
| T1 | **Area of interest leaks to a CDN** through runtime grid fetching | All | **F-1: the pipeline image sets `PROJ_NETWORK=ON`**, and `run_demo.py` enables PROJ networking. PROJ's network mode downloads grid chunks for the region being transformed from its CDN — which tells that CDN where you are working | The build step does **not** bake the grid: with networking on, PROJ caches only the chunks its Delhi test transform touched. Download the whole file into the image (`projsync --file us_nga_egm08_25`, ~80 MB), set `PROJ_NETWORK=OFF` at runtime, and keep `allow_ballpark=False` so a missing grid fails instead of degrading |
| T2 | **Runtime model download** — a network dependency and a code-execution path | Field kit, cloud | **F-2: model load fetched DINOv2 from the hub at runtime** (EXP-10: "incl. DINOv2-giant from hub"; EXP-11: "dominated by fetching DINOv2-giant"). The image bakes the MapAnything snapshot but not the backbone | Bake every weight into the image; set `HF_HUB_OFFLINE=1` and a local `TORCH_HOME`; prove it with **T-NF-03** (a full run with networking disabled) |
| T3 | Supply-chain tampering (images, wheels, weights) | All | Tags, not digests; unpinned conda/pip inside the MVS image | Pin base images and packages by digest or hash; record weight SHA-256 in the run manifest; generate an SBOM per image |
| T4 | Data processed outside India | Cloud | ADR-010 in force; the only GPU quota on the account is outside India | Region pinned in job definitions; Kaggle/Colab only for **non-Indian public** footage |
| T5 | Secrets in the repository | Dev | **Clean**: no keys or tokens in the non-HTML git history; `demo/.gitignore` ignores `.env*` | Keep the scan in the commit gate |
| T6 | Untracked deliverable source | Dev | **F-3: `demo/` and the design-system tools are untracked**, so the deployed site cannot be rebuilt from version control | Commit them (`.env*` stays ignored) |
| T7 | Tampered or wrong outputs presented as measured | All | `docs/08`: a 5.5× scale error shipped unnoticed | Scale status on every metric; claims ledger; run manifest |
| T8 | Field-kit loss or theft | Field kit | Not designed | Full-disk encryption; no cached credentials; wipe procedure (§5) |
| T9 | Hostile input file (decoder exploit) | All | PyAV/FFmpeg decode untrusted containers | Decode in the unprivileged container; keep FFmpeg current; S0 runs before anything else touches the file |
| T10 | Demo reveals competition material to search | Public | `robots.txt` disallows all; no Indian data | Keep it that way; "shareable by link, not by search" |
| T11 | Third-party footage published without clear rights | Public | **F-4 closed 2026-09-22.** Both clips and all three derived reconstructions are off every public surface. `tools/build_console.py` carries a `WITHHELD` set keyed on the source filename and drops the whole run rather than stripping its mesh, because a reconstruction is derived work. The clip stays a development input under L-8 | The lasting fix is still a replacement clip the team holds rights to (B-33). Until then the console has no run with a mesh and an unvalidated scale, and `tools/test_console.py` reports two explicit SKIPs saying so |

---

## 3. Data handling procedure (R-NF8)

1. **Intake.** Supplied data arrives on the field kit, or directly into
   `gs://sih26158-mumbai` (`asia-south1`). Record SHA-256 checksums in the run manifest at intake.
2. **Processing.** Field kit, Cloud Run Jobs in `asia-south1`, or Baramati. No other region,
   no notebook service, no SaaS.
3. **Derived products.** Same locations as the source. A reconstruction is regulated data even
   when the video is not.
4. **Sharing.** Only through the channel the organisers specify. The public demo never carries
   supplied data.
5. **Retention.** Delete supplied data and derived products at the end of the event unless the
   organisers direct otherwise; record the deletion.
6. **Self-certification.** State the residency in the submission, as the DST guidelines
   expect.

---

## 4. Licence compliance

| # | Item | Obligation | Status |
|---|---|---|---|
| **L-1** | **OpenMVS — AGPL-3.0** | Run unmodified as a separate program; our code stays outside its copyleft. **Modifying it and offering it over a network would require offering that source.** | Compliant. ADR-023 proposes a BSD (COLMAP) GPU path that avoids the question |
| L-2 | OpenDroneMap — AGPL-3.0 | Reference only; no code copied | Compliant |
| **L-3** | **Blender fallback for FBX** | The `bpy` expression in `export_formats.write_fbx` is Blender-API glue; a *published* `bpy` script is treated as GPL (`research/02-ingestion-export-findings.md` §5) | Keep it a developer-machine fallback; the container uses assimp (BSD-3). Do not distribute the fallback in a product build |
| L-4 | MapAnything (Apache-2.0), DINOv2 (Apache-2.0) | Keep LICENSE and NOTICE with any redistribution of weights or code | Add to the offline bundle |
| L-5 | COLMAP (BSD), GLOMAP (BSD-3), assimp (BSD-3), laspy, rasterio, trimesh, PyAV | Attribution | Collect into a `THIRD_PARTY_NOTICES` file |
| L-6 | FFmpeg | LGPL when decode-only (the native H.264/HEVC decoders are LGPL) | Compliant; never link libx264/libx265 into a shipped build |
| L-7 | AerialMetric weights (if adopted) | CC BY 4.0 per the paper — attribution | Verify at download (ADR-024) |
| **L-8** | **Footage rights** | Kolu: CC0. Nicosia, Bahá'í temple: CC BY 3.0 (attribution). Toolse: CC BY-SA 4.0. **Village (YouTube Short): no clear rights** | Village is for pipeline testing only (T-ROB-09); F-4 closed 2026-09-22. Authors and source files are in **§4.1**, recovered 2026-09-23. **No public surface can carry a CC BY clip until the gallery has a credit field** |
| **L-9** | **This project's own licence** | None declared. SIH rules split IP in a winning idea equally with the PS organisation | **Decision needed** before anything is published beyond the demo |
| L-10 | VGGT, MASt3R, UniDepth, Inria 3DGS/2DGS, Pi3 weights, NC MapAnything | Barred for this use | Must not appear in any product build; the NC MapAnything checkpoint is internal ablation only |
| L-11 | UseGeo dataset (ISPRS / FBK / Twente), CC BY-NC-SA 4.0 | Attribution; non-commercial; a reconstruction scored against it carries the same licence | Evaluation only (`research/03`). Never deliverable data, never published under another licence |
| L-12 | DJI SRT test fixtures from `JuanIrache/DJI_SRT_Parser`, MIT | Keep the licence text with the files | Compliant: `src/ingest/fixtures/dji_srt/LICENSE.DJI_SRT_Parser` |

### 4.1 Footage provenance (L-8 in full)

L-8 recorded the licences but not the authors, so no compliant credit line could be written
from the repo. Recovered 2026-09-23 from the Wikimedia Commons API. Both files on disk are
byte-identical to the Commons originals, matched on size and duration for Toolse and on SHA-1
for the Bahá'í clip, so these are the correct works and not lookalikes.

| Clip | Commons file | Author | Licence | Date |
|---|---|---|---|---|
| `data/cand/toolse.webm` | `File:Toolse castle in Estonia (Fall 2021).webm` | Sillerkiil | CC BY-SA 4.0 | 2021-11-14 |
| `data/cand/bahai.webm` | `File:Baha'i Temple -- Wilmette , IL -- Drone Video (DJI Spark).webm` | Kurt Elster | CC BY 3.0 | 2019-03-10 |

SHA-1 of `bahai.webm` is `8e682f018f572659e3f09f1157ff0560a0db66a2`; `toolse.webm` is
58,179,695 bytes and 114.283 s. The Bahá'í clip reached Commons from YouTube, which is why its
Commons credit names an archive copy.

**Publishing either one requires a visible credit naming the author and the licence, and a
link to the source.** `tools/build_gallery.py` and `tools/gallery_template.html` have no field
for that today, because Kolu is CC0 and never needed one. That field is a prerequisite for
B-33, not a nicety. CC BY-SA 4.0 additionally makes any published reconstruction of Toolse
share-alike, which is a decision for L-9 rather than one to take while adding a gallery tile.

---

## 5. Field kit baseline

The finale may be offline, and the customer is an intelligence agency. The kit is built for
that, not adapted to it.

| Control | Requirement |
|---|---|
| Disk | Full-disk encryption (BitLocker or LUKS) |
| Network | Disabled during processing; the run must pass T-NF-03 before the event |
| Images | Loaded from a checksummed archive; digests recorded |
| Accounts | No cloud credentials cached on the kit |
| Input media | Mount read-only; checksum at intake |
| Output | Written to the kit, handed over on the organisers' medium |
| After the event | Wipe the working volume; record it |

---

## 6. Drone operations (for data the team collects)

Collecting Held-out A (`docs/12` EXP-21) means flying in India. The Drone Rules, 2021 and the
Digital Sky airspace map govern where and how; **check current registration, pilot and
airspace requirements before any flight** — this document does not restate them because they
change. Record the flight permission reference with the dataset.

---

## 7. Actions

| # | Action | Closes | Effort |
|---|---|---|---|
| 1 | Whole EGM2008 grid in the image; `PROJ_NETWORK=OFF` at runtime | F-1 / T1 | small |
| 2 | Bake DINOv2; `HF_HUB_OFFLINE=1`; run T-NF-03 | F-2 / T2 | small–medium |
| 3 | Commit `demo/` and the design-system tools | F-3 / T6 | small |
| 4 | Pin images by digest; SBOM per image; weight checksums in the manifest | T3 | medium |
| 5 | `THIRD_PARTY_NOTICES` | L-4, L-5 | small |
| 6 | Decide the project licence | L-9 | decision |
| 7 | Secret scan in the commit gate | T5 | small |
| ~~0~~ | Take the Village video off the public gallery — **done 2026-09-22**, along with its reconstructions | F-4 / T11 | small |
| 8 | Field-kit build and wipe procedure, rehearsed | T8, §5 | medium |
