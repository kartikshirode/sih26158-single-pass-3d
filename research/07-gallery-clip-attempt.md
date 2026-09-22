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
(`sih26158-mapanything`, `sih26158-mvs`) exist and the account is authed. Kolu's recorded
reconstruction was 34m 39s, and that is the closest estimate available for a similar clip.
toolse would be larger: 297 keyframes against Kolu's 45.

## 4. The gallery has nowhere to put a credit, and the repo has no credit to put there

This blocks publishing either clip, independently of everything above.

`docs/16` L-8 records the licences but not the authors or source URLs. CC BY 3.0 and CC BY-SA
4.0 both require attributing the creator by name. The name is not written down anywhere in the
repo, so no compliant credit line can be produced from what is on disk.

`tools/build_gallery.py` and `tools/gallery_template.html` have no licence, credit or source
field at all. Kolu is CC0, so the omission never mattered. Any clip that is not CC0 needs that
field added before it ships.

Two pieces of work, in order:

1. Record author, title, source URL and licence for bahai, toolse and nicosia in `docs/16` L-8.
   Without this, B-33 cannot be closed compliantly whichever clip is chosen.
2. Add a per-example credit line to the gallery builder and template, rendered from that record.

## Where this leaves B-33

B-33 is reachable, but it is three tasks rather than one: pick the clip (which is really an L-9
licence decision), pay for two Cloud Run jobs, and build the attribution path. The runs are
resumable, so `out/runs/bahai` and `out/runs/toolse` keep their screening and keyframes and
only need `--adopt` once the containers have produced geometry.
