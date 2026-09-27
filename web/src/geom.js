// Pure measurement maths. No three.js here, so node --test can run it directly.
// Points are plain arrays: 3D points are [x, y, z] with y up, plan points are [x, z].

export function dist3(a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

export function distPlan3(a, b) {
  const dx = b[0] - a[0], dz = b[2] - a[2];
  return Math.sqrt(dx * dx + dz * dz);
}

// Total 3D length of an open polyline, or of a closed ring when closed is true.
export function polylineLength(pts, closed = false) {
  let s = 0;
  for (let i = 1; i < pts.length; i++) s += dist3(pts[i - 1], pts[i]);
  if (closed && pts.length > 2) s += dist3(pts[pts.length - 1], pts[0]);
  return s;
}

// Everything the distance tool reads out, in model units.
export function polylineStats(pts) {
  const segments = [];
  let length = 0, horizontal = 0;
  for (let i = 1; i < pts.length; i++) {
    const d = dist3(pts[i - 1], pts[i]);
    segments.push(d);
    length += d;
    horizontal += distPlan3(pts[i - 1], pts[i]);
  }
  const dh = pts.length ? pts[pts.length - 1][1] - pts[0][1] : 0;
  const slopePct = horizontal > 0 ? (dh / horizontal) * 100 : 0;
  return { length, horizontal, dh, slopePct, segments };
}

// Shoelace area of a plan polygon [[x, z], ...]. Always positive.
export function planArea(poly) {
  let s = 0;
  for (let i = 0, n = poly.length; i < n; i++) {
    const a = poly[i], b = poly[(i + 1) % n];
    s += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(s) / 2;
}

export function pointInPolygon(x, z, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], zi = poly[i][1], xj = poly[j][0], zj = poly[j][1];
    if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

// A square grid of cell centres over the polygon's bounding box, with a mask of the
// cells whose centre is inside. Spacing is picked so about `target` cells are inside.
export function polygonGrid(poly, target) {
  let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
  for (const [x, z] of poly) {
    x0 = Math.min(x0, x); z0 = Math.min(z0, z);
    x1 = Math.max(x1, x); z1 = Math.max(z1, z);
  }
  const area = planArea(poly);
  let step = Math.sqrt(Math.max(area, 1e-12) / Math.max(target, 1));
  // A thin sliver has a huge box for its area; cap the number of cells tested.
  const maxCells = Math.max(target, 1) * 40;
  while (Math.ceil((x1 - x0) / step) * Math.ceil((z1 - z0) / step) > maxCells) step *= 1.25;
  const nx = Math.max(1, Math.ceil((x1 - x0) / step));
  const nz = Math.max(1, Math.ceil((z1 - z0) / step));
  const inside = new Uint8Array(nx * nz);
  let count = 0;
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const x = x0 + (i + 0.5) * step, z = z0 + (j + 0.5) * step;
      if (pointInPolygon(x, z, poly)) { inside[j * nx + i] = 1; count++; }
    }
  }
  return { x0, z0, step, nx, nz, inside, count, area };
}

export function gridX(grid, i) { return grid.x0 + (i + 0.5) * grid.step; }
export function gridZ(grid, j) { return grid.z0 + (j + 0.5) * grid.step; }

// Mean of sqrt(1 + gx^2 + gz^2) over the inside cells with a height: the ratio of
// surface area to plan area. `h` has one height per cell, NaN where nothing was hit.
export function gridSurfaceFactor(grid, h) {
  const { nx, nz, step, inside } = grid;
  const at = (i, j) => (i < 0 || j < 0 || i >= nx || j >= nz ? NaN : h[j * nx + i]);
  const slope = (hm, h0, hp) => {
    if (!isNaN(hm) && !isNaN(hp)) return (hp - hm) / (2 * step);
    if (!isNaN(hp)) return (hp - h0) / step;
    if (!isNaN(hm)) return (h0 - hm) / step;
    return 0;
  };
  let sum = 0, n = 0;
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const k = j * nx + i;
      if (!inside[k] || isNaN(h[k])) continue;
      const gx = slope(at(i - 1, j), h[k], at(i + 1, j));
      const gz = slope(at(i, j - 1), h[k], at(i, j + 1));
      sum += Math.sqrt(1 + gx * gx + gz * gz);
      n++;
    }
  }
  return n ? sum / n : 1;
}

// Cut above the base, fill below it, net = cut - fill. cellArea defaults to step^2;
// pass planArea / count to make the total plan area exact.
export function gridVolume(grid, h, base, cellArea = grid.step * grid.step) {
  let cut = 0, fill = 0, samples = 0, missing = 0;
  for (let k = 0; k < grid.inside.length; k++) {
    if (!grid.inside[k]) continue;
    if (isNaN(h[k])) { missing++; continue; }
    const d = h[k] - base;
    if (d > 0) cut += d * cellArea; else fill -= d * cellArea;
    samples++;
  }
  return { cut, fill, net: cut - fill, samples, missing };
}

// n evenly spaced points from a to b, both ends included. Works for any dimension.
export function resampleSegment(a, b, n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const t = n === 1 ? 0 : i / (n - 1);
    out.push(a.map((v, k) => v + (b[k] - v) * t));
  }
  return out;
}

// n points spread evenly by length along a closed plan ring [[x, z], ...].
export function resampleRing(poly, n) {
  const m = poly.length;
  const lens = [];
  let total = 0;
  for (let i = 0; i < m; i++) {
    const a = poly[i], b = poly[(i + 1) % m];
    const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
    lens.push(l); total += l;
  }
  const out = [];
  if (total === 0) return poly.slice();
  let seg = 0, acc = 0;
  for (let k = 0; k < n; k++) {
    const s = (k / n) * total;
    while (seg < m - 1 && acc + lens[seg] < s) { acc += lens[seg]; seg++; }
    const a = poly[seg], b = poly[(seg + 1) % m];
    const t = lens[seg] > 0 ? (s - acc) / lens[seg] : 0;
    out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
  }
  return out;
}

// Climb, descent and extremes of a sampled profile. NaN heights are skipped.
export function profileStats(dists, heights) {
  let climb = 0, descent = 0, max = -Infinity, min = Infinity, maxAt = 0, minAt = 0, prev = NaN;
  for (let i = 0; i < heights.length; i++) {
    const hh = heights[i];
    if (isNaN(hh)) continue;
    if (!isNaN(prev)) {
      if (hh > prev) climb += hh - prev; else descent += prev - hh;
    }
    if (hh > max) { max = hh; maxAt = dists[i]; }
    if (hh < min) { min = hh; minAt = dists[i]; }
    prev = hh;
  }
  const length = dists.length ? dists[dists.length - 1] - dists[0] : 0;
  return { length, climb, descent, max, min, maxAt, minAt };
}

// Line of sight over a height field: march from observer to target and report the
// first place the ground rises above the sight line. heightAt(x, z) returns a height.
export function lineOfSight(obs, tgt, heightAt, n = 400, eps = 1e-6) {
  const total = dist3(obs, tgt);
  for (let i = 1; i < n; i++) {
    const t = i / n;
    const x = obs[0] + (tgt[0] - obs[0]) * t;
    const y = obs[1] + (tgt[1] - obs[1]) * t;
    const z = obs[2] + (tgt[2] - obs[2]) * t;
    const g = heightAt(x, z);
    if (!isNaN(g) && g > y + eps) return { visible: false, blockedAt: total * t, total };
  }
  return { visible: true, blockedAt: null, total };
}

// Smallest value of the 1, 2, 5 series at or above x.
export function niceInterval(x) {
  if (!(x > 0) || !isFinite(x)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(x)));
  const m = x / p;
  const tol = 1 + 1e-9;
  const k = m <= tol ? 1 : m <= 2 * tol ? 2 : m <= 5 * tol ? 5 : 10;
  return Number((k * p).toPrecision(12));
}

// Local ENU (x east, -z north, y up) to latitude and longitude on WGS84, with a
// tangent-plane approximation around the origin. Good to centimetres over a few km.
export function localToLatLon(x, y, z, georef) {
  const a = 6378137, e2 = 6.69437999014e-3;
  const lat0 = (georef.lat0 * Math.PI) / 180;
  const s = Math.sin(lat0);
  const w = Math.sqrt(1 - e2 * s * s);
  const rn = a / w;                       // prime vertical radius
  const rm = (a * (1 - e2)) / (w * w * w); // meridian radius
  const east = x, north = -z;
  return {
    lat: georef.lat0 + (north / rm) * (180 / Math.PI),
    lon: georef.lon0 + (east / (rn * Math.cos(lat0))) * (180 / Math.PI),
    h: (georef.h0 || 0) + y,
  };
}

export function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
export function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
