#!/usr/bin/env python3
"""
Team Buddies - Server dell'editor livelli.

Serve l'editor HTML e applica le modifiche ai file di gioco:
  GET  /            -> editor.html (rigenerato a ogni avvio da build_editor.py)
  POST /api/save    -> salva le modifiche di un livello in mods/<entry>/
  POST /api/build   -> repack di tutti i livelli modificati + rebuild ISO

Uso:  python3 tools/editor_server.py   (poi apri http://localhost:8787)
"""
import base64, json, os, shutil, struct, subprocess, sys
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tb_lod
import tb_level

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIND = os.path.join(ROOT, "teambudd/dat_estratto/bind")
MODS = os.path.join(ROOT, "teambudd/mods")
DAT = os.path.join(ROOT, "teambudd/estratto/BUDDIES.DAT")
DAT_ORIG = DAT + ".orig"
MANIFEST = os.path.join(ROOT, "teambudd/dat_estratto/manifest.tsv")
WEB = os.path.join(ROOT, "web")
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css",
        ".js": "text/javascript", ".png": "image/png", ".svg": "image/svg+xml"}



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


def _pad_block(c):
    """Impronta 4x4 della pedana centrata in c (centri tile x.5)."""
    x, z = int(c[0] - 0.5) - 1, int(c[1] - 0.5) - 1
    return [(x + i, z + j) for j in range(4) for i in range(4)]


def _anim_desc(d, off_tiles):
    """(offset lista desc, count) della coda animazioni, o None se non decodificabile."""
    anim = off_tiles + 131072
    if anim + 2 > len(d):
        return None
    n1 = struct.unpack_from("<h", d, anim)[0]
    o2 = anim + 2 + max(n1, 0) * 12
    if not (0 <= n1 < 2000 and o2 + 2 <= len(d)):
        return None
    n2 = struct.unpack_from("<H", d, o2)[0]
    if n2 > 2000 or o2 + 2 + n2 * 16 > len(d):
        return None
    return o2, n2


def _clone_pad(d, off_hm, off_tiles, src_c, dst_c):
    """Pedana NUOVA: copia i 16 tile dipinti da src_c a dst_c (src intatta),
    spiana il terreno sotto la destinazione e clona le voci animazione del
    centro 2x2 in coda alla lista desc. Ritorna il bytearray (il PND cresce)."""
    src_b, dst_b = _pad_block(src_c), _pad_block(dst_c)
    if any(not (0 <= x < 64 and 0 <= z < 64) for x, z in src_b + dst_b):
        return d
    for (sx, sz), (dx, dz) in zip(src_b, dst_b):
        so = off_tiles + (sz * 64 + sx) * 28
        do = off_tiles + (dz * 64 + dx) * 28
        d[do:do + 28] = d[so:so + 28]
    vx, vz = dst_b[0]
    hs = [struct.unpack_from("<h", d, off_hm + (zz * 65 + xx) * 2)[0]
          for zz in range(vz, vz + 5) for xx in range(vx, vx + 5)]
    med = sorted(hs)[len(hs) // 2]
    for zz in range(vz, vz + 5):
        for xx in range(vx, vx + 5):
            struct.pack_into("<h", d, off_hm + (zz * 65 + xx) * 2, med)
    al = _anim_desc(d, off_tiles)
    if al:
        o2, n2 = al
        anim = off_tiles + 131072
        n_tex = struct.unpack_from("<h", d, anim)[0]
        smap = {t: k for k, t in enumerate(src_b)}
        clones = []
        for i in range(n2):
            pp = o2 + 2 + i * 16
            idx = struct.unpack_from("<H", d, pp)[0]
            t = (idx % 64, idx // 64)
            if t in smap:
                rec = bytearray(d[pp:pp + 16])
                nx, nz = dst_b[smap[t]]
                struct.pack_into("<H", rec, 0, nz * 64 + nx)
                clones.append(rec)
        if clones:
            # ogni pedana deve avere le SUE run di frame animati: il ricolore
            # team (PADCLUTS, FUN_800a7ab0) riscrive la CLUT dei frame texture
            # (byte +7), non i tile — desc che condividono la run condividono
            # il colore (verificato in gioco: 3 pedane tutte dello stesso team).
            # desc: u16@+8 = n. frame, u32@+12 = indice frame di partenza.
            texblob = b""
            new_start = n_tex
            for rec in clones:
                nfr = struct.unpack_from("<H", rec, 8)[0]
                start = struct.unpack_from("<I", rec, 12)[0]
                if 0 < nfr <= 64 and start + nfr <= n_tex:
                    texblob += bytes(d[anim + 2 + start * 12:
                                       anim + 2 + (start + nfr) * 12])
                    struct.pack_into("<I", rec, 12, new_start)
                    new_start += nfr
            d[o2:o2] = texblob            # in coda alla tabella texture
            struct.pack_into("<h", d, anim, new_start)
            o2 += len(texblob)
            end = o2 + 2 + n2 * 16
            d[end:end] = b"".join(bytes(r) for r in clones)
            struct.pack_into("<H", d, o2, n2 + len(clones))
    return d


def _erase_pad(d, off_tiles, c):
    """Pedana ELIMINATA: tappo d'erba sui 16 tile dipinti e rimozione delle
    voci animazione del blocco. Ritorna il bytearray (il PND si accorcia)."""
    from collections import Counter
    b = _pad_block(c)
    if any(not (0 <= x < 64 and 0 <= z < 64) for x, z in b):
        return d
    x0, z0 = b[0]
    per = [bytes(d[off_tiles + (z * 64 + x) * 28:off_tiles + (z * 64 + x) * 28 + 28])
           for x in range(x0 - 1, x0 + 5) for z in range(z0 - 1, z0 + 5)
           if (x, z) not in b and 0 <= x < 64 and 0 <= z < 64]
    filler = Counter(per).most_common(1)[0][0]
    for x, z in b:
        o = off_tiles + (z * 64 + x) * 28
        d[o:o + 28] = filler
    al = _anim_desc(d, off_tiles)
    if al:
        o2, n2 = al
        bset = set(b)
        keep = []
        for i in range(n2):
            pp = o2 + 2 + i * 16
            idx = struct.unpack_from("<H", d, pp)[0]
            if (idx % 64, idx // 64) not in bset:
                keep.append(bytes(d[pp:pp + 16]))
        if len(keep) != n2:
            d[o2 + 2:o2 + 2 + n2 * 16] = b"".join(keep)
            struct.pack_into("<H", d, o2, len(keep))
    return d


def _parse_s3(d, offs):
    """Zone di lancio casse (sezione 3): [u32 n_zone][per zona: u32 n +
    n x u16 indici mezzi-tile griglia 128 (idx = hz*128 + hx, NON specchiata)
    + pad 2B se n dispari]. Ritorna (zone, off_sezione, off_fine)."""
    o = offs[3] + 8
    cnt = struct.unpack_from("<I", d, o)[0]
    p = o + 4
    zones = []
    for _ in range(cnt):
        n = struct.unpack_from("<I", d, p)[0]
        p += 4
        zones.append(list(struct.unpack_from(f"<{n}H", d, p)))
        p += n * 2 + (2 if n & 1 else 0)
    return zones, o, p


def _zone_center(idx):
    """Centro zona in tile (interi nei vanilla): blocco 4x4 mezzi-tile."""
    hx = [t % 128 for t in idx]
    hz = [t // 128 for t in idx]
    return ((min(hx) + max(hx) + 1) / 4, (min(hz) + max(hz) + 1) / 4)


def apply_zonecfg(mission, entries):
    """Config casse per-zona della missione (LEVELS.BIN, BIND 0955): entries =
    lista per-zona (ordine s3) di 10 interi [tipo0,tipo1,init0,init1,tgt0,tgt1,
    rate0,rate1,a0,a1] oppure None = default motore (ammesso solo in coda).
    Le voci vanilla sono CONDIVISE tra missioni: mai modificarle in place —
    si appende un blocco custom in coda alla tabella (chiude il file) e si
    punta la missione lì (+0x74 count, +0x78 start)."""
    if not 0 <= mission < 48:
        raise ValueError(f"zoneCfg: missione {mission} fuori range (entry livello 512-559)")
    while entries and entries[-1] is None:
        entries = entries[:-1]
    if any(e is None for e in entries):
        raise ValueError("zoneCfg: 'default motore' è ammesso solo per le ultime zone")
    src = os.path.join(BIND, "0955")
    dst = os.path.join(MODS, "0955")
    if not os.path.isdir(dst):
        shutil.copytree(src, dst)
    p = os.path.join(dst, "LEVELS.BIN")
    d = bytearray(open(p, "rb").read())
    van = open(os.path.join(src, "LEVELS.BIN"), "rb").read()
    nrec = struct.unpack_from("<H", d, 0)[0]
    tab = 4 + nrec * 0x80
    n1, n2 = struct.unpack_from("<II", d, tab)
    t3 = tab + 12 + n1 * 28 + n2 * 4
    n_van = (len(van) - t3) // 40
    r = 4 + mission * 0x80
    cur_cnt, cur_start = struct.unpack_from("<II", d, r + 0x74)
    if entries:
        if cur_start >= n_van and len(entries) <= cur_cnt:
            start = cur_start                      # riusa il blocco custom
        else:
            start = (len(d) - t3) // 40            # append in coda
            d += b"\0" * (40 * len(entries))
        for i, e in enumerate(entries):
            if len(e) != 10:
                raise ValueError("zoneCfg: ogni voce ha 10 valori")
            vals = [int(v) for v in e]
            for j, v in enumerate(vals):
                if j not in (4, 5) and v < 0:
                    raise ValueError(f"zoneCfg zona {i + 1}: solo tgt può essere negativo (-30 = infinito)")
            struct.pack_into("<2I2I2i2I2H", d, t3 + (start + i) * 40, *vals)
    else:
        start = 0                                  # count=0: tutte default motore
    struct.pack_into("<II", d, r + 0x74, len(entries), start)
    open(p, "wb").write(d)
    return {"ok": True, "missione": mission, "voci": len(entries)}


def apply_recipes(set_idx, pairs):
    """Ricette casse di un set (BIND 0953, <set>_CRATECONTENTS.BIN, 28B):
    [u32 6][6 x (u16 toy_normale, u16 toy_mega)] nello spazio-180.
    NB il set è CONDIVISO tra tutte le missioni che lo referenziano
    (LEVELS.BIN, campo +0x68 del record missione)."""
    if not 0 <= int(set_idx) <= 40:
        raise ValueError(f"ricette: set {set_idx} fuori range (0-40)")
    if len(pairs) != 6:
        raise ValueError("ricette: servono 6 coppie [normale, mega]")
    for a, b in pairs:
        if not (0 <= int(a) <= 179 and 0 <= int(b) <= 179):
            raise ValueError(f"ricette: toy fuori spazio-180: {a},{b}")
    src = os.path.join(BIND, "0953")
    dst = os.path.join(MODS, "0953")
    if not os.path.isdir(dst):
        shutil.copytree(src, dst)
    p = os.path.join(dst, f"{int(set_idx)}_CRATECONTENTS.BIN")
    blob = struct.pack("<I", 6) + b"".join(struct.pack("<2H", int(a), int(b)) for a, b in pairs)
    open(p, "wb").write(blob)
    return {"ok": True, "set": int(set_idx)}


RAW = os.path.join(ROOT, "teambudd/dat_estratto/raw")


def _raw_mod(idx):
    """Percorso del mod RAW per l'entry idx (mods/NNNN.bin), inizializzato
    dal vanilla la prima volta. Ritorna (path, bytearray)."""
    p = os.path.join(MODS, f"{idx:04d}.bin")
    if not os.path.exists(p):
        os.makedirs(MODS, exist_ok=True)
        shutil.copyfile(os.path.join(RAW, f"{idx:04d}.bin"), p)
    return p, bytearray(open(p, "rb").read())


def apply_teams(mission, n):
    """Numero di team della missione SENZA slot-swap: patcha
    - entry 0956 (config per-missione, id loader 0x3bd): slot[m].n_team = n,
      con teamlist estesa in coda (voci 8B condivise: mai toccare le vanilla;
      i rec_idx sono indici relativi alla base record, che si sposta con
      l'header n2 -> insert in coda alla teamlist sicuro)
    - entry 0003 (tabella missioni menu, res id 4): byte d8cc (max team) di
      TUTTE le varianti della missione = max(attuale, n)
    NB il count s0 della mappa resta il tetto: servono n pedane. Team >4 =
    sperimentale (array runtime da 8 slot, ma colori/CLUT oltre il 4 ignoti)."""
    n = int(n)
    if not 0 <= mission < 48:
        raise ValueError(f"teams: missione {mission} fuori range")
    if not 1 <= n <= 8:
        raise ValueError("teams: numero team 1-8")
    # --- 0956 ---
    p, d = _raw_mod(956)
    van = open(os.path.join(RAW, "0956.bin"), "rb").read()
    n1, n2 = struct.unpack_from("<II", d, 0)
    van_n2 = struct.unpack_from("<II", van, 0)[1]
    cnt, idx = struct.unpack_from("<II", d, 8 + mission * 8)
    tl = 8 + n1 * 8
    entries = [bytes(d[tl + (idx + k) * 8: tl + (idx + k) * 8 + 8]) for k in range(cnt)]
    if n <= cnt:
        if idx >= van_n2 or n == cnt:
            struct.pack_into("<II", d, 8 + mission * 8, n, idx)
        else:  # riduzione su blocco vanilla condiviso: nuovo blocco custom
            new = entries[:n]
            d[tl + n2 * 8: tl + n2 * 8] = b"".join(new)
            struct.pack_into("<I", d, 4, n2 + n)
            struct.pack_into("<II", d, 8 + mission * 8, n, n2)
    else:
        new = entries + [entries[-1]] * (n - cnt) if entries else []
        if not new:
            raise ValueError("teams: la missione non ha voci team da clonare")
        d[tl + n2 * 8: tl + n2 * 8] = b"".join(new)
        struct.pack_into("<I", d, 4, n2 + n)
        struct.pack_into("<II", d, 8 + mission * 8, n, n2)
    open(p, "wb").write(d)
    # --- 0003 ---
    p2, d2 = _raw_mod(3)
    a, b = struct.unpack_from("<2H", d2, 4 + mission * 4)
    for k in range(a):
        off = b * 4 + k * 4
        if d2[off] < n:
            d2[off] = n
    open(p2, "wb").write(d2)
    return {"ok": True, "missione": mission, "team": n}


def apply_edits(entry, edits):
    """Applica il JSON di modifiche al livello e scrive mods/<entry>.
    BASELINE = il mod esistente se c'è (preserva mappe swappate di slot e le
    modifiche future a terreno/tile), altrimenti copia del vanilla. Il client
    manda sempre le liste COMPLETE, quindi le sezioni vengono ricostruite
    sopra la baseline; le sezioni identiche vengono saltate (byte-identità
    dei no-op save, il padding vanilla non è deterministico)."""
    dst = os.path.join(MODS, entry)
    if not (os.path.isdir(dst) and any(f.endswith(".PND") for f in os.listdir(dst))):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(os.path.join(BIND, entry), dst)

    pld_path = next(os.path.join(dst, f) for f in os.listdir(dst) if f.endswith(".PLD"))
    pnd_path = next(os.path.join(dst, f) for f in os.listdir(dst) if f.endswith(".PND"))

    # --- PLD ---
    d = bytearray(open(pld_path, "rb").read())
    pld_before = bytes(d)          # stato pre-edit (per i vecchi centri pedana)
    offs = list(struct.unpack_from("<17I", d, 8))

    # s0: lista [x,z,w,h] in mezzi-tile centro-relativi (float) -> 8.8 con segno.
    # Lunghezza libera (1 record = 1 team/pedana): la sezione viene ricostruita
    # e le successive shiftate come per s6. NB il numero di team EFFETTIVO lo
    # decide la config per-missione (res 0x3bd, slot = entry-512) col count s0
    # come tetto: record oltre la config = pedane senza proprietario (blu).
    if "s0" in edits:
        o = offs[0] + 8
        cnt = struct.unpack_from("<I", d, o)[0]
        recs = edits["s0"]
        if not 1 <= len(recs) <= 16:
            raise ValueError(f"s0: numero record fuori range (1-16): {len(recs)}")
        payload = bytearray(struct.pack("<I", len(recs)))
        for r in recs:
            payload += struct.pack("<4H", *[int(round(v * 256)) & 0xffff for v in r])
        old_size = 4 + cnt * 8
        delta = len(payload) - old_size
        d[o:o + old_size] = payload
        if delta:
            offs = [v + delta if v > offs[0] else v for v in offs]
            struct.pack_into("<17I", d, 8, *offs)

    # s3: ZONE LANCIO CASSE, lista di centri [cx,cz] in tile. La consegna va
    # alla zona più vicina al richiedente (FUN_800e4dc8): per N team servono
    # N zone, una vicino a ogni pedana. Zone oltre il count vanilla = clone
    # della forma della zona 1 traslata; la sezione viene ricostruita.
    if "s3" in edits:
        zones, o3, end3 = _parse_s3(d, offs)
        if not zones:
            raise ValueError("s3: il livello non ha zone casse da usare come modello")
        centers = [_zone_center(z) for z in zones]
        new_zones = []
        for i, c in enumerate(edits["s3"]):
            src, src_c = (zones[i], centers[i]) if i < len(zones) else (zones[0], centers[0])
            dx = int(round((c[0] - src_c[0]) * 2))
            dz = int(round((c[1] - src_c[1]) * 2))
            nz = []
            for t in src:
                hx, hz = t % 128 + dx, t // 128 + dz
                if not (0 <= hx < 128 and 0 <= hz < 128):
                    raise ValueError(f"s3: zona {i + 1} fuori mappa")
                nz.append(hz * 128 + hx)
            new_zones.append(nz)
        payload = bytearray(struct.pack("<I", len(new_zones)))
        for z in new_zones:
            payload += struct.pack(f"<I{len(z)}H", len(z), *z)
            if len(z) & 1:
                payload += b"\0\0"
        # no-op: zone identiche -> non toccare (il padding vanilla dopo le
        # zone a count dispari non e' zero: riscriverlo rompe la byte-identita')
        if new_zones != zones:
            old_size = end3 - o3
            delta = len(payload) - old_size
            d[o3:o3 + old_size] = payload
            if delta:
                offs = [v + delta if v > offs[3] else v for v in offs]
                struct.pack_into("<17I", d, 8, *offs)

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

    # heightmap 65x65 s16 (base64 LE): dimensione fissa -> scrittura in place.
    # Applicata PRIMA delle pedane, così lo spianamento sotto le pedane
    # spostate lavora sul terreno scolpito. MAX/MINHEIGHTS le ricalcola il
    # motore al load (FUN_800aa4b0); il PTH NON viene rigenerato.
    if "hm" in edits:
        hm = base64.b64decode(edits["hm"])
        if len(hm) != 65 * 65 * 2:
            raise ValueError(f"hm: dimensione {len(hm)} != {65 * 65 * 2}")
        _, _, off_hm, _ = _tiles_layout(d)
        if bytes(d[off_hm:off_hm + len(hm)]) != hm:
            d[off_hm:off_hm + len(hm)] = hm

    # array tile 64x64x28B (base64): dimensione fissa -> in place. I tile
    # RIDIPINTI che avevano voci di animazione (frecce pedane, acqua) perdono
    # le loro desc (come _erase_pad): un tile dipinto a mano non deve piu'
    # animarsi col frame di un'altra texture. Applicato PRIMA delle pedane.
    if "tiles" in edits:
        tl = base64.b64decode(edits["tiles"])
        if len(tl) != 4096 * 28:
            raise ValueError(f"tiles: dimensione {len(tl)} != {4096 * 28}")
        _, _, _, off_tiles = _tiles_layout(d)
        old = bytes(d[off_tiles:off_tiles + len(tl)])
        if old != tl:
            changed = {i for i in range(4096)
                       if old[i * 28:(i + 1) * 28] != tl[i * 28:(i + 1) * 28]}
            d[off_tiles:off_tiles + len(tl)] = tl
            al = _anim_desc(d, off_tiles)
            if al:
                o2, n2 = al
                keep = []
                for i in range(n2):
                    pp = o2 + 2 + i * 16
                    if struct.unpack_from("<H", d, pp)[0] not in changed:
                        keep.append(bytes(d[pp:pp + 16]))
                if len(keep) != n2:
                    d[o2 + 2:o2 + 2 + n2 * 16] = b"".join(keep)
                    struct.pack_into("<H", d, o2, len(keep))

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

    # pedane <-> tile dipinti: record spostati = sposta i tile; record eliminati
    # = tappo d'erba; record NUOVI = copia i tile dalla pedana 1 (posizione
    # corrente) + clone delle frecce animate
    if "s0" in edits:
        orig = pld_before          # stato PRE-edit del PLD (mod o vanilla)
        ooffs = struct.unpack_from("<17I", orig, 8)
        oo = ooffs[0] + 8
        ocnt = struct.unpack_from("<I", orig, oo)[0]
        _, _, off_hm, off_tiles = _tiles_layout(d)

        def st(v):
            return (v - 65536 if v >= 32768 else v) / 256

        def ocenter(i):
            ox, oz = struct.unpack_from("<2H", orig, oo + 4 + i * 8)
            return (32 + st(ox) / 2, 32 + st(oz) / 2)

        recs = edits["s0"]
        for i, r in enumerate(recs[:ocnt]):
            old_c = ocenter(i)
            new_c = (32 + r[0] / 2, 32 + r[1] / 2)
            if abs(old_c[0] - new_c[0]) > 0.01 or abs(old_c[1] - new_c[1]) > 0.01:
                _repaint_pad(d, off_hm, off_tiles, old_c, new_c)
        for i in range(len(recs), ocnt):
            d = _erase_pad(d, off_tiles, ocenter(i))
        if len(recs) > ocnt and ocnt > 0:
            src_c = (32 + recs[0][0] / 2, 32 + recs[0][1] / 2)
            for r in recs[ocnt:]:
                d = _clone_pad(d, off_hm, off_tiles, src_c,
                               (32 + r[0] / 2, 32 + r[1] / 2))
    # NB zone casse (s3): SOLO DATI, su richiesta dell'utente niente modifiche
    # al PND (né anello dipinto né spianamento) — l'anello vanilla è decorazione
    # e resta dov'è; la zona funziona ovunque la si metta.
    open(pnd_path, "wb").write(d)
    return {"ok": True}


# ---------------------------------------------------------------- vista 3D --
_3D_CACHE = {}


def api_3d(entry):
    """Dati 3D del livello per l'editor: mesh dei modelli (MDL.BND, formato .LOD
    reversato - vedi tb_lod.py) + texture (TIM.BND) + URL del terreno hi-res.
    I modelli non cambiano coi mods -> cache in memoria per entry."""
    if entry in _3D_CACHE:
        return _3D_CACHE[entry]
    folder = os.path.join(BIND, entry)
    out = {"models": {}, "tex": {}}
    timsz = {}
    tim_path = os.path.join(folder, "TIM.BND")
    if os.path.exists(tim_path):
        for name, data in tb_lod.parse_bind(open(tim_path, "rb").read()):
            key = name.upper().rsplit(".", 1)[0]
            try:
                w, h, _ = tb_lod.tim_to_rgba(data)
                timsz[key] = (w, h)
                out["tex"][key] = "data:image/png;base64," + \
                    base64.b64encode(tb_lod.tim_to_png(data)).decode()
            except Exception:
                pass
    mdl_path = os.path.join(folder, "MDL.BND")
    if os.path.exists(mdl_path):
        for name, data in tb_lod.parse_bind(open(mdl_path, "rb").read()):
            key = name.upper().rsplit(".", 1)[0]
            try:
                m = tb_lod.parse_lod(data)
            except Exception:
                continue
            batches = []
            for part in tb_lod.best_lod(m)["parts"]:
                tex = part["tex"].upper() if part["tex"] else None
                if tex not in out["tex"]:
                    tex = None
                tw, th = timsz.get(tex, (64, 64))
                # le facce SENZA UV di una part texturizzata vanno in un batch
                # a colore pieno (altrimenti campionerebbero il texel 0,0)
                acc = {True: ([], [], []), False: ([], [], [])}
                for pr in part["prims"]:
                    idx, uv = pr["idx"], pr["uv"]
                    P, N, U = acc[bool(uv and tex)]
                    # quad in ordine PERIMETRALE (non strip) -> ventaglio
                    tris = [(0, 1, 2)] if len(idx) == 3 else [(0, 1, 2), (0, 2, 3)]
                    for tri in tris:
                        for k in tri:
                            a, b, c = part["verts"][idx[k]]
                            na, nb, nc = part["norms"][idx[k]]
                            # assi: a=verticale -> y; scala 1/512 = tile
                            P += [round(b / 512, 4), round(a / 512, 4), round(c / 512, 4)]
                            N += [round(nb / 4096, 3), round(na / 4096, 3), round(nc / 4096, 3)]
                            if uv:
                                U += [round((uv[k][0] + .5) / tw, 4),
                                      round((uv[k][1] + .5) / th, 4)]
                            else:
                                U += [0, 0]
                for textured, (P, N, U) in acc.items():
                    if P:
                        batches.append({"t": tex if textured else None,
                                        "c": list(part["color"]), "p": P, "n": N, "u": U})
            if batches:
                out["models"][key] = batches
    _3D_CACHE[entry] = out
    return out


GROUNDS3D = os.path.join(ROOT, "teambudd/grounds3d")


def ground3d_png(entry, px=64):
    """PNG del terreno a 64px/tile (4096x4096, risoluzione NATIVA delle celle
    atlas) dal PND corrente (mods se presente), cache su disco invalidata dal
    mtime del PND. A 32px/tile i muri ripidi (texture stirata in verticale)
    diventavano sbavature: partivano gia' da meta' risoluzione."""
    import glob as _glob
    folder = os.path.join(MODS, entry)
    if not (os.path.isdir(folder) and _glob.glob(os.path.join(folder, "*.PND"))):
        folder = os.path.join(BIND, entry)
    pnds = _glob.glob(os.path.join(folder, "*.PND"))
    if not pnds:
        return None
    os.makedirs(GROUNDS3D, exist_ok=True)
    dst = os.path.join(GROUNDS3D, entry + ".png")
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(pnds[0]):
        import render_ground
        render_ground.render(folder, dst, px)
    return dst


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

    def _file(self, path):
        b = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(path)[1],
                                                  "application/octet-stream"))
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/editor"):
            return self._file(os.path.join(WEB, "index.html"))
        if self.path.startswith(("/js/", "/css/")) or self.path == "/editor.css":
            p = os.path.normpath(os.path.join(WEB, self.path.lstrip("/")))
            if p.startswith(WEB) and os.path.isfile(p):
                return self._file(p)
            return self._json({"err": "not found"}, 404)
        if self.path == "/api/levels":
            return self._json(tb_level.list_levels())
        if self.path == "/api/catalogs":
            return self._json(tb_level.catalogs())
        if self.path.startswith("/api/level/"):
            entry = self.path.split("/")[-1].split("?")[0]
            if not (entry.isdigit() and os.path.isdir(os.path.join(BIND, entry))):
                return self._json({"err": "unknown level"}, 404)
            try:
                return self._json(tb_level.parse_level(entry))
            except Exception as e:
                return self._json({"err": str(e)}, 500)
        if self.path.startswith("/api/atlas/"):
            entry = self.path.split("/")[-1].split("?")[0]
            if not (entry.isdigit() and os.path.isdir(os.path.join(BIND, entry))):
                return self._json({"err": "unknown level"}, 404)
            try:
                return self._json(tb_level.atlas(entry))
            except Exception as e:
                return self._json({"err": str(e)}, 500)
        if self.path.startswith("/api/3d/"):
            entry = self.path.split("/")[-1].split("?")[0]
            if not (entry.isdigit() and os.path.isdir(os.path.join(BIND, entry))):
                return self._json({"err": "livello sconosciuto"}, 404)
            try:
                self._json(api_3d(entry))
            except Exception as e:
                self._json({"err": str(e)}, 500)
        elif self.path.startswith("/ground3d/"):
            entry = self.path.split("/")[-1].split(".")[0].split("?")[0]
            if not (entry.isdigit() and os.path.isdir(os.path.join(BIND, entry))):
                return self._json({"err": "livello sconosciuto"}, 404)
            try:
                p = ground3d_png(entry)
            except Exception as e:
                return self._json({"err": str(e)}, 500)
            if not p:
                return self._json({"err": "PND mancante"}, 404)
            b = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-cache")
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
                zcfg = body["edits"].pop("zoneCfg", None)
                rec = body["edits"].pop("recipes", None)
                tc = body["edits"].pop("teamCount", None)
                res = apply_edits(body["entry"], body["edits"])
                if zcfg is not None:
                    res["zoneCfg"] = apply_zonecfg(int(body["entry"]) - 512, zcfg)
                if rec is not None:
                    res["recipes"] = apply_recipes(rec["set"], rec["pairs"])
                if tc is not None:
                    res["teams"] = apply_teams(int(body["entry"]) - 512, tc)
                # il PNG del terreno si rigenera da solo alla prossima richiesta
                # (ground3d_png invalida sul mtime del PND moddato)
                self._json(res)
            elif self.path == "/api/build":
                self._json(build_iso())
            else:
                self._json({"err": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "err": str(e)}, 500)


if __name__ == "__main__":
    print("Editor: http://localhost:8787  (Ctrl+C to quit)")
    HTTPServer(("127.0.0.1", 8787), H).serve_forever()
