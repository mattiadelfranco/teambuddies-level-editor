// AI-walk (PTH) editing: the engine's AI — enemies, animals, AI buddies —
// only paths through half-tile cells whose PTH byte has bit 16 CLEAR. The
// player ignores this grid entirely (movement uses the real terrain), which
// is why a resculpted map "works" for you but breaks the AI: it still sees
// the vanilla layout. Paint blocked cells under new walls, free the routes
// you open, or let "Auto" mark steep slopes. Small non-zero values (2/3/5)
// are vanilla AI hints (preferred lanes/POIs) — unknown encoding, so this
// tool only ever touches bit 16 and leaves them alone.
import { store } from './store.js';

export const A = {
  mode: 'block',        // block | free
  size: 2,              // brush size in half-tiles (1-6)
};

export const BLOCKED = 16;

function cells(hx, hz) {
  const half = (A.size - 1) / 2;
  const out = [];
  for (let dz = 0; dz < A.size; dz++)
    for (let dx = 0; dx < A.size; dx++) {
      const x = Math.floor(hx - half + dx), z = Math.floor(hz - half + dz);
      if (x >= 0 && x < 128 && z >= 0 && z < 128) out.push(z * 128 + x);
    }
  return out;
}

// paint at world coords (0..512); returns true if anything changed
export function paintAt(wx, wz, alt) {
  const g = store.ed.pth;
  if (!g) return false;
  const block = (A.mode === 'block') !== !!alt;   // Alt inverts the mode
  let changed = false;
  for (const i of cells(wx / 4, wz / 4)) {
    const v = block ? (g[i] | BLOCKED) : (g[i] & ~BLOCKED);
    if (v !== g[i]) { g[i] = v; changed = true; }
  }
  if (changed) store.apply(s => { s.ed.pthTouched = true; }, 'pth');
  return changed;
}

// mark cells whose parent tile has a steep height step as blocked (add-only:
// never frees anything, so vanilla water/cliff blocks are preserved)
export function autoFromSlopes(threshold = 10) {
  const g = store.ed.pth, hm = store.ed.hm;
  if (!g) return 0;
  let n = 0;
  for (let tz = 0; tz < 64; tz++)
    for (let tx = 0; tx < 64; tx++) {
      const h = [hm[tz * 65 + tx], hm[tz * 65 + tx + 1],
                 hm[(tz + 1) * 65 + tx], hm[(tz + 1) * 65 + tx + 1]];
      if (Math.max(...h) - Math.min(...h) < threshold) continue;
      for (const [dx, dz] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
        const i = (tz * 2 + dz) * 128 + tx * 2 + dx;
        if (!(g[i] & BLOCKED)) { g[i] |= BLOCKED; n++; }
      }
    }
  if (n) store.apply(s => { s.ed.pthTouched = true; }, 'pth');
  return n;
}
