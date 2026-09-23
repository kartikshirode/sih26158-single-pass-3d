// Shared plumbing for the upload API: credentials, limits, and the guardrails that
// make a fully public endpoint survivable.
//
// The endpoint is public by choice, so nothing here is access control. These are cost
// and capacity limits: one run is roughly 70 minutes of 8 vCPU on a real billing
// account, and two concurrent MVS runs would want 16 vCPU of asia-south1 quota.

const { Storage } = require("@google-cloud/storage");
// Two clients, deliberately. JobsClient starts a job; listing executions lives on
// ExecutionsClient, and calling it on JobsClient fails at runtime rather than at
// require time, so it only showed up against the deployed function.
const { JobsClient, ExecutionsClient } = require("@google-cloud/run").v2;

const BUCKET = process.env.GCS_BUCKET || "sih26158-mumbai";
const PROJECT = process.env.GCP_PROJECT || "agentbillboard";
const REGION = process.env.GCP_REGION || "asia-south1";
const JOB = process.env.RUN_JOB || "sih26158-run";

// Caps. MAX_BYTES and MAX_CONCURRENT are the ones that protect the bill; the rest
// mirror what run_upload.py enforces so the page and the job agree.
const MAX_BYTES = Number(process.env.MAX_UPLOAD_BYTES || 600 * 1024 * 1024);
const MAX_CONCURRENT = Number(process.env.MAX_CONCURRENT || 1);
const MAX_PER_DAY = Number(process.env.MAX_RUNS_PER_DAY || 12);
// A kill switch that needs no deploy: set PAUSED=1 in the Vercel dashboard and the
// endpoint stops accepting work within seconds, while runs already going finish.
const PAUSED = String(process.env.PAUSED || "") === "1";

function creds() {
  const raw = process.env.GCP_SA_KEY;
  if (!raw) throw new Error("GCP_SA_KEY is not set");
  const c = JSON.parse(raw);
  return { projectId: c.project_id, credentials: c };
}

let _storage, _jobs, _execs;
function storage() {
  if (!_storage) _storage = new Storage(creds());
  return _storage;
}
function jobs() {
  if (!_jobs) _jobs = new JobsClient(creds());
  return _jobs;
}
function execs() {
  if (!_execs) _execs = new ExecutionsClient(creds());
  return _execs;
}
function bucket() {
  return storage().bucket(BUCKET);
}

// A run id the caller cannot guess. Results are served from an unlisted URL rather
// than behind auth, so the id IS the capability and 128 bits of it is the point.
function newRunId() {
  return require("crypto").randomBytes(16).toString("hex");
}

function isRunId(s) {
  return typeof s === "string" && /^[0-9a-f]{32}$/.test(s);
}

// Counted from the platform rather than from a file we keep: two requests arriving
// together would both read the same stale count and both start a run.
async function runningCount() {
  const [list] = await execs().listExecutions({
    parent: `projects/${PROJECT}/locations/${REGION}/jobs/${JOB}`,
  });
  return list.filter((e) => !e.completionTime).length;
}

async function startedToday() {
  const [list] = await execs().listExecutions({
    parent: `projects/${PROJECT}/locations/${REGION}/jobs/${JOB}`,
  });
  const since = Date.now() - 24 * 3600 * 1000;
  return list.filter((e) => {
    const t = e.createTime && Number(e.createTime.seconds) * 1000;
    return t && t >= since;
  }).length;
}

function json(res, code, body) {
  res.setHeader("content-type", "application/json");
  res.setHeader("cache-control", "no-store");
  res.status(code).send(JSON.stringify(body));
}

module.exports = {
  BUCKET, PROJECT, REGION, JOB,
  MAX_BYTES, MAX_CONCURRENT, MAX_PER_DAY, PAUSED,
  storage, jobs, execs, bucket, newRunId, isRunId, runningCount, startedToday, json,
};
