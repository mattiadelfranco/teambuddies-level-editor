#!/usr/bin/env python3
"""
Team Buddies - Shared level/catalog parsing for the editor server.

Everything is mods-aware: if teambudd/mods/<entry> exists it is parsed
instead of the vanilla bind folder, so the editor always shows the current
state of a modded level (apply_edits rebuilds mods from vanilla + the full
edit payload, so the client must always send complete lists).

Coordinate conventions (decompiled from the engine, see docs/FORMATS.md):
- world: wx = 64*x_data - 0x4000, wz = 0x4000 - 64*z_data, y down
- tile:  (w + 0x4000) / 512  ->  instances/extra at tile (x/8, 64 - z/8)
- PLD s0/s6 raw values are world units (signed 8.8 half-tiles rel. center)
- heightmap 65x65 s16 row=z col=x, h/8 tiles, positive up
"""
import base64
import glob
import json
import os
import re
import shutil
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIND = os.path.join(ROOT, "teambudd/dat_estratto/bind")
RAW = os.path.join(ROOT, "teambudd/dat_estratto/raw")
MODS = os.path.join(ROOT, "teambudd/mods")


def _b64(b):
    return base64.b64encode(bytes(b)).decode()


def bind_write(members):
    """Scrive un BIND da [(nome, bytes), ...]. Layout del formato: header
    "BIND"+count, directory 40B (nome[32] + off u32 + size u32, offset
    ASSOLUTI), membri con offset = align4(fine precedente) + 4 (regola
    osservata su tutti i BIND vanilla; round-trip byte-identico validato)."""
    n = len(members)
    out = bytearray(b"BIND")
    out += struct.pack("<I", n)
    dir_off = 8
    out += b"\0" * (n * 40)
    offs = []
    for name, data in members:
        offs.append(len(out))
        out += data
        pos = (len(out) + 3) & ~3          # OGNI membro e' seguito da
        out += b"\0" * (pos - len(out) + 4)  # align4 + 4 byte di gap

    for k, (name, data) in enumerate(members):
        nb = name.encode("latin-1")[:31]
        struct.pack_into("<32sII", out, dir_off + k * 40,
                         nb + b"\0" * (32 - len(nb)), offs[k], len(data))
    return bytes(out)


def level_folder(entry):
    """Folder to parse for a level: mods/<entry> if it has level files."""
    mod = os.path.join(MODS, entry)
    if os.path.isdir(mod) and glob.glob(os.path.join(mod, "*.PND")):
        return mod, True
    return os.path.join(BIND, entry), False


def list_levels():
    out = []
    for folder in sorted(glob.glob(os.path.join(BIND, "*"))):
        pnds = glob.glob(os.path.join(folder, "*.PND"))
        if os.path.isdir(folder) and pnds:
            out.append({"entry": os.path.basename(folder),
                        "name": os.path.basename(pnds[0]).rsplit(".", 1)[0]})
    return out


def parse_level(entry):
    folder, is_mod = level_folder(entry)
    pnds = glob.glob(os.path.join(folder, "*.PND"))
    plds = glob.glob(os.path.join(folder, "*.PLD"))
    if not (pnds and plds):
        return None
    lvl = {"entry": entry, "isMod": is_mod,
           "name": os.path.basename(pnds[0]).rsplit(".", 1)[0]}

    # ---- PND: models, instances, extra list, heightmap ----
    d = open(pnds[0], "rb").read()
    if d[:4] != b"PSM0":
        return None
    n_names, n_inst, _, _ = struct.unpack_from("<4H", d, 4)
    lvl["models"] = [d[12 + i * 32: 12 + (i + 1) * 32].split(b"\0")[0]
                     .decode("ascii", "replace") for i in range(n_names)]
    base = 12 + n_names * 32
    inst = []
    for i in range(n_inst):
        o = base + i * 20
        m, = struct.unpack_from("<I", d, o)
        x, h, z, e = struct.unpack_from("<4h", d, o + 4)
        r1, r2 = struct.unpack_from("<2i", d, o + 12)
        inst.append([m, x, h, z, e, r1, r2])
    lvl["inst"] = inst
    off_extra = base + n_inst * 20
    extra_cnt, = struct.unpack_from("<H", d, off_extra)
    # None = not decodable (e.g. BOSSANOVA): the editor must leave it intact
    lvl["extra"] = ([list(struct.unpack_from("<10H", d, off_extra + 2 + i * 20))
                     for i in range(extra_cnt)] if extra_cnt < 100 else None)
    hm_off = off_extra + 2 + extra_cnt * 20
    lvl["hm"] = _b64(d[hm_off: hm_off + 65 * 65 * 2])

    # ---- PLD: 17 sections ----
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
                    sec["pts"].append(list(struct.unpack_from(
                        f"<{rec // 2}H", d, o + 4 + k * rec)))
        secs.append(sec)
    lvl["pld"] = secs

    # s6 with team/variant split (records are 8B: tipo u16, team u8|var u8, x, z)
    o = offs[6] + 8
    cnt, extra6 = struct.unpack_from("<2H", d, o)
    recs = []
    if cnt < 500:
        for i in range(cnt):
            t, tv, x, z = struct.unpack_from("<4H", d, o + 4 + i * 8)
            recs.append([t, tv & 0xff, tv >> 8, x, z])
    lvl["s6"] = {"extra": extra6, "records": recs}

    # s0 raw records [x,z,w,h] u16
    o0 = offs[0] + 8
    c0 = struct.unpack_from("<I", d, o0)[0]
    lvl["s0"] = [list(struct.unpack_from("<4H", d, o0 + 4 + k * 8))
                 for k in range(min(c0, 16))]

    # s3 crate-launch zones -> tile centers
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
    lvl["s3"] = zones

    # s10 teleport zones: [dest, flags, x0, z0, x1, z1] — rect in HALF-tiles
    # (tile = v/2). flags bit 8 = entrance, low nibble = effect variant.
    o10, sz10 = offs[10] + 8, offs[11] - offs[10]
    tps = []
    if sz10 > 4:
        c10, = struct.unpack_from("<I", d, o10)
        if 0 < c10 <= 64 and 4 + c10 * 12 <= sz10:
            tps = [list(struct.unpack_from("<2H4h", d, o10 + 4 + k * 12))
                   for k in range(c10)]
    lvl["s10"] = tps

    # ---- tile array (64x64 x 28B) + animated-tile indices ----
    d = open(pnds[0], "rb").read()
    off_tiles = hm_off + 65 * 65 * 2
    lvl["tiles"] = _b64(d[off_tiles: off_tiles + 4096 * 28])
    anim = off_tiles + 131072            # engine reserves 32B/tile
    lvl["animTiles"] = []
    lvl["animWater"] = []
    if anim + 2 <= len(d):
        n1 = struct.unpack_from("<h", d, anim)[0]
        o2 = anim + 2 + max(n1, 0) * 12
        if 0 <= n1 < 2000 and o2 + 2 <= len(d):
            n2 = struct.unpack_from("<H", d, o2)[0]
            if n2 < 2000 and o2 + 2 + n2 * 16 <= len(d):
                lvl["animTiles"] = sorted({struct.unpack_from("<H", d, o2 + 2 + k * 16)[0]
                                           for k in range(n2)})
                # type byte 2 = water: pads placed on these turn the pool into
                # an invisible liquid trap (the save drops the animation)
                lvl["animWater"] = sorted({struct.unpack_from("<H", d, o2 + 2 + k * 16)[0]
                                           for k in range(n2) if d[o2 + 2 + k * 16 + 2] == 2})

    # ---- PTH (AI walkability): the 128x128 half-tile grid starts at OFFSET 0
    # (no header!); the trailing 32B (112B on 0543) are an unknown footer.
    # bit 16 = blocked for the AI. Modded copy if present. Calibrated by
    # cross-correlating the blocked bit with heightmap steepness on 42 levels:
    # grid-at-0 aligns (overlap ~0.95), grid-at-32 is shifted by 16 tiles. ----
    pths = glob.glob(os.path.join(folder, "*.PTH")) \
        or glob.glob(os.path.join(BIND, entry, "*.PTH"))
    lvl["pth"] = None
    if pths:
        pd = open(pths[0], "rb").read()
        if len(pd) >= 16384:
            lvl["pth"] = _b64(pd[:16384])
    return lvl


def _tim_path(entry):
    """The level's atlas .TIM: modded copy if the mod folder has one."""
    folder, _ = level_folder(entry)
    tims = glob.glob(os.path.join(folder, "*.TIM"))
    if not tims:   # mod folder without a TIM, fall back to vanilla
        tims = glob.glob(os.path.join(BIND, entry, "*.TIM"))
    return tims[0]


def _tim_parse(d):
    """Header fields of a 4bpp TIM (single CLUT block + single pixel block,
    true for all 45 level atlases). CLUT k = row k (cw colors, 2B each)."""
    magic, typ = struct.unpack_from("<II", d, 0)
    if magic != 0x10 or not (typ & 8):
        raise ValueError("not a 4bpp TIM")
    clen, _, _, cw, ch = struct.unpack_from("<IHHHH", d, 8)
    po = 8 + clen
    _, _, _, iw, ih = struct.unpack_from("<IHHHH", d, po)
    return {"cw": cw, "ch": ch, "iw": iw, "ih": ih,
            "cdata": 20, "pdata": po + 12, "w": iw * 4}


def _imports_path(entry):
    return os.path.join(MODS, entry, "atlas_imports.json")


def _load_imports(entry):
    """Sidecar {cell: clut} written by import_cell, so 'auto' CLUT works for
    imported cells that no tile references yet."""
    try:
        return {int(k): v for k, v in json.load(open(_imports_path(entry))).items()}
    except (OSError, ValueError):
        return {}


def atlas(entry):
    """Level texture atlas (the level's own .TIM): 4bpp indices + all CLUTs.
    Cells are 64x64; a tile record picks a cell corner (U,V), a CLUT and one
    of 8 orientations (corner deltas)."""
    d = open(_tim_path(entry), "rb").read()
    h = _tim_parse(d)
    cluts = []
    for r in range(h["ch"]):
        row = []
        for c in range(h["cw"]):
            v, = struct.unpack_from("<H", d, h["cdata"] + (r * h["cw"] + c) * 2)
            row.append([(v & 31) * 8, ((v >> 5) & 31) * 8,
                        ((v >> 10) & 31) * 8, 0 if v == 0 else 255])
        cluts.append(row)
    raw = d[h["pdata"]: h["pdata"] + h["iw"] * 2 * h["ih"]]  # 2 px/byte, low nibble first
    return {"w": h["w"], "h": h["ih"], "idx": _b64(raw), "cluts": cluts,
            "imports": _load_imports(entry)}


def _pnd_tiles_off(d):
    """Offset of the 64x64x28B tile array inside a PND."""
    n_names, n_inst, _, _ = struct.unpack_from("<4H", d, 4)
    off_extra = 12 + n_names * 32 + n_inst * 20
    extra_cnt = struct.unpack_from("<H", d, off_extra)[0]
    return off_extra + 2 + extra_cnt * 20 + 65 * 65 * 2


def tileinfo(entry):
    """Palette metadata for any level (source browser + destination picker):
    per-cell dominant CLUT, cells referenced by tile records (with counts),
    cells used as animated-texture frames, and the CLUT count of the TIM."""
    folder, _ = level_folder(entry)
    pnds = glob.glob(os.path.join(folder, "*.PND"))
    d = open(pnds[0], "rb").read()
    h = _tim_parse(open(_tim_path(entry), "rb").read())
    cols = h["w"] // 64
    off = _pnd_tiles_off(d)
    cell_tiles, count = {}, {}
    for i in range(4096):
        u, = struct.unpack_from("<H", d, off + i * 28)
        cell = (d[off + i * 28 + 2] // 64) * cols + u // 64
        cell_tiles[cell] = cell_tiles.get(cell, 0) + 1
        key = (cell, d[off + i * 28 + 7])
        count[key] = count.get(key, 0) + 1
    cell_clut = {}
    for (cell, clut), n in count.items():
        if cell not in cell_clut or n > cell_clut[cell][1]:
            cell_clut[cell] = (clut, n)
    cell_clut = {c: v[0] for c, v in cell_clut.items()}
    for cell, clut in _load_imports(entry).items():
        cell_clut.setdefault(cell, clut)
    # animated-texture frames (12B records after the 32B/tile reserved area)
    anim = off + 131072
    cell_anim = set()
    if anim + 2 <= len(d):
        n1, = struct.unpack_from("<h", d, anim)
        if 0 <= n1 < 2000:
            for k in range(n1):
                u, = struct.unpack_from("<H", d, anim + 2 + k * 12)
                cell_anim.add((d[anim + 2 + k * 12 + 2] // 64) * cols + u // 64)
    return {"cols": cols, "rows": h["ih"] // 64, "nCluts": h["ch"],
            "cellClut": cell_clut, "cellTiles": cell_tiles,
            "cellAnim": sorted(cell_anim)}


def import_cell(dst_entry, src_entry, src_cell, src_clut, dst_cell):
    """Copy one 64x64 atlas cell (4bpp pixels + its CLUT) from another level's
    TIM into this level's TIM (modded copy, bootstrapped from vanilla like
    apply_edits). CLUT strategy: reuse a byte-identical CLUT if the target TIM
    already has one (e.g. from a previous import), else append a new row —
    the engine handles variable CLUT counts (vanilla ranges 60..160)."""
    dst = os.path.join(MODS, dst_entry)
    if not (os.path.isdir(dst) and glob.glob(os.path.join(dst, "*.PND"))):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(os.path.join(BIND, dst_entry), dst)

    s = open(_tim_path(src_entry), "rb").read()
    sh = _tim_parse(s)
    dpath = glob.glob(os.path.join(dst, "*.TIM"))[0]
    d = bytearray(open(dpath, "rb").read())
    dh = _tim_parse(bytes(d))
    for name, cell, hh in (("source", src_cell, sh), ("destination", dst_cell, dh)):
        if not 0 <= cell < (hh["w"] // 64) * (hh["ih"] // 64):
            raise ValueError(f"{name} cell {cell} out of range")
    if not 0 <= src_clut < sh["ch"]:
        raise ValueError(f"source CLUT {src_clut} out of range")

    # CLUT: exact match in destination, else append a row
    cb = s[sh["cdata"] + src_clut * sh["cw"] * 2:
           sh["cdata"] + (src_clut + 1) * sh["cw"] * 2]
    rowb = dh["cw"] * 2
    clut_idx = next((k for k in range(dh["ch"])
                     if bytes(d[dh["cdata"] + k * rowb: dh["cdata"] + (k + 1) * rowb]) == cb),
                    None)
    appended = clut_idx is None
    if appended:
        if dh["ch"] >= 250:            # render/scan ceiling; vanilla max is 160
            raise ValueError("destination CLUT table is full (250)")
        clut_idx = dh["ch"]
        end = dh["cdata"] + dh["ch"] * rowb
        d[end:end] = cb
        clen, = struct.unpack_from("<I", d, 8)
        struct.pack_into("<I", d, 8, clen + rowb)
        struct.pack_into("<H", d, 18, dh["ch"] + 1)
        dh = _tim_parse(bytes(d))      # pixel block moved

    # pixels: 64 rows of 32 bytes (cells are 64px-aligned, nibbles never split)
    scx, scy = (src_cell % (sh["w"] // 64)) * 32, (src_cell // (sh["w"] // 64)) * 64
    dcx, dcy = (dst_cell % (dh["w"] // 64)) * 32, (dst_cell // (dh["w"] // 64)) * 64
    srow, drow = sh["iw"] * 2, dh["iw"] * 2
    for y in range(64):
        so = sh["pdata"] + (scy + y) * srow + scx
        do = dh["pdata"] + (dcy + y) * drow + dcx
        d[do:do + 32] = s[so:so + 32]
    open(dpath, "wb").write(d)

    imp = _load_imports(dst_entry)
    imp[dst_cell] = clut_idx
    json.dump({str(k): v for k, v in imp.items()}, open(_imports_path(dst_entry), "w"))
    return {"clut": clut_idx, "appended": appended, "nCluts": dh["ch"]}


# ------------------------------------------------------------- catalogs ----

S6_NAMES = [
    "Commando", "Trooper", "Kung Fu", "Medic", "Stealth", "Super Buddy",
    "Eskimo", "Legionnaire", "Farmer", "Shepherd", "Yeti", "Baywatch",
    "Tarzan", "Penguin", "Polar Bear", "Lion", "Hiker", "Ram", "Monkey",
    "Camel", "Bull", "Horse", "Pig", "Lizard", "Seal", "Grizzly", "Dog",
    "Cat", "Puffin", "Dog B", "Pretty (team objective)", "Cyborg", "Sheep",
    "Ninja", "Ghost", "Hostage (team objective)", "Dummy 1", "Dummy 2",
    "Dummy 3", "Dummy 4", "Dummy 5", "Dummy 6", "Dummy 7", "Dummy 8",
    "Frozen Scientist (objective)", "Camel Supplies", "Mech Laser",
    "Mech Boss", "Mech Gatling", "Bomb Dog (objective)", "Target Dog",
    "Scientist 2", "Baddie", "Alien", "Hooley Alien", "Wolf",
    "Scientist CP", "Ewe Fiend Boss", "Capture Pig", "Capture Penguin",
    "Capture Sheep", "Capture Dog"]


def catalogs():
    out = {"levels": list_levels(), "s6Names": S6_NAMES}

    # extra-list catalog = STATICS.BIN (188 records, proper names)
    statics = {}
    sd = open(os.path.join(BIND, "0953/STATICS.BIN"), "rb").read()
    scnt = int.from_bytes(sd[4:8], "little")
    for i in range(scnt):
        statics[i] = sd[0xc + i * 0x40: 0xc + i * 0x40 + 0x20] \
            .split(b"\0")[0].decode("latin-1").strip()
    out["statics"] = statics
    out["extraVanilla"] = [113, 116, 117, 121, 122, 123, 124, 125, 127, 128, 129, 133]

    # turret type -> global model DAT entry. Each record stores resource
    # pairs (count @+0x2c, start @+0x30 into the 8B-pair table after the
    # records); the turret resource ids in ascending order map 1:1 onto the
    # TURRET* model entries 1150-1165 (calibrated on the model names:
    # Cannon->TURRET1, Gatling->G, Ice->I, Laser->L, Homing->H/AH...).
    tail = 12 + scnt * 64
    tres = {}
    for i in range(scnt):
        if not statics[i].startswith("Turret"):
            continue
        n, start = struct.unpack_from("<2I", sd, 12 + i * 64 + 0x2c, )
        if n == 1:
            tres[i] = struct.unpack_from("<H", sd, tail + start * 8)[0]
    order = sorted(set(tres.values()))
    out["staticModels"] = {i: 1150 + order.index(r) for i, r in tres.items()
                          if order.index(r) < 16}

    # s6 slot -> global buddy/animal model entry, for catalog previews.
    # Slots 0-35 are LINEAR: entry = 1004 + slot (verified on the names:
    # 1004 COMMANDO, 1005 BUDDY(=trooper), 1006 NINJA(=kung fu), 1010 ESKIMO,
    # 1018 POBEAR, 1019 LION ... 1034 B_BABE(=Pretty), 1039 HOSTAGE).
    # Specials 44+ matched by LOD-name keyword; dummies have no model.
    s6m = {}
    special = {44: "SCIENT", 45: "CAMELBAGGAGE", 46: "MECH", 47: "MECHBOSS",
               48: "MECH", 49: "DOG_BOMB", 50: "DOG_TARGET", 51: "SCIENT",
               52: "BADDIE", 53: "ALIEN", 54: "HOOLEY", 55: "WOLF",
               56: "CONTROL_PANEL", 57: "EWE_FIEND", 58: "PIG",
               59: "PENGUIN", 60: "SHEEP", 61: "DOG_TEAM"}
    lodindex = {}
    for folder in glob.glob(os.path.join(BIND, "1*")):
        e = int(os.path.basename(folder))
        if not 1000 <= e <= 1150:
            continue
        for f in os.listdir(folder):
            if f.endswith(".LOD") and not f.startswith("P_"):
                lodindex.setdefault(f[:-4].upper(), e)
    for slot in range(36):
        s6m[slot] = 1004 + slot
    for slot, kw in special.items():
        hit = next((e for n, e in sorted(lodindex.items())
                    if n.startswith(kw)), None)
        if hit:
            s6m[slot] = hit
    # capture variants reuse the plain animal models
    s6m[58] = s6m.get(22, 1026)
    s6m[59] = s6m.get(13, 1017)
    s6m[60] = s6m.get(32, 1036)
    out["s6Models"] = s6m

    # toy names (DAT entry 0015 = English): string i+1 = toy i
    toys = {}
    tp = os.path.join(RAW, "0015.bin")
    if os.path.exists(tp):
        lines = [l for l in open(tp, "rb").read().decode("latin-1").splitlines()
                 if l.strip()]
        for i, line in enumerate(lines[1:181]):
            toys[i] = re.sub(r"^_C", "", line).strip()
    out["toyNames"] = toys

    # per-mission zone crate config + recipe set (LEVELS.BIN, modded if present)
    lvp = os.path.join(MODS, "0955/LEVELS.BIN")
    if not os.path.exists(lvp):
        lvp = os.path.join(BIND, "0955/LEVELS.BIN")
    lv = open(lvp, "rb").read()
    nrec = struct.unpack_from("<H", lv, 0)[0]
    tab = 4 + nrec * 0x80
    n1, n2 = struct.unpack_from("<II", lv, tab)
    t3 = tab + 12 + n1 * 28 + n2 * 4
    zcfg, mset, f68 = {}, {}, {}
    for m in range(nrec):
        r = 4 + m * 0x80
        zc, zs = struct.unpack_from("<II", lv, r + 0x74)
        zcfg[m] = [list(struct.unpack_from("<4I2i4I", lv, t3 + (zs + k) * 40))
                   for k in range(min(zc, 16))]
        # CRATE RECIPES ARE PER MISSION: the loader (FUN_80083304, ENG) gets
        # a0 = _DAT_8004d8ce (mission index) and reads BIND member
        # (mission + 10); the CRATECONTENTS files start at member 10, so
        # mission M uses M_CRATECONTENTS.BIN. The +0x68 field of the record is
        # something else (it indexes the internal tbl1). _DAT_8004d8d4
        # overrides the set when != -1 (ENG 0x800a5368 / GAME 0x800f14b0).
        mset[m] = m
        f68[m] = struct.unpack_from("<I", lv, r + 0x68)[0]
    out["zcfg"], out["mset"], out["levelsField68"] = zcfg, mset, f68

    # crate recipe sets (BIND 0953, modded files override)
    c53m = os.path.join(MODS, "0953")
    setnames = {}
    for f in os.listdir(os.path.join(BIND, "0953")):
        m2 = re.match(r"(\d+)_BT_(.+)\.BIN$", f)
        if m2:
            setnames[int(m2.group(1))] = m2.group(2)
    recipes = {}
    for n in range(41):
        p = os.path.join(c53m, f"{n}_CRATECONTENTS.BIN")
        if not os.path.exists(p):
            p = os.path.join(BIND, f"0953/{n}_CRATECONTENTS.BIN")
        d2 = open(p, "rb").read()
        cn = struct.unpack_from("<I", d2, 0)[0]
        recipes[n] = {"name": setnames.get(n, ""),
                      "pairs": [list(struct.unpack_from("<2H", d2, 4 + k * 4))
                                for k in range(min(cn, 6))]}
    out["recipes"] = recipes

    # per-mission team count (entry 0956, modded if present)
    p56 = os.path.join(MODS, "0956.bin")
    if not os.path.exists(p56):
        p56 = os.path.join(RAW, "0956.bin")
    d56 = open(p56, "rb").read()
    out["mteams"] = {m: struct.unpack_from("<I", d56, 8 + m * 8)[0]
                     for m in range(struct.unpack_from("<I", d56, 0)[0])}
    return out
