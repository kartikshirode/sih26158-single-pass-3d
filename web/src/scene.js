// Renderer, camera, the packed model, surface picking and the render-on-demand loop.
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { computeBoundsTree, acceleratedRaycast } from 'three-mesh-bvh';
import { niceInterval } from './geom.js';

THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// "rgba(176, 36, 110, 0.10)" or "#B0246E" to { color, alpha }.
export function cssColor(name) {
  const v = cssVar(name);
  const m = v.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b, a = '1'] = m[1].split(',').map((s) => s.trim());
    return { color: new THREE.Color(`rgb(${r}, ${g}, ${b})`), alpha: parseFloat(a) };
  }
  return { color: new THREE.Color(v || '#000'), alpha: 1 };
}

function base64ToBuffer(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

export const DEFAULT_FOV = 50;

export function createScene(canvas, T) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const paper = new THREE.Color(cssVar('--paper'));
  const scene = new THREE.Scene();
  scene.background = paper;

  const b0 = new THREE.Vector3().fromArray(T.bounds.min);
  const b1 = new THREE.Vector3().fromArray(T.bounds.max);
  const bounds = new THREE.Box3(b0, b1);
  const diag = Math.hypot(b1.x - b0.x, b1.z - b0.z) || 1;   // horizontal diagonal
  const size = bounds.getSize(new THREE.Vector3());

  const camera = new THREE.PerspectiveCamera(DEFAULT_FOV, 1, diag * 1e-4, diag * 30);
  camera.rotation.order = 'YXZ';

  const modelGroup = new THREE.Group();
  const pathGroup = new THREE.Group();
  const overlayGroup = new THREE.Group();   // measurements, drawn over the surface
  scene.add(modelGroup, pathGroup, overlayGroup);

  // Uniforms shared by every surface material: photo on or off, contours, hillshade.
  const surfaceUniforms = {
    uTex: { value: 1 },
    uContours: { value: 0 },
    uInterval: { value: 1 },
    uContourColor: { value: new THREE.Color(cssVar('--contour')) },
    uShadeColor: { value: paper.clone() },
    uLight: { value: new THREE.Vector3(-0.45, 0.8, -0.4).normalize() },
    // Detail layer: photo pixel footprint per vertex, fine to coarse, grey where unseen.
    uDetail: { value: 0 },
    uDetailA: { value: new THREE.Color('#2F6B4F') },
    uDetailB: { value: new THREE.Color('#D9B44A') },
    uDetailC: { value: new THREE.Color('#9A3B1F') },
    uDetailNone: { value: new THREE.Color('#9AA5A1') },
  };

  function surfaceMaterial(map, vertexColors) {
    const mat = new THREE.MeshBasicMaterial({ map: map || null, vertexColors: !!vertexColors, side: THREE.DoubleSide });
    mat.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, surfaceUniforms);
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `#include <common>
varying vec3 vWPos;
#ifdef HAS_DETAIL
attribute float aDetail;
varying float vDetailV;
varying float vSeen;
#endif`)
        .replace('#include <project_vertex>', `#include <project_vertex>
vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;
#ifdef HAS_DETAIL
vSeen = aDetail < 254.5 ? 1.0 : 0.0;
vDetailV = vSeen * aDetail / 254.0;
#endif`);
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>
varying vec3 vWPos;
uniform float uTex;
uniform float uContours;
uniform float uInterval;
uniform vec3 uContourColor;
uniform vec3 uShadeColor;
uniform vec3 uLight;
#ifdef HAS_DETAIL
varying float vDetailV;
varying float vSeen;
uniform float uDetail;
uniform vec3 uDetailA;
uniform vec3 uDetailB;
uniform vec3 uDetailC;
uniform vec3 uDetailNone;
#endif`)
        .replace('#include <map_fragment>', `#include <map_fragment>
if (uTex < 0.5) {
  // Light hillshade from flat normals, so contours read on a plain surface.
  vec3 n = normalize(cross(dFdx(vWPos), dFdy(vWPos)));
  if (n.y < 0.0) n = -n;
  float d = clamp(dot(n, uLight), 0.0, 1.0);
  diffuseColor.rgb = uShadeColor * (0.52 + 0.48 * d);
}
#ifdef HAS_DETAIL
if (uDetail > 0.5) {
  if (vSeen < 0.5) {
    diffuseColor.rgb = uDetailNone;
  } else {
    // Interpolated value renormalised by the seen weight, so unseen corners do not drag it.
    float t = clamp(vDetailV / max(vSeen, 1e-4), 0.0, 1.0);
    diffuseColor.rgb = t < 0.5 ? mix(uDetailA, uDetailB, t * 2.0) : mix(uDetailB, uDetailC, t * 2.0 - 1.0);
  }
}
#endif`)
        .replace('#include <opaque_fragment>', `if (uContours > 0.5) {
  float c = vWPos.y / uInterval;
  float fw = max(fwidth(c), 1e-6);
  float idx = floor(c + 0.5);
  float major = 1.0 - step(0.5, mod(idx, 5.0));
  float halfWidth = mix(0.45, 0.95, major);
  float px = abs(c - idx) / fw;
  float a = 1.0 - smoothstep(halfWidth - 0.5, halfWidth + 0.5, px);
  a *= 1.0 - smoothstep(0.25, 0.6, fw);   // fade where lines crowd closer than a few pixels
  outgoingLight = mix(outgoingLight, uContourColor, a * mix(0.7, 1.0, major));
}
#include <opaque_fragment>`);
    };
    return mat;
  }

  const meshes = [];
  const raycaster = new THREE.Raycaster();
  raycaster.firstHitOnly = true;

  function loadModel() {
    return new Promise((resolve, reject) => {
      const loader = new GLTFLoader();
      let buf;
      try { buf = base64ToBuffer(T.glb); } catch (e) { reject(e); return; }
      loader.parse(buf, '', (gltf) => {
        const aniso = renderer.capabilities.getMaxAnisotropy();
        gltf.scene.traverse((o) => {
          if (!o.isMesh) return;
          const old = o.material;
          const map = old && old.map;
          if (map) {
            map.colorSpace = THREE.SRGBColorSpace;
            map.anisotropy = aniso;
            map.generateMipmaps = true;
            map.minFilter = THREE.LinearMipmapLinearFilter;
            map.magFilter = THREE.LinearFilter;
            map.needsUpdate = true;
          }
          o.material = surfaceMaterial(map, !map && !!o.geometry.attributes.color);
          if (old) old.dispose();
          o.geometry.computeBoundsTree();
          meshes.push(o);
        });
        if (!meshes.length) { reject(new Error('The packed model has no mesh.')); return; }
        attachDetail(gltf);
        if (!meshes.some((m) => m.material.map)) surfaceUniforms.uTex.value = 0;
        modelGroup.add(gltf.scene);
        scene.updateMatrixWorld(true);
        resolve();
      }, (err) => reject(err instanceof Error ? err : new Error(String(err && err.message || err))));
    });
  }

  // One byte per vertex, in accessor order mesh after mesh; 0..254 on a log scale from
  // lo to hi model units of surface per photo pixel, 255 where no keyframe saw it.
  let detail = null;
  function attachDetail(gltf) {
    const D = T.detail;
    if (!D || !D.b64) return;
    let bytes;
    try { bytes = new Uint8Array(base64ToBuffer(D.b64)); } catch (e) { console.warn('detail layer unreadable', e); return; }
    const assoc = gltf.parser && gltf.parser.associations;
    const order = meshes.slice().sort((a, b) => {
      const x = assoc && assoc.get(a), y = assoc && assoc.get(b);
      return x && y ? (x.meshes - y.meshes) || ((x.primitives || 0) - (y.primitives || 0)) : 0;
    });
    const total = order.reduce((n, m) => n + m.geometry.attributes.position.count, 0);
    if (total !== bytes.length) { console.warn(`detail layer has ${bytes.length} values for ${total} vertices; not shown`); return; }
    let off = 0;
    for (const m of order) {
      const n = m.geometry.attributes.position.count;
      const slice = bytes.subarray(off, off + n);
      off += n;
      m.geometry.setAttribute('aDetail', new THREE.BufferAttribute(slice, 1));
      m.userData.detail = slice;
      m.material.defines = { ...(m.material.defines || {}), HAS_DETAIL: '' };
      m.material.needsUpdate = true;
    }
    detail = { lo: +D.lo, hi: +D.hi, median: +D.median };
  }
  function detailValue(v) {
    const a = Math.log(detail.lo), b = Math.log(detail.hi);
    return Math.exp(a + (v / 254) * (b - a));
  }
  // Model units of surface per photo pixel at a surface point, from the face under it.
  function detailAt(p) {
    if (!detail) return null;
    tmpO.set(p.x, p.y + diag * 2e-3, p.z);
    let hit = castRay(tmpO, down, diag * 5e-3);
    if (!hit) {
      const dir = p.clone().sub(camera.position);
      const len = dir.length();
      hit = castRay(camera.position, dir.normalize(), len + diag * 1e-3);
      if (hit && hit.point.distanceTo(p) > diag * 2e-3) hit = null;
    }
    if (!hit || !hit.face || !hit.object.userData.detail) return null;
    const d = hit.object.userData.detail;
    const vals = [d[hit.face.a], d[hit.face.b], d[hit.face.c]].filter((v) => v < 255);
    if (!vals.length) return { seen: false, value: NaN };
    return { seen: true, value: detailValue(vals.reduce((s, v) => s + v, 0) / vals.length) };
  }

  // ---- picking ----
  const ndc = new THREE.Vector2();
  function rayFromClient(x, y) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1);
    camera.updateMatrixWorld();
    raycaster.setFromCamera(ndc, camera);
    return raycaster.ray.clone();
  }
  function rayFromNDC(nx, ny) {
    ndc.set(nx, ny);
    camera.updateMatrixWorld();
    raycaster.setFromCamera(ndc, camera);
    return raycaster.ray.clone();
  }
  function castRay(origin, dir, far = Infinity) {
    raycaster.set(origin, dir);
    raycaster.near = 0;
    raycaster.far = far;
    const hits = raycaster.intersectObjects(meshes, false);
    raycaster.far = Infinity;
    return hits.length ? hits[0] : null;
  }
  // Surface point under a client (page) position, or null.
  function pickClient(x, y) {
    const ray = rayFromClient(x, y);
    const hit = castRay(ray.origin, ray.direction);
    return hit ? hit.point.clone() : null;
  }
  function pickNDC(nx, ny) {
    const ray = rayFromNDC(nx, ny);
    const hit = castRay(ray.origin, ray.direction);
    return hit ? hit.point.clone() : null;
  }
  const down = new THREE.Vector3(0, -1, 0);
  const top = b1.y + size.y + diag * 0.05;
  const tmpO = new THREE.Vector3();
  // Height of the top surface at (x, z) by casting straight down, NaN when off the model.
  function heightAt(x, z) {
    tmpO.set(x, top, z);
    const hit = castRay(tmpO, down);
    return hit ? hit.point.y : NaN;
  }

  // A rough ground height for fallbacks: the median height under the flight path.
  let groundY = (b0.y + b1.y) / 2;
  function computeGround() {
    const hs = [];
    for (let i = 0; i < 21; i++) for (let j = 0; j < 9; j++) {
      const h = heightAt(b0.x + ((i + 0.5) / 21) * size.x, b0.z + ((j + 0.5) / 9) * size.z);
      if (!isNaN(h)) hs.push(h);
    }
    if (hs.length) { hs.sort((a, b) => a - b); groundY = hs[hs.length >> 1]; }
    api.groundY = groundY;
  }

  // Intersection of a ray with the horizontal plane y = h, or null.
  function rayPlane(ray, h) {
    const dy = ray.direction.y;
    if (Math.abs(dy) < 1e-9) return null;
    const t = (h - ray.origin.y) / dy;
    if (t <= 0) return null;
    return ray.origin.clone().addScaledVector(ray.direction, t);
  }

  // The point the view is centred on: the surface at the middle of the screen, else the
  // ground plane, else a point straight ahead.
  function viewCentre() {
    const hit = pickNDC(0, 0);
    if (hit) return hit;
    const ray = rayFromNDC(0, 0);
    const p = rayPlane(ray, groundY);
    if (p && p.distanceTo(ray.origin) < diag * 3) return p;
    return ray.origin.clone().addScaledVector(ray.direction, diag * 0.3);
  }

  // ---- render on demand ----
  let pending = false;
  const animators = new Set();
  const afterRender = [];
  let last = 0;
  function requestRender() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(frame);
  }
  function animate(fn) { animators.add(fn); last = 0; requestRender(); return () => animators.delete(fn); }
  function frame(now) {
    pending = false;
    const dt = last ? Math.min((now - last) / 1000, 0.25) : 1 / 60;
    last = now;
    for (const fn of [...animators]) if (fn(dt, now) === false) animators.delete(fn);
    render();
    if (animators.size) requestRender(); else last = 0;
  }
  const clipRay = new THREE.Vector3();
  function updateClip() {
    // Near plane scaled to how close the surface is, so close-ups do not clip.
    let d = Infinity;
    const c = pickNDC(0, 0);
    if (c) d = c.distanceTo(camera.position);
    clipRay.copy(camera.position);
    const h = castRay(clipRay, down);
    if (h) d = Math.min(d, h.distance);
    if (!isFinite(d)) d = diag * 0.2;
    const near = Math.min(Math.max(d * 0.05, diag * 2e-5), diag * 0.01);
    if (Math.abs(near - camera.near) > camera.near * 0.1) {
      camera.near = near;
      camera.updateProjectionMatrix();
    }
  }
  function render() {
    if (!meshes.length) return;
    updateClip();
    renderer.render(scene, camera);
    for (const fn of afterRender) fn();
  }

  function resize(w, h) {
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
    requestRender();
  }

  // Contour interval in display units, turned back into model units for the shader.
  function setContourInterval(factor) {
    const range = (b1.y - b0.y) * factor;
    const shown = niceInterval(range / 25);
    surfaceUniforms.uInterval.value = shown / factor;
    requestRender();
    return shown;
  }

  const api = {
    renderer, scene, camera, canvas, bounds, diag, size, meshes, modelGroup, pathGroup, overlayGroup,
    surfaceUniforms, groundY, loadModel, computeGround, rayFromClient, rayFromNDC, castRay, pickClient, pickNDC,
    heightAt, rayPlane, viewCentre, detailAt, get detail() { return detail; }, requestRender, animate, afterRender, render, resize, setContourInterval,
  };
  return api;
}
