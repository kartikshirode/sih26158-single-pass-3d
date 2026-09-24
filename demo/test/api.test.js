// Upload API guards, against in-memory fakes of GCS and Cloud Run.
//
//   node --test "demo/test/*.test.js"
//
// No SDKs, no network, no credentials: _lib requires the GCP clients lazily and these
// tests inject fakes before any handler runs. Kept outside demo/api/ because Vercel
// would deploy any file in that folder as a public function.

process.env.MAX_RUNS_PER_DAY = "2";
process.env.MAX_UPLOAD_BYTES = String(600 * 1024 * 1024);

const test = require("node:test");
const assert = require("node:assert");

const L = require("../api/_lib");
const runs = require("../api/runs");
const start = require("../api/start");

// ---------------------------------------------------------------- fakes
function fakeBucket() {
  const objects = new Map();
  const signed = [];
  const file = (name) => ({
    async save(data, opts = {}) {
      const pre = opts.preconditionOpts || {};
      if (pre.ifGenerationMatch === 0 && objects.has(name)) {
        const e = new Error("precondition failed");
        e.code = 412;
        throw e;
      }
      objects.set(name, { data: String(data), size: String(data).length });
    },
    async download() {
      if (!objects.has(name)) {
        const e = new Error("not found");
        e.code = 404;
        throw e;
      }
      return [Buffer.from(objects.get(name).data)];
    },
    async delete() {
      objects.delete(name);
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

function setup({ running = 0, runJobFails = false } = {}) {
  const bucket = fakeBucket();
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
      async listExecutions() {
        return [Array.from({ length: running }, () => ({ completionTime: null }))];
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
  assert.deepStrictEqual(codes.sort(), [202, 409]);
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
