#!/usr/bin/env python3
"""
Team Buddies (PSX) - Estrattore di BUDDIES.DAT

Formato BUDDIES.DAT:
  header:  "BD" (2 byte) + numero entry (u16) + sconosciuto (u32)
  tabella: per ogni entry, dimensione (u32) + settore di inizio (u32), settore = 2048 byte
  NB: per i contenitori BIND grandi (es. livelli) il campo dimensione della
      tabella non è affidabile; l'estensione reale si ricava dall'header BIND.

Formato BIND (contenitore annidato):
  header:  "BIND" + numero entry (u32)
  entry:   nome file (32 byte, zero-terminato) + offset (u32) + dimensione (u32)
           offset relativo all'inizio del BIND.

Uso:
  python3 tb_extract.py <BUDDIES.DAT> <cartella_output>

Output:
  <out>/raw/NNNN.bin        - ogni entry del DAT com'e' (estensione reale)
  <out>/bind/NNNN/<nomi>    - contenuto dei BIND spacchettato con i nomi originali
  <out>/manifest.tsv        - indice completo per il repack
"""
import struct, os, sys

SECTOR = 2048


def read_dat_table(f):
    head = f.read(8)
    assert head[:2] == b"BD", "non sembra un BUDDIES.DAT"
    count = struct.unpack_from("<H", head, 2)[0]
    table = f.read(count * 8)
    return [struct.unpack_from("<II", table, i * 8) for i in range(count)]


def parse_bind_header(f, sector):
    """Ritorna la lista (nome, offset, dimensione) oppure None se non e' un BIND valido."""
    f.seek(sector * SECTOR)
    hdr = f.read(8)
    if hdr[:4] != b"BIND":
        return None
    n = struct.unpack_from("<I", hdr, 4)[0]
    if n == 0 or n > 10000:
        return None
    tbl = f.read(n * 40)
    if len(tbl) < n * 40:
        return None
    entries = []
    for i in range(n):
        name = tbl[i * 40:i * 40 + 32].split(b"\0")[0].decode("ascii", "replace")
        off, size = struct.unpack_from("<II", tbl, i * 40 + 32)
        if not name or off < 8 or size > 50_000_000:
            return None
        entries.append((name, off, size))
    return entries


def main():
    dat_path, out = sys.argv[1], sys.argv[2]
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    f = open(dat_path, "rb")
    entries = read_dat_table(f)
    manifest = open(os.path.join(out, "manifest.tsv"), "w")
    manifest.write("dat_index\ttable_size\tsector\treal_size\ttype\tinner_name\tinner_size\n")

    for idx, (tsize, sector) in enumerate(entries):
        inner = parse_bind_header(f, sector)
        if inner:
            real = max(o + s for _, o, s in inner)
            kind = "BIND"
        else:
            real = tsize
            kind = "RAW"
        f.seek(sector * SECTOR)
        blob = f.read(real)
        with open(os.path.join(out, "raw", f"{idx:04d}.bin"), "wb") as o:
            o.write(blob)
        if inner:
            bdir = os.path.join(out, "bind", f"{idx:04d}")
            os.makedirs(bdir, exist_ok=True)
            for name, foff, fsize in inner:
                clean = name.replace("\\", "_").lstrip("_").replace("..", "__")
                with open(os.path.join(bdir, clean), "wb") as o:
                    o.write(blob[foff:foff + fsize])
                manifest.write(f"{idx}\t{tsize}\t{sector}\t{real}\tBIND\t{name}\t{fsize}\n")
        else:
            manifest.write(f"{idx}\t{tsize}\t{sector}\t{real}\tRAW\t\t{real}\n")

    manifest.close()
    f.close()
    print(f"estratte {len(entries)} entry in {out}")


if __name__ == "__main__":
    main()
