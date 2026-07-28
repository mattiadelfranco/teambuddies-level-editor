#!/usr/bin/env python3
"""
Team Buddies - Mette la mappa di un livello in un ALTRO slot del DAT.

Copia i 7 file del livello sorgente (da mods/<src> se esiste, altrimenti da
bind/<src>) in mods/<dst>, rinominandoli per POSIZIONE secondo la manifest
dello slot di destinazione: il gioco accede alle entry del BIND per indice
(0=TIM 1=TIM.BND 2=MDL.BND 3=PLD 4=PND 5=CL2 6=PTH), i nomi sono solo etichette.

A cosa serve: il numero di team, la missione e il briefing sono legati allo
SLOT (config per-missione, slot = entry-512), non al file mappa. Es.: una mappa
con 4 record s0 + 4 basi messa in uno slot 4-team (QUARRY, ICESCREAM...) gioca
a 4 squadre senza toccare nessuna config.

Uso: python3 tools/tb_swap_slot.py <src_entry> <dst_entry>     (es. 0512 0518)
"""
import csv, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIND = os.path.join(ROOT, "teambudd/dat_estratto/bind")
MODS = os.path.join(ROOT, "teambudd/mods")
MANIFEST = os.path.join(ROOT, "teambudd/dat_estratto/manifest.tsv")


def inner_names(idx):
    out = []
    with open(MANIFEST) as m:
        for row in csv.DictReader(m, delimiter="\t"):
            if row["type"] == "BIND" and int(row["dat_index"]) == idx:
                out.append(row["inner_name"].replace("\\", "_").lstrip("_").replace("..", "__"))
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    src_dir = os.path.join(MODS, src)
    if not os.path.isdir(src_dir):
        src_dir = os.path.join(BIND, src)
    src_names = inner_names(int(src))
    dst_names = inner_names(int(dst))
    if len(src_names) != len(dst_names):
        sys.exit(f"slot incompatibili: {len(src_names)} vs {len(dst_names)} file interni")
    dst_dir = os.path.join(MODS, dst)
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir)
    for sn, dn in zip(src_names, dst_names):
        shutil.copyfile(os.path.join(src_dir, sn), os.path.join(dst_dir, dn))
        print(f"  {sn} -> {dn}")
    print(f"fatto: {src_dir} -> {dst_dir} ({len(src_names)} file)")


if __name__ == "__main__":
    main()
