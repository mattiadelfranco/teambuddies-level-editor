#!/usr/bin/env python3
"""
Team Buddies - Rebuild completo di BUDDIES.DAT.

Ricolloca TUTTE le entry in sequenza (ordine originale per settore) dando a
ciascuna lo spazio necessario: rimuove il limite dello slot per i livelli
modificati. Riproduce le due semantiche osservate della colonna dimensioni:
  - entry normali: size = dimensione reale
  - entry "livello": size[i] = estensione reale dell'entry precedente + 4
    (stranezza del formato originale, riprodotta fedelmente)

Uso: python3 tools/tb_rebuild.py <BUDDIES.DAT.orig> <mods_dir> <out.DAT> <manifest.tsv>
"""
import struct, os, sys, glob

SECTOR = 2048


def parse_bind_extent(f, sector):
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
    ext = 0
    for i in range(n):
        name = tbl[i*40:i*40+32].split(b"\0")[0]
        off, size = struct.unpack_from("<II", tbl, i*40 + 32)
        if not name or off < 8 or size > 50_000_000:
            return None
        ext = max(ext, off + size)
    return ext


def pack_bind_from_folder(folder, inner_names):
    blobs = []
    for name in inner_names:
        clean = name.replace("\\", "_").lstrip("_").replace("..", "__")
        blobs.append(open(os.path.join(folder, clean), "rb").read())
    n = len(inner_names)
    header = b"BIND" + struct.pack("<I", n)
    table = b""
    data = b""
    data_start = 8 + n * 40
    for i, (name, blob) in enumerate(zip(inner_names, blobs)):
        off = data_start + len(data)
        table += name.encode("ascii")[:31].ljust(32, b"\0") + struct.pack("<II", off, len(blob))
        data += blob
        if i < n - 1:
            if len(data) % 4:
                data += b"\0" * (4 - len(data) % 4)
            data += b"\0" * 4
    return header + table + data


def main():
    src, mods_dir, out_path, manifest = sys.argv[1:5]

    import csv, shutil
    inner = {}
    with open(manifest) as m:
        for row in csv.DictReader(m, delimiter="\t"):
            if row["type"] == "BIND":
                inner.setdefault(int(row["dat_index"]), []).append(row["inner_name"])

    f = open(src, "rb")
    head = f.read(8)
    count = struct.unpack_from("<H", head, 2)[0]
    table = f.read(count * 8)
    entries = [struct.unpack_from("<II", table, i*8) for i in range(count)]

    # estensioni reali originali
    old_real = {}
    for i, (size, sector) in enumerate(entries):
        if sector == 0 and i == count - 1:   # sentinella finale
            continue
        ext = parse_bind_extent(f, sector)
        old_real[i] = ext if ext is not None else size

    # slot disponibili e successore in ordine di settore
    order = sorted((sec, i) for i, (sz, sec) in enumerate(entries) if i in old_real)
    next_in_order = {order[k][1]: order[k+1][1] for k in range(len(order)-1)}
    slot = {}
    for k in range(len(order)):
        i = order[k][1]
        slot[i] = ((order[k+1][0] - order[k][0]) * SECTOR) if k + 1 < len(order) else None

    shutil.copyfile(src, out_path)
    out = open(out_path, "r+b")

    new_real = dict(old_real)
    new_sector = {i: entries[i][1] for i in old_real}
    end = os.path.getsize(out_path)
    if end % SECTOR:
        out.seek(0, 2)
        out.write(b"\0" * (SECTOR - end % SECTOR))
        end = out.tell()

    changed = []
    mods = sorted(glob.glob(os.path.join(mods_dir, "*"))) if os.path.isdir(mods_dir) else []
    for mod in mods:
        name = os.path.basename(mod)
        if os.path.isdir(mod) and name.isdigit():
            i = int(name)
            blob = pack_bind_from_folder(mod, inner[i])
        elif os.path.isfile(mod) and name.endswith(".bin") and name[:-4].isdigit():
            i = int(name[:-4])          # entry RAW (non-BIND), es. mods/0956.bin
            blob = open(mod, "rb").read()
        else:
            continue
        new_real[i] = len(blob)
        if slot.get(i) and len(blob) <= slot[i]:
            out.seek(entries[i][1] * SECTOR)
            out.write(blob)
            print(f"[{i:04d}] in-place ({len(blob)}/{slot[i]} byte)")
        else:
            new_sector[i] = end // SECTOR
            out.seek(end)
            out.write(blob)
            end = out.tell()
            if end % SECTOR:
                out.write(b"\0" * (SECTOR - end % SECTOR))
                end = out.tell()
            print(f"[{i:04d}] ricollocato in coda al settore {new_sector[i]} ({len(blob)} byte)")
        changed.append(i)

    # tabella: settore + colonna dimensioni (pattern proprio e del successore)
    for i in changed:
        out.seek(8 + i * 8 + 4)
        out.write(struct.pack("<I", new_sector[i]))
        if entries[i][0] == old_real[i]:
            out.seek(8 + i * 8)
            out.write(struct.pack("<I", new_real[i]))
        j = next_in_order.get(i)
        if j is not None and entries[j][0] == old_real[i] + 4:
            out.seek(8 + j * 8)
            out.write(struct.pack("<I", new_real[i] + 4))
    out.close()
    print(f"fatto: {len(changed)} livelli applicati, out={os.path.getsize(out_path)} byte")


if __name__ == "__main__":
    main()
