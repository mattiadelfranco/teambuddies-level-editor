// Panel + top bar wiring. All mutations go through store.apply.
import { store, ZONE_PRESETS } from './store.js';
import * as It from './items.js';
import { modelColor } from './view2d.js';
import { brush } from './terrain.js';

const $ = id => document.getElementById(id);
const isAuto = name => /auto/i.test(name || '');

export function setTool(tool) {
  store.apply(s => { s.tool = tool; }, 'tool');
  $('t_select').classList.toggle('on', tool === 'select');
  $('t_height').classList.toggle('on', tool === 'height');
  $('subbar').style.display = tool === 'height' ? 'flex' : 'none';
  if (tool === 'height' && !store.view.layers.hm)
    store.apply(s => { s.view.layers.hm = true; }, 'layers');
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

  // view / layers
  $('ly-mx').onchange = e => store.apply(s => { s.view.mirrorX = e.target.checked; }, 'view');
  $('ly-my').onchange = e => store.apply(s => { s.view.mirrorY = e.target.checked; }, 'view');
  $('ly-rot').onchange = e => store.apply(s => { s.view.rot = +e.target.value; }, 'view');
  for (const k of ['ground', 'hm', 'pth', 'obj'])
    $('ly-' + k).onchange = e => store.apply(s => { s.view.layers[k] = e.target.checked; }, 'layers');

  // catalog static parts
  $('cat-s6').innerHTML = store.cat.s6Names
    .map((n, i) => `<option value="${i}">${i} — ${n}</option>`).join('');
  fillExtraSelect();
  $('cat-addunit').onclick = () =>
    store.apply(() => It.addUnit(+$('cat-s6').value, +$('cat-s6team').value));
  $('cat-addobj').onclick = () => {
    const m = +$('cat-mdl').value;
    const name = store.lvl.models[m] || m;
    if (!store.ed.inst.find(r => r[0] === m)
        && !confirm(`No instance of "${name}" in this level: adding with default params (e=0) may misbehave. Continue?`)) return;
    store.apply(() => It.addObject(m));
  };
  $('cat-addextra').onclick = () => {
    if (!store.ed.extra) return store.say('extra list not decodable for this level — left untouched');
    const t = +$('cat-extra').value;
    const nm = store.cat.statics[t] || '?';
    if (!store.cat.extraVanilla.includes(t) && !/^Turret/i.test(nm)
        && !confirm(`"${nm}" is never placed via the extra list in vanilla levels: untested in game. Continue?`)) return;
    store.apply(() => It.addExtra(t));
  };
  $('cat-defenses').onclick = () => {
    if (!store.ed.extra) return store.say('extra list not decodable for this level');
    let t = +$('cat-extra').value;
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

function fillExtraSelect() {
  const s = $('cat-extra'), cat = store.cat;
  const keys = Object.keys(cat.statics).map(Number).sort((a, b) => a - b);
  const opt = t => `<option value="${t}">${t} — ${cat.statics[t] || '?'}${cat.extraVanilla.includes(t) ? ' ✓' : ''}</option>`;
  const grp = (label, filter) =>
    `<optgroup label="${label}">${keys.filter(filter).map(opt).join('')}</optgroup>`;
  s.innerHTML =
    grp('Enterable turrets', t => /^Turret/i.test(cat.statics[t]) && !isAuto(cat.statics[t]))
    + grp('Auto turrets (fire at everyone!)', t => /^Turret/i.test(cat.statics[t]) && isAuto(cat.statics[t]))
    + grp('Statics (trees / rocks / buildings / powerups…)', t => !/^Turret/i.test(cat.statics[t]));
}

// ---- per-level refresh ----
function onLevel() {
  const l = store.lvl;
  $('cat-mdl').innerHTML = l.models.map((n, i) => `<option value="${i}">${n || '#' + i}</option>`).join('');
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
  for (const s of l.pld) {
    const lab = document.createElement('label');
    const info = s.pts.length ? `n=${s.n} rec=${s.rec}B` : `${s.sz}B`;
    lab.innerHTML = `<input type="checkbox" data-s="${s.i}" ${store.view.sections.has(s.i) ? 'checked' : ''}
      ${s.pts.length ? '' : 'disabled'}>
      <span class="sw" style="background:${SEC_COLORS[s.i]}"></span> s${s.i}
      <span class="hint">(${info})</span>`;
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
    F.innerHTML = `<div class="row"><label>Type</label><select id="if-type"></select></div>
      <div class="row"><label>Team</label><select id="if-team">${[1, 2, 3, 4]
        .map((n, i) => `<option value="${i}"${r[1] === i ? ' selected' : ''}>team ${n}</option>`).join('')}</select></div>`;
    $('if-type').innerHTML = store.cat.s6Names
      .map((n, i) => `<option value="${i}"${r[0] === i ? ' selected' : ''}>${i} — ${n}</option>`).join('');
    $('if-type').onchange = e => store.apply(s => { s.ed.s6.records[sel.i][0] = +e.target.value; });
    $('if-team').onchange = e => store.apply(s => { s.ed.s6.records[sel.i][1] = +e.target.value; });
  } else if (sel.k === 'tr') {
    const r = st.extra[sel.i], f8 = r[8] || 0;
    F.innerHTML = `<div class="row"><label>Team</label><select id="if-trteam">
      <option value="0">auto (vanilla)</option>${[1, 2, 3, 4]
        .map(n => `<option value="${n}"${f8 === n ? ' selected' : ''}>team ${n}${n === 1 ? ' (P1)' : ''}</option>`).join('')}
      </select></div>`;
    $('if-trteam').onchange = e => store.apply(s => { s.ed.extra[sel.i][8] = +e.target.value; });
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
    F.innerHTML = `<div class="row"><label>Altitude</label>
      <input id="if-alt" type="number" value="${r[2]}" style="width:70px">
      <button id="if-snap" title="set altitude to the terrain height under the object">Snap to ground</button></div>
      <div class="hint">rot r1=0x${(r[5] >>> 0).toString(16)} · e-param ${r[4]}</div>`;
    $('if-alt').onchange = e => store.apply(s => { s.ed.inst[sel.i][2] = +e.target.value | 0; });
    $('if-snap').onclick = () => store.apply(s => {
      s.ed.inst[sel.i][2] = Math.round(It.heightAt(it.x / 8, it.z / 8) * 8);
    });
  } else if (sel.k === 'cz') {
    const c = st.zcfg[sel.i];
    F.innerHTML = `<div class="hint">Crates: ${zoneCfgName(c)}</div>
      <div class="row"><select id="if-zpre">${Object.keys(ZONE_PRESETS)
        .map(k => `<option>${k}</option>`).join('')}</select>
      <button id="if-zapply">Apply</button></div>
      <div class="hint">type = area recipe 1–6 (+8/10 special), tgt −30 = infinite</div>
      <div class="grid"><span></span><span>type</span><span>init</span><span>tgt</span><span>rate</span><span>a</span>
      <span>slot A</span>${[0, 2, 4, 6, 8].map(k => `<input id="if-zc${k}" type="number" value="${c ? c[k] : ''}">`).join('')}
      <span>slot B</span>${[1, 3, 5, 7, 9].map(k => `<input id="if-zc${k}" type="number" value="${c ? c[k] : ''}">`).join('')}</div>`;
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
  } else if (sel.k === 's0') {
    F.innerHTML = '';
    note.textContent = `Pad ${sel.i + 1}: spawn + stacking logic. The engine draws the pad here at runtime; `
      + 'painted tiles + arrow animations follow on save. Teams claim the nearest base, in pad order.';
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
