// Plan map of the pass: one orthographic top render at load, then the flight path, the
// view's ground footprint as a wedge and the playhead drawn over it on every render.
// The map is turned so the pass runs left to right; a small arrow marks north (-z) when
// the model is georeferenced.
import * as THREE from 'three';
import { cssVar } from './scene.js';

export function createMinimap(S, flight, nav) {
  const canvas = document.getElementById('minimap');
  const g = canvas.getContext('2d');
  const base = document.createElement('canvas');
  let W = 0, H = 0, dpr = 1;
  let scale = 1;            // map pixels per model unit
  const centre = new THREE.Vector3();
  let dir = new THREE.Vector3(1, 0, 0);    // world direction of map right
  let upDir = new THREE.Vector3(0, 0, -1); // world direction of map up
  const ink = cssVar('--ink'), magenta = cssVar('--magenta'), wash = cssVar('--magenta-wash');

  function toMap(p) {
    const dx = p.x - centre.x, dz = p.z - centre.z;
    return [W / 2 + (dx * dir.x + dz * dir.z) * scale, H / 2 - (dx * upDir.x + dz * upDir.z) * scale];
  }
  function toWorld(px, py) {
    const a = (px - W / 2) / scale, b = -(py - H / 2) / scale;
    return new THREE.Vector3(centre.x + dir.x * a + upDir.x * b, 0, centre.z + dir.z * a + upDir.z * b);
  }

  // The one-off orthographic render, copied out of the main canvas in the same task.
  function build() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(1, Math.round(canvas.clientWidth * dpr));
    H = Math.max(1, Math.round(canvas.clientHeight * dpr));
    canvas.width = W; canvas.height = H;
    base.width = W; base.height = H;

    const cams = flight.cams;
    if (cams.length > 1) {
      const a = cams[0].p, b = cams[cams.length - 1].p;
      dir = new THREE.Vector3(b.x - a.x, 0, b.z - a.z);
      if (dir.lengthSq() < 1e-9) dir.set(1, 0, 0);
      dir.normalize();
    }
    upDir = new THREE.Vector3(dir.z, 0, -dir.x);

    // Footprint of the mesh in the turned frame, from its vertices.
    let a0 = Infinity, a1 = -Infinity, b0 = Infinity, b1 = -Infinity;
    const v = new THREE.Vector3();
    for (const m of S.meshes) {
      const pos = m.geometry.attributes.position;
      const step = Math.max(1, Math.floor(pos.count / 60000));
      for (let i = 0; i < pos.count; i += step) {
        v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld);
        const a = v.x * dir.x + v.z * dir.z, b = v.x * upDir.x + v.z * upDir.z;
        if (a < a0) a0 = a; if (a > a1) a1 = a; if (b < b0) b0 = b; if (b > b1) b1 = b;
      }
    }
    const ca = (a0 + a1) / 2, cb = (b0 + b1) / 2;
    centre.set(dir.x * ca + upDir.x * cb, 0, dir.z * ca + upDir.z * cb);
    scale = Math.min((W * 0.94) / Math.max(a1 - a0, 1e-6), (H * 0.9) / Math.max(b1 - b0, 1e-6));

    const cam = new THREE.OrthographicCamera(-W / 2 / scale, W / 2 / scale, H / 2 / scale, -H / 2 / scale, 0.01, S.size.y * 4 + S.diag);
    cam.up.copy(upDir);
    cam.position.set(centre.x, S.bounds.max.y + S.size.y + S.diag * 0.1, centre.z);
    cam.lookAt(centre.x, S.bounds.min.y - 1, centre.z);

    const r = S.renderer;
    const bg = S.scene.background;
    const vis = [S.pathGroup.visible, S.overlayGroup.visible];
    const u = S.surfaceUniforms;
    const uv = [u.uTex.value, u.uContours.value, u.uDetail.value];
    S.scene.background = new THREE.Color(cssVar('--film'));
    S.pathGroup.visible = S.overlayGroup.visible = false;
    u.uContours.value = 0;
    u.uDetail.value = 0;
    if (S.meshes.some((m) => m.material.map)) u.uTex.value = 1;
    const pr = r.getPixelRatio();
    const buf = r.getDrawingBufferSize(new THREE.Vector2());
    r.setScissorTest(true);
    r.setViewport(0, 0, W / pr, H / pr);
    r.setScissor(0, 0, W / pr, H / pr);
    r.render(S.scene, cam);
    const bg2 = base.getContext('2d');
    bg2.drawImage(r.domElement, 0, buf.y - H, W, H, 0, 0, W, H);
    r.setScissorTest(false);
    r.setViewport(0, 0, buf.x / pr, buf.y / pr);
    S.scene.background = bg;
    [S.pathGroup.visible, S.overlayGroup.visible] = vis;
    [u.uTex.value, u.uContours.value, u.uDetail.value] = uv;
    S.requestRender();
    draw();
  }

  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
  function draw() {
    if (!W) return;
    g.clearRect(0, 0, W, H);
    g.drawImage(base, 0, 0);
    const cams = flight.cams;
    g.lineJoin = 'round';
    if (cams.length > 1) {
      g.beginPath();
      cams.forEach((c, i) => { const [x, y] = toMap(c.p); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      g.strokeStyle = ink;
      g.lineWidth = 1.4 * dpr;
      g.stroke();
    }
    // The view's ground footprint, as a wedge from the camera.
    const cam = S.camera;
    const gy = S.viewCentre().y;
    const pts = corners.map(([x, y]) => {
      const ray = S.rayFromNDC(x, y);
      const p = S.rayPlane(ray, gy);
      if (p && p.distanceTo(ray.origin) < S.diag * 1.5) return p;
      const flat = new THREE.Vector3(ray.direction.x, 0, ray.direction.z);
      if (flat.lengthSq() < 1e-9) flat.set(0, 0, -1);
      return ray.origin.clone().addScaledVector(flat.normalize(), S.diag * 1.5);
    });
    const cp = toMap(cam.position);
    const mp = pts.map(toMap);
    g.beginPath();
    g.moveTo(mp[0][0], mp[0][1]);
    for (let i = 1; i < 4; i++) g.lineTo(mp[i][0], mp[i][1]);
    g.closePath();
    g.fillStyle = wash;
    g.fill();
    g.beginPath();
    g.moveTo(mp[3][0], mp[3][1]); g.lineTo(cp[0], cp[1]); g.lineTo(mp[2][0], mp[2][1]);
    g.moveTo(mp[0][0], mp[0][1]); g.lineTo(mp[1][0], mp[1][1]); g.lineTo(mp[2][0], mp[2][1]); g.lineTo(mp[3][0], mp[3][1]); g.lineTo(mp[0][0], mp[0][1]);
    g.strokeStyle = magenta;
    g.lineWidth = 1.2 * dpr;
    g.stroke();
    g.beginPath();
    g.arc(cp[0], cp[1], 2.5 * dpr, 0, Math.PI * 2);
    g.fillStyle = magenta;
    g.fill();
    // Playhead: where the drone is at the current time.
    const s = flight.sample(flight.time);
    if (s) {
      const [x, y] = toMap(s.p);
      g.beginPath();
      g.arc(x, y, 4 * dpr, 0, Math.PI * 2);
      g.fillStyle = '#fff';
      g.fill();
      g.lineWidth = 2 * dpr;
      g.strokeStyle = magenta;
      g.stroke();
    }
    // North arrow: world -z turned into map pixels (map y grows downward). Only for a
    // georeferenced model: a levelled one knows up, not north.
    if (!(window.TESSERACT || {}).georef) return;
    const ux = -dir.z, uy = upDir.z;
    const ox = W - 16 * dpr, oy = 24 * dpr, L = 8 * dpr, hd = 4 * dpr, hw = 3 * dpr;
    g.save();
    g.translate(ox, oy);
    g.beginPath();
    g.moveTo(-ux * L, -uy * L);
    g.lineTo(ux * L, uy * L);
    g.strokeStyle = ink;
    g.lineWidth = 1.2 * dpr;
    g.stroke();
    g.beginPath();
    g.moveTo(ux * L, uy * L);
    g.lineTo(ux * (L - hd) - uy * hw, uy * (L - hd) + ux * hw);
    g.lineTo(ux * (L - hd) + uy * hw, uy * (L - hd) - ux * hw);
    g.closePath();
    g.fillStyle = ink;
    g.fill();
    g.font = `${10 * dpr}px Archivo, sans-serif`;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText('N', ux * (L + 6 * dpr), uy * (L + 6 * dpr));
    g.restore();
  }

  // Click or drag: move the view centre there, keeping height and heading.
  let dragging = false;
  function moveTo(e) {
    const r = canvas.getBoundingClientRect();
    const w = toWorld((e.clientX - r.left) * dpr, (e.clientY - r.top) * dpr);
    const c = S.viewCentre();
    S.camera.position.x += w.x - c.x;
    S.camera.position.z += w.z - c.z;
    S.requestRender();
  }
  canvas.addEventListener('pointerdown', (e) => {
    if (!W) return;
    dragging = true;
    canvas.setPointerCapture(e.pointerId);
    nav.userMoved();
    moveTo(e);
  });
  canvas.addEventListener('pointermove', (e) => { if (dragging) moveTo(e); });
  canvas.addEventListener('pointerup', () => { dragging = false; });
  canvas.addEventListener('pointercancel', () => { dragging = false; });

  return { build, draw };
}
