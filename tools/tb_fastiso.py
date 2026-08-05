#!/usr/bin/env python3
"""
Team Buddies - Patch IN-PLACE della ISO (rebuild.bin) senza mkpsxiso.

Riscrive dentro la ISO 2352 solo i settori CAMBIATI di un file (stesso LBA,
stessa size): sync/header/subheader preservati, EDC/ECC mode2-form1
ricalcolati (stesso algoritmo di mkpsxiso, tabelle standard CD-ROM XA).

Perché: il layout della ISO e la tabella di BUDDIES.DAT restano identici al
byte, quindi i SAVESTATE dell'emulatore restano validi (la tabella del DAT che
il gioco tiene in RAM continua a puntare ai settori giusti) e il file viene
aggiornato sullo stesso inode (DuckStation aperto vede i dati nuovi senza
riaprire l'immagine).

Uso:
  python3 tools/tb_fastiso.py locate   <iso.bin> <NOME>          # LBA e size
  python3 tools/tb_fastiso.py patch    <iso.bin> <NOME> <file>   # patch in-place
  python3 tools/tb_fastiso.py selftest <iso.bin> [NOME]          # verifica EDC/ECC
"""
import struct, sys

RAW = 2352          # settore fisico
DATA = 2048         # user data form1
HDR = 24            # sync 12 + header 4 + subheader 8


# ------------------------------------------------------ EDC/ECC (CD-ROM XA) --
_edc_lut = None
_ecc_f = None
_ecc_b = None


def _init_luts():
    global _edc_lut, _ecc_f, _ecc_b
    if _edc_lut:
        return
    _edc_lut = [0] * 256
    _ecc_f = [0] * 256
    _ecc_b = [0] * 256
    for i in range(256):
        j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
        _ecc_f[i] = j
        _ecc_b[i ^ j] = i
        edc = i
        for _ in range(8):
            edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
        _edc_lut[i] = edc


def _edc(data):
    _init_luts()
    edc = 0
    lut = _edc_lut
    for b in data:
        edc = (edc >> 8) ^ lut[(edc ^ b) & 0xFF]
    return edc


def _ecc_block(src, major_count, minor_count, major_mult, minor_inc):
    """Reed-Solomon P/Q (da ecm/cdrtools, identico a mkpsxiso)."""
    f, bl = _ecc_f, _ecc_b
    size = major_count * minor_count
    dest = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _ in range(minor_count):
            t = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_a ^= t
            ecc_b ^= t
            ecc_a = f[ecc_a]
        ecc_a = bl[f[ecc_a] ^ ecc_b]
        dest[major] = ecc_a
        dest[major + major_count] = ecc_a ^ ecc_b
    return dest


def build_sector(old_raw, user2048):
    """Nuovo settore raw 2352 con lo user data sostituito: sync+header+subheader
    dal settore esistente, EDC/ECC form1 ricalcolati (header azzerato nel
    calcolo ECC, regola mode2)."""
    _init_luts()
    sub = old_raw[16:24]
    if sub[2] & 0x20:
        raise ValueError("settore form2: non patchabile come dati")
    edc = _edc(sub + user2048)
    body = b"\0\0\0\0" + sub + user2048 + struct.pack("<I", edc)   # 2064
    p = _ecc_block(body, 86, 24, 2, 86)                            # 172
    q = _ecc_block(bytes(body) + bytes(p), 52, 43, 86, 88)         # 104
    return old_raw[:16] + body[4:] + bytes(p) + bytes(q)


# ------------------------------------------------------------------ ISO9660 --
def _user(f, lba, count=1):
    """User data (2048B/settore) di `count` settori a partire da lba."""
    out = []
    for k in range(count):
        f.seek((lba + k) * RAW + HDR)
        out.append(f.read(DATA))
    return b"".join(out)


def locate(f, name):
    """(lba, size) del file `name` (root directory; 'DIR/NOME' per le subdir)."""
    pvd = _user(f, 16)
    if pvd[1:6] != b"CD001":
        raise ValueError("PVD non trovato: non è una ISO 2352?")
    lba, size = struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0]
    for part in name.upper().split("/"):
        d = _user(f, lba, (size + DATA - 1) // DATA)
        found = None
        o = 0
        while o < len(d):
            ln = d[o]
            if ln == 0:                       # fine settore: salta al prossimo
                o = (o // DATA + 1) * DATA
                continue
            nl = d[o + 32]
            nm = d[o + 33:o + 33 + nl].decode("latin-1").split(";")[0]
            if nm == part:
                found = (struct.unpack_from("<I", d, o + 2)[0],
                         struct.unpack_from("<I", d, o + 10)[0])
                break
            o += ln
        if not found:
            raise FileNotFoundError(f"{part} non trovato nella ISO")
        lba, size = found
    return lba, size


# -------------------------------------------------------------------- patch --
def patch_file(iso_path, name, new_data, log=print):
    """Riscrive nel posto del file `name` i soli settori il cui user data
    differisce da new_data. Richiede size identica (layout invariato).
    Ritorna il numero di settori riscritti."""
    f = open(iso_path, "r+b")
    try:
        lba, size = locate(f, name)
        if len(new_data) != size:
            raise ValueError(
                f"{name}: size cambiata ({len(new_data)} vs {size} nella ISO): "
                "serve il rebuild completo")
        n_sect = (size + DATA - 1) // DATA
        changed = 0
        BLK = 1024                                    # settori per blocco letto
        for s0 in range(0, n_sect, BLK):
            n = min(BLK, n_sect - s0)
            f.seek((lba + s0) * RAW)
            raw = f.read(n * RAW)
            for k in range(n):
                s = s0 + k
                user = new_data[s * DATA:(s + 1) * DATA].ljust(DATA, b"\0")
                if raw[k * RAW + HDR:k * RAW + HDR + DATA] == user:
                    continue
                sec = build_sector(raw[k * RAW:(k + 1) * RAW], user)
                f.seek((lba + s) * RAW)
                f.write(sec)
                changed += 1
        f.flush()
        return changed
    finally:
        f.close()


def selftest(iso_path, name="BUDDIES.DAT", step=997):
    """Ricalcola EDC/ECC di settori esistenti del file e confronta col raw
    originale: se combaciano al byte, l'encoder è identico a mkpsxiso."""
    f = open(iso_path, "rb")
    lba, size = locate(f, name)
    n_sect = (size + DATA - 1) // DATA
    tested = bad = 0
    for s in range(0, n_sect, step):
        f.seek((lba + s) * RAW)
        raw = f.read(RAW)
        rebuilt = build_sector(raw, raw[HDR:HDR + DATA])
        tested += 1
        if rebuilt != raw:
            bad += 1
            print(f"  MISMATCH al settore {s} (lba {lba + s})")
    f.close()
    print(f"selftest {name}: {tested} settori ricodificati, {bad} mismatch")
    return bad == 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, iso = sys.argv[1], sys.argv[2]
    if cmd == "locate":
        with open(iso, "rb") as f:
            lba, size = locate(f, sys.argv[3])
        print(f"{sys.argv[3]}: lba={lba} size={size} ({(size + DATA - 1) // DATA} settori)")
    elif cmd == "patch":
        data = open(sys.argv[4], "rb").read()
        n = patch_file(iso, sys.argv[3], data)
        print(f"{sys.argv[3]}: {n} settori riscritti")
    elif cmd == "selftest":
        ok = selftest(iso, sys.argv[3] if len(sys.argv) > 3 else "BUDDIES.DAT")
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
