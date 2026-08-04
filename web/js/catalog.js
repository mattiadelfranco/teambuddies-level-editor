// Object catalog: searchable grid with graphical previews. Clicking an item
// arms "place mode": the next click in the 2D or 3D viewport places it there
// (Escape cancels). Thumbnails come from thumbs.js (WebGL renders of the real
// models); units and model-less statics get letter tiles.
import { store } from './store.js';
import * as It from './items.js';
import * as TH from './thumbs.js';
import { api } from './api.js';

const $ = id => document.getElementById(id);

export let pending = null;      // {kind:'s6'|'in'|'tr'|'imp', id, label, ...}
export let onImportModel = null;   // set by main.js -> view3d.importModel
export function setImportHook(fn) { onImportModel = fn; }

export function cancel() {
  if (!pending) return;
  pending = null;
  document.querySelectorAll('.cat-item.on').forEach(e => e.classList.remove('on'));
  $('placebar').style.display = 'none';
  store.say('');
}

function arm(kind, id, label, el) {
  document.querySelectorAll('.cat-item.on').forEach(e => e.classList.remove('on'));
  if (pending && pending.kind === kind && pending.id === id) return cancel();
  pending = { kind, id, label };
  el.classList.add('on');
  $('placebar-txt').textContent = 'Placing: ' + label + ' — click the map';
  $('placebar').style.display = 'flex';
  store.say('▸ click the map to place "' + label + '" — right-click, Esc or ✕ stops.');
}
document.getElementById('placebar-stop').onclick = () => cancel();

// called by the views on a click while place mode is armed; world = canvas 512
export function placeAt(wx, wz) {
  if (!pending) return false;
  const p = pending;
  if (p.kind === 's6') {
    store.apply(() => It.addUnit(p.id, +$('cat-s6team').value, wx, wz));
  } else if (p.kind === 'in') {
    store.apply(() => It.addObject(p.id, wx, wz));
  } else if (p.kind === 'tr') {
    if (!store.ed.extra) { store.say('extra list not decodable for this level'); return true; }
    store.apply(() => It.addExtra(p.id, +$('cat-trteam').value, wx, wz));
  } else if (p.kind === 'imp') {
    const l = store.lvl;
    store.apply(s => {
      let idx = l.models.findIndex(n => (n || '').toUpperCase() === p.name.toUpperCase());
      if (idx < 0) {
        l.models.push(p.name);
        s.ed.addModels.push({ from: p.from, name: p.name });
        idx = l.models.length - 1;
      }
      const tpl = p.tpl || [0, 0, 0, 0, 0, 0, 0];
      const r = [idx, Math.round(wx), 0, Math.round(512 - wz), tpl[4], tpl[5], tpl[6]];
      r[2] = Math.round(It.heightAt(wx / 8, wz / 8) * 8);
      s.ed.inst.push(r);
      s.sel = { k: 'in', i: s.ed.inst.length - 1 };
    });
    if (onImportModel) onImportModel(p.from, p.name);
  }
  return true;
}

function tileIcon(text, hue) {
  const c = document.createElement('canvas');
  c.width = c.height = 96;
  const x = c.getContext('2d');
  x.fillStyle = `hsl(${hue} 40% 26%)`;
  x.fillRect(0, 0, 96, 96);
  x.fillStyle = `hsl(${hue} 70% 70%)`;
  x.font = 'bold 34px sans-serif';
  x.textAlign = 'center'; x.textBaseline = 'middle';
  x.fillText(text.slice(0, 2), 48, 50);
  return c.toDataURL();
}

function item(grid, label, sub, kind, id, thumbPromise, hue) {
  const div = document.createElement('div');
  div.className = 'cat-item';
  div.dataset.search = (label + ' ' + (sub || '')).toLowerCase();
  const img = new Image();
  img.src = tileIcon(label.replace(/^\d+\s*/, ''), hue);
  if (thumbPromise) thumbPromise.then(u => { if (u) img.src = u; }).catch(() => {});
  div.appendChild(img);
  const cap = document.createElement('div');
  cap.textContent = label;
  cap.title = label + (sub ? ' — ' + sub : '');
  div.appendChild(cap);
  div.onclick = () => arm(kind, id, label, div);
  grid.appendChild(div);
}

export function rebuild() {
  const l = store.lvl, cat = store.cat;
  cancel();
  // units (s6)
  const gu = $('cat-units');
  gu.innerHTML = '';
  cat.s6Names.forEach((n, i) => item(gu, n, 'unit ' + i, 's6', i, null, (i * 47) % 360));
  // level models
  const gm = $('cat-models');
  gm.innerHTML = '';
  l.models.forEach((n, i) =>
    item(gm, n || '#' + i, 'model', 'in', i, TH.levelModelThumb(l.entry, n), 120));
  // turrets & statics
  const gs = $('cat-statics');
  gs.innerHTML = '';
  const keys = Object.keys(cat.statics).map(Number).sort((a, b) => a - b);
  const groups = [
    ['Turrets', k => /^Turret/i.test(cat.statics[k])],
    ['Other statics — no preview: in game these borrow the LEVEL\'s own '
     + 'furniture models (their resource slots are level-dependent). '
     + 'Untested in vanilla.', k => !/^Turret/i.test(cat.statics[k])],
  ];
  for (const [glabel, filter] of groups) {
    const h = document.createElement('div');
    h.className = 'hint';
    h.style.gridColumn = '1/-1';
    h.textContent = glabel;
    gs.appendChild(h);
    for (const k of keys.filter(filter)) {
      const name = cat.statics[k] || '?';
      if (!name || name === 'T') continue;
      const dat = cat.staticModels && cat.staticModels[k];
      const safe = cat.extraVanilla.includes(k) ? '' : ' (untested)';
      item(gs, k + ' ' + name, safe, 'tr', k, dat ? TH.globalThumb(String(dat)) : null, 185);
    }
  }
  rebuildImports();
  filter();
}

export function filter() {
  const q = ($('cat-search').value || '').toLowerCase();
  document.querySelectorAll('.cat-item').forEach(e => {
    e.style.display = !q || e.dataset.search.includes(q) ? '' : 'none';
  });
}

// ---- import from another level ----
export function rebuildImports() {
  const sel = $('cat-implvl');
  const opts = store.cat.levels.filter(l => l.entry !== store.entry);
  sel.innerHTML = opts.map(l => `<option value="${l.entry}">${l.entry} — ${l.name}</option>`).join('');
  sel.onchange = () => buildImportGrid(sel.value);
  if (opts.length) buildImportGrid(opts[0].entry);
}

async function buildImportGrid(src) {
  const grid = $('cat-imports');
  grid.innerHTML = '<div class="hint" style="grid-column:1/-1">loading…</div>';
  try {
    const l = await api.level(src);
    grid.innerHTML = '';
    l.models.forEach((name, i) => {
      if (!name) return;
      const tpl = l.inst.find(r => r[0] === i);   // e-param/rot defaults
      const div = document.createElement('div');
      div.className = 'cat-item';
      div.dataset.search = (name + ' import ' + src).toLowerCase();
      const img = new Image();
      img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg"/%3E';
      TH.levelModelThumb(src, name).then(u => { if (u) img.src = u; }).catch(() => {});
      div.appendChild(img);
      const cap = document.createElement('div');
      cap.textContent = name;
      cap.title = name + ' — from ' + src;
      div.appendChild(cap);
      div.onclick = () => armImport(src, name, tpl, div);
      grid.appendChild(div);
    });
    filter();
  } catch (e) {
    grid.innerHTML = '<div class="hint" style="grid-column:1/-1">failed to load level</div>';
  }
}

function armImport(from, name, tpl, el) {
  document.querySelectorAll('.cat-item.on').forEach(e => e.classList.remove('on'));
  if (pending && pending.kind === 'imp' && pending.name === name && pending.from === from)
    return cancel();
  pending = { kind: 'imp', from, name, tpl, label: name + ' (from ' + from + ')' };
  el.classList.add('on');
  $('placebar-txt').textContent = 'Placing: ' + pending.label + ' — click the map';
  $('placebar').style.display = 'flex';
  store.say('▸ importing "' + name + '" from level ' + from + ' — click the map to place it.');
}
