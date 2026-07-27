#!/usr/bin/env python3
"""
Team Buddies (PSX) - Genera un viewer HTML top-down dei livelli.

Legge i livelli estratti (cartelle bind/NNNN con .PND/.PLD/.PTH) e produce
un unico file HTML autonomo con:
  - heightmap del terreno (PND, griglia vertici 65x65, mondo 512x512)
  - oggetti piazzati (PND, istanze con nome modello)
  - griglia percorsi AI (PTH, 128x128)
  - punti delle sezioni PLD (sez. 0 = spawn/pedane; le altre da identificare,
    con fattore di scala regolabile per la calibrazione)

Uso: python3 tools/build_viewer.py [cartella_estratti] [output.html]
"""
import struct, glob, os, sys, json, base64

SRC = sys.argv[1] if len(sys.argv) > 1 else "teambudd/dat_estratto/bind"
OUT = sys.argv[2] if len(sys.argv) > 2 else "teambudd/viewer.html"
GROUNDS = "teambudd/grounds"


def b64(b):
    return base64.b64encode(b).decode()


def parse_level(folder):
    pnds = glob.glob(os.path.join(folder, "*.PND"))
    plds = glob.glob(os.path.join(folder, "*.PLD"))
    pths = glob.glob(os.path.join(folder, "*.PTH"))
    if not (pnds and plds):
        return None
    name = os.path.basename(pnds[0]).rsplit(".", 1)[0]
    lvl = {"name": name, "entry": os.path.basename(folder)}

    d = open(pnds[0], "rb").read()
    if d[:4] != b"PSM0":
        return None
    n_names, n_inst, gw, gh = struct.unpack_from("<4H", d, 4)
    models = [d[12 + i*32: 12 + (i+1)*32].split(b"\0")[0].decode("ascii", "replace")
              for i in range(n_names)]
    base = 12 + n_names * 32
    inst = []
    for i in range(n_inst):
        o = base + i * 20
        m, = struct.unpack_from("<I", d, o)
        x, h, z, e = struct.unpack_from("<4h", d, o + 4)
        r1, r2 = struct.unpack_from("<2i", d, o + 12)
        inst.append([m, x, h, z, e, r1, r2])
    hm_off = base + n_inst * 20
    lvl["models"] = models
    lvl["inst"] = inst
    lvl["hm"] = b64(d[hm_off: hm_off + 65 * 65 * 2])

    d = open(plds[0], "rb").read()
    offs = list(struct.unpack_from("<17I", d, 8))
    offs.append(len(d) - 8)
    secs = []
    for si in range(17):
        o, sz = offs[si] + 8, offs[si + 1] - offs[si]
        sec = {"i": si, "sz": sz, "pts": []}
        if sz >= 12:
            cnt = struct.unpack_from("<I", d, o)[0]
            if 0 < cnt < 2000 and (sz - 4) % cnt == 0 and (sz - 4) // cnt in (8, 12, 16, 20):
                rec = (sz - 4) // cnt
                sec["rec"] = rec
                sec["n"] = cnt
                for k in range(cnt):
                    vals = struct.unpack_from(f"<{rec//2}H", d, o + 4 + k * rec)
                    sec["pts"].append(list(vals))
        secs.append(sec)
    lvl["pld"] = secs

    if pths:
        d = open(pths[0], "rb").read()
        if len(d) == 16416:
            lvl["pth"] = b64(d[32:])

    gpng = os.path.join(GROUNDS, os.path.basename(folder) + ".png")
    if os.path.exists(gpng):
        lvl["ground"] = b64(open(gpng, "rb").read())
    return lvl


levels = []
for folder in sorted(glob.glob(os.path.join(SRC, "*"))):
    if not os.path.isdir(folder):
        continue
    try:
        lvl = parse_level(folder)
    except Exception as e:
        print("skip", folder, e)
        continue
    if lvl:
        levels.append(lvl)
print(f"{len(levels)} livelli")

DATA = json.dumps(levels, separators=(",", ":"))

HTML = """<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<title>Team Buddies - Level Viewer</title>
<style>
:root{color-scheme:dark}
body{margin:0;font:13px/1.4 -apple-system,Helvetica,sans-serif;background:#14161a;color:#d8dade;display:flex;height:100vh}
#side{width:300px;min-width:300px;overflow-y:auto;padding:12px;background:#1b1e24;border-right:1px solid #2a2e36}
#main{flex:1;display:flex;align-items:center;justify-content:center;position:relative}
canvas{image-rendering:pixelated;background:#000;max-width:95%;max-height:95%}
select{width:100%;padding:6px;background:#242830;color:#fff;border:1px solid #3a3f4a;border-radius:6px;font-size:13px;margin-bottom:10px}
h3{margin:14px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#8b93a1}
label{display:flex;align-items:center;gap:6px;padding:2px 0;cursor:pointer}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block}
#info{position:absolute;left:10px;bottom:10px;background:#000a;padding:6px 10px;border-radius:6px;font-family:ui-monospace,monospace;font-size:12px;pointer-events:none}
#tip{position:absolute;background:#000d;padding:4px 8px;border-radius:4px;font-size:12px;pointer-events:none;display:none;z-index:5}
.num{width:52px;background:#242830;color:#fff;border:1px solid #3a3f4a;border-radius:4px;padding:2px 4px}
.leg{margin:1px 0;display:flex;gap:6px;align-items:center;font-size:12px}
</style></head><body>
<div id="side">
  <select id="lvl"></select>
  <h3>Layer</h3>
  <label><input type="checkbox" id="ck_view"> Specchia X</label>\n  <label><input type="checkbox" id="ck_viewy" checked> Specchia Y (vista di gioco)</label>\n  <label>Ruota <select id="rot" style="width:70px;margin-bottom:0"><option value="0">0°</option><option value="90">90°</option><option value="180">180°</option><option value="270">270°</option></select></label>\n  <label><input type="checkbox" id="ck_gr" checked> Grafica terreno (texture)</label>
  <label><input type="checkbox" id="ck_hm"> Altezze (heightmap)</label>
  <label><input type="checkbox" id="ck_pth"> Percorsi AI (PTH)</label>
  <label><input type="checkbox" id="ck_obj" checked> Oggetti (PND)</label>
  <label style="margin-left:14px"><input type="checkbox" id="ck_mx" checked> specchia X oggetti</label>
  <h3>Sezioni PLD <span style="text-transform:none">(scala <input class="num" id="scale" type="number" value="8" step="0.5"> tar.X <input class="num" id="tarx" type="number" value="23" step="1"> tar.Y <input class="num" id="tary" type="number" value="8" step="1">× <label style="display:inline"><input type="checkbox" id="ck_smx"> specchia X</label>)</span></h3>
  <div id="pldsecs"></div>
  <h3>Oggetti nel livello</h3>
  <div id="legend"></div>
</div>
<div id="main"><canvas id="cv" width="1024" height="1024"></canvas><div id="info"></div><div id="tip"></div></div>
<script>
const LV=__DATA__;
const W=512, CS=2; // mondo 512, canvas scale
const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
const secColors=['#ff4757','#ffa502','#2ed573','#1e90ff','#e84393','#00d2d3','#f9ca24','#a29bfe','#fd79a8','#55efc4','#fab1a0','#74b9ff','#ffeaa7','#81ecec','#dfe6e9','#b2bec3','#636e72'];
function b64i16(s){const b=atob(s),n=b.length/2,a=new Int16Array(n);for(let i=0;i<n;i++){let v=b.charCodeAt(2*i)|(b.charCodeAt(2*i+1)<<8);if(v>32767)v-=65536;a[i]=v}return a}
function b64u8(s){const b=atob(s),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a}
function hash(s){let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))>>>0;return h}
function mcolor(n){if(/BSE|BASE/i.test(n)&&!/flag/i.test(n))return '#ff3b30';if(/flag/i.test(n))return '#ffd60a';const h=hash(n)%360;return `hsl(${h} 70% 60%)`}
const sel=document.getElementById('lvl');
LV.forEach((l,i)=>{const o=document.createElement('option');o.value=i;o.textContent=l.entry+' — '+l.name;sel.appendChild(o)});
const secsDiv=document.getElementById('pldsecs');
let cur=0, showSec=new Set([0]);
function buildSecUI(){secsDiv.innerHTML='';const l=LV[cur];l.pld.forEach(s=>{
  const lab=document.createElement('label');
  const info = s.pts.length? `n=${s.n} rec=${s.rec}B` : `${s.sz}B`;
  lab.innerHTML=`<input type="checkbox" data-s="${s.i}" ${showSec.has(s.i)?'checked':''} ${s.pts.length?'':'disabled'}>`+
    `<span class="sw" style="background:${secColors[s.i]}"></span> s${s.i} <span style="color:#8b93a1">(${info})</span>`;
  lab.querySelector('input').onchange=e=>{const i=+e.target.dataset.s;e.target.checked?showSec.add(i):showSec.delete(i);draw()};
  secsDiv.appendChild(lab)})}
function heightColor(v,mn,mx){const t=(v-mn)/Math.max(1,mx-mn);
  // verde scuro -> verde -> ocra -> grigio chiaro
  const stops=[[30,60,38],[64,120,66],[150,140,80],[190,180,160],[235,235,235]];
  const x=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(x)),f=x-i;
  const c=stops[i].map((a,k)=>Math.round(a+(stops[i+1][k]-a)*f));return c}
const groundCache={};
function draw(){
  const l=LV[cur];ctx.clearRect(0,0,cv.width,cv.height);
  const _fx=document.getElementById('ck_view').checked,_fy=document.getElementById('ck_viewy').checked,_rot=+document.getElementById('rot').value;
  cv.style.transform=`scale(${_fx?-1:1},${_fy?-1:1}) rotate(${_rot}deg)`;
  const px=cv.width/W;
  if(document.getElementById('ck_gr').checked&&l.ground){
    let im=groundCache[cur];
    if(!im){im=new Image();im.src='data:image/png;base64,'+l.ground;groundCache[cur]=im;
      im.onload=draw;}
    if(im.complete)ctx.drawImage(im,0,0,cv.width,cv.height);
  }
  if(document.getElementById('ck_hm').checked&&l.hm){
    const hm=b64i16(l.hm);let mn=32767,mx=-32768;for(const v of hm){if(v<mn)mn=v;if(v>mx)mx=v}
    const cell=W/64*px;
    for(let r=0;r<64;r++)for(let c=0;c<64;c++){
      const v=(hm[r*65+c]+hm[r*65+c+1]+hm[(r+1)*65+c]+hm[(r+1)*65+c+1])/4;
      let col=heightColor(v,mn,mx);
      const shade=1+ (hm[r*65+c]-hm[r*65+Math.max(0,c-1)])*0.03;
      col=col.map(x=>Math.max(0,Math.min(255,Math.round(x*shade))));
      ctx.fillStyle=`rgb(${col[0]},${col[1]},${col[2]})`;
      ctx.fillRect(c*cell,r*cell,cell+1,cell+1)}
  }
  if(document.getElementById('ck_pth').checked&&l.pth){
    const g=b64u8(l.pth);const cell=W/128*px;
    ctx.fillStyle='rgba(80,160,255,.55)';
    for(let r=0;r<128;r++)for(let c=0;c<128;c++)if(g[r*128+c])ctx.fillRect(c*cell,r*cell,cell,cell)}
  const legend={};
  const mx=document.getElementById('ck_mx').checked;
  if(document.getElementById('ck_obj').checked){
    for(const it of l.inst){const [m,x,h,z,e]=it;const nm=l.models[m]||('#'+m);
      legend[nm]=(legend[nm]||0)+1;
      ctx.fillStyle=mcolor(nm);ctx.strokeStyle='#000';
      const X=(mx?W+(+document.getElementById('tarx').value||0)-x:x)*px,Z=z*px,R=/BSE|BASE/i.test(nm)&&!/flag/i.test(nm)?7:4;
      ctx.beginPath();ctx.arc(X,Z,R,0,7);ctx.fill();ctx.stroke()}}
  const sc=parseFloat(document.getElementById('scale').value)||8;
  const smx=document.getElementById('ck_smx').checked;
  const tos16=v=>v>=32768?v-65536:v;
  // codifiche note: s0 = tile ancorato ai bordi (formula verificata in gioco);
  // s1/s2/s4/s14/s15 = mezzi-tile relativi al centro
  const dec=(si,p)=>{
    // tutte le sezioni posizionali: mezzi-tile relativi al centro, con segno (verificato in gioco)
    const TX=()=>+document.getElementById('tarx').value||0,TY=()=>+document.getElementById('tary').value||0;
  const f=v=>(32+tos16(v)/512)*8;
  const fx=v=>f(v)+TX(),fy=v=>f(v)+TY();
    if(si===0)return [fx(p[0]),fy(p[1])];
    if([1,2,4,14,15].includes(si))return [fx(p[0]),fy(p[2]!==undefined?p[2]:p[1])];
    return [p[0]/256*sc,p[1]/256*sc];
  };
  for(const s of l.pld){if(!showSec.has(s.i)||!s.pts.length)continue;
    ctx.fillStyle=secColors[s.i];ctx.strokeStyle='#fff';ctx.font='bold 11px sans-serif';
    s.pts.forEach((p,k)=>{let [X,Z]=dec(s.i,p);if(smx)X=W-X;X*=px;Z*=px;
      ctx.beginPath();ctx.rect(X-5,Z-5,10,10);ctx.fill();ctx.stroke();
      if(s.i===0){ctx.fillStyle='#fff';ctx.fillText(String(k+1),X+7,Z+4);ctx.fillStyle=secColors[s.i]}});}
  const legDiv=document.getElementById('legend');legDiv.innerHTML='';
  Object.entries(legend).sort((a,b)=>b[1]-a[1]).forEach(([nm,n])=>{
    const d=document.createElement('div');d.className='leg';
    d.innerHTML=`<span class="sw" style="background:${mcolor(nm)}"></span>${nm} ×${n}`;legDiv.appendChild(d)})
}
function evtToWorld(e){
  const r=cv.getBoundingClientRect();
  let wx=(e.clientX-r.left)/r.width*W, wz=(e.clientY-r.top)/r.height*W;
  if(document.getElementById('ck_view').checked)wx=W-wx;
  if(document.getElementById('ck_viewy').checked)wz=W-wz;
  const rotv=+document.getElementById('rot').value*Math.PI/180;
  const cx=W/2,cy=W/2,dx=wx-cx,dy=wz-cy,c=Math.cos(-rotv),si=Math.sin(-rotv);
  return [cx+dx*c-dy*si, cy+dx*si+dy*c];
}
cv.onclick=e=>{
  const [wx,wz]=evtToWorld(e);
  const l=LV[cur];
  const g=id=>document.getElementById(id);
  const info=`TB-POS lvl=${l.entry} ${l.name} tile=(${(wx/8).toFixed(2)},${(wz/8).toFixed(2)}) mondo=(${wx.toFixed(0)},${wz.toFixed(0)}) `+
    `centroRel_mezziTile=(${((wx/8-32)*2).toFixed(1)},${((wz/8-32)*2).toFixed(1)}) `+
    `vista[specchiaX=${g('ck_view').checked?1:0} specchiaY=${g('ck_viewy').checked?1:0} rot=${g('rot').value} `+
    `specchiaXogg=${g('ck_mx').checked?1:0} scalaPLD=${g('scale').value} specchiaXpld=${g('ck_smx').checked?1:0}]`;
  const ta=document.createElement('textarea');ta.value=info;document.body.appendChild(ta);
  ta.select();try{document.execCommand('copy')}catch(x){}
  if(navigator.clipboard)navigator.clipboard.writeText(info).catch(()=>{});
  document.body.removeChild(ta);
  const t2=document.getElementById('tip');t2.style.display='block';
  t2.style.left=(e.clientX-cv.getBoundingClientRect().left+14)+'px';
  t2.style.top=(e.clientY-cv.getBoundingClientRect().top-20)+'px';
  t2.textContent='📋 copiato!';setTimeout(()=>{t2.style.display='none'},900);
};
cv.onmousemove=e=>{
  const [wx,wz]=evtToWorld(e);
  const sc=parseFloat(document.getElementById('scale').value)||8;
  document.getElementById('info').textContent=
    `mondo (${wx.toFixed(0)}, ${wz.toFixed(0)})  tile (${(wx/8).toFixed(1)}, ${(wz/8).toFixed(1)})  PLD (${(wx/sc).toFixed(1)}, ${(wz/sc).toFixed(1)})`;
  // tooltip oggetti
  const l=LV[cur];const tip=document.getElementById('tip');let found=null;
  const mx2=document.getElementById('ck_mx').checked;
  for(const it of l.inst){const ix=mx2?W+(+document.getElementById('tarx').value||0)-it[1]:it[1];const dx=ix-wx,dz=it[3]-wz;if(dx*dx+dz*dz<25){found=it;break}}
  if(found){tip.style.display='block';tip.style.left=(e.clientX-r.left+14)+'px';tip.style.top=(e.clientY-r.top+14)+'px';
    tip.textContent=`${l.models[found[0]]||'#'+found[0]} (${found[1]},${found[3]}) alt=${found[2]} e=${found[4]} rot=${found[5]}`}
  else tip.style.display='none';
}
sel.onchange=()=>{cur=+sel.value;buildSecUI();draw()};
['tarx','tary','ck_view','ck_viewy','rot','ck_gr','ck_hm','ck_pth','ck_obj','ck_mx','ck_smx','scale'].forEach(id=>document.getElementById(id).onchange=draw);
buildSecUI();draw();
</script></body></html>"""

with open(OUT, "w") as f:
    f.write(HTML.replace("__DATA__", DATA))
print(f"viewer scritto in {OUT} ({os.path.getsize(OUT)//1024} KB)")
