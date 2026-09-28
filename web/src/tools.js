// Measuring tools. Every point is a BVH raycast on the mesh and is kept in model units;
// readouts go through the units module so a new scale updates everything at once.
import * as THREE from 'three';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import * as G from './geom.js';
import { cssVar, cssColor } from './scene.js';
import { fmt, fmtNice } from './units.js';

export const TOOLS = {
  navigate: { title: 'Move', n: 0, help: 'Pick a tool on the left to measure. Everything is measured on the reconstructed surface, not on the screen.' },
  distance: { title: 'Distance', n: Infinity, min: 2, help: 'Click points along the line. Double-click or press Enter to finish.' },
  height: { title: 'Height', n: 2, help: 'Click two points. The readout is the vertical difference between them.' },
  area: { title: 'Area', n: Infinity, min: 3, help: 'Click the corners of the area. Double-click or press Enter to close it.' },
  volume: { title: 'Volume', n: Infinity, min: 3, help: 'Click around the heap or pit. Double-click or press Enter to close it, then choose the base.' },
  profile: { title: 'Profile', n: 2, help: 'Click the start and the end of the section. Hover the chart to find the place on the model.' },
  sight: { title: 'Line of sight', n: 2, help: 'Click where the observer stands, then click the target.' },
  point: { title: 'Coordinates', n: 1, help: 'Click a point to read its coordinates.' },
  note: { title: 'Note', n: 1, help: 'Click a point, type a short note and press Enter.' },
  calibrate: { title: 'Set scale', n: 2, help: 'Click both ends of the length you know.' },
};

const AREA_SAMPLES = 12000;
const VOLUME_SAMPLES = 40000;
const PROFILE_SAMPLES = 200;

const arr = (v) => [v.x, v.y, v.z];

export function createTools(S, units, T) {
  const magenta = cssVar('--magenta');
  const wash = cssColor('--magenta-wash');
  const $ = (id) => document.getElementById(id);
  const toolName = $('toolName'), toolHelp = $('toolHelp'), readout = $('readout'), chart = $('chart');
  const list = $('measureList'), empty = $('measureEmpty'), exportBtn = $('exportBtn');

  let tool = 'navigate';
  let draft = null;
  let measures = [];
  let selected = null;
  let dragging = null;
  let noteInput = null;
  let onCalibrated = null;
  let calibGroup = null;
  const counts = {};
  let nextId = 1;
  const resolution = new THREE.Vector2(1, 1);
  const lineMats = new Set();

  // ---- drawing helpers ----
  const handleTex = (() => {
    const c = document.createElement('canvas');
    c.width = c.height = 32;
    const g = c.getContext('2d');
    g.beginPath(); g.arc(16, 16, 12, 0, Math.PI * 2);
    g.fillStyle = '#ffffff'; g.fill();
    g.lineWidth = 5; g.strokeStyle = magenta; g.stroke();
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })();
  const dotTex = (() => {
    const c = document.createElement('canvas');
    c.width = c.height = 32;
    const g = c.getContext('2d');
    g.beginPath(); g.arc(16, 16, 13, 0, Math.PI * 2);
    g.fillStyle = magenta; g.fill();
    g.lineWidth = 3; g.strokeStyle = '#ffffff'; g.stroke();
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })();

  function mkLine(pts, o = {}) {
    const pos = [];
    for (const p of pts) pos.push(p.x, p.y, p.z);
    if (o.closed && pts.length > 2) pos.push(pts[0].x, pts[0].y, pts[0].z);
    if (pos.length < 6) return null;
    const g = new LineGeometry();
    g.setPositions(pos);
    const m = new LineMaterial({
      color: o.color || magenta, linewidth: o.width || 2, dashed: !!o.dashed, transparent: true,
      opacity: o.opacity ?? 1, depthTest: !!o.depth, depthWrite: false,
    });
    if (o.dashed) {
      let len = 0;
      for (let i = 1; i < pts.length; i++) len += pts[i].distanceTo(pts[i - 1]);
      m.dashSize = Math.max(len / 36, 1e-6);
      m.gapSize = m.dashSize * 0.8;
    }
    m.resolution.copy(resolution);
    lineMats.add(m);
    const l = new Line2(g, m);
    if (o.dashed) l.computeLineDistances();
    l.renderOrder = 10;
    return l;
  }
  function mkPoints(pts, big) {
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const m = new THREE.PointsMaterial({ map: handleTex, size: big ? 13 : 10, sizeAttenuation: false, transparent: true, depthTest: false, alphaTest: 0.2 });
    const p = new THREE.Points(g, m);
    p.renderOrder = 12;
    return p;
  }
  function mkFill(pts, o = {}) {
    if (pts.length < 3) return null;
    const contour = pts.map((p) => new THREE.Vector2(p.x, p.z));
    let faces;
    try { faces = THREE.ShapeUtils.triangulateShape(contour, []); } catch (e) { return null; }
    const pos = [];
    for (const p of pts) pos.push(p.x, o.y ?? p.y, p.z);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(faces.flat());
    const m = new THREE.MeshBasicMaterial({
      color: o.color || wash.color, transparent: true, opacity: o.opacity ?? wash.alpha,
      depthTest: !!o.depth, depthWrite: false, side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(g, m);
    mesh.renderOrder = 9;
    return mesh;
  }
  function disposeGroup(g) {
    if (!g) return;
    g.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) { lineMats.delete(o.material); o.material.dispose(); }
    });
    g.removeFromParent();
  }
  function addAll(group, items) { for (const it of items) if (it) group.add(it); }

  // Probe dot for the profile chart hover.
  const probe = new THREE.Points(
    new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)),
    new THREE.PointsMaterial({ map: dotTex, size: 14, sizeAttenuation: false, transparent: true, depthTest: false, alphaTest: 0.2 }),
  );
  probe.renderOrder = 13;
  probe.visible = false;
  S.overlayGroup.add(probe);

  // ---- labels in the view ----
  const layer = document.createElement('div');
  layer.setAttribute('aria-hidden', 'true');
  layer.style.cssText = 'position:absolute;inset:0;overflow:hidden;pointer-events:none';
  S.canvas.insertAdjacentElement('afterend', layer);
  function mkLabel() {
    const el = document.createElement('div');
    el.style.cssText = 'position:absolute;left:0;top:0;padding:1px 6px;font-size:12px;line-height:18px;white-space:nowrap;border:1px solid var(--magenta);background:rgba(245,247,246,0.92);color:var(--ink);border-radius:2px;will-change:transform';
    layer.appendChild(el);
    return el;
  }
  const proj = new THREE.Vector3();
  function placeLabels() {
    const w = S.canvas.clientWidth, h = S.canvas.clientHeight;
    for (const m of measures) {
      if (!m.labelEl) continue;
      proj.copy(m.anchor).project(S.camera);
      const off = proj.z > 1 || proj.z < -1 || Math.abs(proj.x) > 1.2 || Math.abs(proj.y) > 1.2;
      m.labelEl.style.display = off ? 'none' : '';
      if (off) continue;
      const x = (proj.x * 0.5 + 0.5) * w, y = (-proj.y * 0.5 + 0.5) * h;
      m.labelEl.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, calc(-100% - 10px))`;
    }
  }
  S.afterRender.push(placeLabels);

  // ---- kinds ----
  function eyeHeight() {
    return units.isMetric() ? 1.7 / units.factor : 0.017 * S.diag;
  }
  const L = (v) => ({ text: fmt(units.len(v)), unit: units.unit() });
  const A = (v) => ({ text: fmt(units.area(v)), unit: units.unit(2) });
  const V = (v) => ({ text: fmt(units.vol(v)), unit: units.unit(3) });
  const Y = (v) => L(v); // heights share the length scale (origin is the model frame's)

  function sampleHeights(grid) {
    const h = new Float64Array(grid.nx * grid.nz).fill(NaN);
    for (let j = 0; j < grid.nz; j++) for (let i = 0; i < grid.nx; i++) {
      const k = j * grid.nx + i;
      if (grid.inside[k]) h[k] = S.heightAt(G.gridX(grid, i), G.gridZ(grid, j));
    }
    return h;
  }

  const KINDS = {
    distance: {
      compute(m) { m.r = G.polylineStats(m.pts.map(arr)); },
      rows(m) {
        const r = m.r;
        const rows = [
          { label: 'Length', ...L(r.length), lead: true },
          { label: 'Horizontal', ...L(r.horizontal) },
          { label: 'Height difference', ...L(r.dh) },
          { label: 'Average slope', text: fmt(r.slopePct, 1), unit: '%' },
        ];
        if (r.segments.length > 1) {
          r.segments.slice(0, 5).forEach((s, i) => rows.push({ label: `Segment ${i + 1}`, ...L(s), small: true }));
          if (r.segments.length > 5) rows.push({ label: `and ${r.segments.length - 5} more segments`, text: "", unit: "", small: true });
        }
        return rows;
      },
      lead(m) { return L(m.r.length); },
      draw(m, sel) { return [mkLine(m.pts, { width: sel ? 3 : 2 }), mkPoints(m.pts, sel)]; },
      anchor(m) { return m.pts[m.pts.length - 1]; },
    },
    height: {
      compute(m) {
        const [a, b] = m.pts;
        const hi = a.y >= b.y ? a : b, lo = hi === a ? b : a;
        m.r = { dv: hi.y - lo.y, horizontal: G.distPlan3(arr(a), arr(b)), direct: a.distanceTo(b), hi, lo };
      },
      rows(m) {
        return [
          { label: 'Vertical difference', ...L(m.r.dv), lead: true },
          { label: 'Horizontal offset', ...L(m.r.horizontal) },
          { label: 'Straight line', ...L(m.r.direct) },
        ];
      },
      lead(m) { return L(m.r.dv); },
      draw(m, sel) {
        const { hi, lo } = m.r;
        const foot = new THREE.Vector3(hi.x, lo.y, hi.z);
        return [mkLine([hi, foot], { width: sel ? 3 : 2 }), mkLine([foot, lo], { width: 1.5, dashed: true }), mkPoints(m.pts, sel)];
      },
      anchor(m) { return new THREE.Vector3(m.r.hi.x, (m.r.hi.y + m.r.lo.y) / 2, m.r.hi.z); },
    },
    area: {
      compute(m, full) {
        const poly = m.pts.map((p) => [p.x, p.z]);
        m.r = m.r || {};
        m.r.plan = G.planArea(poly);
        m.r.perimeter = G.polylineLength(m.pts.map(arr), true);
        if (full) {
          const grid = G.polygonGrid(poly, AREA_SAMPLES);
          const h = sampleHeights(grid);
          m.r.surface = m.r.plan * G.gridSurfaceFactor(grid, h);
          m.r.missing = countMissing(grid, h);
        }
      },
      rows(m) {
        const rows = [
          { label: 'Plan area', ...A(m.r.plan), lead: true },
          { label: 'Surface area', ...A(m.r.surface) },
          { label: 'Perimeter', ...L(m.r.perimeter) },
        ];
        if (m.r.missing) rows.push(missingRow(m.r.missing));
        return rows;
      },
      lead(m) { return A(m.r.plan); },
      draw(m, sel) { return [mkFill(m.pts), mkLine(m.pts, { closed: true, width: sel ? 3 : 2 }), mkPoints(m.pts, sel)]; },
      anchor: centroid,
    },
    volume: {
      compute(m, full) {
        const poly = m.pts.map((p) => [p.x, p.z]);
        m.r = m.r || {};
        m.r.plan = G.planArea(poly);
        if (full || !m.cache) {
          const grid = G.polygonGrid(poly, VOLUME_SAMPLES);
          const h = sampleHeights(grid);
          const ring = G.resampleRing(poly, 240).map(([x, z]) => S.heightAt(x, z)).filter((v) => !isNaN(v));
          const edge = ring.length ? ring : m.pts.map((p) => p.y);
          m.cache = {
            grid, h,
            edgeMin: Math.min(...edge),
            edgeMean: edge.reduce((s, v) => s + v, 0) / edge.length,
          };
        }
        if (!m.baseMode) m.baseMode = 'average';
        const c = m.cache;
        const base = m.baseMode === 'lowest' ? c.edgeMin : m.baseMode === 'typed' && isFinite(m.typedBase) ? m.typedBase : c.edgeMean;
        m.r.base = base;
        const cell = c.grid.count ? m.r.plan / c.grid.count : 0;
        Object.assign(m.r, G.gridVolume(c.grid, c.h, base, cell));
      },
      rows(m) {
        const rows = [
          { label: 'Net volume', ...V(m.r.net), lead: true },
          { label: 'Cut above the base', ...V(m.r.cut) },
          { label: 'Fill below the base', ...V(m.r.fill) },
          { label: 'Base height', ...Y(m.r.base) },
        ];
        if (m.r.missing) rows.push(missingRow(m.r.missing));
        return rows;
      },
      lead(m) { return V(m.r.net); },
      draw(m, sel) {
        const base = m.pts.map((p) => new THREE.Vector3(p.x, m.r.base, p.z));
        return [
          mkFill(m.pts, { y: m.r.base, color: new THREE.Color(magenta), opacity: 0.22, depth: true }),
          mkLine(base, { closed: true, width: 1.5, dashed: true }),
          mkLine(m.pts, { closed: true, width: sel ? 3 : 2 }),
          mkPoints(m.pts, sel),
        ];
      },
      anchor: centroid,
      extra: volumeBaseUI,
    },
    profile: {
      compute(m, full) {
        const [a, b] = m.pts;
        const flat = G.resampleSegment([a.x, a.z], [b.x, b.z], PROFILE_SAMPLES);
        const dists = flat.map(([x, z]) => Math.hypot(x - a.x, z - a.z));
        let heights;
        if (full || !m.samples) heights = flat.map(([x, z]) => S.heightAt(x, z));
        else heights = flat.map((_, i) => a.y + ((b.y - a.y) * i) / (PROFILE_SAMPLES - 1));
        m.samples = flat.map(([x, z], i) => ({ x, z, y: heights[i], d: dists[i] }));
        m.r = G.profileStats(dists, heights);
      },
      rows(m) {
        return [
          { label: 'Length', ...L(m.r.length), lead: true },
          { label: 'Climb', ...L(m.r.climb) },
          { label: 'Descent', ...L(m.r.descent) },
          { label: 'Highest', ...Y(m.r.max) },
          { label: 'Lowest', ...Y(m.r.min) },
        ];
      },
      lead(m) { return L(m.r.length); },
      draw(m, sel) {
        const lift = S.diag * 0.0005;
        const pts = m.samples.filter((s) => !isNaN(s.y)).map((s) => new THREE.Vector3(s.x, s.y + lift, s.z));
        return [mkLine(pts, { width: sel ? 3 : 2 }), mkPoints(m.pts, sel)];
      },
      anchor(m) { return m.pts[1]; },
    },
    sight: {
      compute(m) {
        const [o, t] = m.pts;
        const eyeH = eyeHeight();
        const eye = o.clone().add(new THREE.Vector3(0, eyeH, 0));
        const dir = t.clone().sub(eye);
        const total = dir.length();
        dir.normalize();
        const tol = Math.max(total * 0.004, S.diag * 1e-4);
        const hit = total > 0 ? S.castRay(eye, dir, Math.max(total - tol, 0)) : null;
        const blocked = !!hit;
        m.r = { eye, eyeH, total, blocked, at: blocked ? hit.distance : null, hitPoint: blocked ? hit.point.clone() : null };
      },
      rows(m) {
        const eyeText = units.isMetric()
          ? { text: '1.7', unit: 'm' }
          : { text: fmt(m.r.eyeH), unit: 'units', note: 'no scale yet: 1.7% of the model’s horizontal diagonal stands in for 1.7 m' };
        return [
          { label: 'Target is', text: m.r.blocked ? 'Blocked' : 'Visible', unit: '', lead: true },
          { label: 'Eye to target', ...L(m.r.total) },
          { label: 'First obstruction', ...(m.r.blocked ? L(m.r.at) : { text: 'none', unit: '' }) },
          { label: 'Eye height', ...eyeText },
        ];
      },
      lead(m) { return { text: m.r.blocked ? 'Blocked' : 'Visible', unit: '' }; },
      draw(m, sel) {
        const { eye, hitPoint } = m.r;
        const t = m.pts[1];
        const w = sel ? 3 : 2;
        const items = [mkLine([m.pts[0], eye], { width: 1.5 })];
        if (hitPoint) {
          items.push(mkLine([eye, hitPoint], { width: w }), mkLine([hitPoint, t], { width: w * 0.8, dashed: true }));
          const dot = new THREE.Points(new THREE.BufferGeometry().setFromPoints([hitPoint]),
            new THREE.PointsMaterial({ map: dotTex, size: 11, sizeAttenuation: false, transparent: true, depthTest: false, alphaTest: 0.2 }));
          dot.renderOrder = 13;
          items.push(dot);
        } else {
          items.push(mkLine([eye, t], { width: w }));
        }
        items.push(mkPoints(m.pts, sel));
        return items;
      },
      anchor(m) { return m.r.eye; },
    },
    point: {
      compute(m) { m.r = { p: m.pts[0].clone(), detail: S.detailAt(m.pts[0]) }; },
      rows(m) {
        const p = m.r.p;
        const rows = [
          { label: T.georef ? 'East' : 'Grid x', ...L(p.x) },
          { label: T.georef ? 'North' : 'Grid y', ...L(-p.z) },
          { label: 'Height', ...Y(p.y), lead: true },
        ];
        const d = m.r.detail;
        if (d) {
          if (d.seen) { const s = units.small(d.value); rows.push({ label: 'Detail here', text: s.text, unit: `${s.unit} per pixel` }); }
          else rows.push({ label: 'Detail here', text: 'not seen', unit: '', note: 'No keyframe saw this face inside its frame.' });
        }
        if (T.georef) {
          const g = G.localToLatLon(units.len(p.x), units.len(p.y), units.len(p.z), T.georef);
          rows.push({ label: 'Latitude', text: g.lat.toFixed(7), unit: '°' });
          rows.push({ label: 'Longitude', text: g.lon.toFixed(7), unit: '°' });
          // The local height is already above; this one says what it is measured from.
          if (T.georef.height_note) rows.push({ label: 'Height is above', text: 'take-off', unit: '', note: T.georef.height_note });
          else rows.push({ label: 'Ellipsoid height', text: fmt(g.h), unit: 'm' });
        }
        return rows;
      },
      lead(m) { return Y(m.r.p.y); },
      draw(m, sel) { return [mkPoints(m.pts, sel)]; },
      anchor(m) { return m.pts[0]; },
    },
    note: {
      compute(m) { m.r = { p: m.pts[0].clone() }; },
      rows(m) {
        return [
          { label: 'Note', text: m.text, unit: '', textBlock: true },
          { label: 'Height', ...Y(m.r.p.y) },
        ];
      },
      lead(m) { return { text: firstWords(m.text), unit: '' }; },
      draw(m, sel) { return [mkPoints(m.pts, sel)]; },
      anchor(m) { return m.pts[0]; },
      label(m) { return firstWords(m.text); },
    },
  };

  function centroid(m) {
    const c = new THREE.Vector3();
    for (const p of m.pts) c.add(p);
    return c.multiplyScalar(1 / m.pts.length);
  }
  function countMissing(grid, h) {
    let n = 0;
    for (let k = 0; k < h.length; k++) if (grid.inside[k] && isNaN(h[k])) n++;
    return n;
  }
  function missingRow(n) { return { label: 'Samples off the model', text: String(n), unit: '', small: true }; }
  function firstWords(t) {
    const words = String(t || '').trim().split(/\s+/).slice(0, 4).join(' ').replace(/[,;:.]+$/, '');
    return words.length > 28 ? `${words.slice(0, 27)}…` : words;
  }

  // ---- measurements ----
  function create(kind, pts, extra = {}) {
    counts[kind] = (counts[kind] || 0) + 1;
    const m = { id: nextId++, kind, name: `${TOOLS[kind].title} ${counts[kind]}`, pts: pts.map((p) => p.clone()), ...extra };
    KINDS[kind].compute(m, true);
    measures.push(m);
    const li = document.createElement('li');
    li.dataset.id = String(m.id);
    li.innerHTML = '<strong></strong><span></span><button type="button">×</button>';
    li.querySelector('button').setAttribute('aria-label', `Delete ${m.name}`);
    m.li = li;
    list.appendChild(li);
    m.labelEl = mkLabel();
    redraw(m);
    updateListState();
    select(m);
    return m;
  }
  function redraw(m) {
    disposeGroup(m.group);
    const K = KINDS[m.kind];
    m.group = new THREE.Group();
    addAll(m.group, K.draw(m, m === selected));
    S.overlayGroup.add(m.group);
    m.anchor = K.anchor(m).clone();
    const lead = K.lead(m);
    const text = K.label ? K.label(m) : `${lead.text}${lead.unit ? ` ${lead.unit}` : ''}`;
    m.labelEl.textContent = text;
    const sel = m === selected;
    m.labelEl.style.background = sel ? 'var(--magenta)' : 'rgba(245,247,246,0.92)';
    m.labelEl.style.color = sel ? '#fff' : 'var(--ink)';
    m.li.querySelector('strong').textContent = m.name;
    m.li.querySelector('span').textContent = `${lead.text}${lead.unit ? ` ${lead.unit}` : ''}`;
    m.li.classList.toggle('is-selected', sel);
    S.requestRender();
  }
  function remove(m) {
    disposeGroup(m.group);
    m.labelEl.remove();
    m.li.remove();
    measures = measures.filter((x) => x !== m);
    if (selected === m) { selected = null; probe.visible = false; showPanel(); }
    updateListState();
    S.requestRender();
  }
  function updateListState() {
    empty.hidden = measures.length > 0;
    exportBtn.disabled = measures.length === 0;
  }
  function select(m) {
    const prev = selected;
    selected = m;
    if (prev && prev !== m && measures.includes(prev)) redraw(prev);
    if (m) redraw(m);
    probe.visible = false;
    showPanel();
  }

  list.addEventListener('click', (e) => {
    const li = e.target.closest('li');
    if (!li) return;
    const m = measures.find((x) => String(x.id) === li.dataset.id);
    if (!m) return;
    if (e.target.closest('button')) remove(m);
    else select(m === selected ? null : m);
  });

  // ---- inspector ----
  function figureHTML(r) {
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    if (r.textBlock) return `<p style="margin:0;font-size:var(--t-md);line-height:1.4">${esc(r.text)}</p>`;
    const cls = r.lead ? 'figure lead' : 'figure';
    const style = r.small ? ' style="font-size:var(--t-md)"' : '';
    const note = r.note ? `<p class="note" style="margin:-4px 0 0;font-size:var(--t-sm)">${esc(r.note)}</p>` : '';
    return `<div class="${cls}"><span>${esc(r.label)}</span><strong${style}>${esc(r.text)}${r.unit ? `<small>${esc(r.unit)}</small>` : ''}</strong></div>${note}`;
  }
  function showPanel(flash) {
    chart.hidden = true;
    chart.textContent = '';
    if (selected) {
      const K = KINDS[selected.kind];
      toolName.textContent = selected.name;
      toolHelp.textContent = flash || 'Drag its points on the model to adjust it. The Delete key removes it.';
      readout.innerHTML = K.rows(selected).map(figureHTML).join('');
      if (K.extra) K.extra(selected);
      if (selected.kind === 'profile') drawChart(selected);
      return;
    }
    const t = TOOLS[tool];
    toolName.textContent = t.title;
    toolHelp.textContent = flash || t.help;
    readout.innerHTML = draft ? draftRows().map(figureHTML).join('') : '';
  }
  let flashTimer = 0;
  function flash(msg) {
    toolHelp.textContent = msg;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => showPanel(), 2600);
  }

  function volumeBaseUI(m) {
    const box = document.createElement('div');
    box.style.cssText = 'display:grid;gap:8px;margin-top:2px';
    const modes = [['lowest', 'Lowest edge point'], ['average', 'Average edge height'], ['typed', 'Typed height']];
    box.innerHTML = `<span style="color:var(--slate);font-size:var(--t-sm)">Base</span><div style="display:flex;gap:6px;flex-wrap:wrap">${
      modes.map(([k, t]) => `<button type="button" class="ws-btn" data-base="${k}" aria-pressed="${m.baseMode === k}">${t}</button>`).join('')
    }</div>`;
    const input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    input.setAttribute('aria-label', `Base height in ${units.unit()}`);
    input.style.cssText = 'font:inherit;font-size:var(--t-sm);padding:5px 8px;border:1px solid var(--rule);border-radius:2px;width:10em;background:var(--paper)';
    input.hidden = m.baseMode !== 'typed';
    input.value = fmtNice(units.len(m.r.base));
    box.appendChild(input);
    readout.appendChild(box);
    box.addEventListener('click', (e) => {
      const b = e.target.closest('[data-base]');
      if (!b) return;
      m.baseMode = b.dataset.base;
      if (m.baseMode === 'typed' && !isFinite(m.typedBase)) m.typedBase = m.r.base;
      KINDS.volume.compute(m, false);
      redraw(m);
      showPanel();
      if (m.baseMode === 'typed') { const i = readout.querySelector('input'); if (i) i.focus(); }
    });
    input.addEventListener('change', () => {
      const v = parseFloat(input.value);
      if (!isFinite(v)) return;
      m.typedBase = v / units.factor;
      KINDS.volume.compute(m, false);
      redraw(m);
      showPanel();
    });
  }

  // Elevation chart of a profile: distance across, height up, magenta line, ink axes.
  function drawChart(m) {
    chart.hidden = false;
    const w = chart.clientWidth || 280, h = chart.clientHeight || 150;
    const ml = 46, mr = 8, mt = 18, mb = 22;
    const f = units.factor;
    const s = m.samples;
    const valid = s.filter((p) => !isNaN(p.y));
    if (valid.length < 2) { chart.textContent = 'The section is off the model.'; return; }
    const xmax = s[s.length - 1].d * f || 1;
    let y0 = Math.min(...valid.map((p) => p.y)) * f, y1 = Math.max(...valid.map((p) => p.y)) * f;
    const pad = Math.max((y1 - y0) * 0.08, xmax * 0.002, 1e-6);
    y0 -= pad; y1 += pad;
    const X = (d) => ml + (d * f / xmax) * (w - ml - mr);
    const Yp = (y) => mt + (1 - (y * f - y0) / (y1 - y0)) * (h - mt - mb);
    let d = '';
    let pen = false;
    for (const p of s) {
      if (isNaN(p.y)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${X(p.d).toFixed(1)},${Yp(p.y).toFixed(1)}`;
      pen = true;
    }
    const xs = G.niceInterval(xmax / 3.5), ys = G.niceInterval((y1 - y0) / 3.2);
    let ticks = '';
    for (let v = 0; v <= xmax + 1e-9; v += xs) {
      const x = ml + (v / xmax) * (w - ml - mr);
      ticks += `<line x1="${x}" x2="${x}" y1="${h - mb}" y2="${h - mb + 4}"/><text x="${x}" y="${h - 6}" text-anchor="middle">${fmtNice(v)}</text>`;
    }
    for (let v = Math.ceil(y0 / ys) * ys; v <= y1 + 1e-9; v += ys) {
      const y = mt + (1 - (v - y0) / (y1 - y0)) * (h - mt - mb);
      ticks += `<line x1="${ml - 4}" x2="${ml}" y1="${y}" y2="${y}"/><text x="${ml - 7}" y="${y + 4}" text-anchor="end">${fmtNice(v)}</text>`;
    }
    chart.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Elevation profile, ${fmt(xmax)} ${units.unit()} long">
<g style="stroke:var(--ink);stroke-width:1;fill:var(--slate);font-size:11px">
<line x1="${ml}" x2="${ml}" y1="${mt}" y2="${h - mb}"/><line x1="${ml}" x2="${w - mr}" y1="${h - mb}" y2="${h - mb}"/>
${ticks.replace(/<text /g, '<text style="stroke:none" ')}</g>
<text x="${ml - 7}" y="10" text-anchor="end" style="fill:var(--slate);font-size:11px">${units.unit()}</text>
<path d="${d}" style="fill:none;stroke:var(--magenta);stroke-width:1.8;stroke-linejoin:round"/>
<g class="probe" style="display:none"><line y1="${mt}" y2="${h - mb}" style="stroke:var(--magenta);stroke-width:1;stroke-dasharray:3 3"/><circle r="3.5" style="fill:var(--magenta);stroke:#fff;stroke-width:1.5"/></g>
<rect x="${ml}" y="${mt}" width="${w - ml - mr}" height="${h - mt - mb}" style="fill:transparent"/></svg>`;
    const svg = chart.querySelector('svg');
    const g = svg.querySelector('.probe');
    const line = g.querySelector('line'), dot = g.querySelector('circle');
    const move = (e) => {
      const r = svg.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * w;
      const k = Math.round(G.clamp((x - ml) / (w - ml - mr), 0, 1) * (s.length - 1));
      const p = s[k];
      if (isNaN(p.y)) { g.style.display = 'none'; probe.visible = false; S.requestRender(); return; }
      g.style.display = '';
      line.setAttribute('x1', X(p.d)); line.setAttribute('x2', X(p.d));
      dot.setAttribute('cx', X(p.d)); dot.setAttribute('cy', Yp(p.y));
      probe.position.set(p.x, p.y, p.z);
      probe.visible = true;
      S.requestRender();
    };
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerleave', () => { g.style.display = 'none'; probe.visible = false; S.requestRender(); });
    api.chartProbe = (i) => move({ clientX: svg.getBoundingClientRect().left + (X(s[i].d) / w) * svg.getBoundingClientRect().width });
  }

  // ---- draft ----
  let draftGroup = null;
  function draftPts() {
    const pts = draft ? draft.pts.slice() : [];
    if (draft && draft.preview) pts.push(draft.preview);
    return pts;
  }
  function draftRows() {
    const pts = draftPts();
    if (!draft) return [];
    if (draft.kind === 'distance' && pts.length > 1) {
      const r = G.polylineStats(pts.map(arr));
      return [{ label: 'Length so far', ...L(r.length), lead: true }, { label: 'Horizontal', ...L(r.horizontal) }];
    }
    if ((draft.kind === 'area' || draft.kind === 'volume') && pts.length > 2) {
      return [{ label: 'Plan area so far', ...A(G.planArea(pts.map((p) => [p.x, p.z]))), lead: true }];
    }
    if ((draft.kind === 'height' || draft.kind === 'calibrate' || draft.kind === 'profile' || draft.kind === 'sight') && pts.length > 1) {
      const [a, b] = pts;
      if (draft.kind === 'height') return [{ label: 'Vertical difference', ...L(Math.abs(b.y - a.y)), lead: true }];
      if (draft.kind === 'calibrate') return [{ label: 'Model length', text: fmt(a.distanceTo(b)), unit: 'units', lead: true }];
      return [{ label: 'Length', ...L(G.distPlan3(arr(a), arr(b))), lead: true }];
    }
    return [];
  }
  function redrawDraft() {
    disposeGroup(draftGroup);
    draftGroup = null;
    if (draft) {
      const pts = draftPts();
      const closed = draft.kind === 'area' || draft.kind === 'volume';
      draftGroup = new THREE.Group();
      addAll(draftGroup, [
        closed && pts.length > 2 ? mkFill(pts) : null,
        mkLine(pts, { closed, width: 2 }),
        mkPoints(draft.pts, false),
      ]);
      S.overlayGroup.add(draftGroup);
    }
    if (!selected) readout.innerHTML = draft ? draftRows().map(figureHTML).join('') : '';
    S.requestRender();
  }
  function cancelDraft() {
    draft = null;
    redrawDraft();
  }
  function finish() {
    if (!draft) return;
    const kind = draft.kind;
    const pts = draft.pts;
    const need = TOOLS[kind].min || TOOLS[kind].n;
    if (pts.length < need) { flash(`${TOOLS[kind].title} needs at least ${need} points.`); return; }
    draft = null;
    redrawDraft();
    if (kind === 'calibrate') {
      disposeGroup(calibGroup);
      calibGroup = new THREE.Group();
      addAll(calibGroup, [mkLine(pts, { width: 2.5 }), mkPoints(pts, true)]);
      S.overlayGroup.add(calibGroup);
      const cb = onCalibrated;
      onCalibrated = null;
      setTool('navigate');
      if (cb) cb(pts[0].distanceTo(pts[1]), pts);
      return;
    }
    create(kind, pts);
  }

  // ---- pointer hooks, called by nav ----
  function screenOf(p) {
    const r = S.canvas.getBoundingClientRect();
    S.camera.updateMatrixWorld();
    proj.copy(p).project(S.camera);
    if (proj.z > 1) return null;
    return [r.left + (proj.x * 0.5 + 0.5) * r.width, r.top + (-proj.y * 0.5 + 0.5) * r.height];
  }
  function grabHandle(e) {
    if (draft || noteInput) return false;
    let best = null, bd = 9;
    const order = selected ? [selected, ...measures.filter((m) => m !== selected)] : measures;
    for (const m of order) {
      m.pts.forEach((p, i) => {
        const s = screenOf(p);
        if (!s) return;
        const d = Math.hypot(s[0] - e.clientX, s[1] - e.clientY);
        if (d < bd) { bd = d; best = { m, i }; }
      });
      if (best && best.m === selected) break;
    }
    if (!best) return false;
    dragging = best;
    if (selected !== best.m) select(best.m);
    return true;
  }
  function dragHandle(e) {
    if (!dragging) return;
    const hit = S.pickClient(e.clientX, e.clientY);
    if (!hit) return;
    const m = dragging.m;
    m.pts[dragging.i] = hit;
    KINDS[m.kind].compute(m, m.kind === 'sight' || m.kind === 'distance' || m.kind === 'height');
    redraw(m);
    readout.innerHTML = KINDS[m.kind].rows(m).map(figureHTML).join('');
  }
  function dropHandle() {
    if (!dragging) return;
    const m = dragging.m;
    dragging = null;
    KINDS[m.kind].compute(m, true);
    redraw(m);
    showPanel();
  }
  function click(e) {
    if (tool === 'navigate' || noteInput) return;
    const hit = S.pickClient(e.clientX, e.clientY);
    if (!hit) { flash('Nothing under the cursor there. Click on the model itself.'); return; }
    if (tool === 'note') { openNote(hit, e); return; }
    if (selected) select(null);
    if (!draft) draft = { kind: tool, pts: [], screen: [], preview: null };
    const last = draft.screen[draft.screen.length - 1];
    if (last && Math.hypot(last[0] - e.clientX, last[1] - e.clientY) < 5) return; // second click of a double-click
    draft.pts.push(hit);
    draft.screen.push([e.clientX, e.clientY]);
    draft.preview = null;
    if (draft.pts.length >= TOOLS[tool].n) finish();
    else redrawDraft();
  }
  function dblclick() {
    if (tool === 'navigate') return false;
    if (draft && TOOLS[draft.kind].n === Infinity) finish();
    return true;
  }
  let hoverEvt = null;
  function hover(e) {
    if (!draft || !draft.pts.length) return;
    if (!hoverEvt) requestAnimationFrame(() => {
      const ev = hoverEvt;
      hoverEvt = null;
      if (!draft || !ev) return;
      draft.preview = S.pickClient(ev.clientX, ev.clientY);
      redrawDraft();
    });
    hoverEvt = e;
  }

  // ---- notes ----
  function openNote(hit, e) {
    closeNote();
    const box = S.canvas.parentElement.getBoundingClientRect();
    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 160;
    input.placeholder = 'Type a note, then Enter';
    input.setAttribute('aria-label', 'Note text');
    input.style.cssText = `position:absolute;left:${e.clientX - box.left}px;top:${e.clientY - box.top}px;transform:translate(-50%,calc(-100% - 12px));z-index:4;width:240px;font:inherit;font-size:var(--t-sm);padding:5px 8px;border:1px solid var(--magenta);border-radius:2px;background:var(--paper);color:var(--ink)`;
    S.canvas.parentElement.appendChild(input);
    noteInput = { input, hit };
    const pin = mkPoints([hit], true);
    noteInput.pin = pin;
    S.overlayGroup.add(pin);
    S.requestRender();
    const save = () => {
      const text = input.value.trim();
      closeNote();
      if (text) create('note', [hit], { text });
    };
    input.addEventListener('keydown', (ev) => {
      ev.stopPropagation();
      if (ev.key === 'Enter') { ev.preventDefault(); save(); }
      else if (ev.key === 'Escape') { ev.preventDefault(); closeNote(); }
    });
    input.addEventListener('blur', () => { if (noteInput && noteInput.input === input) save(); });
    setTimeout(() => input.focus(), 0);
  }
  function closeNote() {
    if (!noteInput) return;
    const n = noteInput;
    noteInput = null;
    n.input.remove();
    n.pin.geometry.dispose(); n.pin.material.dispose(); n.pin.removeFromParent();
    S.requestRender();
  }

  // ---- tool switching ----
  const rail = document.querySelectorAll('[data-tool]');
  function setTool(name) {
    if (!TOOLS[name]) return;
    closeNote();
    if (draft) cancelDraft();
    if (name !== 'calibrate' && onCalibrated) onCalibrated = null;
    tool = name;
    rail.forEach((b) => {
      const on = b.dataset.tool === name;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', String(on));
    });
    document.body.classList.toggle('is-picking', name !== 'navigate');
    if (selected) select(null); else showPanel();
  }
  rail.forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool)));

  function escape() {
    if (noteInput) { closeNote(); return; }
    if (draft) { cancelDraft(); }
    if (tool !== 'navigate') setTool('navigate');
    else if (selected) select(null);
  }
  function enter() { if (draft && TOOLS[draft.kind].n === Infinity) finish(); }
  function deleteSelected() { if (selected) remove(selected); }

  units.onChange(() => {
    for (const m of measures) {
      if (m.kind === 'sight') KINDS.sight.compute(m, true);
      redraw(m);
    }
    showPanel();
  });

  function setResolution(w, h) {
    resolution.set(w, h);
    for (const m of lineMats) m.resolution.set(w, h);
  }

  function startCalibration(cb) {
    setTool('calibrate');
    onCalibrated = cb;
  }
  function clearCalibration() { disposeGroup(calibGroup); calibGroup = null; S.requestRender(); }

  const api = {
    hooks: { grabHandle, dragHandle, dropHandle, click, dblclick, hover },
    setTool, escape, enter, deleteSelected, setResolution, startCalibration, clearCalibration, create, select,
    get tool() { return tool; },
    get measures() { return measures; },
    rows: (m) => KINDS[m.kind].rows(m),
    lead: (m) => KINDS[m.kind].lead(m),
    chartProbe: null,
    showPanel,
  };
  showPanel();
  updateListState();
  return api;
}
