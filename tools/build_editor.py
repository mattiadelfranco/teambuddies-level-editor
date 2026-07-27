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

EDJS = r"""
// ============== EDITOR ==============
const ED_DATA=__ED__;
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
    edStates[cur]={
      s0:((x&&x.s0)?x.s0:(l.pld[0].pts||[])).map(p=>p.slice()),
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
  st.s6.records.forEach((r,i)=>out.push({k:'s6',i,x:h2wx(r[3]),z:h2wy(r[4]),
    lbl:(ED_NAMES[r[0]]||('tipo '+r[0]))+` (team ${r[1]+1})`,col:'#f9ca24'}));
  if(st.extra)st.extra.forEach((r,i)=>out.push({k:'tr',i,x:r[2]+18,z:512-r[4],lbl:edTrName(r[5]),col:'#00d2d3'}));
  st.inst.forEach((it,i)=>out.push({k:'in',i,x:W+eTX()-it[1],z:it[3],
    lbl:l.models[it[0]]||('#'+it[0]),col:'#a29bfe',small:true}));
  return out;
}
function edSelect(k,i){edSel=edItems().find(o=>o.k===k&&o.i===i)||null;}
// proprieta' degli oggetti extra (da FUN_800a8780 ENG): al caricamento l'oggetto
// prende il team della BASE piu' vicina; ogni team possiede la base piu' vicina
// al proprio spawn s0. Riproduciamo la catena per l'anteprima nell'editor.
function edOwner(it){
  const st=edState(), l=LV[cur], items=edItems();
  const bases=items.filter(o=>o.k==='in'&&(l.models[st.inst[o.i][0]]||'').toUpperCase().startsWith('BSE'));
  if(!bases.length)return null;
  const s0=items.filter(o=>o.k==='s0');
  const claimed=s0.map(s=>{let bb=null,bd=1/0;
    for(const b of bases){const d=(b.x-s.x)**2+(b.z-s.z)**2;if(d<bd){bd=d;bb=b;}}
    return {team:s.i,base:bb};});
  let best=null,bd=1/0;
  for(const c of claimed){if(!c.base)continue;
    const d=(c.base.x-it.x)**2+(c.base.z-it.z)**2;
    if(d<bd){bd=d;best=c;}}
  return best;
}
function drawEd(){
  if(!edMode)return;
  const px=cv.width/W;
  // anteprima impronta pedana 4x4 (32 unita' mondo) sotto i marker s0
  for(const it of edItems()){
    if(it.k!=='s0')continue;
    ctx.save();
    ctx.fillStyle='rgba(255,71,87,0.25)';ctx.strokeStyle='rgba(255,71,87,0.9)';
    ctx.fillRect((it.x-16)*px,(it.z-16)*px,32*px,32*px);
    ctx.strokeRect((it.x-16)*px,(it.z-16)*px,32*px,32*px);
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
  else return alert('le pedane/spawn s0 non si eliminano (una per team)');
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
  }else return alert('le pedane/spawn s0 non si duplicano');
  edDirty=true;edStatus();draw();
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
  if(st.extra)edits.extra=st.extra;
  const r=await fetch('/api/save',{method:'POST',body:JSON.stringify({entry:l.entry,edits})});
  const j=await r.json();
  document.getElementById('edlog').textContent=j.ok?'✓ salvato in mods/'+l.entry:('ERRORE: '+(j.err||''));
  if(j.ok)edDirty=false;edStatus();
}
async function edBuild(){
  document.getElementById('edlog').textContent='compilo...';
  const r=await fetch('/api/build',{method:'POST',body:'{}'});
  const j=await r.json();
  document.getElementById('edlog').textContent=(j.ok?'✓ ISO pronta (rebuild.cue)':'ERRORE')+'\n'+(j.log||[]).join('\n');
}
function edStatus(){
  let txt=edSel?('selezionato: '+edSel.lbl):'niente selezionato';
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
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0">
    <button id="bt_dup">duplica selez.</button><button id="bt_del">elimina selez.</button>
    <button id="bt_save">💾 salva livello</button><button id="bt_build">🔨 compila ISO</button>
  </div>
  <div id="edsel" style="color:#8b93a1"></div><div id="eddirty" style="color:#ffa502"></div>
  <pre id="edlog" style="white-space:pre-wrap;font-size:11px;color:#8b93a1"></pre>`;
  document.getElementById('side').insertBefore(div,document.getElementById('side').children[1]);
  document.getElementById('ck_edit').onchange=e=>{edMode=e.target.checked;edFillModels();edFillExtra();draw();};
  document.getElementById('ed_trteam').onchange=e=>{
    if(!edSel||edSel.k!=='tr')return;
    edState().extra[edSel.i][8]=+e.target.value;
    edDirty=true;edStatus();
  };
  document.getElementById('ed_mdl').addEventListener('focus',edFillModels);
  document.getElementById('bt_def').onclick=edAddDefenses;
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

html = open(VIEWER).read()
inject = EDJS.replace("__ED__", json.dumps(extras, separators=(",", ":"))) \
             .replace("__EDNAMES__", json.dumps(S6_NAMES)) \
             .replace("__EDSTATICS__", json.dumps(STATICS_NAMES, ensure_ascii=False)) \
             .replace("__EDEXV__", json.dumps(EXTRA_VANILLA))
html = html.replace("</script></body></html>", inject + "\n</script></body></html>")
html = html.replace("<title>Team Buddies - Level Viewer</title>",
                    "<title>Team Buddies - Level EDITOR</title>")
open(OUT, "w").write(html)
print(f"editor scritto in {OUT} ({os.path.getsize(OUT)//1024} KB)")
