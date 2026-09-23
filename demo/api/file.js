// GET /api/file?id=<runId>&p=<preview|final>/<name> -> redirect to a signed download.
//
// A redirect, not a proxy: the exports are tens to hundreds of megabytes and a Vercel
// function response is capped far below that. The signed URL is short-lived and scoped
// to the one object, so the run id stays the only capability a holder needs.

const L = require("./_lib");

module.exports = async (req, res) => {
  try {
    const id = req.query && req.query.id;
    const p = String((req.query && req.query.p) || "");
    if (!L.isRunId(id)) return L.json(res, 400, { error: "bad id" });

    // The path comes from the page, so it is constrained rather than trusted: one of
    // the two model labels, then a plain filename. No slashes, no traversal, no
    // reaching sideways into another run's prefix.
    const m = p.match(/^(preview|final)\/([A-Za-z0-9._-]{1,64})$/);
    if (!m) return L.json(res, 400, { error: "bad path" });

    // The orchestrator writes exports under out/<run><suffix>/export/. preview is the
    // feed-forward run (<id>3d) and final the MVS one (<id>mvs3d).
    const suffix = m[1] === "preview" ? "3d" : "mvs3d";
    const object = `web/${id}${suffix}/export/${m[2]}`;

    const file = L.bucket().file(object);
    const [exists] = await file.exists();
    if (!exists) return L.json(res, 404, { error: "no such file for this run" });

    const [url] = await file.getSignedUrl({
      version: "v4",
      action: "read",
      expires: Date.now() + 15 * 60 * 1000,
      responseDisposition: `attachment; filename="${m[2]}"`,
    });
    res.setHeader("cache-control", "no-store");
    res.writeHead(302, { Location: url });
    return res.end();
  } catch (e) {
    return L.json(res, 500, { error: String((e && e.message) || e) });
  }
};
