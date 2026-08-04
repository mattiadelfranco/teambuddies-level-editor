import { store } from './store.js';
import { init2d, draw, loadGround, reloadGround } from './view2d.js';
import * as V3 from './view3d.js';
import { initUI, setViewButtons, setTool } from './ui.js';
import { deleteSel } from './items.js';
import { brush, strokeActive } from './terrain.js';
import * as TL from './tiles.js';
import * as CAT from './catalog.js';

// repainting the 3D ground texture is ~10ms: throttle during paint drags
let composeTimer = 0;
function scheduleCompose() {
  if (composeTimer) return;
  composeTimer = setTimeout(() => { composeTimer = 0; V3.composeGround(); }, 150);
}

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
  CAT.setImportHook((from, name) => V3.importModel(from, name));

  // camera buttons (Layers tab, 3D mode)
  $('ly-rotl').onclick = () => V3.rotateCam(Math.PI / 2);
  $('ly-rotr').onclick = () => V3.rotateCam(-Math.PI / 2);
  $('ly-gamecam').onclick = () => V3.gameCam();

  const sel = $('level');
  sel.innerHTML = store.cat.levels
    .map(l => `<option value="${l.entry}">${l.entry} — ${l.name}</option>`).join('');

  store.onChange(what => {
    if (what === 'level') {
      loadGround(() => V3.composeGround());
      V3.reload();
      TL.loadAtlas(store.entry).then(() => store.emit('atlas')).catch(() => {});
      if (sel.value !== store.entry) sel.value = store.entry;
    }
    if (what === 'saved') {           // baseline reloaded from disk
      reloadGround(() => V3.composeGround());
      V3.refreshTerrainMesh();
    }
    if (what === 'layers') V3.composeGround();
    if (what === 'hm' || what === 'hm-restored') V3.refreshTerrainMesh();
    if (what === 'tiles') scheduleCompose();
    if (what === 'tiles-restored') { TL.repaintAll(); scheduleCompose(); }
    if (store.view.mode === '2d') draw();
  });

  window.addEventListener('keydown', e => {
    const inInput = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
    if ((e.metaKey || e.ctrlKey) && (e.key === 'z' || e.key === 'Z')) {
      if (inInput) return;             // let text inputs keep their own undo
      e.preventDefault();
      if (e.shiftKey) store.redo(); else store.undo();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && (e.key === 'y' || e.key === 'Y')) {
      if (inInput) return;
      e.preventDefault();
      store.redo();
      return;
    }
    if (e.key === 'Escape' && inInput) { document.activeElement.blur(); return; }
    if (inInput) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      if (store.sel && store.tool === 'select') {
        let err;
        store.apply(() => { err = deleteSel(); });
        if (err) store.say(err);
        e.preventDefault();
      }
    } else if (e.key === 'Escape') {
      if (CAT.pending) CAT.cancel();
      else if (store.sel) store.apply(s => { s.sel = null; }, 'select');
      else if (store.tool !== 'select') setTool('select');
    } else if (e.key === 'v' || e.key === 'V') setTool('select');
    else if (e.key === 'h' || e.key === 'H') setTool('height');
    else if (e.key === 't' || e.key === 'T') setTool('tiles');
    else if ((e.key === '[' || e.key === ']') && store.tool === 'height' && !strokeActive()) {
      brush.radius = Math.max(1, Math.min(8, brush.radius + (e.key === ']' ? 0.5 : -0.5)));
      document.getElementById('br-radius').value = brush.radius;
      document.getElementById('br-radiusv').textContent = String(brush.radius);
      if (store.view.mode === '2d') draw();
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
