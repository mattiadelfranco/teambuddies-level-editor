"""Team Buddies - mission script (DAT entry 559+missione, res id 0x22f+m).

Formato (reversato da ENG FUN_8006fda8 + handler, 6 ago 2026):
  header 0x38 byte:
    +0x00 u32, +0x04 u32, +0x08 u32, +0x0c u32, +0x10 s16 (pool A),
    +0x14 s16 +0x16 s16 (pool obiettivi), +0x18 s16 n_team_script +0x1a s16,
    +0x1c..+0x26 s16 vari (pool), +0x28 s16 N_RECORD, +0x2a s16 N_INDICI,
    +0x2c i32, +0x30 s16 (musica? segno testato a fine load), +0x34
  poi N_INDICI x u32 (indici tabella oggetti 0x18-stride, attivati al load)
  poi N_RECORD record tipizzati (primo u32 = tipo):
    1  obiettivi squadra (ENG FUN_80071830 -> GAME FUN_800edd6c/FUN_800ede64):
       [1][blob 0x18: u32 modo, 12 contatori u8, 2 param u16][dati gruppi]
    2  override stat toy: [2][toy u32 (spazio-62)][val u16+pad][spare] (0x10)
    3  spawner/ondata (variabile), 4 (0x14), 5/6/d/e/f win-condition
       (e/f = bersagli da distruggere), 7 punti area (8+n*16),
    8  RELAZIONI SQUADRE: [8][n_nemici][n_alleati][team][flags: bit0 =
       prima azzera tutti i nemici; >>9&7 payload; +-0x168 speciale]
       [extra14][extra18][n_nemici x u32][n_alleati x u32]
    9  statico con rotazione: [9][rot/tipo u16][x][z] (0x10)
    a  (0x24), b cattura oggetto: [b][team][hp][x][z] (0x14),
    c  [c][u16][s16 n1][u32 n2][n1*8][n2*4]
Le liste nemici/alleati partono VUOTE al level load: i record tipo 8 le
definiscono (campagna: nemici=[giocatore], alleati=[le altre AI]).
"""
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODS = os.path.join(ROOT, "teambudd/mods")
DAT_ORIG = os.path.join(ROOT, "teambudd/estratto/BUDDIES.DAT.orig")
SYS_BIN = os.path.join(ROOT, "teambudd/estratto/SYS.BIN")
ENTRY_BASE = 558          # slot s -> DAT entry 558+s (settore della
                          # tabella risorse SYS 0x800450e4, id 0x22f+m; la
                          # colonna size della tabella DAT è sfasata di 1:
                          # la size vera viene dalla tabella SYS)
_RESTAB = None



# --- mappa missione -> slot script (albero del menu, 0002.bin @0x800) ---
# Lo script della missione m NON e' l'entry 558+m: il menu scrive in d8d8 lo
# SLOT del leaf selezionato (per modo di gioco) e il motore carica la risorsa
# 0x22f+slot = DAT entry 558+slot. Le missioni con piu' leaf hanno varianti
# per modo (campagna=modo0; le arene MP usano modi 2-5 = formato partita).
MISSION_SLOTS = {
    0: [(0, 0), (1, 1)], 1: [(0, 2)], 2: [(0, 3)], 3: [(0, 4)], 4: [(0, 5)],
    5: [(0, 6)], 6: [(0, 7), (1, 8)], 7: [(0, 9)], 8: [(0, 10), (1, 11)],
    9: [(0, 12)], 10: [(0, 13)], 11: [(0, 14), (1, 15)], 12: [(0, 16)],
    13: [(0, 17)], 14: [(0, 18)], 15: [(0, 19)], 16: [(0, 20)],
    17: [(0, 21), (1, 22)], 18: [(0, 23)], 19: [(0, 24)], 20: [(0, 25)],
    21: [(0, 26), (1, 27)], 22: [(0, 28)], 23: [(0, 29)], 24: [(0, 30)],
    25: [(0, 31), (1, 32)], 26: [(0, 33)], 27: [(0, 34)], 28: [(0, 35)],
    29: [(0, 36)], 30: [(0, 37)], 31: [(0, 38), (1, 39)], 32: [(5, 40)],
    33: [(0, 41)], 34: [(4, 42)], 35: [(3, 43)], 36: [(3, 44)], 37: [(3, 45)],
    38: [(2, 46)], 39: [(2, 47)], 40: [(2, 48)], 41: [(2, 49)], 42: [(4, 50)],
    43: [(4, 51)], 44: [(4, 52)], 45: [(3, 53)],
}

def slot_of(mission):
    "slot script primario (modo piu' basso) della missione"
    leaves = MISSION_SLOTS.get(mission)
    return min(leaves)[1] if leaves else mission

def _res(mission):
    """(settore, size) dello script della missione dalla tabella SYS."""
    global _RESTAB
    if _RESTAB is None:
        d = open(SYS_BIN, "rb").read()
        tab = 0x800450e4 - 0x80038f80
        _RESTAB = [struct.unpack_from("<II", d, tab + (0x22f + m) * 8)
                   for m in range(48)]
    return _RESTAB[slot_of(mission)]

# nomi dal dispatch del motore (walker ENG FUN_8006fda8, jump table 0x80053250):
#   1  -> FUN_80071830 -> GAME 0x800edd6c: GRUPPO AI/ondata (modo + contatori)
#   2  -> FUN_80071920: scrive rec+8 in DAT_80119b00[rec+4]+0x60 = stat unità
#   3  -> FUN_80071984: SPAWNER (rec+8 = modo: 1-4,6 una famiglia; -1,0,5,7,8 l'altra)
#   4  -> FUN_80071a94 -> FUN_80072464: trigger base 20B
#   5,6,13,14,15 -> FUN_80071c04 -> GAME 0x800f06f0: TRIGGER/WIN-COND
#      (14/15 vengono anche CONTATI: sono i "bersagli" della missione)
#   7  -> FUN_80071aec: CRATERI pre-cotti (chiama l'esplosione FUN_800ac1f0!)
#   8  -> FUN_80071c8c: alleanze (nemici+alleati -> liste squadra)
#   9  -> FUN_80071efc: oggetto piazzato a (x,z) con angolo (matrice GTE)
#   10 -> FUN_8007206c: config consegne AI
#   11 -> FUN_800720b8: override della ZONA CASSE più vicina a (x,z)
#   12 -> FUN_800721ec: AREA rettangolare (x0,z0,x1,z1 in tile, z flippata)
TYPE_NAMES = {
    1: "gruppo AI / ondata", 2: "vita unità", 3: "spawner", 4: "trigger base",
    5: "trigger (win/lose)", 6: "trigger (win/lose)", 7: "crateri terreno",
    8: "alleanze", 9: "oggetto piazzato", 10: "consegne AI",
    11: "override zona casse", 12: "area rettangolare",
    13: "trigger (win/lose)", 14: "bersaglio missione", 15: "bersaglio missione",
}

# tipi unità (spazio-62, stesso ordine di DAT_80119b00) per le note del tipo 2
UNIT_NAMES = [
    "Commando", "ST", "KungFu", "Medic", "Stealth", "Super", "Eskimo",
    "Legionario", "Contadino", "Pastore", "Yeti", "Baywatch", "Tarzan",
    "Pinguino", "Orso polare", "Leone", "Escursionista", "Ariete", "Scimmia",
    "Cammello", "Toro", "Cavallo", "Maiale", "Lucertola", "Foca", "Grizzly",
    "Cane", "Gatto", "Pulcinella", "Cane2", "Pretty", "Cyborg", "Pecora",
    "Ninja", "Fantasma", "Ostaggio", "Dummy1", "Dummy2", "Dummy3", "Dummy4",
    "Dummy5", "Dummy6", "Dummy7", "Dummy8", "Scienziato cong.",
    "Cammello scorte", "Mech laser", "Mech boss", "Mech gatling", "Bomb dog",
    "Target dog", "Scienziato2", "Baddie", "Alieno", "Hooley alieno", "Lupo",
    "ScienziatoCP", "Ewe boss", "Maiale catt.", "Pinguino catt.",
    "Pecora catt.", "Cane catt.",
]


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _i32(d, o):
    return struct.unpack_from("<i", d, o)[0]


def record_size(d, o):
    """Lunghezza del record che inizia a offset o (dai decompile ENG)."""
    t = _u32(d, o)
    if t == 1:
        b = o + 4                      # blob header 0x18
        cc, cd, d2, d1 = d[b + 4], d[b + 6], d[b + 7], d[b + 8]
        ce, cf, d4, d6 = d[b + 9], d[b + 10], d[b + 11], d[b + 12]
        d8, da, n15 = d[b + 13], d[b + 14], d[b + 15]
        d0 = _u32(d, b + 0x14)
        words = (cc + d2 + cd * 2 + ce) * 2 + d1 + cf * 2 + d4 * 4 \
            + d6 + d8 + da * 2 + n15 + d0 * 4
        return 0x1c + words * 4
    if t == 2:
        return 0x10
    if t == 3:
        n = 0x30 + _i32(d, o + 0x10) * 8 + _i32(d, o + 0x18) * 16 \
            + _i32(d, o + 0x24) * 8 + _i32(d, o + 0x2c) * 4
        if _i32(d, o + 0x14) != -1:
            n += _i32(d, o + 0x14) * 8
        return n
    if t == 4:
        return 0x14
    if t in (5, 6, 13, 14, 15):
        b4 = struct.unpack_from("<b", d, o + 4)[0]
        b5 = struct.unpack_from("<b", d, o + 5)[0]
        b6 = struct.unpack_from("<b", d, o + 6)[0]
        n = 0x10 + b4 * 4 + b6 * 4 + _i32(d, o + 0xc) * 4
        if b5 != -1:
            n += b5 * 4
        return n
    if t == 7:
        return 8 + _u32(d, o + 4) * 16
    if t == 8:
        return 0x1c + _u32(d, o + 4) * 4 + _u32(d, o + 8) * 4
    if t == 9:
        return 0x10
    if t == 10:
        return 0x24
    if t == 11:
        return 0x14
    if t == 12:
        return 0xc + struct.unpack_from("<h", d, o + 6)[0] * 8 \
            + _i32(d, o + 8) * 4
    raise ValueError(f"tipo record sconosciuto {t} a offset {o:#x}")


def parse(d):
    """-> {header: bytes, indices: [u32], records: [{type, off, data}], tail}"""
    n_rec = struct.unpack_from("<h", d, 0x28)[0]
    n_idx = struct.unpack_from("<h", d, 0x2a)[0]
    p = 0x38
    indices = list(struct.unpack_from(f"<{n_idx}I", d, p)) if n_idx else []
    p += n_idx * 4
    records = []
    for _ in range(max(n_rec, 0)):
        size = record_size(d, p)
        records.append({"type": _u32(d, p), "off": p, "data": bytes(d[p:p + size])})
        p += size
    return {"header": bytes(d[:0x38]), "indices": indices,
            "records": records, "tail": bytes(d[p:])}


def serialize(ms):
    """Ricostruisce il file (byte-identico se non modificato)."""
    hdr = bytearray(ms["header"])
    struct.pack_into("<h", hdr, 0x28, len(ms["records"]))
    struct.pack_into("<h", hdr, 0x2a, len(ms["indices"]))
    out = bytes(hdr) + struct.pack(f"<{len(ms['indices'])}I", *ms["indices"])
    for r in ms["records"]:
        out += r["data"]
    return out + ms["tail"]


# ---------------------------------------------------------------- alleanze --
def get_relations(ms, n_teams):
    """Simula i record tipo 8 in ordine -> per squadra {nemici, alleati}.
    Le liste runtime partono vuote al level load; a fine load il motore
    (ENG FUN_800712a4) rende nemica di TUTTE le altre ogni squadra rimasta
    con entrambe le liste vuote (default tutti-contro-tutti)."""
    rel = {t: {"nemici": [], "alleati": []} for t in range(n_teams)}
    touched = set()
    for r in ms["records"]:
        if r["type"] != 8:
            continue
        d = r["data"]
        na, nb = _u32(d, 4), _u32(d, 8)
        team, flags = _u32(d, 0xc), _u32(d, 0x10)
        if team >= n_teams:
            continue
        if flags & 1:
            rel[team]["nemici"] = []
        if na or nb:
            touched.add(team)
        lst = struct.unpack_from(f"<{na + nb}I", d, 0x1c)
        for v in lst[:na]:
            if v < n_teams and v != team and v not in rel[team]["nemici"]:
                rel[team]["nemici"].append(v)
        for v in lst[na:]:
            if v < n_teams and v != team and v not in rel[team]["alleati"]:
                rel[team]["alleati"].append(v)
    for t in range(n_teams):                       # default del motore
        if t not in touched and not rel[t]["nemici"] and not rel[t]["alleati"]:
            rel[t]["nemici"] = [u for u in range(n_teams) if u != t]
    return rel


def set_relations(ms, rel):
    """Riscrive le liste dei record tipo 8: per ogni squadra in rel
    {team: {nemici: [...], alleati: [...]}} modifica l'ULTIMO record tipo 8
    della squadra (flags/extra intatti), svuota le liste degli eventuali
    record precedenti della stessa squadra, e APPENDE un record nuovo
    (flags=1 = azzera prima) per le squadre senza record."""
    by_team = {}
    for i, r in enumerate(ms["records"]):
        if r["type"] == 8:
            by_team.setdefault(_u32(r["data"], 0xc), []).append(i)
    for team, cfg in rel.items():
        team = int(team)
        nem = [int(v) for v in cfg.get("nemici", [])]
        all_ = [int(v) for v in cfg.get("alleati", [])]
        if not nem and not all_:
            all_ = [team]          # vedi sotto: evita il default del motore
        idxs = by_team.get(team, [])
        if idxs:
            for i in idxs[:-1]:                    # svuota i precedenti
                d = bytearray(ms["records"][i]["data"][:0x1c])
                struct.pack_into("<II", d, 4, 0, 0)
                ms["records"][i]["data"] = bytes(d)
            i = idxs[-1]
            head = bytearray(ms["records"][i]["data"][:0x1c])
            struct.pack_into("<II", head, 4, len(nem), len(all_))
            ms["records"][i]["data"] = bytes(head) + struct.pack(
                f"<{len(nem) + len(all_)}I", *nem, *all_)
        else:
            if not nem and not all_:
                all_ = [team]      # liste vuote = default "nemico di tutti";
                                   # auto-alleanza innocua per dire "neutrale"
            head = struct.pack("<7I", 8, len(nem), len(all_), team, 1, 0, 0)
            ms["records"].append({"type": 8, "off": -1, "data": head + struct.pack(
                f"<{len(nem) + len(all_)}I", *nem, *all_)})
    return ms


# ------------------------------------------------------------- campi editor --
def _fields_u32(d, labels, start=4):
    out = []
    for k, lab in enumerate(labels):
        out.append({"label": lab, "off": start + k * 4,
                    "val": _i32(d, start + k * 4)})
    return out


def decode_record(r):
    """Campi editabili (label/off/val u32) + riassunto, per il pannello."""
    d = r["data"]
    t = r["type"]
    f = []
    note = ""
    if t == 1:
        b = 4
        f = [{"label": "modo", "off": 4, "val": _i32(d, 4)}]
        names = [("zone casse", b + 4), ("rettangoli pattuglia", b + 6),
                 ("gruppo d2", b + 7), ("indici oggetti", b + 8),
                 ("punti obiettivo", b + 9), ("gruppo cf", b + 10),
                 ("gruppo d4", b + 11), ("gruppo d6", b + 12),
                 ("gruppo d8", b + 13), ("gruppo da", b + 14)]
        note = "contatori: " + ", ".join(f"{n}={d[o]}" for n, o in names)
        p = 0x1c
        for k in range((len(d) - 0x1c) // 4):
            f.append({"label": f"dato[{k}]", "off": p + k * 4,
                      "val": _i32(d, p + k * 4)})
    elif t == 3:
        f = [{"label": "campo[0]", "off": 4, "val": _i32(d, 4)},
             {"label": "modo (1-4,6=A; -1,0,5,7,8=B)", "off": 8,
              "val": _i32(d, 8)}]
        for k in range(2, (len(d) - 4) // 4):
            f.append({"label": f"campo[{k}]", "off": 4 + k * 4,
                      "val": _i32(d, 4 + k * 4)})
        note = ("spawner rinforzi/consegne: il modo sceglie la famiglia di "
                "init (A=0x800ed098, B=0x800ec1c4); i contatori bloccati "
                "guidano le liste in coda")
    elif t == 2:
        f = _fields_u32(d, ["tipo unità (spazio-62)", "valore (vita)", "spare"])
        u = _i32(d, 4)
        nm = UNIT_NAMES[u] if 0 <= u < len(UNIT_NAMES) else "?"
        note = (f"vita/stat di «{nm}» = {_i32(d, 8)} (scrive il campo +0x60 "
                "della struct del tipo; applicato solo in campagna)")
    elif t in (5, 6, 13, 14, 15):
        # struttura dal parser GAME 0x800f06f0: contatori a byte in testa,
        # poi le liste in coda (un elemento ogni 4 byte, conta il low-16)
        na = d[4]
        nb = struct.unpack_from("<b", d, 5)[0]
        nc = d[6]
        nd = _u32(d, 0xc)
        f = [{"label": "n condizioni", "off": 4, "val": na, "lock": 1},
             {"label": "n squadre (-1=tutte)", "off": 5, "val": nb, "lock": 1},
             {"label": "n lista C", "off": 6, "val": nc, "lock": 1},
             {"label": "byte +7", "off": 7, "val": d[7]},
             {"label": "byte +8", "off": 8, "val": d[8]},
             {"label": "azione (255=default)", "off": 10, "val": d[10]},
             {"label": "n lista D", "off": 0xc, "val": nd, "lock": 1}]
        p = 0x10
        for k in range(na):
            f.append({"label": f"condizione[{k}]", "off": p, "val": _i32(d, p)})
            p += 4
        for k in range(max(nb, 0)):
            f.append({"label": f"squadra[{k}]", "off": p, "val": _i32(d, p)})
            p += 4
        for k in range(nc):
            f.append({"label": f"C[{k}]", "off": p, "val": _i32(d, p)})
            p += 4
        for k in range(nd):
            f.append({"label": f"D[{k}]", "off": p, "val": _i32(d, p)})
            p += 4
        chi = "tutte le squadre" if nb <= 0 else "squadre in lista"
        cosa = "BERSAGLIO missione (contato per la win)" if t in (14, 15) \
            else "trigger win/lose"
        note = (f"{cosa}: {na} condizioni (indici nella tabella eventi della "
                f"missione) per {chi}. Azione 255 = esito standard; in campagna "
                "il motore usa 0x37/0x38 per il completamento.")
    elif t == 7:
        n = _u32(d, 4)
        f = [{"label": "n punti", "off": 4, "val": n}]
        for k in range(n):
            for j, lab in enumerate(("x (mezzi-tile)", "z (mezzi-tile)",
                                     "tipo", "raggio")):
                f.append({"label": f"p{k + 1}.{lab}", "off": 8 + k * 16 + j * 4,
                          "val": _i32(d, 8 + k * 16 + j * 4)})
        note = ("crateri/bruciature applicati al load (stessa routine delle "
                "esplosioni): tipo 0 = deformazione con profondità raggio*10, "
                "altrimenti solo segno. tile = valore/2")
    elif t == 8:
        na, nb = _u32(d, 4), _u32(d, 8)
        f = [{"label": "squadra", "off": 0xc, "val": _i32(d, 0xc)},
             {"label": "flags", "off": 0x10, "val": _i32(d, 0x10)},
             {"label": "extra14", "off": 0x14, "val": _i32(d, 0x14)},
             {"label": "extra18", "off": 0x18, "val": _i32(d, 0x18)}]
        note = (f"nemici={list(struct.unpack_from(f'<{na}I', d, 0x1c))} "
                f"alleati={list(struct.unpack_from(f'<{nb}I', d, 0x1c + na * 4))}")
    elif t == 9:
        f = _fields_u32(d, ["angolo (0-4095)", "x (mezzi-tile)", "z (mezzi-tile)"])
        note = "oggetto/prop piazzato a terra con rotazione (matrice GTE)"
    elif t == 11:
        f = _fields_u32(d, ["squadra/valore (-1=no)", "scorta target (-1=no)",
                            "x (mezzi-tile)", "z (mezzi-tile)"])
        note = ("override della zona casse più vicina a (x,z): squadra scritta "
                "in +0x48 (flag 0x200) e scorta portata al valore dato")
    else:
        for k in range((len(d) - 4) // 4):
            f.append({"label": f"campo[{k}]", "off": 4 + k * 4,
                      "val": _i32(d, 4 + k * 4)})
    # campi che guidano la lunghezza del record: non editabili dal pannello
    locks = {3: (0x10, 0x14, 0x18, 0x24, 0x2c), 7: (4,), 12: (4, 8),
             5: (4, 0xc), 6: (4, 0xc), 13: (4, 0xc), 14: (4, 0xc), 15: (4, 0xc)}
    for fld in f:
        if fld["off"] in locks.get(t, ()):
            fld["lock"] = 1
    return {"type": t, "name": TYPE_NAMES.get(t, f"tipo {t}"),
            "size": len(d), "fields": f, "note": note}


# ------------------------------------------------------------------ file IO --
def raw_bytes(mission):
    """Bytes dello script: mod se esiste, altrimenti slice del DAT vanilla
    (settore+size dalla tabella SYS — i raw estratti hanno size sfasate)."""
    mod = os.path.join(MODS, f"{ENTRY_BASE + slot_of(mission):04d}.bin")
    if os.path.exists(mod):
        return open(mod, "rb").read()
    sec, size = _res(mission)
    f = open(DAT_ORIG, "rb")
    f.seek(sec * 2048)
    d = f.read(size)
    f.close()
    return d


def load(mission):
    return parse(raw_bytes(mission))


def save(mission, ms):
    """Scrive mods/<entry>.bin. Se lo script è più corto dell'originale viene
    paddato (la lettura è cappata dalla size di tabella SYS); se è più lungo
    la tabella SYS va aggiornata: lo fa sync_restable() alla build."""
    os.makedirs(MODS, exist_ok=True)
    out = serialize(ms)
    _, size = _res(mission)
    if len(out) < size:
        out += b"\0" * (size - len(out))
    mod = os.path.join(MODS, f"{ENTRY_BASE + slot_of(mission):04d}.bin")
    open(mod, "wb").write(out)
    return mod


def sync_restable():
    """Allinea le size della tabella risorse in SYS.BIN agli script moddati
    più lunghi dell'originale (SYS.BIN è un file proprio della ISO; OVERLAY.DAT
    è solo un indice da 512B). Idempotente, derivato dai mods. Ritorna la
    lista delle missioni patchate (serve riavvio pieno dell'emulatore: la
    tabella vive in RAM dal boot)."""
    grown = []
    for sl in range(54):
        mod = os.path.join(MODS, f"{ENTRY_BASE + sl:04d}.bin")
        if os.path.exists(mod):
            n = os.path.getsize(mod)
            row = struct.unpack_from("<II", open(SYS_BIN, "rb").read(),
                                     0x800450e4 - 0x80038f80 + (0x22f + sl) * 8)
            if n > row[1]:
                grown.append((sl, n))
    if not grown:
        return []
    tab_off = 0x800450e4 - 0x80038f80
    d = bytearray(open(SYS_BIN, "rb").read())
    for sl, n in grown:
        struct.pack_into("<I", d, tab_off + (0x22f + sl) * 8 + 4, n)
    open(SYS_BIN, "wb").write(d)
    return [m for m, _ in grown]
