import test from 'node:test';
import assert from 'node:assert/strict';
import {
  polylineLength, polylineStats, planArea, polygonGrid, gridSurfaceFactor, gridVolume,
  gridX, gridZ, resampleSegment, profileStats, lineOfSight, niceInterval, localToLatLon,
} from '../src/geom.js';

const near = (a, b, tol = 1e-9) => assert.ok(Math.abs(a - b) <= tol, `${a} is not within ${tol} of ${b}`);

test('polyline length', () => {
  near(polylineLength([[0, 0, 0], [3, 0, 4], [3, 12, 4]]), 17);
  const s = polylineStats([[0, 0, 0], [3, 0, 4], [3, 12, 4]]);
  near(s.horizontal, 5);
  near(s.dh, 12);
  near(s.slopePct, 240);
  assert.deepEqual(s.segments.map(Math.round), [5, 12]);
  near(polylineLength([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], true), 4);
});

test('plan area of a square and an L shape', () => {
  near(planArea([[0, 0], [10, 0], [10, 10], [0, 10]]), 100);
  // L: 4 x 4 square with a 2 x 2 corner removed, either winding
  const L = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]];
  near(planArea(L), 12);
  near(planArea(L.slice().reverse()), 12);
  // the grid mask agrees with the shoelace area
  const g = polygonGrid(L, 20000);
  near(g.count * g.step * g.step, 12, 0.15);
});

test('surface area of a tilted square', () => {
  const sq = [[0, 0], [10, 0], [10, 10], [0, 10]];
  const g = polygonGrid(sq, 400);
  const h = new Float64Array(g.nx * g.nz);
  for (let j = 0; j < g.nz; j++) for (let i = 0; i < g.nx; i++) h[j * g.nx + i] = 0.5 * gridX(g, i) + 0.25 * gridZ(g, j);
  const surface = planArea(sq) * gridSurfaceFactor(g, h);
  near(surface, 100 * Math.sqrt(1 + 0.25 + 0.0625), 1e-9);
});

test('volume of a box heap on a grid', () => {
  // 20 x 20 plot, a 4 x 4 box of height 2 in the middle
  const sq = [[0, 0], [20, 0], [20, 20], [0, 20]];
  const g = polygonGrid(sq, 400);
  assert.equal(g.step, 1);
  const h = new Float64Array(g.nx * g.nz);
  for (let j = 0; j < g.nz; j++) for (let i = 0; i < g.nx; i++) {
    const x = gridX(g, i), z = gridZ(g, j);
    h[j * g.nx + i] = x > 8 && x < 12 && z > 8 && z < 12 ? 2 : 0;
  }
  const v0 = gridVolume(g, h, 0);
  near(v0.cut, 32); near(v0.fill, 0); near(v0.net, 32);
  const v1 = gridVolume(g, h, 1);
  near(v1.cut, 16); near(v1.fill, 384); near(v1.net, -368);
  h[0] = NaN;
  const v2 = gridVolume(g, h, 0);
  assert.equal(v2.missing, 1);
  assert.equal(v2.samples, 399);
});

test('profile resampling of a straight ramp', () => {
  const pts = resampleSegment([0, 0], [30, 40], 200);
  assert.equal(pts.length, 200);
  assert.deepEqual(pts[0], [0, 0]);
  assert.deepEqual(pts[199], [30, 40]);
  const dists = pts.map(([x, z]) => Math.hypot(x, z));
  const heights = dists.map((d) => 1 + d * 0.1); // 10 % ramp
  const s = profileStats(dists, heights);
  near(s.length, 50);
  near(s.climb, 5);
  near(s.descent, 0);
  near(s.max, 6); near(s.min, 1);
  near(s.maxAt, 50); near(s.minAt, 0);
  const back = profileStats(dists, heights.slice().reverse());
  near(back.descent, 5); near(back.climb, 0);
});

test('line of sight against a wall height field', () => {
  // flat ground with a 3-high wall across x = 10 .. 11
  const heightAt = (x) => (x >= 10 && x <= 11 ? 3 : 0);
  const blocked = lineOfSight([0, 1.7, 0], [20, 0.5, 0], heightAt, 2000);
  assert.equal(blocked.visible, false);
  near(blocked.blockedAt, 10, 0.02);
  const over = lineOfSight([0, 5, 0], [20, 4, 0], heightAt, 2000);
  assert.equal(over.visible, true);
  assert.equal(over.blockedAt, null);
});

test('niceInterval on 0.07, 3.2, 48, 750', () => {
  assert.equal(niceInterval(0.07), 0.1);
  assert.equal(niceInterval(3.2), 5);
  assert.equal(niceInterval(48), 50);
  assert.equal(niceInterval(750), 1000);
  assert.equal(niceInterval(2), 2);
  assert.equal(niceInterval(0.2), 0.2);
});

test('local ENU to latitude and longitude', () => {
  const g = { lat0: 19, lon0: 72.8, h0: 10 };
  const p = localToLatLon(0, 5, -1000, g); // 1 km north
  near(p.lat - 19, 1000 / 110_700, 1e-4);
  near(p.lon, 72.8);
  near(p.h, 15);
});
