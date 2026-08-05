// 2D top-down view: ground + layers + markers, with the view transform
// (mirror X/Y, rotate) applied via canvas matrix so picking stays exact.
import { store } from './store.js';
import { items, moveItem, owner, heightAt } from './items.js';
import { b64u8 } from './api.js';
import { api } from './api.js';
import { brush, beginStroke, moveStroke, endStroke, strokeActive } from './terrain.js';
import * as TL from './tiles.js';
import * as CAT from './catalog.js';
import * as AI from './aiwalk.js';

const W = 512;
const SEC_COLORS = ['#ff4757', '#ffa502', '#2ed573', '#1e90ff', '#e84393',
  '#00d2d3', '#f9ca24', '#a29bfe', '#fd79a8', '#55efc4', '#fab1a0',
  '#74b9ff', '#ffeaa7', '#81ecec', '#dfe6e9', '#b2bec3', '#636e72'];

let cv, ctx, ground = null, groundEntry = null, hover = null;
let drag = null;
let cursor = null;      // last mouse pos in world units (brush cursor)
let tileRect = null;    // fill-rect drag [[tx,tz],[tx,tz]]
let tilePaint = false;  // painting drag active
let aiPaint = false;    // AI-walk painting drag active

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

  const gc = TL.groundCanvas();
  if (v.layers.ground && gc) ctx.drawImage(gc, 0, 0, W, W);
  else if (v.layers.ground) { ctx.fillStyle = '#1c2b1c'; ctx.fillRect(0, 0, W, W); }

  if (v.layers.hm) drawHeightmap();
  if (v.layers.pth) drawPth();
  drawSections(m);
  drawMarkers(m);
  // AI-walk tool: half-tile brush cursor
  if (store.tool === 'ai' && cursor) {
    const s = AI.A.size, h = (s - 1) / 2;
    const x = Math.floor(cursor[0] / 4 - h) * 4, z = Math.floor(cursor[1] / 4 - h) * 4;
    ctx.strokeStyle = AI.A.mode === 'block' ? '#ff4646' : '#2ed573';
    ctx.lineWidth = 1.5 / Math.abs(m.a);
    ctx.strokeRect(x, z, s * 4, s * 4);
  }
  // brush cursor (heights tool)
  if (store.tool === 'height' && cursor) {
    ctx.strokeStyle = 'rgba(255,255,255,0.9)';
    ctx.lineWidth = 1.5 / Math.abs(m.a);
    ctx.setLineDash([4 / Math.abs(m.a), 3 / Math.abs(m.a)]);
    ctx.beginPath();
    ctx.arc(cursor[0], cursor[1], brush.radius * 8, 0, 7);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  // tiles tool: animated-tile badges, hovered tile, fill-rect preview
  if (store.tool === 'tiles') {
    ctx.fillStyle = 'rgba(80,200,255,0.35)';
    for (const i of store.lvl.animTiles)
      ctx.fillRect((i % 64) * 8 + 2.5, (i >> 6) * 8 + 2.5, 3, 3);
    const lw = 1.5 / Math.abs(m.a);
    if (tileRect) {
      const [a, b] = tileRect;
      const x0 = Math.min(a[0], b[0]) | 0, x1 = Math.max(a[0], b[0]) | 0;
      const z0 = Math.min(a[1], b[1]) | 0, z1 = Math.max(a[1], b[1]) | 0;
      ctx.strokeStyle = '#fff'; ctx.lineWidth = lw;
      ctx.strokeRect(x0 * 8, z0 * 8, (x1 - x0 + 1) * 8, (z1 - z0 + 1) * 8);
    } else if (cursor && TL.T.mode === 'paste' && TL.T.clip) {
      const c = TL.T.clip;
      const x0 = Math.max(0, Math.min(64 - c.w, Math.round(cursor[0] / 8 - c.w / 2)));
      const z0 = Math.max(0, Math.min(64 - c.h, Math.round(cursor[1] / 8 - c.h / 2)));
      ctx.strokeStyle = '#fff'; ctx.lineWidth = lw;
      ctx.setLineDash([4 / Math.abs(m.a), 3 / Math.abs(m.a)]);
      ctx.strokeRect(x0 * 8, z0 * 8, c.w * 8, c.h * 8);
      ctx.setLineDash([]);
    } else if (cursor) {
      const s = TL.T.size, h = (s - 1) / 2;
      const x = Math.floor(cursor[0] / 8 - h) * 8, z = Math.floor(cursor[1] / 8 - h) * 8;
      ctx.strokeStyle = TL.T.mode === 'pick' ? '#ffd60a'
        : TL.T.mode === 'clone' ? '#00d2d3' : '#fff';
      ctx.lineWidth = lw;
      ctx.strokeRect(x, z, s * 8, s * 8);
    }
    if (TL.T.cloneSrc) {
      ctx.strokeStyle = 'rgba(0,210,211,0.9)'; ctx.lineWidth = lw;
      ctx.setLineDash([3 / Math.abs(m.a), 2 / Math.abs(m.a)]);
      ctx.strokeRect(Math.floor(TL.T.cloneSrc[0]) * 8, Math.floor(TL.T.cloneSrc[1]) * 8, 8, 8);
      ctx.setLineDash([]);
    }
  }
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
  const g = (store.ed && store.ed.pth) || (store.lvl.pth && b64u8(store.lvl.pth));
  if (!g) return;
  const cell = W / 128;
  for (let r = 0; r < 128; r++) for (let c = 0; c < 128; c++) {
    const v = g[r * 128 + c];
    if (!v) continue;
    // red = blocked for the AI (bit 16); yellow = vanilla AI hints (2/3/5…)
    ctx.fillStyle = v & AI.BLOCKED ? 'rgba(255,70,70,.55)' : 'rgba(255,210,60,.5)';
    ctx.fillRect(c * cell, r * cell, cell, cell);
  }
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
    } else if (it.k === 'tp') {
      // teleport zone: its rect, plus an arrow to the paired destination
      const w = Math.max(it.w, 4), h = Math.max(it.h, 4);
      ctx.fillStyle = it.entrance ? 'rgba(197,108,240,0.18)' : 'rgba(127,143,166,0.16)';
      ctx.strokeStyle = it.col;
      ctx.lineWidth = 1.5 / scale;
      ctx.fillRect(it.x - w / 2, it.z - h / 2, w, h);
      ctx.strokeRect(it.x - w / 2, it.z - h / 2, w, h);
      if (it.entrance) {
        const dst = list.find(o => o.k === 'tp' && o.i === it.dest);
        if (dst && dst !== it) {
          ctx.strokeStyle = 'rgba(197,108,240,0.75)';
          ctx.setLineDash([5 / scale, 4 / scale]);
          ctx.beginPath(); ctx.moveTo(it.x, it.z); ctx.lineTo(dst.x, dst.z); ctx.stroke();
          ctx.setLineDash([]);
          // arrow head at the destination
          const a = Math.atan2(dst.z - it.z, dst.x - it.x), s2 = 7 / scale;
          ctx.beginPath();
          ctx.moveTo(dst.x, dst.z);
          ctx.lineTo(dst.x - Math.cos(a - 0.4) * s2 * 2, dst.z - Math.sin(a - 0.4) * s2 * 2);
          ctx.lineTo(dst.x - Math.cos(a + 0.4) * s2 * 2, dst.z - Math.sin(a + 0.4) * s2 * 2);
          ctx.closePath();
          ctx.fillStyle = 'rgba(197,108,240,0.85)'; ctx.fill();
        }
      }
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

export function loadGround(onReady) {
  if (groundEntry === store.entry && ground) return;
  groundEntry = store.entry;
  ground = new Image();
  ground.onload = () => {
    TL.setGroundImage(ground);      // shared canvas used by both views
    draw();
    if (onReady) onReady();
  };
  ground.src = api.groundUrl(store.entry);
}
export function reloadGround(onReady) { groundEntry = null; loadGround(onReady); }

export function init2d(canvas, statusPos, tipEl) {
  cv = canvas;
  ctx = cv.getContext('2d');

  cv.addEventListener('contextmenu', e => {
    e.preventDefault();
    if (CAT.pending) CAT.cancel();    // right-click stops placing
  });

  cv.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    const [wx, wz] = evtWorld(e);
    if (CAT.pending) {
      if (CAT.placeAt(Math.max(0, Math.min(512, wx)), Math.max(0, Math.min(512, wz)))) {
        e.preventDefault();
        return;
      }
    }
    if (store.tool === 'height') {
      beginStroke(wx / 8, wz / 8, e.altKey);
      e.preventDefault();
      return;
    }
    if (store.tool === 'ai') {
      aiPaint = true;
      store.beginGesture();
      AI.paintAt(wx, wz, e.altKey);
      draw();
      e.preventDefault();
      return;
    }
    if (store.tool === 'tiles') {
      const tx = wx / 8, tz = wz / 8;
      if (TL.T.mode === 'pick' || e.altKey && TL.T.mode !== 'clone') {
        TL.readTile(tx, tz);
        store.emit('stamp');
      } else if (TL.T.mode === 'fill' || TL.T.mode === 'copy') {
        tileRect = [[tx, tz], [tx, tz]];
      } else if (TL.T.mode === 'paste') {
        TL.pasteRegion(tx, tz);
      } else if (TL.T.mode === 'clone') {
        if (e.altKey || !TL.T.cloneSrc) {
          TL.T.cloneSrc = [tx, tz];
          store.say('clone source set — now paint to copy from there.');
          draw();
        } else {
          TL.T.cloneDelta = [Math.floor(TL.T.cloneSrc[0]) - Math.floor(tx),
                             Math.floor(TL.T.cloneSrc[1]) - Math.floor(tz)];
          tilePaint = true;
          store.beginGesture();
          TL.paintAt(tx, tz);
        }
      } else {
        tilePaint = true;
        store.beginGesture();
        TL.beginPaintStroke();
        TL.paintAt(tx, tz, e.altKey);
      }
      e.preventDefault();
      return;
    }
    const it = pick(wx, wz);
    if (it) {
      store.beginGesture();           // one undo step per marker drag
      store.apply(s => { s.sel = { k: it.k, i: it.i }; }, 'select');
      drag = { it, moved: false };
      e.preventDefault();
    } else {
      drag = { empty: true, wx, wz, moved: false };
    }
  });

  window.addEventListener('mousemove', e => {
    if (!store.lvl || store.view.mode !== '2d') return;
    const [wx, wz] = evtWorld(e);
    if (statusPos) statusPos.textContent =
      `tile (${(wx / 8).toFixed(2)}, ${(wz / 8).toFixed(2)})  world (${wx.toFixed(0)}, ${wz.toFixed(0)})  h=${heightAt(wx / 8, wz / 8).toFixed(1)}`;
    if (store.tool === 'height') {
      cursor = e.target === cv ? [wx, wz] : null;
      if (strokeActive()) { moveStroke(wx / 8, wz / 8, e.altKey); return; }
      draw();
      return;
    }
    if (store.tool === 'ai') {
      cursor = e.target === cv ? [wx, wz] : null;
      if (aiPaint) AI.paintAt(wx, wz, e.altKey);
      draw();
      return;
    }
    if (store.tool === 'tiles') {
      cursor = e.target === cv ? [wx, wz] : null;
      if (tileRect) { tileRect[1] = [wx / 8, wz / 8]; draw(); return; }
      if (tilePaint) { TL.paintAt(wx / 8, wz / 8, e.altKey); return; }
      draw();
      return;
    }
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
    if (strokeActive()) { endStroke(); return; }   // ends its own gesture
    store.endGesture();
    if (tileRect) {
      if (TL.T.mode === 'copy')
        TL.copyRegion(tileRect[0][0], tileRect[0][1], tileRect[1][0], tileRect[1][1]);
      else
        TL.fillRect(tileRect[0][0], tileRect[0][1], tileRect[1][0], tileRect[1][1]);
      tileRect = null;
      draw();
      return;
    }
    if (tilePaint) { tilePaint = false; TL.T.cloneDelta = null; return; }
    if (aiPaint) { aiPaint = false; return; }
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
