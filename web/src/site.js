// The presentation page's hero: each keyframe photo wiped against the model rendered
// from that keyframe's own camera. The photo is shown only at real keyframes, never at an
// interpolated pose, so the two halves are always the same moment from the same place.

import {
  WebGLRenderer, Scene, PerspectiveCamera, MeshBasicMaterial, SRGBColorSpace,
  NoToneMapping, Color, Vector3,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const data = window.TESSERACT;
const $ = (id) => document.getElementById(id);

function b64ToBuffer(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function facts() {
  const s = data.stats || {};
  const set = (id, text) => { const el = $(id); if (el && text) el.textContent = text; };
  set("factDuration", `${data.duration.toFixed(1)} s`);
  set("factKeyframes", String(s.keyframes));
  if (s.triangles) set("factTriangles", s.triangles.toLocaleString("en-GB"));
  set("factWall", `${Math.round(s.wall_s)} s`);
}

function sheet() {
  const sh = data.sheet, img = $("sheetImg");
  if (!sh || !img) { const band = $("sheet"); if (band) band.hidden = true; return; }
  img.src = sh.file;
  img.width = sh.width;
  img.height = sh.height;
  const unit = data.units === "metres" ? "m" : "model units";
  const across = (sh.extent[2] - sh.extent[0]).toFixed(1);
  $("sheetCaption").textContent = `The model seen straight down: its own texture, contours every ${sh.contour_interval} ${unit} from its heights (heavier every fifth), and the drone's path in black with a dot for each second. The sheet is ${across} ${unit} across.`;
}

function wipe() {
  const fig = $("wipe"), photo = $("wipePhoto"), handle = $("wipeHandle");
  let at = 50;
  const place = (pct) => {
    at = Math.min(100, Math.max(0, pct));
    photo.style.clipPath = `inset(0 ${100 - at}% 0 0)`;
    handle.style.left = `${at}%`;
    handle.setAttribute("aria-valuenow", String(Math.round(at)));
  };
  let dragging = false;
  const fromEvent = (e) => {
    const r = fig.getBoundingClientRect();
    place(((e.clientX - r.left) / r.width) * 100);
  };
  fig.addEventListener("pointerdown", (e) => { dragging = true; fig.setPointerCapture(e.pointerId); fromEvent(e); });
  fig.addEventListener("pointermove", (e) => { if (dragging) fromEvent(e); });
  fig.addEventListener("pointerup", () => { dragging = false; });
  handle.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") { place(at - 5); e.preventDefault(); }
    if (e.key === "ArrowRight") { place(at + 5); e.preventDefault(); }
  });
  place(50);
}

function start() {
  if (!data) {
    $("wipeNote").textContent = "No model packed. Run python tools/pack_site.py out/runs/<run> first.";
    return;
  }
  facts();
  sheet();
  wipe();
  $("wipeNote").textContent = "These photos helped build the model. The evidence below scores it against photos held back from the build.";

  const canvas = $("wipeModel");
  const renderer = new WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: false });
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = NoToneMapping;
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new Scene();
  scene.background = new Color(getComputedStyle(document.documentElement).getPropertyValue("--film").trim() || "#E8EDEB");
  const camera = new PerspectiveCamera(30, 3.2, 0.01, 1000);

  const cams = data.cameras;
  const photos = cams.map((c) => { const im = new Image(); im.decoding = "async"; im.src = c.file; return im; });
  let index = 0, playing = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let ready = false;

  const size = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };

  const show = (i) => {
    index = (i + cams.length) % cams.length;
    const c = cams[index];
    camera.fov = c.fovy;
    camera.near = 0.005 * Math.hypot(...[0, 1, 2].map((k) => data.bounds.max[k] - data.bounds.min[k]));
    camera.updateProjectionMatrix();
    camera.position.set(...c.p);
    camera.up.set(...c.u);
    camera.lookAt(new Vector3(...c.p).add(new Vector3(...c.f)));
    $("wipeImg").src = photos[index].src;
    $("wipeTime").textContent = `${c.t.toFixed(1)} s into the pass`;
    $("wipeScrub").value = String(Math.round((c.t / data.duration) * 1000));
    if (ready) renderer.render(scene, camera);
  };

  new GLTFLoader().parse(b64ToBuffer(data.glb), "", (gltf) => {
    const aniso = renderer.capabilities.getMaxAnisotropy();
    gltf.scene.traverse((o) => {
      if (!o.isMesh) return;
      const map = o.material.map;
      if (map) { map.colorSpace = SRGBColorSpace; map.anisotropy = aniso; map.needsUpdate = true; }
      o.material = new MeshBasicMaterial({ map, color: map ? 0xffffff : 0x9aa5a1 });
    });
    scene.add(gltf.scene);
    ready = true;
    size();
    show(index);
  }, (err) => { $("wipeNote").textContent = `The model did not load: ${err && err.message ? err.message : err}`; });

  window.addEventListener("resize", () => { size(); show(index); });

  // Keyframes are played at their own timestamps, looping.
  let t0 = performance.now(), base = 0;
  const tick = (now) => {
    if (playing && ready) {
      const t = (base + (now - t0) / 1000) % data.duration;
      let i = cams.findIndex((c) => c.t > t) - 1;
      if (i < 0) i = cams.length - 1;
      if (i !== index) show(i);
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  const playBtn = $("wipePlay");
  const setPlaying = (p) => {
    playing = p;
    playBtn.textContent = p ? "Pause the pass" : "Play the pass";
    t0 = performance.now();
    base = cams[index].t;
  };
  setPlaying(playing);
  playBtn.addEventListener("click", () => setPlaying(!playing));
  $("wipeScrub").addEventListener("input", (e) => {
    setPlaying(false);
    const t = (Number(e.target.value) / 1000) * data.duration;
    let best = 0;
    cams.forEach((c, i) => { if (Math.abs(c.t - t) < Math.abs(cams[best].t - t)) best = i; });
    show(best);
  });
}

start();
