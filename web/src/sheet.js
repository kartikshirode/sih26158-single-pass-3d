// The map sheet furniture: neatline graduations in plan view, a scale bar otherwise.
import * as THREE from 'three';
import { niceInterval } from './geom.js';
import { cssVar } from './scene.js';
import { fmtNice } from './units.js';

const GAP = 6; // the ticks canvas overhangs the inner neatline by this many CSS px

export function createSheet(S, nav, units) {
  const ticks = document.getElementById('ticks');
  const g = ticks.getContext('2d');
  const bar = document.getElementById('scalebar');
  const ink = cssVar('--ink'), paper = cssVar('--paper');
  let dpr = 1;
  let lastBar = '';

  function size() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    ticks.width = Math.round(ticks.clientWidth * dpr);
    ticks.height = Math.round(ticks.clientHeight * dpr);
  }

  // World units per CSS pixel at the depth of the view centre.
  function unitsPerPixel() {
    const c = S.viewCentre();
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(S.camera.quaternion);
    const depth = Math.max(c.clone().sub(S.camera.position).dot(fwd), 1e-9);
    const h = S.canvas.clientHeight || 1;
    return { upx: (2 * depth * Math.tan(THREE.MathUtils.degToRad(S.camera.fov) / 2)) / h, c };
  }

  function draw() {
    if (!ticks.width) size();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, ticks.width, ticks.height);
    const { upx, c } = unitsPerPixel();
    const f = units.factor;
    if (nav.isPlan()) {
      if (lastBar) { bar.textContent = ''; bar.hidden = true; lastBar = ''; }
      graduations(upx * f, c);
    } else {
      const target = 90 * upx * f;
      const L = niceInterval(target * 0.66);
      const px = L / (upx * f);
      const text = `about ${fmtNice(L)} ${units.unit()} at the centre of the view`;
      const key = `${Math.round(px)}|${text}`;
      if (key !== lastBar) {
        bar.hidden = false;
        bar.innerHTML = `<span style="display:block;background:rgba(245,247,246,0.86);padding:3px 6px 2px"><span style="display:block;margin-left:auto;width:${px.toFixed(1)}px;height:5px;border:1px solid var(--ink);border-top:0"></span><span>${text}</span></span>`;
        lastBar = key;
      }
    }
  }

  function graduations(dpu, c) {
    // dpu: display units per CSS pixel. Values along the screen axes, through the centre.
    const W = ticks.clientWidth - 2 * GAP, H = ticks.clientHeight - 2 * GAP;
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(S.camera.quaternion);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(S.camera.quaternion);
    right.y = 0; up.y = 0;
    right.normalize(); up.normalize();
    const f = units.factor;
    const cx = c.x * f, cz = c.z * f;
    const uC = cx * right.x + cz * right.z;
    const vC = cx * up.x + cz * up.z;
    const step = niceInterval(dpu * 9);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.strokeStyle = ink;
    g.lineWidth = 1;
    g.font = '10px Archivo, sans-serif';
    g.fillStyle = ink;
    const labels = [];
    // top and bottom: values along screen right
    const u0 = uC - (W / 2) * dpu, u1 = uC + (W / 2) * dpu;
    for (let k = Math.ceil(u0 / step); k * step <= u1; k++) {
      const x = GAP + (k * step - u0) / dpu;
      const isMajor = ((k % 5) + 5) % 5 === 0;
      const len = isMajor ? GAP - 1 : 2.5;
      g.beginPath();
      g.moveTo(x + 0.5, GAP); g.lineTo(x + 0.5, GAP - len);
      g.moveTo(x + 0.5, GAP + H); g.lineTo(x + 0.5, GAP + H + len);
      g.stroke();
      // labels only where the view buttons and the minimap leave room
      if (isMajor && x > GAP + 370 && x < GAP + W - 260) labels.push([fmtNice(k * step), x, GAP + 12, 'center']);
    }
    // left and right: values along screen up
    const v0 = vC - (H / 2) * dpu, v1 = vC + (H / 2) * dpu;
    for (let k = Math.ceil(v0 / step); k * step <= v1; k++) {
      const y = GAP + H - (k * step - v0) / dpu;
      const isMajor = ((k % 5) + 5) % 5 === 0;
      const len = isMajor ? GAP - 1 : 2.5;
      g.beginPath();
      g.moveTo(GAP, y + 0.5); g.lineTo(GAP - len, y + 0.5);
      g.moveTo(GAP + W, y + 0.5); g.lineTo(GAP + W + len, y + 0.5);
      g.stroke();
      if (isMajor && y > GAP + 64 && y < GAP + H - 56) labels.push([fmtNice(k * step), GAP + 4, y, 'left']);
    }
    g.textBaseline = 'middle';
    g.lineWidth = 3;
    g.strokeStyle = paper;
    for (const [t, x, y, align] of labels) {
      g.textAlign = align;
      g.strokeText(t, x, y);
      g.fillText(t, x, y);
    }
  }

  return { draw, size };
}
