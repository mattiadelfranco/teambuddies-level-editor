// Panel + top bar wiring. All mutations go through store.apply.
import { store, ZONE_PRESETS } from './store.js';
import * as It from './items.js';
import { modelColor } from './view2d.js';
import { brush } from './terrain.js';
import * as TL from './tiles.js';
import * as CAT from './catalog.js';
import * as IM from './atlasimport.js';
import * as AI from './aiwalk.js';

const $ = id => document.getElementById(id);
const isAuto = name => /auto/i.test(name || '');

export function setTool(tool) {
  store.apply(s => { s.tool = tool; }, 'tool');
  $('t_select').classList.toggle('on', tool === 'select');
  $('t_height').classList.toggle('on', tool === 'height');
  $('t_tiles').classList.toggle('on', tool === 'tiles');
  $('t_ai').classList.toggle('on', tool === 'ai');
  $('subbar').style.display = tool === 'height' ? 'flex' : 'none';
  $('subbar-tiles').style.display = tool === 'tiles' ? 'flex' : 'none';
  $('subbar-ai').style.display = tool === 'ai' ? 'flex' : 'none';
  if (tool === 'height' && !store.view.layers.hm)
    store.apply(s => { s.view.layers.hm = true; }, 'layers');
  if (tool === 'ai' && !store.view.layers.pth)
    store.apply(s => { s.view.layers.pth = true; }, 'layers');
  if (tool === 'ai' && !store.ed.pth)
    store.say('this level has no PTH file — AI grid editing unavailable.');
  if (tool === 'tiles') {
    const tabBtn = document.querySelector('#tabs button[data-tab="palette"]');
    if (tabBtn && !document.getElementById('tab-palette').classList.contains('on'))
      tabBtn.click();
    drawStamp();
  }
}

// ---- palette ----
function rotStamp() { TL.T.stamp.orient = (TL.T.stamp.orient & 4) | ((TL.T.stamp.orient + 1) & 3); store.emit('stamp'); }
function mirStamp() { TL.T.stamp.orient ^= 4; store.emit('stamp'); }

export function drawPalette() {
  if (!TL.T.atlas) return;
  // keep the CLUT dropdown in sync with this level's atlas
  const n = TL.T.atlas.cluts.length, selEl = $('pl-clut');
  if (selEl.options.length !== n + 1) {
    const cur = selEl.value;
    selEl.innerHTML = '<option value="-1">auto (per cell)</option>'
      + Array.from({ length: n }, (_, i) => `<option value="${i}">${i}</option>`).join('');
    selEl.value = [...selEl.options].some(o => o.value === cur) ? cur : '-1';
  }
  const cx = TL.cellsX(), rows = TL.T.atlas.h >> 6;
  const cvp = $('pl-atlas');
  cvp.width = cx * 32; cvp.height = rows * 32;
  const x = cvp.getContext('2d');
  const clutSel = +($('pl-clut').value || -1);
  const tmp = document.createElement('canvas');
  tmp.width = tmp.height = 64;
  for (let cell = 0; cell < cx * rows; cell++) {
    const clut = clutSel < 0 ? TL.autoClutFor(cell) : clutSel;
    tmp.getContext('2d').putImageData(TL.renderCell(cell, clut, 0), 0, 0);
    x.imageSmoothingEnabled = false;
    x.drawImage(tmp, (cell % cx) * 32, (cell / cx | 0) * 32, 32, 32);
  }
  // highlight the selected cell
  x.strokeStyle = '#fff'; x.lineWidth = 2;
  x.strokeRect((TL.T.stamp.cell % cx) * 32 + 1, (TL.T.stamp.cell / cx | 0) * 32 + 1, 30, 30);
  IM.drawOverlay(x);          // free/used markers while picking an import target
  drawStamp();
}

export function drawStamp() {
  if (!TL.T.atlas) return;
  const im = TL.renderCell(TL.T.stamp.cell, TL.stampClut(), TL.T.stamp.orient);
  for (const id of ['pl-stamp', 'tl-stamp']) {
    const c = $(id);
    const tmp = document.createElement('canvas');
    tmp.width = tmp.height = 64;
    tmp.getContext('2d').putImageData(im, 0, 0);
    const x = c.getContext('2d');
    x.imageSmoothingEnabled = false;
    x.clearRect(0, 0, c.width, c.height);
    x.drawImage(tmp, 0, 0, c.width, c.height);
  }
  $('pl-info').textContent = `cell ${TL.T.stamp.cell} · clut ${TL.stampClut()}`
    + (TL.T.stamp.autoClut ? ' (auto)' : '') + ` · orient ${TL.T.stamp.orient}`;
}

function initPalette() {
  $('pl-atlas').onclick = e => {
    const r = $('pl-atlas').getBoundingClientRect();
    const cx = TL.cellsX();
    const cell = Math.floor((e.clientY - r.top) / r.height * (TL.T.atlas.h >> 6)) * cx
               + Math.floor((e.clientX - r.left) / r.width * cx);
    if (IM.pickActive()) return IM.pickDst(cell);   // import destination pick
    TL.T.stamp.cell = cell;
    const clutSel = +($('pl-clut').value || -1);
    TL.T.stamp.autoClut = clutSel < 0;
    if (clutSel >= 0) TL.T.stamp.clut = clutSel;
    store.emit('stamp');
  };
  IM.initImport();
  $('pl-clut').onchange = () => {
    const v = +$('pl-clut').value;
    TL.T.stamp.autoClut = v < 0;
    if (v >= 0) TL.T.stamp.clut = v;
    drawPalette();
    store.emit('stamp');
  };
  $('pl-rot').onclick = rotStamp;
  $('pl-mir').onclick = mirStamp;
  $('tl-rot').onclick = rotStamp;
  $('tl-mir').onclick = mirStamp;
  document.querySelectorAll('#subbar-tiles [data-tm]').forEach(b => b.onclick = () => {
    document.querySelectorAll('#subbar-tiles [data-tm]').forEach(o =>
      o.classList.toggle('on', o === b));
    TL.T.mode = b.dataset.tm;
    if (b.dataset.tm !== 'clone') TL.T.cloneSrc = null;
  });
  $('tl-size').oninput = e => { TL.T.size = +e.target.value; $('tl-sizev').textContent = e.target.value; };
  $('tl-rel').onchange = e => { TL.T.rel = e.target.checked; };
}

export function initUI(onViewMode) {
  // tabs
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.tab').forEach(x =>
      x.classList.toggle('on', x.id === 'tab-' + b.dataset.tab));
  });

  // top bar
  $('level').onchange = async e => {
    if (store.dirty && !confirm('Unsaved changes on this level will stay in memory. Switch anyway?')) {
      e.target.value = store.entry; return;
    }
    await store.load(e.target.value);
  };
  $('undo').onclick = () => store.undo();
  $('redo').onclick = () => store.redo();
  $('save').onclick = () => store.save().catch(e => store.say('SAVE ERROR: ' + e.message));
  $('build').onclick = async () => {
    store.say('building ISO…');
    try {
      const j = await (await fetch('/api/build', { method: 'POST', body: '{}' })).json();
      store.say((j.ok ? '✓ ISO ready (teambudd/rebuild.cue)' : 'BUILD ERROR') + '\n' + (j.log || []).join('\n'));
    } catch (e) { store.say('BUILD ERROR: ' + e.message); }
  };
  $('v2d').onclick = () => onViewMode('2d');
  $('v3d').onclick = () => onViewMode('3d');

  // tools + brush sub-bar
  $('t_select').onclick = () => setTool('select');
  $('t_height').onclick = () => setTool('height');
  $('t_tiles').onclick = () => setTool('tiles');
  $('t_ai').onclick = () => setTool('ai');
  document.querySelectorAll('#subbar-ai [data-am]').forEach(b => b.onclick = () => {
    document.querySelectorAll('#subbar-ai [data-am]').forEach(o =>
      o.classList.toggle('on', o === b));
    AI.A.mode = b.dataset.am;
  });
  $('ai-size').oninput = e => { AI.A.size = +e.target.value; $('ai-sizev').textContent = e.target.value; };
  $('ai-auto').onclick = () => {
    store.beginGesture();
    const n = AI.autoFromSlopes();
    store.endGesture();
    store.say(n ? `⚡ blocked ${n} half-tile cells under steep slopes (add-only: `
      + 'vanilla water/cliff blocks untouched). Check the red layer, free gates with ✓ Free.'
      : 'no new steep cells to block — the AI grid already covers the current terrain.');
  };
  document.querySelectorAll('#subbar [data-bm]').forEach(b => b.onclick = () => {
    document.querySelectorAll('#subbar [data-bm]').forEach(x =>
      x.classList.toggle('on', x === b));
    brush.mode = b.dataset.bm;
    $('br-valrow').style.display = brush.mode === 'set' ? '' : 'none';
  });
  $('br-radius').oninput = e => { brush.radius = +e.target.value; $('br-radiusv').textContent = e.target.value; };
  $('br-strength').oninput = e => { brush.strength = +e.target.value; $('br-strengthv').textContent = e.target.value; };
  $('br-value').onchange = e => { brush.value = +e.target.value | 0; };
  $('br-snap').onchange = e => { brush.snap4 = e.target.checked; };
  initPalette();

  // view / layers
  $('ly-mx').onchange = e => store.apply(s => { s.view.mirrorX = e.target.checked; }, 'view');
  $('ly-my').onchange = e => store.apply(s => { s.view.mirrorY = e.target.checked; }, 'view');
  $('ly-rot').onchange = e => store.apply(s => { s.view.rot = +e.target.value; }, 'view');
  for (const k of ['ground', 'hm', 'pth', 'obj'])
    $('ly-' + k).onchange = e => store.apply(s => { s.view.layers[k] = e.target.checked; }, 'layers');

  // catalog (grid + place mode in catalog.js)
  $('cat-search').oninput = () => CAT.filter();
  $('cat-defenses').onclick = () => {
    if (!store.ed.extra) return store.say('extra list not decodable for this level');
    let t = CAT.pending && CAT.pending.kind === 'tr' ? CAT.pending.id : 117;
    if (!/^Turret/i.test(store.cat.statics[t] || '')) t = 117;   // Gatling (Auto)
    let n = 0;
    store.apply(() => { n = It.addDefenses(t); });
    store.say(n ? `added ${n} × "${store.cat.statics[t]}" around the bases (owner's team via ENG patch). Drag to refine.`
                : 'no BSE_* base in this level');
  };
  $('cat-addteam').onclick = () => {
    let parts;
    store.apply(() => { parts = It.addTeam(); });
    store.say(`new team ${store.ed.s0.length}: pad` + (parts.length ? ' + ' + parts.join(' + ') : '')
      + ' cloned near the center — drag into place. Active only if the mission expects that many teams'
      + ' (Level tab). Remember a nearby crate zone.');
  };
  $('cat-addtp').onclick = () => {
    let i;
    store.apply(() => { i = It.addTeleportPair(256, 256); });
    store.say(`new teleport pair: entrance ${i} → exit ${i + 1}, both near the map center — `
      + 'drag them where you want (the arrow shows the link).');
  };
  $('cat-addzone').onclick = () => {
    let ok;
    store.apply(() => { ok = It.addZone(); });
    store.say(ok ? 'new crate zone (clone of zone 1): drag it NEAR the pad it should serve — delivery always goes to the nearest zone.'
                 : 'level has no crate zones to clone');
  };

  // level tab
  $('lv-teams').innerHTML = [1, 2, 3, 4, 5, 6, 7, 8]
    .map(n => `<option value="${n}">${n}${n > 4 ? ' ⚠' : ''}</option>`).join('');
  $('lv-teams').onchange = e => store.apply(s => {
    s.ed.tcount = +e.target.value; s.ed.tcountTouched = true;
    s.log = `mission set to ${e.target.value} teams on next save (needs as many s0 pads, ideally as many crate zones).`;
  });
  $('lv-rset').innerHTML = Object.keys(store.cat.recipes)
    .map(n => `<option value="${n}">${n}${store.cat.recipes[n].name ? ' — ' + store.cat.recipes[n].name : ''}</option>`).join('');
  $('lv-rset').onchange = e => {
    if (store.rec.touched && !confirm(`Discard unsaved recipe edits for set ${store.rec.set}?`)) {
      e.target.value = String(store.rec.set); return;
    }
    store.loadRecipeSet(e.target.value);
  };

  store.onChange(what => {
    if (what === 'level') onLevel();
    if (what === 'recipes' || what === 'level') renderRecipes();
    if (what === 'view' || what === 'layers' || what === 'level') syncViewControls();
    if (what === 'stamp' || what === 'atlas' || what === 'palette') drawPalette();
    refreshInspector();
    $('dirty').textContent = store.dirty ? '● unsaved changes' : '';
    $('st-sel').textContent = store.sel ? selLabel() : '';
    $('st-log').textContent = store.log;
  });
}

function selLabel() {
  const it = It.items().find(o => o.k === store.sel.k && o.i === store.sel.i);
  return it ? it.lbl : '';
}

export function setViewButtons(mode) {
  $('v2d').classList.toggle('on', mode === '2d');
  $('v3d').classList.toggle('on', mode === '3d');
  document.querySelectorAll('#ly-mx,#ly-my,#ly-rot').forEach(el =>
    el.closest('label, .row').style.display = mode === '2d' ? '' : 'none');
  $('ly-3dhint').style.display = mode === '3d' ? '' : 'none';
  $('ly-camrow').style.display = mode === '3d' ? 'flex' : 'none';
}

function syncViewControls() {
  $('ly-mx').checked = store.view.mirrorX;
  $('ly-my').checked = store.view.mirrorY;
  $('ly-rot').value = String(store.view.rot);
  for (const k of ['ground', 'hm', 'pth', 'obj']) $('ly-' + k).checked = store.view.layers[k];
}

// ---- per-level refresh ----
function onLevel() {
  const l = store.lvl;
  CAT.rebuild();
  $('cat-note').textContent = store.ed.extra ? '' :
    '⚠ extra list not decodable for this level: turret editing disabled, data left untouched.';
  const tc = store.ed.tcount;
  $('lv-teams').disabled = tc === null;
  if (tc !== null) $('lv-teams').value = String(tc);
  // PLD sections toggles
  const div = $('ly-secs');
  div.innerHTML = '';
  const SEC_COLORS = ['#ff4757', '#ffa502', '#2ed573', '#1e90ff', '#e84393', '#00d2d3',
    '#f9ca24', '#a29bfe', '#fd79a8', '#55efc4', '#fab1a0', '#74b9ff', '#ffeaa7',
    '#81ecec', '#dfe6e9', '#b2bec3', '#636e72'];
  // all 17 sections identified — see docs/FORMATS.md
  const SEC_NAMES = ['spawns + pads', 'random spawn candidates', 'hidden weapons',
    'crate zones', 'objective points', '(unused)', 'placed units', 'AI patrol routes',
    '(unused)', '(unused)', 'teleport zones', '(unused)', 'delivery points',
    'scripted drops', 'nearest-point list A', 'nearest-point list B', 'unit routes'];
  for (const s of l.pld) {
    const lab = document.createElement('label');
    const info = s.pts.length ? `n=${s.n} rec=${s.rec}B` : `${s.sz}B`;
    lab.title = `s${s.i} (accessor arg 0x${(s.i * 4).toString(16)}) — ${SEC_NAMES[s.i]}`;
    lab.innerHTML = `<input type="checkbox" data-s="${s.i}" ${store.view.sections.has(s.i) ? 'checked' : ''}
      ${s.pts.length ? '' : 'disabled'}>
      <span class="sw" style="background:${SEC_COLORS[s.i]}"></span>
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">s${s.i} ${SEC_NAMES[s.i]}</span>
      <span class="hint">${info}</span>`;
    lab.querySelector('input').onchange = e => store.apply(st => {
      const i = +e.target.dataset.s;
      e.target.checked ? st.view.sections.add(i) : st.view.sections.delete(i);
    }, 'layers');
    div.appendChild(lab);
  }
  // legend
  const counts = {};
  for (const r of store.ed.inst) {
    const nm = l.models[r[0]] || '#' + r[0];
    counts[nm] = (counts[nm] || 0) + 1;
  }
  $('ly-legend').innerHTML = Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([nm, n]) => `<div class="leg"><span class="sw" style="background:${modelColor(nm)}"></span>${nm} ×${n}</div>`)
    .join('');
  renderRecipes();
}

// ---- recipes ----
function renderRecipes() {
  $('lv-rsetlbl').textContent = '— set ' + store.rec.set
    + (store.cat.recipes[store.rec.set].name ? ' (' + store.cat.recipes[store.rec.set].name + ')' : '');
  if ($('lv-rset').value !== String(store.rec.set)) $('lv-rset').value = String(store.rec.set);
  const toyOpt = v => Object.keys(store.cat.toyNames)
    .map(t => `<option value="${t}"${+t === v ? ' selected' : ''}>${t} — ${store.cat.toyNames[t]}</option>`).join('');
  $('lv-rrows').innerHTML = store.rec.pairs
    .map((p, i) => `<div class="rrow"><span class="hint" style="width:12px">${i + 1}</span>
      <select data-i="${i}" data-j="0" title="normal crate">${toyOpt(p[0])}</select>
      <select data-i="${i}" data-j="1" title="mega version">${toyOpt(p[1])}</select></div>`).join('');
  $('lv-rrows').querySelectorAll('select').forEach(s => s.onchange = () => store.apply(st => {
    st.rec.pairs[+s.dataset.i][+s.dataset.j] = +s.value;
    st.rec.touched = true;
  }));
  const ms = Object.keys(store.cat.mset).filter(m => store.cat.mset[m] === store.rec.set)
    .map(m => '0' + (512 + +m));
  $('lv-ruse').textContent = ms.length ? 'used by levels: ' + ms.join(', ')
    : 'no campaign mission uses this set';
}

// ---- inspector ----
function zoneCfgName(c) {
  if (!c) return 'engine default';
  for (const [k, v] of Object.entries(ZONE_PRESETS))
    if (v && v.join() === c.join()) return k;
  return 'custom [' + c.join(',') + ']';
}

function refreshInspector() {
  const sel = store.sel;
  $('ins-empty').style.display = sel ? 'none' : '';
  $('ins-body').style.display = sel ? '' : 'none';
  if (!sel) return;
  const it = It.items().find(o => o.k === sel.k && o.i === sel.i);
  if (!it) { store.sel = null; return refreshInspector(); }
  $('ins-title').textContent = it.lbl;
  $('ins-pos').textContent = `tile (${(it.x / 8).toFixed(2)}, ${(it.z / 8).toFixed(2)})`
    + `  ·  h ${It.heightAt(it.x / 8, it.z / 8).toFixed(1)}`;
  const F = $('ins-fields');
  const note = $('ins-note');
  note.textContent = '';
  const st = store.ed;

  if (sel.k === 's6') {
    const r = st.s6.records[sel.i];
    if (CAT.OBJECTIVE_UNITS[r[0]])
      note.textContent = '⚠ mission-objective unit (' + CAT.OBJECTIVE_UNITS[r[0]]
        + '). Outside its mission it often spawns INVISIBLE while its contact '
        + 'logic still runs — a frequent cause of "invisible zones that kill you".';
    F.innerHTML = `<div class="row"><label>Type</label><select id="if-type"></select></div>
      <div class="row"><label>Team</label><select id="if-team">${[1, 2, 3, 4]
        .map((n, i) => `<option value="${i}"${r[1] === i ? ' selected' : ''}>team ${n}</option>`).join('')}</select></div>`;
    $('if-type').innerHTML = store.cat.s6Names
      .map((n, i) => `<option value="${i}"${r[0] === i ? ' selected' : ''}>${i} — ${n}</option>`).join('');
    $('if-type').onchange = e => store.apply(s => { s.ed.s6.records[sel.i][0] = +e.target.value; });
    $('if-team').onchange = e => store.apply(s => { s.ed.s6.records[sel.i][1] = +e.target.value; });
  } else if (sel.k === 'tr') {
    const r = st.extra[sel.i], f8 = r[8] || 0;
    const deg = Math.round((r[7] & 0xfff) / 4096 * 360);
    F.innerHTML = `<div class="row"><label>Team</label><select id="if-trteam">
      <option value="0">auto (vanilla)</option>${[1, 2, 3, 4]
        .map(n => `<option value="${n}"${f8 === n ? ' selected' : ''}>team ${n}${n === 1 ? ' (P1)' : ''}</option>`).join('')}
      </select></div>
      <div class="row"><label>Rotation</label>
      <input id="if-rot" type="number" value="${deg}" step="45" style="width:60px">°
      <button id="if-rotl">−90°</button><button id="if-rotr">+90°</button></div>`;
    $('if-trteam').onchange = e => store.apply(s => { s.ed.extra[sel.i][8] = +e.target.value; });
    const setRot = d => store.apply(s => {
      s.ed.extra[sel.i][7] = Math.round(((d % 360 + 360) % 360) / 360 * 4096) & 0xfff;
    });
    $('if-rot').onchange = e => setRot(+e.target.value || 0);
    $('if-rotl').onclick = () => setRot(Math.round((st.extra[sel.i][7] & 0xfff) / 4096 * 360) - 90);
    $('if-rotr').onclick = () => setRot(Math.round((st.extra[sel.i][7] & 0xfff) / 4096 * 360) + 90);
    if (f8 > 0) note.textContent = `TEAM ${f8} FORCED (via ENG patch).`;
    else if (isAuto(store.cat.statics[r[5]]))
      note.textContent = '⚠ AUTO turret without a team: in practice hostile to the player — set a team above.';
    else {
      const ow = It.owner(it);
      note.textContent = ow ? `→ nearest claimed base: TEAM ${ow.team + 1} (verify in game)`
                            : '→ no base: ownership undefined';
    }
  } else if (sel.k === 'in') {
    const r = st.inst[sel.i];
    const deg = Math.round(((r[5] >>> 16) & 0xfff) / 4096 * 360);
    F.innerHTML = `<div class="row"><label>Altitude</label>
      <input id="if-alt" type="number" value="${r[2]}" style="width:70px">
      <button id="if-snap" title="set altitude to the terrain height under the object">Snap to ground</button></div>
      <div class="row"><label>Rotation</label>
      <input id="if-rot" type="number" value="${deg}" step="45" style="width:60px">°
      <button id="if-rotl">−90°</button><button id="if-rotr">+90°</button></div>
      <div class="hint">e-param ${r[4]} · r1 0x${(r[5] >>> 0).toString(16)}</div>`;
    $('if-alt').onchange = e => store.apply(s => { s.ed.inst[sel.i][2] = +e.target.value | 0; });
    $('if-snap').onclick = () => store.apply(s => {
      s.ed.inst[sel.i][2] = Math.round(It.heightAt(it.x / 8, it.z / 8) * 8);
    });
    const setRot = d => store.apply(s => {
      const raw = Math.round(((d % 360 + 360) % 360) / 360 * 4096) & 0xfff;
      s.ed.inst[sel.i][5] = ((raw << 16) | (s.ed.inst[sel.i][5] & 0xffff)) | 0;
    });
    $('if-rot').onchange = e => setRot(+e.target.value || 0);
    $('if-rotl').onclick = () => setRot(Math.round(((st.inst[sel.i][5] >>> 16) & 0xfff) / 4096 * 360) - 90);
    $('if-rotr').onclick = () => setRot(Math.round(((st.inst[sel.i][5] >>> 16) & 0xfff) / 4096 * 360) + 90);
  } else if (sel.k === 'cz') {
    const c = st.zcfg[sel.i];
    F.innerHTML = `<div class="hint">Crates: ${zoneCfgName(c)}</div>
      <div class="row"><select id="if-zpre">${Object.keys(ZONE_PRESETS)
        .map(k => `<option>${k}</option>`).join('')}</select>
      <button id="if-zapply">Apply</button></div>
      <div class="hint">Two independent drop streams: NORMAL crates and MEGA crates (big
        model, worth more). One crate every RATE frames, from frame START to frame END
        (end &lt; 0 = forever), max MAX of this stream's crates on the ground at once
        (25 frames = 1s). TYPE is not read by the drop scheduler (mission-script data;
        effect unverified) — timing and amounts live entirely in the other 4 columns.</div>
      <div class="grid"><span></span><span>type</span><span>start</span><span>end</span><span>rate</span><span>max</span>
      <span>NORMAL</span>${[0, 2, 4, 6, 8].map(k => `<input id="if-zc${k}" type="number" value="${c ? c[k] : ''}">`).join('')}
      <span>MEGA</span>${[1, 3, 5, 7, 9].map(k => `<input id="if-zc${k}" type="number" value="${c ? c[k] : ''}">`).join('')}</div>`;
    $('if-zapply').onclick = () => store.apply(s => {
      const v = ZONE_PRESETS[$('if-zpre').value];
      s.ed.zcfg[sel.i] = v ? v.slice() : null;
      if (v) for (let j = 0; j < sel.i; j++) if (!s.ed.zcfg[j]) {
        s.ed.zcfg[j] = ZONE_PRESETS['standard (t3, every 150)'].slice();
        s.log = `note: zone ${j + 1} was "engine default" (only allowed at the tail): set to "standard".`;
      }
      s.ed.zcfgTouched = true;
    });
    for (let k = 0; k < 10; k++) $('if-zc' + k).onchange = () => store.apply(s => {
      if (!s.ed.zcfg[sel.i]) {
        s.ed.zcfg[sel.i] = ZONE_PRESETS['standard (t3, every 150)'].slice();
        for (let j = 0; j < sel.i; j++)
          if (!s.ed.zcfg[j]) s.ed.zcfg[j] = ZONE_PRESETS['standard (t3, every 150)'].slice();
      }
      for (let j = 0; j < 10; j++) {
        const v = parseInt($('if-zc' + j).value, 10);
        if (!isNaN(v)) s.ed.zcfg[sel.i][j] = v;
      }
      s.ed.zcfgTouched = true;
    });
  } else if (sel.k === 'tp') {
    const r = st.s10[sel.i], entrance = !!(r[1] & 0x100);
    const others = st.s10.map((_, k) => k).filter(k => k !== sel.i);
    F.innerHTML = `<label><input type="checkbox" id="if-tpin" ${entrance ? 'checked' : ''}>
        entrance (sends the buddy to the destination)</label>
      <div class="row"><label>Destination</label><select id="if-tpdest">${
        others.map(k => `<option value="${k}"${r[0] === k ? ' selected' : ''}>zone ${k}</option>`).join('')
        || '<option value="0">— no other zone —</option>'}</select></div>
      <div class="row"><label>Size</label>
        <input id="if-tpw" type="number" min="1" max="32" value="${r[4] - r[2]}" style="width:52px">×
        <input id="if-tph" type="number" min="1" max="32" value="${r[5] - r[3]}" style="width:52px">
        <span class="hint">half-tiles</span></div>
      <div class="hint">variant ${r[1] & 0xff} · rect ${r[2]},${r[3]}–${r[4]},${r[5]} (half-tiles)</div>`;
    $('if-tpin').onchange = e => store.apply(s2 => {
      const rr = s2.ed.s10[sel.i];
      rr[1] = e.target.checked ? (rr[1] | 0x100) : (rr[1] & ~0x100);
    });
    $('if-tpdest').onchange = e => store.apply(s2 => { s2.ed.s10[sel.i][0] = +e.target.value; });
    const setSize = () => store.apply(s2 => {
      const rr = s2.ed.s10[sel.i];
      const w = Math.max(1, Math.min(32, +$('if-tpw').value || 1));
      const h = Math.max(1, Math.min(32, +$('if-tph').value || 1));
      rr[4] = Math.min(128, rr[2] + w); rr[5] = Math.min(128, rr[3] + h);
    });
    $('if-tpw').onchange = setSize; $('if-tph').onchange = setSize;
    const dst = st.s10[r[0]];
    note.textContent = entrance
      ? (dst ? `Entering this rect tosses the buddy to zone ${r[0]} at tile `
               + `(${((dst[2] + dst[4]) / 4).toFixed(1)}, ${((dst[3] + dst[5]) / 4).toFixed(1)}).`
             : 'destination zone missing!')
      : 'Exit pad: something else points here. Explosions never crater teleport zones.';
  } else if (sel.k === 's0') {
    F.innerHTML = '';
    note.textContent = `Pad ${sel.i + 1}: spawn + stacking logic. The painted 2x2 pad art follows the `
      + 'marker live (the ground around it stays put); animations + terrain flattening apply on save. '
      + 'Teams claim the nearest base, in pad order.';
  } else {
    F.innerHTML = '';
  }

  $('ins-dup').onclick = () => store.apply(() => It.duplicateSel());
  $('ins-del').onclick = () => {
    if (sel.k === 's0' && !confirm(`Delete pad ${sel.i + 1}? Teams are bound to record ORDER — prefer deleting the last one.`)) return;
    let err;
    store.apply(() => { err = It.deleteSel(); });
    if (err) store.say(err);
  };
}
