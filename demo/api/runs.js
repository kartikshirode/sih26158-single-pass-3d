// POST /api/runs -> { runId, uploadUrl }
//
// The video never passes through this function. Vercel caps a request body at a few
// megabytes and these clips are hundreds, so the browser is handed a v4 signed URL and
// PUTs straight to GCS. That also keeps the footage in asia-south1 the whole way, which
// R-NF8 requires of imagery at or finer than 1 m.

const L = require("./_lib");

module.exports = async (req, res) => {
  if (req.method !== "POST") return L.json(res, 405, { error: "POST only" });
  try {
    if (L.PAUSED) {
      return L.json(res, 503, {
        error: "Uploads are paused right now. Nothing is wrong with your clip.",
      });
    }

    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body || {};
    const size = Number(body.size || 0);
    if (size > L.MAX_BYTES) {
      return L.json(res, 413, {
        error: `That file is ${(size / 1e6).toFixed(0)} MB. The limit is ` +
               `${(L.MAX_BYTES / 1e6).toFixed(0)} MB.`,
      });
    }

    // Capacity, checked before an upload rather than after: being told to come back
    // later after pushing 300 MB is a worse experience than being told now.
    const [running, today] = await Promise.all([L.runningCount(), L.startedToday()]);
    if (running >= L.MAX_CONCURRENT) {
      return L.json(res, 429, {
        error: `A reconstruction is already running, and this runs one at a time. ` +
               `Each takes about 70 minutes. Try again shortly.`,
      });
    }
    if (today >= L.MAX_PER_DAY) {
      return L.json(res, 429, {
        error: `The daily limit of ${L.MAX_PER_DAY} runs has been reached. ` +
               `This is a compute budget, not a queue.`,
      });
    }

    const runId = L.newRunId();
    const name = String(body.name || "source");
    const ext = (name.match(/\.[a-z0-9]{2,5}$/i) || [".mp4"])[0].toLowerCase();
    const object = `web/${runId}/source${ext}`;
    const contentType = String(body.type || "application/octet-stream");

    const [uploadUrl] = await L.bucket().file(object).getSignedUrl({
      version: "v4",
      action: "write",
      expires: Date.now() + 30 * 60 * 1000,
      contentType,
    });

    return L.json(res, 200, { runId, uploadUrl, object });
  } catch (e) {
    return L.json(res, 500, { error: String((e && e.message) || e) });
  }
};
