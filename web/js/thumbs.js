// WebGL thumbnail renderer for catalog previews. Own tiny GL context (96px),
// consumes the same mesh JSON as view3d (api.models3d / api.global3d) and
// returns dataURL images, cached by key.
import { api } from './api.js';

const SIZE = 96;
let gl = null, pr = null, loc = null, cv = null;
const done = new Map();          // key -> dataURL
const texCache = new Map();      // dataURI -> WebGLTexture

function init() {
  if (gl) return;
  cv = document.createElement('canvas');
  cv.width = cv.height = SIZE;
  gl = cv.getContext('webgl', { preserveDrawingBuffer: true, antialias: true });
  const vs = `attribute vec3 aP;attribute vec3 aN;attribute vec2 aU;
    uniform mat4 uVP;varying vec2 vU;varying vec3 vN;
    void main(){vU=aU;vN=aN;gl_Position=uVP*vec4(aP,1.0);}`;
  const fs = `precision mediump float;
    uniform bool uTexOn;uniform sampler2D uTex;uniform vec4 uCol;
    varying vec2 vU;varying vec3 vN;
    void main(){vec4 c=uCol;
    if(uTexOn){vec4 t=texture2D(uTex,vU);if(t.a<0.5)discard;c=vec4(c.rgb*t.rgb,c.a);}
    vec3 L=normalize(vec3(0.4,0.8,0.45));
    float l=0.62+0.38*max(dot(normalize(vN),L),0.0);
    gl_FragColor=vec4(c.rgb*l,1.0);}`;
  const sh = (t, s) => {
    const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x); return x;
  };
  pr = gl.createProgram();
  gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(pr); gl.useProgram(pr);
  loc = { aP: gl.getAttribLocation(pr, 'aP'), aN: gl.getAttribLocation(pr, 'aN'),
          aU: gl.getAttribLocation(pr, 'aU'), uVP: gl.getUniformLocation(pr, 'uVP'),
          uTexOn: gl.getUniformLocation(pr, 'uTexOn'), uCol: gl.getUniformLocation(pr, 'uCol') };
  gl.enable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);
}

function texFor(uri) {
  return new Promise(res => {
    if (texCache.has(uri)) return res(texCache.get(uri));
    const im = new Image();
    im.onload = () => {
      const t = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, im);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      texCache.set(uri, t);
      res(t);
    };
    im.onerror = () => res(null);
    im.src = uri;
  });
}

// isometric-ish view fitted to the model bounds
function fitVP(batches) {
  let mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  for (const b of batches) for (let i = 0; i < b.p.length; i += 3)
    for (let k = 0; k < 3; k++) {
      if (b.p[i + k] < mn[k]) mn[k] = b.p[i + k];
      if (b.p[i + k] > mx[k]) mx[k] = b.p[i + k];
    }
  const c = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2];
  const r = Math.max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) / 2 || 1;
  const d = r * 2.6, ya = Math.PI / 4, pa = 0.42;
  const eye = [c[0] + d * Math.cos(pa) * Math.sin(ya), c[1] + d * Math.sin(pa),
               c[2] + d * Math.cos(pa) * Math.cos(ya)];
  const f = [c[0] - eye[0], c[1] - eye[1], c[2] - eye[2]];
  const fl = Math.hypot(...f); f[0] /= fl; f[1] /= fl; f[2] /= fl;
  // right = cross(f, up) — same convention as view3d (the mirrored basis of
  // the first version rendered every thumbnail upside down)
  const s = [-f[2], 0, f[0]];
  const sl = Math.hypot(...s) || 1; s[0] /= sl; s[2] /= sl;
  const u = [s[1] * f[2] - s[2] * f[1], s[2] * f[0] - s[0] * f[2], s[0] * f[1] - s[1] * f[0]];
  const V = [s[0], u[0], -f[0], 0, s[1], u[1], -f[1], 0, s[2], u[2], -f[2], 0,
    -(s[0] * eye[0] + s[1] * eye[1] + s[2] * eye[2]),
    -(u[0] * eye[0] + u[1] * eye[1] + u[2] * eye[2]),
    (f[0] * eye[0] + f[1] * eye[1] + f[2] * eye[2]), 1];
  const n = d - r * 1.6, fa = d + r * 2, t = r * 1.15 / (d - r) * n;
  const P = [n / t, 0, 0, 0, 0, n / t, 0, 0, 0, 0, -(fa + n) / (fa - n), -1,
             0, 0, -2 * fa * n / (fa - n), 0];
  const o = new Float32Array(16);
  for (let rr = 0; rr < 4; rr++) for (let cc = 0; cc < 4; cc++) {
    let sum = 0;
    for (let k = 0; k < 4; k++) sum += P[k * 4 + cc] * V[rr * 4 + k];
    o[rr * 4 + cc] = sum;
  }
  return o;
}

// the GL context is shared: renders MUST NOT interleave (an await mid-draw
// would let another thumb rebind buffers/uniforms) -> serialize on a queue
// and load every texture BEFORE issuing the draw calls.
let queue = Promise.resolve();
function render(batches, texMap) {
  const job = queue.then(async () => {
    init();
    const texs = {};
    for (const b of batches)
      if (b.t && texMap[b.t] && !(b.t in texs)) texs[b.t] = await texFor(texMap[b.t]);
    gl.viewport(0, 0, SIZE, SIZE);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.uniformMatrix4fv(loc.uVP, false, fitVP(batches));
    gl.enableVertexAttribArray(loc.aP);
    gl.enableVertexAttribArray(loc.aN);
    gl.enableVertexAttribArray(loc.aU);
    for (const b of batches) {
      const n = b.p.length / 3, arr = new Float32Array(n * 8);
      for (let i = 0; i < n; i++)
        arr.set([b.p[3 * i], b.p[3 * i + 1], b.p[3 * i + 2],
                 b.n[3 * i], b.n[3 * i + 1], b.n[3 * i + 2],
                 b.u[2 * i], b.u[2 * i + 1]], i * 8);
      const vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
      gl.vertexAttribPointer(loc.aP, 3, gl.FLOAT, false, 32, 0);
      gl.vertexAttribPointer(loc.aN, 3, gl.FLOAT, false, 32, 12);
      gl.vertexAttribPointer(loc.aU, 2, gl.FLOAT, false, 32, 24);
      gl.uniform4f(loc.uCol, b.c[0] / 128, b.c[1] / 128, b.c[2] / 128, 1);
      const t = texs[b.t];
      if (t) { gl.uniform1i(loc.uTexOn, 1); gl.bindTexture(gl.TEXTURE_2D, t); }
      else gl.uniform1i(loc.uTexOn, 0);
      gl.drawArrays(gl.TRIANGLES, 0, n);
      gl.deleteBuffer(vbo);
    }
    return cv.toDataURL();
  });
  queue = job.catch(() => {});
  return job;
}

// thumbnail of a LEVEL model (by name) — key: entry/model
export async function levelModelThumb(entry, name) {
  const key = entry + '/' + name.toUpperCase();
  if (done.has(key)) return done.get(key);
  const p = (async () => {
    const j = await api.models3d(entry);
    const b = j.models[name.toUpperCase()];
    return b ? render(b, j.tex) : null;
  })();
  done.set(key, p);
  return p;
}

// thumbnail of a GLOBAL model (turrets, buddies): key: dat entry.
// A folder can hold several LODs (ninja + katana): pick the biggest one.
export async function globalThumb(dat) {
  const key = 'g' + dat;
  if (done.has(key)) return done.get(key);
  const p = (async () => {
    const j = await api.global3d(dat);
    let best = null, bn = 0;
    for (const b of Object.values(j.models)) {
      const n = b.reduce((s, x) => s + x.p.length, 0);
      if (n > bn) { bn = n; best = b; }
    }
    return best ? render(best, j.tex) : null;
  })();
  done.set(key, p);
  return p;
}
