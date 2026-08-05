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
import tb_fastiso

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


def _repaint_pads(d, off_hm, off_tiles, moves):
    """Sposta l'ARTE dipinta delle pedane [(old_c, new_c), ...] (centri tile
    x.5) e spiana il terreno sotto le nuove posizioni. L'arte è il SOLO centro
    2x2 (quadrato colorato + frecce, clut della squadra): l'anello del blocco
    4x4 è erba/terreno locale e NON viene trapiantato — la destinazione tiene
    il suo terreno e la decorazione attorno al vecchio posto resta. Gli
    spostamenti sono SIMULTANEI: tutto viene letto dallo stato pre-edit, così
    due pedane che si scambiano di posto non si mangiano i tile a vicenda."""
    def rd(x, z):
        o = off_tiles + (z * 64 + x) * 28
        return bytes(d[o:o + 28])

    def wr(x, z, rec):
        o = off_tiles + (z * 64 + x) * 28
        d[o:o + 28] = rec

    moves = [m for m in moves
             if all(0 <= x < 64 and 0 <= z < 64
                    for x, z in _pad_block(m[0]) + _pad_block(m[1]))]
    if not moves:
        return
    # snapshot pre-edit: arte del centro 2x2 + tappo dall'anello di ogni pedana
    snap = [(oc, nc, [rd(x, z) for x, z in _pad_center(oc)],
             _ring_filler(d, off_tiles, oc)) for oc, nc in moves]
    # tappo su tutti i vecchi centri, POI arte sui nuovi centri
    for oc, _, _, filler in snap:
        for x, z in _pad_center(oc):
            wr(x, z, filler)
    for _, nc, recs, _ in snap:
        for (x, z), rec in zip(_pad_center(nc), recs):
            wr(x, z, rec)
    # rimappa le VOCI DI ANIMAZIONE (vivono sui 4 tile del centro) in un
    # passaggio unico su una mappa globale vecchio->nuovo: ogni desc viene
    # toccata al massimo una volta (niente doppi rimbalzi negli scambi)
    remap = {}
    for oc, nc, _, _ in snap:
        for t, nt in zip(_pad_center(oc), _pad_center(nc)):
            remap.setdefault(t, nt)
    al = _anim_desc(d, off_tiles)
    if al:
        o2, n2 = al
        for i in range(n2):
            pp = o2 + 2 + i * 16
            idx = struct.unpack_from("<H", d, pp)[0]
            t = (idx % 64, idx // 64)
            if t in remap:
                nx, nz = remap[t]
                struct.pack_into("<H", d, pp, nz * 64 + nx)
    # spiana i vertici sotto il blocco 4x4 di ogni nuova posizione
    for _, nc, _, _ in snap:
        vx, vz = _pad_block(nc)[0]
        hs = [struct.unpack_from("<h", d, off_hm + (zz * 65 + xx) * 2)[0]
              for zz in range(vz, vz + 5) for xx in range(vx, vx + 5)]
        med = sorted(hs)[len(hs) // 2]
        for zz in range(vz, vz + 5):
            for xx in range(vx, vx + 5):
                struct.pack_into("<h", d, off_hm + (zz * 65 + xx) * 2, med)


def _pad_block(c):
    """Impronta 4x4 della pedana centrata in c (centri tile x.5)."""
    x, z = int(c[0] - 0.5) - 1, int(c[1] - 0.5) - 1
    return [(x + i, z + j) for j in range(4) for i in range(4)]


def _pad_center(c):
    """Centro 2x2 della pedana: l'arte dipinta vera (quadrato colorato con
    frecce baked, 4 orientazioni della stessa cella + clut squadra)."""
    x, z = int(c[0] - 0.5), int(c[1] - 0.5)
    return [(x, z), (x + 1, z), (x, z + 1), (x + 1, z + 1)]


def _ring_filler(d, off_tiles, c):
    """Tile più comune dell'anello del blocco 4x4 (l'erba/terreno locale che
    circonda l'arte pedana): è il tappo giusto per il buco del centro 2x2."""
    from collections import Counter
    ctr = set(_pad_center(c))
    per = [bytes(d[off_tiles + (z * 64 + x) * 28:off_tiles + (z * 64 + x) * 28 + 28])
           for x, z in _pad_block(c)
           if (x, z) not in ctr and 0 <= x < 64 and 0 <= z < 64]
    return Counter(per).most_common(1)[0][0]


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
    """Pedana NUOVA: copia l'arte centro 2x2 da src_c a dst_c (src intatta,
    l'anello di terreno NON viene trapiantato), spiana il terreno sotto la
    destinazione e clona le voci animazione del centro 2x2 in coda alla
    lista desc. Ritorna il bytearray (il PND cresce)."""
    src_b, dst_b = _pad_block(src_c), _pad_block(dst_c)
    if any(not (0 <= x < 64 and 0 <= z < 64) for x, z in src_b + dst_b):
        return d
    src_ctr, dst_ctr = _pad_center(src_c), _pad_center(dst_c)
    for (sx, sz), (dx, dz) in zip(src_ctr, dst_ctr):
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
        smap = {t: k for k, t in enumerate(src_ctr)}
        clones = []
        for i in range(n2):
            pp = o2 + 2 + i * 16
            idx = struct.unpack_from("<H", d, pp)[0]
            t = (idx % 64, idx // 64)
            if t in smap:
                rec = bytearray(d[pp:pp + 16])
                nx, nz = dst_ctr[smap[t]]
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
    """Pedana ELIMINATA: tappo di terreno locale sull'arte centro 2x2 (l'anello
    resta: è già il terreno del posto) e rimozione delle voci animazione del
    blocco. Ritorna il bytearray (il PND si accorcia)."""
    b = _pad_block(c)
    if any(not (0 <= x < 64 and 0 <= z < 64) for x, z in b):
        return d
    filler = _ring_filler(d, off_tiles, c)
    for x, z in _pad_center(c):
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

    # MODELLI IMPORTATI da altri livelli: [{"from": "0520", "name": "frn_cleo_sphinx"}]
    # -> copia il .LOD (e le TIM delle sue part) nel MDL.BND/TIM.BND del mod e
    # aggiunge il nome alla lista modelli del PND (il motore registra le
    # risorse per nome dal MDL.BND del livello). NB le TIM importate tengono
    # le coordinate VRAM originali: possibili conflitti visivi da testare in
    # gioco. PRIMA di hm/tiles/istanze: la lista nomi shifta tutto il PND.
    if edits.get("addModels"):
        mdl_path = next(os.path.join(dst, f) for f in os.listdir(dst)
                        if f.upper() == "MDL.BND")
        timb_path = next(os.path.join(dst, f) for f in os.listdir(dst)
                         if f.upper() == "TIM.BND")
        mdl = tb_lod.parse_bind(open(mdl_path, "rb").read())
        timb = tb_lod.parse_bind(open(timb_path, "rb").read())
        mkeys = {n.upper().rsplit(".", 1)[0] for n, _ in mdl}
        tkeys = {n.upper().rsplit(".", 1)[0] for n, _ in timb}
        n_names, = struct.unpack_from("<H", d, 4)
        names = [bytes(d[12 + i * 32: 12 + (i + 1) * 32]) for i in range(n_names)]
        namekeys = {n.split(b"\0")[0].decode("latin-1").upper() for n in names}
        for imp in edits["addModels"]:
            src = os.path.join(BIND, str(imp["from"]))
            name = imp["name"]
            key = name.upper()
            smdl = tb_lod.parse_bind(open(os.path.join(src, "MDL.BND"), "rb").read())
            member = next(((n, dat) for n, dat in smdl
                           if n.upper().rsplit(".", 1)[0] == key), None)
            if member is None:
                raise ValueError(f"addModels: {name} non trovato in {imp['from']}")
            if key not in mkeys:
                mdl.append(member)
                mkeys.add(key)
                stim = tb_lod.parse_bind(open(os.path.join(src, "TIM.BND"), "rb").read())
                pm = tb_lod.parse_lod(member[1])
                for lod in pm["lods"]:
                    for p in lod["parts"]:
                        t = (p["tex"] or "").upper()
                        if t and t not in tkeys:
                            tm = next(((n, dat) for n, dat in stim
                                       if n.upper().rsplit(".", 1)[0] == t), None)
                            if tm:
                                timb.append(tm)
                                tkeys.add(t)
            if key not in namekeys:
                nb = name.encode("latin-1")[:31]
                names.append(nb + b"\0" * (32 - len(nb)))
                namekeys.add(key)
        open(mdl_path, "wb").write(tb_level.bind_write(mdl))
        open(timb_path, "wb").write(tb_level.bind_write(timb))
        if len(names) != n_names:
            d[12:12 + n_names * 32] = b"".join(names)
            struct.pack_into("<H", d, 4, len(names))

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

    # PTH: griglia AI 128x128 u8 (16384B, base64) A OFFSET 0 del file — la
    # CODA (32B, 112B su 0543: tabella ignota) resta intatta; dimensione
    # fissa -> in place, skip se identica. bit 16 = cella bloccata per l'AI.
    if "pth" in edits:
        grid = base64.b64decode(edits["pth"])
        if len(grid) != 128 * 128:
            raise ValueError(f"pth: dimensione {len(grid)} != {128 * 128}")
        pth_path = next((os.path.join(dst, f) for f in os.listdir(dst)
                         if f.endswith(".PTH")), None)
        if pth_path:
            pd = bytearray(open(pth_path, "rb").read())
            if len(pd) >= 16384 and bytes(pd[:16384]) != grid:
                pd[:16384] = grid
                open(pth_path, "wb").write(pd)

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
        moves = []
        for i, r in enumerate(recs[:ocnt]):
            old_c = ocenter(i)
            new_c = (32 + r[0] / 2, 32 + r[1] / 2)
            if abs(old_c[0] - new_c[0]) > 0.01 or abs(old_c[1] - new_c[1]) > 0.01:
                moves.append((old_c, new_c))
        _repaint_pads(d, off_hm, off_tiles, moves)
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


def _build_3d(model_files, tim_files, pose=None):
    """JSON mesh+texture dal formato .LOD/.TIM: liste di (nome, bytes).
    pose = parser alternativo (es. _pose_turret)."""
    out = {"models": {}, "tex": {}}
    timsz = {}
    for name, data in tim_files:
        key = name.upper().rsplit(".", 1)[0]
        try:
            w, h, _ = tb_lod.tim_to_rgba(data)
            timsz[key] = (w, h)
            out["tex"][key] = "data:image/png;base64," + \
                base64.b64encode(tb_lod.tim_to_png(data)).decode()
        except Exception:
            pass
    if True:
        for name, data in model_files:
            key = name.upper().rsplit(".", 1)[0]
            try:
                m = (pose or tb_lod.parse_lod)(data)
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
    return out


def api_3d(entry):
    """Dati 3D del livello per l'editor: mesh dei modelli (MDL.BND, formato .LOD
    reversato - vedi tb_lod.py) + texture (TIM.BND). Mods-aware (i modelli
    importati vivono nel MDL.BND del mod); cache invalidata dal mtime."""
    folder, _ = tb_level.level_folder(entry)
    mdl_path = os.path.join(folder, "MDL.BND")
    tim_path = os.path.join(folder, "TIM.BND")
    key = (entry, os.path.getmtime(mdl_path) if os.path.exists(mdl_path) else 0)
    if key in _3D_CACHE:
        return _3D_CACHE[key]
    models, tims = [], []
    if os.path.exists(tim_path):
        tims = list(tb_lod.parse_bind(open(tim_path, "rb").read()))
    if os.path.exists(mdl_path):
        models = list(tb_lod.parse_bind(open(mdl_path, "rb").read()))
    out = _build_3d(models, tims)
    _3D_CACHE[key] = out
    return out


def _pad_decode(w0, w1):
    """Decoder ESATTO del record frame 8B dei .PAD (da 0x800B1778, trovato
    con breakpoint runtime via DuckStation MCP): 3 rotazioni a 8 bit scalate
    x16 (PSX 0x1000 = giro) + traslazione 14/13/13 bit con segno."""
    def sra(x, n):
        x &= 0xffffffff
        return ((x ^ 0x80000000) >> n) - (0x80000000 >> n)
    def s16(v):
        v &= 0xffff
        return v - 65536 if v >= 32768 else v
    rot = (((w0 >> 16) & 0xff) << 4, ((w0 >> 8) & 0xff) << 4, (w0 & 0xff) << 4)
    tr = (s16((sra((w0 << 1) & 0xffffffff, 19) & 0xffc0) | ((w1 >> 26) & 0x3f)),
          s16(sra((w1 << 6) & 0xffffffff, 19) & 0xffff),
          s16(sra((w1 << 19) & 0xffffffff, 19) & 0xffff))
    return rot, tr


def _pad_pose(pad_bytes, frame=0):
    """Trasformazioni per-osso di un frame: [(R 3x3, T), ...].
    Il runtime NEGA i 3 angoli e costruisce la matrice (0x800b0e84);
    qui replichiamo con Rx*Ry*Rz sugli angoli negati. Spazio y-GIU'
    (traslazioni: occhi a y=-354 = in alto)."""
    import math
    nf, nb = struct.unpack_from("<2H", pad_bytes, 4)
    frame = max(0, min(nf - 1, frame))
    stride = 32 + nf * 8
    out = []
    for b in range(nb):
        base = 8 + b * stride
        w0, w1 = struct.unpack_from("<2I", pad_bytes, base + 32 + frame * 8)
        rot, tr = _pad_decode(w0, w1)
        a = [-(r / 4096.0) * 2 * math.pi for r in rot]     # angoli negati
        cx, sx = math.cos(a[0]), math.sin(a[0])
        cy, sy = math.cos(a[1]), math.sin(a[1])
        cz, sz = math.cos(a[2]), math.sin(a[2])
        Rx = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
        Ry = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
        Rz = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))
        def mul(A, B):
            return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3))
                               for j in range(3)) for i in range(3))
        out.append((mul(mul(Rx, Ry), Rz), tr))
    return out


def _pose_buddy(lod_bytes, pad_bytes):
    """Posa statica di un modello animato: part k trasformata dall'osso k
    (v_ydown = (b, -a, c); v' = R*v + T; ritorno a (a,b,c))."""
    m = tb_lod.parse_lod(lod_bytes)
    bones = _pad_pose(pad_bytes, 0)
    for lod in m["lods"]:
        for k, p in enumerate(lod["parts"]):
            if k >= len(bones) or not p["verts"]:
                continue
            R, T = bones[k]
            def xf(a, b, c):
                x, y, z = b, -a, c
                nx = R[0][0] * x + R[0][1] * y + R[0][2] * z + T[0]
                ny = R[1][0] * x + R[1][1] * y + R[1][2] * z + T[1]
                nz = R[2][0] * x + R[2][1] * y + R[2][2] * z + T[2]
                return (-ny, nx, nz)
            def xfn(a, b, c):
                x, y, z = b, -a, c
                nx = R[0][0] * x + R[0][1] * y + R[0][2] * z
                ny = R[1][0] * x + R[1][1] * y + R[1][2] * z
                nz = R[2][0] * x + R[2][1] * y + R[2][2] * z
                return (-ny, nx, nz)
            p["verts"] = [xf(*v) for v in p["verts"]]
            p["norms"] = [xfn(*n) for n in p["norms"]]
    return m


def _pose_turret(lod_bytes):
    """POSA STATICA per i modelli torretta: i .LOD hanno 5 part con un'unica
    origine e la CANNA modellata in VERTICALE (bbox a>=150: in gioco il motore
    la assembla/ruota col sistema di animazione). Per l'anteprima ruotiamo le
    part alte di -90 gradi attorno all'asse c passante per la loro base:
    (da, b) -> (b, -da). Approssimazione della rest pose, non la vera catena
    di trasformazioni del motore (R_ANIMATIONS.BIN, non ancora reversato)."""
    m = tb_lod.parse_lod(lod_bytes)
    for lod in m["lods"]:
        for p in lod["parts"]:
            if not p["verts"]:
                continue
            mn = min(v[0] for v in p["verts"])
            if mn < 150:
                continue
            p["verts"] = [(mn + b, -(a - mn), c) for a, b, c in p["verts"]]
            p["norms"] = [(nb, -na, nc) for na, nb, nc in p["norms"]]
    return m


def api_global3d(dat):
    """Modello GLOBALE (entry DAT tipo 1150-1165 TURRET*): la cartella
    bind/<dat> estratta contiene .LOD e .TIM sciolti. Ritorna lo stesso JSON
    di api_3d (i proiettili P_* vengono saltati; part alte in posa statica)."""
    key = "g" + dat
    if key in _3D_CACHE:
        return _3D_CACHE[key]
    folder = os.path.join(BIND, dat)
    models = [(f, open(os.path.join(folder, f), "rb").read())
              for f in sorted(os.listdir(folder))
              if f.endswith(".LOD") and not f.startswith("P_")]
    tims = [(f, open(os.path.join(folder, f), "rb").read())
            for f in sorted(os.listdir(folder)) if f.endswith(".TIM")]
    pads = [open(os.path.join(folder, f), "rb").read()
            for f in sorted(os.listdir(folder)) if f.endswith(".PAD")]

    # NB: _pose_buddy (posa scheletrale dai .PAD) NON e' usata: il decoder dei
    # frame e' corretto (vedi tb_pad.py) ma i vertici delle part sono gia' in
    # posa di riposo nello spazio modello, quindi la trasformazione osso va
    # applicata come DELTA rispetto a una bind pose ancora da identificare.
    # Le anteprime restano statiche (rese gia' buone); vedi docs/FORMATS.md.
    def pose(lod_bytes):
        return _pose_turret(lod_bytes)

    out = _build_3d(models, tims, pose=pose)
    _3D_CACHE[key] = out
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
    # atlas imports touch the TIM without touching the PND: check both mtimes
    srcs = pnds + _glob.glob(os.path.join(folder, "*.TIM"))
    if not os.path.exists(dst) or os.path.getmtime(dst) < max(map(os.path.getmtime, srcs)):
        import render_ground
        render_ground.render(folder, dst, px)
    return dst


DAT_DEV = DAT + ".dev"           # base a slot espansi (tools/tb_expand.py)
ISO_BIN = os.path.join(ROOT, "teambudd/rebuild.bin")
ESTRATTO = os.path.join(ROOT, "teambudd/estratto")


def _slot_headroom(base):
    """Margine residuo (slot fisico - contenuto) delle entry moddate: finché
    resta positivo il repack è in-place, il layout non cambia e il savestate
    sopravvive alle build. Slot fisico = distanza tra i settori di tabella
    consecutivi della BASE; contenuto = estensione reale nel DAT costruito."""
    try:
        def table(path):
            with open(path, "rb") as f:
                n = struct.unpack_from("<H", f.read(4), 2)[0]
                f.seek(8)
                raw = f.read(n * 8)
            return [struct.unpack_from("<II", raw, i * 8) for i in range(n)]
        tb, td = table(base), table(DAT)
        fd = open(DAT, "rb")
        out = []
        for name in sorted(os.listdir(MODS)):
            e = name.split(".")[0]
            if not (e.isdigit() and int(e) < len(tb) - 1):
                continue
            i = int(e)
            slot = (tb[i + 1][1] - tb[i][1]) * 2048
            fd.seek(td[i][1] * 2048)
            hdr = fd.read(8)
            used = tb[i][0]
            if hdr[:4] == b"BIND":                     # real extent, not table size
                n = struct.unpack_from("<I", hdr, 4)[0]
                t = fd.read(n * 40)
                used = max(struct.unpack_from("<II", t, k * 40 + 32)[0]
                           + struct.unpack_from("<II", t, k * 40 + 32)[1]
                           for k in range(n)) if 0 < n < 10000 else used
            out.append(f"  slot {e}: {used // 1024}KB usati / {slot // 1024}KB "
                       f"({'margine ' + str((slot - used) // 1024) + 'KB' if used <= slot else '⚠ SFORATO'})")
        fd.close()
        return out
    except Exception as ex:
        return [f"(headroom check saltato: {ex})"]


def build_iso():
    """Applica i mods al DAT e aggiorna la ISO. Base = BUDDIES.DAT.dev (slot
    espansi) se esiste. FAST PATH: se il layout non è cambiato (stessa size di
    DAT/ENG/GAME nella ISO) riscrive in-place solo i settori cambiati di
    rebuild.bin -> i savestate dell'emulatore restano validi e non serve
    nemmeno riaprire l'immagine. Altrimenti rebuild completo con mkpsxiso
    (e savestate da rifare)."""
    log = []
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/tb_patch_eng.py")],
                       capture_output=True, text=True)
    log.append(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        return {"ok": False, "log": log}
    base = DAT_DEV if os.path.exists(DAT_DEV) else DAT_ORIG
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/tb_rebuild.py"),
                        base, MODS, DAT, MANIFEST],
                       capture_output=True, text=True)
    rebuild_out = r.stdout.strip() or r.stderr.strip()
    log.append(rebuild_out)
    if r.returncode != 0:
        return {"ok": False, "log": log}
    if base == DAT_ORIG:
        log.append("(suggerimento: `python3 tools/tb_expand.py` crea la base a "
                   "slot espansi: con quella i savestate restano quasi sempre validi)")
    if "ricollocato" in rebuild_out:
        log.append("⚠ una entry ha sforato il suo slot: layout del DAT cambiato "
                   "(se succede spesso, aumenta lo slack: tools/tb_expand.py --level-slack 128)")
    log += _slot_headroom(base)
    # --- fast path: patch in-place della ISO esistente ---
    if os.path.exists(ISO_BIN):
        try:
            n = 0
            for name in ("BUDDIES.DAT", "ENG.BIN", "GAME.BIN"):
                p = DAT if name == "BUDDIES.DAT" else os.path.join(ESTRATTO, name)
                n += tb_fastiso.patch_file(ISO_BIN, name, open(p, "rb").read())
            log.append(f"⚡ ISO aggiornata in-place ({n} settori riscritti) — "
                       "✔ SAVESTATE ANCORA VALIDO: caricalo e prova il livello")
            return {"ok": True, "log": log}
        except (ValueError, FileNotFoundError) as e:
            log.append(f"patch in-place non possibile ({e})")
    # --- rebuild completo ---
    mk = os.path.join(ROOT, "mkpsxiso/build/mkpsxiso")
    if not os.path.exists(mk):
        log.append("mkpsxiso non trovato: esegui prima `python3 tools/setup.py`")
        return {"ok": False, "log": log}
    r = subprocess.run([mk, "-y",
                        "-o", "rebuild.bin", "-c", "rebuild.cue", "teambuddies.xml"],
                       cwd=os.path.join(ROOT, "teambudd"), capture_output=True, text=True)
    ok = "successfully" in r.stdout
    log.append(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
    if ok:
        log.append("⚠⚠ SAVESTATE DA RIFARE (evento raro, una tantum): la ISO è stata "
                   "ricostruita da zero e il layout è cambiato — BOOT DA ZERO in "
                   "DuckStation (niente savestate!), arriva alla selezione livello "
                   "e salva lì il nuovo savestate. Le build successive torneranno "
                   "in-place e quel savestate resterà valido.")
    return {"ok": ok, "log": log}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-cache")   # atlas reloads after imports
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
        if self.path.startswith("/api/tileinfo/"):
            entry = self.path.split("/")[-1].split("?")[0]
            if not (entry.isdigit() and os.path.isdir(os.path.join(BIND, entry))):
                return self._json({"err": "unknown level"}, 404)
            try:
                return self._json(tb_level.tileinfo(entry))
            except Exception as e:
                return self._json({"err": str(e)}, 500)
        if self.path.startswith("/api/global3d/"):
            dat = self.path.split("/")[-1].split("?")[0]
            if not (dat.isdigit() and os.path.isdir(os.path.join(BIND, dat))):
                return self._json({"err": "unknown entry"}, 404)
            try:
                return self._json(api_global3d(dat))
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
            elif self.path == "/api/import_cell":
                for k in ("dst", "src"):
                    e = str(body.get(k, ""))
                    if not (e.isdigit() and os.path.isdir(os.path.join(BIND, e))):
                        return self._json({"err": f"unknown level in '{k}'"}, 404)
                os.makedirs(MODS, exist_ok=True)
                self._json(tb_level.import_cell(
                    str(body["dst"]), str(body["src"]), int(body["srcCell"]),
                    int(body["srcClut"]), int(body["dstCell"])))
            else:
                self._json({"err": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "err": str(e)}, 500)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"Editor: http://localhost:{port}  (Ctrl+C to quit)")
    HTTPServer(("127.0.0.1", port), H).serve_forever()
