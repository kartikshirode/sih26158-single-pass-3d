// Navigation that travels the pass: grab-pan, turn about the point under the cursor,
// zoom toward the cursor, double-click to go there, WASD keys and the named views.
import * as THREE from 'three';
import { clamp, easeOutCubic } from './geom.js';
import { DEFAULT_FOV } from './scene.js';

const MIN_ELEVATION = Math.sin(THREE.MathUtils.degToRad(2));

export function createNav(S) {
  const { camera, canvas } = S;
  const euler = new THREE.Euler(0, 0, 0, 'YXZ');
  let viewName = null;
  let cancelAnim = null;
  const hooks = {
    grabHandle: () => false, dragHandle() {}, dropHandle() {}, click() {}, dblclick: () => false, hover() {},
    userMoved() {}, viewChanged() {},
  };

  function yawPitch() {
    euler.setFromQuaternion(camera.quaternion, 'YXZ');
    return { yaw: euler.y, pitch: euler.x };
  }
  function quatFrom(yaw, pitch) {
    return new THREE.Quaternion().setFromEuler(new THREE.Euler(pitch, yaw, 0, 'YXZ'));
  }
  function forwardOf(q) { return new THREE.Vector3(0, 0, -1).applyQuaternion(q); }

  function setView(name) {
    viewName = name;
    document.querySelectorAll('[data-view]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.view === name)));
    hooks.viewChanged(name);
  }
  function stopAnim() { if (cancelAnim) { cancelAnim(); cancelAnim = null; } }
  function userMoved() {
    stopAnim();
    if (viewName) setView(null);
    hooks.userMoved();
  }

  function setPose(pos, q, fov, name = null) {
    stopAnim();
    camera.position.copy(pos);
    camera.quaternion.copy(q);
    const f = fov || DEFAULT_FOV;
    if (camera.fov !== f) { camera.fov = f; camera.updateProjectionMatrix(); }
    if (name !== viewName) setView(name);
    S.requestRender();
  }

  function animateTo(pos, q, fov, ms = 400, name = null) {
    stopAnim();
    const p0 = camera.position.clone(), q0 = camera.quaternion.clone(), f0 = camera.fov;
    const f1 = fov || DEFAULT_FOV;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let el = 0;
    const dur = reduce ? 1 : ms / 1000;
    setView(name);
    cancelAnim = S.animate((dt) => {
      el += dt;
      const k = easeOutCubic(clamp(el / dur, 0, 1));
      camera.position.lerpVectors(p0, pos, k);
      camera.quaternion.slerpQuaternions(q0, q, k);
      camera.fov = f0 + (f1 - f0) * k;
      camera.updateProjectionMatrix();
      if (k >= 1) { cancelAnim = null; return false; }
      return true;
    });
  }

  // ---- pointer ----
  let drag = null;
  function planeFallback(ray) {
    const c = S.viewCentre();
    return S.rayPlane(ray, c.y) || c;
  }

  function pan(e) {
    const ray = S.rayFromClient(e.clientX, e.clientY);
    const p = S.rayPlane(ray, drag.grab.y);
    if (!p || p.distanceTo(ray.origin) > S.diag * 8) return;
    camera.position.x += drag.grab.x - p.x;
    camera.position.z += drag.grab.z - p.z;
  }

  function orbit(pivot, dx, dy) {
    const { yaw, pitch } = yawPitch();
    const h = canvas.clientHeight || 600;
    const dyaw = (-dx / h) * Math.PI * 0.9;
    let dp = (-dy / h) * Math.PI * 0.9;
    const qFrom = quatFrom(yaw, pitch).invert();
    const offset = camera.position.clone().sub(pivot);
    const len = offset.length();
    const elev0 = len > 1e-9 ? offset.y / len : 1;
    for (let tries = 0; tries < 7; tries++) {
      const p1 = clamp(pitch + dp, -Math.PI / 2 + 1e-4, Math.PI / 2 - 0.05);
      const q1 = quatFrom(yaw + dyaw, p1);
      const off = offset.clone().applyQuaternion(q1.clone().multiply(qFrom));
      const elev = len > 1e-9 ? off.y / len : 1;
      if (elev >= Math.min(MIN_ELEVATION, elev0) - 1e-9 || dp === 0) {
        camera.position.copy(pivot).add(off);
        camera.quaternion.copy(q1);
        return;
      }
      dp = tries >= 5 ? 0 : dp * 0.5;
    }
  }

  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('pointerdown', (e) => {
    canvas.focus && canvas.focus({ preventScroll: true });
    if (e.button === 0 && !e.ctrlKey && !e.metaKey && hooks.grabHandle(e)) {
      drag = { mode: 'handle', x0: e.clientX, y0: e.clientY, moved: false, button: 0 };
      canvas.setPointerCapture(e.pointerId);
      return;
    }
    const turn = e.button === 2 || (e.button === 0 && (e.ctrlKey || e.metaKey));
    const ray = S.rayFromClient(e.clientX, e.clientY);
    const hit = S.pickClient(e.clientX, e.clientY);
    const anchor = hit || planeFallback(ray);
    drag = { mode: turn ? 'orbit' : 'pan', x0: e.clientX, y0: e.clientY, lx: e.clientX, ly: e.clientY, moved: false, button: e.button, grab: anchor, pivot: anchor };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) { hooks.hover(e); return; }
    if (drag.mode === 'handle') { drag.moved = true; hooks.dragHandle(e); return; }
    if (!drag.moved && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) > 3) { drag.moved = true; userMoved(); }
    if (!drag.moved) return;
    if (drag.mode === 'pan') pan(e);
    else orbit(drag.pivot, e.clientX - drag.lx, e.clientY - drag.ly);
    drag.lx = e.clientX; drag.ly = e.clientY;
    S.requestRender();
  });
  const up = (e) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (d.mode === 'handle') { hooks.dropHandle(e); return; }
    if (!d.moved && d.button === 0 && !e.ctrlKey && !e.metaKey && e.type === 'pointerup') hooks.click(e);
  };
  canvas.addEventListener('pointerup', up);
  canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('dblclick', (e) => {
    e.preventDefault();
    if (hooks.dblclick(e)) return;
    flyToClient(e.clientX, e.clientY);
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    userMoved();
    const unit = e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1;
    const ray = S.rayFromClient(e.clientX, e.clientY);
    const target = S.pickClient(e.clientX, e.clientY) || S.rayPlane(ray, S.viewCentre().y) || ray.origin.clone().addScaledVector(ray.direction, S.diag * 0.2);
    const offset = camera.position.clone().sub(target);
    const d = offset.length();
    const k = Math.exp(clamp(e.deltaY * unit, -400, 400) * 0.0015);
    const nd = clamp(d * k, S.diag * 0.0015, S.diag * 4);
    camera.position.copy(target).addScaledVector(offset, nd / Math.max(d, 1e-9));
    S.requestRender();
  }, { passive: false });

  // Double-click: centre the point at a comfortable distance, 400 ms ease out.
  function flyToPoint(p) {
    let { yaw, pitch } = yawPitch();
    if (pitch > THREE.MathUtils.degToRad(-20)) pitch = THREE.MathUtils.degToRad(-35);
    const q = quatFrom(yaw, pitch);
    const d = clamp(camera.position.distanceTo(p) * 0.5, S.diag * 0.02, S.diag * 0.25);
    const pos = p.clone().addScaledVector(forwardOf(q), -d);
    userMoved();
    animateTo(pos, q, camera.fov, 400, null);
  }
  function flyToClient(x, y) {
    const p = S.pickClient(x, y);
    if (p) flyToPoint(p);
  }

  // ---- keys ----
  const held = new Set();
  let keyAnim = null;
  let fast = false;
  const MOVE_KEYS = new Set(['w', 'a', 's', 'd', 'q', 'e', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright']);
  function keyStep(dt) {
    if (!held.size) { keyAnim = null; return false; }
    const { yaw } = yawPitch();
    const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
    const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
    const ref = clamp(camera.position.distanceTo(S.viewCentre()), S.diag * 0.01, S.diag * 2);
    const v = ref * 0.8 * (fast ? 3 : 1) * dt;
    const m = new THREE.Vector3();
    if (held.has('w') || held.has('arrowup')) m.add(fwd);
    if (held.has('s') || held.has('arrowdown')) m.sub(fwd);
    if (held.has('d') || held.has('arrowright')) m.add(right);
    if (held.has('a') || held.has('arrowleft')) m.sub(right);
    if (m.lengthSq() > 0) m.normalize().multiplyScalar(v);
    if (held.has('e')) m.y += v;
    if (held.has('q')) m.y -= v;
    camera.position.add(m);
    return true;
  }
  function keyDown(key, shift) {
    fast = shift;
    if (!MOVE_KEYS.has(key)) return false;
    if (!held.has(key)) { held.add(key); userMoved(); }
    if (!keyAnim) keyAnim = S.animate(keyStep);
    return true;
  }
  function keyUp(key, shift) {
    fast = shift;
    held.delete(key);
  }
  function releaseAll() { held.clear(); }

  // ---- views ----
  let flight = null;
  function view(name) {
    const c = S.viewCentre();
    const { yaw } = yawPitch();
    const dist = Math.max(camera.position.distanceTo(c), S.diag * 0.02);
    hooks.userMoved();
    if (name === 'plan') {
      animateTo(c.clone().add(new THREE.Vector3(0, dist, 0)), quatFrom(yaw, -Math.PI / 2), DEFAULT_FOV, 400, 'plan');
    } else if (name === 'oblique') {
      const q = quatFrom(yaw, -Math.PI / 4);
      animateTo(c.clone().addScaledVector(forwardOf(q), -dist), q, DEFAULT_FOV, 400, 'oblique');
    } else if (name === 'pilot' && flight && flight.cams.length) {
      const k = flight.nearest(flight.time);
      animateTo(k.p.clone(), k.q.clone(), k.fovy, 400, 'pilot');
    } else if (name === 'fit') {
      const p = fitPose();
      animateTo(p.pos, p.q, DEFAULT_FOV, 400, 'fit');
    }
  }
  // From above and to the side, the pass running left to right, the whole box in frame.
  function fitPose() {
    let ax = 1, az = 0;
    if (flight && flight.cams.length > 1) {
      const a = flight.cams[0].p, b = flight.cams[flight.cams.length - 1].p;
      ax = b.x - a.x; az = b.z - a.z;
    } else if (S.size.z > S.size.x) { ax = 0; az = 1; }
    const l = Math.hypot(ax, az) || 1;
    ax /= l; az /= l;
    if (ax < 0) { ax = -ax; az = -az; }
    const yaw = Math.atan2(-az, ax);
    const pitch = THREE.MathUtils.degToRad(-40);
    const q = quatFrom(yaw, pitch);
    const fwd = forwardOf(q);
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(q);
    const upv = new THREE.Vector3(0, 1, 0).applyQuaternion(q);
    const tanV = Math.tan(THREE.MathUtils.degToRad(DEFAULT_FOV) / 2) * 0.9;
    const tanH = tanV * camera.aspect;
    // Frame the mesh itself (a sample of its vertices), not its bounding box.
    const pts = meshSample();
    let r0 = Infinity, r1 = -Infinity, u0 = Infinity, u1 = -Infinity;
    for (const v of pts) {
      const r = v.dot(right), u = v.dot(upv);
      if (r < r0) r0 = r; if (r > r1) r1 = r; if (u < u0) u0 = u; if (u > u1) u1 = u;
    }
    const c = new THREE.Vector3().addScaledVector(right, (r0 + r1) / 2).addScaledVector(upv, (u0 + u1) / 2);
    const mid = pts.reduce((s, v) => s + v.dot(fwd), 0) / Math.max(pts.length, 1);
    c.addScaledVector(fwd, mid);
    let d = 0;
    for (const v of pts) {
      const w = v.clone().sub(c);
      const zc = w.dot(fwd);
      d = Math.max(d, Math.abs(w.dot(right)) / tanH - zc, Math.abs(w.dot(upv)) / tanV - zc);
    }
    return { pos: c.addScaledVector(fwd, -d), q };
  }

  let sample = null;
  function meshSample() {
    if (sample) return sample;
    sample = [];
    for (const m of S.meshes) {
      const pos = m.geometry.attributes.position;
      const step = Math.max(1, Math.floor(pos.count / 8000));
      for (let i = 0; i < pos.count; i += step) sample.push(new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld));
    }
    if (!sample.length) sample.push(S.bounds.min.clone(), S.bounds.max.clone());
    return sample;
  }

  // Straight-down view, used by the neatline graduations.
  function isPlan() { return yawPitch().pitch < THREE.MathUtils.degToRad(-89); }

  return {
    hooks, setPose, animateTo, view, fitPose, flyToPoint, keyDown, keyUp, releaseAll, isPlan, yawPitch, userMoved,
    isPilot: () => viewName === 'pilot',
    get viewName() { return viewName; },
    set flight(f) { flight = f; },
    isDragging: () => !!drag,
  };
}
