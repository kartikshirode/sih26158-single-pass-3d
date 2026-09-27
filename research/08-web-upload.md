# A front end that takes an upload, 2026-09-23

Building "upload a clip, watch it run, get the model". This file records the decisions
and the two defects the work exposed, both of which matter beyond the feature.

## Shape

A Cloud Run **job** per upload, not a service. A service request is capped at 60 minutes
and the chain is about 70. A job execution also removes this laptop from the loop, which
today's Toolse run could not do: it only completed because a shell script here kept
polling, and that is not a product.

```
upload -> S0 screen -> S1 keyframes -> poses (kolu-ma) -> PREVIEW
                                    -> densify (sih26158-mvs) -> FINAL
```

The preview is the point. Densification is about 77% of wall clock, so the feed-forward
model exists roughly an hour before the rebuilt one. Publishing it the moment it lands
is what the PS calls near-real-time (challenge vi) and what `docs/18` B-31 describes. A
page that shows nothing for 70 minutes answers the same question worse.

`web/<runId>/status.json` is the contract and the only thing the browser reads. Expected
durations come from rates this project measured (10.68 s/view for poses, 2,003 s densify
at 60 views), never from an invented percentage.

A screener refusal is a **result**, not an error: it ends in seconds at L5 with the
reasons and spends no MapAnything or MVS compute. `docs/01` R-C9 asks the system to say
why a clip is hard before spending inference on it, and this is where a user sees that.

## Defect 1: the packing scripts could never have left this laptop

`finish_kolu.py` and `finish_mvs.py` both hardcoded
`PY311 = C:\Users\Mandar\...\python.exe` and shelled out to `gsutil -m cp` with
`shell=True`. Neither can run in a container. This was invisible while a human ran them
by hand and is fatal the moment a reconstruction has to finish without one.

Now `sys.executable` (still 3.11 here, 3.12 in the image) and `tools/gcs_io.pull`, using
the google-cloud-storage client already in `requirements.txt`.

## Defect 2: ingest retained every frame at full resolution, and this caps the PS target

The first containerised run died at S1 with `rc=-9`, SIGKILL, no log line. The cause:

```python
thumbs.append(img)      # img is the FULL-RESOLUTION frame, every analysed frame
```

| Clip | Frames | Retained at 1920x1080x3 |
|---|---|---|
| Kolu, 52 s | 1,562 | 9.7 GB |
| Toolse, 114 s | 2,857 | **17.8 GB** (killed at 16 GiB) |
| **A 10-minute video at 30 fps, which the PS asks for** | **18,000** | **~112 GB** |

So **R-O2 was unreachable for its own stated input**, and not for a reason anyone had
looked at. "Under 15 minutes for a 10-minute video" cannot be met by a stage that needs
112 GB to read one. The ceiling stayed hidden because every development clip is under
two minutes, and this laptop has enough memory to absorb the smaller cases.

The fix is not a smaller buffer. Of the three uses of that list, two downscale
immediately and the 0.25-scale analysis copy is already the size they want; only the
final emit needs full resolution, and only for the ~60 selected frames. So keep the
analysis copy and decode the selected frames again in a short second pass. Memory at
full resolution becomes O(keyframes) instead of O(clip length), and the per-frame
constant drops 16x.

Verified against the previous Toolse run: the same 60 frame numbers, the same statistics
down to `blur_threshold_varlap` of 1209.9, and all 60 keyframe JPEGs byte-for-byte
identical. One extra sequential decode, about 20 s on a 114 s clip.

**This is worth re-checking before any R-O2 claim.** A 10-minute clip now holds roughly
7 GB of analysis copies at 0.25 scale, which fits but is not comfortable, and nothing
here has yet been run at that length. The next honest step is to ingest a 10-minute clip
and record what it actually costs, rather than assuming the fix is sufficient.

Done on 2026-09-25 (`research/09-gpu-pipeline.md`), on the demo clip looped to 10 minutes of
1080p30: the code as it stood took 402 s and peaked at 10.7 GB. After the S1 changes
recorded there it takes 55 s and peaks at 6.0 GB, scoring every second frame on threads.

## Limits on the public endpoint

Chosen as engineering limits, not access control: a size cap, a 10-minute duration cap
(the PS figure), a fixed 60-view cap whatever the clip length (297 views would need
3.2 h of densify against a 3 h job timeout), a concurrency limit, a daily cap and a
kill-switch. Each run is roughly 70 minutes of 8 vCPU on a billing account with no auth
in front of it.

**Added 2026-09-24, after the core-logic audit (F-04, F-05).** Two of those limits did not
hold as first built. `/api/start` never checked the daily cap and never recorded that a
run id had started, so one uploaded clip could be started again every time its last
execution ended. And the upload URL trusted the size the browser declared. Both are
enforced by GCS now rather than by a count read beforehand:

- a start claims `web/<id>/started.json` and one of `web/_slots/<UTC day>/NNN.json`, each
  created with `ifGenerationMatch=0`, so a second start of the same id gets 409 and the
  thirteenth start of the day gets 429, however the requests race;
- the signed PUT URL carries `x-goog-content-length-range: 0,<MAX_BYTES>`, so GCS refuses
  a larger body. The bucket's CORS config has to allow that header
  (`deploy/web-bucket-cors.json`) before the page that sends it is deployed.

What is still advisory: the one-at-a-time check. Two different clips started within the
same second can both pass it. The daily slots bound what that race can cost.

## Uploads stay off the gallery and the console

`footage.credit()` refuses a clip whose rights are not recorded, and it is right to.
An uploaded clip has no record, so results live at an unlisted `/run/#<id>` with a
lifecycle rule, and never appear on the two curated surfaces.
