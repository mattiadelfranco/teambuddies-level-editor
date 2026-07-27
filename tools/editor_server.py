#!/usr/bin/env python3
"""
Team Buddies - Server dell'editor livelli.

Serve l'editor HTML e applica le modifiche ai file di gioco:
  GET  /            -> editor.html (rigenerato a ogni avvio da build_editor.py)
  POST /api/save    -> salva le modifiche di un livello in mods/<entry>/
  POST /api/build   -> repack di tutti i livelli modificati + rebuild ISO

Uso:  python3 tools/editor_server.py   (poi apri http://localhost:8787)
"""
import json, os, shutil, struct, subprocess, sys
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIND = os.path.join(ROOT, "teambudd/dat_estratto/bind")
MODS = os.path.join(ROOT, "teambudd/mods")
DAT = os.path.join(ROOT, "teambudd/estratto/BUDDIES.DAT")
DAT_ORIG = DAT + ".orig"
MANIFEST = os.path.join(ROOT, "teambudd/dat_estratto/manifest.tsv")
EDITOR_HTML = os.path.join(ROOT, "teambudd/editor.html")



def _tiles_layout(d):
    """Ritorna (off_extra, extra_cnt, off_heightmap, off_tiles) del PND."""
    n_names, n_inst, _, _ = struct.unpack_from("<4H", d, 4)
    off_extra = 12 + n_names * 32 + n_inst * 20
    extra_cnt = struct.unpack_from("<H", d, off_extra)[0]
    off_hm = off_extra + 2 + extra_cnt * 20
    off_tiles = off_hm + 65 * 65 * 2
    return off_extra, extra_cnt, off_hm, off_tiles


def _repaint_pad(d, off_hm, off_tiles, old_c, new_c):
    """Sposta i 4 tile dipinti della pedana da old_c a new_c (centri tile x.5)
    e spiana il terreno sotto la nuova posizione."""
    from collections import Counter

    def block(c):
        # impronta completa della pedana: 4x4 (cornice di frecce + centro 2x2)
        x, z = int(c[0] - 0.5) - 1, int(c[1] - 0.5) - 1
        return [(x + i, z + j) for j in range(4) for i in range(4)]

    def rd(x, z):
        o = off_tiles + (z * 64 + x) * 28
        return bytes(d[o:o + 28])

    def wr(x, z, rec):
        o = off_tiles + (z * 64 + x) * 28
        d[o:o + 28] = rec

    old_b, new_b = block(old_c), block(new_c)
    if any(not (0 <= x < 64 and 0 <= z < 64) for x, z in old_b + new_b):
        return
    pad_recs = [rd(x, z) for x, z in old_b]
    # tappo d'erba sul vecchio blocco, pedana dipinta sul nuovo
    x0, z0 = old_b[0]
    per = [rd(x, z) for x in range(x0 - 1, x0 + 5) for z in range(z0 - 1, z0 + 5)
           if (x, z) not in old_b and 0 <= x < 64 and 0 <= z < 64]
    filler = Counter(per).most_common(1)[0][0]
    for x, z in old_b:
        wr(x, z, filler)
    for (x, z), rec in zip(new_b, pad_recs):
        wr(x, z, rec)
    # rimappa le VOCI DI ANIMAZIONE (frecce animate del centro pedana):
    # coda a tiles+131072 (il motore riserva 32B/tile): [s16 n_tex][n_tex*12B]
    # [u16 n_desc][n_desc*16B, campo 0 = indice tile]
    nx0, nz0 = new_b[0]
    anim = off_tiles + 131072
    if anim + 2 <= len(d):
        n1 = struct.unpack_from("<h", d, anim)[0]
        o2 = anim + 2 + max(n1, 0) * 12
        if 0 <= n1 < 2000 and o2 + 2 <= len(d):
            n2 = struct.unpack_from("<H", d, o2)[0]
            old_map = {t: i for i, t in enumerate(old_b)}
            for i in range(min(n2, 2000)):
                pp = o2 + 2 + i * 16
                if pp + 2 > len(d):
                    break
                idx = struct.unpack_from("<H", d, pp)[0]
                t = (idx % 64, idx // 64)
                if t in old_map:
                    k = old_map[t]
                    nx, nz = new_b[k]
                    struct.pack_into("<H", d, pp, nz * 64 + nx)
    # spiana i 9 vertici del nuovo blocco all'altezza mediana
    vx, vz = new_b[0]
    hs = []
    for zz in range(vz, vz + 5):
        for xx in range(vx, vx + 5):
            hs.append(struct.unpack_from("<h", d, off_hm + (zz * 65 + xx) * 2)[0])
    med = sorted(hs)[len(hs) // 2]
    for zz in range(vz, vz + 5):
        for xx in range(vx, vx + 5):
            struct.pack_into("<h", d, off_hm + (zz * 65 + xx) * 2, med)


def apply_edits(entry, edits):
    """Applica il JSON di modifiche al livello: copia bind/<entry> in mods/<entry>
    e patcha PLD (s0, s6) e PND (istanze, lista extra torrette)."""
    src = os.path.join(BIND, entry)
    dst = os.path.join(MODS, entry)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    pld_path = next(os.path.join(dst, f) for f in os.listdir(dst) if f.endswith(".PLD"))
    pnd_path = next(os.path.join(dst, f) for f in os.listdir(dst) if f.endswith(".PND"))

    # --- PLD ---
    d = bytearray(open(pld_path, "rb").read())
    offs = list(struct.unpack_from("<17I", d, 8))

    # s0: lista [x,z,w,h] in mezzi-tile centro-relativi (float) -> 8.8 con segno
    if "s0" in edits:
        o = offs[0] + 8
        cnt = struct.unpack_from("<I", d, o)[0]
        recs = edits["s0"]
        if len(recs) != cnt:
            raise ValueError(f"s0: numero record non modificabile ({len(recs)} vs {cnt})")
        for i, r in enumerate(recs):
            vals = [int(round(v * 256)) & 0xffff for v in r]
            struct.pack_into("<4H", d, o + 4 + i * 8, *vals)

    # s6: {extra: int, records: [[tipo, team, var, x, z], ...]} - lunghezza libera:
    # la sezione viene ricostruita e le sezioni successive (s7..s16) shiftate
    # aggiornando la tabella dei 17 offset (le sezioni sono fisicamente in ordine)
    if "s6" in edits:
        o = offs[6] + 8
        cnt, extra = struct.unpack_from("<2H", d, o)
        recs = edits["s6"]["records"]
        for r in recs:
            if not 0 <= int(r[0]) <= 61:
                raise ValueError(f"s6: tipo {r[0]} fuori dallo spazio-62 (0-61): crash garantito in gioco")
        payload = bytearray(struct.pack("<2H", len(recs), edits["s6"].get("extra", extra)))
        for r in recs:
            tipo, team, var, x, z = r
            tv = (team & 0xff) | ((var & 0xff) << 8)
            xv = int(round(x * 256)) & 0xffff
            zv = int(round(z * 256)) & 0xffff
            payload += struct.pack("<4H", int(tipo), tv, xv, zv)
        old_size = 4 + cnt * 8
        delta = len(payload) - old_size
        d[o:o + old_size] = payload
        if delta:
            offs = [v + delta if v > offs[6] else v for v in offs]
            struct.pack_into("<17I", d, 8, *offs)
    open(pld_path, "wb").write(d)

    # --- PND ---
    d = bytearray(open(pnd_path, "rb").read())
    n_names, n_inst, _, _ = struct.unpack_from("<4H", d, 4)
    base = 12 + n_names * 32

    # istanze, lista completa [[modello, x, alt, z, e, r1, r2], ...]: sostituisce
    # tutta la lista (aggiunta/rimozione/spostamento in un colpo solo; il resto
    # del PND si legge in sequenza, quindi lo splice basta)
    if "instFull" in edits:
        recs = edits["instFull"]
        for r in recs:
            if not 0 <= int(r[0]) < n_names:
                raise ValueError(f"istanza: modello {r[0]} fuori range (0-{n_names - 1})")
        new = b"".join(struct.pack("<Ihhhhii", int(r[0]),
                                   *[int(round(v)) for v in r[1:7]]) for r in recs)
        d[base:base + n_inst * 20] = new
        n_inst = len(recs)
        struct.pack_into("<H", d, 6, n_inst)
    else:
        # retrocompatibilità: spostamenti puntuali {i, x, z} in coordinate istanza
        for mv in edits.get("inst", []):
            o = base + mv["i"] * 20
            struct.pack_into("<h", d, o + 4, int(round(mv["x"])))
            struct.pack_into("<h", d, o + 8, int(round(mv["z"])))

    # lista extra (torrette): lista di record [10 u16] completi (sostituisce tutta la lista)
    if "extra" in edits:
        o = base + n_inst * 20
        old_cnt = struct.unpack_from("<H", d, o)[0]
        recs = edits["extra"]
        new = struct.pack("<H", len(recs)) + b"".join(struct.pack("<10H", *r) for r in recs)
        old_size = 2 + old_cnt * 20
        d[o:o + old_size] = new

    # ridipintura pedane: per ogni record s0 spostato, sposta anche i 4 tile
    # dipinti e spiana il terreno nella nuova posizione
    if "s0" in edits:
        orig = open(os.path.join(BIND, entry, os.path.basename(pld_path)), "rb").read()
        ooffs = struct.unpack_from("<17I", orig, 8)
        oo = ooffs[0] + 8
        ocnt = struct.unpack_from("<I", orig, oo)[0]
        _, _, off_hm, off_tiles = _tiles_layout(d)
        for i, r in enumerate(edits["s0"][:ocnt]):
            ox, oz = struct.unpack_from("<2H", orig, oo + 4 + i * 8)
            def st(v):
                return (v - 65536 if v >= 32768 else v) / 256
            old_c = (32 + st(ox) / 2, 32 + st(oz) / 2)
            new_c = (32 + r[0] / 2, 32 + r[1] / 2)
            if abs(old_c[0] - new_c[0]) > 0.01 or abs(old_c[1] - new_c[1]) > 0.01:
                _repaint_pad(d, off_hm, off_tiles, old_c, new_c)
    open(pnd_path, "wb").write(d)
    return {"ok": True}


def build_iso():
    """Applica i mods al DAT (in-place o ricollocando in coda, senza limiti di slot),
    patcha ENG.BIN (campo team lista extra) e ricostruisce l'ISO."""
    log = []
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/tb_patch_eng.py")],
                       capture_output=True, text=True)
    log.append(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        return {"ok": False, "log": log}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/tb_rebuild.py"),
                        DAT_ORIG, MODS, DAT, MANIFEST],
                       capture_output=True, text=True)
    log.append(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        return {"ok": False, "log": log}
    mk = os.path.join(ROOT, "mkpsxiso/build/mkpsxiso")
    if not os.path.exists(mk):
        log.append("mkpsxiso non trovato: esegui prima `python3 tools/setup.py`")
        return {"ok": False, "log": log}
    r = subprocess.run([mk, "-y",
                        "-o", "rebuild.bin", "-c", "rebuild.cue", "teambuddies.xml"],
                       cwd=os.path.join(ROOT, "teambudd"), capture_output=True, text=True)
    ok = "successfully" in r.stdout
    log.append(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
    return {"ok": ok, "log": log}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/editor"):
            b = open(EDITOR_HTML, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            self._json({"err": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if self.path == "/api/save":
                os.makedirs(MODS, exist_ok=True)
                res = apply_edits(body["entry"], body["edits"])
                # rigenera terreno+pagina in background (ricarica la pagina per vederlo)
                import threading
                if globals().get("_refreshing"):
                    globals()["_pending"] = True
                else:
                    globals()["_refreshing"] = True
                    def _rf():
                        while True:
                            globals()["_pending"] = False
                            subprocess.run([sys.executable, os.path.join(ROOT, "tools/build_editor.py")], cwd=ROOT)
                            if not globals().get("_pending"):
                                break
                        globals()["_refreshing"] = False
                    threading.Thread(target=_rf, daemon=True).start()
                res["nota"] = "terreno in rigenerazione: ricarica la pagina tra ~30s per vedere la ridipintura"
                self._json(res)
            elif self.path == "/api/build":
                self._json(build_iso())
            else:
                self._json({"err": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "err": str(e)}, 500)


if __name__ == "__main__":
    subprocess.run([sys.executable, os.path.join(ROOT, "tools/build_editor.py")], cwd=ROOT)
    print("Editor: http://localhost:8787  (Ctrl+C per uscire)")
    HTTPServer(("127.0.0.1", 8787), H).serve_forever()
