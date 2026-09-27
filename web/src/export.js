// GeoJSON of every measurement plus a CSV summary, downloaded through Blob links.
import { localToLatLon } from './geom.js';

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

const round = (v) => Math.round(v * 1e6) / 1e6;

export function buildGeoJSON(measures, tools, units, T) {
  const f = units.factor;
  // Local frame: x east, y north (= -z), height. With a georeference: lon, lat, height.
  const coord = (p) => {
    const x = p.x * f, y = p.y * f, z = p.z * f;
    if (T.georef) {
      const g = localToLatLon(x, y, z, T.georef);
      return [Number(g.lon.toFixed(9)), Number(g.lat.toFixed(9)), round(g.h)];
    }
    return [round(x), round(-z), round(y)];
  };
  const features = measures.map((m) => {
    let geometry;
    if (m.kind === 'point' || m.kind === 'note') geometry = { type: 'Point', coordinates: coord(m.pts[0]) };
    else if (m.kind === 'area' || m.kind === 'volume') {
      const ring = m.pts.map(coord);
      ring.push(ring[0]);
      geometry = { type: 'Polygon', coordinates: [ring] };
    } else geometry = { type: 'LineString', coordinates: m.pts.map(coord) };
    const readouts = {};
    for (const r of tools.rows(m)) readouts[r.label] = r.unit ? `${r.text} ${r.unit}` : r.text;
    const props = { name: m.name, kind: m.kind, readouts };
    if (m.kind === 'note') props.note = m.text;
    if (m.kind === 'volume') props.base = m.baseMode;
    return { type: 'Feature', geometry, properties: props };
  });
  return {
    type: 'FeatureCollection',
    name: `${T.title || 'Tesseract'} measurements`,
    properties: {
      model: T.id,
      units: units.isMetric() ? 'metres' : 'model units',
      scale: { factor: units.factor, status: units.status, label: units.label },
      frame: T.georef ? 'WGS84 lon, lat, height' : 'local: x east, y north, z up',
      georef: T.georef || null,
    },
    features,
  };
}

function csvCell(v) {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function buildCSV(measures, tools) {
  const lines = [['name', 'kind', 'measure', 'value', 'unit', 'details'].join(',')];
  for (const m of measures) {
    const rows = tools.rows(m);
    const lead = rows.find((r) => r.lead) || rows[0];
    const details = rows.filter((r) => r !== lead).map((r) => `${r.label} ${r.text}${r.unit ? ` ${r.unit}` : ''}`).join('; ');
    lines.push([m.name, m.kind, lead.label, lead.text, lead.unit, details].map(csvCell).join(','));
  }
  return lines.join('\r\n') + '\r\n';
}

export function exportAll(tools, units, T) {
  const ms = tools.measures;
  if (!ms.length) return;
  const stem = `tesseract-${T.id || 'model'}-measurements`;
  download(`${stem}.geojson`, JSON.stringify(buildGeoJSON(ms, tools, units, T), null, 1), 'application/geo+json');
  setTimeout(() => download(`${stem}.csv`, buildCSV(ms, tools), 'text/csv'), 300);
}
