// Unified marker items + move logic, shared by the 2D and 3D views.
//
// Canvas world space = 512 units (8 per tile), same frame as the ground PNG
// (row = z, col = x). From the engine (FUN_800a7fbc + FUN_800a79f4):
//   instances AND extra list: canvas (x, 512 - z)   [z mirrored, x not]
//   s0 / s6 raw values:       world units -> canvas (raw_x/... via tile*8)
import { store, tos16, snapOdd } from './store.js';

const t2w = raw => (32 + tos16(raw) / 512) * 8;          // s0/s6 raw -> canvas
const w2raw = w => Math.round((w / 8 - 32) * 2 * 256) & 0xffff;

export function items() {
  const st = store.ed, l = store.lvl, cat = store.cat, out = [];
  if (!st) return out;
  st.s0.forEach((p, i) => out.push({
    k: 's0', i, x: t2w(p[0]), z: t2w(p[1]),
    lbl: 'pad/spawn ' + (i + 1), col: '#ff4757',
  }));
  st.s3.forEach((p, i) => out.push({
    k: 'cz', i, x: p[0] * 8, z: p[1] * 8,
    lbl: 'crate zone ' + (i + 1), col: '#ff9f1a',
  }));
  // teleport zones (s10): rect stored in HALF-tiles -> canvas world = v*4
  st.s10.forEach((r, i) => {
    const entrance = !!(r[1] & 0x100);
    out.push({
      k: 'tp', i, x: (r[2] + r[4]) * 2, z: (r[3] + r[5]) * 2,
      w: (r[4] - r[2]) * 4, h: (r[5] - r[3]) * 4, dest: r[0], entrance,
      lbl: `teleport ${i} ${entrance ? '→ ' + r[0] : '(exit)'}`,
      col: entrance ? '#c56cf0' : '#7f8fa6',
    });
  });
  st.s6.records.forEach((r, i) => out.push({
    k: 's6', i, x: t2w(r[3]), z: t2w(r[4]),
    lbl: (cat.s6Names[r[0]] || 'type ' + r[0]) + ' (team ' + (r[1] + 1) + ')',
    col: '#f9ca24',
  }));
  if (st.extra) st.extra.forEach((r, i) => out.push({
    k: 'tr', i, x: r[2], z: 512 - r[4], rot: r[7],
    lbl: cat.statics[r[5]] || 'static ' + r[5], col: '#00d2d3',
  }));
  st.inst.forEach((r, i) => out.push({
    k: 'in', i, x: r[1], z: 512 - r[3], alt: r[2], rot: r[5], m: r[0],
    lbl: l.models[r[0]] || '#' + r[0], col: '#a29bfe', small: true,
  }));
  return out;
}

// move an item to canvas world (wx, wz); mutates store.ed (call via store.apply)
export function moveItem(it, wx, wz) {
  const st = store.ed;
  if (it.k === 's0') {
    st.s0[it.i][0] = snapOdd(w2raw(wx));
    st.s0[it.i][1] = snapOdd(w2raw(wz));
  } else if (it.k === 'cz') {
    st.s3[it.i][0] = Math.max(4, Math.min(59, Math.round(wx / 8)));
    st.s3[it.i][1] = Math.max(4, Math.min(59, Math.round(wz / 8)));
  } else if (it.k === 's6') {
    st.s6.records[it.i][3] = w2raw(wx);
    st.s6.records[it.i][4] = w2raw(wz);
  } else if (it.k === 'tr') {
    st.extra[it.i][2] = Math.round(wx) & 0xffff;
    st.extra[it.i][4] = Math.round(512 - wz) & 0xffff;
  } else if (it.k === 'in') {
    st.inst[it.i][1] = Math.round(wx);
    st.inst[it.i][3] = Math.round(512 - wz);
  } else if (it.k === 'tp') {
    const r = st.s10[it.i];
    const w = r[4] - r[2], h = r[5] - r[3];
    const cx = Math.round(wx / 4), cz = Math.round(wz / 4);   // half-tiles
    r[2] = Math.max(0, Math.min(128 - w, cx - (w >> 1)));
    r[3] = Math.max(0, Math.min(128 - h, cz - (h >> 1)));
    r[4] = r[2] + w; r[5] = r[3] + h;
  }
}

// pad->base claiming preview (engine: each pad claims, in order and
// exclusively, the nearest BSE_* base; extra objects take the team of the
// nearest claimed base). Tile frame: base V = (x/8, 64 - z/8) = marker/8.
export function owner(it) {
  const st = store.ed, l = store.lvl;
  const bases = [];
  st.inst.forEach((r, i) => {
    if ((l.models[r[0]] || '').toUpperCase().startsWith('BSE'))
      bases.push({ i, x: r[1] / 8, z: (512 - r[3]) / 8 });
  });
  if (!bases.length) return null;
  const taken = new Set(), claimed = [];
  st.s0.forEach((p, ti) => {
    const px = t2w(p[0]) / 8, pz = t2w(p[1]) / 8;
    let bb = null, bd = 1 / 0;
    for (const b of bases) {
      if (taken.has(b.i)) continue;
      const d = (b.x - px) ** 2 + (b.z - pz) ** 2;
      if (d < bd) { bd = d; bb = b; }
    }
    if (bb) { taken.add(bb.i); claimed.push({ team: ti, base: bb }); }
  });
  let best = null, bd = 1 / 0;
  for (const c of claimed) {
    const d = (c.base.x - it.x / 8) ** 2 + (c.base.z - it.z / 8) ** 2;
    if (d < bd) { bd = d; best = c; }
  }
  return best;   // {team, base:{i, x(tile), z(tile)}}
}


// Animated tiles (water, pad arrows) under a pad's 4x4 footprint. Dropping a
// pad on water is a trap: the save repaints those tiles and drops their water
// animation, so the pool stops being drawn while the terrain keeps behaving
// like liquid — invisible zones that kill you.
export function padWaterWarning(wx, wz) {
  const l = store.lvl;
  if (!l || !l.animTiles || !l.animWater) return '';
  const cx = Math.floor(wx / 8 - 0.5) - 1, cz = Math.floor(wz / 8 - 0.5) - 1;
  const hits = [];
  for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) {
    const t = (cz + j) * 64 + (cx + i);
    if (l.animWater.includes(t)) hits.push([cx + i, cz + j]);
  }
  return hits.length
    ? `⚠ this pad covers ${hits.length} WATER tile(s) (e.g. ${hits[0][0]},${hits[0][1]}): `
      + 'saving repaints them and removes their water animation — the pool goes '
      + 'invisible but the ground still behaves like liquid and kills you. Move the pad onto dry land.'
    : '';
}

export function heightAt(tx, tz) {
  const hm = store.hm;
  if (!hm) return 0;
  const x = Math.max(0, Math.min(63.999, tx)), z = Math.max(0, Math.min(63.999, tz));
  const i = x | 0, j = z | 0, fx = x - i, fz = z - j;
  return (hm[j * 65 + i] * (1 - fx) * (1 - fz) + hm[j * 65 + i + 1] * fx * (1 - fz)
        + hm[(j + 1) * 65 + i] * (1 - fx) * fz + hm[(j + 1) * 65 + i + 1] * fx * fz) / 8;
}

// ---- mutations used by the Catalog (call via store.apply) ----
// wx/wz are optional canvas-world coordinates (512 units); default = center.

export function addUnit(type, team, wx, wz) {
  const st = store.ed;
  st.s6.records.push([type, team, 0,
    wx !== undefined ? w2raw(wx) : 0, wz !== undefined ? w2raw(wz) : 0]);
  store.sel = { k: 's6', i: st.s6.records.length - 1 };
}

export function addObject(modelIdx, wx, wz) {
  const st = store.ed;
  const tpl = st.inst.find(r => r[0] === modelIdx);
  const r = tpl ? tpl.slice() : [modelIdx, 0, 0, 0, 0, 0, 0];
  r[1] = wx !== undefined ? Math.round(wx) : 256;
  r[3] = wz !== undefined ? Math.round(512 - wz) : 256;
  // snap the altitude to the terrain (vanilla objects sit exactly on it)
  r[2] = Math.round(heightAt(r[1] / 8, (512 - r[3]) / 8) * 8);
  st.inst.push(r);
  store.sel = { k: 'in', i: st.inst.length - 1 };
  return !!tpl;
}

export function addExtra(type, team = 0, wx, wz) {
  const st = store.ed;
  st.extra.push([0, 0,
    wx !== undefined ? Math.round(wx) & 0xffff : 256, 16,
    wz !== undefined ? Math.round(512 - wz) & 0xffff : 256,
    type, 0, 512, team, 0]);
  store.sel = { k: 'tr', i: st.extra.length - 1 };
}

export function addTeam() {
  const st = store.ed, l = store.lvl, parts = [];
  st.s0.push([snapOdd(256), snapOdd(256), 0x200, 0x200]);   // near center
  const p = st.s0[st.s0.length - 1];
  const px = t2w(p[0]) / 8, pz = t2w(p[1]) / 8;   // pad tile
  const bi = st.inst.findIndex(r => (l.models[r[0]] || '').toUpperCase().startsWith('BSE'));
  if (bi >= 0) {
    const b = st.inst[bi].slice();
    b[1] = Math.round(8 * (px + 4)); b[3] = Math.round(512 - 8 * pz);
    st.inst.push(b); parts.push('base');
  }
  const fi = st.inst.findIndex(r => (l.models[r[0]] || '') === 'base_flag');
  if (fi >= 0) {
    const f = st.inst[fi].slice();
    f[1] = Math.round(8 * (px + 2)); f[3] = Math.round(512 - 8 * (pz + 2));
    st.inst.push(f); parts.push('flag');
  }
  store.sel = { k: 's0', i: st.s0.length - 1 };
  return parts;
}

export function addZone() {
  const st = store.ed;
  if (!st.s3.length) return false;
  st.s3.push([32, 32]);
  st.zcfg.push(st.zcfg[0] ? st.zcfg[0].slice() : null);
  st.zcfgTouched = true;
  store.sel = { k: 'cz', i: st.s3.length - 1 };
  return true;
}

export function addDefenses(type) {
  const st = store.ed, l = store.lvl;
  const all = items();
  const bases = all.filter(o => o.k === 'in'
    && (l.models[st.inst[o.i][0]] || '').toUpperCase().startsWith('BSE'));
  if (!bases.length) return 0;
  const pads = all.filter(o => o.k === 's0');
  const done = new Set();
  let n = 0;
  for (const s of pads) {
    let bb = null, bd = 1 / 0;
    for (const b of bases) {
      const d = (b.x - s.x) ** 2 + (b.z - s.z) ** 2;
      if (d < bd) { bd = d; bb = b; }
    }
    if (!bb || done.has(bb.i)) continue;
    done.add(bb.i);
    for (const [dx, dz] of [[28, -28], [-28, 28]]) {
      st.extra.push([0, 0, Math.round(bb.x + dx) & 0xffff, 16,
                     Math.round(512 - (bb.z + dz)) & 0xffff, type, 0, 512, s.i + 1, 0]);
      n++;
    }
  }
  return n;
}

// new teleport PAIR: entrance + paired exit, both 1x1 half-tile, linked
export function addTeleportPair(wx, wz) {
  const st = store.ed, n = st.s10.length;
  const hx = Math.max(0, Math.min(126, Math.round(wx / 4)));
  const hz = Math.max(0, Math.min(126, Math.round(wz / 4)));
  st.s10.push([n + 1, 0x103, hx, hz, hx + 1, hz + 1]);              // entrance
  st.s10.push([n, 0x003, Math.min(126, hx + 8), hz, Math.min(127, hx + 9), hz + 1]); // exit
  store.sel = { k: 'tp', i: n };
  return n;
}

export function duplicateSel() {
  const st = store.ed, sel = store.sel;
  if (!sel) return;
  if (sel.k === 's6') {
    const r = st.s6.records[sel.i].slice(); r[3] = (r[3] + 1024) & 0xffff;
    st.s6.records.push(r); store.sel = { k: 's6', i: st.s6.records.length - 1 };
  } else if (sel.k === 'tr') {
    const r = st.extra[sel.i].slice(); r[2] = (r[2] + 8) & 0xffff;
    st.extra.push(r); store.sel = { k: 'tr', i: st.extra.length - 1 };
  } else if (sel.k === 'in') {
    const r = st.inst[sel.i].slice(); r[1] -= 8;
    st.inst.push(r); store.sel = { k: 'in', i: st.inst.length - 1 };
  } else if (sel.k === 'cz') {
    const r = st.s3[sel.i].slice();
    if (r.length < 3) r[2] = sel.i;   // il server clona la FORMA di questa zona
    r[0] = Math.min(59, r[0] + 4);
    st.s3.push(r);
    st.zcfg.push(st.zcfg[sel.i] ? st.zcfg[sel.i].slice() : null);
    st.zcfgTouched = true;
    store.sel = { k: 'cz', i: st.s3.length - 1 };
  } else if (sel.k === 's0') {
    const r = st.s0[sel.i].slice(); r[0] = snapOdd((r[0] + 1024) & 0xffff);
    st.s0.push(r); store.sel = { k: 's0', i: st.s0.length - 1 };
  }
}

export function deleteSel() {
  const st = store.ed, sel = store.sel;
  if (!sel) return null;
  if (sel.k === 's6') st.s6.records.splice(sel.i, 1);
  else if (sel.k === 'tr') st.extra.splice(sel.i, 1);
  else if (sel.k === 'in') st.inst.splice(sel.i, 1);
  else if (sel.k === 'cz') {
    if (st.s3.length <= 1) return 'A level needs at least one crate zone.';
    st.s3.splice(sel.i, 1); st.zcfg.splice(sel.i, 1); st.zcfgTouched = true;
  } else if (sel.k === 's0') {
    if (st.s0.length <= 1) return 'A level needs at least one pad/spawn.';
    st.s0.splice(sel.i, 1);
  } else if (sel.k === 'tp') {
    // remove the zone AND anything pointing at it, then renumber dest
    const drop = new Set([sel.i]);
    st.s10.forEach((r, k) => { if (r[0] === sel.i) drop.add(k); });
    const keep = st.s10.filter((_, k) => !drop.has(k));
    const remap = new Map();
    let n = 0;
    st.s10.forEach((_, k) => { if (!drop.has(k)) remap.set(k, n++); });
    for (const r of keep) r[0] = remap.has(r[0]) ? remap.get(r[0]) : 0;
    st.s10 = keep;
  }
  store.sel = null;
  return null;
}
