// GET /api/status?id=<runId> -> the orchestrator's status.json.
//
// Proxied rather than handed out as a signed URL: the file is small, the page polls it
// every five seconds, and a signed URL would expire mid-run and turn a live page into a
// dead one. Everything the page shows is what the job wrote, which is the same rule the
// rest of this site follows, with one exception below.
//
// The exception: only the job writes status.json, and a job killed for memory or time
// cannot write "failed". Its last word is "running", and the page used to poll that
// forever (audit F-12). So while the file says the run is live, this asks Cloud Run
// whether the execution it names has ended, and if it has, says so. Nothing else is
// changed, and nothing is written back.

const L = require("./_lib");

const TERMINAL = ["done", "failed", "refused", "partial"];
// A start with no status file after this long did not cold-start slowly; it never ran.
const NEVER_STARTED_S = 15 * 60;

async function startedAgeSeconds(id) {
  try {
    const [buf] = await L.bucket().file(`web/${id}/started.json`).download();
    const at = Date.parse(JSON.parse(buf.toString()).at);
    return Number.isFinite(at) ? (Date.now() - at) / 1000 : null;
  } catch (_) {
    return null;
  }
}

function ended(d, message) {
  // A preview that landed before the job died is still a result.
  d.state = d.preview ? "partial" : "failed";
  d.error = { message, code: "WEB-ENDED" };
  (d.stages || []).forEach((s) => {
    if (s.state === "running") s.state = "failed";
  });
  return d;
}

module.exports = async (req, res) => {
  try {
    const id = req.query && req.query.id;
    if (!L.isRunId(id)) return L.json(res, 400, { error: "bad id" });

    const file = L.bucket().file(`web/${id}/status.json`);
    const [exists] = await file.exists();
    if (!exists) {
      const age = await startedAgeSeconds(id);
      if (age !== null && age > NEVER_STARTED_S) {
        return L.json(res, 200, ended(
          { runId: id, stages: [{ id: "boot", label: "Starting the pipeline",
                                  state: "running" }] },
          `The job was started ${Math.round(age / 60)} minutes ago and never ` +
          `reported. It did not run; your upload is still stored.`));
      }
      // The job takes a few seconds to cold-start before it writes anything. That is
      // not an error, and the page keeps polling.
      return L.json(res, 200, {
        runId: id,
        state: "starting",
        stages: [{ id: "boot", label: "Starting the pipeline", state: "running" }],
      });
    }
    const [buf] = await file.download();
    const d = JSON.parse(buf.toString("utf8"));

    if (!TERMINAL.includes(d.state) && d.execution) {
      let ex = null;
      try {
        ex = await L.execution(d.execution);
      } catch (_) {
        // Cannot ask the platform: fall back to what the job wrote.
      }
      if (ex && ex.completionTime) {
        return L.json(res, 200, ended(d,
          `The job stopped without finishing (Cloud Run ended execution ` +
          `${d.execution}). The usual cause is running out of memory or time.`));
      }
    }
    return L.json(res, 200, d);
  } catch (e) {
    return L.json(res, 500, { error: String((e && e.message) || e) });
  }
};
