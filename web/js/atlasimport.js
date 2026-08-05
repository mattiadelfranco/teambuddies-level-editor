// Cross-level atlas import: browse any level's atlas cells and copy one
// (64x64 4bpp pixels + its CLUT) into the current level's TIM. The engine
// only sees the level's own atlas, so art from other levels must be baked
// into this level's TIM first — that is what /api/import_cell does (CLUT is
// reused if byte-identical, else appended; vanilla counts range 60..160).
// Imports are immediate server-side writes (mods/<entry>/*.TIM): they are
// NOT part of undo/redo, but harmless until a tile actually uses the cell.
import { store } from './store.js';
import * as TL from './tiles.js';

const $ = id => document.getElementById(id);

const IM = {
  entry: null,        // source level currently shown, null = none
  atlas: null,        // decoded source atlas {w,h,idx,cluts}
  info: null,         // /api/tileinfo of the source (cellClut for "auto")
  cell: -1,           // selected source cell
  pick: null,         // {anim:Set} while choosing a destination cell
};
export const pickActive = () => !!IM.pick;

const srcCols = () => IM.atlas ? IM.atlas.w >> 6 : 16;
const srcRows = () => IM.atlas ? IM.atlas.h >> 6 : 4;
function srcClut() {
  const sel = +($('im-clut').value || -1);
  if (sel >= 0) return sel;
  const c = IM.info && IM.info.cellClut[IM.cell];
  return c === undefined ? 0 : c;
}

// plain orient-0 preview of a cell (v-flip, same look as the main palette)
function cellImage(A, cell, clutIdx) {
  const cu = (cell % (A.w >> 6)) * 64, cv = (cell / (A.w >> 6) | 0) * 64;
  const cl = A.cluts[Math.min(clutIdx, A.cluts.length - 1)];
  const im = new ImageData(64, 64);
  for (let y = 0; y < 64; y++) {
    const sv = 63 - y;
    for (let x = 0; x < 64; x++) {
      const c = cl[A.idx[(cv + sv) * A.w + cu + x]];
      const k = (y * 64 + x) * 4;
      im.data[k] = c[0]; im.data[k + 1] = c[1]; im.data[k + 2] = c[2]; im.data[k + 3] = c[3];
    }
  }
  return im;
}

async function loadSrc(entry) {
  IM.entry = null; IM.atlas = null; IM.info = null; IM.cell = -1;
  $('im-go').disabled = true;
  if (!entry) { drawSrc(); return; }
  const [a, info] = await Promise.all([
    fetch('/api/atlas/' + entry).then(r => r.json()),
    fetch('/api/tileinfo/' + entry).then(r => r.json()),
  ]);
  IM.atlas = TL.decodeAtlas(a);
  IM.info = info;
  IM.entry = entry;
  const sel = $('im-clut'), n = IM.atlas.cluts.length;
  sel.innerHTML = '<option value="-1">auto (per cell)</option>'
    + Array.from({ length: n }, (_, i) => `<option value="${i}">${i}</option>`).join('');
  drawSrc();
}

function drawSrc() {
  const cv = $('im-atlas'), show = !!IM.atlas;
  cv.style.display = show ? '' : 'none';
  $('im-ctl').style.display = show ? '' : 'none';
  if (!show) return;
  const cols = srcCols(), rows = srcRows();
  cv.width = cols * 32; cv.height = rows * 32;
  const x = cv.getContext('2d');
  const clutSel = +($('im-clut').value || -1);
  const tmp = document.createElement('canvas');
  tmp.width = tmp.height = 64;
  for (let cell = 0; cell < cols * rows; cell++) {
    const clut = clutSel >= 0 ? clutSel
      : (IM.info.cellClut[cell] === undefined ? 0 : IM.info.cellClut[cell]);
    tmp.getContext('2d').putImageData(cellImage(IM.atlas, cell, clut), 0, 0);
    x.imageSmoothingEnabled = false;
    x.drawImage(tmp, (cell % cols) * 32, (cell / cols | 0) * 32, 32, 32);
  }
  if (IM.cell >= 0) {
    x.strokeStyle = '#fff'; x.lineWidth = 2;
    x.strokeRect((IM.cell % cols) * 32 + 1, (IM.cell / cols | 0) * 32 + 1, 30, 30);
    const tmp2 = $('im-prev');
    tmp2.getContext('2d').putImageData(cellImage(IM.atlas, IM.cell, srcClut()), 0, 0);
  }
}

// ---- destination pick over the main palette ----
function liveCellCounts() {
  // counts from the LIVE tile array (includes unsaved paints)
  const cols = TL.cellsX(), tl = store.ed.tiles;
  const dv = new DataView(tl.buffer, tl.byteOffset);
  const m = new Map();
  for (let i = 0; i < 4096; i++) {
    const cell = ((tl[i * 28 + 2] >> 6) * cols) + (dv.getUint16(i * 28, true) >> 6);
    m.set(cell, (m.get(cell) || 0) + 1);
  }
  return m;
}

async function startPick() {
  if (IM.pick) return cancelPick();
  const info = await (await fetch('/api/tileinfo/' + store.entry)).json();
  IM.pick = { anim: new Set(info.cellAnim) };
  $('im-go').textContent = '✕ cancel';
  store.say('IMPORT: click the destination cell in YOUR atlas above — green = free, '
    + '⚡ = animation frame, numbers = tiles using it. Esc cancels.');
  store.emit('palette');
}

export function cancelPick() {
  if (!IM.pick) return;
  IM.pick = null;
  $('im-go').textContent = 'Import…';
  store.emit('palette');
}

// overlay painted by drawPalette (ui.js) while picking a destination
export function drawOverlay(x) {
  if (!IM.pick) return;
  const cols = TL.cellsX(), rows = TL.T.atlas.h >> 6;
  const counts = liveCellCounts();
  x.textAlign = 'center'; x.textBaseline = 'middle'; x.font = 'bold 11px sans-serif';
  for (let cell = 0; cell < cols * rows; cell++) {
    const px = (cell % cols) * 32, py = (cell / cols | 0) * 32;
    const n = counts.get(cell) || 0, anim = IM.pick.anim.has(cell);
    if (!n && !anim) {
      x.strokeStyle = '#2ed573'; x.lineWidth = 2;
      x.strokeRect(px + 1, py + 1, 30, 30);
    } else {
      x.fillStyle = 'rgba(0,0,0,.55)';
      x.fillRect(px, py, 32, 32);
      x.fillStyle = anim ? '#ff6b6b' : '#dfe6e9';
      x.fillText(anim ? '⚡' : String(n), px + 16, py + 16);
    }
  }
}

export async function pickDst(cell) {
  if (!IM.pick || IM.cell < 0) return;
  const n = liveCellCounts().get(cell) || 0;
  const anim = IM.pick.anim.has(cell);
  const msg = anim
    ? `Cell ${cell} is a frame of an ANIMATED texture (water, pad arrows…): `
      + 'overwriting it corrupts that animation in game. Replace anyway?'
    : n ? `Cell ${cell} is used by ${n} painted tiles: importing here replaces `
      + 'their texture everywhere on the map. Replace anyway?' : null;
  if (msg && !confirm(msg)) return;
  const body = { dst: store.entry, src: IM.entry, srcCell: IM.cell,
                 srcClut: srcClut(), dstCell: cell };
  let r;
  try {
    r = await (await fetch('/api/import_cell',
      { method: 'POST', body: JSON.stringify(body) })).json();
  } catch (e) { r = { err: e.message }; }
  if (r.err) { store.say('IMPORT ERROR: ' + r.err); return; }
  IM.pick = null;
  $('im-go').textContent = 'Import…';
  TL.T.entry = null;                       // force a fresh /api/atlas fetch
  await TL.loadAtlas(store.entry);
  TL.T.stamp.cell = cell;
  TL.T.stamp.autoClut = true;              // auto resolves to the imported CLUT
  if (n || anim) store.emit('tiles-restored');   // cell was visible: repaint ground
  store.emit('atlas');
  store.say(`✓ cell ${IM.cell} of ${IM.entry} imported into cell ${cell}`
    + ` — CLUT ${r.clut} ${r.appended ? 'appended' : 'reused'} (${r.nCluts} total`
    + `${r.nCluts > 160 ? ', above the vanilla max of 160: TEST IN GAME' : ''})`
    + '. Import is written to the mod TIM now (not undoable) — paint away.');
}

export function initImport() {
  $('im-level').innerHTML = '<option value="">— choose a level —</option>'
    + store.cat.levels.map(l => `<option value="${l.entry}">${l.entry} — ${l.name}</option>`).join('');
  $('im-level').onchange = e => loadSrc(e.target.value)
    .catch(err => store.say('IMPORT ERROR: ' + err.message));
  $('im-clut').onchange = drawSrc;
  $('im-atlas').onclick = e => {
    const r = $('im-atlas').getBoundingClientRect();
    IM.cell = Math.floor((e.clientY - r.top) / r.height * srcRows()) * srcCols()
            + Math.floor((e.clientX - r.left) / r.width * srcCols());
    $('im-go').disabled = false;
    drawSrc();
  };
  $('im-go').onclick = () => startPick()
    .catch(err => store.say('IMPORT ERROR: ' + err.message));
  store.onChange(what => { if (what === 'level') cancelPick(); });
}
