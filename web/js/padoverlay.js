// Live pad visuals: when a pad/spawn (s0) marker moves, the painted 4x4
// tiles follow it on the shared ground canvas (2D view, 3D texture, minimap).
// Pure VISUAL overlay computed from saved baseline (lvl.s0) vs current state
// (ed.s0): store.ed.tiles is never touched — the server performs the real
// move on save (_repaint_pads) and the reloaded baseline turns this into a
// no-op. Mirrors the server rules: grass caps on every old block first, then
// pads on the new blocks; out-of-bounds moves are skipped; added pads show a
// copy of pad 1's block; deleted pads leave the grass cap.
import { store, tos16 } from './store.js';
import * as TL from './tiles.js';

let applied = [];      // canvas cells currently owned by the overlay
let sig = null;
let entry = null;

const ct = raw => 32 + tos16(raw) / 512;          // s0 raw -> tile center x.5
function blockOf(cx, cz) {
  const x = Math.round(cx - 0.5) - 1, z = Math.round(cz - 0.5) - 1;
  const b = [];
  for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) b.push([x + i, z + j]);
  return b;
}
const inb = b => b.every(([x, z]) => x >= 0 && x < 64 && z >= 0 && z < 64);

// most common record around the block (grass cap), excluding every old block
function fillerOff(tl, ob, oldAll) {
  const [x0, z0] = ob[0];
  const seen = new Map();
  let best = ob[0][1] * 64 + ob[0][0], bn = 0;
  for (let x = x0 - 1; x < x0 + 5; x++) for (let z = z0 - 1; z < z0 + 5; z++) {
    if (x < 0 || x >= 64 || z < 0 || z >= 64) continue;
    const i = z * 64 + x;
    if (oldAll.has(i)) continue;
    let key = '';
    for (let k = 0; k < 28; k++) key += String.fromCharCode(tl[i * 28 + k]);
    const n = (seen.get(key) || 0) + 1;
    seen.set(key, n);
    if (n > bn) { bn = n; best = i; }
  }
  return best * 28;
}

// recompute the overlay; returns true if the ground canvas changed
export function update(force) {
  if (!store.ed || !store.lvl) return false;
  if (entry !== store.entry) {          // level switch: canvas gets replaced,
    entry = store.entry;                // forget foreign cells without repaint
    applied = [];
    sig = null;
    force = true;
  }
  if (!TL.T.canvas || !TL.T.atlas || TL.T.entry !== store.entry) return false;
  const base = store.lvl.s0, cur = store.ed.s0;
  const acts = [];
  for (let i = 0; i < Math.min(base.length, cur.length); i++) {
    const ob = blockOf(ct(base[i][0]), ct(base[i][1]));
    const nb = blockOf(ct(cur[i][0]), ct(cur[i][1]));
    if ((ob[0][0] !== nb[0][0] || ob[0][1] !== nb[0][1]) && inb(ob) && inb(nb))
      acts.push({ ob, nb });
  }
  for (let i = cur.length; i < base.length; i++) {         // deleted pads
    const ob = blockOf(ct(base[i][0]), ct(base[i][1]));
    if (inb(ob)) acts.push({ ob });
  }
  if (cur.length > base.length && base.length > 0) {       // added pads
    const sb = blockOf(ct(base[0][0]), ct(base[0][1]));
    for (let i = base.length; i < cur.length; i++) {
      const nb = blockOf(ct(cur[i][0]), ct(cur[i][1]));
      if (inb(sb) && inb(nb)) acts.push({ sb, nb });
    }
  }
  const s = acts.map(a => (a.ob ? 'o' + a.ob[0] : '') + (a.sb ? 's' + a.sb[0] : '')
                        + (a.nb ? 'n' + a.nb[0] : '')).join(';');
  if (!force && s === sig) return false;
  sig = s;
  for (const i of applied) TL.patchCanvas(i);   // restore the base tiles
  applied = [];
  if (!acts.length) return true;
  const tl = store.ed.tiles;
  const oldAll = new Set();
  for (const a of acts) if (a.ob) for (const [x, z] of a.ob) oldAll.add(z * 64 + x);
  for (const a of acts) {                        // grass caps first
    if (!a.ob) continue;
    const off = fillerOff(tl, a.ob, oldAll);
    for (const [x, z] of a.ob) {
      TL.drawRecAt(z * 64 + x, tl, off);
      applied.push(z * 64 + x);
    }
  }
  for (const a of acts) {                        // then the pads
    if (!a.nb) continue;
    const src = a.sb || a.ob;
    for (let k = 0; k < 16; k++) {
      const i = a.nb[k][1] * 64 + a.nb[k][0];
      TL.drawRecAt(i, tl, (src[k][1] * 64 + src[k][0]) * 28);
      applied.push(i);
    }
  }
  return true;
}
