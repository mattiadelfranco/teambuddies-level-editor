#!/usr/bin/env python3
"""
Team Buddies (PSX) - Repack di una entry BIND dentro BUDDIES.DAT

Modalita' predefinita: IN-PLACE. Il BIND ricostruito viene riscritto nel suo
settore originale, senza toccare la tabella. Richiede che il nuovo contenuto
stia nello slot esistente (spazio fino all'entry successiva). E' la modalita'
verificata funzionante in gioco: il gioco assume che i dati del livello siano
nella posizione originale.

Con --append invece il BIND viene appeso in coda al DAT e viene aggiornato il
settore nella tabella (NB: testato NON funzionante per i livelli - il gioco
si blocca al caricamento).

Uso:
  python3 tb_repack.py [--append] <BUDDIES.DAT> <manifest.tsv> <dat_index> <cartella_bind>

  <cartella_bind> e' la cartella bind/NNNN prodotta da tb_extract.py,
  con i file eventualmente modificati (i nomi devono restare gli stessi).

Al primo utilizzo viene creata una copia BUDDIES.DAT.orig accanto al DAT.
"""
import struct, os, sys, shutil, csv

SECTOR = 2048


def main():
    args = sys.argv[1:]
    append = "--append" in args
    if append:
        args.remove("--append")
    dat_path, manifest_path, idx_s, bind_dir = args[:4]
    idx = int(idx_s)

    # ordine e nomi originali delle entry interne dal manifest,
    # piu' settori di tutte le entry per calcolare lo slot disponibile
    inner_names = []
    sectors = {}
    with open(manifest_path) as m:
        for row in csv.DictReader(m, delimiter="\t"):
            i = int(row["dat_index"])
            sectors[i] = int(row["sector"])
            if i == idx and row["type"] == "BIND":
                inner_names.append(row["inner_name"])
    if not inner_names:
        sys.exit(f"entry {idx} non trovata nel manifest o non e' un BIND")

    # ricostruisci il BIND
    blobs = []
    for name in inner_names:
        clean = name.replace("\\", "_").lstrip("_").replace("..", "__")
        path = os.path.join(bind_dir, clean)
        with open(path, "rb") as f:
            blobs.append(f.read())

    n = len(inner_names)
    header = b"BIND" + struct.pack("<I", n)
    table = b""
    data = b""
    data_start = 8 + n * 40
    for i, (name, blob) in enumerate(zip(inner_names, blobs)):
        off = data_start + len(data)
        raw_name = name.encode("ascii")[:31].ljust(32, b"\0")
        table += raw_name + struct.pack("<II", off, len(blob))
        data += blob
        # il formato originale allinea a 4 byte e lascia un gap di 4 byte
        # tra un file e il successivo
        if i < n - 1:
            if len(data) % 4:
                data += b"\0" * (4 - len(data) % 4)
            data += b"\0" * 4
    bind = header + table + data
    if len(bind) % SECTOR:
        bind += b"\0" * (SECTOR - len(bind) % SECTOR)

    # backup una tantum
    orig = dat_path + ".orig"
    if not os.path.exists(orig):
        shutil.copy2(dat_path, orig)
        print(f"backup creato: {orig}")

    if append:
        # appendi in coda e aggiorna il settore nella tabella
        with open(dat_path, "r+b") as f:
            f.seek(0, 2)
            end = f.tell()
            if end % SECTOR:
                f.write(b"\0" * (SECTOR - end % SECTOR))
                end = f.tell()
            new_sector = end // SECTOR
            f.write(bind)
            # tabella: header 8 byte, entry da 8 byte (size u32, sector u32)
            f.seek(8 + idx * 8 + 4)
            f.write(struct.pack("<I", new_sector))
        print(f"entry {idx}: nuovo BIND ({len(bind)} byte) APPESO al settore {new_sector}")
    else:
        # in-place: riscrivi nel settore originale, tabella intatta
        sector = sectors[idx]
        next_sectors = [s for s in sectors.values() if s > sector]
        slot = (min(next_sectors) - sector) * SECTOR if next_sectors \
            else os.path.getsize(dat_path) - sector * SECTOR
        if len(bind) > slot:
            sys.exit(f"non entra: nuovo BIND {len(bind)} byte, slot {slot} byte "
                     f"(riduci i contenuti o scegli un'altra entry)")
        with open(dat_path, "r+b") as f:
            f.seek(sector * SECTOR)
            f.write(bind)
        print(f"entry {idx}: BIND riscritto in-place al settore {sector} "
              f"({len(bind)}/{slot} byte dello slot)")
    print("ora ricostruisci l'ISO con mkpsxiso.")


if __name__ == "__main__":
    main()
