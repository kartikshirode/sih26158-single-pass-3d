// POST /api/start { runId } -> starts the orchestrator job for that upload.
//
// Separate from /api/runs because the upload happens between the two: the browser PUTs
// to GCS and only then asks for the work to begin. Splitting them also means a failed
// upload costs nothing, since no execution was ever created.

const L = require("./_lib");

module.exports = async (req, res) => {
  if (req.method !== "POST") return L.json(res, 405, { error: "POST only" });
  try {
    if (L.PAUSED) return L.json(res, 503, { error: "Uploads are paused right now." });

    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body || {};
    const runId = body.runId;
    // Validate the shape rather than trusting it: this value becomes a GCS prefix and
    // an env var on a job execution.
    if (!L.isRunId(runId)) return L.json(res, 400, { error: "bad runId" });

    // The upload must actually be there. Otherwise a caller could spend an execution
    // on nothing, and the job would fail 40 seconds later with a confusing message.
    const [files] = await L.bucket().getFiles({ prefix: `web/${runId}/source` });
    if (!files.length) {
      return L.json(res, 400, { error: "no uploaded file found for this run" });
    }
    if (files[0].metadata && Number(files[0].metadata.size) > L.MAX_BYTES) {
      return L.json(res, 413, { error: "that file is over the size limit" });
    }

    // Re-check concurrency here too. /api/runs checked before the upload, which may
    // have taken minutes, and another run can have started in between.
    if ((await L.runningCount()) >= L.MAX_CONCURRENT) {
      return L.json(res, 429, {
        error: "A reconstruction started while you were uploading. " +
               "This runs one at a time; your file is saved, try again shortly.",
      });
    }

    // A run id starts at most once. Without this, anyone holding an id could start it
    // again each time the last execution ended, and nothing counted those restarts
    // against the daily cap (audit F-04). The claim is atomic, so two concurrent
    // starts for one id cannot both get through.
    const claimName = `web/${runId}/started.json`;
    if (!(await L.claim(claimName, { runId }))) {
      return L.json(res, 409, { error: "this run has already been started" });
    }

    // The daily cap is enforced here, at the moment compute is committed, not only
    // at /api/runs where a URL is handed out.
    const slot = await L.reserveSlot(runId);
    if (!slot) {
      await L.release(claimName);
      return L.json(res, 429, {
        error: `The daily limit of ${L.MAX_PER_DAY} runs has been reached. ` +
               `Your file is saved; try again tomorrow.`,
      });
    }

    try {
      await L.jobs().runJob({
        name: `projects/${L.PROJECT}/locations/${L.REGION}/jobs/${L.JOB}`,
        overrides: {
          containerOverrides: [{ env: [{ name: "RUN_ID", value: runId }] }],
        },
      });
    } catch (e) {
      // Nothing was launched, so nothing was spent: give the id and the slot back.
      await L.release(slot);
      await L.release(claimName);
      throw e;
    }

    return L.json(res, 202, { runId, state: "starting" });
  } catch (e) {
    return L.json(res, 500, { error: String((e && e.message) || e) });
  }
};
