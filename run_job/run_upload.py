"""
One uploaded clip, start to finish, as a single Cloud Run Job execution.

Why a job and not a service: the whole chain is roughly 70 minutes of 8 vCPU, and a
Cloud Run *service* request is capped at 60. A job can run for hours, so the execution
itself is the unit of work and nothing on the caller's side has to stay alive. The
Vercel functions only create the upload URL, start this, and read status.json.

    upload -> S0 screen -> S1 keyframes -> poses (kolu-ma) -> PREVIEW
                                        -> densify (sih26158-mvs) -> FINAL

The preview matters. Densification is ~77% of the wall clock, so the feed-forward
model exists about an hour before the rebuilt one. Serving it as soon as it lands is
what the PS calls near-real-time (challenge vi) and what docs/18 B-31 describes; a page
that shows nothing for 70 minutes would be a worse answer to the same question.

STATUS IS THE CONTRACT. `web/<runId>/status.json` is rewritten after every transition
and is the only thing the browser reads. Every number in it is measured: elapsed comes
from the clock, expected comes from the rates this project actually recorded
(research/07). No stage reports a percentage it cannot justify.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

BUCKET = os.environ.get("BUCKET", "sih26158-mumbai")
RUN_ID = os.environ.get("RUN_ID", "")
PROJECT = os.environ.get("GCP_PROJECT", "agentbillboard")
REGION = os.environ.get("REGION", "asia-south1")
MA_JOB = os.environ.get("MA_JOB", "kolu-ma")
MVS_JOB = os.environ.get("MVS_JOB", "sih26158-mvs")

# Caps. These are engineering limits, not access control: they are what fits inside the
# two job timeouts and what the PS asks for. MAX_VIEWS is the hard one - 297 views was
# planned for Toolse and would have needed 3.2 h of densify against a 3 h job timeout,
# while 60 views matches Kolu's view density and lands near its recorded wall clock.
MAX_VIEWS = int(os.environ.get("MAX_VIEWS", "60"))
# Below this there is not enough baseline to reconstruct anything, so the run stops
# with the screener's reasons instead of spending an hour proving it.
MIN_VIEWS = int(os.environ.get("MIN_VIEWS", "8"))
MAX_SECONDS = float(os.environ.get("MAX_SECONDS", "600"))      # PS: 10-minute video
MAX_BYTES = int(os.environ.get("MAX_BYTES", str(600 * 1024 * 1024)))

W = "/tmp/web"
SRC = f"{W}/source"
T0 = time.time()

# Measured on this project, not guessed. Poses: 10.68 s/view at 60 views (the 6.4-8.1
# in research/exp10 was measured at 8 views and does not hold here). Densify: 2,003 s
# for 60 views. Both exclude container image import, which is why the first run of the
# day looks slower than these.
RATE_POSE_S_PER_VIEW = 10.68
DENSIFY_S_AT_60 = 2003.0

STAGES = [
    ("fetch", "Fetching the upload"),
    ("screen", "Screening admissibility"),
    ("ingest", "Selecting keyframes"),
    ("poses", "Estimating camera poses"),
    ("preview", "Building the preview model"),
    ("densify", "Photometric densification"),
    ("final", "Building the final model"),
]

_state = {
    "runId": RUN_ID,
    "schema": "sih26158/web-run/1",
    "state": "running",
    "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "stages": [{"id": i, "label": l, "state": "waiting"} for i, l in STAGES],
    "screen": None,
    "ingest": None,
    "preview": None,
    "final": None,
    "error": None,
}


def bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def put_status():
    """Rewrite status.json. Called after every transition, so the page is never more
    than one step behind. no-cache because the browser polls it."""
    _state["elapsed"] = round(time.time() - T0, 1)
    b = bucket().blob(f"web/{RUN_ID}/status.json")
    b.cache_control = "no-store"
    b.upload_from_string(json.dumps(_state, indent=1), content_type="application/json")


def stage(sid, state, **kw):
    for s in _state["stages"]:
        if s["id"] == sid:
            s["state"] = state
            if state == "running":
                s["startedAt"] = round(time.time() - T0, 1)
            if state in ("done", "skipped", "failed"):
                s["seconds"] = round(time.time() - T0 - s.get("startedAt", 0), 1)
            s.update(kw)
    put_status()


def expect(sid, seconds):
    """Publish an expected duration so the page can show progress without inventing
    one. Only set where a measured rate exists."""
    for s in _state["stages"]:
        if s["id"] == sid:
            s["expectedSeconds"] = round(seconds)
    put_status()


def fail(msg, code=None):
    _state["state"] = "failed"
    _state["error"] = {"message": msg, "code": code}
    put_status()
    print(f"FAILED: {msg}", flush=True)
    sys.exit(1)


def sh(args, label):
    print(f"  $ {label}", flush=True)
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if r.stdout:
        print("\n".join("    " + x for x in r.stdout.strip().splitlines()[-40:]),
              flush=True)
    if r.returncode:
        print(r.stderr[-3000:], flush=True)
        raise RuntimeError(f"{label} failed rc={r.returncode}")
    return r.stdout


def run_cloud_job(job, env, label, expect_s, sid):
    """Start a Cloud Run job with per-run env overrides and wait for it.

    Overrides rather than `jobs update`: two uploads must not race each other into the
    same job definition, which is exactly what would happen if each rewrote the job's
    env before executing it.
    """
    from google.cloud import run_v2
    c = run_v2.JobsClient()
    name = f"projects/{PROJECT}/locations/{REGION}/jobs/{job}"
    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[run_v2.RunJobRequest.Overrides.ContainerOverride(
            env=[run_v2.EnvVar(name=k, value=v) for k, v in env.items()])])
    # Cloud Run returns 503 "Internal error running task" occasionally, with the task's
    # own exit code reported as 0. That is the platform, not the job: the first web run
    # lost its pose stage to one. Retry once, and only for that shape of failure, so a
    # genuine job failure still surfaces immediately rather than costing a second hour.
    last = None
    for attempt in (1, 2):
        op = c.run_job(request=run_v2.RunJobRequest(name=name, overrides=overrides))
        print(f"  {label}: execution started (attempt {attempt})", flush=True)
        expect(sid, expect_s)
        try:
            res = op.result(timeout=4 * 3600)
        except Exception as e:
            last = e
            if attempt == 1 and "Internal error running task" in str(e):
                print(f"  {label}: transient platform error, retrying once", flush=True)
                continue
            raise
        ok = getattr(res, "succeeded_count", 0) or 0
        if ok < 1:
            raise RuntimeError(f"{label}: job reported no successful task")
        return res
    raise RuntimeError(f"{label}: {last}")


def main():
    if not RUN_ID:
        sys.exit("RUN_ID is required")
    print(f"web run {RUN_ID}", flush=True)
    put_status()

    os.makedirs(W, exist_ok=True)

    # ---- fetch -----------------------------------------------------------------
    stage("fetch", "running")
    b = bucket()
    blobs = [x for x in b.list_blobs(prefix=f"web/{RUN_ID}/")
             if os.path.basename(x.name).startswith("source")]
    if not blobs:
        fail("no uploaded file found for this run", "WEB-NOSRC")
    src = blobs[0]
    if src.size and src.size > MAX_BYTES:
        fail(f"file is {src.size/1e6:.0f} MB; the limit is {MAX_BYTES/1e6:.0f} MB",
             "WEB-TOOBIG")
    ext = os.path.splitext(src.name)[1] or ".mp4"
    path = SRC + ext
    src.download_to_filename(path)
    stage("fetch", "done", note=f"{src.size/1e6:.1f} MB")

    # ---- screen + ingest, in-process via the real pipeline ---------------------
    # tesseract.py is the product; the web path runs the same code rather than a
    # parallel implementation that could drift from it.
    # S0 and S1 are called directly, NOT through `tesseract.py run`. The runner owns a
    # degradation ladder, and S3 has no geometry provider in this container by design
    # (poses run in kolu-ma). So the ladder read STAGE-UNAVAILABLE as a reason to retry
    # the whole run at L1, L2, L3, L4 and finally L5, re-screening and re-ingesting each
    # time: five passes, 594 s, and a verdict of "not reconstructable" for a clip that
    # reconstructs perfectly well. The ladder is right for a batch run and wrong here,
    # because this orchestrator supplies the missing stage itself a few lines below.
    stage("screen", "running")
    from ingest.screen import screen as screen_clip
    try:
        scr = screen_clip(path)
    except Exception as e:
        fail(f"could not read the video: {e}", "ING-READ")
    _state["screen"] = scr
    stage("screen", "done",
          note=f"{scr['resolution']} - {scr['duration_s']:.0f} s - "
               f"{scr['shots_detected']} shots")

    if scr.get("duration_s", 0) > MAX_SECONDS:
        fail(f"clip is {scr['duration_s']:.0f} s; the limit is {MAX_SECONDS:.0f} s "
             f"(the PS target is a 10-minute video)", "WEB-TOOLONG")

    stage("ingest", "running")
    kf_dir = f"{W}/kf"
    try:
        sh([sys.executable, os.path.join(ROOT, "src", "ingest", "video_ingest.py"),
            path, "--out", kf_dir, "--n", str(MAX_VIEWS), "--horizon", "crop"],
           "S1 ingest")
    except RuntimeError as e:
        fail(f"keyframe selection failed: {e}", "ING-FAIL")

    ing_p = os.path.join(kf_dir, "ingest.json")
    if not os.path.exists(ing_p):
        fail("ingest wrote no keyframe set", "ING-FAIL")
    ing = json.load(open(ing_p, encoding="utf-8"))
    if len(ing.get("keyframes") or []) < MIN_VIEWS:
        # Too little survives the gates to reconstruct anything. That is a RESULT, and
        # the screener's own reasons are the explanation: R-C9 asks the system to say
        # why a clip is hard before spending inference on it. No MapAnything, no MVS.
        _state["state"] = "refused"
        _state["error"] = {
            "message": "; ".join(scr.get("reasons") or []) or
                       f"only {len(ing.get('keyframes') or [])} usable keyframes",
            "code": "ADM-REFUSED"}
        for s in _state["stages"]:
            if s["state"] in ("waiting", "running"):
                s["state"] = "skipped"
        put_status()
        print("refused: too few usable keyframes; no inference spent", flush=True)
        return
    st = ing["stats"]
    _state["ingest"] = {
        "framesDecoded": st["frames_decoded"],
        "keyframes": st["keyframes_selected"],
        "shots": st["shots_detected"],
        "cropTop": st.get("overlay_crop_trbl", [0])[0],
        "rejectedBlur": st.get("rejected_blur"),
        "rejectedSky": st.get("rejected_sky"),
        "hasTelemetry": st.get("has_gps_sidecar", False),
    }
    # No stale-file filter needed: video_ingest.py clears kf_*.jpg from --out before it
    # writes, so this directory holds exactly this run's selection. Doing it by hand is
    # how 296 stale frames from an earlier pass nearly went up with a later one.
    sent = 0
    for fn in sorted(os.listdir(kf_dir)):
        if fn.startswith("kf_") and fn.endswith(".jpg"):
            b.blob(f"web/{RUN_ID}/kf/{fn}").upload_from_filename(
                os.path.join(kf_dir, fn))
            sent += 1
    stage("ingest", "done",
          note=f"{sent} keyframes from {st['frames_decoded']:,} frames, "
               f"horizon cropped {100*st.get('overlay_crop_trbl',[0])[0]:.0f}% off the top")

    # ---- poses ------------------------------------------------------------------
    stage("poses", "running")
    try:
        run_cloud_job(MA_JOB, {
            "IN_PREFIX": f"web/{RUN_ID}/kf",
            "OUT_PREFIX": f"web/{RUN_ID}/ma",
            "MAX_VIEWS": str(sent),
        }, "poses", sent * RATE_POSE_S_PER_VIEW, "poses")
    except Exception as e:
        fail(f"pose estimation failed: {e}", "MA-FAIL")
    stage("poses", "done")

    # ---- preview (feed-forward) --------------------------------------------------
    stage("preview", "running")
    try:
        env = dict(os.environ, RUN=RUN_ID, GCS_PREFIX=f"web/{RUN_ID}/ma",
                   KF_DIR=f"web_{RUN_ID}")
        shutil.copytree(kf_dir, os.path.join(ROOT, "out", f"web_{RUN_ID}"),
                        dirs_exist_ok=True)
        shutil.copy(ing_p, os.path.join(ROOT, "out", f"web_{RUN_ID}", "ingest.json"))
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "finish_kolu.py")],
                       env=env, check=True)
        prev = publish_model(b, f"{RUN_ID}3d", "preview")
        _state["preview"] = prev
        stage("preview", "done", note=f"{prev['points']:,} points")
    except Exception as e:
        print(traceback.format_exc()[-2000:], flush=True)
        stage("preview", "failed", note=str(e)[:200])

    # ---- densify -----------------------------------------------------------------
    stage("densify", "running")
    try:
        run_cloud_job(MVS_JOB, {
            "KF_PREFIX": f"web/{RUN_ID}/kf",
            "MA_PREFIX": f"web/{RUN_ID}/ma",
            "OUT_PREFIX": f"web/{RUN_ID}/mvs",
            "MESH_BLOB": "",
            "RESOLUTION_LEVEL": "0",
        }, "densify", DENSIFY_S_AT_60 * max(1, sent) / 60.0, "densify")
    except Exception as e:
        _state["state"] = "partial"
        _state["error"] = {"message": f"densification failed: {e}", "code": "MVS-FAIL"}
        stage("densify", "failed")
        put_status()
        return
    stage("densify", "done")

    # ---- final -------------------------------------------------------------------
    stage("final", "running")
    try:
        env = dict(os.environ, RUN=RUN_ID, GCS_PREFIX=f"web/{RUN_ID}/mvs",
                   BASELINE=f"{RUN_ID}3d")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "finish_mvs.py")],
                       env=env, check=True)
        fin = publish_model(b, f"{RUN_ID}mvs3d", "final")
        _state["final"] = fin
        stage("final", "done", note=f"{fin['points']:,} points")
    except Exception as e:
        print(traceback.format_exc()[-2000:], flush=True)
        _state["state"] = "partial"
        stage("final", "failed", note=str(e)[:200])
        put_status()
        return

    _state["state"] = "done"
    put_status()
    print(f"done in {time.time()-T0:.0f}s", flush=True)


def publish_model(b, out_run, label):
    """Upload the packed geometry and whatever export formats exist, and return what
    the page needs to show and to offer for download.

    The pack is lifted with build_gallery.packed(), which is how the gallery and the
    console already read a built viewer: byte-for-byte what that run delivered, and no
    second packing path to drift. build_viewer.py has no JSON flag, only --stats/--out.

    Only the MVS run writes an export/ directory; finish_kolu does not, so the preview
    legitimately has no downloads and `files` stays empty for it.
    """
    from build_gallery import packed

    d = os.path.join(ROOT, "out", out_run)
    info = {"label": label, "files": {}}
    D, half = packed(out_run)
    blob = b.blob(f"web/{out_run}/packed.json")
    blob.cache_control = "public, max-age=86400"
    blob.upload_from_string(json.dumps(D), content_type="application/json")
    info["mesh"] = f"web/{out_run}/packed.json"
    info["points"] = int(D.get("np", 0))
    info["triangles"] = int(D.get("nt", 0))
    info["halfExtent"] = round(half, 3)
    exp = os.path.join(d, "export")
    if os.path.isdir(exp):
        for fn in sorted(os.listdir(exp)):
            p = os.path.join(exp, fn)
            if os.path.isfile(p) and os.path.getsize(p) < 400e6:
                b.blob(f"web/{out_run}/export/{fn}").upload_from_filename(p)
                info["files"][fn] = round(os.path.getsize(p) / 1e6, 1)
    return info


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(traceback.format_exc(), flush=True)
        try:
            fail(f"unexpected: {e}", "WEB-CRASH")
        except Exception:
            sys.exit(1)
