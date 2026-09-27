// The flight: keyframe interpolation, the chase camera, the strip of thumbnails, play,
// and the flight-path layer (camera centres, one tick a second, the current frustum).
import * as THREE from 'three';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { cssVar } from './scene.js';
import { clamp } from './geom.js';

const PLAY_SPEED = 2;

export function createFlight(S, T, nav) {
  const cams = (T.cameras || []).map((c) => {
    const f = new THREE.Vector3().fromArray(c.f).normalize();
    const u0 = new THREE.Vector3().fromArray(c.u);
    const r = new THREE.Vector3().crossVectors(f, u0).normalize();
    const u = new THREE.Vector3().crossVectors(r, f).normalize();
    const m = new THREE.Matrix4().makeBasis(r, u, f.clone().negate());
    return { t: +c.t, file: c.file, p: new THREE.Vector3().fromArray(c.p), q: new THREE.Quaternion().setFromRotationMatrix(m), fovy: c.fovy || 30, aspect: c.aspect || 1.5 };
  });
  const duration = T.duration || (cams.length ? cams[cams.length - 1].t : 0);
  let time = 0;
  let playing = false;
  let stopPlay = null;

  // Typical height of the drone above the surface sets the chase offset and frustum size.
  let hag = S.diag * 0.03;
  function measureHeightAboveGround() {
    const hs = [];
    for (let i = 0; i < cams.length; i += Math.max(1, Math.floor(cams.length / 30))) {
      const g = S.heightAt(cams[i].p.x, cams[i].p.z);
      if (!isNaN(g) && cams[i].p.y > g) hs.push(cams[i].p.y - g);
    }
    if (hs.length) { hs.sort((a, b) => a - b); hag = hs[hs.length >> 1]; }
  }

  function indexAt(t) {
    let lo = 0, hi = cams.length - 1;
    if (t <= cams[0].t) return 0;
    if (t >= cams[hi].t) return hi;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (cams[mid].t <= t) lo = mid; else hi = mid; }
    return lo;
  }
  // Position lerp and orientation slerp between the two keyframes around t.
  function sample(t) {
    if (!cams.length) return null;
    const i = indexAt(t);
    const a = cams[i], b = cams[Math.min(i + 1, cams.length - 1)];
    const span = b.t - a.t;
    const k = span > 0 ? clamp((t - a.t) / span, 0, 1) : 0;
    return { p: a.p.clone().lerp(b.p, k), q: a.q.clone().slerp(b.q, k), i, cam: a };
  }
  function nearest(t) {
    const i = indexAt(t);
    const j = Math.min(i + 1, cams.length - 1);
    return Math.abs(cams[j].t - t) < Math.abs(cams[i].t - t) ? cams[j] : cams[i];
  }

  // Behind and above the interpolated camera, looking where it looks.
  function chasePose(t) {
    const s = sample(t);
    if (!s) return null;
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(s.q);
    const flat = new THREE.Vector3(fwd.x, 0, fwd.z);
    if (flat.lengthSq() < 1e-6) flat.set(1, 0, 0);
    flat.normalize();
    const pos = s.p.clone().addScaledVector(flat, -hag * 1.1).add(new THREE.Vector3(0, hag * 0.45, 0));
    return { pos, q: s.q };
  }

  // ---- path layer ----
  const ink = cssVar('--ink');
  const magenta = cssVar('--magenta');
  const lineMats = [];
  function mat(color, width, opts = {}) {
    const m = new LineMaterial({ color, linewidth: width, ...opts });
    lineMats.push(m);
    return m;
  }
  const frustum = new LineSegments2(new LineSegmentsGeometry(), mat(magenta, 1.6, { depthTest: false, transparent: true }));
  frustum.renderOrder = 5;
  const playheadDot = new THREE.Points(
    new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)),
    new THREE.PointsMaterial({ color: magenta, size: 7, sizeAttenuation: false, depthTest: false, transparent: true }),
  );
  playheadDot.renderOrder = 5;
  function buildPath() {
    if (cams.length < 2) return;
    const pos = [];
    for (const c of cams) pos.push(c.p.x, c.p.y, c.p.z);
    const g = new LineGeometry();
    g.setPositions(pos);
    const line = new Line2(g, mat(ink, 1.4));
    const ticks = [];
    const tickLen = hag * 0.12;
    for (let s = 1; s < duration; s += 1) {
      const a = sample(s).p, b = sample(Math.min(s + 0.05, duration)).p;
      const dir = new THREE.Vector3(b.x - a.x, 0, b.z - a.z);
      if (dir.lengthSq() < 1e-12) dir.set(1, 0, 0);
      dir.normalize();
      const side = new THREE.Vector3(-dir.z, 0, dir.x).multiplyScalar(tickLen);
      ticks.push(a.x - side.x, a.y, a.z - side.z, a.x + side.x, a.y, a.z + side.z);
    }
    const tg = new LineSegmentsGeometry();
    tg.setPositions(ticks.length ? ticks : [0, 0, 0, 0, 0, 0]);
    const tickLines = new LineSegments2(tg, mat(ink, 1.4));
    S.pathGroup.add(line, tickLines, frustum, playheadDot);
  }
  function updateFrustum() {
    const s = sample(time);
    if (!s) return;
    const depth = hag * 0.5;
    const hh = Math.tan(THREE.MathUtils.degToRad(s.cam.fovy) / 2) * depth;
    const hw = hh * s.cam.aspect;
    const corners = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]].map(([x, y]) => new THREE.Vector3(x, y, -depth).applyQuaternion(s.q).add(s.p));
    const pos = [];
    for (let i = 0; i < 4; i++) {
      const c = corners[i], n = corners[(i + 1) % 4];
      pos.push(s.p.x, s.p.y, s.p.z, c.x, c.y, c.z, c.x, c.y, c.z, n.x, n.y, n.z);
    }
    frustum.geometry.dispose();
    frustum.geometry = new LineSegmentsGeometry();
    frustum.geometry.setPositions(pos);
    playheadDot.position.copy(s.p);
    frustum.visible = playheadDot.visible = !nav.isPilot();
  }

  // ---- strip ----
  const strip = document.getElementById('strip');
  const frames = document.getElementById('frames');
  const playhead = document.getElementById('playhead');
  const clock = document.getElementById('clock');
  const playBtn = document.getElementById('playBtn');
  function buildStrip() {
    frames.textContent = '';
    const n = Math.min(24, cams.length);
    for (let k = 0; k < n; k++) {
      const c = cams[Math.round((k / Math.max(n - 1, 1)) * (cams.length - 1))];
      const img = document.createElement('img');
      img.alt = '';
      img.draggable = false;
      img.decoding = 'async';
      img.onerror = () => { img.style.visibility = 'hidden'; };
      img.src = c.file;
      frames.appendChild(img);
    }
    strip.setAttribute('aria-valuemax', duration.toFixed(1));
  }
  function showTime() {
    const w = strip.clientWidth;
    playhead.style.left = `${duration > 0 ? (time / duration) * (w - 2) : 0}px`;
    clock.textContent = `${time.toFixed(1)} s`;
    strip.setAttribute('aria-valuenow', time.toFixed(1));
    strip.setAttribute('aria-valuetext', `${time.toFixed(1)} seconds of ${duration.toFixed(1)}`);
  }
  function setTime(t, follow = true) {
    time = clamp(t, 0, duration);
    showTime();
    updateFrustum();
    if (follow) {
      const pose = chasePose(time);
      if (pose) nav.setPose(pose.pos, pose.q, null, 'flight');
    }
    S.requestRender();
    api.onTime && api.onTime(time);
  }
  function timeFromEvent(e) {
    const r = strip.getBoundingClientRect();
    return clamp((e.clientX - r.left) / r.width, 0, 1) * duration;
  }
  let scrubbing = false;
  strip.addEventListener('pointerdown', (e) => {
    if (!cams.length) return;
    stop();
    scrubbing = true;
    strip.setPointerCapture(e.pointerId);
    setTime(timeFromEvent(e));
  });
  strip.addEventListener('pointermove', (e) => { if (scrubbing) setTime(timeFromEvent(e)); });
  const endScrub = () => { scrubbing = false; };
  strip.addEventListener('pointerup', endScrub);
  strip.addEventListener('pointercancel', endScrub);
  strip.addEventListener('keydown', (e) => {
    if (!cams.length) return;
    let t = null;
    const i = indexAt(time);
    if (e.key === 'ArrowRight') t = cams[Math.min(i + 1, cams.length - 1)].t;
    else if (e.key === 'ArrowLeft') t = cams[Math.max(cams[i].t < time - 1e-6 ? i : i - 1, 0)].t;
    else if (e.key === 'Home') t = 0;
    else if (e.key === 'End') t = duration;
    if (t === null) return;
    e.preventDefault();
    e.stopPropagation();
    stop();
    setTime(t);
  });

  function play() {
    if (!cams.length || playing) return;
    if (time >= duration - 1e-3) time = 0;
    playing = true;
    playBtn.textContent = 'Pause';
    playBtn.setAttribute('aria-pressed', 'true');
    stopPlay = S.animate((dt) => {
      if (!playing) return false;
      const t = time + dt * PLAY_SPEED;
      setTime(t);
      if (t >= duration) { stop(); return false; }
      return true;
    });
  }
  function stop() {
    if (!playing) return;
    playing = false;
    if (stopPlay) stopPlay();
    playBtn.textContent = 'Fly the pass';
    playBtn.setAttribute('aria-pressed', 'false');
  }
  playBtn.addEventListener('click', () => (playing ? stop() : play()));

  function setResolution(w, h) { for (const m of lineMats) m.resolution.set(w, h); }

  const api = {
    cams, duration, sample, nearest, chasePose, play, stop, setTime, setResolution,
    get time() { return time; },
    get playing() { return playing; },
    get hag() { return hag; },
    init() {
      measureHeightAboveGround();
      buildPath();
      buildStrip();
      updateFrustum();
      showTime();
    },
    refresh() { updateFrustum(); showTime(); },
    onTime: null,
  };
  return api;
}
