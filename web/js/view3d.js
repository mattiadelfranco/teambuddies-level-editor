// 3D view (WebGL1, no deps). Same store/items as the 2D view.
// Engine facts baked in: heights h/8 tiles positive up; instances and extra
// at tile (x/8, 64-z/8); yaw from the parser (0x800-rot flip when |p6|>500),
// +rot in our Y-up frame; extra spawn yaw = rot + 0x800.
import { store } from './store.js';
import { items, moveItem, heightAt } from './items.js';
import { api, b64u8 } from './api.js';
import { brush, beginStroke, moveStroke, endStroke, strokeActive } from './terrain.js';
import * as TL from './tiles.js';
import * as CAT from './catalog.js';

const TCOLS = [[231, 76, 60], [52, 152, 219], [46, 204, 113], [241, 196, 15],
  [155, 89, 182], [230, 126, 34], [26, 188, 156], [149, 165, 166]];
const SEC_COLORS = ['#ff4757', '#ffa502', '#2ed573', '#1e90ff', '#e84393',
  '#00d2d3', '#f9ca24', '#a29bfe', '#fd79a8', '#55efc4', '#fab1a0',
  '#74b9ff', '#ffeaa7', '#81ecec', '#dfe6e9', '#b2bec3', '#636e72'];

const E3 = {
  cv: null, gl: null, pr: null, loc: null,
  entry: null, terr: null, models: null, texs: {}, ground: null,
  groundImg: null, gizmo: null, statusPos: null,
  cam: {
    yaw: parseFloat(localStorage.e3yaw || String(Math.PI)),
    pitch: parseFloat(localStorage.e3pitch || '0.85'),
    dist: parseFloat(localStorage.e3dist || '46'), tx: 32, tz: 32,
  },
  drag: null, raf: 0, on: false,
};

function saveCam() {
  localStorage.e3yaw = E3.cam.yaw; localStorage.e3pitch = E3.cam.pitch;
  localStorage.e3dist = E3.cam.dist;
}
export function rotateCam(d) { E3.cam.yaw += d; saveCam(); }
export function gameCam() { E3.cam.yaw = Math.PI; E3.cam.pitch = 0.85; saveCam(); }

// ---------------------------------------------------------------- setup ----
export function init3d(canvas, statusPos) {
  E3.cv = canvas; E3.statusPos = statusPos;
  window.E3D = E3;              // debug handle (console)
  const gl = canvas.getContext('webgl', { antialias: true });
  E3.gl = gl;
  const vs = `attribute vec3 aP;attribute vec3 aN;attribute vec2 aU;
    uniform mat4 uVP;uniform vec3 uT;uniform float uRot;
    varying vec2 vU;varying vec3 vN;
    void main(){float cr=cos(uRot),sr=sin(uRot);
    vec3 p=vec3(aP.x*cr-aP.z*sr,aP.y,aP.x*sr+aP.z*cr)+uT;
    vN=vec3(aN.x*cr-aN.z*sr,aN.y,aN.x*sr+aN.z*cr);
    vU=aU;gl_Position=uVP*vec4(p,1.0);}`;
  const fs = `precision mediump float;
    uniform bool uTexOn;uniform sampler2D uTex;uniform vec4 uCol;uniform float uLit;
    varying vec2 vU;varying vec3 vN;
    void main(){vec4 c=uCol;
    if(uTexOn){vec4 t=texture2D(uTex,vU);if(t.a<0.5)discard;c=vec4(c.rgb*t.rgb,c.a);}
    if(uLit>0.5){vec3 L=normalize(vec3(0.35,0.8,0.5));
      float l=0.58+0.42*max(dot(normalize(vN),L),0.0);c=vec4(c.rgb*l,c.a);}
    gl_FragColor=c;}`;
  const sh = (t, s) => {
    const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x);
    if (!gl.getShaderParameter(x, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(x));
    return x;
  };
  const pr = gl.createProgram();
  gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(pr); gl.useProgram(pr);
  E3.pr = pr;
  E3.loc = Object.fromEntries(['uVP', 'uT', 'uRot', 'uTexOn', 'uCol', 'uLit']
    .map(n => [n, gl.getUniformLocation(pr, n)]));
  E3.loc.aP = gl.getAttribLocation(pr, 'aP');
  E3.loc.aN = gl.getAttribLocation(pr, 'aN');
  E3.loc.aU = gl.getAttribLocation(pr, 'aU');
  gl.enable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  E3.gizmo = { box: mesh(boxGeo()), cone: mesh(coneGeo(10)), cyl: mesh(cylGeo(10)) };
  input();
}

export function show3d(on) {
  E3.on = on;
  if (on) { load(); frame(); }
  else cancelAnimationFrame(E3.raf);
}

// ------------------------------------------------------------ gizmo geo ----
function boxGeo() {
  const v = [], q = (a, b, c, d, n) => [a, b, c, a, c, d].forEach(p => v.push(...p, ...n, 0, 0));
  const p = [[-.5, 0, -.5], [.5, 0, -.5], [.5, 0, .5], [-.5, 0, .5],
             [-.5, 1, -.5], [.5, 1, -.5], [.5, 1, .5], [-.5, 1, .5]];
  q(p[0], p[1], p[2], p[3], [0, -1, 0]); q(p[4], p[7], p[6], p[5], [0, 1, 0]);
  q(p[0], p[4], p[5], p[1], [0, 0, -1]); q(p[3], p[2], p[6], p[7], [0, 0, 1]);
  q(p[0], p[3], p[7], p[4], [-1, 0, 0]); q(p[1], p[5], p[6], p[2], [1, 0, 0]);
  return v;
}
function coneGeo(n) {
  const v = [];
  for (let i = 0; i < n; i++) {
    const a = i / n * 6.2832, b = (i + 1) / n * 6.2832;
    const x1 = Math.cos(a) * .5, z1 = Math.sin(a) * .5, x2 = Math.cos(b) * .5, z2 = Math.sin(b) * .5;
    v.push(0, 1, 0, 0, 1, 0, 0, 0, x1, 0, z1, x1, 0, z1, 0, 0, x2, 0, z2, x2, 0, z2, 0, 0);
    v.push(0, 0, 0, 0, -1, 0, 0, 0, x2, 0, z2, 0, -1, 0, 0, 0, x1, 0, z1, 0, -1, 0, 0, 0);
  }
  return v;
}
function cylGeo(n) {
  const v = [];
  for (let i = 0; i < n; i++) {
    const a = i / n * 6.2832, b = (i + 1) / n * 6.2832;
    const x1 = Math.cos(a) * .5, z1 = Math.sin(a) * .5, x2 = Math.cos(b) * .5, z2 = Math.sin(b) * .5;
    v.push(x1, 0, z1, x1, 0, z1, 0, 0, x1, 1, z1, x1, 0, z1, 0, 0, x2, 1, z2, x2, 0, z2, 0, 0);
    v.push(x1, 0, z1, x1, 0, z1, 0, 0, x2, 1, z2, x2, 0, z2, 0, 0, x2, 0, z2, x2, 0, z2, 0, 0);
    v.push(0, 1, 0, 0, 1, 0, 0, 0, x1, 1, z1, 0, 1, 0, 0, 0, x2, 1, z2, 0, 1, 0, 0, 0);
  }
  return v;
}
function mesh(arr) {
  const gl = E3.gl, b = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(arr), gl.STATIC_DRAW);
  return { vbo: b, n: arr.length / 8 };
}

// -------------------------------------------------------------- loading ----
function tex(img) {
  const gl = E3.gl, t = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, t);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  // PSX-style point sampling (bilinear smears texels on steep faces)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  return t;
}

export function load() {
  if (!store.lvl || E3.entry === store.entry) return;
  E3.entry = store.entry;
  E3.models = null; E3.texs = {}; E3.ground = null; E3.groundImg = null;
  buildTerrain();
  const entry = store.entry;
  const img = new Image();
  img.onload = () => { if (E3.entry === entry) { E3.groundImg = img; composeGround(); } };
  img.src = api.groundUrl(entry);
  api.models3d(entry).then(jd => {
    if (E3.entry !== entry || !jd.models) return;
    const gl = E3.gl;
    for (const [name, uri] of Object.entries(jd.tex || {})) {
      const im = new Image();
      im.onload = () => { E3.texs[name] = tex(im); };
      im.src = uri;
    }
    E3.models = {};
    for (const [name, batches] of Object.entries(jd.models))
      E3.models[name] = buildBatches(batches);
    // unsaved imports from other levels need their meshes too
    for (const m of store.ed.addModels || []) importModel(m.from, m.name);
  }).catch(() => store.say('3D models unavailable (is the server running?)'));
}

function buildBatches(batches) {
  const gl = E3.gl;
  return batches.map(b => {
    const n = b.p.length / 3, arr = new Float32Array(n * 8);
    for (let i = 0; i < n; i++)
      arr.set([b.p[3 * i], b.p[3 * i + 1], b.p[3 * i + 2],
               b.n[3 * i], b.n[3 * i + 1], b.n[3 * i + 2],
               b.u[2 * i], b.u[2 * i + 1]], i * 8);
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
    return { vbo, n, tex: b.t, col: [b.c[0] / 128, b.c[1] / 128, b.c[2] / 128, 1] };
  });
}

// global models (turrets): lazy per-DAT-entry cache shared by all levels
const GLB = { meshes: new Map(), texs: new Map(), loading: new Set() };
function globalMesh(dat) {
  if (GLB.meshes.has(dat)) return GLB.meshes.get(dat);
  if (!GLB.loading.has(dat)) {
    GLB.loading.add(dat);
    api.global3d(String(dat)).then(j => {
      for (const [name, uri] of Object.entries(j.tex || {})) {
        if (GLB.texs.has(name)) continue;
        const im = new Image();
        im.onload = () => { GLB.texs.set(name, tex(im)); };
        im.src = uri;
      }
      const first = Object.values(j.models)[0];
      if (first) GLB.meshes.set(dat, buildBatches(first));
    }).catch(() => {});
  }
  return null;
}

// register a model from ANOTHER level (import preview): mesh + its textures
export function importModel(from, name) {
  api.models3d(String(from)).then(j => {
    const key = name.toUpperCase();
    if (!j.models[key] || !E3.models) return;
    for (const [tn, uri] of Object.entries(j.tex || {})) {
      if (E3.texs[tn]) continue;
      const im = new Image();
      im.onload = () => { E3.texs[tn] = tex(im); };
      im.src = uri;
    }
    if (!E3.models[key]) E3.models[key] = buildBatches(j.models[key]);
  }).catch(() => {});
}

export function reload() { E3.entry = null; if (E3.on) load(); }
export function refreshTerrain() { buildTerrain(); composeGround(); }
export function refreshTerrainMesh() { buildTerrain(); }

// compose ground + heightmap + PTH layers into one terrain texture
export function composeGround() {
  const v = store.view.layers;
  const c = document.createElement('canvas');
  c.width = c.height = 2048;
  const x = c.getContext('2d');
  const gc = TL.groundCanvas();
  if (v.ground && gc) x.drawImage(gc, 0, 0, 2048, 2048);
  else if (v.ground && E3.groundImg) x.drawImage(E3.groundImg, 0, 0, 2048, 2048);
  else { x.fillStyle = v.ground ? '#1c2b1c' : '#3a4048'; x.fillRect(0, 0, 2048, 2048); }
  if (v.hm) {
    const hm = store.hm;
    let mn = 32767, mx = -32768;
    for (const q of hm) { if (q < mn) mn = q; if (q > mx) mx = q; }
    const stops = [[30, 60, 38], [64, 120, 66], [150, 140, 80], [190, 180, 160], [235, 235, 235]];
    const cell = 2048 / 64;
    x.globalAlpha = v.ground ? 0.65 : 1;
    for (let r = 0; r < 64; r++) for (let cc = 0; cc < 64; cc++) {
      const q = (hm[r * 65 + cc] + hm[r * 65 + cc + 1] + hm[(r + 1) * 65 + cc] + hm[(r + 1) * 65 + cc + 1]) / 4;
      const t = (q - mn) / Math.max(1, mx - mn), s = t * 4 | 0, f = t * 4 - s;
      const a = stops[Math.min(3, s)], b = stops[Math.min(4, s + 1)];
      x.fillStyle = `rgb(${a.map((w, k) => Math.round(w + (b[k] - w) * f)).join(',')})`;
      x.fillRect(cc * cell, r * cell, cell + 1, cell + 1);
    }
    x.globalAlpha = 1;
  }
  if (v.pth && store.lvl.pth) {
    const g = b64u8(store.lvl.pth), cell = 2048 / 128;
    x.fillStyle = 'rgba(80,160,255,.55)';
    for (let r = 0; r < 128; r++) for (let cc = 0; cc < 128; cc++)
      if (g[r * 128 + cc]) x.fillRect(cc * cell, r * cell, cell, cell);
  }
  E3.ground = tex(c);
}

function buildTerrain() {
  const gl = E3.gl, hm = store.hm;
  if (!gl || !hm) return;
  const H = (i, j) => hm[Math.max(0, Math.min(64, j)) * 65 + Math.max(0, Math.min(64, i))] / 8;
  const P = new Float32Array(65 * 65 * 8);
  for (let j = 0; j <= 64; j++) for (let i = 0; i <= 64; i++) {
    const o = (j * 65 + i) * 8;
    P[o] = i; P[o + 1] = H(i, j); P[o + 2] = j;
    // engine-style vertex normals (MAP_VNORMS) for gouraud shading
    const dx = (H(i + 1, j) - H(i - 1, j)) / 2, dz = (H(i, j + 1) - H(i, j - 1)) / 2;
    const il = 1 / Math.hypot(dx, 1, dz);
    P[o + 3] = -dx * il; P[o + 4] = il; P[o + 5] = -dz * il;
    P[o + 6] = i / 64; P[o + 7] = j / 64;
  }
  const I = new Uint16Array(64 * 64 * 6);
  let k = 0;
  for (let j = 0; j < 64; j++) for (let i = 0; i < 64; i++) {
    const a = j * 65 + i, b = a + 1, c = a + 65, d = a + 66;
    I[k++] = a; I[k++] = b; I[k++] = c; I[k++] = b; I[k++] = d; I[k++] = c;
  }
  if (E3.terr) { gl.deleteBuffer(E3.terr.vbo); gl.deleteBuffer(E3.terr.ibo); }
  const vbo = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo); gl.bufferData(gl.ARRAY_BUFFER, P, gl.STATIC_DRAW);
  const ibo = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, I, gl.STATIC_DRAW);
  E3.terr = { vbo, ibo, n: I.length };
}

// ------------------------------------------------------------- matrices ----
function mMul(a, b) {
  const o = new Float32Array(16);
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += a[k * 4 + c] * b[r * 4 + k];
    o[r * 4 + c] = s;
  }
  return o;
}
function vp(w, h) {
  const c = E3.cam;
  const ex = c.tx + c.dist * Math.cos(c.pitch) * Math.sin(c.yaw);
  const ey = Math.max(1, c.dist * Math.sin(c.pitch));
  const ez = c.tz + c.dist * Math.cos(c.pitch) * Math.cos(c.yaw);
  const f = [c.tx - ex, 0 - ey, c.tz - ez];
  const fl = Math.hypot(...f); f[0] /= fl; f[1] /= fl; f[2] /= fl;
  const up = [0, 1, 0];
  const s = [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]];
  const sl = Math.hypot(...s); s[0] /= sl; s[1] /= sl; s[2] /= sl;
  const u = [s[1] * f[2] - s[2] * f[1], s[2] * f[0] - s[0] * f[2], s[0] * f[1] - s[1] * f[0]];
  const V = new Float32Array([s[0], u[0], -f[0], 0, s[1], u[1], -f[1], 0, s[2], u[2], -f[2], 0,
    -(s[0] * ex + s[1] * ey + s[2] * ez), -(u[0] * ex + u[1] * ey + u[2] * ez),
    (f[0] * ex + f[1] * ey + f[2] * ez), 1]);
  const fov = 0.9, n = 0.5, fa = 600, t = Math.tan(fov / 2), a = w / h;
  const p = new Float32Array([1 / (t * a), 0, 0, 0, 0, 1 / t, 0, 0,
    0, 0, -(fa + n) / (fa - n), -1, 0, 0, -2 * fa * n / (fa - n), 0]);
  E3.eye = [ex, ey, ez]; E3.fwd = f; E3.right = s; E3.up = u; E3.tanF = t; E3.aspect = a;
  return mMul(p, V);
}
function project(p, m, w, h) {
  const cx = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
  const cy = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
  const cw = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
  if (cw <= 0) return null;
  return [(cx / cw * .5 + .5) * w, (1 - (cy / cw * .5 + .5)) * h, cw];
}
function ray(mx, my, w, h) {
  const nx = mx / w * 2 - 1, ny = 1 - my / h * 2;
  const d = [0, 1, 2].map(i =>
    E3.fwd[i] + nx * E3.tanF * E3.aspect * E3.right[i] + ny * E3.tanF * E3.up[i]);
  const l = Math.hypot(...d);
  return [d[0] / l, d[1] / l, d[2] / l];
}
function groundHit(mx, my, w, h, planeY) {
  const d = ray(mx, my, w, h), e = E3.eye;
  let y = planeY !== undefined ? planeY : 0;
  for (let i = 0; i < 4; i++) {
    if (Math.abs(d[1]) < 1e-4) break;
    const t = (y - e[1]) / d[1];
    if (t < 0) return null;
    const px = e[0] + d[0] * t, pz = e[2] + d[2] * t;
    if (planeY !== undefined) return [px, pz];
    y = heightAt(px, pz);
    if (i === 3) return [px, pz];
  }
  const t = (y - e[1]) / d[1];
  return t > 0 ? [e[0] + d[0] * t, e[2] + d[2] * t] : null;
}

// --------------------------------------------------------------- render ----
function drawMesh(m, tx, ty, tz, rot, col, texId, lit) {
  const gl = E3.gl, L = E3.loc;
  gl.bindBuffer(gl.ARRAY_BUFFER, m.vbo);
  gl.vertexAttribPointer(L.aP, 3, gl.FLOAT, false, 32, 0);
  gl.vertexAttribPointer(L.aN, 3, gl.FLOAT, false, 32, 12);
  gl.vertexAttribPointer(L.aU, 2, gl.FLOAT, false, 32, 24);
  gl.uniform3f(L.uT, tx, ty, tz);
  gl.uniform1f(L.uRot, rot || 0);
  gl.uniform4fv(L.uCol, col);
  gl.uniform1f(L.uLit, lit ? 1 : 0);
  if (texId) { gl.uniform1i(L.uTexOn, 1); gl.bindTexture(gl.TEXTURE_2D, texId); }
  else gl.uniform1i(L.uTexOn, 0);
  gl.drawArrays(gl.TRIANGLES, 0, m.n);
}
function drapedQuad(cx, cz, half, col) {
  const gl = E3.gl, L = E3.loc, N = 4, v = [];
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const x0 = cx - half + 2 * half * i / N, x1 = cx - half + 2 * half * (i + 1) / N;
    const z0 = cz - half + 2 * half * j / N, z1 = cz - half + 2 * half * (j + 1) / N;
    const q = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    [q[0], q[1], q[2], q[0], q[2], q[3]].forEach(p =>
      v.push(p[0], heightAt(p[0], p[1]) + 0.06, p[1], 0, 1, 0, 0, 0));
  }
  const b = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STREAM_DRAW);
  gl.vertexAttribPointer(L.aP, 3, gl.FLOAT, false, 32, 0);
  gl.vertexAttribPointer(L.aN, 3, gl.FLOAT, false, 32, 12);
  gl.vertexAttribPointer(L.aU, 2, gl.FLOAT, false, 32, 24);
  gl.uniform3f(L.uT, 0, 0, 0); gl.uniform1f(L.uRot, 0);
  gl.uniform4fv(L.uCol, col); gl.uniform1f(L.uLit, 0); gl.uniform1i(L.uTexOn, 0);
  gl.drawArrays(gl.TRIANGLES, 0, v.length / 8);
  gl.deleteBuffer(b);
}

function items3() {
  // items() in canvas world (8/tile) -> tile units for the 3D scene
  return items().map(it => ({ ...it, tx: it.x / 8, tz: it.z / 8 }));
}

function instYaw(r1) {
  let rot = (r1 >>> 16) & 0xfff;
  const p6 = (r1 << 16) >> 16;
  if (Math.abs(p6) > 500) rot = (0x800 - rot) & 0xfff;
  return rot / 4096 * 6.2832;
}

function frame() {
  if (!E3.on) return;
  E3.raf = requestAnimationFrame(frame);
  render();
}
setInterval(() => { if (E3.on && E3.gl) try { render(); } catch (e) { console.error(e); } }, 250);

function render() {
  const gl = E3.gl, L = E3.loc, c = E3.cv;
  if (!gl || !store.lvl) return;
  if (E3.entry !== store.entry) load();
  const w = c.clientWidth, h = c.clientHeight, dpr = window.devicePixelRatio || 1;
  if (c.width !== w * dpr || c.height !== h * dpr) { c.width = w * dpr; c.height = h * dpr; }
  gl.viewport(0, 0, c.width, c.height);
  gl.clearColor(0.075, 0.08, 0.10, 1);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  const m = vp(w, h);
  gl.uniformMatrix4fv(L.uVP, false, m);
  E3.vp = m;
  gl.enableVertexAttribArray(L.aP);
  gl.enableVertexAttribArray(L.aN);
  gl.enableVertexAttribArray(L.aU);
  if (E3.terr) {
    gl.bindBuffer(gl.ARRAY_BUFFER, E3.terr.vbo);
    gl.vertexAttribPointer(L.aP, 3, gl.FLOAT, false, 32, 0);
    gl.vertexAttribPointer(L.aN, 3, gl.FLOAT, false, 32, 12);
    gl.vertexAttribPointer(L.aU, 2, gl.FLOAT, false, 32, 24);
    gl.uniform3f(L.uT, 0, 0, 0); gl.uniform1f(L.uRot, 0); gl.uniform1f(L.uLit, 1);
    gl.uniform4f(L.uCol, 1, 1, 1, 1);
    if (E3.ground) { gl.uniform1i(L.uTexOn, 1); gl.bindTexture(gl.TEXTURE_2D, E3.ground); }
    else { gl.uniform1i(L.uTexOn, 0); gl.uniform4f(L.uCol, 0.22, 0.28, 0.2, 1); }
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, E3.terr.ibo);
    gl.drawElements(gl.TRIANGLES, E3.terr.n, gl.UNSIGNED_SHORT, 0);
  }
  const list = items3();
  // real models for instances
  if (store.view.layers.obj) {
    for (const it of list) {
      if (it.k !== 'in') continue;
      const name = (store.lvl.models[it.m] || '').toUpperCase();
      const ms = E3.models && E3.models[name];
      const y = (it.alt || 0) / 8;
      const yaw = instYaw(it.rot);
      if (ms) for (const b of ms)
        drawMesh(b, it.tx, y, it.tz, yaw, b.col, b.tex ? E3.texs[b.tex] : null, true);
      else drawMesh(E3.gizmo.box, it.tx, y, it.tz, yaw, [0.55, 0.55, 0.6, 1], null, true);
    }
  }
  // gizmos
  const sel = store.sel;
  for (const it of list) {
    const isSel = sel && sel.k === it.k && sel.i === it.i;
    if (it.k === 's0') {
      const tc = TCOLS[it.i % TCOLS.length];
      drapedQuad(it.tx, it.tz, 2, [tc[0] / 255, tc[1] / 255, tc[2] / 255, isSel ? 0.75 : 0.45]);
    } else if (it.k === 'cz') {
      drapedQuad(it.tx, it.tz, 4, [1, 0.62, 0.1, isSel ? 0.5 : 0.22]);
    } else if (it.k === 's6') {
      drawMesh(E3.gizmo.cone, it.tx, heightAt(it.tx, it.tz), it.tz, 0,
        [0.98, 0.79, 0.14, isSel ? 1 : 0.85], null, true);
    } else if (it.k === 'tr') {
      // spawn yaw = (-rot)^0x800 -> rot+0x800 in our Y-up frame
      const yaw = (((it.rot & 4095) + 2048) & 4095) / 4096 * 6.2832;
      const y = heightAt(it.tx, it.tz);
      const type = store.ed.extra ? store.ed.extra[it.i][5] : -1;
      const dat = store.cat.staticModels && store.cat.staticModels[type];
      const gm = dat ? globalMesh(dat) : null;
      if (gm) {
        for (const b of gm)
          drawMesh(b, it.tx, y, it.tz, yaw, b.col, b.tex ? GLB.texs.get(b.tex) : null, true);
        if (isSel) drawMesh(E3.gizmo.cyl, it.tx, y, it.tz, 0, [0, 0.82, 0.83, 0.3], null, false);
      } else {
        drawMesh(E3.gizmo.cyl, it.tx, y, it.tz, yaw,
          [0, 0.82, 0.83, isSel ? 1 : 0.85], null, true);
      }
    }
  }
  // extra PLD sections as small colored cones
  const tos16v = x => (x >= 32768 ? x - 65536 : x);
  const f = x => 32 + tos16v(x) / 512;
  for (const s of store.lvl.pld) {
    if (!store.view.sections.has(s.i) || !s.pts.length || s.i === 0) continue;
    const col = SEC_COLORS[s.i];
    const rgb = [parseInt(col.slice(1, 3), 16) / 255, parseInt(col.slice(3, 5), 16) / 255,
                 parseInt(col.slice(5, 7), 16) / 255, 0.9];
    for (const p of s.pts) {
      let tx, tz;
      if ([1, 2, 4, 14, 15].includes(s.i)) { tx = f(p[0]); tz = f(p[2] !== undefined ? p[2] : p[1]); }
      else { tx = p[0] / 2048; tz = p[1] / 2048; }
      if (tx < 0 || tx > 64 || tz < 0 || tz > 64) continue;
      drawMesh(E3.gizmo.cone, tx, heightAt(tx, tz), tz, 0, rgb, null, true);
    }
  }
  // selection beacon
  if (sel) {
    const it = list.find(o => o.k === sel.k && o.i === sel.i);
    if (it) {
      const y = heightAt(it.tx, it.tz);
      drawMesh(E3.gizmo.box, it.tx, y, it.tz, 0, [1, 1, 1, 0.35], null, false);
      gl.depthMask(false);
      drawMesh(E3.gizmo.cyl, it.tx, y, it.tz, 0, [1, 1, 1, 0.18], null, false);
      gl.depthMask(true);
    }
  }
  // brush ring (heights tool)
  if (store.tool === 'height' && E3.brushPos) {
    gl.depthMask(false);
    drapedRing(E3.brushPos[0], E3.brushPos[1], brush.radius, [1, 1, 1, 0.7]);
    gl.depthMask(true);
  }
}

function drapedRing(cx, cz, r, col) {
  const gl = E3.gl, L = E3.loc, N = 40, v = [], w = 0.08;
  for (let i = 0; i < N; i++) {
    const a = i / N * 6.2832, b = (i + 1) / N * 6.2832;
    const p = [[cx + Math.cos(a) * (r - w), cz + Math.sin(a) * (r - w)],
               [cx + Math.cos(a) * (r + w), cz + Math.sin(a) * (r + w)],
               [cx + Math.cos(b) * (r + w), cz + Math.sin(b) * (r + w)],
               [cx + Math.cos(b) * (r - w), cz + Math.sin(b) * (r - w)]];
    [p[0], p[1], p[2], p[0], p[2], p[3]].forEach(q =>
      v.push(q[0], heightAt(q[0], q[1]) + 0.1, q[1], 0, 1, 0, 0, 0));
  }
  const b2 = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, b2);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STREAM_DRAW);
  gl.vertexAttribPointer(L.aP, 3, gl.FLOAT, false, 32, 0);
  gl.vertexAttribPointer(L.aN, 3, gl.FLOAT, false, 32, 12);
  gl.vertexAttribPointer(L.aU, 2, gl.FLOAT, false, 32, 24);
  gl.uniform3f(L.uT, 0, 0, 0); gl.uniform1f(L.uRot, 0);
  gl.uniform4fv(L.uCol, col); gl.uniform1f(L.uLit, 0); gl.uniform1i(L.uTexOn, 0);
  gl.drawArrays(gl.TRIANGLES, 0, v.length / 8);
  gl.deleteBuffer(b2);
}

// ---------------------------------------------------------------- input ----
function pick3(mx, my) {
  const w = E3.cv.clientWidth, h = E3.cv.clientHeight;
  let best = null, bd = 26;
  for (const it of items3()) {
    if (it.k === 'in' && !store.view.layers.obj) continue;
    const y = it.k === 'in' ? (it.alt || 0) / 8 : heightAt(it.tx, it.tz);
    const p = project([it.tx, y + 0.4, it.tz], E3.vp, w, h);
    if (!p) continue;
    const d = Math.hypot(p[0] - mx, p[1] - my) * (it.k === 'in' ? 1.25 : 1);
    if (d < bd) { bd = d; best = it; }
  }
  return best;
}

function input() {
  const c = E3.cv;
  let mode = null, sx = 0, sy = 0, moved = 0;
  c.addEventListener('contextmenu', e => e.preventDefault());
  c.addEventListener('mousedown', e => {
    const r = c.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    sx = mx; sy = my; moved = 0;
    if (e.button === 1 || e.shiftKey) { mode = 'pan'; return; }
    if (e.button === 2) {
      if (CAT.pending) { CAT.cancel(); return; }   // right-click stops placing
      mode = 'orbit'; return;
    }
    if (CAT.pending) {
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight);
      if (g && isFinite(g[0]))
        CAT.placeAt(Math.max(0, Math.min(512, g[0] * 8)), Math.max(0, Math.min(512, g[1] * 8)));
      return;
    }
    if (store.tool === 'height') {
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight);
      if (g) {
        mode = 'sculpt';
        E3.sculptY = heightAt(g[0], g[1]);   // stable picking plane for the stroke
        beginStroke(g[0], g[1], e.altKey);
      }
      return;
    }
    if (store.tool === 'tiles') {
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight);
      if (g && isFinite(g[0])) {
        if (TL.T.mode === 'pick' || e.altKey) {
          TL.readTile(g[0], g[1]);
          store.emit('stamp');
        } else if (TL.T.mode === 'clone') {
          if (!TL.T.cloneSrc) { TL.T.cloneSrc = [g[0], g[1]]; store.say('clone source set.'); }
          else {
            TL.T.cloneDelta = [Math.floor(TL.T.cloneSrc[0]) - Math.floor(g[0]),
                               Math.floor(TL.T.cloneSrc[1]) - Math.floor(g[1])];
            mode = 'tilepaint';
            store.beginGesture();
            TL.paintAt(g[0], g[1]);
          }
        } else if (TL.T.mode === 'paint') {
          mode = 'tilepaint';
          store.beginGesture();
          TL.paintAt(g[0], g[1]);
        } else if (TL.T.mode === 'paste') {
          TL.pasteRegion(g[0], g[1]);
        } else store.say('fill/copy rectangles work in the 2D view — paint and paste work here.');
      }
      return;
    }
    const it = pick3(mx, my);
    if (it) {
      mode = 'move';
      store.beginGesture();           // one undo step per marker drag
      E3.drag = { it, py: it.k === 'in' ? (it.alt || 0) / 8 : heightAt(it.tx, it.tz) };
      store.apply(s => { s.sel = { k: it.k, i: it.i }; }, 'select');
    } else mode = 'orbit';
  });
  window.addEventListener('mousemove', e => {
    if (!E3.on || !E3.vp || !E3.tanF) return;
    const r = c.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    if (E3.statusPos && e.target === c) {
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight);
      if (g && isFinite(g[0])) E3.statusPos.textContent =
        `tile (${g[0].toFixed(2)}, ${g[1].toFixed(2)})  world (${(g[0] * 8).toFixed(0)}, ${(g[1] * 8).toFixed(0)})  h=${heightAt(g[0], g[1]).toFixed(1)}`;
      E3.brushPos = (store.tool === 'height' && g && isFinite(g[0])) ? g : null;
    }
    if (mode === 'sculpt') {
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight, E3.sculptY);
      if (g && isFinite(g[0])) {
        E3.brushPos = g;
        moveStroke(Math.max(0, Math.min(64, g[0])), Math.max(0, Math.min(64, g[1])), e.altKey);
      }
      return;
    }
    if (mode === 'tilepaint') {
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight);
      if (g && isFinite(g[0])) TL.paintAt(g[0], g[1]);
      return;
    }
    if (!mode) return;
    const dx = mx - sx, dy = my - sy;
    moved += Math.abs(dx) + Math.abs(dy); sx = mx; sy = my;
    const cam = E3.cam;
    if (mode === 'orbit') {
      cam.yaw -= dx * 0.008;
      cam.pitch = Math.max(0.15, Math.min(1.45, cam.pitch + dy * 0.006));
      saveCam();
    } else if (mode === 'pan') {
      const k = cam.dist * 0.0016;
      cam.tx -= E3.right[0] * dx * k; cam.tz -= E3.right[2] * dx * k;
      const fx = E3.fwd[0], fz = E3.fwd[2], fl = Math.hypot(fx, fz) || 1;
      cam.tx += fx / fl * dy * k; cam.tz += fz / fl * dy * k;
      cam.tx = Math.max(0, Math.min(64, cam.tx));
      cam.tz = Math.max(0, Math.min(64, cam.tz));
    } else if (mode === 'move' && E3.drag) {
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight, E3.drag.py);
      if (g) {
        const tx = Math.max(0, Math.min(64, g[0])), tz = Math.max(0, Math.min(64, g[1]));
        store.apply(() => moveItem(E3.drag.it, tx * 8, tz * 8));
      }
    }
  });
  window.addEventListener('mouseup', e => {
    if (mode === 'sculpt') { endStroke(); mode = null; return; }
    if (mode === 'tilepaint') { store.endGesture(); TL.T.cloneDelta = null; mode = null; return; }
    if (mode === 'move') store.endGesture();
    if (mode === 'orbit' && moved < 5 && E3.on && e.target === c) {
      const r = c.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      const g = groundHit(mx, my, c.clientWidth, c.clientHeight);
      if (g) {
        const l = store.lvl;
        const s = `TB-POS3D lvl=${l.entry} ${l.name} tile=(${g[0].toFixed(2)},${g[1].toFixed(2)})`
          + ` data=(${(g[0] * 8).toFixed(0)},${(512 - g[1] * 8).toFixed(0)})`
          + ` halfTileCentered=(${((g[0] - 32) * 2).toFixed(1)},${((g[1] - 32) * 2).toFixed(1)})`;
        if (navigator.clipboard) navigator.clipboard.writeText(s).catch(() => {});
        store.say('📋 ' + s);
      }
    }
    mode = null; E3.drag = null;
  });
  c.addEventListener('wheel', e => {
    e.preventDefault();
    E3.cam.dist = Math.max(4, Math.min(160, E3.cam.dist * (1 + Math.sign(e.deltaY) * 0.09)));
    saveCam();
  }, { passive: false });
}
