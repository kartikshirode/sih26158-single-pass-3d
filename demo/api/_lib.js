// Shared plumbing for the upload API: credentials, limits, and the guardrails that
// make a fully public endpoint survivable.
//
// The endpoint is public by choice, so nothing here is access control. These are cost
// and capacity limits: one run is roughly 70 minutes of 8 vCPU on a real billing
// account, and two concurrent MVS runs would want 16 vCPU of asia-south1 quota.

// The GCP clients are required on first use, not at load, so the tests in demo/test/
// can run these handlers against in-memory fakes without the SDKs installed.
//
// Two Run clients, deliberately. JobsClient starts a job; listing executions lives on
// ExecutionsClient, and calling it on JobsClient fails at runtime rather than at
// require time, so it only showed up against the deployed function.

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
  if (!_storage) {
    const { Storage } = require("@google-cloud/storage");
    _storage = new Storage(creds());
  }
  return _storage;
}
function jobs() {
  if (!_jobs) {
    const { JobsClient } = require("@google-cloud/run").v2;
    _jobs = new JobsClient(creds());
  }
  return _jobs;
}
function execs() {
  if (!_execs) {
    const { ExecutionsClient } = require("@google-cloud/run").v2;
    _execs = new ExecutionsClient(creds());
  }
  return _execs;
}

// Tests only: swap in fakes for the three clients.
function _inject(c) {
  _storage = c.storage;
  _jobs = c.jobs;
  _execs = c.execs;
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

// Create an object only if nothing exists at that name. GCS applies the
// ifGenerationMatch=0 precondition atomically, so of two requests racing for the same
// name exactly one wins; that is what makes a run id or a daily slot claimable once.
// The nonce covers a retried write whose first attempt did land: the 412 it gets back
// is our own object, not someone else's.
async function claim(name, body) {
  const nonce = require("crypto").randomBytes(8).toString("hex");
  const file = bucket().file(name);
  try {
    await file.save(JSON.stringify({ ...body, nonce, at: new Date().toISOString() }), {
      contentType: "application/json",
      resumable: false,
      preconditionOpts: { ifGenerationMatch: 0 },
    });
    return true;
  } catch (e) {
    if (!e || e.code !== 412) throw e;
    try {
      const [buf] = await file.download();
      return JSON.parse(buf.toString()).nonce === nonce;
    } catch (_) {
      return false;
    }
  }
}

async function release(name) {
  try {
    await bucket().file(name).delete();
  } catch (_) {
    // A slot that cannot be released costs one start today; it is not worth a 500.
  }
}

// The daily cap is a set of numbered slot objects per UTC day, each claimable once.
// Counting executions could not enforce it: two starts read the same count before
// either launched, and a start never checked the count at all (audit F-04).
function slotPrefix() {
  return `web/_slots/${new Date().toISOString().slice(0, 10)}/`;
}

async function slotsUsedToday() {
  const [files] = await bucket().getFiles({ prefix: slotPrefix() });
  return files.length;
}

// Returns the slot's object name, or null when every slot today is taken.
async function reserveSlot(runId) {
  const prefix = slotPrefix();
  for (let n = 0; n < MAX_PER_DAY; n++) {
    const name = `${prefix}${String(n).padStart(3, "0")}.json`;
    if (await claim(name, { runId })) return name;
  }
  return null;
}

// The orchestrator execution a status file names, or null. Short names only, since the
// value comes from a file in the bucket and is spliced into a resource path.
async function execution(shortName) {
  if (typeof shortName !== "string" || !/^[a-z0-9-]{1,63}$/.test(shortName)) return null;
  const [ex] = await execs().getExecution({
    name: `projects/${PROJECT}/locations/${REGION}/jobs/${JOB}/executions/${shortName}`,
  });
  return ex;
}

function json(res, code, body) {
  res.setHeader("content-type", "application/json");
  res.setHeader("cache-control", "no-store");
  res.status(code).send(JSON.stringify(body));
}

module.exports = {
  BUCKET, PROJECT, REGION, JOB,
  MAX_BYTES, MAX_CONCURRENT, MAX_PER_DAY, PAUSED,
  storage, jobs, execs, bucket, newRunId, isRunId, runningCount,
  claim, release, slotsUsedToday, reserveSlot, execution, json, _inject,
};
