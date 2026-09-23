# Adding a second clip to the gallery, 2026-09-23

An attempt to reconstruct a new clip for the public gallery, prompted by a request to use a
YouTube drone video. Four things came out of it, in the order they blocked the work.

## 1. The requested video cannot be used

`https://youtu.be/kfCIqEvXi6U`, "Antietam National Battlefield drone video", Paul Vivrett,
uploaded 2018-09-22, 409 s at 1280x720/24.

`yt-dlp --dump-json` reports `license: None`, which is YouTube's standard licence. A Creative
Commons video reports "Creative Commons Attribution license (reuse allowed)" in that field.

This is the Village clip situation again, which `docs/16` closed as F-4 on 2026-09-22. The
reasoning there applies unchanged: `tools/build_console.py` drops a whole run rather than
stripping its mesh, because a reconstruction is derived work. A model built from this clip is
as exposed as republishing the clip.

## 2. Of the two rights-clear candidates, the roadmap named the weaker one first

`docs/18` B-33 offers `bahai.webm` (CC BY 3.0) and `toolse.webm` (CC BY-SA 4.0) and says both
now pass S0 through `--horizon crop`. Both do pass. They are not comparable after that.

| | bahai | toolse |
|---|---|---|
| Duration | 58.0 s | 114.3 s |
| Shots, longest | 8, 14.0 s | 4, 40.0 s |
| Median sky | 58.8% | 9.4% |
| S0 verdict | REJECT, sky | REJECT, horizon |
| Crop applied off the top | **66.2%** | 17.7% |
| Frame after crop | 1920x365 | 1920x889 |
| Keyframes | **37** | **297** |
| Keyframe span | **3.8 s** (frames 1000-1115) | **37.6 s** (frames 940-1879) |
| Frames rejected for sky | 1288 | 122 |

The crop is what separates them. Cropping 66% off bahai to get under the sky threshold leaves a
365-pixel strip, and inside that strip the surviving keyframes cover under four seconds of
flight. The subject is also the worst case for matching: the Wilmette temple dome is a
repetitive ornamental lattice, and the run orbits it slowly, so there is little parallax to
recover. `tools/build_console.py` already carries a `bahai-rejected` entry describing an
earlier refusal of this clip as intended behaviour.

toolse gives ten times the flight time and eight times the keyframes with the frame nearly
intact. It is the better reconstruction candidate by a wide margin.

The cost of preferring it is licensing, not geometry. CC BY-SA 4.0 is share-alike, so the
reconstruction inherits it, and `docs/16` L-9 records that this project has no declared licence
yet. Publishing a share-alike derivative is a decision that belongs with L-9, not one to make
in passing while adding a gallery tile.

## 3. Neither clip can reconstruct on this machine

Both runs stop at the same place:

```
S3-geometry  skipped  [STAGE-UNAVAILABLE]
  no geometry provider on this host. Run the containers
  (gcloud run jobs execute sih26158-mapanything --region=asia-south1, then sih26158-mvs)
  and re-run with --adopt <out/RUN>, or use --source synthetic
```

This is the documented design, not a fault: the ladder walks down and the run still writes a
manifest and a verdict. `out/runs/bahai/run_manifest.json` records R-O1 not met and R-O5
partial (0), which is the honest result of a run that never reached geometry.

So a gallery model costs two Cloud Run jobs in `asia-south1`, not local compute. Both
(`sih26158-mapanything`, `sih26158-mvs`) exist, the account is authed, and both are 8 vCPU /
32 GiB.

**Uncapped, toolse does not fit in the jobs as configured.** S2 planned 297 pose views and 297
dense views, because `--dense-views` defaults to 300 and nothing capped it. At the repo's own
`S_PER_VIEW_DENSE_CPU = 39.0`, 297 dense views is 11,583 s, or 3.2 hours. `sih26158-mvs` has
`timeoutSeconds: 10800`, three hours, so the run would be killed before it finished.
`sih26158-mapanything` is tighter still at 3,600 s, and its 0.55 s/view figure is the GPU
number from EXP-11, not what 8 vCPU will do.

The fix is to cap the views, and the view count is waste rather than quality. toolse's
keyframes sit about 3 frames apart, 0.13 s, across a 37.6 s span. Kolu used 45 views across
52 s. Matching that density needs roughly 35 views, so `--dense-views 60` is already generous:
60 x 39 = 2,340 s, comfortably inside the timeout and close to Kolu's recorded 34m 39s.

State the quality case carefully. What makes toolse the better clip is the 37.6 s span against
3.8 s, and the 17.7% crop against 66.2%. The 297 keyframes are a cost to be capped, not a
merit.

## 4. The gallery has nowhere to put a credit

`docs/16` L-8 recorded the licences but not the authors, and CC BY 3.0 and CC BY-SA 4.0 both
require naming the creator. The authors were not written down anywhere in the repo, and the
video containers carry only encoder tags, so nothing on disk could produce a compliant credit.

Both were recovered from the Wikimedia Commons API and are now in `docs/16` §4.1:

| Clip | Author | Licence | Commons file |
|---|---|---|---|
| toolse | Sillerkiil | CC BY-SA 4.0 | `File:Toolse castle in Estonia (Fall 2021).webm` |
| bahai | Kurt Elster | CC BY 3.0 | `File:Baha'i Temple -- Wilmette , IL -- Drone Video (DJI Spark).webm` |

Both matched byte-identically, Toolse on size and duration (58,179,695 bytes, 114.283 s) and
bahai on SHA-1 (`8e682f018f572659e3f09f1157ff0560a0db66a2`), so these are the works themselves
rather than lookalikes. An earlier guess in this file that the clips had been re-encoded, and
that a hash lookup was therefore pointless, was wrong: the `Lavc` tags are the uploaders' own.

What remains is the field to print it in. `tools/build_gallery.py` and
`tools/gallery_template.html` have no licence, credit or source field at all, because Kolu is
CC0 and the omission never mattered. Adding one is a prerequisite for B-33, and it has to cover
the source video too: the gallery copies the clip into `demo/gallery/assets`, which republishes
it alongside the model.

## 5. Running it turned up a wrong instruction in the repo

The pipeline's own `STAGE-UNAVAILABLE` message says to run `sih26158-mapanything`, and
`README.md` and `docs/15` said the same. Following that on a real clip fails:

```
  fetched 60 files from gs://sih26158-mumbai/mapanything/toolse_input
  MapAnything on CPU  |  torch 2.6.0+cpu | threads 5
FileNotFoundError: [Errno 2] No such file or directory: '/tmp/ma/meta.json'
```

That job runs `mapanything:v1`, which is the **synthetic harness**. It reads a `meta.json`
written beside the rendered frames by the rasteriser, and
`gs://sih26158-mumbai/mapanything/ma_input/meta.json` is where it comes from. `research/exp10`
reproduces against exactly that prefix, so v1 is doing its job; the instruction was pointing
video runs at it.

Real keyframes go through the `kolu-ma` job, which runs `mapanything:v2` and takes bare images.
Its name is historical and not Kolu-specific. Fixed in `stages.py`, `README.md` and `docs/15`.

The lesson generalises: the local `mapanything_job/run_mapanything.py` has no `meta.json`
handling anywhere in its 182 lines, so the repo source cannot tell you which deployed image
does what. Only the job definitions in `asia-south1` carry that, and they disagree with each
other. Anything that reads a container's behaviour off the repo is guessing.

## 6. The credit field is built

`tools/build_gallery.py` now carries `FOOTAGE` with the provenance from `docs/16` §4.1, and
`credit()` renders an attribution line into a new `.vcred` element under the video. It exits
rather than build an example whose rights are not recorded, because the failure it guards
against is silent republication rather than a visible error. Kolu renders its CC0 line today.

## Where this leaves B-33

B-33 is reachable, but it is three tasks rather than one: pick the clip (which is really an L-9
licence decision), pay for two Cloud Run jobs, and build the attribution path. The runs are
resumable, so `out/runs/bahai` and `out/runs/toolse` keep their screening and keyframes and
only need `--adopt` once the containers have produced geometry.
