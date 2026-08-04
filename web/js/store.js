// Single source of truth for the editor. Every mutation goes through
// store.apply(fn) so both views stay in sync (and undo can hook in later).
import { api, b64i16 } from './api.js';

export const ZONE_PRESETS = {
  'rich (t4, every 30)':      [4, 0, 0, 0, -30, -30, 30, 3600, 8, 0],
  'standard (t3, every 150)': [3, 0, 0, 0, 45000, 0, 150, 0, 4, 0],
  'light (t1, every 150)':    [1, 0, 0, 0, 45000, 0, 150, 0, 2, 0],
  'mega (t10, every 90)':     [10, 0, 0, 3600, -30, -30, 90, 900, 6, 0],
  'campaign (t5, every 120)': [5, 0, 0, 1800, 45000, 45000, 120, 300, 5, 0],
  'nearly dead (vanilla)':    [0, 0, 0, 900, 0, -30, 0, 900, 0, 0],
  'engine default':           null,
};

export const tos16 = v => (v >= 32768 ? v - 65536 : v);
// native pad grid: odd half-tiles (like every vanilla s0 value)
export const snapOdd = r => {
  const h = Math.round((tos16(r) / 256 - 1) / 2) * 2 + 1;
  return (h * 256) & 0xffff;
};

const listeners = [];

export const store = {
  cat: null,            // catalogs (levels, names, recipes, zcfg, mset, mteams)
  entry: null,          // current level entry ("0512")
  lvl: null,            // parsed level data from /api/level
  hm: null,             // Int16Array 65x65
  ed: null,             // editable state (s0/s3/s6/extra/inst/zcfg/tcount)
  edits: {},            // per-entry editable states (kept across level switches)
  rec: { set: 0, pairs: null, touched: false },
  sel: null,            // {k, i}
  dirty: false,
  tool: 'select',
  view: {
    mode: '2d', mirrorX: false, mirrorY: true, rot: 0,
    layers: { ground: true, hm: false, pth: false, obj: true },
    sections: new Set([0]),
  },
  log: '',

  onChange(fn) { listeners.push(fn); },
  emit(what) { for (const fn of listeners) fn(what); },

  // every mutation goes through here
  apply(fn, what = 'edit') {
    fn(this);
    if (what === 'edit' || what === 'hm') this.dirty = true;
    this.emit(what);
  },

  say(msg) { this.log = msg; this.emit('log'); },

  mission() { return parseInt(this.entry, 10) - 512; },

  async init() {
    this.cat = await api.catalogs();
    const rs = this.cat.recipes[0];
    this.rec = { set: 0, pairs: rs.pairs.map(p => p.slice()), touched: false };
  },

  async load(entry) {
    this.lvl = await api.level(entry);
    this.entry = entry;
    if (!this.edits[entry]) {
      const l = this.lvl, mis = this.mission();
      const zc = this.cat.zcfg[mis] || [];
      this.edits[entry] = {
        s0: l.s0.map(r => r.slice()),
        s3: l.s3.map(p => p.slice()),
        zcfg: l.s3.map((_, i) => (zc[i] ? zc[i].slice() : null)),
        zcfgTouched: false,
        tcount: this.cat.mteams[mis] !== undefined ? this.cat.mteams[mis] : null,
        tcountTouched: false,
        s6: JSON.parse(JSON.stringify(l.s6)),
        extra: l.extra ? l.extra.map(r => r.slice()) : null,
        inst: l.inst.map(r => r.slice()),
        hm: b64i16(this.lvl.hm),          // editable heightmap (65x65 s16)
        hmTouched: false,
      };
    }
    this.ed = this.edits[entry];
    this.hm = this.ed.hm;                 // views read the editable copy
    this.sel = null;
    // auto-follow the level's recipe set unless the user is mid-edit
    const ds = this.cat.mset[this.mission()];
    if (ds !== undefined && !this.rec.touched && this.rec.set !== ds) this.loadRecipeSet(ds);
    this.emit('level');
  },

  loadRecipeSet(set) {
    const rs = this.cat.recipes[set];
    if (!rs) return;
    this.rec = { set: +set, pairs: rs.pairs.map(p => p.slice()), touched: false };
    this.emit('recipes');
  },

  async save() {
    const ed = this.ed;
    const edits = {
      s0: ed.s0.map(p => p.map(v => tos16(v) / 256)),
      s6: {
        extra: ed.s6.extra,
        records: ed.s6.records.map(r => [r[0], r[1], r[2], tos16(r[3]) / 256, tos16(r[4]) / 256]),
      },
      instFull: ed.inst,
    };
    if (ed.s3.length) edits.s3 = ed.s3;
    if (ed.zcfgTouched) edits.zoneCfg = ed.zcfg;
    if (this.rec.touched) edits.recipes = { set: this.rec.set, pairs: this.rec.pairs };
    if (ed.tcountTouched) edits.teamCount = ed.tcount;
    if (ed.extra) edits.extra = ed.extra;
    if (ed.hmTouched) {
      // 65x65 s16 LE -> base64
      const b = new Uint8Array(ed.hm.buffer.slice(0));
      let s = '';
      for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
      edits.hm = btoa(s);
    }
    const r = await api.save(this.entry, edits);
    if (r.ok) {
      this.dirty = false;
      if (r.recipes) this.rec.touched = false;
      ed.hmTouched = false;
      this.say('✓ saved to mods/' + this.entry + (r.recipes ? ' (+recipe set ' + r.recipes.set + ')' : ''));
      // reload from disk so the baseline matches what was written
      this.lvl = await api.level(this.entry);
      ed.hm.set(b64i16(this.lvl.hm));     // keep the shared reference alive
      this.emit('saved');
    } else {
      this.say('SAVE ERROR: ' + (r.err || ''));
    }
    return r;
  },
};
