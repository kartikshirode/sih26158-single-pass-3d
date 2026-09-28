// The presentation page's hero: the drone's video wiped against the model, rendered from
// the camera's path at the same instant. The keyframes are only 5-7 a second, so the
// camera between them is interpolated (a centripetal spline through the positions, slerp
// for the turn) and the photo side plays the video itself, cut to the keyframes' crop.
// The model follows the video's clock frame by frame. Without a packed clip the photo
// side falls back to the nearest keyframe at or before the moment shown.

import {
  WebGLRenderer, Scene, PerspectiveCamera, MeshBasicMaterial, SRGBColorSpace,
  NoToneMapping, Color, Vector3, Matrix4, Quaternion, CatmullRomCurve3,
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
  set("factDuration", `${data.duration.toFixed(1)} s`);
  set("factKeyframes", String(s.keyframes));
  if (s.triangles) set("factTriangles", s.triangles.toLocaleString("en-GB"));
  set("factWall", `${Math.round(s.wall_s)} s`);
}

function sheet() {
  const sh = data.sheet, img = $("sheetImg");
  if (!sh || !img) { const band = $("sheet"); if (band) band.hidden = true; return; }
  img.src = sh.file;
  img.width = sh.width;
  img.height = sh.height;
  const unit = data.units === "metres" ? "m" : "model units";
  const across = (sh.extent[2] - sh.extent[0]).toFixed(1);
  $("sheetCaption").textContent = `The model seen straight down: its own texture, contours every ${sh.contour_interval} ${unit} from its heights (heavier every fifth), and the drone's path in black with a dot for each second. The sheet is ${across} ${unit} across.` +
    (sh.hatched_fraction ? ` Hatched, ${Math.round(sh.hatched_fraction * 100)}% of it: ground the photos only saw coarsely, where one pixel covers over four times the median, so measure there with care.` : "");
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

function flightPath(cams) {
  const keys = cams.map((c) => {
    const p = new Vector3(...c.p);
    const m = new Matrix4().lookAt(p, p.clone().add(new Vector3(...c.f)), new Vector3(...c.u));
    return { t: c.t, p, q: new Quaternion().setFromRotationMatrix(m), fovy: c.fovy };
  });
  // Neighbouring quaternions on the same side, or slerp takes the long way round.
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1].q, b = keys[i].q;
    if (a.dot(b) < 0) b.set(-b.x, -b.y, -b.z, -b.w);
  }
  const curve = keys.length > 1 ? new CatmullRomCurve3(keys.map((k) => k.p), false, "centripetal") : null;
  // The index of the last keyframe at or before t.
  const before = (t) => {
    let lo = 0, hi = keys.length - 1;
    if (t <= keys[0].t) return 0;
    if (t >= keys[hi].t) return hi;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (keys[mid].t <= t) lo = mid; else hi = mid; }
    return lo;
  };
  const place = (camera, t) => {
    const i = before(t), a = keys[i], b = keys[Math.min(i + 1, keys.length - 1)];
    const k = b === a ? 0 : Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t)));
    if (curve) camera.position.copy(curve.getPoint((i + k) / (keys.length - 1)));
    else camera.position.copy(a.p);
    camera.quaternion.slerpQuaternions(a.q, b.q, k);
    camera.fov = a.fovy + (b.fovy - a.fovy) * k;
    camera.updateProjectionMatrix();
    return i;
  };
  return { keys, before, place };
}

function start() {
  if (!data) {
    $("wipeNote").textContent = "No model packed. Run python tools/pack_site.py out/runs/<run> first.";
    return;
  }
  facts();
  sheet();
  wipe();

  const canvas = $("wipeModel");
  const renderer = new WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: false });
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = NoToneMapping;
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new Scene();
  scene.background = new Color(getComputedStyle(document.documentElement).getPropertyValue("--film").trim() || "#E8EDEB");
  const camera = new PerspectiveCamera(30, 3.2, 0.01, 1000);
  camera.near = 0.005 * Math.hypot(...[0, 1, 2].map((k) => data.bounds.max[k] - data.bounds.min[k]));

  const cams = data.cameras;
  const path = flightPath(cams);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let ready = false;
  let playing = !reduced, scrubbing = false;
  let t0 = performance.now(), base = 0;

  // The photo side: the packed clip if there is one, else the keyframe stills.
  let video = null;
  const img = $("wipeImg");
  if (data.clip) {
    video = document.createElement("video");
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    video.preload = "auto";
    video.setAttribute("muted", "");
    video.setAttribute("aria-label", "The drone video");
    video.src = data.clip.file;
    img.replaceWith(video);
    $("wipeNote").textContent = "The left side is the drone's own video. Its keyframes built the model; the evidence below scores the model against photos held back from the build.";
  } else {
    $("wipeNote").textContent = "These photos helped build the model. The evidence below scores it against photos held back from the build.";
  }
  const stills = video ? null : cams.map((c) => { const im = new Image(); im.decoding = "async"; im.src = c.file; return im; });
  const duration = () => (video && isFinite(video.duration) ? video.duration : data.duration);
  const now = () => {
    if (video) return video.currentTime;
    return playing ? (base + (performance.now() - t0) / 1000) % data.duration : base;
  };

  const size = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };

  let shownStill = -1, lastLabel = "";
  const draw = (t) => {
    const i = path.place(camera, t);
    if (stills && i !== shownStill) { img.src = stills[i].src; shownStill = i; }
    const label = `${t.toFixed(1)} s into the pass`;
    if (label !== lastLabel) { $("wipeTime").textContent = label; lastLabel = label; }
    if (!scrubbing) $("wipeScrub").value = String(Math.round((t / duration()) * 1000));
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
    draw(now());
  }, (err) => { $("wipeNote").textContent = `The model did not load: ${err && err.message ? err.message : err}`; });

  window.addEventListener("resize", () => { size(); draw(now()); });

  // One clock. With a clip it is the video's own, read on every frame the video presents,
  // so the model never runs ahead of or behind the picture beside it.
  if (video) {
    if (video.requestVideoFrameCallback) {
      const onFrame = (_, meta) => { draw(meta.mediaTime); video.requestVideoFrameCallback(onFrame); };
      video.requestVideoFrameCallback(onFrame);
    } else {
      const loop = () => { if (!video.paused) draw(video.currentTime); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }
    video.addEventListener("seeked", () => draw(video.currentTime));
    video.addEventListener("loadeddata", () => draw(video.currentTime));
  } else {
    const loop = () => { if (playing) draw(now()); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }

  const playBtn = $("wipePlay");
  const setPlaying = (p) => {
    if (!video) { base = now(); t0 = performance.now(); }
    playing = p;
    if (video) {
      if (p) video.play().catch(() => setPlaying(false));
      else video.pause();
    }
    playBtn.textContent = p ? "Pause the pass" : "Play the pass";
  };
  setPlaying(playing);
  playBtn.addEventListener("click", () => setPlaying(!playing));
  const scrub = $("wipeScrub");
  scrub.addEventListener("pointerdown", () => { scrubbing = true; });
  scrub.addEventListener("pointerup", () => { scrubbing = false; });
  scrub.addEventListener("input", (e) => {
    setPlaying(false);
    const t = (Number(e.target.value) / 1000) * duration();
    if (video) video.currentTime = t;
    else { base = t; draw(t); }
  });
}

start();
