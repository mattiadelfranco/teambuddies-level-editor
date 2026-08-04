// Height sculpting brushes. The heightmap is 65x65 s16 vertices (row = z,
// col = x), h/8 tiles, positive up; vanilla uses steps of 4 (half a tile).
// A stroke works on a float shadow buffer and commits to store.ed.hm on end
// (snapped to steps of 4 when enabled), so slow drags don't lose fractions.
import { store, tos16 } from './store.js';

export const brush = {
  mode: 'raise',      // raise | lower | flatten | smooth | set
  radius: 3,          // tiles
  strength: 4,        // file units per tick at the brush center
  value: 0,           // target for 'set' (file units)
  snap4: true,
};

let shadow = null;    // Float64Array during a stroke
let touched = null;   // Set of vertex indices modified in this stroke
let flattenTarget = 0;

function falloff(d, r) {
  if (d >= r) return 0;
  return 0.5 + 0.5 * Math.cos(Math.PI * d / r);     // smooth cosine
}

export function beginStroke(tx, tz, invert) {
  const hm = store.ed.hm;
  shadow = new Float64Array(hm);
  touched = new Set();
  // flatten locks its target at the stroke start point
  const i = Math.max(0, Math.min(64, Math.round(tx)));
  const j = Math.max(0, Math.min(64, Math.round(tz)));
  flattenTarget = hm[j * 65 + i];
  moveStroke(tx, tz, invert);
}

export function moveStroke(tx, tz, invert) {
  if (!shadow) return;
  const r = brush.radius, s = brush.strength;
  const i0 = Math.max(0, Math.ceil(tx - r)), i1 = Math.min(64, Math.floor(tx + r));
  const j0 = Math.max(0, Math.ceil(tz - r)), j1 = Math.min(64, Math.floor(tz + r));
  for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
    const f = falloff(Math.hypot(i - tx, j - tz), r);
    if (!f) continue;
    const k = j * 65 + i;
    if (brush.mode === 'raise') shadow[k] += (invert ? -1 : 1) * s * f * 0.5;
    else if (brush.mode === 'lower') shadow[k] -= (invert ? -1 : 1) * s * f * 0.5;
    else if (brush.mode === 'flatten')
      shadow[k] += (flattenTarget - shadow[k]) * Math.min(1, f * s * 0.1);
    else if (brush.mode === 'smooth') {
      const n = (shadow[k - (i > 0 ? 1 : 0)] + shadow[k + (i < 64 ? 1 : 0)]
               + shadow[k - (j > 0 ? 65 : 0)] + shadow[k + (j < 64 ? 65 : 0)]) / 4;
      shadow[k] += (n - shadow[k]) * Math.min(1, f * s * 0.1);
    } else if (brush.mode === 'set') shadow[k] = brush.value;
    touched.add(k);
    // live view: unsnapped preview
    store.ed.hm[k] = Math.max(-32768, Math.min(32767, Math.round(shadow[k])));
  }
  store.apply(st => { st.ed.hmTouched = true; }, 'hm');
}

export function endStroke() {
  if (!shadow) return;
  const hm = store.ed.hm;
  for (const k of touched) {
    let v = shadow[k];
    if (brush.snap4 && brush.mode !== 'set') v = Math.round(v / 4) * 4;
    hm[k] = Math.max(-32768, Math.min(32767, Math.round(v)));
  }
  const warn = padWarnings(touched);
  shadow = null; touched = null;
  store.apply(st => { st.ed.hmTouched = true; }, 'hm');
  if (warn) store.say(warn);
}

export function strokeActive() { return !!shadow; }

// warn if the stroke touched the ground under a pad or crate zone footprint
function padWarnings(set) {
  const st = store.ed, hits = [];
  st.s0.forEach((p, n) => {
    const cx = 32 + tos16(p[0]) / 512, cz = 32 + tos16(p[1]) / 512;
    for (const k of set) {
      const i = k % 65, j = (k / 65) | 0;
      if (Math.abs(i - cx) <= 2.5 && Math.abs(j - cz) <= 2.5) { hits.push('pad ' + (n + 1)); break; }
    }
  });
  st.s3.forEach((p, n) => {
    for (const k of set) {
      const i = k % 65, j = (k / 65) | 0;
      if (Math.abs(i - p[0]) <= 4.5 && Math.abs(j - p[1]) <= 4.5) { hits.push('crate zone ' + (n + 1)); break; }
    }
  });
  return hits.length
    ? '⚠ terrain changed under ' + hits.join(', ') + ' — pads/zones want flat ground.'
    : '';
}
