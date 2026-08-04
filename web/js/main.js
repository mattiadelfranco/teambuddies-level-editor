import { store } from './store.js';
import { init2d, draw, loadGround, reloadGround } from './view2d.js';
import * as V3 from './view3d.js';
import { initUI, setViewButtons } from './ui.js';
import { deleteSel } from './items.js';

const $ = id => document.getElementById(id);

function setMode(mode) {
  store.view.mode = mode;
  $('cv2d').style.display = mode === '2d' ? '' : 'none';
  $('cv3d').style.display = mode === '3d' ? 'block' : 'none';
  V3.show3d(mode === '3d');
  setViewButtons(mode);
  if (mode === '2d') draw();
}

async function boot() {
  await store.init();
  initUI(setMode);
  init2d($('cv2d'), $('st-pos'), $('tip'));
  V3.init3d($('cv3d'), $('st-pos'));

  // camera buttons (Layers tab, 3D mode)
  $('ly-rotl').onclick = () => V3.rotateCam(Math.PI / 2);
  $('ly-rotr').onclick = () => V3.rotateCam(-Math.PI / 2);
  $('ly-gamecam').onclick = () => V3.gameCam();

  const sel = $('level');
  sel.innerHTML = store.cat.levels
    .map(l => `<option value="${l.entry}">${l.entry} — ${l.name}</option>`).join('');

  store.onChange(what => {
    if (what === 'level') {
      loadGround();
      V3.reload();
      if (sel.value !== store.entry) sel.value = store.entry;
    }
    if (what === 'saved') {           // baseline reloaded from disk
      reloadGround();
      V3.refreshTerrain();
    }
    if (what === 'layers') V3.composeGround();
    if (store.view.mode === '2d') draw();
  });

  window.addEventListener('keydown', e => {
    if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      if (store.sel) {
        let err;
        store.apply(() => { err = deleteSel(); });
        if (err) store.say(err);
        e.preventDefault();
      }
    } else if (e.key === 'Escape' && store.sel) {
      store.apply(s => { s.sel = null; }, 'select');
    }
  });

  setMode('2d');
  await store.load(store.cat.levels[0].entry);
}

boot().catch(e => {
  document.body.innerHTML = '<pre style="padding:20px;color:#ff8f8f">Editor failed to start: '
    + e.message + '\n\nIs the server running?  python3 tools/editor_server.py</pre>';
  console.error(e);
});
