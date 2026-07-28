#!/usr/bin/env python3
"""
Team Buddies (PSX) - Renderizza il terreno di un livello in PNG.

Usa la TIM del livello (atlas 4bpp, celle 64x64, N CLUT da 16 colori) e i
record per-tile del PND:
  [u16 U][u8 V][4 x s8 delta angoli quad][u8 clut] + 4 colori vertice + u32 flag
U/V puntano all'angolo UV del vertice NW del tile; i delta (in {0,+63,-63})
danno gli angoli NE e SW -> le 8 orientazioni (rot/mirror) della cella.

Uso: python3 tools/render_ground.py <cartella_livello> <out.png> [px_per_tile]
"""
import struct, sys, os, glob
import numpy as np
from PIL import Image


def load_tim(path):
    d = open(path, "rb").read()
    magic, typ = struct.unpack_from("<II", d, 0)
    assert magic == 0x10 and (typ & 8), f"TIM non 4bpp: {path}"
    clen, _, _, cw, ch = struct.unpack_from("<IHHHH", d, 8)
    cluts = np.zeros((ch, cw, 4), dtype=np.uint8)
    for r in range(ch):
        for c in range(cw):
            v, = struct.unpack_from("<H", d, 20 + (r * cw + c) * 2)
            cluts[r, c] = ((v & 31) * 8, ((v >> 5) & 31) * 8,
                           ((v >> 10) & 31) * 8, 0 if v == 0 else 255)
    o = 8 + clen
    ilen, _, _, iw, ih = struct.unpack_from("<IHHHH", d, o)
    raw = np.frombuffer(d, dtype=np.uint8,
                        count=iw * 2 * ih, offset=o + 12).reshape(ih, iw * 2)
    idx = np.zeros((ih, iw * 4), dtype=np.uint8)
    idx[:, 0::2] = raw & 15
    idx[:, 1::2] = raw >> 4
    return cluts, idx


def load_tiles(pnd_path):
    d = open(pnd_path, "rb").read()
    n_names, n_inst, _, _ = struct.unpack_from("<4H", d, 4)

    def rec_ok(p):
        if p + 28 > len(d):
            return False
        u, = struct.unpack_from("<H", d, p)
        v = d[p + 2]
        deltas = struct.unpack_from("<4b", d, p + 3)
        clut = d[p + 7]
        # NB niente tetto stretto sulla clut: i livelli grandi (COUNTRYVILE,
        # BOSSANOVA...) arrivano a ~140 - il vecchio limite 120 lasciava
        # buchi neri; il range vero viene controllato in render() sul TIM
        return (u < 4096 and (u % 64) in (0, 63) and (v % 64) in (0, 63)
                and all(x in (0, 63, -63) for x in deltas) and clut < 250)

    # POSIZIONE ESATTA (layout sequenziale del parser del motore, lo stesso
    # usato da editor_server._tiles_layout, verificato in gioco con le
    # pedane): nomi, istanze, [u16 count lista extra + count*20B],
    # heightmap 65x65 s16, poi l'array tile.
    # Il vecchio auto-rilevamento a run di record validi partiva quasi
    # sempre 2 record in anticipo (la coda della heightmap valida per caso):
    # mappa slittata di 2 tile con le colonne di destra "wrappate" a
    # sinistra una riga sotto.
    off_extra = 12 + n_names * 32 + n_inst * 20
    extra_cnt, = struct.unpack_from("<H", d, off_extra)
    o = None
    if extra_cnt < 2000:
        cand = off_extra + 2 + extra_cnt * 20 + 65 * 65 * 2
        if sum(1 for k in range(20) if rec_ok(cand + k * 28)) >= 16:
            o = cand
    if o is None:
        # fallback: run di record validi + coda animazioni sana a +131072
        def anim_ok(p):
            a = p + 131072
            if a + 2 > len(d):
                return False
            n1, = struct.unpack_from("<h", d, a)
            if not 0 <= n1 < 2000:
                return False
            o2 = a + 2 + n1 * 12
            if o2 + 2 > len(d):
                return False
            n2, = struct.unpack_from("<H", d, o2)
            if n2 > 2000 or o2 + 2 + n2 * 16 > len(d) + 4:
                return False
            return all(struct.unpack_from("<H", d, o2 + 2 + i * 16)[0] < 4096
                       for i in range(min(n2, 8)))
        base = 12 + n_names * 32 + n_inst * 20 + 65 * 65 * 2
        for cand in range(base - 512, base + 12000):
            if (sum(1 for k in range(20) if rec_ok(cand + k * 28)) >= 18
                    and anim_ok(cand)):
                o = cand
                break
    if o is None:
        raise ValueError("array tile non trovato")
    tiles = []
    for i in range(4096):
        u, = struct.unpack_from("<H", d, o)
        v = d[o + 2]
        deltas = struct.unpack_from("<4b", d, o + 3)
        clut = d[o + 7]
        colors = struct.unpack_from("<16B", d, o + 8)
        flags, = struct.unpack_from("<I", d, o + 24)
        if rec_ok(o):
            tiles.append((u, v, deltas, clut, colors, flags))
        else:
            tiles.append(None)   # tile non standard: lascialo vuoto
        o += 28
    return tiles


def orient_block(block, u_edge, v_edge, deltas):
    """block: cella 64x64 gia' ritagliata. Ricava la trasposizione dal fatto
    che UV0 e' il vertice NW e i delta danno NE (d0,d1) e SW (d2,d3)."""
    du1, dv1, du2, dv2 = deltas
    # vettore NE nel texture space: (du1, dv1); vettore SW: (du2, dv2)
    # costruiamo la mappa affine: dest (x,y) in [0,1]^2 -> src uv
    # src = uv0 + x*(du1,dv1) + y*(du2,dv2)
    # con uv0 relativo alla cella: 0 o 63 su ciascun asse
    u0 = 0 if u_edge == 0 else 63
    v0 = 0 if v_edge == 0 else 63
    ys, xs = np.mgrid[0:64, 0:64]
    su = u0 + (xs * du1 + ys * du2) / 63.0
    sv = v0 + (xs * dv1 + ys * dv2) / 63.0
    su = np.clip(np.rint(su), 0, 63).astype(np.int32)
    sv = np.clip(np.rint(sv), 0, 63).astype(np.int32)
    # l'angolo UV base e' il vertice a SUD, non a nord: senza questo flip ogni
    # sprite risulta specchiato (segnalato dall'utente sul gioco reale).
    # Prova assoluta: le frecce delle pedane devono puntare TUTTE verso il
    # centro pedana — col flip verticale tornano coerenti.
    return block[sv, su][::-1, :]


def render(folder, out, px=16):
    pnd = glob.glob(os.path.join(folder, "*.PND"))[0]
    tim = [t for t in glob.glob(os.path.join(folder, "*.TIM"))
           if os.path.basename(t).split(".")[0] not in ("TIM",)][0]
    cluts, idx = load_tim(tim)
    tiles = load_tiles(pnd)
    H, W = idx.shape
    img = np.zeros((64 * px, 64 * px, 4), dtype=np.uint8)
    for i, t in enumerate(tiles):
        if t is None:
            continue
        u, v, deltas, clut, colors, flags = t
        r, c = divmod(i, 64)
        cu = (u // 64) * 64
        cv = (v // 64) * 64
        if cu + 64 > W or cv + 64 > H or clut >= len(cluts):
            continue
        block = idx[cv:cv + 64, cu:cu + 64]
        ob = orient_block(block, u - cu, v - cv, deltas)
        rgba = cluts[clut][ob]
        # modulazione colori vertice (media dei 4, PSX modula 128=neutro)
        mr = sum(colors[0::4]) / 4 / 128
        mg = sum(colors[1::4]) / 4 / 128
        mb = sum(colors[2::4]) / 4 / 128
        if (mr, mg, mb) != (1.0, 1.0, 1.0):
            rgba = rgba.astype(np.float32)
            rgba[..., 0] *= mr; rgba[..., 1] *= mg; rgba[..., 2] *= mb
            rgba = np.clip(rgba, 0, 255).astype(np.uint8)
        cell = np.array(Image.fromarray(rgba).resize((px, px), Image.BOX))
        img[r * px:(r + 1) * px, c * px:(c + 1) * px] = cell
    Image.fromarray(img).save(out)
    print(f"salvato {out}")


if __name__ == "__main__":
    folder, out = sys.argv[1], sys.argv[2]
    px = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    render(folder, out, px)
