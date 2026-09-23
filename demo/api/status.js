// GET /api/status?id=<runId> -> the orchestrator's status.json, verbatim.
//
// Proxied rather than handed out as a signed URL: the file is small, the page polls it
// every five seconds, and a signed URL would expire mid-run and turn a live page into a
// dead one. Nothing is computed here. Everything the page shows is what the job wrote,
// which is the same rule the rest of this site follows.

const L = require("./_lib");

module.exports = async (req, res) => {
  try {
    const id = req.query && req.query.id;
    if (!L.isRunId(id)) return L.json(res, 400, { error: "bad id" });

    const file = L.bucket().file(`web/${id}/status.json`);
    const [exists] = await file.exists();
    if (!exists) {
      // The job takes a few seconds to cold-start before it writes anything. That is
      // not an error, and the page keeps polling.
      return L.json(res, 200, {
        runId: id,
        state: "starting",
        stages: [{ id: "boot", label: "Starting the pipeline", state: "running" }],
      });
    }
    const [buf] = await file.download();
    res.setHeader("content-type", "application/json");
    res.setHeader("cache-control", "no-store");
    return res.status(200).send(buf.toString("utf8"));
  } catch (e) {
    return L.json(res, 500, { error: String((e && e.message) || e) });
  }
};
