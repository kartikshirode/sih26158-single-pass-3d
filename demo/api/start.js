// POST /api/start { runId } -> starts the orchestrator job for that upload.
//
// Separate from /api/runs because the upload happens between the two: the browser PUTs
// to GCS and only then asks for the work to begin. Splitting them also means a failed
// upload costs nothing, since no execution was ever created.

const L = require("./_lib");

// Returns { code, body }. Everything it created is handed back before it returns unless
// the job launched, and the lease is always released. Cleanup runs BEFORE the response
// is sent: a serverless function can be frozen as soon as it has answered.
async function startUnderLease(runId) {
  const owned = [];
  try {
    // Re-check concurrency here too. /api/runs checked before the upload, which may
    // have taken minutes, and another run can have started in between.
    if ((await L.runningCount()) >= L.MAX_CONCURRENT) {
      return { code: 429, body: {
        error: "A reconstruction started while you were uploading. " +
               "This runs one at a time; your file is saved, try again shortly." } };
    }

    // A run id starts at most once. Without this, anyone holding an id could start it
    // again each time the last execution ended, and nothing counted those restarts
    // against the daily cap (audit F-04). The claim is atomic, so two concurrent
    // starts for one id cannot both get through.
    const claimName = `web/${runId}/started.json`;
    let claimed;
    try {
      claimed = await L.claim(claimName, { runId });
    } catch (e) {
      // The write may have landed before the error. Under the lease nobody else can
      // have created it, so it is ours to remove; left behind, the id would answer
      // 409 forever for a run that never launched.
      owned.push(claimName);
      throw e;
    }
    if (!claimed) return { code: 409, body: { error: "this run has already been started" } };
    owned.push(claimName);

    // The daily cap is enforced here, at the moment compute is committed, not only
    // at /api/runs where a URL is handed out.
    const slot = await L.reserveSlot(runId);
    if (!slot) {
      return { code: 429, body: {
        error: `The daily limit of ${L.MAX_PER_DAY} runs has been reached. ` +
               `Your file is saved; try again tomorrow.` } };
    }
    owned.push(slot);

    await L.jobs().runJob({
      name: `projects/${L.PROJECT}/locations/${L.REGION}/jobs/${L.JOB}`,
      overrides: {
        containerOverrides: [{ env: [{ name: "RUN_ID", value: runId }] }],
      },
    });
    owned.length = 0;                     // launched: the claim and the slot are spent
    return { code: 202, body: { runId, state: "starting" } };
  } catch (e) {
    return { code: 500, body: { error: String((e && e.message) || e) } };
  } finally {
    // Nothing launched means nothing spent: give back the id and the slot.
    for (const name of owned) await L.release(name);
    await L.release(L.START_LEASE);
  }
}

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

    // Everything from the concurrency check to the launch happens under one lease,
    // so two starts for different ids cannot both see a free slot (see _lib.js).
    if (!(await L.acquireLease())) {
      return L.json(res, 429, {
        error: "Another reconstruction is starting right now. " +
               "Your file is saved; try again in a minute.",
      });
    }
    const out = await startUnderLease(runId);
    return L.json(res, out.code, out.body);
  } catch (e) {
    return L.json(res, 500, { error: String((e && e.message) || e) });
  }
};
