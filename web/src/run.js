// Entry point for run.html: pick a processed flight or upload a video, then play the chosen
// run's recorded stage log (pack_site.replay) in real time before opening the workspace.

const MODELS = (window.TESSERACT_MODELS || []).filter((m) => m.replay);
const $ = (id) => document.getElementById(id);

function clock(s) {
  const r = Math.max(0, Math.floor(s));
  return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}`;
}
function dur(s) {
  if (s < 10) return `${s.toFixed(1)} s`;
  if (s < 60) return `${Math.round(s)} s`;
  return clock(s);
}
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ---- choose ----
function listFlights() {
  const ul = $('flights');
  if (!MODELS.length) {
    ul.innerHTML = '<li class="note">No processed flights are packed with this copy yet.</li>';
    return;
  }
  ul.innerHTML = MODELS.map((m) => {
    const r = m.replay;
    return `<li><button type="button" data-id="${esc(m.id)}"><b>${esc(m.title)}</b>` +
      `<span>${esc(r.file)}, a ${Math.round(r.duration_s)} s pass, reconstructed in ${Math.round(r.wall_s)} s` +
      `${m.units === 'metres' ? ', in metres' : ''}</span><em>Replay the run</em></button></li>`;
  }).join('');
  ul.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    start(MODELS.find((m) => m.id === b.dataset.id));
  }));
}

function wireDrop() {
  const drop = $('drop');
  const input = $('file');
  const take = (f) => { if (f && MODELS.length) start(MODELS[0], f); };
  input.addEventListener('change', () => take(input.files[0]));
  ['dragenter', 'dragover'].forEach((e) => drop.addEventListener(e, (ev) => {
    ev.preventDefault();
    drop.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach((e) => drop.addEventListener(e, (ev) => {
    ev.preventDefault();
    drop.classList.remove('over');
  }));
  drop.addEventListener('drop', (ev) => take(ev.dataTransfer && ev.dataTransfer.files[0]));
}

// ---- the run ----
let speed = Number(new URLSearchParams(location.search).get('speed')) || 1;
let raf = 0;
let countdown = 0;

function uploadStage(file) {
  const mb = file.size / 1e6;
  return {
    label: 'Upload', what: 'The clip goes to the processing machine.',
    seconds: Math.min(30, Math.max(3, mb / 40)),
    upload: mb,
    done: `${mb.toFixed(mb < 10 ? 1 : 0)} MB received`,
  };
}

function start(model, file) {
  const r = model.replay;
  const stages = (file ? [uploadStage(file)] : []).concat(r.stages);
  let at = 0;
  stages.forEach((s) => { s.start = at; at += s.seconds; });
  const total = at;

  $('choose').hidden = true;
  $('progress').hidden = false;
  window.scrollTo(0, 0);
  $('runTitle').textContent = file ? 'Reconstructing your clip' : `Reconstructing ${model.title}`;
  $('runFile').textContent = file
    ? `${file.name}, ${(file.size / 1e6).toFixed(0)} MB`
    : `${r.file}, a ${r.duration_s} s single pass`;
  if (file) {
    // The clip's own length, once the browser has read its header.
    const v = document.createElement('video');
    v.preload = 'metadata';
    v.onloadedmetadata = () => {
      if (isFinite(v.duration)) $('runFile').textContent += `, ${v.duration.toFixed(1)} s`;
      URL.revokeObjectURL(v.src);
    };
    v.src = URL.createObjectURL(file);
  }
  $('total').textContent = clock(total);
  $('budget').textContent = r.budget_s ? `budget ${Math.round(r.budget_s / 60)} minutes` : '';
  $('stages').innerHTML = stages.map((s, i) =>
    `<li class="stage" data-s="waiting" id="st${i}"><span class="dot"></span><b>${esc(s.label)}</b>` +
    `<span class="what">${esc(s.what)}</span><span class="t"></span>` +
    `<span class="step"></span><span class="bar"><i></i></span></li>`).join('');
  const rows = stages.map((s, i) => {
    const li = $(`st${i}`);
    return { li, t: li.querySelector('.t'), step: li.querySelector('.step'), bar: li.querySelector('.bar i') };
  });

  const ws = `workspace.html?model=${encodeURIComponent(model.id)}`;
  $('openWs').href = ws;
  let t = 0;
  let last = performance.now();
  const shown = new Array(stages.length).fill('');

  function frame(now) {
    // A hidden tab stops the clock rather than jumping ahead when it comes back.
    t = Math.min(total, t + Math.min(1, (now - last) / 1000) * speed);
    last = now;
    stages.forEach((s, i) => {
      const row = rows[i];
      const local = t - s.start;
      const state = local <= 0 && t < total ? 'waiting' : local >= s.seconds ? 'done' : 'running';
      if (shown[i] !== state) { row.li.dataset.s = state; shown[i] = state; }
      if (state === 'running') {
        row.t.textContent = `${dur(local)} / ${dur(s.seconds)}`;
        row.bar.style.width = `${(100 * local) / s.seconds}%`;
        if (s.upload) {
          row.step.textContent = `${((s.upload * local) / s.seconds).toFixed(0)} of ${s.upload.toFixed(0)} MB`;
        } else if (s.steps && s.steps.length) {
          let acc = 0;
          const cur = s.steps.find((st) => (acc += st.seconds) > local) || s.steps[s.steps.length - 1];
          row.step.textContent = cur.label;
        }
      } else if (state === 'done' && row.t.textContent !== dur(s.seconds)) {
        row.t.textContent = dur(s.seconds);
        row.bar.style.width = '100%';
        row.step.textContent = s.done ? s.done[0].toUpperCase() + s.done.slice(1) : '';
      }
    });
    $('overallBar').style.width = `${(100 * t) / total}%`;
    $('elapsed').textContent = clock(t);
    if (t < total) raf = requestAnimationFrame(frame);
    else finish(model, file, ws, r);
  }
  raf = requestAnimationFrame(frame);
}

function finish(model, file, ws, r) {
  $('ready').hidden = false;
  $('readyText').textContent = `Model ready in ${clock(r.wall_s)}.`;
  $('readyNote').textContent = file
    ? 'This copy opens the demo clip\'s model; your clip would run on the laptop.'
    : `${model.title}, ${model.units}.`;
  let n = 5;
  const a = $('openWs');
  const tick = () => {
    a.textContent = `Open in the workspace (${n})`;
    if (n-- <= 0) location.href = ws;
  };
  tick();
  countdown = setInterval(tick, 1000);
}

document.querySelectorAll('.speed button').forEach((b) => {
  b.setAttribute('aria-pressed', String(Number(b.dataset.speed) === speed));
  b.addEventListener('click', () => {
    speed = Number(b.dataset.speed);
    document.querySelectorAll('.speed button').forEach((o) => o.setAttribute('aria-pressed', String(o === b)));
  });
});
$('stay').addEventListener('click', () => {
  clearInterval(countdown);
  $('openWs').textContent = 'Open in the workspace';
});

listFlights();
wireDrop();
const pre = new URLSearchParams(location.search).get('replay');
if (pre) {
  const m = MODELS.find((x) => x.id === pre);
  if (m) start(m);
}
