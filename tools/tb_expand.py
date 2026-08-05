#!/usr/bin/env python3
"""
Team Buddies - BUDDIES.DAT "dev": slot espansi per build con savestate stabili.

Ricolloca ogni entry del DAT lasciando SLACK di settori dopo il suo slot
vanilla (default: +64 settori per i livelli 512-559, +8 per tutto il resto;
le ~415 entry con size di tabella SFASATA oltre lo slot fisico ricevono
slack extra pari al deficit, così anche il loro file estratto "gonfio" di
coda spuria sta sempre nello slot). Con gli slot espansi il repack delle mod
resta praticamente sempre IN-PLACE: la tabella del DAT e il layout della ISO
non cambiano più tra un build e l'altro, quindi i savestate dell'emulatore
restano validi.

Ogni slot viene copiato INTERO e lo slack viene riempito con la CONTINUAZIONE
dei byte vanilla che seguivano l'entry (non zeri): una lettura oltre lo slot
fisico trova gli stessi byte del vanilla. Della tabella si aggiorna solo la
colonna settore: la colonna dimensioni (semantica sfasata) e la sentinella
finale restano al byte come nel vanilla. Deterministico: stessi parametri ->
stesso file.

Va rigenerato (e il savestate rifatto) solo se si cambia lo slack.

Uso:  python3 tools/tb_expand.py [--level-slack 64] [--slack 2]
      (input  teambudd/estratto/BUDDIES.DAT.orig
       output teambudd/estratto/BUDDIES.DAT.dev)
"""
import os, struct, sys

SECTOR = 2048
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "teambudd/estratto/BUDDIES.DAT.orig")
OUT = os.path.join(ROOT, "teambudd/estratto/BUDDIES.DAT.dev")
LEVELS = range(512, 560)


def parse_table(d):
    count = struct.unpack_from("<H", d, 2)[0]
    entries = [struct.unpack_from("<II", d, 8 + i * 8) for i in range(count)]
    return count, entries


def expand(src=SRC, out_path=OUT, level_slack=64, slack=8, log=print):
    src_data = open(src, "rb").read()
    count, entries = parse_table(src_data)
    n_sect = len(src_data) // SECTOR

    real = sorted((sec, i) for i, (sz, sec) in enumerate(entries)
                  if not (sec == 0 and i == count - 1))
    first = real[0][0]

    # slot vanilla (interi, settori) e nuove posizioni con slack; le entry con
    # size di tabella oltre lo slot fisico ricevono slack extra a compensare
    new_sector = {}
    cur = first
    plan = []
    deficit_n = 0
    for k, (sec, i) in enumerate(real):
        end = real[k + 1][0] if k + 1 < len(real) else n_sect
        n = end - sec
        tab_sect = (entries[i][0] + SECTOR - 1) // SECTOR
        comp = max(0, tab_sect - n)
        deficit_n += comp > 0
        sl = (level_slack if i in LEVELS else slack) + comp
        new_sector[i] = cur
        plan.append((i, sec, n, n + sl))
        cur += n + sl

    out = bytearray(cur * SECTOR)
    out[:first * SECTOR] = src_data[:first * SECTOR]        # header+tabella+gap
    for i, sec, n, tot in plan:
        dst = new_sector[i] * SECTOR
        # slot + coda vanilla a riempire lo slack (oltre EOF restano zeri)
        chunk = src_data[sec * SECTOR:(sec + tot) * SECTOR]
        out[dst:dst + len(chunk)] = chunk
        struct.pack_into("<I", out, 8 + i * 8 + 4, new_sector[i])

    open(out_path, "wb").write(out)

    # verifica: slot+coda al byte + colonna size e sentinella intatte
    chk = open(out_path, "rb").read()
    for i, sec, n, tot in plan:
        a = src_data[sec * SECTOR:(sec + tot) * SECTOR]
        b = chk[new_sector[i] * SECTOR:new_sector[i] * SECTOR + len(a)]
        assert a == b, f"verify: slot {i} non identico"
        assert struct.unpack_from("<I", chk, 8 + i * 8)[0] == entries[i][0], \
            f"verify: size entry {i} cambiata"
    assert struct.unpack_from("<II", chk, 8 + (count - 1) * 8) == entries[count - 1], \
        "verify: sentinella cambiata"

    log(f"BUDDIES.DAT.dev: {len(out)} byte ({len(out) // SECTOR} settori, "
        f"+{(len(out) - len(src_data)) // 1024} KB di slack), "
        f"slot livelli +{level_slack * 2}KB, altri +{slack * 2}KB, "
        f"{deficit_n} entry compensate per size sfasata — verify ok")
    return out_path


def main():
    args = sys.argv[1:]
    lv, gn = 64, 8
    if "--level-slack" in args:
        lv = int(args[args.index("--level-slack") + 1])
    if "--slack" in args:
        gn = int(args[args.index("--slack") + 1])
    expand(level_slack=lv, slack=gn)


if __name__ == "__main__":
    main()
