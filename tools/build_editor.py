#!/usr/bin/env python3
"""
Team Buddies - Genera l'editor (teambudd/editor.html) partendo dal viewer:
rigenera viewer.html, poi inietta i dati extra (s6, lista torrette PND) e la
UI di modifica. L'editor parla col server locale (tools/editor_server.py).
"""
import struct, glob, os, sys, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIND = os.path.join(ROOT, "teambudd/dat_estratto/bind")
VIEWER = os.path.join(ROOT, "teambudd/viewer.html")
OUT = os.path.join(ROOT, "teambudd/editor.html")

# catalogo dello spazio-62 (sezione s6) = entry DAT 958: BIND con 62 ST*.BIN,
# uno per slot della tabella DAT_80119b00 IN ORDINE (FUN_800834bc li scorre in
# parallelo). Verificato sui tipi noti in gioco: 15=STLION, 22=STPIG, 32=STSHEEP.
# 30/35/44/49 = obiettivi missione per-team (percorso speciale nello spawner).
S6_NAMES = {
    0: "Commando", 1: "Fante", 2: "Kung Fu", 3: "Medico", 4: "Stealth",
    5: "Super Buddy", 6: "Eskimo", 7: "Legionario", 8: "Contadino", 9: "Pastore",
    10: "Yeti", 11: "Baywatch", 12: "Tarzan", 13: "Pinguino", 14: "Orso polare",
    15: "Leone", 16: "Escursionista", 17: "Ariete", 18: "Scimmia", 19: "Cammello",
    20: "Toro", 21: "Cavallo", 22: "Maiale", 23: "Lucertola", 24: "Foca",
    25: "Grizzly", 26: "Cane", 27: "Gatto", 28: "Puffin", 29: "Cane B",
    30: "Pretty (obiettivo team)", 31: "Cyborg", 32: "Pecora", 33: "Ninja",
    34: "Fantasma", 35: "Ostaggio (obiettivo team)", 36: "Dummy 1", 37: "Dummy 2",
    38: "Dummy 3", 39: "Dummy 4", 40: "Dummy 5", 41: "Dummy 6", 42: "Dummy 7",
    43: "Dummy 8", 44: "Scienziato congelato (obiettivo)", 45: "Rifornimenti cammello",
    46: "Mech Laser", 47: "Mech Boss", 48: "Mech Gatling", 49: "Cane bomba (obiettivo)",
    50: "Cane bersaglio", 51: "Scienziato 2", 52: "Cattivo (Baddie)", 53: "Alieno",
    54: "Alieno Hooley", 55: "Lupo", 56: "Scienziato CP", 57: "Boss Pecora (Ewe Fiend)",
    58: "Maiale da cattura", 59: "Pinguino da cattura", 60: "Pecora da cattura",
    61: "Cane da cattura"}

# catalogo della lista extra PND = STATICS.BIN (entry 0953): 188 record da 64B
# con NOME PROPRIO nei primi 32 byte. Il campo tipo del record extra indicizza
# questa tabella 1:1 (il builder FUN_80093a44 la copia in DAT_800bffb0, 0x48/slot).
# NB la vecchia mappa "tipo = toy+26" era un'illusione da coincidenze di nomi.
STATICS_NAMES = {}
_sd = open(os.path.join(ROOT, "teambudd/dat_estratto/bind/0953/STATICS.BIN"), "rb").read()
for _i in range(int.from_bytes(_sd[4:8], "little")):
    _n = _sd[0xc + _i*0x40: 0xc + _i*0x40 + 0x20].split(b"\0")[0].decode("latin-1").strip()
    STATICS_NAMES[_i] = _n
# tipi extra visti nei livelli vanilla (sicuri di certo)
EXTRA_VANILLA = [113, 116, 117, 121, 122, 123, 124, 125, 127, 128, 129, 133]


def parse_extra(folder):
    """s0/s6 del PLD + lista extra e istanze del PND per un livello (da mods/ se presente)."""
    entry = os.path.basename(folder)
    mod = os.path.join(ROOT, "teambudd/mods", entry)
    is_mod = os.path.isdir(mod)
    if is_mod:
        folder = mod
    plds = glob.glob(os.path.join(folder, "*.PLD"))
    pnds = glob.glob(os.path.join(folder, "*.PND"))
    if not (plds and pnds):
        return None
    out = {"entry": entry}
    d = open(plds[0], "rb").read()
    offs = struct.unpack_from("<17I", d, 8)
    o = offs[6] + 8
    cnt, extra = struct.unpack_from("<2H", d, o)
    recs = []
    if cnt < 500:
        for i in range(cnt):
            t, tv, x, z = struct.unpack_from("<4H", d, o + 4 + i * 8)
            recs.append([t, tv & 0xff, tv >> 8, x, z])
    out["s6"] = {"extra": extra, "records": recs}
    o0 = offs[0] + 8
    c0 = struct.unpack_from("<I", d, o0)[0]
    out["s0"] = [list(struct.unpack_from("<4H", d, o0 + 4 + k * 8)) for k in range(min(c0, 16))]
    # s3 = zone lancio casse: centri in tile (griglia 128 di mezzi-tile)
    o3 = offs[3] + 8
    c3 = struct.unpack_from("<I", d, o3)[0]
    p = o3 + 4
    zones = []
    for _ in range(min(c3, 16)):
        n = struct.unpack_from("<I", d, p)[0]
        p += 4
        idx = struct.unpack_from(f"<{n}H", d, p)
        p += n * 2 + (2 if n & 1 else 0)
        hx = [t % 128 for t in idx]
        hz = [t // 128 for t in idx]
        zones.append([(min(hx) + max(hx) + 1) / 4, (min(hz) + max(hz) + 1) / 4])
    out["s3"] = zones

    d = open(pnds[0], "rb").read()
    n_names, n_inst, _, _ = struct.unpack_from("<4H", d, 4)
    o = 12 + n_names * 32 + n_inst * 20
    cnt, = struct.unpack_from("<H", d, o)
    # None = lista non decodificabile (es. BOSSANOVA): l'editor la lascia intatta
    ex = None
    if cnt < 100:
        ex = [list(struct.unpack_from("<10H", d, o + 2 + i * 20)) for i in range(cnt)]
    out["extra"] = ex
    if is_mod:
        # istanze complete: baseline assoluta per l'editor sui livelli gia' moddati
        # (il viewer legge i vanilla; senza questa lista le modifiche precedenti
        # sparirebbero dalla UI e verrebbero perse al salvataggio successivo)
        inst = []
        for i in range(n_inst):
            oo = 12 + n_names * 32 + i * 20
            m, = struct.unpack_from("<I", d, oo)
            x, h, z, e = struct.unpack_from("<4h", d, oo + 4)
            r1, r2 = struct.unpack_from("<2i", d, oo + 12)
            inst.append([m, x, h, z, e, r1, r2])
        out["inst"] = inst
    return out


# rigenera i terreni dei livelli modificati (da mods/) prima del viewer;
# grounds_vanilla conserva i render originali per il ripristino
GR = os.path.join(ROOT, "teambudd/grounds")
GRV = os.path.join(ROOT, "teambudd/grounds_vanilla")
MODS = os.path.join(ROOT, "teambudd/mods")
if not os.path.isdir(GRV):
    import shutil
    shutil.copytree(GR, GRV)
for png in glob.glob(os.path.join(GRV, "*.png")):
    entry = os.path.basename(png)[:-4]
    mod = os.path.join(MODS, entry)
    dst = os.path.join(GR, entry + ".png")
    if os.path.isdir(mod) and glob.glob(os.path.join(mod, "*.PND")):
        pnd = glob.glob(os.path.join(mod, "*.PND"))[0]
        if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(pnd):
            subprocess.run([sys.executable, os.path.join(ROOT, "tools/render_ground.py"),
                            mod, dst, "8"], cwd=ROOT, check=True)
            print(f"terreno rigenerato da mods: {entry}")
    else:
        orig_png = open(png, "rb").read()
        if not os.path.exists(dst) or open(dst, "rb").read() != orig_png:
            open(dst, "wb").write(orig_png)

subprocess.run([sys.executable, os.path.join(ROOT, "tools/build_viewer.py")], cwd=ROOT, check=True)

extras = []
for folder in sorted(glob.glob(os.path.join(BIND, "*"))):
    if os.path.isdir(folder):
        e = parse_extra(folder)
        if e:
            extras.append(e)

# config casse per-zona (LEVELS.BIN, BIND 0955 - versione moddata se presente):
# per missione (= entry-512) la lista di voci 40B [t0,t1,i0,i1,g0,g1,r0,r1,a0,a1];
# le zone s3 oltre il count girano coi default del motore (funzionanti)
_lvp = os.path.join(ROOT, "teambudd/mods/0955/LEVELS.BIN")
if not os.path.exists(_lvp):
    _lvp = os.path.join(ROOT, "teambudd/dat_estratto/bind/0955/LEVELS.BIN")
_lv = open(_lvp, "rb").read()
_nrec = struct.unpack_from("<H", _lv, 0)[0]
_tab = 4 + _nrec * 0x80
_n1, _n2 = struct.unpack_from("<II", _lv, _tab)
_t3 = _tab + 12 + _n1 * 28 + _n2 * 4
ZCFG = {}
MSET = {}
for _m in range(_nrec):
    _r = 4 + _m * 0x80
    _zc, _zs = struct.unpack_from("<II", _lv, _r + 0x74)
    ZCFG[_m] = [list(struct.unpack_from("<2I2I2i2I2H", _lv, _t3 + (_zs + _k) * 40))
                for _k in range(min(_zc, 16))]
    MSET[_m] = struct.unpack_from("<I", _lv, _r + 0x68)[0]   # set ricette casse

# ricette casse: 41 set (BIND 0953, N_CRATECONTENTS.BIN = 6 coppie normale/mega
# nello spazio-180); nomi set dai file compagni N_BT_*.BIN, nomi toy IT da
# toy_names_it.txt (estratti dalla entry DAT 0016)
import re as _re
_c53 = os.path.join(ROOT, "teambudd/mods/0953")
if not os.path.isdir(_c53):
    _c53 = os.path.join(ROOT, "teambudd/dat_estratto/bind/0953")
RECIPES = {}
_setnames = {}
for _f in os.listdir(os.path.join(ROOT, "teambudd/dat_estratto/bind/0953")):
    _m2 = _re.match(r"(\d+)_BT_(.+)\.BIN$", _f)
    if _m2:
        _setnames[int(_m2.group(1))] = _m2.group(2)
for _n in range(41):
    _p = os.path.join(_c53, f"{_n}_CRATECONTENTS.BIN")
    if not os.path.exists(_p):
        _p = os.path.join(ROOT, f"teambudd/dat_estratto/bind/0953/{_n}_CRATECONTENTS.BIN")
    _d2 = open(_p, "rb").read()
    _cn = struct.unpack_from("<I", _d2, 0)[0]
    RECIPES[_n] = {"name": _setnames.get(_n, ""),
                   "pairs": [list(struct.unpack_from("<2H", _d2, 4 + _k * 4)) for _k in range(min(_cn, 6))]}
TOYNAMES = {}
for _ln in open(os.path.join(ROOT, "teambudd/toy_names_it.txt")):
    _m2 = _re.match(r"\s*(\d+)\s+(.+)$", _ln)
    if _m2:
        TOYNAMES[int(_m2.group(1))] = _m2.group(2).strip()

# numero team per missione (entry 0956, moddata se presente)
_p56 = os.path.join(ROOT, "teambudd/mods/0956.bin")
if not os.path.exists(_p56):
    _p56 = os.path.join(ROOT, "teambudd/dat_estratto/raw/0956.bin")
_d56 = open(_p56, "rb").read()
MTEAMS = {m: struct.unpack_from("<I", _d56, 8 + m * 8)[0] for m in range(struct.unpack_from("<I", _d56, 0)[0])}

EDJS = r"""
// ============== EDITOR ==============
const ED_DATA=__ED__;
const ED_ZCFG=__EDZCFG__;      // missione -> voci config zona correnti (LEVELS.BIN)
// preset config zona [tipo0,tipo1,init0,init1,tgt0,tgt1,rate0,rate1,a0,a1]
// tipo = ricetta cassa 1-6 dell'area (+ speciali 8/10); -30 = infinito
const ED_ZPRESETS={
  'ricca (t4, ogni 30)':        [4,0,0,0,-30,-30,30,3600,8,0],
  'standard (t3, ogni 150)':    [3,0,0,0,45000,0,150,0,4,0],
  'leggera (t1, ogni 150)':     [1,0,0,0,45000,0,150,0,2,0],
  'mega (t10, ogni 90)':        [10,0,0,3600,-30,-30,90,900,6,0],
  'campagna (t5, ogni 120)':    [5,0,0,1800,45000,45000,120,300,5,0],
  'quasi morta (vanilla)':      [0,0,0,900,0,-30,0,900,0,0],
  'default motore':             null
};
const ED_RECIPES=__EDRECIPES__;  // set -> {name, pairs[6][2]} (spazio-180)
const ED_TOYNAMES=__EDTOYS__;    // toy id -> nome IT
const ED_MSET=__EDMSET__;        // missione -> set ricette (LEVELS.BIN +0x68)
const ED_MTEAMS=__EDMTEAMS__;    // missione -> n. team (entry 0956, config slot)
const ED_NAMES=__EDNAMES__;
const ED_STATICS=__EDSTATICS__;    // tipo lista extra -> nome (STATICS.BIN, 188)
const ED_EXTRA_VANILLA=new Set(__EDEXV__); // tipi extra visti nei livelli vanilla
const edTrName=t=>ED_STATICS[t]||('static tipo '+t+' (?)');
const edIsAuto=t=>/auto/i.test(ED_STATICS[t]||'');
const tos16e=v=>v>=32768?v-65536:v;
const eTX=()=>+document.getElementById('tarx').value||0,eTY=()=>+document.getElementById('tary').value||0;
const h2wx=h=>(32+tos16e(h)/512)*8+eTX(),h2wy=h=>(32+tos16e(h)/512)*8+eTY();          // raw 8.8 mezzi-tile centro-rel -> mondo
const w2hx=w=>Math.round(((w-eTX())/8-32)*2*256)&0xffff,w2hy=w=>Math.round(((w-eTY())/8-32)*2*256)&0xffff;
// snap alla griglia nativa delle pedane: mezzi-tile DISPARI (come tutti i valori s0 vanilla)
const snapOdd=r=>{const h=Math.round((tos16e(r)/256-1)/2)*2+1;return (h*256)&0xffff;};  // mondo -> raw 8.8
let edMode=false, edStates={}, edSel=null, edDrag=false, edDirty=false;
// allinea i layer del viewer ai dati correnti (mods): niente elementi vanilla fantasma
ED_DATA.forEach(e=>{const l=LV.find(x=>x.entry===e.entry);
  if(!l)return;
  if(e.s0&&l.pld[0])l.pld[0].pts=e.s0.map(r=>r.slice());
  if(e.inst)l.inst=e.inst.map(r=>r.slice());});

function edState(){
  const l=LV[cur], x=ED_DATA.find(e=>e.entry===l.entry);
  if(!edStates[cur]){
    const mis=parseInt(l.entry,10)-512;
    const zc=ED_ZCFG[mis]||[];
    const s3z=((x&&x.s3)?x.s3:[]).map(p=>p.slice());
    edStates[cur]={
      s0:((x&&x.s0)?x.s0:(l.pld[0].pts||[])).map(p=>p.slice()),
      s3:s3z,                                            // zone lancio casse [cx,cz] tile
      zcfg:s3z.map((_,i)=>zc[i]?zc[i].slice():null),     // config cassa per zona (null=default)
      zcfgTouched:false,
      tcount:ED_MTEAMS[mis]!==undefined?ED_MTEAMS[mis]:null,  // n. team missione (0956)
      tcountTouched:false,
      s6:JSON.parse(JSON.stringify(x?x.s6:{extra:0,records:[]})),
      extra:(x&&x.extra)?x.extra.map(r=>r.slice()):null, // null = non modificabile
      inst:l.inst.map(r=>r.slice())                      // lista completa (assoluta)
    };
  }
  return edStates[cur];
}
function edItems(){
  const st=edState(), l=LV[cur], out=[];
  st.s0.forEach((p,i)=>out.push({k:'s0',i,x:h2wx(p[0]),z:h2wy(p[1]),lbl:'pedana/spawn '+(i+1),col:'#ff4757'}));
  st.s3.forEach((p,i)=>out.push({k:'cz',i,x:p[0]*8+eTX(),z:p[1]*8+eTY(),
    lbl:'zona casse '+(i+1)+' (consegna alla zona più vicina)',col:'#ff9f1a'}));
  st.s6.records.forEach((r,i)=>out.push({k:'s6',i,x:h2wx(r[3]),z:h2wy(r[4]),
    lbl:(ED_NAMES[r[0]]||('tipo '+r[0]))+` (team ${r[1]+1})`,col:'#f9ca24'}));
  if(st.extra)st.extra.forEach((r,i)=>out.push({k:'tr',i,x:r[2]+18,z:512-r[4],lbl:edTrName(r[5]),col:'#00d2d3'}));
  st.inst.forEach((it,i)=>out.push({k:'in',i,x:W+eTX()-it[1],z:it[3],
    lbl:l.models[it[0]]||('#'+it[0]),col:'#a29bfe',small:true}));
  return out;
}
function edSelect(k,i){edSel=edItems().find(o=>o.k===k&&o.i===i)||null;}
// proprieta' degli oggetti extra (da FUN_800a8780 ENG): al caricamento l'oggetto
// prende il team della BASE piu' vicina; ogni pedana i reclama (in ordine,
// esclusivo) la base piu' vicina NELLO SPAZIO-V del motore:
// V_base=(x_inst/8, 64-z_inst/8) in tile, pad = tile s0 (verificato da savestate).
function edVinst(r){return {x:r[1]/8, z:64-r[3]/8};}
function edPadTile(p){return {x:32+tos16e(p[0])/512, z:32+tos16e(p[1])/512};}
function edOwner(it){
  const st=edState(), l=LV[cur];
  const bases=[];
  st.inst.forEach((r,i)=>{if((l.models[r[0]]||'').toUpperCase().startsWith('BSE'))bases.push({i,v:edVinst(r)});});
  if(!bases.length)return null;
  const taken=new Set(), claimed=[];
  st.s0.forEach((p,ti)=>{const pt=edPadTile(p);let bb=null,bd=1/0;
    for(const b of bases){if(taken.has(b.i))continue;
      const d=(b.v.x-pt.x)**2+(b.v.z-pt.z)**2;if(d<bd){bd=d;bb=b;}}
    if(bb){taken.add(bb.i);claimed.push({team:ti,base:bb});}});
  // l'oggetto extra (spazio dati non specchiato: coord marker) -> base piu' vicina in V?
  // gli oggetti extra vivono nello stesso spazio-V delle istanze: V_extra=(x_dato/8... )
  // per l'anteprima usiamo la distanza in spazio-V con la posizione marker convertita
  const itv={x:(it.x-eTX())/8, z:(it.z-eTY())/8};
  let best=null,bd=1/0;
  for(const c of claimed){
    const d=(c.base.v.x-itv.x)**2+(c.base.v.z-itv.z)**2;
    if(d<bd){bd=d;best=c;}}
  if(best){ // per il disegno della linea: posizione marker della base
    const r=st.inst[best.base.i];
    best.base={i:best.base.i, x:W+eTX()-r[1], z:r[3]};
  }
  return best;
}
function drawEd(){
  if(!edMode)return;
  const px=cv.width/W;
  // anteprime: impronta pedana 4x4 (32 unita' mondo) e anello zona casse 8x8 (64)
  for(const it of edItems()){
    if(it.k!=='s0'&&it.k!=='cz')continue;
    ctx.save();
    if(it.k==='s0'){ctx.fillStyle='rgba(255,71,87,0.25)';ctx.strokeStyle='rgba(255,71,87,0.9)';
      ctx.fillRect((it.x-16)*px,(it.z-16)*px,32*px,32*px);
      ctx.strokeRect((it.x-16)*px,(it.z-16)*px,32*px,32*px);}
    else{ctx.fillStyle='rgba(255,159,26,0.15)';ctx.strokeStyle='rgba(255,159,26,0.9)';
      ctx.fillRect((it.x-32)*px,(it.z-32)*px,64*px,64*px);
      ctx.strokeRect((it.x-32)*px,(it.z-32)*px,64*px,64*px);}
    ctx.restore();
  }
  for(const it of edItems()){
    ctx.save();
    ctx.strokeStyle=(edSel&&edSel.k===it.k&&edSel.i===it.i)?'#fff':'#000';
    ctx.lineWidth=(edSel&&edSel.k===it.k&&edSel.i===it.i)?3:1;
    ctx.fillStyle=it.col;
    const r=it.small?5:9;
    ctx.beginPath();ctx.arc(it.x*px,it.z*px,r,0,7);ctx.fill();ctx.stroke();
    ctx.restore();
  }
  // linea verso la base che possiedera' l'oggetto extra selezionato
  if(edSel&&edSel.k==='tr'){
    const cur_it=edItems().find(o=>o.k==='tr'&&o.i===edSel.i);
    const ow=cur_it&&edOwner(cur_it);
    if(ow){
      ctx.save();
      ctx.strokeStyle=['#e74c3c','#3498db','#2ecc71','#f1c40f'][ow.team]||'#fff';
      ctx.setLineDash([6,4]);ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(cur_it.x*px,cur_it.z*px);ctx.lineTo(ow.base.x*px,ow.base.z*px);ctx.stroke();
      ctx.restore();
    }
  }
}
{const _d=draw; draw=function(){_d();drawEd();};}

function pick(wx,wz){
  let best=null,bd=8;
  for(const it of edItems()){
    const d=Math.hypot(it.x-wx,it.z-wz);
    if(d<bd){bd=d;best=it;}
  }
  return best;
}
function applyMove(it,wx,wz){
  const st=edState();
  if(it.k==='s0'){st.s0[it.i][0]=snapOdd(w2hx(wx));st.s0[it.i][1]=snapOdd(w2hy(wz));}
  else if(it.k==='cz'){st.s3[it.i][0]=Math.max(4,Math.min(59,Math.round((wx-eTX())/8)));
    st.s3[it.i][1]=Math.max(4,Math.min(59,Math.round((wz-eTY())/8)));}
  else if(it.k==='s6'){st.s6.records[it.i][3]=w2hx(wx);st.s6.records[it.i][4]=w2hy(wz);}
  else if(it.k==='tr'){st.extra[it.i][2]=Math.round(wx-18)&0xffff;st.extra[it.i][4]=Math.round(512-wz)&0xffff;}
  else if(it.k==='in'){st.inst[it.i][1]=Math.round(W+eTX()-wx);st.inst[it.i][3]=Math.round(wz);}
  edDirty=true;edStatus();
}
cv.addEventListener('mousedown',e=>{
  if(!edMode)return;
  const [wx,wz]=evtToWorld(e);
  edSel=pick(wx,wz);edDrag=!!edSel;edStatus();draw();
  if(edSel)e.stopImmediatePropagation();
},true);
cv.addEventListener('mousemove',e=>{
  if(!edMode||!edDrag||!edSel)return;
  const [wx,wz]=evtToWorld(e);
  applyMove(edSel,wx,wz);draw();
},true);
window.addEventListener('mouseup',()=>{edDrag=false;});

function edDel(){
  if(!edSel)return;
  const st=edState();
  if(edSel.k==='s6')st.s6.records.splice(edSel.i,1);
  else if(edSel.k==='tr')st.extra.splice(edSel.i,1);
  else if(edSel.k==='in')st.inst.splice(edSel.i,1);
  else if(edSel.k==='cz'){
    if(st.s3.length<=1)return alert('serve almeno una zona casse');
    st.s3.splice(edSel.i,1);st.zcfg.splice(edSel.i,1);st.zcfgTouched=true;
  }
  else{
    if(st.s0.length<=1)return alert('serve almeno una pedana/spawn');
    if(!confirm('Elimino la pedana/spawn '+(edSel.i+1)+'? (i team sono legati all\'ORDINE dei record: elimina solo l\'ultima se possibile)'))return;
    st.s0.splice(edSel.i,1);
  }
  edSel=null;edDirty=true;edStatus();draw();
}
function edDup(){
  if(!edSel)return alert('seleziona prima un elemento');
  const st=edState();
  if(edSel.k==='s6'){
    const r=st.s6.records[edSel.i].slice();r[3]=(r[3]+1024)&0xffff;   // +2 tile
    st.s6.records.push(r);edSelect('s6',st.s6.records.length-1);
  }else if(edSel.k==='tr'){
    const r=st.extra[edSel.i].slice();r[2]=(r[2]+8)&0xffff;
    st.extra.push(r);edSelect('tr',st.extra.length-1);
  }else if(edSel.k==='in'){
    const r=st.inst[edSel.i].slice();r[1]-=8;
    st.inst.push(r);edSelect('in',st.inst.length-1);
  }else if(edSel.k==='cz'){
    const r=st.s3[edSel.i].slice();r[0]=Math.min(59,r[0]+4);
    st.s3.push(r);
    st.zcfg.push(st.zcfg[edSel.i]?st.zcfg[edSel.i].slice():null);st.zcfgTouched=true;
    edSelect('cz',st.s3.length-1);
  }else{
    const r=st.s0[edSel.i].slice();r[0]=snapOdd((r[0]+1024)&0xffff);  // +2 tile
    st.s0.push(r);edSelect('s0',st.s0.length-1);
  }
  edDirty=true;edStatus();draw();
}
function edAddTeam(){
  // nuovo team = pedana s0 + base + bandiera clonate (poi trascinale a posto).
  // NB il n. di team EFFETTIVO lo decide lo SLOT livello (config per-missione
  // res 0x3bd, slot=entry-512, tetto=count s0): su uno slot 2-team la terza
  // pedana resta blu/senza proprietario. Slot 4-team vanilla: PIGGY, QUARRY,
  // ANILEATION, SPHINX, ICESCREAM, BOSSANOVA... (s0 count=4)
  const st=edState(), l=LV[cur];
  st.s0.push([snapOdd(256),snapOdd(256),0x200,0x200]);   // vicino al centro
  // base+bandiera in SPAZIO-V vicino alla nuova pedana (x_inst=8*Vx, z_inst=512-8*Vz)
  const pt=edPadTile(st.s0[st.s0.length-1]);
  const parts=[];
  const bi=st.inst.findIndex(r=>(l.models[r[0]]||'').toUpperCase().startsWith('BSE'));
  if(bi>=0){const b=st.inst[bi].slice();b[1]=Math.round(8*(pt.x+4));b[3]=Math.round(512-8*pt.z);st.inst.push(b);parts.push('base');}
  const fi=st.inst.findIndex(r=>(l.models[r[0]]||'')==='base_flag');
  if(fi>=0){const f=st.inst[fi].slice();f[1]=Math.round(8*(pt.x+2));f[3]=Math.round(512-8*(pt.z+2));st.inst.push(f);parts.push('bandiera');}
  edSelect('s0',st.s0.length-1);
  edDirty=true;edStatus();draw();
  document.getElementById('edlog').textContent='nuovo team '+st.s0.length+': pedana'+
    (parts.length?' + '+parts.join(' + ')+' (clonate vicino al centro)':'')+
    ' — trascina tutto a posto. Attivo solo se lo slot livello prevede almeno '+st.s0.length+' team.'+
    ' Ricorda una ZONA CASSE vicina (+ zona casse), o il team userà quella di un altro.';
}
function edAddZone(){
  const st=edState();
  if(!st.s3.length)return alert('livello senza zone casse: nessun modello da clonare');
  st.s3.push([32,32]);
  st.zcfg.push(st.zcfg[0]?st.zcfg[0].slice():ED_ZPRESETS['standard (t3, ogni 150)'].slice());
  st.zcfgTouched=true;
  edSelect('cz',st.s3.length-1);
  edDirty=true;edStatus();draw();
  document.getElementById('edlog').textContent='nuova zona casse (clone della zona 1, config "'+(st.zcfg[0]?'come zona 1':'standard')+'"): trascinala VICINO alla pedana del team che deve servirla — la consegna va sempre alla zona più vicina al richiedente.';
}
// ---- ricette casse (per SET, condivise tra le missioni che usano il set) ----
let edRec={set:null,pairs:null,touched:false};
function edRecLoad(set){
  set=+set;
  if(!ED_RECIPES[set])return;
  edRec={set,pairs:ED_RECIPES[set].pairs.map(p=>p.slice()),touched:false};
  const s=document.getElementById('ed_rset');
  if(s.value!==String(set))s.value=String(set);
  document.getElementById('ed_rsetlbl').textContent=set+(ED_RECIPES[set].name?' — '+ED_RECIPES[set].name:'');
  edRecRender();
}
function edRecRender(){
  const div=document.getElementById('ed_rrows');
  const opt=v=>Object.keys(ED_TOYNAMES).map(t=>`<option value="${t}"${+t===v?' selected':''}>${t} — ${ED_TOYNAMES[t]}</option>`).join('');
  div.innerHTML=edRec.pairs.map((p,i)=>`<div style="display:flex;gap:4px;align-items:center;margin:2px 0">
    <span style="width:14px;color:#8b93a1">${i+1}</span>
    <select data-i="${i}" data-j="0" title="cassa normale">${opt(p[0])}</select>
    <select data-i="${i}" data-j="1" title="versione mega/potenziata">${opt(p[1])}</select></div>`).join('')
    +'<div style="color:#8b93a1;font-size:11px">col.1 = cassa normale, col.2 = versione mega. Il set è CONDIVISO tra i livelli elencati sopra.</div>';
  div.querySelectorAll('select').forEach(s=>{s.onchange=()=>{
    edRec.pairs[+s.dataset.i][+s.dataset.j]=+s.value;
    edRec.touched=true;edDirty=true;edStatus();
  };});
  const ms=Object.keys(ED_MSET).filter(m=>ED_MSET[m]===edRec.set).map(m=>'0'+(512+ +m));
  document.getElementById('ed_ruse').textContent=ms.length?('usato dai livelli: '+ms.join(', ')):'nessuna missione campagna usa questo set';
}
let edRecMis=null;
setInterval(()=>{ // al CAMBIO di livello proponi il suo set (mai mentre lavori su un set scelto a mano)
  if(typeof cur==='undefined'||!LV[cur])return;
  const mis=parseInt(LV[cur].entry,10)-512;
  if(mis===edRecMis)return;
  edRecMis=mis;
  const ds=ED_MSET[mis];
  if(ds!==undefined&&!edRec.touched&&edRec.set!==ds)edRecLoad(ds);
},700);
function edZoneCfgName(c){
  if(!c)return 'default motore';
  for(const[k,v]of Object.entries(ED_ZPRESETS)){if(v&&v.join()===c.join())return k;}
  return 'personalizzata ['+c.join(',')+']';
}
function edApplyZoneCfg(){
  if(!edSel||edSel.k!=='cz')return alert('seleziona prima una zona casse (marker arancione)');
  const st=edState(), name=document.getElementById('ed_zpre').value;
  const v=ED_ZPRESETS[name];
  st.zcfg[edSel.i]=v?v.slice():null;
  // vincolo formato: "default motore" solo per le ULTIME zone
  if(v)for(let j=0;j<edSel.i;j++)if(!st.zcfg[j]){
    st.zcfg[j]=ED_ZPRESETS['standard (t3, ogni 150)'].slice();
    document.getElementById('edlog').textContent='nota: zona '+(j+1)+' era "default motore" (ammesso solo in coda): impostata a "standard".';
  }
  st.zcfgTouched=true;edDirty=true;edStatus();
}
function edAddUnit(){
  const st=edState();
  const tipo=+document.getElementById('ed_s6t').value;
  const team=+document.getElementById('ed_s6team').value;
  st.s6.records.push([tipo,team,0,0,0]);          // raw (0,0) = centro mappa
  edSelect('s6',st.s6.records.length-1);
  edDirty=true;edStatus();draw();
}
function edAddObj(){
  const st=edState(), l=LV[cur];
  const m=+document.getElementById('ed_mdl').value;
  // clona un'istanza esistente dello stesso modello (e-param/alt/rot corretti)
  const tpl=st.inst.find(r=>r[0]===m);
  const r=tpl?tpl.slice():[m,0,0,0,0,0,0];
  if(!tpl&&st.inst.length){
    const hs=st.inst.map(q=>q[2]).sort((a,b)=>a-b);r[2]=hs[hs.length>>1];
    if(!confirm('Nessuna istanza di "'+(l.models[m]||m)+'" nel livello: la aggiungo con parametri di default (e=0), potrebbe comportarsi male. Continuo?'))return;
  }
  r[1]=256+eTX();r[3]=256;                        // vicino al centro
  st.inst.push(r);
  edSelect('in',st.inst.length-1);
  edDirty=true;edStatus();draw();
}
function edAddExtra(){
  const st=edState();
  if(!st.extra)return alert('lista extra non decodificata per questo livello: la lascio intatta');
  const tipo=+document.getElementById('ed_extra').value;
  const isTurret=/^Turret/i.test(ED_STATICS[tipo]||'');
  if(!ED_EXTRA_VANILLA.has(tipo)&&!isTurret&&
     !confirm('"'+edTrName(tipo)+'" non e\' mai piazzato via lista extra nei vanilla: da testare in gioco. Continuo?'))return;
  st.extra.push([0,0,256,16,256,tipo,0,512,0,0]);
  edSelect('tr',st.extra.length-1);
  edDirty=true;edStatus();draw();
}
function edFillExtra(){
  const s=document.getElementById('ed_extra');
  if(s.options.length)return;
  const grp=l=>{const g=document.createElement('optgroup');g.label=l;s.appendChild(g);return g;};
  const add=(g,tipo)=>{const o=document.createElement('option');o.value=tipo;
    o.textContent=tipo+' — '+(ED_STATICS[tipo]||'?')+(ED_EXTRA_VANILLA.has(tipo)?' ✓':'');g.appendChild(o);};
  const keys=Object.keys(ED_STATICS).map(Number).sort((a,b)=>a-b);
  const g1=grp('Torrette entrabili');
  keys.filter(t=>/^Turret/i.test(ED_STATICS[t])&&!edIsAuto(t)).forEach(t=>add(g1,t));
  const g2=grp('Torrette automatiche (sparano a tutti!)');
  keys.filter(t=>/^Turret/i.test(ED_STATICS[t])&&edIsAuto(t)).forEach(t=>add(g2,t));
  const g3=grp('Oggetti statici (alberi/rocce/edifici/powerup...)');
  keys.filter(t=>!/^Turret/i.test(ED_STATICS[t])).forEach(t=>add(g3,t));
}
function edAddDefenses(){
  const st=edState(), l=LV[cur];
  if(!st.extra)return alert('lista extra non decodificata per questo livello');
  const items=edItems();
  const bases=items.filter(o=>o.k==='in'&&(l.models[st.inst[o.i][0]]||'').toUpperCase().startsWith('BSE'));
  if(!bases.length)return alert('nessuna base (BSE_*) nel livello');
  const s0=items.filter(o=>o.k==='s0');
  let tipo=+document.getElementById('ed_extra').value;
  if(!/^Turret/i.test(ED_STATICS[tipo]||''))tipo=117;   // default: Gatling (Auto)
  const done=new Set(); let n=0;
  for(const s of s0){
    let bb=null,bd=1/0;
    for(const b of bases){const d=(b.x-s.x)**2+(b.z-s.z)**2;if(d<bd){bd=d;bb=b;}}
    if(!bb||done.has(bb.i))continue;
    done.add(bb.i);
    for(const [dx,dz] of [[28,-28],[-28,28]]){
      st.extra.push([0,0,Math.round(bb.x+dx-18)&0xffff,16,Math.round(512-(bb.z+dz))&0xffff,tipo,0,512,s.i+1,0]);
      n++;
    }
  }
  edDirty=true;edStatus();draw();
  document.getElementById('edlog').textContent='aggiunte '+n+' "'+edTrName(tipo)+'" attorno alle basi, team del proprietario (patch ENG). Trascinale per rifinire.';
}
function edFillModels(){
  const l=LV[cur], s=document.getElementById('ed_mdl');
  if(s.dataset.entry===l.entry)return;
  s.dataset.entry=l.entry;
  s.innerHTML=l.models.map((n,i)=>`<option value="${i}">${n||('#'+i)}</option>`).join('');
}
async function edSave(){
  const l=LV[cur], st=edState();
  const edits={
    s0:st.s0.map(p=>p.map(v=>tos16e(v)/256)),
    s6:{extra:st.s6.extra,records:st.s6.records.map(r=>[r[0],r[1],r[2],tos16e(r[3])/256,tos16e(r[4])/256])},
    instFull:st.inst
  };
  if(st.s3.length)edits.s3=st.s3;
  if(st.zcfgTouched)edits.zoneCfg=st.zcfg;   // scrive LEVELS.BIN (mods/0955)
  if(edRec.touched)edits.recipes={set:edRec.set,pairs:edRec.pairs};  // BIND 0953
  if(st.tcountTouched)edits.teamCount=st.tcount;                     // entry 0956+0003
  if(st.extra)edits.extra=st.extra;
  const r=await fetch('/api/save',{method:'POST',body:JSON.stringify({entry:l.entry,edits})});
  const j=await r.json();
  document.getElementById('edlog').textContent=j.ok?'✓ salvato in mods/'+l.entry+(j.recipes?' (+ricette set '+j.recipes.set+')':''):('ERRORE: '+(j.err||''));
  if(j.ok){edDirty=false;if(j.recipes)edRec.touched=false;}edStatus();
}
async function edBuild(){
  document.getElementById('edlog').textContent='compilo...';
  const r=await fetch('/api/build',{method:'POST',body:'{}'});
  const j=await r.json();
  document.getElementById('edlog').textContent=(j.ok?'✓ ISO pronta (rebuild.cue)':'ERRORE')+'\n'+(j.log||[]).join('\n');
}
function edZRawSync(){
  const box=document.getElementById('ed_zraw');
  if(!edSel||edSel.k!=='cz'){box.style.display='none';return;}
  box.style.display='';
  const c=edState().zcfg[edSel.i];
  for(let k=0;k<10;k++)document.getElementById('ed_zc'+k).value=c?c[k]:'';
}
function edStatus(){
  let txt=edSel?('selezionato: '+edSel.lbl):'niente selezionato';
  if(edSel&&edSel.k==='cz'){
    const st=edState(), name=edZoneCfgName(st.zcfg[edSel.i]);
    txt+=' — casse: '+name;
    const s=document.getElementById('ed_zpre');
    if(ED_ZPRESETS[name]!==undefined)s.value=name;
  }
  edZRawSync();
  {const st=edState(), s=document.getElementById('ed_mteams');
   if(st.tcount!==null&&s.value!==String(st.tcount))s.value=String(st.tcount);}
  if(edSel&&edSel.k==='tr'){
    const it=edItems().find(o=>o.k==='tr'&&o.i===edSel.i);
    const st=edState(), rec=st.extra[edSel.i], tipo=rec[5], f8=rec[8]||0;
    document.getElementById('ed_trteam').value=String(f8<=4?f8:0);
    if(f8>0)txt+=` → TEAM ${f8} FORZATO (via patch ENG)`;
    else if(edIsAuto(tipo))txt+=' ⚠ AUTO senza team: in pratica ostile al giocatore — imposta un team qui a destra';
    else{
      const ow=it&&edOwner(it);
      txt+=ow?` → base più vicina: TEAM ${ow.team+1} (da verificare in gioco)`:' → nessuna base: proprietà indefinita';
    }
  }
  document.getElementById('edsel').textContent=txt;
  document.getElementById('eddirty').textContent=edDirty?'● modifiche non salvate':'';
}
{
  const div=document.createElement('div');
  const s6opts=Array.from({length:62},(_,i)=>`<option value="${i}">${i} — ${ED_NAMES[i]||'?'}</option>`).join('');
  div.innerHTML=`<h3>Editor</h3>
  <label><input type="checkbox" id="ck_edit"> Modalità modifica (trascina i punti)</label>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0;align-items:center">
    <select id="ed_s6t" title="tipo unità (spazio-62; ? = da catalogare in gioco)">${s6opts}</select>
    <select id="ed_s6team"><option value="0">team 1</option><option value="1">team 2</option>
      <option value="2">team 3</option><option value="3">team 4</option></select>
    <button id="bt_unit">+ unità</button>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0;align-items:center">
    <select id="ed_mdl" title="modelli del livello (PND)"></select>
    <button id="bt_obj">+ oggetto</button>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0;align-items:center">
    <select id="ed_extra" title="torrette/oggetti speciali (lista extra PND = STATICS.BIN)"></select>
    <button id="bt_tr">+ torretta/speciale</button>
    <select id="ed_trteam" title="team dell'oggetto extra selezionato (campo f8, richiede ENG patchato)">
      <option value="0">team: auto (vanilla)</option><option value="1">team 1 (P1)</option>
      <option value="2">team 2</option><option value="3">team 3</option><option value="4">team 4</option>
    </select>
    <button id="bt_def" title="2 torrette del tipo selezionato attorno a ogni base, col team del proprietario">🛡 difese basi</button>
  </div>
  <details style="margin:6px 0">
    <summary style="cursor:pointer">📦 ricette casse — set <span id="ed_rsetlbl"></span></summary>
    <div style="margin:4px 0"><select id="ed_rset" title="set di ricette (il livello selezionato usa quello evidenziato)"></select></div>
    <div id="ed_ruse" style="color:#8b93a1;font-size:11px"></div>
    <div id="ed_rrows"></div>
  </details>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0">
    <button id="bt_team" title="pedana s0 + base + bandiera clonate; il n. di team effettivo dipende dallo slot livello">➕ team (pedana+base)</button>
    <select id="ed_mteams" title="numero di squadre della MISSIONE (config 0956+0003, niente slot-swap); il count s0 resta il tetto: servono altrettante pedane. >4 sperimentale"></select>
    <button id="bt_zone" title="zona di lancio casse (s3): la consegna va sempre alla zona più vicina al richiedente">📦 zona casse</button>
    <button id="bt_dup">duplica selez.</button><button id="bt_del">elimina selez.</button>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0;align-items:center">
    <select id="ed_zpre" title="contenuto/ritmo casse della zona selezionata (LEVELS.BIN per-missione; tipo = ricetta 1-6 dell'area)"></select>
    <button id="bt_zcfg">casse → zona selez.</button>
  </div>
  <div id="ed_zraw" style="display:none;margin:2px 0 6px 0;font-size:11px">
    <div style="color:#8b93a1">valori zona selezionata (vanilla spesso su misura): tipo=ricetta 1-6/8/10, tgt −30=infinito</div>
    <div style="display:grid;grid-template-columns:38px repeat(5,1fr);gap:2px;align-items:center">
      <span></span><span style="color:#8b93a1">tipo</span><span style="color:#8b93a1">init</span><span style="color:#8b93a1">tgt</span><span style="color:#8b93a1">rate</span><span style="color:#8b93a1">a</span>
      <span style="color:#8b93a1">slot A</span>
      <input id="ed_zc0" type="number" style="width:100%"><input id="ed_zc2" type="number" style="width:100%"><input id="ed_zc4" type="number" style="width:100%"><input id="ed_zc6" type="number" style="width:100%"><input id="ed_zc8" type="number" style="width:100%">
      <span style="color:#8b93a1">slot B</span>
      <input id="ed_zc1" type="number" style="width:100%"><input id="ed_zc3" type="number" style="width:100%"><input id="ed_zc5" type="number" style="width:100%"><input id="ed_zc7" type="number" style="width:100%"><input id="ed_zc9" type="number" style="width:100%">
    </div>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0">
    <button id="bt_save">💾 salva livello</button><button id="bt_build">🔨 compila ISO</button>
  </div>
  <div id="edsel" style="color:#8b93a1"></div><div id="eddirty" style="color:#ffa502"></div>
  <pre id="edlog" style="white-space:pre-wrap;font-size:11px;color:#8b93a1"></pre>`;
  document.getElementById('side').insertBefore(div,document.getElementById('side').children[1]);
  document.getElementById('ck_edit').onchange=e=>{edMode=e.target.checked;edFillModels();edFillExtra();edStatus();draw();};
  document.getElementById('ed_trteam').onchange=e=>{
    if(!edSel||edSel.k!=='tr')return;
    edState().extra[edSel.i][8]=+e.target.value;
    edDirty=true;edStatus();
  };
  document.getElementById('ed_mdl').addEventListener('focus',edFillModels);
  document.getElementById('bt_def').onclick=edAddDefenses;
  document.getElementById('bt_team').onclick=edAddTeam;
  {const s=document.getElementById('ed_mteams');
   s.innerHTML=[1,2,3,4,5,6,7,8].map(n=>`<option value="${n}">team missione: ${n}${n>4?' ⚠':''}</option>`).join('');
   s.onchange=()=>{const st=edState();st.tcount=+s.value;st.tcountTouched=true;edDirty=true;edStatus();
     document.getElementById('edlog').textContent='missione a '+s.value+' team al prossimo salvataggio (ricorda: servono '+s.value+' pedane s0 e idealmente '+s.value+' zone casse).';};}
  document.getElementById('bt_zone').onclick=edAddZone;
  {const s=document.getElementById('ed_zpre');
   s.innerHTML=Object.keys(ED_ZPRESETS).map(k=>`<option>${k}</option>`).join('');}
  document.getElementById('bt_zcfg').onclick=edApplyZoneCfg;
  for(let k=0;k<10;k++)document.getElementById('ed_zc'+k).onchange=()=>{
    if(!edSel||edSel.k!=='cz')return;
    const st=edState();
    if(!st.zcfg[edSel.i]){ // zona a default motore: materializza partendo da "standard"
      st.zcfg[edSel.i]=ED_ZPRESETS['standard (t3, ogni 150)'].slice();
      for(let j=0;j<edSel.i;j++)if(!st.zcfg[j])st.zcfg[j]=ED_ZPRESETS['standard (t3, ogni 150)'].slice();
    }
    for(let j=0;j<10;j++){
      const v=parseInt(document.getElementById('ed_zc'+j).value,10);
      if(!isNaN(v))st.zcfg[edSel.i][j]=v;
    }
    st.zcfgTouched=true;edDirty=true;edStatus();
  };
  {const s=document.getElementById('ed_rset');
   s.innerHTML=Object.keys(ED_RECIPES).map(n=>`<option value="${n}">${n}${ED_RECIPES[n].name?' — '+ED_RECIPES[n].name:''}</option>`).join('');
   s.onchange=()=>{if(edRec.touched&&!confirm('Ricette modificate non salvate per il set '+edRec.set+': le scarto?'))
     {s.value=String(edRec.set);return;}
     edRecLoad(s.value);};
   edRecLoad(0);}
  document.getElementById('bt_unit').onclick=edAddUnit;
  document.getElementById('bt_obj').onclick=edAddObj;
  document.getElementById('bt_tr').onclick=edAddExtra;
  document.getElementById('bt_dup').onclick=edDup;
  document.getElementById('bt_del').onclick=edDel;
  document.getElementById('bt_save').onclick=edSave;
  document.getElementById('bt_build').onclick=edBuild;
  const style=document.createElement('style');
  style.textContent='button{background:#2d3440;color:#fff;border:1px solid #3a3f4a;border-radius:6px;padding:4px 8px;cursor:pointer}button:hover{background:#3a4250}'+
    'select{background:#2d3440;color:#fff;border:1px solid #3a3f4a;border-radius:6px;padding:3px 6px;max-width:180px}';
  document.head.appendChild(style);
}
"""

# ============================ VISTA 3D (WebGL) ============================
# Renderer senza dipendenze: terreno da heightmap 65x65 + texture tile,
# modelli .LOD reali (via /api/3d del server), gizmo per pedane/unita'/zone,
# picking con raycast in coordinate mondo ESATTE (niente tarature empiriche).
# Tutto vive nello SPAZIO-V del motore (tile 0-64: Vx=x_inst/8, Vz=64-z_inst/8),
# lo stesso di claiming/visuale verificato da savestate.
ED3JS = r"""
// ============== VISTA 3D ==============
(function(){
const TCOLS=[[231,76,60],[52,152,219],[46,204,113],[241,196,15],[155,89,182],[230,126,34],[26,188,156],[149,165,166]];
const ED3={on:false,gl:null,cv:null,entry:null,lvl:null,terr:null,models:null,texs:{},ground:null,
  cam:{yaw:parseFloat(localStorage.ed3yaw||'2.356'),pitch:parseFloat(localStorage.ed3pitch||'0.85'),
       dist:parseFloat(localStorage.ed3dist||'46'),tx:32,tz:32},
  hdiv:parseInt(localStorage.ed3hdiv||'512'),drag:null,last:null,msg:'',raf:0};
window.ED3=ED3;   // handle di debug (console)

// ---------- UI ----------
{
  const div=document.createElement('div');
  div.innerHTML=`<label><input type="checkbox" id="ck_3d"> <b>🧊 vista 3D</b> (modelli reali, click = coordinate esatte)</label>
  <div id="ed3bar" style="display:none;gap:6px;flex-wrap:wrap;margin:4px 0;align-items:center">
    <button id="e3_rotl" title="ruota vista a sinistra">⟲</button>
    <button id="e3_rotr" title="ruota vista a destra">⟳</button>
    <select id="e3_h" title="scala verticale del terreno">
      <option value="512">quota /512</option><option value="256">quota /256</option>
      <option value="128">quota /128</option><option value="64">quota /64</option></select>
    <span style="color:#8b93a1;font-size:11px">trascina: ruota · shift/tasto centrale: sposta · rotella: zoom · click su un marker: seleziona e trascina</span>
  </div>`;
  const side=document.getElementById('side');
  side.insertBefore(div,side.children[1]);
  document.getElementById('e3_h').value=String(ED3.hdiv);
  document.getElementById('ck_3d').onchange=e=>{ed3Toggle(e.target.checked)};
  document.getElementById('e3_rotl').onclick=()=>{ED3.cam.yaw+=Math.PI/2;ed3SaveCam()};
  document.getElementById('e3_rotr').onclick=()=>{ED3.cam.yaw-=Math.PI/2;ed3SaveCam()};
  document.getElementById('e3_h').onchange=e=>{ED3.hdiv=+e.target.value;localStorage.ed3hdiv=e.target.value;
    if(ED3.lvl)ed3BuildTerrain();};
}
function ed3SaveCam(){localStorage.ed3yaw=ED3.cam.yaw;localStorage.ed3pitch=ED3.cam.pitch;localStorage.ed3dist=ED3.cam.dist;}

function ed3Toggle(on){
  ED3.on=on;
  document.getElementById('ed3bar').style.display=on?'flex':'none';
  if(on&&!ED3.cv)ed3Init();
  if(ED3.cv)ED3.cv.style.display=on?'block':'none';
  if(ED3.info)ED3.info.style.display=on?'block':'none';
  cv.style.display=on?'none':'block';
  if(on){ed3Load();ed3Frame();}
}

function ed3Init(){
  const main=document.getElementById('main');
  main.style.position='relative';
  const c=document.createElement('canvas');
  c.id='cv3';c.style.cssText='position:absolute;inset:0;width:100%;height:100%;display:none';
  main.appendChild(c);
  const info=document.createElement('div');
  info.id='info3';
  info.style.cssText='position:absolute;left:10px;bottom:10px;background:#000b;padding:6px 10px;border-radius:6px;font:12px ui-monospace,monospace;pointer-events:none;display:none;white-space:pre';
  main.appendChild(info);
  ED3.cv=c;ED3.info=info;
  const gl=c.getContext('webgl',{antialias:true});
  ED3.gl=gl;
  const vs=`attribute vec3 aP;attribute vec3 aN;attribute vec2 aU;
    uniform mat4 uVP;uniform vec3 uT;uniform float uRot;uniform float uMx;
    varying vec2 vU;varying vec3 vN;varying float vD;
    void main(){float cr=cos(uRot),sr=sin(uRot);
    vec3 q=vec3(aP.x*uMx,aP.y,aP.z);
    vec3 m=vec3(aN.x*uMx,aN.y,aN.z);
    vec3 p=vec3(q.x*cr-q.z*sr,q.y,q.x*sr+q.z*cr)+uT;
    vec3 n=vec3(m.x*cr-m.z*sr,m.y,m.x*sr+m.z*cr);
    vU=aU;vN=n;gl_Position=uVP*vec4(p,1.0);vD=gl_Position.w;}`;
  const fs=`precision mediump float;
    uniform bool uTexOn;uniform sampler2D uTex;uniform vec4 uCol;uniform float uLit;
    varying vec2 vU;varying vec3 vN;varying float vD;
    void main(){vec4 c=uCol;
    if(uTexOn){vec4 t=texture2D(uTex,vU);if(t.a<0.5)discard;c=vec4(c.rgb*t.rgb,c.a);}
    if(uLit>0.5){vec3 L=normalize(vec3(0.35,0.8,0.5));
      float l=0.58+0.42*max(dot(normalize(vN),L),0.0);c=vec4(c.rgb*l,c.a);}
    gl_FragColor=c;}`;
  function sh(t,s){const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);
    if(!gl.getShaderParameter(x,gl.COMPILE_STATUS))console.error(gl.getShaderInfoLog(x));return x;}
  const pr=gl.createProgram();
  gl.attachShader(pr,sh(gl.VERTEX_SHADER,vs));gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,fs));
  gl.linkProgram(pr);gl.useProgram(pr);
  ED3.pr=pr;
  ED3.loc={aP:gl.getAttribLocation(pr,'aP'),aN:gl.getAttribLocation(pr,'aN'),aU:gl.getAttribLocation(pr,'aU'),
    uVP:gl.getUniformLocation(pr,'uVP'),uT:gl.getUniformLocation(pr,'uT'),uRot:gl.getUniformLocation(pr,'uRot'),
    uTexOn:gl.getUniformLocation(pr,'uTexOn'),uCol:gl.getUniformLocation(pr,'uCol'),uLit:gl.getUniformLocation(pr,'uLit'),
    uMx:gl.getUniformLocation(pr,'uMx')};
  gl.enable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);          // mesh PSX non chiuse: due facce
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  ED3.gizmo={box:ed3Mesh(ed3Box()),cone:ed3Mesh(ed3Cone(10)),cyl:ed3Mesh(ed3Cyl(10))};
  ed3Input();
}

// ---------- geometrie gizmo (tri-soup interleaved p3 n3 u2) ----------
function ed3Box(){const v=[],q=(a,b,c,d,n)=>{[a,b,c,a,c,d].forEach(p=>v.push(p[0],p[1],p[2],n[0],n[1],n[2],0,0))};
  const p=[[-.5,0,-.5],[.5,0,-.5],[.5,0,.5],[-.5,0,.5],[-.5,1,-.5],[.5,1,-.5],[.5,1,.5],[-.5,1,.5]];
  q(p[0],p[1],p[2],p[3],[0,-1,0]);q(p[4],p[7],p[6],p[5],[0,1,0]);
  q(p[0],p[4],p[5],p[1],[0,0,-1]);q(p[3],p[2],p[6],p[7],[0,0,1]);
  q(p[0],p[3],p[7],p[4],[-1,0,0]);q(p[1],p[5],p[6],p[2],[1,0,0]);return v;}
function ed3Cone(n){const v=[];for(let i=0;i<n;i++){const a=i/n*6.2832,b=(i+1)/n*6.2832;
  const x1=Math.cos(a)*.5,z1=Math.sin(a)*.5,x2=Math.cos(b)*.5,z2=Math.sin(b)*.5;
  v.push(0,1,0,0,1,0,0,0, x1,0,z1,x1,0,z1,0,0, x2,0,z2,x2,0,z2,0,0);
  v.push(0,0,0,0,-1,0,0,0, x2,0,z2,0,-1,0,0,0, x1,0,z1,0,-1,0,0,0);}return v;}
function ed3Cyl(n){const v=[];for(let i=0;i<n;i++){const a=i/n*6.2832,b=(i+1)/n*6.2832;
  const x1=Math.cos(a)*.5,z1=Math.sin(a)*.5,x2=Math.cos(b)*.5,z2=Math.sin(b)*.5;
  v.push(x1,0,z1,x1,0,z1,0,0, x1,1,z1,x1,0,z1,0,0, x2,1,z2,x2,0,z2,0,0);
  v.push(x1,0,z1,x1,0,z1,0,0, x2,1,z2,x2,0,z2,0,0, x2,0,z2,x2,0,z2,0,0);
  v.push(0,1,0,0,1,0,0,0, x1,1,z1,0,1,0,0,0, x2,1,z2,0,1,0,0,0);}return v;}
function ed3Mesh(arr){const gl=ED3.gl,b=gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(arr),gl.STATIC_DRAW);
  return {vbo:b,n:arr.length/8};}

// ---------- livello ----------
function ed3Load(){
  const l=LV[cur];
  if(ED3.entry===l.entry)return;
  ED3.entry=l.entry;ED3.lvl=l;ED3.models=null;ED3.ground=null;ED3.texs={};
  ed3BuildTerrain();
  // texture terreno hi-res dal server (fallback: PNG embedded)
  const img=new Image();
  img.onload=()=>{if(ED3.entry===l.entry)ED3.ground=ed3Tex(img,true)};
  img.onerror=()=>{if(!l.ground)return;const im2=new Image();
    im2.onload=()=>{if(ED3.entry===l.entry)ED3.ground=ed3Tex(im2,true)};
    im2.src='data:image/png;base64,'+l.ground;};
  img.src='/ground3d/'+l.entry+'.png?v='+Date.now();
  fetch('/api/3d/'+l.entry).then(r=>r.json()).then(j=>{
    if(ED3.entry!==l.entry||!j.models)return;
    const gl=ED3.gl;
    for(const[name,uri]of Object.entries(j.tex||{})){
      const im=new Image();
      im.onload=()=>{ED3.texs[name]=ed3Tex(im,false)};
      im.src=uri;
    }
    ED3.models={};
    for(const[name,batches]of Object.entries(j.models)){
      ED3.models[name]=batches.map(b=>{
        const n=b.p.length/3,arr=new Float32Array(n*8);
        for(let i=0;i<n;i++){arr.set([b.p[3*i],b.p[3*i+1],b.p[3*i+2],b.n[3*i],b.n[3*i+1],b.n[3*i+2],b.u[2*i],b.u[2*i+1]],i*8);}
        const vbo=gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER,vbo);gl.bufferData(gl.ARRAY_BUFFER,arr,gl.STATIC_DRAW);
        return {vbo,n,tex:b.t,col:[b.c[0]/128,b.c[1]/128,b.c[2]/128,1]};
      });
    }
    ED3.msg='';
  }).catch(()=>{ED3.msg='modelli 3D non disponibili (serve il server: python3 tools/editor_server.py)'});
}
function ed3Tex(img,ground){
  const gl=ED3.gl,t=gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D,t);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,img);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,ground?gl.LINEAR:gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,ground?gl.LINEAR:gl.NEAREST);
  return t;
}
function ed3BuildTerrain(){
  const l=ED3.lvl,gl=ED3.gl;
  const hm=b64i16(l.hm);
  ED3.hm=hm;
  const P=new Float32Array(65*65*8);
  for(let j=0;j<=64;j++)for(let i=0;i<=64;i++){
    const o=(j*65+i)*8;
    P[o]=i;P[o+1]=hm[j*65+i]/ED3.hdiv;P[o+2]=j;
    P[o+3]=0;P[o+4]=1;P[o+5]=0;
    // il PNG del terreno e' NELLO STESSO spazio di s0/heightmap (riga=z, col=x):
    // verificato coi tile dipinti delle pedane (pedana A = quadrato blu a (39,38))
    P[o+6]=i/64;P[o+7]=j/64;
  }
  const I=new Uint16Array(64*64*6);
  let k=0;
  for(let j=0;j<64;j++)for(let i=0;i<64;i++){
    const a=j*65+i,b=a+1,c=a+65,d=a+66;
    I[k++]=a;I[k++]=b;I[k++]=c;I[k++]=b;I[k++]=d;I[k++]=c;
  }
  if(ED3.terr){gl.deleteBuffer(ED3.terr.vbo);gl.deleteBuffer(ED3.terr.ibo);}
  const vbo=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,vbo);gl.bufferData(gl.ARRAY_BUFFER,P,gl.STATIC_DRAW);
  const ibo=gl.createBuffer();gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,ibo);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,I,gl.STATIC_DRAW);
  ED3.terr={vbo,ibo,n:I.length};
}
function hAt(tx,tz){
  const hm=ED3.hm;if(!hm)return 0;
  const x=Math.max(0,Math.min(63.999,tx)),z=Math.max(0,Math.min(63.999,tz));
  const i=x|0,j=z|0,fx=x-i,fz=z-j;
  return (hm[j*65+i]*(1-fx)*(1-fz)+hm[j*65+i+1]*fx*(1-fz)
         +hm[(j+1)*65+i]*(1-fx)*fz+hm[(j+1)*65+i+1]*fx*fz)/ED3.hdiv;
}

// ---------- matrici ----------
function mMul(a,b){const o=new Float32Array(16);
  for(let r=0;r<4;r++)for(let c=0;c<4;c++){let s=0;for(let k=0;k<4;k++)s+=a[k*4+c]*b[r*4+k];o[r*4+c]=s;}return o;}
function ed3VP(w,h){
  const c=ED3.cam;
  const ex=c.tx+c.dist*Math.cos(c.pitch)*Math.sin(c.yaw);
  const ey=Math.max(1,c.dist*Math.sin(c.pitch));
  const ez=c.tz+c.dist*Math.cos(c.pitch)*Math.cos(c.yaw);
  const f=[c.tx-ex,0-ey,c.tz-ez];
  const fl=Math.hypot(...f);f[0]/=fl;f[1]/=fl;f[2]/=fl;
  const up=[0,1,0];
  const s=[f[1]*up[2]-f[2]*up[1],f[2]*up[0]-f[0]*up[2],f[0]*up[1]-f[1]*up[0]];
  const sl=Math.hypot(...s);s[0]/=sl;s[1]/=sl;s[2]/=sl;
  const u=[s[1]*f[2]-s[2]*f[1],s[2]*f[0]-s[0]*f[2],s[0]*f[1]-s[1]*f[0]];
  const V=new Float32Array([s[0],u[0],-f[0],0, s[1],u[1],-f[1],0, s[2],u[2],-f[2],0,
    -(s[0]*ex+s[1]*ey+s[2]*ez),-(u[0]*ex+u[1]*ey+u[2]*ez),(f[0]*ex+f[1]*ey+f[2]*ez),1]);
  const fov=0.9,n=0.5,fa=600,t=Math.tan(fov/2),a=w/h;
  const p=new Float32Array([1/(t*a),0,0,0, 0,1/t,0,0, 0,0,-(fa+n)/(fa-n),-1, 0,0,-2*fa*n/(fa-n),0]);
  ED3.eye=[ex,ey,ez];ED3.fwd=f;ED3.right=s;ED3.up=u;ED3.tanF=t;ED3.aspect=a;
  return mMul(p,V);
}
function ed3Project(p,vp,w,h){
  const x=p[0],y=p[1],z=p[2];
  const cx=vp[0]*x+vp[4]*y+vp[8]*z+vp[12];
  const cy=vp[1]*x+vp[5]*y+vp[9]*z+vp[13];
  const cw=vp[3]*x+vp[7]*y+vp[11]*z+vp[15];
  if(cw<=0)return null;
  return [(cx/cw*.5+.5)*w,(1-(cy/cw*.5+.5))*h,cw];
}
function ed3Ray(mx,my,w,h){
  const nx=mx/w*2-1,ny=1-my/h*2;
  const d=[ED3.fwd[0]+nx*ED3.tanF*ED3.aspect*ED3.right[0]+ny*ED3.tanF*ED3.up[0],
           ED3.fwd[1]+nx*ED3.tanF*ED3.aspect*ED3.right[1]+ny*ED3.tanF*ED3.up[1],
           ED3.fwd[2]+nx*ED3.tanF*ED3.aspect*ED3.right[2]+ny*ED3.tanF*ED3.up[2]];
  const l=Math.hypot(...d);return [d[0]/l,d[1]/l,d[2]/l];
}
function ed3Ground(mx,my,w,h,planeY){
  const d=ed3Ray(mx,my,w,h),e=ED3.eye;
  let y=planeY!==undefined?planeY:0;
  for(let i=0;i<4;i++){
    if(Math.abs(d[1])<1e-4)break;
    const t=(y-e[1])/d[1];
    if(t<0)return null;
    const px=e[0]+d[0]*t,pz=e[2]+d[2]*t;
    if(planeY!==undefined)return [px,pz];
    y=hAt(px,pz);
    if(i===3)return [px,pz];
  }
  const t=(y-e[1])/d[1];
  return t>0?[e[0]+d[0]*t,e[2]+d[2]*t]:null;
}

// ---------- items in spazio-V (tile) ----------
function edItems3(){
  const st=edState(),l=LV[cur],out=[];
  st.s0.forEach((p,i)=>out.push({k:'s0',i,tx:32+tos16e(p[0])/512,tz:32+tos16e(p[1])/512,lbl:'pedana/spawn '+(i+1)}));
  st.s3.forEach((p,i)=>out.push({k:'cz',i,tx:p[0],tz:p[1],lbl:'zona casse '+(i+1)}));
  st.s6.records.forEach((r,i)=>out.push({k:'s6',i,tx:32+tos16e(r[3])/512,tz:32+tos16e(r[4])/512,
    lbl:(ED_NAMES[r[0]]||('tipo '+r[0]))+' (team '+(r[1]+1)+')'}));
  if(st.extra)st.extra.forEach((r,i)=>out.push({k:'tr',i,tx:r[2]/8,tz:64-r[4]/8,rot:r[7],lbl:edTrName(r[5])}));
  // istanze nello spazio tile/s0 (ancorato ai tile dipinti delle pedane,
  // verificati in gioco): x SPECCHIATA rispetto al dato, z diretta.
  // (le torrette sopra hanno la convenzione opposta: z specchiata)
  st.inst.forEach((r,i)=>out.push({k:'in',i,tx:64-r[1]/8,tz:r[3]/8,alt:r[2],rot:r[5],m:r[0],
    lbl:l.models[r[0]]||('#'+r[0])}));
  return out;
}
function applyMove3(it,tx,tz){
  const st=edState();
  const raw=v=>Math.round((v-32)*512)&0xffff;
  if(it.k==='s0'){st.s0[it.i][0]=snapOdd(raw(tx));st.s0[it.i][1]=snapOdd(raw(tz));}
  else if(it.k==='cz'){st.s3[it.i][0]=Math.max(4,Math.min(59,Math.round(tx)));
    st.s3[it.i][1]=Math.max(4,Math.min(59,Math.round(tz)));}
  else if(it.k==='s6'){st.s6.records[it.i][3]=raw(tx);st.s6.records[it.i][4]=raw(tz);}
  else if(it.k==='tr'){st.extra[it.i][2]=Math.round(8*tx)&0xffff;st.extra[it.i][4]=Math.round(512-8*tz)&0xffff;}
  else if(it.k==='in'){st.inst[it.i][1]=Math.round(512-8*tx);st.inst[it.i][3]=Math.round(8*tz);}
  edDirty=true;edStatus();draw();
}

// ---------- render ----------
function ed3DrawMesh(mesh,tx,ty,tz,rot,col,tex,lit,mx){
  const gl=ED3.gl,L=ED3.loc;
  gl.bindBuffer(gl.ARRAY_BUFFER,mesh.vbo);
  gl.vertexAttribPointer(L.aP,3,gl.FLOAT,false,32,0);
  gl.vertexAttribPointer(L.aN,3,gl.FLOAT,false,32,12);
  gl.vertexAttribPointer(L.aU,2,gl.FLOAT,false,32,24);
  gl.uniform3f(L.uT,tx,ty,tz);
  gl.uniform1f(L.uRot,rot||0);
  gl.uniform1f(L.uMx,mx||1);
  gl.uniform4fv(L.uCol,col);
  gl.uniform1f(L.uLit,lit?1:0);
  if(tex){gl.uniform1i(L.uTexOn,1);gl.bindTexture(gl.TEXTURE_2D,tex);}
  else gl.uniform1i(L.uTexOn,0);
  gl.drawArrays(gl.TRIANGLES,0,mesh.n);
}
function ed3Quad(cx,cz,half,col,y0){
  // quad drappeggiato sul terreno (griglia 4x4 campioni)
  const gl=ED3.gl,L=ED3.loc,N=4,v=[];
  for(let j=0;j<N;j++)for(let i=0;i<N;i++){
    const x0=cx-half+2*half*i/N,x1=cx-half+2*half*(i+1)/N;
    const z0=cz-half+2*half*j/N,z1=cz-half+2*half*(j+1)/N;
    const q=[[x0,z0],[x1,z0],[x1,z1],[x0,z1]];
    [q[0],q[1],q[2],q[0],q[2],q[3]].forEach(p=>v.push(p[0],hAt(p[0],p[1])+(y0||0.06),p[1],0,1,0,0,0));
  }
  const b=gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(v),gl.STREAM_DRAW);
  gl.vertexAttribPointer(L.aP,3,gl.FLOAT,false,32,0);
  gl.vertexAttribPointer(L.aN,3,gl.FLOAT,false,32,12);
  gl.vertexAttribPointer(L.aU,2,gl.FLOAT,false,32,24);
  gl.uniform3f(L.uT,0,0,0);gl.uniform1f(L.uRot,0);
  gl.uniform4fv(L.uCol,col);gl.uniform1f(L.uLit,0);gl.uniform1i(L.uTexOn,0);
  gl.drawArrays(gl.TRIANGLES,0,v.length/8);
  gl.deleteBuffer(b);
}
function ed3Frame(){
  if(!ED3.on)return;
  ED3.raf=requestAnimationFrame(ed3Frame);
  ed3Render();
}
// tick di sicurezza: alcuni browser/tab in background congelano il RAF
setInterval(()=>{if(ED3.on&&ED3.gl)try{ed3Render()}catch(e){console.error(e)}},250);
function ed3Render(){
  const gl=ED3.gl,L=ED3.loc,c=ED3.cv;
  if(ED3.entry!==LV[cur].entry)ed3Load();
  const w=c.clientWidth,h=c.clientHeight,dpr=window.devicePixelRatio||1;
  if(c.width!==w*dpr||c.height!==h*dpr){c.width=w*dpr;c.height=h*dpr;}
  gl.viewport(0,0,c.width,c.height);
  gl.clearColor(0.075,0.08,0.10,1);
  gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  const vp=ed3VP(w,h);
  gl.uniformMatrix4fv(L.uVP,false,vp);
  ED3.vp=vp;
  gl.enableVertexAttribArray(L.aP);gl.enableVertexAttribArray(L.aN);gl.enableVertexAttribArray(L.aU);
  // terreno
  if(ED3.terr){
    gl.bindBuffer(gl.ARRAY_BUFFER,ED3.terr.vbo);
    gl.vertexAttribPointer(L.aP,3,gl.FLOAT,false,32,0);
    gl.vertexAttribPointer(L.aN,3,gl.FLOAT,false,32,12);
    gl.vertexAttribPointer(L.aU,2,gl.FLOAT,false,32,24);
    gl.uniform3f(L.uT,0,0,0);gl.uniform1f(L.uRot,0);gl.uniform1f(L.uLit,0);
    gl.uniform4f(L.uCol,1,1,1,1);
    if(ED3.ground){gl.uniform1i(L.uTexOn,1);gl.bindTexture(gl.TEXTURE_2D,ED3.ground);}
    else{gl.uniform1i(L.uTexOn,0);gl.uniform4f(L.uCol,0.22,0.28,0.2,1);}
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,ED3.terr.ibo);
    gl.drawElements(gl.TRIANGLES,ED3.terr.n,gl.UNSIGNED_SHORT,0);
  }
  const items=edItems3();
  // istanze: modelli reali
  for(const it of items){
    if(it.k!=='in')continue;
    const name=(ED3.lvl.models[it.m]||'').toUpperCase();
    const mesh=ED3.models&&ED3.models[name];
    const y=(it.alt||0)/ED3.hdiv;
    // spazio istanze specchiato in x -> geometria specchiata e rotazione invertita
    const yaw=((it.rot>>16)/4096)*6.2832;
    if(mesh)for(const b of mesh)
      ed3DrawMesh(b,it.tx,y,it.tz,yaw,b.col,b.tex?ED3.texs[b.tex]:null,true,-1);
    else ed3DrawMesh(ED3.gizmo.box,it.tx,y,it.tz,yaw,[0.55,0.55,0.6,1],null,true,-1);
  }
  // gizmo sopra il terreno
  for(const it of items){
    const seld=edSel&&edSel.k===it.k&&edSel.i===it.i;
    if(it.k==='s0'){
      const tc=TCOLS[it.i%TCOLS.length];
      ed3Quad(it.tx,it.tz,2,[tc[0]/255,tc[1]/255,tc[2]/255,seld?0.75:0.45],0.06);
    }else if(it.k==='cz'){
      ed3Quad(it.tx,it.tz,4,[1,0.62,0.1,seld?0.5:0.22],0.045);
    }else if(it.k==='s6'){
      const y=hAt(it.tx,it.tz);
      ed3DrawMesh(ED3.gizmo.cone,it.tx,y,it.tz,0,[0.98,0.79,0.14,seld?1:0.85],null,true);
    }else if(it.k==='tr'){
      const y=hAt(it.tx,it.tz);
      const yaw=(((4096-(it.rot&4095))&4095)/4096)*6.2832;
      ed3DrawMesh(ED3.gizmo.cyl,it.tx,y,it.tz,yaw,[0,0.82,0.83,seld?1:0.85],null,true);
    }
  }
  // fascio di selezione
  if(edSel){
    const it=items.find(o=>o.k===edSel.k&&o.i===edSel.i);
    if(it){
      const y=hAt(it.tx,it.tz);
      ed3DrawMesh(ED3.gizmo.box,it.tx,y,it.tz,0,[1,1,1,0.35],null,false);
      gl.depthMask(false);
      ed3DrawMesh(ED3.gizmo.cyl,it.tx,y,it.tz,0,[1,1,1,0.18],null,false);
      gl.depthMask(true);
    }
  }
  ed3Info();
}
function ed3Info(){
  const m=ED3.last;
  let txt='';
  if(m){
    const g=ed3Ground(m[0],m[1],ED3.cv.clientWidth,ED3.cv.clientHeight);
    if(g){
      const [tx,tz]=g;
      txt=`tile (${tx.toFixed(2)}, ${tz.toFixed(2)})  V-dato x=${(tx*8).toFixed(0)} z=${(512-tz*8).toFixed(0)}  centroRel mezzi-tile (${((tx-32)*2).toFixed(1)}, ${((tz-32)*2).toFixed(1)})  h=${hAt(tx,tz).toFixed(2)}`;
    }
  }
  if(ED3.hover)txt+=`\n→ ${ED3.hover.lbl}`;
  if(ED3.msg)txt+='\n'+ED3.msg;
  ED3.info.textContent=txt;
}

// ---------- input ----------
function ed3Pick(mx,my){
  const w=ED3.cv.clientWidth,h=ED3.cv.clientHeight;
  let best=null,bd=26;
  for(const it of edItems3()){
    const y=it.k==='in'?(it.alt||0)/ED3.hdiv:hAt(it.tx,it.tz);
    const p=ed3Project([it.tx,y+0.4,it.tz],ED3.vp,w,h);
    if(!p)continue;
    const d=Math.hypot(p[0]-mx,p[1]-my)*(it.k==='in'?1.25:1);
    if(d<bd){bd=d;best=it;}
  }
  return best;
}
function ed3Input(){
  const c=ED3.cv;
  let mode=null,sx=0,sy=0,moved=0;
  c.addEventListener('contextmenu',e=>e.preventDefault());
  c.addEventListener('mousedown',e=>{
    const r=c.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
    sx=mx;sy=my;moved=0;
    if(e.button===1||e.shiftKey){mode='pan';return;}
    if(e.button===2){mode='orbit';return;}
    const it=edMode?ed3Pick(mx,my):null;
    if(it){mode='move';ED3.drag={it,py:it.k==='in'?(it.alt||0)/ED3.hdiv:hAt(it.tx,it.tz)};
      edSelect(it.k,it.i);edStatus();draw();}
    else mode='orbit';
  });
  window.addEventListener('mousemove',e=>{
    const r=c.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
    ED3.last=[mx,my];
    if(!mode){if(ED3.on&&ED3.vp)ED3.hover=ed3Pick(mx,my);return;}
    const dx=mx-sx,dy=my-sy;moved+=Math.abs(dx)+Math.abs(dy);sx=mx;sy=my;
    const cam=ED3.cam;
    if(mode==='orbit'){cam.yaw-=dx*0.008;cam.pitch=Math.max(0.15,Math.min(1.45,cam.pitch+dy*0.006));ed3SaveCam();}
    else if(mode==='pan'){
      const k=cam.dist*0.0016;
      cam.tx-=(ED3.right[0]*dx*k)+(-ED3.fwd[0])*0; cam.tz-=(ED3.right[2]*dx*k);
      const fx=ED3.fwd[0],fz=ED3.fwd[2],fl=Math.hypot(fx,fz)||1;
      cam.tx+=fx/fl*dy*k;cam.tz+=fz/fl*dy*k;
      cam.tx=Math.max(0,Math.min(64,cam.tx));cam.tz=Math.max(0,Math.min(64,cam.tz));
    }
    else if(mode==='move'&&ED3.drag){
      const g=ed3Ground(mx,my,c.clientWidth,c.clientHeight,ED3.drag.py);
      if(g)applyMove3(ED3.drag.it,Math.max(0,Math.min(64,g[0])),Math.max(0,Math.min(64,g[1])));
    }
  });
  window.addEventListener('mouseup',e=>{
    if(mode==='orbit'&&moved<5&&ED3.on){
      // click a vuoto: copia coordinate esatte (raycast sul terreno)
      const r=c.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
      const g=ed3Ground(mx,my,c.clientWidth,c.clientHeight);
      if(g){
        const l=LV[cur];
        const s=`TB-POS3D lvl=${l.entry} ${l.name} tile=(${g[0].toFixed(2)},${g[1].toFixed(2)}) V-dato=(${(g[0]*8).toFixed(0)},${(512-g[1]*8).toFixed(0)}) centroRel_mezziTile=(${((g[0]-32)*2).toFixed(1)},${((g[1]-32)*2).toFixed(1)})`;
        if(navigator.clipboard)navigator.clipboard.writeText(s).catch(()=>{});
        ED3.msg='📋 '+s;setTimeout(()=>{ED3.msg=''},2500);
      }
    }
    mode=null;ED3.drag=null;
  });
  c.addEventListener('wheel',e=>{
    e.preventDefault();
    ED3.cam.dist=Math.max(4,Math.min(160,ED3.cam.dist*(1+Math.sign(e.deltaY)*0.09)));
    ed3SaveCam();
  },{passive:false});
}
})();
"""

html = open(VIEWER).read()
inject = EDJS.replace("__ED__", json.dumps(extras, separators=(",", ":"))) \
             .replace("__EDZCFG__", json.dumps(ZCFG, separators=(",", ":"))) \
             .replace("__EDRECIPES__", json.dumps(RECIPES, ensure_ascii=False, separators=(",", ":"))) \
             .replace("__EDTOYS__", json.dumps(TOYNAMES, ensure_ascii=False, separators=(",", ":"))) \
             .replace("__EDMSET__", json.dumps(MSET, separators=(",", ":"))) \
             .replace("__EDMTEAMS__", json.dumps(MTEAMS, separators=(",", ":"))) \
             .replace("__EDNAMES__", json.dumps(S6_NAMES)) \
             .replace("__EDSTATICS__", json.dumps(STATICS_NAMES, ensure_ascii=False)) \
             .replace("__EDEXV__", json.dumps(EXTRA_VANILLA))
html = html.replace("</script></body></html>", inject + ED3JS + "\n</script></body></html>")
html = html.replace("<title>Team Buddies - Level Viewer</title>",
                    "<title>Team Buddies - Level EDITOR</title>")
open(OUT, "w").write(html)
print(f"editor scritto in {OUT} ({os.path.getsize(OUT)//1024} KB)")
