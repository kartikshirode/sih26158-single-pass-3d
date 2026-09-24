// Upload API guards, against in-memory fakes of GCS and Cloud Run.
//
//   node --test "demo/test/*.test.js"
//
// No SDKs, no network, no credentials: _lib requires the GCP clients lazily and these
// tests inject fakes before any handler runs. Kept outside demo/api/ because Vercel
// would deploy any file in that folder as a public function.

process.env.MAX_RUNS_PER_DAY = "2";
process.env.MAX_CONCURRENT = "3";
process.env.MAX_UPLOAD_BYTES = String(600 * 1024 * 1024);

const test = require("node:test");
const assert = require("node:assert");

const L = require("../api/_lib");
const runs = require("../api/runs");
const start = require("../api/start");
const status = require("../api/status");

// ---------------------------------------------------------------- fakes
function fakeBucket({ failSave = () => false } = {}) {
  const objects = new Map();
  const signed = [];
  let gen = 0;
  const pre412 = () => Object.assign(new Error("precondition failed"), { code: 412 });
  const file = (name) => ({
    async save(data, opts = {}) {
      const pre = opts.preconditionOpts || {};
      if (pre.ifGenerationMatch === 0 && objects.has(name)) throw pre412();
      objects.set(name, { data: String(data), size: String(data).length, generation: ++gen });
      // A write that lands and still errors, as a timeout after the upload can.
      if (failSave(name)) throw new Error(`storage timed out writing ${name}`);
    },
    async getMetadata() {
      if (!objects.has(name)) throw Object.assign(new Error("not found"), { code: 404 });
      return [{ generation: objects.get(name).generation }];
    },
    async download() {
      if (!objects.has(name)) {
        const e = new Error("not found");
        e.code = 404;
        throw e;
      }
      return [Buffer.from(objects.get(name).data)];
    },
    async delete(opts = {}) {
      if (opts.ifGenerationMatch !== undefined && objects.has(name) &&
          objects.get(name).generation !== opts.ifGenerationMatch) throw pre412();
      objects.delete(name);
    },
    async exists() {
      return [objects.has(name)];
    },
    async getSignedUrl(opts) {
      signed.push({ name, opts });
      return [`https://signed.example/${name}`];
    },
  });
  return {
    objects,
    signed,
    file,
    async getFiles({ prefix }) {
      const hits = [...objects.keys()].filter((k) => k.startsWith(prefix));
      return [hits.map((k) => ({ name: k, metadata: { size: objects.get(k).size } }))];
    },
  };
}

function setup({ running = 0, runJobFails = false, executions = {}, failSave } = {}) {
  const bucket = fakeBucket({ failSave });
  const launched = [];
  L._inject({
    storage: { bucket: () => bucket },
    jobs: {
      async runJob(req) {
        if (runJobFails) throw new Error("platform said no");
        launched.push(req);
        return [{}];
      },
    },
    execs: {
      // A launched execution is listed as running, as the platform lists it.
      async listExecutions() {
        return [Array.from({ length: running + launched.length },
                           () => ({ completionTime: null }))];
      },
      async getExecution({ name }) {
        const short = name.split("/").pop();
        if (!(short in executions)) throw new Error("not found");
        return [executions[short]];
      },
    },
  });
  return { bucket, launched };
}

function call(handler, body) {
  return new Promise((resolve, reject) => {
    const res = {
      code: 0,
      headers: {},
      setHeader(k, v) { this.headers[k] = v; },
      status(c) { this.code = c; return this; },
      send(s) { resolve({ code: this.code, body: JSON.parse(s) }); },
    };
    Promise.resolve(handler({ method: "POST", body }, res)).catch(reject);
  });
}

function get(handler, query) {
  return new Promise((resolve, reject) => {
    const res = {
      code: 0,
      setHeader() {},
      status(c) { this.code = c; return this; },
      send(s) { resolve({ code: this.code, body: JSON.parse(s) }); },
    };
    Promise.resolve(handler({ method: "GET", query }, res)).catch(reject);
  });
}

function writeStatus(bucket, runId, d) {
  bucket.objects.set(`web/${runId}/status.json`, { data: JSON.stringify(d), size: 1 });
}

function upload(bucket, runId) {
  bucket.objects.set(`web/${runId}/source.mp4`, { data: "x", size: 1 });
}

const ID_A = "a".repeat(32);
const ID_B = "b".repeat(32);
const ID_C = "c".repeat(32);

// ---------------------------------------------------------------- F-04
test("a run id starts once; a second start is refused", async () => {
  const { bucket, launched } = setup();
  upload(bucket, ID_A);
  assert.strictEqual((await call(start, { runId: ID_A })).code, 202);
  const again = await call(start, { runId: ID_A });
  assert.strictEqual(again.code, 409);
  assert.strictEqual(launched.length, 1);
});

test("two concurrent starts of one id launch one execution", async () => {
  const { bucket, launched } = setup();
  upload(bucket, ID_A);
  const codes = (await Promise.all([call(start, { runId: ID_A }),
                                    call(start, { runId: ID_A })])).map((r) => r.code);
  // The loser meets the start lease (429) or the run-id claim (409); either way one runs.
  assert.strictEqual(codes.filter((c) => c === 202).length, 1, String(codes));
  assert.ok(codes.every((c) => [202, 409, 429].includes(c)), String(codes));
  assert.strictEqual(launched.length, 1);
});

test("the daily cap is enforced at start, not only at /api/runs", async () => {
  const { bucket, launched } = setup();
  for (const id of [ID_A, ID_B, ID_C]) upload(bucket, id);
  assert.strictEqual((await call(start, { runId: ID_A })).code, 202);
  assert.strictEqual((await call(start, { runId: ID_B })).code, 202);
  const third = await call(start, { runId: ID_C });
  assert.strictEqual(third.code, 429);
  assert.strictEqual(launched.length, 2);
  // Refused for the cap, not because it was started: the claim was handed back.
  assert.ok(!bucket.objects.has(`web/${ID_C}/started.json`));
});

test("a failed launch gives back the claim and the slot", async () => {
  const first = setup({ runJobFails: true });
  upload(first.bucket, ID_A);
  assert.strictEqual((await call(start, { runId: ID_A })).code, 500);
  const left = [...first.bucket.objects.keys()].filter((k) => !k.endsWith("source.mp4"));
  assert.deepStrictEqual(left, []);
});

test("/api/runs reads the same slots /api/start fills", async () => {
  const { bucket } = setup();
  for (const id of [ID_A, ID_B]) upload(bucket, id);
  await call(start, { runId: ID_A });
  await call(start, { runId: ID_B });
  const r = await call(runs, { name: "clip.mp4", size: 10, type: "video/mp4" });
  assert.strictEqual(r.code, 429);
});

test("two starts for different ids cannot both take the last free slot", async () => {
  const { bucket, launched } = setup({ running: Number(L.MAX_CONCURRENT) - 1 });
  upload(bucket, ID_A);
  upload(bucket, ID_B);
  const codes = (await Promise.all([call(start, { runId: ID_A }),
                                    call(start, { runId: ID_B })])).map((r) => r.code);
  assert.deepStrictEqual(codes.sort(), [202, 429]);
  assert.strictEqual(launched.length, 1);
  assert.ok(!bucket.objects.has(L.START_LEASE), "the lease is released after the start");
});

test("a storage error while reserving the slot leaves the id startable", async () => {
  const { bucket, launched } = setup({ failSave: (n) => n.startsWith("web/_slots/") });
  upload(bucket, ID_A);
  assert.strictEqual((await call(start, { runId: ID_A })).code, 500);
  assert.ok(!bucket.objects.has(`web/${ID_A}/started.json`));
  assert.strictEqual(launched.length, 0);
});

test("a started.json write that landed and then errored is handed back", async () => {
  const { bucket } = setup({ failSave: (n) => n.endsWith("started.json") });
  upload(bucket, ID_A);
  assert.strictEqual((await call(start, { runId: ID_A })).code, 500);
  assert.ok(!bucket.objects.has(`web/${ID_A}/started.json`));
});

test("a fresh lease blocks a start; one left by a dead start is taken over", async () => {
  const { bucket, launched } = setup();
  upload(bucket, ID_A);
  const lease = (at) => bucket.objects.set(L.START_LEASE, {
    data: JSON.stringify({ at: new Date(at).toISOString() }), size: 1, generation: 999 });
  lease(Date.now());
  assert.strictEqual((await call(start, { runId: ID_A })).code, 429);
  assert.ok(!bucket.objects.has(`web/${ID_A}/started.json`));
  lease(Date.now() - 10 * 60 * 1000);
  assert.strictEqual((await call(start, { runId: ID_A })).code, 202);
  assert.strictEqual(launched.length, 1);
});

// ---------------------------------------------------------------- F-05
test("the upload URL carries a signed byte bound, and the page is told to send it", async () => {
  const { bucket } = setup();
  const r = await call(runs, { name: "clip.mp4", size: 1, type: "video/mp4" });
  assert.strictEqual(r.code, 200);
  const range = `0,${L.MAX_BYTES}`;
  assert.strictEqual(bucket.signed.length, 1);
  assert.deepStrictEqual(bucket.signed[0].opts.extensionHeaders,
                         { "x-goog-content-length-range": range });
  assert.strictEqual(r.body.uploadHeaders["x-goog-content-length-range"], range);
  assert.strictEqual(r.body.uploadHeaders["content-type"], "video/mp4");
});

test("the declared size is still checked before a URL is issued", async () => {
  setup();
  const r = await call(runs, { name: "clip.mp4", size: L.MAX_BYTES + 1, type: "video/mp4" });
  assert.strictEqual(r.code, 413);
});

// ---------------------------------------------------------------- F-12
const RUNNING = {
  runId: ID_A, state: "running", execution: "sih26158-run-abc12",
  stages: [{ id: "poses", state: "done" }, { id: "densify", state: "running" }],
};

test("a live execution leaves the job's own status untouched", async () => {
  const { bucket } = setup({ executions: { "sih26158-run-abc12": { completionTime: null } } });
  writeStatus(bucket, ID_A, RUNNING);
  const r = await get(status, { id: ID_A });
  assert.strictEqual(r.body.state, "running");
});

test("a killed worker is reported as ended, not running forever", async () => {
  const { bucket } = setup({
    executions: { "sih26158-run-abc12": { completionTime: { seconds: 1 }, failedCount: 1 } },
  });
  writeStatus(bucket, ID_A, RUNNING);
  const r = await get(status, { id: ID_A });
  assert.strictEqual(r.body.state, "failed");
  assert.strictEqual(r.body.error.code, "WEB-ENDED");
  assert.strictEqual(r.body.stages[1].state, "failed");
});

test("a killed worker that already published a preview is partial", async () => {
  const { bucket } = setup({
    executions: { "sih26158-run-abc12": { completionTime: { seconds: 1 } } },
  });
  writeStatus(bucket, ID_A, { ...RUNNING, preview: { points: 10, files: {} } });
  assert.strictEqual((await get(status, { id: ID_A })).body.state, "partial");
});

test("a terminal status is never second-guessed", async () => {
  const { bucket } = setup({
    executions: { "sih26158-run-abc12": { completionTime: { seconds: 1 } } },
  });
  writeStatus(bucket, ID_A, { ...RUNNING, state: "done" });
  assert.strictEqual((await get(status, { id: ID_A })).body.state, "done");
});

test("a start that never reported is failed after fifteen minutes", async () => {
  const { bucket } = setup();
  const old = new Date(Date.now() - 20 * 60 * 1000).toISOString();
  bucket.objects.set(`web/${ID_A}/started.json`,
                     { data: JSON.stringify({ runId: ID_A, at: old }), size: 1 });
  assert.strictEqual((await get(status, { id: ID_A })).body.state, "failed");
  const fresh = new Date().toISOString();
  bucket.objects.set(`web/${ID_B}/started.json`,
                     { data: JSON.stringify({ runId: ID_B, at: fresh }), size: 1 });
  assert.strictEqual((await get(status, { id: ID_B })).body.state, "starting");
});

test("an execution name from the bucket cannot reach an arbitrary resource path", async () => {
  const { bucket } = setup({ executions: { "x": { completionTime: { seconds: 1 } } } });
  writeStatus(bucket, ID_A, { ...RUNNING, execution: "../../other/x" });
  assert.strictEqual((await get(status, { id: ID_A })).body.state, "running");
});
