// Scale state and number formatting. Every measurement is kept in model units; this is
// the only place that turns them into what the page shows.

const METRIC = new Set(['gnss', 'gnss+rtk', 'calibrated']);

function storageKey(id) { return `tesseract.scale.${id || 'model'}`; }

export function createUnits(T) {
  const original = {
    factor: (T.scale && +T.scale.factor) || 1,
    status: (T.scale && T.scale.status) || 'unvalidated',
    label: (T.scale && T.scale.label) || '',
  };
  const state = { ...original, lengthM: null };
  const listeners = [];

  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(T.id)) || 'null');
    if (saved && saved.factor > 0) Object.assign(state, saved, { status: 'calibrated' });
  } catch (e) { /* storage blocked: start from the packed scale */ }

  const api = {
    get factor() { return state.factor; },
    get status() { return state.status; },
    get label() { return state.label; },
    get original() { return original; },
    isMetric() { return METRIC.has(state.status); },
    isCalibrated() { return state.status === 'calibrated'; },
    hadMetres() { return METRIC.has(original.status) && original.status !== 'calibrated'; },
    unit(power = 1) {
      const u = api.isMetric() ? 'm' : 'units';
      return power === 2 ? `${u}²` : power === 3 ? `${u}³` : u;
    },
    // Model length, area or volume to display units.
    len(v) { return v * state.factor; },
    area(v) { return v * state.factor * state.factor; },
    vol(v) { return v * state.factor * state.factor * state.factor; },
    fmt,
    fmtLen(v) { return `${fmt(api.len(v))} ${api.unit()}`; },
    // A small length such as the surface one photo pixel covers: centimetres when metric.
    small(v) {
      const d = api.len(v);
      if (!api.isMetric()) return { text: fmt(d), unit: 'units' };
      return d < 1 ? { text: fmt(d * 100), unit: 'cm' } : { text: fmt(d), unit: 'm' };
    },
    headline() {
      if (state.status === 'calibrated') return 'metres (calibrated)';
      if (api.isMetric()) return 'metres';
      return 'model units';
    },
    calibrate(modelLength, metres) {
      state.factor = metres / modelLength;
      state.status = 'calibrated';
      state.lengthM = metres;
      state.label = `calibrated from one ${metres.toFixed(2)} m length`;
      try {
        localStorage.setItem(storageKey(T.id), JSON.stringify({ factor: state.factor, lengthM: metres, label: state.label }));
      } catch (e) { /* not persisted; the calibration still applies to this visit */ }
      emit();
    },
    reset() {
      Object.assign(state, original, { lengthM: null });
      try { localStorage.removeItem(storageKey(T.id)); } catch (e) { /* nothing stored */ }
      emit();
    },
    onChange(fn) { listeners.push(fn); },
  };
  function emit() { for (const fn of listeners) fn(api); }
  return api;
}

// Fixed decimals by magnitude so columns line up; thousands grouped with a thin space.
export function fmt(v, digits) {
  if (v === null || v === undefined || isNaN(v)) return 'n/a';
  const a = Math.abs(v);
  const d = digits !== undefined ? digits : a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : a >= 0.01 ? 3 : 4;
  const s = v.toFixed(d);
  if (a < 10000) return s;
  const [int, frac] = s.split('.');
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + (frac ? `.${frac}` : '');
}

// A tick or scale-bar value without trailing zeros.
export function fmtNice(v) {
  return String(Number(v.toPrecision(6)));
}
