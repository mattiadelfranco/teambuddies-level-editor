// 2D top-down view: ground + layers + markers, with the view transform
// (mirror X/Y, rotate) applied via canvas matrix so picking stays exact.
import { store } from './store.js';
import { items, moveItem, owner, heightAt } from './items.js';
import { b64u8 } from './api.js';
import { api } from './api.js';

const W = 512;
const SEC_COLORS = ['#ff4757', '#ffa502', '#2ed573', '#1e90ff', '#e84393',
  '#00d2d3', '#f9ca24', '#a29bfe', '#fd79a8', '#55efc4', '#fab1a0',
  '#74b9ff', '#ffeaa7', '#81ecec', '#dfe6e9', '#b2bec3', '#636e72'];

let cv, ctx, ground = null, groundEntry = null, hover = null;
let drag = null;

function hash(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }
export function modelColor(n) {
  if (/BSE|BASE/i.test(n) && !/flag/i.test(n)) return '#ff3b30';
  if (/flag/i.test(n)) return '#ffd60a';
  return `hsl(${hash(n) % 360} 70% 60%)`;
}

// world(512) -> canvas px matrix honoring the view options
function matrix() {
  const v = store.view, s = cv.width / W, c = W / 2;
  const r = v.rot * Math.PI / 180, co = Math.cos(r), si = Math.sin(r);
  const mx = v.mirrorX ? -1 : 1, my = v.mirrorY ? -1 : 1;
  // M = S(s) * T(c) * R * S(mx,my) * T(-c)
  const a = co * mx, b = si * mx, cc = -si * my, d = co * my;
  const e = c - a * c - cc * c, f = c - b * c - d * c;
  return { a: a * s, b: b * s, c: cc * s, d: d * s, e: e * s, f: f * s };
}
function invApply(m, px, py) {
  const det = m.a * m.d - m.b * m.c;
  const x = px - m.e, y = py - m.f;
  return [(m.d * x - m.c * y) / det, (m.a * y - m.b * x) / det];
}
function apply(m, x, y) {
  return [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f];
}

function evtWorld(e) {
  const r = cv.getBoundingClientRect();
  const px = (e.clientX - r.left) / r.width * cv.width;
  const py = (e.clientY - r.top) / r.height * cv.height;
  return invApply(matrix(), px, py);
}

export function draw() {
  if (!store.lvl || !ctx) return;
  const m = matrix(), v = store.view;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.setTransform(m.a, m.b, m.c, m.d, m.e, m.f);

  if (v.layers.ground && ground && ground.complete)
    ctx.drawImage(ground, 0, 0, W, W);
  else if (v.layers.ground) { ctx.fillStyle = '#1c2b1c'; ctx.fillRect(0, 0, W, W); }

  if (v.layers.hm) drawHeightmap();
  if (v.layers.pth) drawPth();
  drawSections(m);
  drawMarkers(m);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function heightColor(t) {
  const stops = [[30, 60, 38], [64, 120, 66], [150, 140, 80], [190, 180, 160], [235, 235, 235]];
  const x = t * (stops.length - 1), i = Math.min(stops.length - 2, x | 0), f = x - i;
  return stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * f));
}

function drawHeightmap() {
  const hm = store.hm;
  let mn = 32767, mx = -32768;
  for (const q of hm) { if (q < mn) mn = q; if (q > mx) mx = q; }
  const cell = W / 64;
  for (let r = 0; r < 64; r++) for (let c = 0; c < 64; c++) {
    const q = (hm[r * 65 + c] + hm[r * 65 + c + 1] + hm[(r + 1) * 65 + c] + hm[(r + 1) * 65 + c + 1]) / 4;
    let col = heightColor((q - mn) / Math.max(1, mx - mn));
    const shade = 1 + (hm[r * 65 + c] - hm[r * 65 + Math.max(0, c - 1)]) * 0.03;
    col = col.map(x => Math.max(0, Math.min(255, Math.round(x * shade))));
    ctx.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${store.view.layers.ground ? 0.65 : 1})`;
    ctx.fillRect(c * cell, r * cell, cell + 0.5, cell + 0.5);
  }
}

function drawPth() {
  if (!store.lvl.pth) return;
  const g = b64u8(store.lvl.pth), cell = W / 128;
  ctx.fillStyle = 'rgba(80,160,255,.55)';
  for (let r = 0; r < 128; r++) for (let c = 0; c < 128; c++)
    if (g[r * 128 + c]) ctx.fillRect(c * cell, r * cell, cell, cell);
}

function drawSections(m) {
  const l = store.lvl;
  const tos16 = x => (x >= 32768 ? x - 65536 : x);
  const f = x => (32 + tos16(x) / 512) * 8;
  for (const s of l.pld) {
    if (!store.view.sections.has(s.i) || !s.pts.length || s.i === 0) continue;
    ctx.fillStyle = SEC_COLORS[s.i];
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1 / m.a;
    for (const p of s.pts) {
      let X, Z;
      if ([1, 2, 4, 14, 15].includes(s.i)) { X = f(p[0]); Z = f(p[2] !== undefined ? p[2] : p[1]); }
      else { X = p[0] / 256 * 8; Z = p[1] / 256 * 8; }
      ctx.fillRect(X - 2.5, Z - 2.5, 5, 5);
      ctx.strokeRect(X - 2.5, Z - 2.5, 5, 5);
    }
  }
}

function drawMarkers(m) {
  const sel = store.sel;
  const list = items();
  const scale = Math.abs(m.a);          // world->px
  // footprints first (pads 4x4 tiles, zones 8x8)
  for (const it of list) {
    if (it.k === 's0') {
      ctx.fillStyle = 'rgba(255,71,87,0.22)'; ctx.strokeStyle = 'rgba(255,71,87,0.9)';
      ctx.lineWidth = 1.5 / scale;
      ctx.fillRect(it.x - 16, it.z - 16, 32, 32); ctx.strokeRect(it.x - 16, it.z - 16, 32, 32);
    } else if (it.k === 'cz') {
      ctx.fillStyle = 'rgba(255,159,26,0.12)'; ctx.strokeStyle = 'rgba(255,159,26,0.9)';
      ctx.lineWidth = 1.5 / scale;
      ctx.fillRect(it.x - 32, it.z - 32, 64, 64); ctx.strokeRect(it.x - 32, it.z - 32, 64, 64);
    }
  }
  // owner line for selected turret
  if (sel && sel.k === 'tr' && store.ed.extra) {
    const it = list.find(o => o.k === 'tr' && o.i === sel.i);
    const rec = store.ed.extra[sel.i];
    if (it && rec && !(rec[8] > 0)) {
      const ow = owner(it);
      if (ow) {
        ctx.strokeStyle = ['#e74c3c', '#3498db', '#2ecc71', '#f1c40f'][ow.team] || '#fff';
        ctx.setLineDash([6 / scale, 4 / scale]); ctx.lineWidth = 2 / scale;
        ctx.beginPath(); ctx.moveTo(it.x, it.z); ctx.lineTo(ow.base.x * 8, ow.base.z * 8); ctx.stroke();
        ctx.setLineDash([]);
      }
    }
  }
  for (const it of list) {
    if (it.k === 'in' && !store.view.layers.obj) continue;
    const isSel = sel && sel.k === it.k && sel.i === it.i;
    ctx.strokeStyle = isSel ? '#fff' : '#000';
    ctx.lineWidth = (isSel ? 2.5 : 1) / scale;
    ctx.fillStyle = it.k === 'in' ? modelColor(it.lbl) : it.col;
    const r = (it.small ? 4.5 : 7) / scale * (cv.width / 1024) * 2;
    ctx.beginPath(); ctx.arc(it.x, it.z, Math.max(r, it.small ? 2.2 : 3.5), 0, 7);
    ctx.fill(); ctx.stroke();
  }
  // pad numbers (unmirrored text)
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.font = 'bold 15px sans-serif';
  for (const it of list) {
    if (it.k !== 's0') continue;
    const [px, py] = apply(m, it.x, it.z);
    ctx.fillStyle = '#fff'; ctx.strokeStyle = '#000'; ctx.lineWidth = 3;
    ctx.strokeText(String(it.i + 1), px + 10, py + 5);
    ctx.fillText(String(it.i + 1), px + 10, py + 5);
  }
  ctx.setTransform(m.a, m.b, m.c, m.d, m.e, m.f);
}

function pick(wx, wz) {
  let best = null, bd = 8;
  for (const it of items()) {
    if (it.k === 'in' && !store.view.layers.obj) continue;
    const d = Math.hypot(it.x - wx, it.z - wz);
    if (d < bd) { bd = d; best = it; }
  }
  return best;
}

export function loadGround() {
  if (groundEntry === store.entry && ground) return;
  groundEntry = store.entry;
  ground = new Image();
  ground.onload = draw;
  ground.src = api.groundUrl(store.entry);
}
export function reloadGround() { groundEntry = null; loadGround(); }

export function init2d(canvas, statusPos, tipEl) {
  cv = canvas;
  ctx = cv.getContext('2d');

  cv.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    const [wx, wz] = evtWorld(e);
    const it = pick(wx, wz);
    if (it) {
      store.apply(s => { s.sel = { k: it.k, i: it.i }; }, 'select');
      drag = { it, moved: false };
      e.preventDefault();
    } else {
      drag = { empty: true, wx, wz, moved: false };
    }
  });

  window.addEventListener('mousemove', e => {
    if (!store.lvl) return;
    const [wx, wz] = evtWorld(e);
    if (statusPos) statusPos.textContent =
      `tile (${(wx / 8).toFixed(2)}, ${(wz / 8).toFixed(2)})  world (${wx.toFixed(0)}, ${wz.toFixed(0)})  h=${heightAt(wx / 8, wz / 8).toFixed(1)}`;
    if (drag && !drag.empty) {
      drag.moved = true;
      store.apply(() => moveItem(drag.it, Math.max(0, Math.min(W, wx)), Math.max(0, Math.min(W, wz))));
      return;
    }
    // hover tooltip
    const it = e.target === cv ? pick(wx, wz) : null;
    if (it !== hover) {
      hover = it;
      if (tipEl) {
        if (it) {
          const r = cv.getBoundingClientRect();
          tipEl.style.display = 'block';
          tipEl.style.left = (e.clientX - r.left + 14) + 'px';
          tipEl.style.top = (e.clientY - r.top - 8) + 'px';
          tipEl.textContent = it.lbl;
        } else tipEl.style.display = 'none';
      }
    } else if (tipEl && it) {
      const r = cv.getBoundingClientRect();
      tipEl.style.left = (e.clientX - r.left + 14) + 'px';
      tipEl.style.top = (e.clientY - r.top - 8) + 'px';
    }
  });

  window.addEventListener('mouseup', () => {
    if (drag && drag.empty && !drag.moved) {
      // click on empty ground: copy exact coordinates
      const l = store.lvl, wx = drag.wx, wz = drag.wz;
      const s = `TB-POS lvl=${l.entry} ${l.name} tile=(${(wx / 8).toFixed(2)},${(wz / 8).toFixed(2)})`
        + ` world=(${wx.toFixed(0)},${wz.toFixed(0)})`
        + ` halfTileCentered=(${((wx / 8 - 32) * 2).toFixed(1)},${((wz / 8 - 32) * 2).toFixed(1)})`;
      if (navigator.clipboard) navigator.clipboard.writeText(s).catch(() => {});
      store.say('📋 ' + s);
      if (store.sel) store.apply(st => { st.sel = null; }, 'select');
    }
    drag = null;
  });
}
