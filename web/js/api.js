// Thin fetch wrappers for the editor server API.
async function j(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json();
  if (!r.ok) throw new Error(body.err || r.statusText);
  return body;
}

const cache = new Map();
function cached(url) {
  if (!cache.has(url)) cache.set(url, j(url).catch(e => { cache.delete(url); throw e; }));
  return cache.get(url);
}

export const api = {
  levels: () => j('/api/levels'),
  catalogs: () => j('/api/catalogs'),
  level: entry => j('/api/level/' + entry),
  mission: entry => j('/api/mission/' + entry),
  models3d: entry => cached('/api/3d/' + entry),
  global3d: dat => cached('/api/global3d/' + dat),
  groundUrl: entry => '/ground3d/' + entry + '.png?v=' + Date.now(),
  save: (entry, edits) => j('/api/save', { method: 'POST', body: JSON.stringify({ entry, edits }) }),
  build: () => j('/api/build', { method: 'POST', body: '{}' }),
};

export function b64i16(s) {
  const b = atob(s), n = b.length / 2, a = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    let v = b.charCodeAt(2 * i) | (b.charCodeAt(2 * i + 1) << 8);
    if (v > 32767) v -= 65536;
    a[i] = v;
  }
  return a;
}

export function b64u8(s) {
  const b = atob(s), a = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) a[i] = b.charCodeAt(i);
  return a;
}
