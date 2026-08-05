// Tile painting engine: level atlas (4bpp TIM + CLUTs), the editable 64x64
// tile array (28B records) and the shared ground canvas both views draw.
//
// Record: [u16 U][u8 V][4x s8 corner deltas][u8 clut][16B vertex colors]
// [u32 flags]. U/V pick the 64x64 atlas cell corner; the deltas encode one
// of 8 orientations; the sampled cell is v-flipped at render time (the UV
// base corner is the SOUTH vertex — engine quirk, same as render_ground.py).
import { store } from './store.js';
import { b64u8 } from './api.js';

// the 8 orientations: (du1,dv1)=M*(63,0), (du2,dv2)=M*(0,63) for the 8
// symmetries of the square; base corner = 0 or 63 so sampling spans the cell
export const ORIENTS = [];
for (const mir of [1, -1]) for (let r = 0; r < 4; r++) {
  const c = [1, 0, -1, 0][r], s = [0, 1, 0, -1][r];
  const du1 = 63 * c * mir, dv1 = 63 * s, du2 = -63 * s * mir, dv2 = 63 * c;
  ORIENTS.push({ u0: du1 + du2 > 0 ? 0 : 63, v0: dv1 + dv2 > 0 ? 0 : 63,
                 d: [du1, dv1, du2, dv2] });
}
export function orientIndex(u0, v0, d) {
  for (let i = 0; i < 8; i++) {
    const o = ORIENTS[i];
    if (o.u0 === u0 && o.v0 === v0 && o.d[0] === d[0] && o.d[1] === d[1]
        && o.d[2] === d[2] && o.d[3] === d[3]) return i;
  }
  return 0;
}

export const T = {
  atlas: null,          // {w, h, idx: Uint8Array nibbles, cluts}
  entry: null,
  canvas: null,         // shared ground canvas (native atlas res: 64 px/tile)
  cellClut: null,       // per-cell most common clut in this level
  stamp: { cell: 0, clut: 0, autoClut: true, orient: 0 },
  mode: 'paint',        // paint | fill | clone | pick | copy | paste
  size: 1,              // paint brush size (tiles)
  cloneSrc: null,       // [tx,tz] clone source anchor
  cloneDelta: null,     // stamp offset while clone-painting
  onPatch: null,        // callback(tileIdx) after a tile is painted
  clip: null,           // region clipboard {w, h, recs, hm} — survives level switches
  rel: true,            // paste heights relative to the target terrain
};

const cellCache = new Map();

export async function loadAtlas(entry) {
  if (T.entry === entry && T.atlas) return;
  const a = await (await fetch('/api/atlas/' + entry)).json();
  const raw = b64u8(a.idx);
  const idx = new Uint8Array(a.w * a.h);
  for (let i = 0; i < raw.length; i++) {
    idx[2 * i] = raw[i] & 15;
    idx[2 * i + 1] = raw[i] >> 4;
  }
  T.atlas = { w: a.w, h: a.h, idx, cluts: a.cluts };
  T.entry = entry;
  cellCache.clear();
  // per-cell dominant clut (for "auto" clut picking)
  const count = new Map();
  const tl = store.ed.tiles;
  const dv = new DataView(tl.buffer, tl.byteOffset);
  for (let i = 0; i < 4096; i++) {
    const u = dv.getUint16(i * 28, true);
    if (u >= a.w) continue;
    const cell = ((tl[i * 28 + 2] >> 6) * (a.w >> 6)) + (u >> 6);
    const key = cell * 256 + tl[i * 28 + 7];
    count.set(key, (count.get(key) || 0) + 1);
  }
  T.cellClut = new Map();
  for (const [key, n] of count) {
    const cell = key >> 8, clut = key & 255;
    if (!T.cellClut.has(cell) || n > T.cellClut.get(cell)[1])
      T.cellClut.set(cell, [clut, n]);
  }
}

export function cellsX() { return T.atlas ? T.atlas.w >> 6 : 16; }
export function autoClutFor(cell) {
  const e = T.cellClut && T.cellClut.get(cell);
  return e ? e[0] : 0;
}
export function stampClut() {
  return T.stamp.autoClut ? autoClutFor(T.stamp.cell) : T.stamp.clut;
}

// render one atlas cell with a clut+orientation -> ImageData 64x64 (cached)
export function renderCell(cell, clut, orient) {
  const key = cell * 4096 + clut * 8 + orient;
  let im = cellCache.get(key);
  if (im) return im;
  const A = T.atlas, o = ORIENTS[orient];
  const cu = (cell % cellsX()) * 64, cv = (cell / cellsX() | 0) * 64;
  const cl = A.cluts[Math.min(clut, A.cluts.length - 1)];
  im = new ImageData(64, 64);
  const px = im.data;
  for (let y = 0; y < 64; y++) {
    const yy = 63 - y;                       // vertical flip (south base corner)
    for (let x = 0; x < 64; x++) {
      let su = Math.round(o.u0 + (x * o.d[0] + yy * o.d[2]) / 63);
      let sv = Math.round(o.v0 + (x * o.d[1] + yy * o.d[3]) / 63);
      su = su < 0 ? 0 : su > 63 ? 63 : su;
      sv = sv < 0 ? 0 : sv > 63 ? 63 : sv;
      const c = cl[A.idx[(cv + sv) * A.w + cu + su]];
      const k = (y * 64 + x) * 4;
      px[k] = c[0]; px[k + 1] = c[1]; px[k + 2] = c[2]; px[k + 3] = c[3];
    }
  }
  cellCache.set(key, im);
  return im;
}

// ---- shared ground canvas ----
export function setGroundImage(img) {
  if (!T.canvas) T.canvas = document.createElement('canvas');
  T.canvas.width = T.canvas.height = 4096;
  const x = T.canvas.getContext('2d');
  x.clearRect(0, 0, 4096, 4096);
  x.drawImage(img, 0, 0, 4096, 4096);
}
export function groundCanvas() { return T.canvas; }

function patchCanvas(i) {
  if (!T.canvas || !T.atlas) return;
  const tl = store.ed.tiles;
  const dv = new DataView(tl.buffer, tl.byteOffset);
  const u = dv.getUint16(i * 28, true), v = tl[i * 28 + 2];
  const d = [dv.getInt8(i * 28 + 3), dv.getInt8(i * 28 + 4),
             dv.getInt8(i * 28 + 5), dv.getInt8(i * 28 + 6)];
  const cell = ((v >> 6) * cellsX()) + (u >> 6);
  let im = renderCell(cell, tl[i * 28 + 7], orientIndex(u & 63, v & 63, d));
  // vertex-color modulation (mean of the 4 corners, 128 = neutral) — same
  // as render_ground.py, so the client patch matches the server PNG
  const co = i * 28 + 8;
  let mr = 0, mg = 0, mb = 0;
  for (let k = 0; k < 4; k++) { mr += tl[co + k * 4]; mg += tl[co + k * 4 + 1]; mb += tl[co + k * 4 + 2]; }
  mr /= 512; mg /= 512; mb /= 512;
  if (mr !== 1 || mg !== 1 || mb !== 1) {
    const out = new ImageData(new Uint8ClampedArray(im.data), 64, 64);
    const p = out.data;
    for (let k = 0; k < p.length; k += 4) {
      p[k] = p[k] * mr; p[k + 1] = p[k + 1] * mg; p[k + 2] = p[k + 2] * mb;
    }
    im = out;
  }
  T.canvas.getContext('2d').putImageData(im, (i % 64) * 64, (i >> 6) * 64);
  if (T.onPatch) T.onPatch(i);
}

// shade brush: scale the 4 vertex colors of a tile (darken, Alt = lighten)
function shadeTile(i, lighten) {
  const tl = store.ed.tiles, co = i * 28 + 8;
  const f = lighten ? 1.12 : 0.89;
  for (let k = 0; k < 4; k++) for (let c = 0; c < 3; c++) {
    const o = co + k * 4 + c;
    tl[o] = Math.max(16, Math.min(255, Math.round(tl[o] * f)));
  }
  patchCanvas(i);
}

// ---- painting ----
export function readTile(tx, tz) {           // eyedropper
  const i = idxAt(tx, tz);
  if (i < 0) return;
  const tl = store.ed.tiles;
  const dv = new DataView(tl.buffer, tl.byteOffset);
  const u = dv.getUint16(i * 28, true), v = tl[i * 28 + 2];
  T.stamp.cell = ((v >> 6) * cellsX()) + (u >> 6);
  T.stamp.clut = tl[i * 28 + 7];
  T.stamp.autoClut = false;
  T.stamp.orient = orientIndex(u & 63, v & 63,
    [dv.getInt8(i * 28 + 3), dv.getInt8(i * 28 + 4),
     dv.getInt8(i * 28 + 5), dv.getInt8(i * 28 + 6)]);
}

function idxAt(tx, tz) {
  const x = Math.floor(tx), z = Math.floor(tz);
  return (x >= 0 && x < 64 && z >= 0 && z < 64) ? z * 64 + x : -1;
}

function writeStamp(i) {
  const tl = store.ed.tiles;
  const dv = new DataView(tl.buffer, tl.byteOffset);
  const o = ORIENTS[T.stamp.orient];
  const cx = (T.stamp.cell % cellsX()) * 64, cy = (T.stamp.cell / cellsX() | 0) * 64;
  dv.setUint16(i * 28, cx + o.u0, true);
  tl[i * 28 + 2] = cy + o.v0;
  dv.setInt8(i * 28 + 3, o.d[0]); dv.setInt8(i * 28 + 4, o.d[1]);
  dv.setInt8(i * 28 + 5, o.d[2]); dv.setInt8(i * 28 + 6, o.d[3]);
  tl[i * 28 + 7] = stampClut();
  for (let k = 0; k < 4; k++)                      // neutral vertex colors
    tl.set([128, 128, 128, 0], i * 28 + 8 + k * 4);
  dv.setUint32(i * 28 + 24, 0, true);              // flags
  patchCanvas(i);
}

function copyTile(src, dst) {
  const tl = store.ed.tiles;
  tl.copyWithin(dst * 28, src * 28, src * 28 + 28);
  patchCanvas(dst);
}

export function beginPaintStroke() { T._stroked = new Set(); }

export function paintAt(tx, tz, alt) {
  const st = store.ed;
  let painted = false, animHit = false;
  const half = (T.size - 1) / 2;
  for (let dz = 0; dz < T.size; dz++) for (let dx = 0; dx < T.size; dx++) {
    const i = idxAt(tx - half + dx, tz - half + dz);
    if (i < 0) continue;
    if (T.mode === 'shade') {
      // once per tile per stroke, or a drag would darken to black instantly
      if (T._stroked && T._stroked.has(i)) continue;
      if (T._stroked) T._stroked.add(i);
      shadeTile(i, alt);
    } else if (T.mode === 'clone' && T.cloneDelta) {
      const sx = (i % 64) + T.cloneDelta[0], sz = (i >> 6) + T.cloneDelta[1];
      const si = idxAt(sx + 0.5, sz + 0.5);
      if (si < 0 || si === i) continue;
      copyTile(si, i);
    } else {
      writeStamp(i);
    }
    if (T.mode !== 'shade' && store.lvl.animTiles.includes(i)) animHit = true;
    painted = true;
  }
  if (painted) store.apply(s => { s.ed.tilesTouched = true; }, 'tiles');
  if (animHit) store.say('⚠ painted over an ANIMATED tile — its animation entries will be removed on save.');
  return painted;
}

export function fillRect(tx0, tz0, tx1, tz1) {
  const x0 = Math.max(0, Math.min(Math.floor(tx0), Math.floor(tx1)));
  const x1 = Math.min(63, Math.max(Math.floor(tx0), Math.floor(tx1)));
  const z0 = Math.max(0, Math.min(Math.floor(tz0), Math.floor(tz1)));
  const z1 = Math.min(63, Math.max(Math.floor(tz0), Math.floor(tz1)));
  let animHit = false;
  for (let z = z0; z <= z1; z++) for (let x = x0; x <= x1; x++) {
    writeStamp(z * 64 + x);
    if (store.lvl.animTiles.includes(z * 64 + x)) animHit = true;
  }
  store.apply(s => { s.ed.tilesTouched = true; }, 'tiles');
  if (animHit) store.say('⚠ painted over ANIMATED tiles — their animation entries will be removed on save.');
}

// refresh the whole canvas from the tile array (after reload from disk)
export function repaintAll() {
  if (!T.atlas || !T.canvas) return;
  for (let i = 0; i < 4096; i++) patchCanvas(i);
}

// ---- region copy/paste (tiles + heights, works across levels) ----
export function copyRegion(tx0, tz0, tx1, tz1) {
  const x0 = Math.max(0, Math.min(Math.floor(tx0), Math.floor(tx1)));
  const x1 = Math.min(63, Math.max(Math.floor(tx0), Math.floor(tx1)));
  const z0 = Math.max(0, Math.min(Math.floor(tz0), Math.floor(tz1)));
  const z1 = Math.min(63, Math.max(Math.floor(tz0), Math.floor(tz1)));
  const w = x1 - x0 + 1, h = z1 - z0 + 1;
  const tl = store.ed.tiles, hm = store.ed.hm;
  const recs = new Uint8Array(w * h * 28);
  for (let z = 0; z < h; z++) for (let x = 0; x < w; x++)
    recs.set(tl.subarray(((z0 + z) * 64 + x0 + x) * 28, ((z0 + z) * 64 + x0 + x) * 28 + 28),
             (z * w + x) * 28);
  const ch = new Int16Array((w + 1) * (h + 1));
  for (let z = 0; z <= h; z++) for (let x = 0; x <= w; x++)
    ch[z * (w + 1) + x] = hm[(z0 + z) * 65 + x0 + x];
  T.clip = { w, h, recs, hm: ch, from: store.entry };
  store.say(`⛶ copied ${w}×${h} tiles (+heights) — switch to Paste and click the target (any level).`);
}

export function pasteRegion(tx, tz) {
  const c = T.clip;
  if (!c) { store.say('clipboard empty — use Copy first.'); return; }
  const x0 = Math.max(0, Math.min(64 - c.w, Math.round(tx - c.w / 2)));
  const z0 = Math.max(0, Math.min(64 - c.h, Math.round(tz - c.h / 2)));
  const tl = store.ed.tiles, hm = store.ed.hm;
  let delta = 0;
  if (T.rel) {
    let mn = 32767;
    for (const v of c.hm) if (v < mn) mn = v;
    const target = hm[Math.min(64, z0 + (c.h >> 1)) * 65 + Math.min(64, x0 + (c.w >> 1))];
    delta = Math.round((target - mn) / 4) * 4;
  }
  store.beginGesture();
  let animHit = false;
  for (let z = 0; z < c.h; z++) for (let x = 0; x < c.w; x++) {
    const di = (z0 + z) * 64 + x0 + x;
    tl.set(c.recs.subarray((z * c.w + x) * 28, (z * c.w + x) * 28 + 28), di * 28);
    if (store.lvl.animTiles.includes(di)) animHit = true;
    patchCanvas(di);
  }
  for (let z = 0; z <= c.h; z++) for (let x = 0; x <= c.w; x++) {
    const v = c.hm[z * (c.w + 1) + x] + delta;
    hm[(z0 + z) * 65 + x0 + x] = Math.max(-32768, Math.min(32767, v));
  }
  store.apply(s => { s.ed.tilesTouched = true; }, 'tiles');
  store.apply(s => { s.ed.hmTouched = true; }, 'hm');
  store.endGesture();
  store.say(`📋 pasted ${c.w}×${c.h} at (${x0},${z0})`
    + (T.rel ? ` · heights ${delta >= 0 ? '+' : ''}${delta}` : ' · absolute heights')
    + (animHit ? ' · ⚠ overwrote animated tiles (their animation entries go away on save)' : ''));
}
