// Live pad visuals: when a pad/spawn (s0) marker moves, the painted pad ART
// follows it on the shared ground canvas (2D view, 3D texture, minimap).
// The art is the 2x2 CENTER only (colored square with baked arrows, team
// clut): the ring of the 4x4 block is local grass/ground and is never
// transplanted — the destination keeps its terrain and the decoration around
// the old spot stays. Pure VISUAL overlay computed from saved baseline
// (lvl.s0) vs current state (ed.s0): store.ed.tiles is never touched — the
// server performs the real move on save (_repaint_pads) and the reloaded
// baseline turns this into a no-op. Mirrors the server rules: local-ground
// caps on every old center first, then art on the new centers; out-of-bounds
// moves are skipped; added pads show a copy of pad 1's art; deleted pads
// leave the cap.
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
function centerOf(cx, cz) {
  const x = Math.round(cx - 0.5), z = Math.round(cz - 0.5);
  return [[x, z], [x + 1, z], [x, z + 1], [x + 1, z + 1]];
}
const inb = b => b.every(([x, z]) => x >= 0 && x < 64 && z >= 0 && z < 64);

// most common record of the block's ring (the local ground around the pad
// art): the right cap for the 2x2 center hole
function ringFillerOff(tl, cx, cz) {
  const ctr = new Set(centerOf(cx, cz).map(([x, z]) => z * 64 + x));
  const seen = new Map();
  let best = -1, bn = 0;
  for (const [x, z] of blockOf(cx, cz)) {
    const i = z * 64 + x;
    if (ctr.has(i) || x < 0 || x >= 64 || z < 0 || z >= 64) continue;
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
  const acts = [];                      // {oc:[cx,cz]?, sc:[cx,cz]?, nc:[cx,cz]?}
  for (let i = 0; i < Math.min(base.length, cur.length); i++) {
    const oc = [ct(base[i][0]), ct(base[i][1])];
    const nc = [ct(cur[i][0]), ct(cur[i][1])];
    if ((oc[0] !== nc[0] || oc[1] !== nc[1])
        && inb(blockOf(...oc)) && inb(blockOf(...nc))) acts.push({ oc, nc });
  }
  for (let i = cur.length; i < base.length; i++) {         // deleted pads
    const oc = [ct(base[i][0]), ct(base[i][1])];
    if (inb(blockOf(...oc))) acts.push({ oc });
  }
  if (cur.length > base.length && base.length > 0) {       // added pads
    const sc = [ct(base[0][0]), ct(base[0][1])];
    for (let i = base.length; i < cur.length; i++) {
      const nc = [ct(cur[i][0]), ct(cur[i][1])];
      if (inb(blockOf(...sc)) && inb(blockOf(...nc))) acts.push({ sc, nc });
    }
  }
  const s = acts.map(a => (a.oc ? 'o' + a.oc : '') + (a.sc ? 's' + a.sc : '')
                        + (a.nc ? 'n' + a.nc : '')).join(';');
  if (!force && s === sig) return false;
  sig = s;
  for (const i of applied) TL.patchCanvas(i);   // restore the base tiles
  applied = [];
  if (!acts.length) return true;
  const tl = store.ed.tiles;
  for (const a of acts) {                        // local-ground caps first
    if (!a.oc) continue;
    const off = ringFillerOff(tl, ...a.oc);
    for (const [x, z] of centerOf(...a.oc)) {
      TL.drawRecAt(z * 64 + x, tl, off);
      applied.push(z * 64 + x);
    }
  }
  for (const a of acts) {                        // then the pad art
    if (!a.nc) continue;
    const src = centerOf(...(a.sc || a.oc));
    const dst = centerOf(...a.nc);
    for (let k = 0; k < 4; k++) {
      const i = dst[k][1] * 64 + dst[k][0];
      TL.drawRecAt(i, tl, (src[k][1] * 64 + src[k][0]) * 28);
      applied.push(i);
    }
  }
  return true;
}
