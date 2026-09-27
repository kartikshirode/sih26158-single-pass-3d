// Entry point for workspace.html: loads the packed model and wires the page together.
// Debug hook: ?demo=item,item,... runs a short script after load so a headless browser
// can capture a state. Items: plan, oblique, pilot, fit (views); distance, height, area,
// volume, profile, sight, point, note (place one measurement at fixed screen spots);
// contours, notex, detail (layers); t=<seconds> (playhead); play; scale (calibrate 1 unit = 5.54 m);
// probe (hover the profile chart); tool=<name> (leave a tool active).
import { createScene, DEFAULT_FOV } from './scene.js';
import { createUnits, fmt } from './units.js';
import { createNav } from './nav.js';
import { createFlight } from './flight.js';
import { createMinimap } from './minimap.js';
import { createSheet } from './sheet.js';
import { createTools } from './tools.js';
import { exportAll } from './export.js';

const $ = (id) => document.getElementById(id);
const loading = $('loading');
const loadingNote = $('loadingNote');
let loaded = false;

function note(text) { loadingNote.textContent = text; }
const tick = () => new Promise((r) => setTimeout(r, 30));

window.addEventListener('error', (e) => {
  if (!loaded) note(`Could not open the model: ${e.message}`);
});
window.addEventListener('unhandledrejection', (e) => {
  if (!loaded) note(`Could not open the model: ${(e.reason && e.reason.message) || e.reason}`);
});

async function main() {
  const T = window.TESSERACT;
  if (!T) { note('No model packed. Run python tools/pack_site.py out/runs/<run> first.'); return; }

  $('modelTitle').textContent = T.title || 'Model';
  $('modelSub').textContent = T.subtitle || '';
  // With more than one packed model, a switcher replaces the title; switching reloads the
  // page with ?model=<id>, since each model arrives by its own script tag.
  const models = window.TESSERACT_MODELS || [];
  if (models.length > 1) {
    const sel = $('modelSelect');
    models.forEach((m) => {
      const o = document.createElement('option');
      o.value = m.id;
      o.textContent = `${m.title} (${m.georef ? 'GPS, metres' : m.units})`;
      o.selected = m.id === T.id;
      sel.appendChild(o);
    });
    sel.addEventListener('change', () => { location.search = `?model=${encodeURIComponent(sel.value)}`; });
    sel.parentElement.hidden = false;
    $('modelTitle').hidden = true;
  }
  document.title = `${T.title || 'Model'} · Tesseract workspace`;

  const canvas = $('view');
  const S = createScene(canvas, T);
  const units = createUnits(T);
  const nav = createNav(S);
  S.resize(canvas.clientWidth || 800, canvas.clientHeight || 600);

  note('Reading the model');
  await tick();
  await S.loadModel();
  S.computeGround();

  const flight = createFlight(S, T, nav);
  nav.flight = flight;
  flight.init();
  const tools = createTools(S, units, T);
  let hintDone = false;
  Object.assign(nav.hooks, tools.hooks, {
    userMoved: () => { flight.stop(); if (loaded && !hintDone) { hintDone = true; $('hint').hidden = true; } },
    viewChanged: () => flight.refresh(),
  });
  const sheet = createSheet(S, nav, units);
  const minimap = createMinimap(S, flight, nav);

  // ---- sizes ----
  let mmSize = '';
  function layout() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    S.resize(w, h);
    flight.setResolution(w, h);
    tools.setResolution(w, h);
    sheet.size();
    flight.refresh();
    const mm = $('minimap');
    const key = `${mm.clientWidth}x${mm.clientHeight}`;
    if (loaded && key !== mmSize) { mmSize = key; minimap.build(); }
    fitHint();
    S.requestRender();
  }
  // The navigation hint shares the foot of the sheet with the layers and the scale bar;
  // on a narrow sheet it would run into them, so it steps aside.
  function fitHint() {
    const hint = $('hint');
    if (hintDone) return;
    hint.hidden = false;
    const a = hint.getBoundingClientRect();
    const hit = ['.ws-layers', '#scalebar'].some((sel) => {
      const el = document.querySelector(sel);
      if (!el || el.hidden) return false;
      const b = el.getBoundingClientRect();
      return b.width > 0 && a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    });
    hint.hidden = hit;
  }
  new ResizeObserver(layout).observe(canvas.parentElement);
  new ResizeObserver(() => flight.refresh()).observe($('strip'));
  layout();

  // ---- units and scale ----
  function showUnits() {
    const el = $('unitsValue');
    el.textContent = units.headline();
    el.classList.toggle('is-calibrated', units.isCalibrated());
    el.title = units.label || '';
    $('calibrateBtn').textContent = units.hadMetres() ? 'Check scale' : 'Set scale';
    S.setContourInterval(units.factor);
    S.requestRender();
  }
  units.onChange(showUnits);
  showUnits();
  setupCalibration(S, units, tools);

  // ---- layers ----
  const hasMap = S.meshes.some((m) => m.material.map);
  const tex = $('layerTexture'), con = $('layerContours'), path = $('layerPath');
  if (!hasMap) { tex.checked = false; tex.disabled = true; }
  const detail = setupDetail(S, units, con);
  const applyLayers = () => {
    S.surfaceUniforms.uTex.value = tex.checked && hasMap ? 1 : 0;
    S.surfaceUniforms.uContours.value = con.checked ? 1 : 0;
    S.pathGroup.visible = path.checked;
    if (detail) {
      S.surfaceUniforms.uDetail.value = detail.input.checked ? 1 : 0;
      detail.legend.hidden = !detail.input.checked;
    }
    S.requestRender();
  };
  [tex, con, path, detail && detail.input].forEach((i) => i && i.addEventListener('change', applyLayers));
  applyLayers();

  // ---- views and export ----
  document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => { flight.stop(); nav.view(b.dataset.view); }));
  $('exportBtn').addEventListener('click', () => exportAll(tools, units, T));

  setupKeys(S, nav, tools, flight);

  // ---- first frame ----
  const fit = nav.fitPose();
  nav.setPose(fit.pos, fit.q, DEFAULT_FOV, 'fit');
  S.render();
  minimap.build();
  mmSize = `${$('minimap').clientWidth}x${$('minimap').clientHeight}`;
  S.afterRender.push(() => minimap.draw(), () => sheet.draw());
  S.render();
  loaded = true;
  // Open on the pass itself, a third of the way along, from just behind the drone: the
  // model is best seen from where its photos were taken. "Whole model" is one click away.
  flight.setTime(T.duration * 0.35);
  fitHint();
  loading.classList.add('is-done');

  const params = new URLSearchParams(location.search);
  const demo = params.get('demo');
  if (demo !== null || params.has('debug')) window.__ws = { S, nav, flight, tools, units };
  if (demo) await runDemo(demo, { S, nav, flight, tools, units, $ });
}

// Detail layer, only for packs that carry per-vertex detail: the checkbox goes next to
// Contours and the legend sits above the scale bar, both made here so other models show
// neither.
function setupDetail(S, units, contours) {
  if (!S.detail) return null;
  const label = document.createElement('label');
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.id = 'layerDetail';
  label.append(input, ' Detail');
  contours.closest('label').insertAdjacentElement('afterend', label);
  const legend = document.createElement('div');
  legend.hidden = true;
  legend.setAttribute('aria-live', 'polite');
  legend.style.cssText = 'position:absolute;right:14px;bottom:60px;white-space:nowrap;font-size:var(--t-xs);line-height:1.4;background:rgba(245,247,246,0.92);border:1px solid var(--rule);padding:6px 9px 7px';
  $('scalebar').insertAdjacentElement('beforebegin', legend);
  function fill() {
    const end = (v) => {
      const s = units.small(v);
      return units.isMetric() ? `1 photo pixel covers ${s.text} ${s.unit} here` : `${s.text} units per pixel`;
    };
    legend.innerHTML = `<strong style="font-weight:600">Detail</strong>
<span style="display:block;height:8px;margin:4px 0 4px;background:linear-gradient(to right,#2F6B4F,#D9B44A,#9A3B1F)"></span>
<span style="display:block">Fine: ${end(S.detail.lo)}</span>
<span style="display:block">Coarse: ${end(S.detail.hi)}</span>
<span style="display:flex;align-items:center;gap:6px;margin-top:3px"><span style="display:inline-block;width:10px;height:10px;background:#9AA5A1"></span>Not seen by any keyframe</span>`;
  }
  units.onChange(fill);
  fill();
  return { input, legend };
}

function setupCalibration(S, units, tools) {
  const dlg = $('calibrateDialog');
  const form = dlg.querySelector('form');
  const lenInput = $('calibrateLength');
  const modelNote = $('calibrateModel');
  const intro = dlg.querySelector('p');
  const actions = dlg.querySelector('.ws-dialog-actions');
  const reset = document.createElement('button');
  reset.type = 'button';
  reset.className = 'ws-btn';
  reset.textContent = 'Reset scale';
  actions.appendChild(reset);
  let line = null;

  function refresh() {
    if (units.hadMetres()) intro.textContent = 'This model is scaled from GPS. Draw a line along something whose real length you know to check it; applying replaces the GPS scale.';
    if (line) modelNote.textContent = `The line you drew is ${fmt(line)} model units long.`;
    else if (units.isCalibrated()) modelNote.textContent = `Now ${units.label}. Draw a new line to change it.`;
    else modelNote.textContent = 'Draw the line first, then type its real length.';
    reset.hidden = !units.isCalibrated();
  }
  $('calibrateBtn').addEventListener('click', () => { refresh(); dlg.showModal(); });
  $('calibrateDraw').addEventListener('click', () => {
    dlg.close('draw');
    tools.startCalibration((len) => {
      line = len;
      refresh();
      dlg.showModal();
      lenInput.focus();
    });
  });
  form.querySelector('button[value="cancel"]').addEventListener('click', (e) => {
    e.preventDefault();
    dlg.close('cancel');
  });
  reset.addEventListener('click', () => {
    units.reset();
    line = null;
    dlg.close('reset');
  });
  form.addEventListener('submit', (e) => {
    const v = e.submitter && e.submitter.value;
    if (v !== 'apply') return;
    const metres = parseFloat(lenInput.value);
    if (!line) { e.preventDefault(); modelNote.textContent = 'Draw the line first: press "Draw the line" and click both ends.'; return; }
    if (!(metres > 0)) { e.preventDefault(); lenInput.reportValidity(); return; }
    if (units.hadMetres() && !window.confirm('This model already has a GPS scale. Replace it with the scale from this one length?')) { e.preventDefault(); return; }
    units.calibrate(line, metres);
    line = null;
  });
  dlg.addEventListener('close', () => {
    if (dlg.returnValue !== 'draw') tools.clearCalibration();
  });
}

function setupKeys(S, nav, tools, flight) {
  const toolKeys = {};
  document.querySelectorAll('[data-tool][data-key]').forEach((b) => {
    const k = b.dataset.key.toLowerCase();
    if (k !== 'escape') toolKeys[k] = b.dataset.tool;
  });
  // A and D are both tool shortcuts and movement keys: a tap picks the tool, holding
  // longer than HOLD_MS moves.
  const HOLD_MS = 180;
  const taps = {};
  const skip = (e) => {
    const t = e.target;
    return !!(t && t.closest && t.closest('input, textarea, select, [contenteditable="true"], dialog')) || $('calibrateDialog').open;
  };
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || skip(e)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'shift') { nav.keyDown('shift', true); return; }
    if (k === 'escape') { tools.escape(); return; }
    const onButton = e.target && e.target.closest && e.target.closest('button');
    if (k === 'enter' && !onButton) { tools.enter(); return; }
    if (k === 'delete' || k === 'backspace') { e.preventDefault(); tools.deleteSelected(); return; }
    if (k === 'f') { flight.stop(); nav.view('fit'); return; }
    if (document.activeElement === $('strip') && k.startsWith('arrow')) return;
    if ((k === 'a' || k === 'd') && toolKeys[k]) {
      e.preventDefault();
      if (e.repeat || taps[k]) return;
      const shift = e.shiftKey;
      taps[k] = { held: false, timer: setTimeout(() => { taps[k].held = true; nav.keyDown(k, shift); }, HOLD_MS) };
      return;
    }
    if (nav.keyDown(k, e.shiftKey)) { e.preventDefault(); return; }
    if (toolKeys[k]) tools.setTool(toolKeys[k]);
  });
  document.addEventListener('keyup', (e) => {
    const k = e.key.toLowerCase();
    if (k === 'shift') { nav.keyUp('shift', false); return; }
    if (taps[k]) {
      const t = taps[k];
      delete taps[k];
      clearTimeout(t.timer);
      if (t.held) nav.keyUp(k, e.shiftKey);
      else if (!skip(e)) tools.setTool(toolKeys[k]);
      return;
    }
    nav.keyUp(k, e.shiftKey);
  });
  window.addEventListener('blur', () => {
    for (const k of Object.keys(taps)) { clearTimeout(taps[k].timer); delete taps[k]; }
    nav.releaseAll();
  });
}

// ---- debug hook for headless checks ----
const DEMO_SPOTS = {
  distance: [[-0.5, -0.3], [-0.1, -0.1], [0.3, -0.35]],
  height: [[-0.2, -0.4], [0.25, 0.05]],
  area: [[-0.45, -0.1], [-0.1, -0.05], [-0.05, -0.45], [-0.5, -0.5]],
  volume: [[0.15, -0.05], [0.4, -0.05], [0.4, -0.3], [0.15, -0.3]],
  profile: [[-0.7, -0.2], [0.7, -0.25]],
  sight: [[-0.6, -0.3], [0.6, 0.0]],
  point: [[0.0, -0.2]],
  note: [[0.35, 0.0]],
};
async function runDemo(spec, { S, nav, flight, tools, units, $ }) {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  for (const item of spec.split(',').map((s) => s.trim()).filter(Boolean)) {
    const [key, val] = item.split('=');
    if (['plan', 'oblique', 'pilot', 'fit'].includes(key)) { nav.view(key); await wait(600); }
    else if (key === 't') { flight.setTime(parseFloat(val) || 0); await wait(100); }
    else if (key === 'play') flight.play();
    else if (key === 'contours' || key === 'notex') {
      const box = key === 'contours' ? $('layerContours') : $('layerTexture');
      box.checked = key === 'contours';
      box.dispatchEvent(new Event('change'));
    } else if (key === 'detail' && $('layerDetail')) {
      $('layerDetail').checked = true;
      $('layerDetail').dispatchEvent(new Event('change'));
    } else if (key === 'scale') units.calibrate(1, 5.54);
    else if (key === 'probe' && tools.chartProbe) tools.chartProbe(120);
    else if (key === 'tool') tools.setTool(val);
    else if (DEMO_SPOTS[key]) {
      const pts = DEMO_SPOTS[key].map(([x, y]) => S.pickNDC(x, y)).filter(Boolean);
      if (pts.length >= (key === 'area' || key === 'volume' ? 3 : DEMO_SPOTS[key].length)) {
        tools.create(key, pts, key === 'note' ? { text: 'Culvert under the road, check the drain' } : {});
      } else console.warn(`demo: ${key} spots missed the model`);
      await wait(50);
    }
    S.requestRender();
  }
}

main().catch((e) => {
  console.error(e);
  note(`Could not open the model: ${e.message || e}`);
});
